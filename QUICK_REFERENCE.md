# 快速参考卡 —— 本地历史知识库 Deep Search 系统

## 🚀 3 个核心命令

```bash
# 1️⃣ 启动 Docker 容器（第一次运行需要 5-10 分钟）
cd /Users/afei/projects/demo/daizhigev20
docker-compose up -d

# 2️⃣ 安装 Python 依赖（在容器启动完成后）
pip install -r requirements.txt

# 3️⃣ 运行测试验证框架就绪
pytest corpus_pipeline/tests/test_end_to_end_sample.py -v
```

## 📊 监控容器状态

```bash
# 查看所有容器
docker-compose ps

# 实时查看日志
docker-compose logs -f

# 特定容器的日志
docker-compose logs elasticsearch
docker-compose logs qdrant
docker-compose logs redis
```

## ✅ 验证服务是否正常

```bash
# Elasticsearch (应该返回 "green" 状态)
curl http://localhost:9200/_cluster/health

# Qdrant (应该返回 {"ok":true})
curl http://localhost:6333/health

# Redis (应该返回 PONG)
redis-cli ping
```

## 🔧 常见操作

```bash
# 停止容器
docker-compose down

# 停止并清除所有数据（重新开始）
docker-compose down -v

# 重启容器
docker-compose restart

# 查看容器网络
docker network inspect history_net

# 进入容器调试
docker-compose exec elasticsearch bash
docker-compose exec qdrant bash
docker-compose exec redis sh
```

## 📁 项目目录结构

```
daizhigev20/
├── shared/                    # 数据契约层
│   ├── schema.py             # 关键：所有字段定义
│   └── config.py             # 统一配置
│
├── corpus_pipeline/           # 语料库处理系统
│   ├── pipeline_runner.py     # 主执行入口
│   ├── state_manager.py       # 断点续跑状态
│   └── ...子模块...
│
├── deepsearch_engine/         # Deep Search 引擎框架
│
├── docker-compose.yml         # 一键启动配置
├── requirements.txt           # Python 依赖
└── 文档/
    ├── QUICKSTART.md                    # 完整快速开始
    ├── DOCKER_STARTUP_COMMANDS.md       # Docker 诊断指南
    └── IMPLEMENTATION_PROGRESS.md       # 详细实施路线图
```

## 🔴 故障排查

| 问题 | 解决方案 |
|------|--------|
| 端口被占用 | `lsof -i :9200` / `:6333` / `:6379` 找到进程后 `kill -9 <PID>` |
| Docker 响应慢 | 等待 2-3 分钟，或重启 Docker Desktop |
| 镜像拉取失败 | 检查网络连接，或使用代理 |
| 磁盘空间不足 | `df -h /` 检查，需要 20GB+ 空闲 |
| 内存溢出 | 编辑 docker-compose.yml 降低内存限制 |

## 📍 关键文件位置

| 文件 | 用途 |
|------|------|
| `shared/schema.py` | 所有字段定义（改动影响全系统） |
| `shared/config.py` | 全局配置（从 .env 读取） |
| `corpus_pipeline/pipeline_runner.py` | 语料处理主程序 |
| `docker-compose.yml` | 容器编排配置 |
| `.env.example` | 配置模板 |

## 🎯 当前阶段

**阶段一（数据底座）**: ✅ 100% 完成
- 架构设计完整
- 框架代码就绪
- 基础设施部署配置完成

**下一步**：集成古文模型 + 完整系统验证

## 💡 技术栈速查

| 组件 | 技术 | 端口 |
|------|------|------|
| 索引引擎 | Elasticsearch 8.10 | 9200 |
| 向量库 | Qdrant | 6333 |
| 状态存储 | Redis 7.2 | 6379 |
| 分词 | Jieba | - |
| Embedding | BGE-M3 | - |
| LLM | Qwen2.5-7B | - |

## 📞 常见问题

**Q: Docker 容器需要多长时间启动?**
A: 首次启动 5-10 分钟（拉取镜像），之后 1-2 分钟。

**Q: 可以修改容器配置吗?**
A: 可以。编辑 `docker-compose.yml`，然后运行 `docker-compose up -d`。

**Q: 如何查看容器内部的文件?**
A: `docker-compose exec <service> ls -la <path>`

**Q: 可以同时运行多个项目吗?**
A: 可以，但要改端口避免冲突。编辑 `docker-compose.yml` 的 ports 字段。

---

**更新日期**: 2024-07-06  
**维护者**: Claude Copilot
