# Docker 容器启动指南

## 当前状态

Docker 容器启动命令已提交，正在后台运行。Docker daemon 响应较慢是正常现象（首次启动需要拉取镜像）。

## 手动检查命令

如果上面的自动检查未返回结果，可以在终端中手动运行以下命令：

### 1️⃣ 查看容器状态
```bash
cd /Users/afei/projects/demo/daizhigev20
docker-compose ps
```

**预期输出**（启动成功时）：
```
NAME              COMMAND                  SERVICE          STATUS
es_history        /bin/tini -- /usr/local… elasticsearch    Up 2 minutes
qdrant_history    ./qdrant                 qdrant           Up 2 minutes
redis_history     redis-server /usr/local… redis            Up 2 minutes
```

### 2️⃣ 验证 Elasticsearch
```bash
curl http://localhost:9200/_cluster/health
```

**预期输出**：
```json
{"cluster_name":"history_corpus_es","status":"green",...}
```

### 3️⃣ 验证 Qdrant
```bash
curl http://localhost:6333/health
```

**预期输出**：
```json
{"ok":true}
```

### 4️⃣ 验证 Redis
```bash
redis-cli ping
```

**预期输出**：
```
PONG
```

### 5️⃣ 查看容器日志（诊断问题）
```bash
# Elasticsearch 日志
docker-compose logs elasticsearch | tail -20

# Qdrant 日志
docker-compose logs qdrant | tail -20

# Redis 日志
docker-compose logs redis | tail -20
```

## 如果容器没有启动

### 方案 A：手动启动
```bash
cd /Users/afei/projects/demo/daizhigev20
docker-compose down    # 停止旧容器（如有）
docker-compose up -d   # 启动新容器
```

### 方案 B：重启 Docker Desktop
1. 打开 Docker Desktop 应用
2. 在菜单中选择 "Restart"
3. 等待 Docker 重启完成（~1分钟）
4. 运行：`docker-compose up -d`

### 方案 C：检查磁盘空间
```bash
df -h /
# 需要至少 20GB 空闲空间
```

### 方案 D：清理旧镜像和容器
```bash
docker system prune -a
docker volume prune
# 然后重新启动：docker-compose up -d
```

## 容器已启动后

一旦三个服务都 `Up` 状态，就可以进行第二步（安装 Python 依赖）：

```bash
pip install -r requirements.txt
```

## 监控容器

### 实时查看日志
```bash
docker-compose logs -f
```

### 进入容器进行调试
```bash
# 进入 Elasticsearch 容器
docker-compose exec elasticsearch bash

# 进入 Qdrant 容器
docker-compose exec qdrant bash

# 进入 Redis 容器
docker-compose exec redis sh
```

## 故障排查

### 端口被占用
```bash
# 找出占用端口的进程
lsof -i :9200    # ES
lsof -i :6333    # Qdrant
lsof -i :6379    # Redis

# 杀死进程（如需要）
kill -9 <PID>
```

### 内存不足
Docker 容器默认配置：
- Elasticsearch: 4GB
- Qdrant: 自动（建议 2GB+）
- Redis: 2GB

如果系统内存不足，编辑 docker-compose.yml 中的内存限制。

### 网络问题
```bash
# 检查容器网络
docker network ls
docker network inspect history_net

# 重新创建网络
docker-compose down -v
docker-compose up -d
```

## 关键文件位置

- **Docker 配置**: `/Users/afei/projects/demo/daizhigev20/docker-compose.yml`
- **Elasticsearch 配置**: `/Users/afei/projects/demo/daizhigev20/docker/elasticsearch.yml`
- **Redis 配置**: `/Users/afei/projects/demo/daizhigev20/docker/redis.conf`
- **启动脚本**: `/Users/afei/projects/demo/daizhigev20/start_services.sh`

## 预计启动时间

- **第一次启动**（需要拉取镜像）：5-10 分钟
- **后续启动**：1-2 分钟

## 下一步

容器启动完成后，执行第二步：

```bash
cd /Users/afei/projects/demo/daizhigev20
pip install -r requirements.txt
```

详见：`QUICKSTART.md`
