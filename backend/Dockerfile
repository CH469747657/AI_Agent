FROM python:3.10-slim

WORKDIR /app

# 使用阿里云镜像源加速 apt
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null; \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null; \
    apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender-dev \
    libgthread-2.0-0 libfontconfig1 libfreetype6 libgomp1 \
    poppler-utils \
    libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
    fonts-noto-cjk \
    default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

# 使用阿里云镜像源加速 pip
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

# OFD 转图片所需 jar（OFD 是中国电子发票格式，由 ofdrw 转为 PNG 后复用 OCR/LLM 流程）
# jar 需提前下载到 backend/lib/ 目录，构建时拷入镜像
COPY lib/ /app/lib/
ENV OFDRW_JAR_PATH=/app/lib/ofdrw-tool.jar
ENV JAVA_BIN=java

COPY . .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
