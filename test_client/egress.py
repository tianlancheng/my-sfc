# -*- coding: utf-8 -*-
import socket
import os

client = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)

def main():
    socket_protocol = socket.IPPROTO_ICMP
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind(( '0.0.0.0', 5002 ))
    #sniffer.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)

    while 1:
        raw_buffer = server.recvfrom(65565)[0]
        client.sendto(raw_buffer[60:],('127.0.0.1', 5001)) #nsh_header: 32 ip_header:28


if __name__ == '__main__':
    main()