# ====================================
# 阶段 1: 构建前端
# ====================================
FROM node:20-alpine AS frontend-builder

WORKDIR /build/web

# 先复制包管理文件，最大化利用缓存（只有依赖变化时才重新 install）
COPY web/package.json web/package-lock.json ./

# 安装依赖
RUN npm install --registry=https://registry.npmmirror.com

# 再复制源码和配置文件
COPY web/index.html ./
COPY web/vite.config.ts ./
COPY web/tsconfig*.json ./
COPY web/postcss.config.js ./
COPY web/tailwind.config.js ./
COPY web/eslint.config.js ./
COPY web/public ./public
COPY web/src ./src

# 构建前端
RUN npm run build

# ====================================
# 阶段 2: Python依赖预热 (可选，用于生成依赖快照)
# ====================================
FROM python:3.11-slim AS deps-builder

# 安装编译工具（ARM64构建需要从源码编译部分包）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    --prefix=/deps

# ====================================
# 阶段 3: 运行时镜像 (精简，只包含运行时必要文件)
# ====================================
FROM python:3.11-slim

WORKDIR /app

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

# 从前端构建阶段复制构建好的静态文件（变化频率较低）
COPY --from=frontend-builder /build/web/dist ./static

# 复制配置文件（变化频率较低）
COPY config/ ./config/
COPY .env.example .env

# 复制应用源码（变化频率较高，放在最后）
COPY app/ ./app/
COPY src/ ./src/
COPY main.py .

# 创建必要的运行时目录
RUN mkdir -p /app/data /app/reports /app/logs /app/config && \
    chmod -R 755 /app

# 暴露端口
EXPOSE 9000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:9000/api/health || exit 1

# 启动命令
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000"]
