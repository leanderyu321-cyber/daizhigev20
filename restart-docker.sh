#!/bin/bash
set -e

echo "🔴 停止 Docker Desktop..."
osascript -e 'quit app "Docker"'
sleep 10

echo "🟢 启动 Docker Desktop..."
open -a Docker
sleep 30

echo "📦 启动容器..."
cd /Users/afei/projects/demo/daizhigev20

# 使用简化版 docker-compose
docker-compose -f docker-compose-simple.yml up -d

echo ""
echo "⏳ 等待服务启动 (需要 30-60 秒)..."
for i in {1..30}; do
  if curl -s http://localhost:9200/ > /dev/null 2>&1; then
    echo "✅ Elasticsearch 已启动"
    break
  fi
  echo "还在等待... ($i/30)"
  sleep 2
done

echo ""
echo "🧪 验证服务..."
echo "- Elasticsearch: $(curl -s http://localhost:9200/ | grep -o '"version"' | head -1 || echo '✗ 未响应')"
echo "- Qdrant: $(nc -z -w 1 localhost 6333 && echo '✓ 端口开放' || echo '✗ 端口关闭')"
echo "- Redis: $(nc -z -w 1 localhost 6379 && echo '✓ 端口开放' || echo '✗ 端口关闭')"
