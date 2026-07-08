# 🚀 一键部署指南

本项目支持在任何计算机上一键部署，包括初始化、依赖安装、Docker 启动和 API 服务运行。

---

## 快速开始

### 方案 A: 使用 Bash 脚本（推荐 Linux/macOS）

```bash
# 下载部署脚本
curl -o deploy.sh https://raw.githubusercontent.com/leanderyu321-cyber/daizhigev20/main/deploy.sh
chmod +x deploy.sh

# 一键部署（默认配置）
./deploy.sh

# 或指定自定义配置
./deploy.sh --port 9000
./deploy.sh --dir /opt/daizhigev20
```

### 方案 B: 使用 Python 脚本（跨平台）

```bash
# 一键部署
python3 deploy.py

# 或指定自定义配置
python3 deploy.py --port 9000
python3 deploy.py --dir /opt/daizhigev20
```

---

## 系统要求

### 必需

- **Git** - 用于克隆项目
- **Python 3.8+** - 运行 API 服务
- **Docker & Docker Compose** - 运行 Elasticsearch 等服务（可选）

### 可选

- **Docker Desktop** - 如果要使用完整 Docker 部署
- **8GB+ 内存** - 推荐配置（Elasticsearch 需要内存）
- **20GB+ 磁盘空间** - 用于索引和数据

### 操作系统支持

- ✅ Linux (Ubuntu, CentOS, etc.)
- ✅ macOS (Intel/Apple Silicon)
- ✅ Windows (WSL 2 或 Git Bash)

---

## 详细使用

### 1. Bash 脚本选项

```bash
./deploy.sh [选项]

选项:
  --repo <url>      Git 仓库地址
                    默认: https://github.com/leanderyu321-cyber/daizhigev20.git
  
  --dir <path>      项目安装目录
                    默认: ~/daizhigev20
  
  --port <port>     API 服务端口
                    默认: 8000
  
  --skip-docker     跳过 Docker 启动（仅启动 Python API）
                    需要 Elasticsearch 已在 localhost:9200 运行
  
  --help            显示帮助信息
```

#### 示例

```bash
# 标准部署
./deploy.sh

# 自定义端口和目录
./deploy.sh --port 9000 --dir /opt/daizhigev20

# 跳过 Docker（本地 Elasticsearch）
./deploy.sh --skip-docker

# 从自定义仓库部署
./deploy.sh --repo https://github.com/your-name/daizhigev20.git
```

### 2. Python 脚本选项

```bash
python3 deploy.py [选项]

选项:
  --repo <url>      Git 仓库地址
  --dir <path>      项目安装目录
  --port <port>     API 服务端口（默认: 8000）
  --skip-docker     跳过 Docker 启动
```

#### 示例

```bash
# 标准部署
python3 deploy.py

# 自定义端口
python3 deploy.py --port 8080

# 跳过 Docker
python3 deploy.py --skip-docker
```

---

## 部署流程详解

脚本会自动执行以下步骤：

### 1️⃣ 环境检查

```
✅ 检查 Git、Python、Docker 等工具
✅ 验证 Python 版本 >= 3.8
✅ 确认指定端口未被占用
```

### 2️⃣ 项目设置

```
✅ 克隆/更新项目代码
✅ 初始化 Git 仓库
```

### 3️⃣ Python 环境

```
✅ 创建虚拟环境 (.venv)
✅ 升级 pip、setuptools、wheel
✅ 安装依赖包 (requirements.txt)
   - Elasticsearch 客户端
   - FastAPI + Uvicorn
   - 中文处理库
   - 等等...
```

### 4️⃣ Docker 启动

```
✅ 启动 Elasticsearch 8.10.0
✅ 启动 Redis 7.2
✅ 启动 Qdrant 向量数据库
✅ 等待服务就绪 (可能需要 10-30 秒)
```

### 5️⃣ 数据索引

```
✅ 检查是否已有索引
✅ 如果没有：构建 Markdown 索引
   - 可能需要 5-10 分钟
   - 索引 16,160 个文件
   - 生成搜索索引
```

### 6️⃣ API 启动

```
✅ 停止已有的 API 进程
✅ 启动新的 API 服务
✅ 验证 API 是否响应
```

---

## 部署后

### 访问 API

```bash
# 搜索接口
curl "http://localhost:8000/search?q=诸葛亮&mode=phrase"

# API 文档 (Swagger UI)
http://localhost:8000/docs

# 健康检查
curl "http://localhost:8000/health"
```

### 日志查看

```bash
# 查看 API 日志
tail -f /tmp/search_api.log

# 查看 Docker 日志
docker-compose -f ~/daizhigev20/docker-compose.yml logs -f elasticsearch

# 查看所有日志
docker-compose -f ~/daizhigev20/docker-compose.yml logs
```

### 常见命令

```bash
# 停止 API 服务
kill $(cat /tmp/search_api.pid)

# 重启 API 服务
./restart-docker.sh  # 或手动启动

# 停止所有 Docker 服务
cd ~/daizhigev20
docker-compose down

# 重建索引（清空现有索引）
python .venv/bin/python index_markdown_to_es.py --clear

# 查看索引统计
python .venv/bin/python index_markdown_to_es.py --stats
```

---

## 故障排除

### 问题 1: "Docker 未安装"

**解决方案 A**: 安装 Docker
```bash
# macOS
brew install docker docker-compose

# Ubuntu
sudo apt-get install docker.io docker-compose

# 或使用 Docker Desktop
```

**解决方案 B**: 跳过 Docker（使用本地 Elasticsearch）
```bash
./deploy.sh --skip-docker
# 需要 Elasticsearch 已在 localhost:9200 运行
```

### 问题 2: "端口已被占用"

```bash
# 使用不同端口
./deploy.sh --port 9000

# 或查看占用的进程
lsof -i :8000
kill <PID>
```

### 问题 3: "Elasticsearch 启动失败"

```bash
# 检查 Docker 状态
docker ps

# 查看 Elasticsearch 日志
docker logs es_history

# 重启 Docker
cd ~/daizhigev20
docker-compose down
docker-compose up -d
```

### 问题 4: "Python 依赖安装失败"

```bash
# 清除缓存并重新安装
rm -rf ~/.venv
python3 -m venv ~/.venv
source ~/.venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 问题 5: "API 无法启动"

```bash
# 检查日志
tail -f /tmp/search_api.log

# 手动启动以查看错误
cd ~/daizhigev20
source .venv/bin/activate
python search_api.py

# 检查 Elasticsearch 连接
curl http://localhost:9200/_cluster/health
```

---

## 高级配置

### 自定义安装路径

```bash
./deploy.sh --dir /opt/myproject
```

安装完后，所有文件将在 `/opt/myproject`：
- `/opt/myproject/.venv` - Python 虚拟环境
- `/opt/myproject/search_api.py` - API 脚本
- `/opt/myproject/docker-compose.yml` - Docker 配置

### 使用私有仓库

```bash
./deploy.sh --repo https://github.com/your-org/daizhigev20.git
```

### 重新索引数据

```bash
cd ~/daizhigev20
source .venv/bin/activate

# 清空并重新索引
python index_markdown_to_es.py --clear

# 或仅索引部分文件
python index_markdown_to_es.py --limit 1000

# 查看统计
python index_markdown_to_es.py --stats
```

---

## 生产部署

### 使用 Systemd 管理服务

创建 `/etc/systemd/system/daizhigev20-api.service`:

```ini
[Unit]
Description=Daizhigev20 Search API
After=network.target

[Service]
Type=simple
User=nobody
WorkingDirectory=/opt/daizhigev20
ExecStart=/opt/daizhigev20/.venv/bin/python search_api.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl enable daizhigev20-api
sudo systemctl start daizhigev20-api
sudo systemctl status daizhigev20-api
```

### 使用反向代理

配置 Nginx：
```nginx
server {
    listen 80;
    server_name api.example.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 使用 Docker 容器部署

创建 `Dockerfile`:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . .

RUN python -m venv .venv
RUN .venv/bin/pip install -r requirements.txt

EXPOSE 8000

CMD [".venv/bin/python", "search_api.py"]
```

构建并运行：
```bash
docker build -t daizhigev20-api .
docker run -p 8000:8000 --network host daizhigev20-api
```

---

## 性能调优

### Elasticsearch 内存配置

在 `docker/elasticsearch.yml`:
```yaml
ES_JAVA_OPTS: "-Xms2g -Xmx2g"  # 调整为系统总内存的 50%
```

### API 性能

在 `search_api.py` 中：
```python
uvicorn.run(
    app,
    host="0.0.0.0",
    port=8000,
    workers=4  # 增加工作进程数
)
```

---

## 卸载

```bash
# 停止服务
kill $(cat /tmp/search_api.pid)
cd ~/daizhigev20
docker-compose down

# 删除项目目录
rm -rf ~/daizhigev20

# 删除 Docker 数据
docker volume rm daizhigev20_es_data
docker volume rm daizhigev20_qdrant_data
docker volume rm daizhigev20_redis_data
```

---

## 获取帮助

- 📖 [README.md](README.md) - 项目文档
- 🔍 [SEARCH_MODES.md](SEARCH_MODES.md) - 搜索模式说明
- ⚡ [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - 快速参考
- 🐛 GitHub Issues - 报告问题

---

**最后更新**: 2024-01-XX

**支持的部署脚本**:
- ✅ `deploy.sh` - Bash 脚本 (Linux/macOS)
- ✅ `deploy.py` - Python 脚本 (跨平台)
