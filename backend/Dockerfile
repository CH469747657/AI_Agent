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

# 把 NotoSansCJK .ttc 提取为 .ttf（ofdrw FontLoader 不识别 .ttc）
# 必须在装 fonttools 之后
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com fonttools \
    && python -c "from fontTools.ttLib import TTCollection; \
import os; \
src='/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'; \
dst_dir='/usr/share/fonts/truetype/noto-cjk'; \
os.makedirs(dst_dir, exist_ok=True); \
coll=TTCollection(src); \
[font.save(os.path.join(dst_dir, f'NotoSansCJK-Regular-{i}.ttf')) for i, font in enumerate(coll.fonts)]"

# 使用阿里云镜像源加速 pip
COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

# OFD 转图片所需 jar（fat jar，含 ofdrw-converter 2.3.7 + 所有依赖）
# OFD → ofd2img.jar → PDF → poppler pdftoppm → PNG
COPY lib/ /app/lib/
ENV OFD2IMG_JAR_PATH=/app/lib/ofd2img.jar
ENV OFD2IMG_DPI=150
ENV JAVA_BIN=java

COPY . .

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
