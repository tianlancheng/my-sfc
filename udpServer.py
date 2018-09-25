# -*- coding: utf-8 -*-
import socket
import os
import struct
import ctypes
#from ICMPHeader import ICMP

import ctypes

class ICMP(ctypes.Structure):
    _fields_ = [
    ('type',        ctypes.c_ubyte),
    ('code',        ctypes.c_ubyte),
    ('checksum',    ctypes.c_ushort),
    ('unused',      ctypes.c_ushort),
    ('next_hop_mtu',ctypes.c_ushort)
    ]

    def __new__(self, socket_buffer):
        return self.from_buffer_copy(socket_buffer)

    def __init__(self, socket_buffer):
        pass


# host to listen on
HOST = '0.0.0.0'

def main():
    socket_protocol = socket.IPPROTO_ICMP
    sniffer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sniffer.bind(( HOST, 9999 ))
    #sniffer.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

    while 1:
        raw_buffer = sniffer.recvfrom(65565)[0]
        print('packet -> %s' %raw_buffer)
        ip_header = raw_buffer[0:20]
        iph = struct.unpack('!BBHHHBBH4s4s' , ip_header)

        # Create our IP structure
        version_ihl = iph[0]
        version = version_ihl >> 4
        ihl = version_ihl & 0xF
        iph_length = ihl * 4
        ttl = iph[5]
        protocol = iph[6]
        s_addr = socket.inet_ntoa(iph[8]);
        d_addr = socket.inet_ntoa(iph[9]);

        print('IP -> Version:' + str(version) + ', Header Length:' + str(ihl) + \
        ', TTL:' + str(ttl) + ', Protocol:' + str(protocol) + ', Source:'\
         + str(s_addr) + ', Destination:' + str(d_addr))

        # Create our ICMP structure
        buf = raw_buffer[iph_length:iph_length + ctypes.sizeof(ICMP)]
        icmp_header = ICMP(buf)
        print ("ICMP -> Type:%d, Code:%d" %(icmp_header.type, icmp_header.code))

        print("data -> %s" %(raw_buffer[iph_length + ctypes.sizeof(ICMP):]).decode()+'\n')
	

if __name__ == '__main__':
    main()


"""
import socket
BUFSIZE = 1024
ip_port = ('0.0.0.0', 9999)
server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
server.bind(ip_port)
while True:
    data,client_addr = server.recvfrom(BUFSIZE)
    print(client_addr,data)
    readstr = ' '.join(hex(x) for x in data)
    print(readstr)
    server.sendto(data.upper(),client_addr)
 
server.close()
"""
