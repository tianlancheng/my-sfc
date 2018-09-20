FROM ubuntu:16.04
# APT 自动安装相关的依赖包，如需其他依赖包在此添加
RUN apt-get update --fix-missing && \  
      apt-get install -y python3 \
                       python3-pip  \
    # 用完包管理器后安排打扫卫生可以显著的减少镜像大小
    && apt-get clean \
    && apt-get autoclean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* 

#RUN pip install --no-cache-dir --upgrade pip