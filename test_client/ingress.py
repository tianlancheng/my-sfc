# -*- coding: utf-8 -*-

import socket
import os
import sys

from nsh.decode import *  # noqa
from nsh.encode import *  # noqa
import struct


client = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)

def get_nsh_header(service_path=1, service_index=255):
    base_header_values = BASEHEADER(service_path=service_path, service_index=255, proto=NSH_NEXT_PROTO_ETH)
    base_header_values.next_protocol = NSH_NEXT_PROTO_IPV4
    vxlan_header_values = VXLANGPE()
    
    ctx1 = ctx2 = ctx3 = ctx4 = 0
    context_headers = process_context_headers(ctx1, ctx2, ctx3, ctx4)
    ctx_header_values = CONTEXTHEADER(context_headers[0], context_headers[1], context_headers[2], context_headers[3])
    packet = build_nsh_header(vxlan_header_values, base_header_values, ctx_header_values)

    return packet


def main(service_path, remote_ips, remote_port, inner_dest_ip, inner_dest_port):
    socket_protocol = socket.IPPROTO_ICMP
    sniffer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sniffer.bind(( '0.0.0.0', 6000 ))
    #sniffer.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

    nsh_header1 = get_nsh_header(service_path)
    nsh_header2 = get_nsh_header(2)
    nsh_header3 = get_nsh_header(3)

    inner_src_ip = '192.168.33.128'
    inner_src_port = 7777

    i=0
    n=len(remote_ips)
    while 1:
        i=(i+1)%n
        raw_buffer = sniffer.recvfrom(65565)[0]
        udp_inner_packet = build_udp_packet(inner_src_ip, inner_dest_ip, inner_src_port, inner_dest_port, raw_buffer)
        client.sendto(nsh_header1 + udp_inner_packet, (remote_ips[i], remote_port))
        # client.sendto(nsh_header2 + udp_inner_packet, (remote_ips[i], remote_port))
        # client.sendto(nsh_header3 + udp_inner_packet, (remote_ips[i], remote_port))
       
if __name__ == '__main__':
    service_path = 1
    remote_ips = ['192.168.43.129','192.168.43.130']
    remote_port = 6000
    inner_dest_ip = '192.168.43.128'
    inner_dest_port = 9999
    if(len(sys.argv)>1):
        service_path = int(sys.argv[1])
        remote_ip = sys.argv[2]
        remote_port = int(sys.argv[3])
        inner_dest_ips = sys.argv[4]
        inner_dest_port = int(sys.argv[5])
    main(service_path, remote_ips, remote_port, inner_dest_ip, inner_dest_port)
