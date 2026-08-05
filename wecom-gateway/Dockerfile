FROM python:3.10-slim

WORKDIR /app

# 使用阿里云镜像源加速 apt
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxslt1-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 使用阿里云镜像源加速 pip
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

COPY . .

EXPOSE 8090

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8090"]
