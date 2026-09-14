# 印章识别服务 - CPU 版本
# 构建：docker build -t seal-service:cpu .
FROM python:3.10-slim

RUN sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources && \
    sed -i 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list.d/debian.sources && \
    apt update

# 系统依赖（PaddleOCR 运行需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 Docker 缓存）
COPY requirements-base.txt requirements-cpu.txt ./
RUN pip install --no-cache-dir -r requirements-cpu.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple

# 拷贝代码
COPY . .

# 模型缓存目录（容器内）
ENV PADDLE_PDX_CACHE_DIR=/root/.paddlex

EXPOSE 8000

# 启动命令（2 worker，生产环境按需调整）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
