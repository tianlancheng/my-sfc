#-*- coding: utf-8 -*-：
import socket
BUFSIZE = 1024
client = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
# client = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
client.bind(("",17000))
while True:
    msg = input(">>").strip()
    ip_port = ('192.168.43.165', 9999)
    client.sendto('dd',ip_port)
 
    # data,server_addr = client.recvfrom(BUFSIZE)
    # print('client recvfrom ',data,server_addr)
 
client.close()