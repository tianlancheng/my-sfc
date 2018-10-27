# -*- coding: UTF-8 -*-
from __future__ import division
import codecs


fr=codecs.open('recvdata.txt','r','utf-8')
lines=fr.readlines()

n=len(lines)

first = lines[0]
first = first.split('  ')

end = lines[n-1]
end = end.split('  ')

send_start_time=long(first[2])
send_end_time=long(end[2])
recv_start_time=long(first[1])
recv_end_time=long(end[1])

total_time = 0
for line in lines:
	line=line.split('  ')
	total_time = total_time + (long(line[1])-long(line[2]))

total_size = 1470*n/1000000
spend_time = (recv_end_time-recv_start_time)/1000000
bandwidth = 1470*n/(recv_end_time-recv_start_time)
delay = total_time/n/1000
print('receive datagrams: %d' % n)
print('total size: %dM' % total_size)
print('spend time: %fs' % spend_time)
print('bandwidth: %fM/s' % bandwidth)
print('delay: %fms' % delay)