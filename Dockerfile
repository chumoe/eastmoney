# ====================================
# 阶段 1: 构建前端
# ====================================
FROM --platform=linux/amd64 node:20-alpine AS frontend-builder

WORKDIR /build/web

COPY web/ ./

# 安装依赖并构建
RUN npm install --registry=https://registry.npmmirror.com && \
    npm run build

# ====================================
# 阶段 2: Python依赖预热 (可选，用于生成依赖快照)
# ====================================
FROM --platform=linux/amd64 python:3.11-slim AS deps-builder

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --prefix=/deps

# ====================================
# 阶段 3: 运行时镜像 (精简，只包含运行时必要文件)
# ====================================
FROM --platform=linux/amd64 python:3.11-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PYTHONPATH=/app \
    DB_FILE_PATH=/app/data/funds.db

# 安装运行时依赖 (只安装运行时必需的)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libffi-dev \
    curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 从依赖构建阶段复制Python包
COPY --from=deps-builder /deps /usr/local

# 从前端构建阶段复制构建好的静态文件
COPY --from=frontend-builder /build/web/dist ./static

# 创建必要的运行时目录
RUN mkdir -p /app/data /app/reports /app/logs && \
    chmod -R 755 /app

# 暴露端口
EXPOSE 9000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9000/api/health || exit 1

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000", "--reload"]
