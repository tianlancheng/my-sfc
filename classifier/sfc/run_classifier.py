#
# Copyright (c) 2014 Cisco Systems, Inc. and others.  All rights reserved.
#
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License v1.0 which accompanies this distribution,
# and is available at http://www.eclipse.org/legal/epl-v10.html

import os
import sys
import flask
import signal
import logging
import argparse
import requests
import netifaces
import json
from flask import jsonify
from urllib.parse import urlparse


# fix Python 3 relative imports inside packages
# CREDITS: http://stackoverflow.com/a/6655098/4183498
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(1, parent_dir)
import sfc  # noqa
__package__ = 'sfc'


from sfc.common import classifier
from sfc.cli import xe_cli, xr_cli, ovs_cli
from sfc.common import sfc_globals as _sfc_globals



"""
SFC Agent Server. This Server should be co-located with the python SFF data
plane implementation (sff_thread.py)
"""

app = flask.Flask(__name__)
logger = logging.getLogger(__file__)
nfq_classifier = classifier.NfqClassifier()
sfc_globals = _sfc_globals.sfc_globals



def check_nfq_classifier_state():
    """
    Check if the NFQ classifier is running, log an error and abort otherwise
    """
    if not nfq_classifier.nfq_running():
        logger.warning('Classifier is not running: ignoring ACL')
        flask.abort(500)


@app.errorhandler(404)
def page_not_found(e):
    return 'Not found', 404


@app.route('/config/acl', methods=['PUT', 'POST'])
def apply_acl():
    check_nfq_classifier_state()
    logger.info("Received request from ODL to create ACL ...")

    if not flask.request.json:
        logger.error('Received ACL is empty, aborting ...')
        flask.abort(400)

    try:
        r_json = flask.request.get_json()
        nfq_classifier.process_acl(r_json)
    except Exception as e:
        logger.error(e)
        return jsonify(status=500, msg='error', data=None), 500
    return jsonify(status=200, msg='success', data=None), 200

@app.route('/config/acls', methods=['GET'])
def get_acls():
    check_nfq_classifier_state()
    acls = nfq_classifier._get_accessLists()
    return jsonify(status=200, msg='success', data=acls), 200


@app.route('/config/acl/<rspId>', methods=['DELETE'])
def remove_acl(rspId):
    check_nfq_classifier_state()
    nfq_classifier.remove_acl_rsp(rspId)
    return '', 200


# @app.route('/rsp', methods=['PUT'])
# def update_rsp():
#     r_json = flask.request.get_json()
#     nfq_classifier._set_rsp(r_json)
#     return '', 200

if __name__ == "__main__":
    try:
        classifier.start_classifier()
        nfq_classifier.set_fwd_socket('127.0.0.1')
        app.run(host='0.0.0.0',
                port=5100,
                debug=True,
                use_reloader=False)
    except:
        pass
    finally:
        classifier.clear_classifier()

    # not a great way how to exit, but it works and prevents the
    # `Exception ignored in: ...` message from beeing displayed
    os.kill(os.getpid(), signal.SIGTERM)

'''
{
    "rsp":{
        "rspId1": [],
        "rspId2": []
    },
    "accessLists": [{
        "rspId": 1,
        "matches": {
            "source-port-range": {
                "upper-port": 20000,
                "lower-port": 15000
            },
            "destination-ipv4-address": "127.0.0.1/0",
            "ip-protocol": 17,
            "source-ipv4-address": "127.0.0.1/0"
        }
    }]
}
'''
# def heartbeat(odl_ip_port):
#     myname = socket.getfqdn(socket.gethostname(  ))
#     myaddr = socket.gethostbyname(myname)
#     while(True):
#         data={
#             "ip": myaddr,
#             "accessLists": nfq_classifier._get_accessLists()
#         }
#         try:
#             r=requests.post('http://'+odl_ip_port+'/api/acl/heartbeat',data = json.dumps(data))
#             # logger.info(r.text)
#             r=r.json()
#             nfq_classifier._set_rsp(r['rsp'])
#             if r.get('accessLists'):
#                 nfq_classifier.process_acl(r['accessLists'])
#         except Exception as e:
#             logger.info(e)
#         time.sleep(5)
    
