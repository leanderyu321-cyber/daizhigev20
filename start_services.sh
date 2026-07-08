#!/bin/bash

echo "═══════════════════════════════════════════════════════════"
echo "本地历史知识库 Deep Search —— Docker 启动脚本"
echo "═══════════════════════════════════════════════════════════"
echo

cd /Users/afei/projects/demo/daizhigev20

echo "🔍 检查 Docker 状态..."
if docker --version > /dev/null 2>&1; then
    echo "✓ Docker 已安装: $(docker --version)"
else
    echo "✗ Docker 未找到，请先安装 Docker Desktop"
    exit 1
fi

echo
echo "📦 启动 Docker 容器..."
docker-compose up -d

echo
echo "⏳ 等待容器启动（30秒）..."
sleep 30

echo
echo "✅ 检查容器状态..."
docker-compose ps

echo
echo "🌐 验证服务连接..."

# 检查 Elasticsearch
echo -n "Elasticsearch (http://localhost:9200): "
curl -s http://localhost:9200/_cluster/health | grep -q "status" && echo "✓ 正常" || echo "✗ 未响应"

# 检查 Qdrant
echo -n "Qdrant (http://localhost:6333): "
curl -s http://localhost:6333/health | grep -q "ok" && echo "✓ 正常" || echo "✗ 未响应"

# 检查 Redis
echo -n "Redis (localhost:6379): "
redis-cli ping 2>/dev/null | grep -q "PONG" && echo "✓ 正常" || echo "✗ 未响应"

echo
echo "═══════════════════════════════════════════════════════════"
echo "✅ Docker 启动完成！"
echo "═══════════════════════════════════════════════════════════"
