#include<stdio.h>
#include<string.h>
#include<sys/types.h>
#include<sys/socket.h>
#include<netinet/in.h>
#include<stdlib.h>
#include<errno.h>
#include<signal.h>
 
#define MAX_BUF_SIZE 1500
 
// struct udp_packet
// {
//     long int sendtime; 
//     unsigned long int seq;
// };

// struct udp_packet {
//     signed   int id      : 32;
//     unsigned int tv_sec  : 32;
//     unsigned int tv_usec : 32;
// };

struct udp_packet {
    int32_t id;
    u_int32_t tv_sec;
    u_int32_t tv_usec;
};

long packetSize=0;

long firstTime = 0;
long lastTime = 0;
long num = 0;
long totalTime = 0;

int isReport = 0;

void report()
{
    if(isReport==0){
        printf("\n");
        printf("receive datagrams : %ld\n",num);
        printf("packet size : %ld\n",packetSize);
        printf("receive total size : %fM\n",(float)(num*packetSize)/1000000);
        printf("spend time: %fms\n", (float)(lastTime-firstTime)/1000);
        printf("bandwidth is : %fMbits/s\n", (float)num*packetSize*8/(lastTime-firstTime));
        printf("delay is : %fms\n", (float)totalTime/num/1000);

        firstTime = 0;
        lastTime = 0;
        num = 0;
        totalTime = 0;
        isReport = 1;
    }
    exit(0);
}

int main(int argc,char* argv[])
{
    if (argc != 2)
    {
        printf("./%s portnumber",argv[0]);
        exit(1);
    }
 
    int sockfd;
    long localtime;
    FILE *fp;
    struct sockaddr_in localaddr,remoteaddr;
    struct timeval recvtime;
    char recvbuf[MAX_BUF_SIZE];
    struct udp_packet udp_data;
 
    memset(&localaddr,0x00,sizeof(struct sockaddr_in));
    localaddr.sin_family = AF_INET;
    localaddr.sin_port = htons(atoi(argv[1]));
    localaddr.sin_addr.s_addr = htonl(INADDR_ANY);//本机IP
 
    if ((sockfd = socket(AF_INET,SOCK_DGRAM,0)) < 0)
    {
        printf("Create socket failed !\n");
        exit(1);
    }
    else
        printf("Create socket success !\n");
 
    if ((bind(sockfd,(struct sockaddr*)&localaddr,sizeof(localaddr))) < 0)
    {
        printf("Bind port failed !\n");
        exit(1);
    }
    else
        printf("Bind port success !\n");
    
    // if ((fp = fopen("recvdata.txt","w")) == NULL )
    // {
    //     perror("fopen error");
    //     exit(1);
    // }
    // else
    //     printf("Success to create the receive file!\n");
    int remoteaddr_len = sizeof(struct sockaddr);
    
    signal(SIGINT,report);
    long sendtime;
    int id;
    while(1)
    {
        packetSize=recvfrom(sockfd,recvbuf,MAX_BUF_SIZE,0,(struct sockaddr*)&remoteaddr,&remoteaddr_len);
        if (packetSize < 0)
        {
            printf("Fail to receive data!\n");
        }
        else
        {
            // printf("receiving... \n");
            struct udp_packet* t_data = (struct udp_packet*)recvbuf;
            id = ntohl(t_data->id);
            // printf("%d\n",id);
            gettimeofday(&recvtime,0);
            localtime = 1000000*recvtime.tv_sec + recvtime.tv_usec;
            sendtime = (long)1000000*ntohl(t_data->tv_sec) + ntohl(t_data->tv_usec);
            // fprintf(fp,"%ld  %ld  %ld\n", t_data -> seq, localtime, t_data -> sendtime);//输出到txt文件方便统计
            if(id < 0){
                // report();
                printf("-1\n");
            }else{
                isReport = 0;
                if(firstTime == 0)
                    firstTime = localtime;
                lastTime = localtime;
                totalTime=totalTime+localtime-sendtime;
                num++;
            }
        }       
    
    }
    // fclose(fp);
    close(sockfd);
    return(0);
}
