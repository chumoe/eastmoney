#!/bin/bash

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== 启动 EastMoney 服务 (Docker) ===${NC}"

# 1. 检查 Docker
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Docker 未安装，请先安装 Docker。${NC}"
    exit 1
fi

# 检测 Compose 版本
COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo -e "${RED}Docker Compose 未安装。${NC}"
    exit 1
fi

# 2. 目录准备
echo -e "${GREEN}--> 检查并创建目录结构...${NC}"
mkdir -p reports/commodities
mkdir -p reports/sentiment
mkdir -p config
mkdir -p data

# 数据库文件初始化
if [ ! -f "data/funds.db" ]; then
    if [ -d "data/funds.db" ]; then
        rm -rf data/funds.db
    fi
    touch data/funds.db
fi

# 3. 清理旧环境
echo -e "${GREEN}--> 清理旧容器...${NC}"
$COMPOSE_CMD down 2>/dev/null || true

# 4. 构建并启动
echo -e "${GREEN}--> 构建并启动容器...${NC}"
$COMPOSE_CMD up -d --build

# 5. 状态检查
echo -e "${GREEN}--> 容器状态：${NC}"
$COMPOSE_CMD ps

echo ""
echo -e "${YELLOW}提示：${NC}"
echo "  - 源代码通过 volumes 挂载，修改代码后会自动重载"
echo "  - 如需重新构建镜像，运行: $COMPOSE_CMD up -d --build"
echo "  - 查看日志: $COMPOSE_CMD logs -f"
echo ""
echo -e "${GREEN}=== 服务已在端口 9000 上线 ===${NC}"
