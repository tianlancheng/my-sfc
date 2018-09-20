#
# Copyright (c) 2014 Cisco Systems, Inc. and others.  All rights reserved.
#
# This program and the accompanying materials are made available under the
# terms of the Eclipse Public License v1.0 which accompanies this distribution,
# and is available at http://www.eclipse.org/legal/epl-v10.html

import socket
import logging
import asyncio

from time import sleep
from threading import Thread

from .sfc_globals import sfc_globals
from .services import SF, SFF, CUDP, find_service


__author__ = "Jim Guichard, Reinaldo Penno"
__copyright__ = "Copyright(c) 2014, Cisco Systems, Inc."
__version__ = "0.2"
__email__ = "jguichar@cisco.com, rapenno@gmail.com"
__status__ = "alpha"


"""
Manage LOCAL service [and associated thread] starting and stopping
"""


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


#: constants
DPCP = 'data_plane_control_port'


def _get_global_threads(service_type):
    """
    Get the global service threads dictionary.

    If service type is not a SFF then it must be a type of SF.

    :param service_type: service type (SF or SFF)
    :type service_type: str

    :return dict

    """
    if service_type == SFF:
        global_threads = sfc_globals.get_sff_threads()
    else:
        global_threads = sfc_globals.get_sf_threads()

    return global_threads


def _check_thread_state(service_type, service_name, thread):
    """
    Check service thread state.

    As per asynchronous nature of working with threads [and asyncio] wait till
    the thread is started, till the SfcGlobals data are updated and then insert
    the thread info.

    :param service_type: service type (SF or SFF)
    :type service_type: str
    :param service_name: service name
    :type service_name: str
    :param thread: service thread
    :type thread: `class:threading.Thread`

    """
    global_threads = _get_global_threads(service_type)

    timeout = 0
    while timeout < 10:
        sleep(0.1)
        timeout += 0.1

        if not thread.is_alive():
            continue

        if service_name not in global_threads:
            continue

        if not global_threads[service_name]:
            continue

        break

    else:
        raise TimeoutError('Failed to start %s "%s": service thread is '  # noqa
                           'still not running after 10s or SfcGlobals was not'
                           'updated properly' %
                           (service_type.upper(), service_name))

    global_threads[service_name]['thread'] = thread


def _connect(loop, addr, service):
    """
    Create a background socket connection for the specified service.

    :param loop:
    :type loop: `:class:asyncio.unix_events._UnixSelectorEventLoop`
    :param addr: IP address, port
    :type addr: tuple
    :param service: service instance
    :type service: `:class:common.services.BasicService`

    :return `:class:asyncio.selector_events._SelectorDatagramTransport`

    """
    listen = loop.create_datagram_endpoint(lambda: service, local_addr=addr)
    transport, _ = loop.run_until_complete(listen)

    return transport


def start_service(service_name, service_ip, service_port, service_type):
    """
    Start a service and register it with SfcGlobals.

    Start both the target service and its control UPD server.

    NOTE: loop.run_forever() blocs!

    :param service_name: service name
    :type service_name: str
    :param service_ip: service IP address
    :type service_ip: str
    :param service_port: service port
    :type service_port: int
    :param service_type: service type
    :type service_type: str

    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    logger.info('Starting %s serving as %s at %s:%s, service type:%s ',
                service_type.upper(), service_name, service_ip, service_port, service_type)

    service_class = find_service(service_type)
    service = service_class(loop)
    service.set_name(service_name)

    service_transport = _connect(loop, (service_ip, service_port), service)
    service_socket = service_transport.get_extra_info('socket')


    service_threads = _get_global_threads(service_type)
    service_threads[service_name] = {}
    service_threads[service_name]['socket'] = service_socket
   
    loop.run_forever()
    loop.close()


def start_sf(sf_name, sf_ip, sf_port, sf_type):
    """
    Start a Service Function.

    Stop an already running SF if it has the same name as the SF which is
    about to start. Then start the new one.

    """
    logger.info('Starting Service Function: %s', sf_name)


    sf_thread = Thread(target=start_service,
                       args=(sf_name, sf_ip, sf_port, sf_type))

    sf_thread.start()
    _check_thread_state(SF, sf_name, sf_thread)

