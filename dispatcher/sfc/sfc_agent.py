# -*- coding: utf-8 -*-

import os
import sys
import signal
import logging
import requests
import json
import socket
import time


# fix Python 3 relative imports inside packages
# CREDITS: http://stackoverflow.com/a/6655098/4183498
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, parent_dir)
import sfc  # noqa
__package__ = 'sfc'


from sfc.common import sfc_globals as _sfc_globals
from sfc.common.launcher import start_sff


"""
SFC Agent Server. This Server should be co-located with the python SFF data
plane implementation (sff_thread.py)
"""
logger = logging.getLogger(__file__)
sfc_globals = _sfc_globals.sfc_globals


'''
{
    "sfId": "",
    "instanceId": "",
    "queuedPackets": "",
    "processedPackets": ""
    "remainPackets": ""
    "speed":""
}
'''
def heartbeat(odl_ip_port):
    myname = socket.getfqdn(socket.gethostname(  ))
    myaddr = socket.gethostbyname(myname)
    logger.info(myname+' '+myaddr)
    last_processed_packets = -1
    first = True
    while(True):
        nowTime = time.time()
        receivedPackets = sfc_globals.sff_received_packets
        processed_packets = sfc_globals.sf_processed_packets
        if(last_processed_packets == -1):
            speed = 0
        else:
            speed = round((processed_packets - last_processed_packets)/(nowTime-lastTime),2)
        last_processed_packets = processed_packets
        lastTime = nowTime
        data={
            "instanceId": sfc_globals.get_instance_id(),
            "sfId": sfc_globals.get_sf_id(),
            "ip": myaddr,
            "receivedPackets": receivedPackets,
            "qsize": sfc_globals.qsize,
            "speed": speed,
            "first": first
        }
        try:
            r=requests.post('http://'+odl_ip_port+'/api/heartbeat',data = json.dumps(data))
            r=r.json()
            next_hops = r['data']['next_hops']
            sfc_globals.hostIp=r['data']['hostIp']
            sfc_globals.set_next_hops(next_hops)
            first = False
        except Exception as e:
            logger.error(e)
            logger.info('send error')
        time.sleep(5)


def start(sffname):
    start_sff(sffname, '0.0.0.0', 6000)

# python3 sfc/sfc_agent.py --odl-ip-port 192.168.43.126:8080 --sf-id 1 --instance-id 1
if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1])
        sfc_globals.set_odl_locator(args['server'])
        sfc_globals.set_sf_id(args['sfId'])
        sfc_globals.set_instance_id(args['instanceId'])
        sfc_globals.set_policy(args['policy'])
        sfc_globals.set_max_size(args['max_queue_size'])
        sfc_globals.set_next_hops(args['next_hops'])
    except Exception as e:
        logger.error(e)
        exit(2)
    
    logger.info('server: %s', sfc_globals.get_odl_locator())
    logger.info('sfId: %s', sfc_globals.get_sf_id())
    logger.info('instanceId: %s', sfc_globals.get_instance_id())
    logger.info('policy: %s', sfc_globals.get_policy())
    logger.info('max_size: %s', sfc_globals.get_max_size())
    logger.info('next_hops: %s', sfc_globals.get_next_hops())

    start('sff')
    heartbeat(sfc_globals.get_odl_locator())
