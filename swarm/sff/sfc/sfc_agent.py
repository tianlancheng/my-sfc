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
    last_processed_packets = -1;
    while(True):
        nowTime = time.time()
        queued_packets = sfc_globals.sff_queued_packets
        processed_packets = sfc_globals.sf_processed_packets
        if(last_processed_packets == -1):
            speed = 0
        else:
            speed = round((processed_packets - last_processed_packets)/(nowTime-lastTime),2)
        last_processed_packets = processed_packets
        lastTime = nowTime
        data={
            "sfId": sfc_globals.get_sf_id(),
            "instanceId": sfc_globals.get_instance_id(),
            "ip": myaddr,
            "queuedPackets": queued_packets,
            "processedPackets": processed_packets,
            "remainPackets": queued_packets-2*processed_packets,
            "speed": speed
        }
        # logger.info(data)
        try:
            r=requests.post('http://'+odl_ip_port+'/api/heartbeat',data = json.dumps(data))
            # logger.info(r.text)
            r=r.json()
            next_hops = r['data']
            sfc_globals.set_next_hops(next_hops)
        except:
            logger.info('send error')
        time.sleep(5)


def start(sffname):
    start_sff(sffname, '0.0.0.0', 6000)

# python3 sfc/sfc_agent.py --odl-ip-port 192.168.43.126:8080 --sf-id 1 --instance-id 1
if __name__ == "__main__":
    if len(sys.argv) == 2:
        sfc_globals.set_next_hops({'ip':sys.argv[1],'port':6000})
    else:
        sfc_globals.set_next_hops(None)
    
    logger.info('next service: %s', sfc_globals.get_next_hops())
    start('sff')

