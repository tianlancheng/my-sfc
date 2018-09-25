﻿# flake8: noqa
#
# Copyright (c) 2015 Cisco Systems, Inc. and others. All rights reserved.
#
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License v1.0 which accompanies this distribution,
# and is available at http://www.eclipse.org/legal/epl-v10.html


import sys
import json
import socket
import logging
import requests
import ipaddress
import threading
import subprocess
import queue
# -*- coding: utf-8 -*-：
from time import sleep
import copy

from ..nsh.encode import build_nsh_eth_header, build_nsh_header
from ..common.sfc_globals import sfc_globals
from ..nsh.common import (VXLANGPE, VXLAN, GREHEADER, BASEHEADER, CONTEXTHEADER, ETHHEADER,
                          VXLAN_NEXT_PROTO_NSH)
from _socket import IPV6_V6ONLY


"""
NFQ classifier - manage everything related with NetFilterQueue: from starting
packet listeners to creation of appropriate ip(6)tables rules and marking
received packets accordingly.
"""


# NOTE: naming conventions
# nfq -> NetFilterQueue
# nsh -> Network Service Headers
# fwd -> forwarder/forwarding
# acl -> access list
# ace -> access list entry
# `rule(s)` and `chain(s)` can be used interchangeably in ip(6)tables context


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# silence `requests` module logging
requests_logger = logging.getLogger('requests')
requests_logger.setLevel(logging.WARNING)


#: constants
IPV4 = 4
IPv6 = 6
NFQ_NUMBER = 2
NFQ_AVAILABLE = False

in_pckt_queue = queue.Queue()

#: NetfilterQueue is available only on Linux as it cooperates with ip(6)tables
if sys.platform.startswith('linux'):
    try:
        from netfilterqueue import NetfilterQueue
        NFQ_AVAILABLE = True
    except ImportError:
        pass


#: ACE items to ip(6)tables flags/types mapping
ace_2_iptables = {'source-ips': {'flag': '-s',
                                 'type': ('source-ipv4-address',
                                          'source-ipv6-address')
                                 },
                  'destination-ips': {'flag': '-d',
                                      'type': ('destination-ipv4-address',
                                               'destination-ipv6-address')
                                      },
                  'protocols': {'flag': '-p',
                                'type': {6: 'tcp',
                                         17: 'udp'}
                                },
                  'ports': {'source-port-range': '--sport',
                            'destination-port-range': '--dport'}
                  }

#: IP version to NSH next protocol mapping
ipv_2_next_protocol = {4: 0x1,      # IPv4
                       6: 0x2,      # IPv6
                       10: 0x3}     # Ethernet


def run_cmd(cmd):
    """
    Execute a BASH command

    :param cmd: command to be executed
    :type cmd: list

    """
    cmd = [str(cmd_part) for cmd_part in cmd]
    logger.debug('Executing command: %s', ' '.join(cmd))

    try:
        process = subprocess.Popen(cmd,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)

        _, err = process.communicate()

        if process.returncode != 0:
            err = err.strip()
            logger.exception(err.decode())

    except OSError:
        logger.exception('Command execution failed')


def run_cmd_as_root(cmd):
    """
    Execute a BASH command with root privileges

    :param cmd: command to be executed
    :type cmd: list

    """
    cmd.insert(0, 'sudo')
    run_cmd(cmd)


def run_iptables_cmd(arguments, ipv):
    """
    Execute ip(6)tables command with given arguments

    :param arguments: iptables arguments
    :type arguments: list
    :param ipv: IP version
    :type ipv: tuple

    """
    iptables = 'iptables'
    ip6tables = 'ip6tables'

    if (IPV4 in ipv) and (IPv6 in ipv):
        ip_tables = (iptables, ip6tables)
    elif IPV4 in ipv:
        ip_tables = (iptables,)
    elif IPv6 in ipv:
        ip_tables = (ip6tables,)
    else:
        raise ValueError('Unknown IP address version "%s"', ipv)

    for iptables_cmd in ip_tables:
        base_iptables_cmd = [iptables_cmd, '-t', 'raw']
        base_iptables_cmd.extend(arguments)

        run_cmd_as_root(base_iptables_cmd)


class Singleton(type):
    instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls.instances:
            singleton_cls = super(Singleton, cls).__call__(*args, **kwargs)
            cls.instances[cls] = singleton_cls

        return cls.instances[cls]


class NfqClassifier(metaclass=Singleton):
    def __init__(self):
        """
        NFQ classifier

        ASSUMED:
        - RSP(s) already exists when an ACL referencing it is obtained

        How it works:
        1. sfc_agent receives an ACL and passes it for processing
        2. the RSP (its SFF locator) referenced by ACL is requested from ODL
        3. if the RSP exists in the ODL iptables rules for it are applied

        After this process is over, every packet successfully matched to an
        iptables rule (i.e. successfully classified) will be NSH encapsulated
        and forwarded to a related SFF, which knows how to traverse the RSP.

        Rules are created using appropriate iptables command. If the ACE rule
        is MAC address related both iptables and ip6tabeles rules re issued.
        If ACE rule is IPv4 address related, only iptables rules are issued,
        same for IPv6.

        ACL            RULES FOR
        ----------------------------------
        MAC            iptables, ip6tables
        PORT           iptables, ip6tables
        IPv4           iptables
        IPv6           ip6tables

        Information regarding already registered RSP(s) are stored in an
        internal data-store, which is represented as a dictionary:

        {rsp_id: {'name': <rsp_name>,
                  'chains': {'chain_name': (<ipv>,),
                             ...
                             },
                  'sff': {'ip': <ip>,
                          'port': <port>,
                          'starting-index': <starting-index>,
                          'transport-type': <transport-type>
                          },
                  },
        ...
        }

        Where:
            - name: RSP name
            - chains: dict of iptables rules/chains related to the RSP
            - SFF:
                - ip: SFF IP
                - port: SFF port
                - starting-index: index given to packet at first RSP hop
                - transport-type:

        """
        # NFQ for classified packets, initialized by packet_collector()
        self.nfq = None

        # socket used to forward NSH encapsulated packets
        self.fwd_socket = None

        # identifiers of the currently processed RSP, set by process_acl()
        # these will be different for each processed ACL/ACE
        self.rsp_id = None
        self.rsp_acl = None
        self.rsp_ace = None
        self.rsp_chain = None

        # IP version of the currently processed RSP, set by parse_ace()
        # this attribute serves as run_iptables_cmd() 'ipv' argument
        self.rsp_ipv = None

        # currently processed RSP mark, set by parse_ace()
        # this attribute serves as the ip(6)tables mark argument
        self.rsp_mark = None

        self.rsp = None
        self.accessLists={}

    def _set_rsp(self,rsp):
        self.rsp = rsp

    def _get_accessLists(self):
        return self.accessLists

    def _get_current_ip_version(self, ip):
        """
        Get current IP address version

        :param ip: IP address
        :type ip: str

        :return int

        """
        if '/' in ip:
            ip_parts = ip.split('/')
            ip = ip_parts[0]

        ip = ipaddress.ip_address(ip)

        return ip.version

    def set_fwd_socket(self, ip_adr):
        """
        Set classifier forward port base on the ip_adrr version provided

        :param ip_adr: IP address
        :type ip: str

        """
        ipver = self._get_current_ip_version(ip_adr)
        #logger.info('IP version for classifier forward socket is :"%s"', ipver)
        if ipver == 4:
            adrr_family = socket.AF_INET
        elif ipver == 6:
            adrr_family = socket.AF_INET6     
        else:
           adrr_family = socket.AF_INET
           
        if self.fwd_socket != None:
            self.fwd_socket.close()
  
        self.fwd_socket = socket.socket(adrr_family, socket.SOCK_DGRAM)
        logger.debug("Forward socket created in classifier with IP %s", ip_adr)
        # res = self.fwd_socket.getsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY)
        # logger.info('IPV6_V6ONLY set to :"%s"', res)
        # self.fwd_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        try:
            self.fwd_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, socket.error):
            # Apparently, the socket option is not available in
            # this machine's TCP stack
            logger.info("Apparently, the socket option is not available in this machine's TCP stack")            
            pass

    def _compose_packet_mark(self):
        """
        Compose packet mark as a combination of the RSP ID and IP version

        :return int

        """
        return int(str(self.rsp_id) + "%02d" % sum(self.rsp_ipv))

    def _decompose_packet_mark(self, mark):
        """
        Decompose packet mark to the RSP ID and IP version

        :param mark: packet mark
        :type mark: int

        :return tuple

        """
        mark = str(mark)

        rsp_id = int(mark[:-2])
        ipv = int(mark[-2:])

        return rsp_id, ipv

    def forward_packet(self, packet):
        """
        Encapsulate given packet with NSH and forward it to SFF related with
        currently matched RSP

        :param packet: packet to process
        :type packet: `:class:netfilterqueue.Packet`


        """

        mark = packet.get_mark()
        logger.info('forward_packet: %s, marked "%d"', packet, mark)
        rsp_id, ipv = self._decompose_packet_mark(mark)
        

        # if rsp_id not in self.rsp:
        #     sfc_globals.not_processed_packets += 1
        #     return

        if rsp_id not in self.accessLists:
            sfc_globals.not_processed_packets += 1
            return

        # instances = self.rsp[rsp_id]
        # minRemain = 10000000
        # index = -1
        # for i in range(0,len(instances)):
        #     if instances[i]['remainPackets'] < minRemain:
        #         minRemain = instances[i]['remainPackets']
        #         index =i
        # if index == -1:
        #     return
        # instances[index]['remainPackets'] = instances[index]['remainPackets']+1

        # index = self.accessLists[rsp_id]['index']
        # if index > len(index):
        #     index = 0
        # self.accessLists[rsp_id]['index'] = index + 1 
        
        # fwd_to = {'ip':instances[index]['ip'],'port':6000,'starting-index':255}

        fwd_to = {'ip':'192.168.43.165','port':6000,'starting-index':255, 'transport-type': 'service-locator:vxlan-gpe',}

        next_protocol = ipv_2_next_protocol[ipv]
        
        transport = fwd_to['transport-type']
               
        if 'vxlan-gpe' in transport and sfc_globals.get_legacy_vxlan() == False:
            # NOTE
            # tunnel_id (0x0500) is hard-coded, will it be always the same?
            logger.info('transport: VXLAN_GPE')
            encap_header = VXLANGPE(vni=0x0500,
                                    reserved=0,
                                    reserved2=64,
                                    next_protocol=VXLAN_NEXT_PROTO_NSH,
                                    flags=int('00001100', 2))
        elif 'gre' in transport:
            logger.info('transport: GRE')
            encap_header = GREHEADER(reserved1=0,
                                     c=int('0', 2),
                                     protocol_type=0x894F,
                                     version=int('000', 2),
                                     reserved0=int('000000000000', 2),
                                     checksum=int('0000000000000000', 2))
        elif 'vxlan' in  transport and sfc_globals.get_legacy_vxlan():
            # NOTE
            # tunnel_id (0x0500) is hard-coded, will it be always the same?
            logger.info('transport: VXLAN')
            encap_header = VXLAN()                
        else:
            raise ValueError('Unsupported transport type "%s"', transport)


        base_header = BASEHEADER(service_path=rsp_id,
                                 service_index=fwd_to['starting-index'],
                                 next_protocol=next_protocol)


        # NOTE
        # so far only context metadata are supported 
        local_sfp_mtdt = sfc_globals.get_sfp_context_metadata()
        if local_sfp_mtdt:
            ctx_header = CONTEXTHEADER(network_shared=local_sfp_mtdt['context-header1'],
                                   service_shared=local_sfp_mtdt['context-header2'],
                                   network_platform=local_sfp_mtdt['context-header3'],
                                   service_platform=local_sfp_mtdt['context-header4'])
        else:
            ctx_header = CONTEXTHEADER(network_shared=0,
                                   service_shared=0,
                                   network_platform=0,
                                   service_platform=0)
        eth_header = ETHHEADER(0x3c, 0x15, 0xc2, 0xc9, 0x4f, 0xbc, 0x08, 0x00, 0x27, 0xb6, 0xb0, 0x58,
                                    0x08, 0x00)
        if sfc_globals.NSH_TYPE_3 == sfc_globals.get_NSH_type():
            nsh_header = build_nsh_eth_header(encap_header, base_header, ctx_header, eth_header)
            logger.debug('NSH type 3 created')
        else:
            nsh_header = build_nsh_header(encap_header, base_header, ctx_header)
            logger.debug('NSH type 1 created')
        nsh_packet = nsh_header + packet.get_payload()
        
        try:
            logger.info('addr: "%s"  port:"%s"', fwd_to['ip'], fwd_to['port'])
            logger.debug('* Sending packet to IP: "%s", port: "%d", nsp: "%d", nsi: "%d", next_protocol(base_header): "%s", next_protocol(encap_header): "%s"',
                fwd_to['ip'], fwd_to['port'], rsp_id, fwd_to['starting-index'], next_protocol, VXLAN_NEXT_PROTO_NSH)
        
            self.fwd_socket.sendto(nsh_packet, (fwd_to['ip'], fwd_to['port']))

            sfc_globals.sent_packets += 1
            # logger.debug('* Queued:"%d" sent:"%d sfq:"%d" sffq:"%d" sf_proc:"%d" sff_proc "%d"',
            #         sfc_globals.processed_packets, sfc_globals.sent_packets,
            #         sfc_globals.sf_queued_packets, sfc_globals.sff_queued_packets,
            #         sfc_globals.sf_processed_packets, sfc_globals.sff_processed_packets)
            sleep(0.00000001)  # not nice but this sending process needs to be slow down
        except Exception as e:  
            # msg = 'Excepton {} , {}'.format(e.message, e.args)
            logger.info(e)
            logger.exception(e)
            # raise
        
    def process_packet(self, packet):
        """
        Main NFQ callback for each classified packet.
        Drop the packet if RSP is unknown, pass it for processing otherwise.

        :param packet: packet to process
        :type packet: `:class:netfilterqueue.Packet`
        """

        try:
            logger.info("dd:receive a packet")
            in_pckt_queue.put_nowait(packet)
            packet.drop()
            sfc_globals.processed_packets += 1
        except:
            logger.exception('NFQ failed to receive a packet')

    def packet_sender(self):
        """

        Waiting for the packets  from in_packet_queue and forward them.

        """
        global in_pckt_queue

        if not NFQ_AVAILABLE:
            logger.error('Classifier can\'t start\n\n'
                         '*** NetfilterQueue not supported or installed ***\n')
            return

        try:
            while True:
                packet = in_pckt_queue.get(block=True)
                logger.info('getting from queue ok')
                self.forward_packet(packet)
                in_pckt_queue.task_done()
        except:
            msg = 'Reading from queue failed'
            logger.exception(msg)
            raise

    def packet_collector(self):
        """
        Main NFQ related method.

        Configure the queue (if available) and wait for packets.

        NOTE: NetfilterQueue.run() blocs!

        """
        if not NFQ_AVAILABLE:
            logger.error('Classifier can\'t start\n\n'
                         '*** NetfilterQueue not supported or installed ***\n')
            return

        try:
            self.nfq = NetfilterQueue()

            logger.info('Binding to NFQ queue number "%s"', NFQ_NUMBER)
            self.nfq.bind(NFQ_NUMBER, self.process_packet)
        except:
            msg = ('Failed to bind to the NFQ queue number "%s". '
                   'HINT: try to run command `sudo iptables -L` to check if '
                   'the required queue is available.' % NFQ_NUMBER)

            logger.exception(msg)
            raise

        try:
            logger.info('Starting NFQ - waiting for packets ...')
            self.nfq.run()
        except:
            logger.exception('Failed to start NFQ')
            raise

    def collect_packets(self):
        """
        Start a thread for classified packets collection
        """
        nfq_thread = threading.Thread(target=self.packet_collector)
        nfq_thread.daemon = True
        nfq_thread.start()

        sending_thread = threading.Thread(target=self.packet_sender)
        sending_thread.daemon = True
        sending_thread.start()

    def parse_ace(self, ace_matches):
        """
        Parse given Access List Entries (ACE) matches and put together an
        iptables command representing the rule that should be applied.

        ACE matches is parsed item by item and the `ace_rule_cmd` list is
        extended in each step. Setting packets marking is the last step before
        returning.

        :param ace_matches: Access List Entries
        :type ace_matches: dict

        :return list

        """
        ipv = None
        ace_rule_cmd = ['-I', self.rsp_chain]
        logger.info('Parsing ACE...')
        if 'ip-protocol' in ace_matches:
            protocols = ace_2_iptables['protocols']['type']
            protocol_flag = ace_2_iptables['protocols']['flag']

            for protocol in protocols:
                try:
                    protocol = protocols[ace_matches.pop('ip-protocol')]
                    ace_rule_cmd.extend([protocol_flag, protocol])
                    break

                except KeyError:
                    logger.warning('Unknown ip-protocol "%s"', protocol)

        src_ips = ace_2_iptables['source-ips']['type']
        for src_ip in src_ips:
            if src_ip in ace_matches:
                src_ip_flag = ace_2_iptables['source-ips']['flag']
                src_ip = ace_matches.pop(src_ip)
                ipv = (self._get_current_ip_version(src_ip),)

                ace_rule_cmd.extend([src_ip_flag, src_ip])
                break

        dst_ips = ace_2_iptables['destination-ips']['type']
        for dst_ip in dst_ips:
            if dst_ip in ace_matches:
                dst_ip_flag = ace_2_iptables['destination-ips']['flag']
                dst_ip = ace_matches.pop(dst_ip)
                ipv = (self._get_current_ip_version(dst_ip),)

                ace_rule_cmd.extend([dst_ip_flag, dst_ip])
                break

        ports = ace_2_iptables['ports']
        for port_range in ports:
            if port_range in ace_matches:
                port_flag = ports[port_range]

                port_range = ace_matches.pop(port_range)
                upper = str(port_range['upper-port'])
                lower = str(port_range['lower-port'])

                if upper == lower:
                    port = upper
                else:
                    port = '%s:%s' % (lower, upper)

                ace_rule_cmd.extend([port_flag, port])

        source_mac = 'source-mac-address'
        if source_mac in ace_matches:
            ace_rule_cmd.extend(['-m', 'mac', '--mac-source'])
            ace_rule_cmd.append(ace_matches[source_mac])

        self.rsp_ipv = (IPV4, IPv6) if ipv is None else ipv
        self.rsp_mark = self._compose_packet_mark()

        ace_rule_cmd.extend(['-j', 'MARK', '--set-mark', self.rsp_mark])
        return ace_rule_cmd

    def process_acl(self, accessLists):
        """
        Parse ACL data and create/remove ip(6)tables rules accordingly.

        To be able to create/remove an ip(6)tables rule/chain these attributes
        must be set (i.e. not None):
        self.rsp_chain, self.rsp_ipv, self.rsp_mark + self.rsp_id for creating
        a rule/chain.

        :param acl_data: ACL
        :type acl_data: dict

        """
        self.rsp_acl = 'ACL1'

        for ace in accessLists:
            rspId = ace['rspId']
            if rspId in self.accessLists:
                logger.warning('RSP "%s" already exists', rspId)
                continue

            self.rsp_id = rspId
            self.rsp_ace = 'ACE1'
            self.rsp_chain = '-'.join((self.rsp_acl,
                                   self.rsp_ace,
                                   'RSP',
                                   str(self.rsp_id)))
            matches = copy.deepcopy(ace['matches'])
            # `self.rsp_ipv` and `self.rsp_mark` are set by this
            ace_rule_cmd = self.parse_ace(ace['matches'])
            self.register_rsp()
            run_iptables_cmd(ace_rule_cmd, self.rsp_ipv)
            self.accessLists[rspId] = {'name':self.rsp_chain,'ipv':self.rsp_ipv,'matches':matches}

    def register_rsp(self):
        """
        Create iptables rules for the current ACL -> ACE -> RSP

        In other words: create an iptables chain for the current RSP, mark
        traversing packets and redirect them to the NFQ.

        Packet mark (which must be an integer) is a combination of the RSP ID
        and the IP version for which an ip(6)tables rule/chain exists.
        IP version is described by the last two mark digits, i.e. 04 -> IPv4,
        06 -> IPv6, 10 -> IPv4 and IPv6.

        For example a '104' mark describes RSP "1" for which an IPv4 iptables
        rule exists. Mark 5010 describes RSP "50" for which both an IPv4 and
        an IPv6 ip(6)tables rules exists.

        """
        logger.debug('Creating iptables rule for ACL "%s", ACE "%s", RSP "%s"',
                     self.rsp_acl, self.rsp_ace, self.rsp_id)

        # create [-N] new chain for the RSP
        run_iptables_cmd(['-N', self.rsp_chain],
                         self.rsp_ipv)

        # insert [-I] a jump to the created chain
        run_iptables_cmd(['-I', 'PREROUTING',
                          '-j', self.rsp_chain],
                         self.rsp_ipv)

        run_iptables_cmd(['-I', 'OUTPUT',
                          '-j', self.rsp_chain],
                         self.rsp_ipv)

        # append [-A] packet marking and redirection to the NFQ
        run_iptables_cmd(['-A', self.rsp_chain,
                          '-m', 'mark', '--mark', self.rsp_mark,
                          '-j', 'NFQUEUE', '--queue-num', NFQ_NUMBER],
                         self.rsp_ipv)

    def unregister_rsp(self):
        """
        Remove iptables rules for the current RSP
        """
        # delete [-D] the jump to the chain
        run_iptables_cmd(['-D', 'PREROUTING',
                          '-j', self.rsp_chain],
                         self.rsp_ipv)

        run_iptables_cmd(['-D', 'OUTPUT',
                          '-j', self.rsp_chain],
                         self.rsp_ipv)

        # flush [-F] the chain
        run_iptables_cmd(['-F', self.rsp_chain],
                         self.rsp_ipv)

        # delete [-X] chain
        run_iptables_cmd(['-X', self.rsp_chain],
                         self.rsp_ipv)

    def remove_acl_rsp(self, rsp_id):
        """
        Remove ip(6)tables rules/chains for a given RSP and remove it from the
        data-store as well; state (return) if the removal was succesfull.

        :param rsp_name: RSP name
        :type rsp_name: str

        """
        logger.debug('Removing iptables rules for RSP "%s"', rsp_id) 
        acl = self.accessLists.get(rsp_id)
        if acl is None:
            return
        
        self.rsp_chain = acl['name']
        self.rsp_ipv = acl['ipv']
        self.unregister_rsp()
        del self.accessLists[rsp_id]


    def remove_acl_rsps(self):
        """
        Remove ip(6)tables rules/chains related to the current ACL
        """
        for rsp_id in self.accessLists.keys():
            acl = self.accessLists.get(rsp_id)
            if acl is None:
                return     
            self.rsp_chain = acl['name']
            self.rsp_ipv = acl['ipv']
            self.unregister_rsp()
        self.accessLists = {}



    def nfq_running(self):
        """
        Check if the NFQ is running

        :return bool

        """
        return False if self.nfq is None else True


def start_classifier():
    """
    Start NFQ classifier
    """
    nfq_classifier = NfqClassifier()

    nfq_classifier.collect_packets()
    logger.info('******************Classifier started "***************')


def clear_classifier():
    """
    Clear all created ip(6)tables rules (if any), unbind from NFQ
    """
    nfq_classifier = NfqClassifier()

    if nfq_classifier.nfq_running():
        # TODO: logging exceptions ocures (sometimes) -> debug
        nfq_classifier.remove_acl_rsps()
        logger.debug('******************Classifier Processed packets "%d"***************', sfc_globals.processed_packets)
        logger.debug('******************Classifier Sent packets "%d"***************', sfc_globals.sent_packets)
    logger.debug('******************Not processed packets "%d"***************', sfc_globals.not_processed_packets)