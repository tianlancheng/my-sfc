#include<stdio.h>
#include<stdlib.h>
#include<netinet/in.h>
#include<sys/socket.h>
#include<sys/types.h>
#include<sys/time.h>
#include<string.h>
#include<time.h>
#include<errno.h>
 
#define MAX_BUF_SIZE 1500
// #define INTERVAL 1000
#define SENDSIZE 1470     //设置包大小和发送间隔以控制流量

struct udp_packet
{
    long int sendtime; 
    unsigned long int seq;
};

int main(int argc, char* argv[])
{
    if(argc != 5)
    {
        printf("Usage: ./%s ip port datagrams_num interval",argv[0]);
        exit(1);
    } 
    
    char sendbuf[MAX_BUF_SIZE];
    int sockfd;
    struct timeval sendtimeval,send_interval;
    struct sockaddr_in hostaddr;
 
    struct udp_packet udp_data;
   
    hostaddr.sin_family = AF_INET;
    hostaddr.sin_port = htons(atoi(argv[2]));
    hostaddr.sin_addr.s_addr = inet_addr(argv[1]);
    
 
    if ((sockfd = socket(AF_INET,SOCK_DGRAM,0)) < 0)
    {
        printf("Creat Socket Failed !\n");
        exit(1);
    }
    else
        printf("Create Socket Success !\n");
   
    udp_data.seq = 1;
    int num = atoi(argv[3]);
    int interval = atoi(argv[4]);
    float total_size = (float)SENDSIZE*num/1000000;
    printf(" packetsize is : %d\n",SENDSIZE);
    printf(" datagrams num is : %d\n",num);
    printf(" send total is : %f M\n",total_size);

    gettimeofday(&sendtimeval,0);
    long int starttime = 1000000 * sendtimeval.tv_sec + sendtimeval.tv_usec;

    int temp;

    while(udp_data.seq<=num)
    {
        send_interval.tv_sec = 0;
        send_interval.tv_usec = interval;
        // do{
        //     temp=select(0,NULL,NULL,NULL,&send_interval);
        // }while(temp<0 && errno == EINTR);
        temp = select(0, NULL, NULL, NULL, &send_interval);
        if(temp == -1)
        {
            continue;
        }

        gettimeofday(&sendtimeval,0);
        udp_data.sendtime = 1000000 * sendtimeval.tv_sec + sendtimeval.tv_usec;
 
        memset(sendbuf,0x00,MAX_BUF_SIZE);
        memcpy(sendbuf,&udp_data,sizeof(struct udp_packet));//!!
        
        if ((sendto(sockfd,sendbuf,SENDSIZE,0,(struct sockaddr*)&hostaddr,sizeof(hostaddr))) < 0 )
        {
            printf("Fail to send the udp packet \n");
        }
        udp_data.seq++;
    }
    close(sockfd);

    float spend_time = udp_data.sendtime - starttime;
    printf(" spend time is : %f ms\n", spend_time/1000);
    printf(" bandwidth is : %f M/s\n", total_size/(spend_time/1000000));
    return 0;
}   
