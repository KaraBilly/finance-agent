#!/bin/bash
# stop_milvus.sh — 停止 Milvus 服务

echo "停止 Milvus 服务..."
docker-compose -f docker-compose.milvus.yml down

echo ""
echo "Milvus 已停止。"
echo "数据保留在 volumes/ 目录中。"
