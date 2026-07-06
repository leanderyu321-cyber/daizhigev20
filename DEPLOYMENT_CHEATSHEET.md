# ⚡ 部署速查表

## 🚀 初次部署（完整安装）

### Linux / macOS

```bash
# 方案 A：Bash 脚本（推荐）
curl -o deploy.sh https://raw.githubusercontent.com/leanderyu321-cyber/daizhigev20/main/deploy.sh
chmod +x deploy.sh
./deploy.sh

# 方案 B：Python 脚本
python3 deploy.py
```

### Windows (WSL 2 / Git Bash)

```bash
# 同上
python3 deploy.py
```

---

## 📋 部署配置速查

| 需求 | 命令 |
|------|------|
| 默认配置 | `./deploy.sh` |
| 自定义端口 8080 | `./deploy.sh --port 8080` |
| 自定义目录 | `./deploy.sh --dir /opt/myapp` |
| 跳过 Docker | `./deploy.sh --skip-docker` |
| 自定义仓库 | `./deploy.sh --repo <url>` |

---

## 🎯 常用命令

| 操作 | 命令 |
|------|------|
| **启动** | `bash startup.sh start` |
| **停止** | `bash startup.sh stop` |
| **重启** | `bash startup.sh restart` |
| **查看状态** | `bash startup.sh status` |
| **查看日志** | `bash startup.sh logs` |
| **测试搜索** | `bash startup.sh test` |

---

## 🔍 搜索示例

```bash
# 精确搜索
curl "http://localhost:8000/search?q=诸葛亮&mode=phrase&page=1&size=10"

# 综合搜索
curl "http://localhost:8000/search?q=诸葛亮&mode=best&page=1&size=10"

# 容错搜索
curl "http://localhost:8000/search?q=诸葛蛮&mode=fuzzy&page=1&size=10"
```

---

## 🐳 Docker 命令

```bash
# 查看 Docker 日志
docker-compose -f ~/daizhigev20/docker-compose.yml logs -f

# 重启 Docker
docker-compose -f ~/daizhigev20/docker-compose.yml restart

# 停止 Docker
docker-compose -f ~/daizhigev20/docker-compose.yml down

# 重建索引
cd ~/daizhigev20
python .venv/bin/python index_markdown_to_es.py --clear
```

---

## 📊 服务状态检查

```bash
# API 状态
curl http://localhost:8000/health

# Elasticsearch 状态
curl http://localhost:9200/_cluster/health

# API 文档
http://localhost:8000/docs
```

---

## ⚠️ 故障排除速查

| 问题 | 解决方案 |
|------|---------|
| Docker 未安装 | `./deploy.sh --skip-docker` 或安装 Docker Desktop |
| 端口占用 | `./deploy.sh --port 9000` 改用其他端口 |
| API 启动失败 | `tail -f /tmp/search_api.log` 查看错误 |
| 索引丢失 | 重建索引: `python index_markdown_to_es.py --clear` |
| Elasticsearch 超时 | 等待 30+ 秒或增加内存配置 |

---

## 📂 项目结构

```
~/daizhigev20/
├── deploy.sh                 ← 部署脚本 (Bash)
├── deploy.py                 ← 部署脚本 (Python)
├── startup.sh                ← 启动/停止脚本
├── search_api.py             ← API 服务
├── index_markdown_to_es.py   ← 索引构建脚本
├── docker-compose.yml        ← Docker 配置
├── .venv/                    ← Python 虚拟环境
├── requirements.txt          ← Python 依赖
└── DEPLOYMENT.md             ← 详细部署指南
```

---

## 🔗 快速链接

| 资源 | URL |
|------|-----|
| **API 搜索** | http://localhost:8000/search |
| **API 文档** | http://localhost:8000/docs |
| **API 健康检查** | http://localhost:8000/health |
| **Elasticsearch** | http://localhost:9200 |
| **GitHub** | https://github.com/leanderyu321-cyber/daizhigev20 |

---

## 🚦 部署流程总结

```
1. 检查环境 ✓
2. 克隆项目 ✓
3. 安装依赖 ✓
4. 启动 Docker ✓
5. 构建索引 ✓
6. 启动 API ✓
7. 验证部署 ✓
```

---

## 💾 日志位置

| 日志 | 位置 |
|------|------|
| API 日志 | `/tmp/search_api.log` |
| Docker 日志 | `docker logs <container_name>` |
| 部署日志 | 脚本输出（实时） |

---

## 🎯 性能指标

| 项目 | 配置 |
|------|------|
| 索引文件数 | 16,160 个 |
| 索引大小 | ~8GB |
| API 端口 | 8000 (可配置) |
| Elasticsearch | 8.10.0 |
| Python | 3.8+ |
| 内存需求 | 8GB+ (推荐) |

---

**最后更新**: 2024-01-XX
