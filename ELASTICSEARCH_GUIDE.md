# 📚 Elasticsearch + Markdown 搜索完整指南

## ✅ 当前状态

- **Elasticsearch 8.10.0** ✓ 已启动
- **搜索索引脚本** ✓ 已创建
- **搜索 API** ✓ 已启动
- **16,145 个 Markdown 文件** ✓ 准备索引

---

## 🚀 快速开始

### 1️⃣ 启动所有服务（Docker）

```bash
# 启动 Elasticsearch、Qdrant、Redis
docker-compose up -d

# 验证服务
docker ps
```

### 2️⃣ 索引 Markdown 文件到 Elasticsearch

#### 方案 A：索引前 N 个文件（推荐用于测试）

```bash
source .venv/bin/activate

# 索引前 500 个文件
python index_markdown_to_es.py --limit 500

# 查看统计
python index_markdown_to_es.py --stats
```

#### 方案 B：索引所有文件（完整索引）

```bash
# 这会索引全部 16,145 个文件（需要几分钟）
python index_markdown_to_es.py

# 显示进度
# 已处理: 100/16145
# 已处理: 200/16145
# ...
```

#### 方案 C：清空并重新索引

```bash
# 删除旧索引，重新创建
python index_markdown_to_es.py --clear

# 然后执行方案 A 或 B
```

### 3️⃣ 使用搜索 API

#### 启动 API 服务

```bash
source .venv/bin/activate
python search_api.py

# 输出：
# 🚀 启动 Markdown 搜索 API
# 📖 文档地址: http://localhost:8000/docs
```

#### 通过 HTTP 搜索

```bash
# 搜索 "Docker" 相关文件
curl "http://localhost:8000/search?q=Docker&size=5"

# 搜索 "诗" 相关内容（中文）
curl "http://localhost:8000/search?q=诗&size=10"

# 搜索 "机器学习"
curl "http://localhost:8000/search?q=机器学习&size=3"
```

#### API 文档

访问 `http://localhost:8000/docs` 获取完整的 Swagger 文档

---

## 📖 API 端点详解

### `GET /search`

搜索 Markdown 内容

**参数：**
- `q` (必需): 搜索关键词
- `size` (可选): 返回结果数，默认 10，最多 100
- `highlight` (可选): 是否返回高亮内容，默认 true

**示例：**

```bash
curl "http://localhost:8000/search?q=Elasticsearch&size=5"
```

**响应：**

```json
{
  "query": "Elasticsearch",
  "total": 7,
  "took_ms": 25,
  "results": [
    {
      "file_name": "DOCKER_STARTUP_COMMANDS.md",
      "file_path": "DOCKER_STARTUP_COMMANDS.md",
      "title": "Docker 容器启动指南",
      "score": 4.06,
      "word_count": 337,
      "size_kb": 3.5,
      "highlights": [
        "...关于 <em>Elasticsearch</em> 的相关内容..."
      ]
    }
  ]
}
```

### `GET /stats`

查看索引统计信息

**示例：**

```bash
curl "http://localhost:8000/stats"
```

**响应：**

```json
{
  "index_name": "markdown_docs",
  "document_count": 500
}
```

### `GET /health`

健康检查

**示例：**

```bash
curl "http://localhost:8000/health"
```

**响应：**

```json
{
  "elasticsearch": "connected",
  "cluster_status": "green",
  "active_shards": 1
}
```

---

## 🔍 命令行搜索示例

### 索引脚本搜索

```bash
source .venv/bin/activate

# 搜索 "Docker"
python index_markdown_to_es.py --search "Docker"

# 搜索 "Python"
python index_markdown_to_es.py --search "Python"

# 搜索 "分布式"
python index_markdown_to_es.py --search "分布式"
```

### 直接使用 curl 查询 Elasticsearch

```bash
# 基础搜索
curl -X GET "localhost:9200/markdown_docs/_search?pretty" -H 'Content-Type: application/json' -d'
{
  "query": {
    "multi_match": {
      "query": "Docker",
      "fields": ["title^3", "content"]
    }
  }
}'

# 模糊搜索
curl -X GET "localhost:9200/markdown_docs/_search?pretty" -H 'Content-Type: application/json' -d'
{
  "query": {
    "match": {
      "content": {
        "query": "Python",
        "fuzziness": "AUTO"
      }
    }
  }
}'
```

---

## 📊 索引管理

### 查看索引信息

```bash
# 列出所有索引
curl "localhost:9200/_cat/indices?v"

# 查看 markdown_docs 索引详情
curl "localhost:9200/markdown_docs?pretty"

# 查看索引映射
curl "localhost:9200/markdown_docs/_mapping?pretty"
```

### 删除索引

```bash
# 删除 markdown_docs 索引
curl -X DELETE "localhost:9200/markdown_docs"
```

### 查看索引中的文档

```bash
# 查看前 10 个文档
curl "localhost:9200/markdown_docs/_search?pretty" -H 'Content-Type: application/json' -d'
{
  "query": {"match_all": {}},
  "size": 10
}'
```

---

## 🔧 性能优化建议

### 对于 16,145 个文件的大规模索引

1. **批量索引**
   ```bash
   # 使用脚本中的分批处理（自动）
   # 每处理 100 个文件输出一次进度
   python index_markdown_to_es.py
   ```

2. **索引设置调优**
   - 当前配置：1 个分片，0 个副本（适合单机）
   - 分片配置已在 `index_markdown_to_es.py` 中定义

3. **搜索性能**
   - 使用 `multi_match` 查询在多字段搜索
   - 对常用字段（title）赋予更高的权重

4. **内存使用**
   - Elasticsearch：512MB JVM（已配置）
   - 可根据需要增加：`docker-compose.yml` 中的 `ES_JAVA_OPTS`

---

## 🐛 故障排查

### 连接问题

```bash
# 测试 Elasticsearch 连接
curl "http://localhost:9200"

# 输出应该类似于：
# {
#   "name": "node-1",
#   "cluster_name": "history_corpus_es",
#   "version": {"number": "8.10.0"}
# }
```

### 索引问题

```bash
# 查看索引是否存在
curl "localhost:9200/_cat/indices" | grep markdown_docs

# 查看索引文档数
curl "localhost:9200/markdown_docs/_count?pretty"

# 查看最近的索引错误
docker logs es_history | tail -50
```

### API 服务问题

```bash
# 检查 API 是否运行
curl "http://localhost:8000/health"

# 查看完整的 API 文档（Swagger）
# 访问 http://localhost:8000/docs
```

---

## 📋 项目文件说明

| 文件 | 功能 |
|------|------|
| `index_markdown_to_es.py` | Markdown 索引脚本 |
| `search_api.py` | REST API 服务 |
| `docker-compose.yml` | 服务编排配置 |
| `docker/elasticsearch.yml` | Elasticsearch 配置 |

---

## 💡 下一步

1. **索引所有文件**：`python index_markdown_to_es.py`
2. **启动 API**：`python search_api.py`
3. **集成到应用**：使用 `/search` 端点实现搜索功能
4. **性能监控**：定期检查索引大小和搜索性能

---

## 📝 注意事项

- 首次索引 16,145 个文件需要 5-10 分钟
- 索引大小预计为 2-3 GB
- 建议在非工作时间执行完整索引
- 可配合 Qdrant 进行向量搜索，实现混合搜索

