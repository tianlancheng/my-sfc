#-*- coding: utf-8 -*-：
import socket, time
BUFSIZE = 1024
client = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
# client = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_RAW)
client.bind(("",17000))
x=0
while True:
	if x>100:
		break
	x=x+1
	ip_port = ('127.0.0.1', 6000)
	client.sendto("test1".encode('utf-8'),ip_port)
	time.sleep(0.01)
	# data,server_addr = client.recvfrom(BUFSIZE)
	# print('client recvfrom ',data,server_addr)

client.close()