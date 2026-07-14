#!/bin/bash
# start_milvus.sh — 一键启动 Milvus 并导入数据

set -e

echo "========================================"
echo "Finance Agent - Milvus 启动脚本"
echo "========================================"

# 检查 Docker 是否运行
if ! docker info > /dev/null 2>&1; then
    echo "错误: Docker 未运行，请先启动 Docker"
    exit 1
fi

# 启动 Milvus
echo ""
echo "[1/3] 启动 Milvus 服务..."
docker compose -f docker-compose.milvus.yml up -d

# 等待 Milvus 就绪
echo ""
echo "[2/3] 等待 Milvus 就绪..."
echo "这可能需要 30-60 秒..."
for i in {1..30}; do
    if curl -s http://localhost:9091/healthz > /dev/null 2>&1; then
        echo "Milvus 已就绪!"
        break
    fi
    echo -n "."
    sleep 2
done

echo ""
echo "[3/3] 导入数据到 Milvus..."
python scripts/import_to_milvus.py

echo ""
echo "========================================"
echo "Milvus 启动完成!"
echo ""
echo "Milvus 地址: localhost:19530"
echo "MinIO 控制台: http://localhost:9001"
echo ""
echo "要停止服务，运行:"
echo "  docker-compose -f docker-compose.milvus.yml down"
echo "========================================"
