# 🔍 Elasticsearch Markdown 搜索系统

## 快速开始（3 步）

### 1️⃣ 启动服务
```bash
docker-compose up -d  # 启动 Elasticsearch
```

### 2️⃣ 索引 Markdown 文件
```bash
source .venv/bin/activate
python index_markdown_to_es.py --limit 500  # 测试用（500个文件）
# 或
python index_markdown_to_es.py               # 完整索引（16,145个文件）
```

### 3️⃣ 启动搜索 API（可选）
```bash
python search_api.py
# 然后访问 http://localhost:8000/docs 查看文档
```

---

## 📚 使用方法

### 方法 A：命令行搜索

```bash
# 搜索关键词
python index_markdown_to_es.py --search "Docker"

# 查看统计
python index_markdown_to_es.py --stats
```

### 方法 B：HTTP API 搜索

```bash
# 启动 API 后，通过 curl 搜索
curl "http://localhost:8000/search?q=Docker&size=5"

# Swagger 文档
open http://localhost:8000/docs
```

### 方法 C：直接使用 Elasticsearch

```bash
# 基础搜索
curl "localhost:9200/markdown_docs/_search?q=Docker"

# 高级查询
curl -X GET "localhost:9200/markdown_docs/_search" -H 'Content-Type: application/json' -d'{
  "query": {
    "multi_match": {
      "query": "Python",
      "fields": ["title^3", "content"]
    }
  }
}'
```

---

## 🎯 使用场景

| 场景 | 命令 |
|------|------|
| 快速搜索测试 | `python index_markdown_to_es.py --search "关键词"` |
| 集成到应用 | 使用 `search_api.py` 的 `/search` 端点 |
| 大规模索引 | `python index_markdown_to_es.py`（所有16,145文件） |
| 重新索引 | `python index_markdown_to_es.py --clear` |

---

## ✨ 功能特性

✅ **支持中文搜索** - 支持中文内容的全文搜索  
✅ **多字段搜索** - 在标题和内容中搜索  
✅ **搜索高亮** - 返回匹配内容的高亮片段  
✅ **相关性排序** - 按匹配度排序结果  
✅ **性能优化** - 预配置的索引映射和分析器  

---

## 📊 当前状态

- ✅ Elasticsearch 8.10.0 已运行
- ✅ 索引脚本已创建（index_markdown_to_es.py）
- ✅ API 服务已创建（search_api.py）
- ⏳ 等待索引 Markdown 文件

---

## 🚀 下一步

1. 运行 `python index_markdown_to_es.py` 索引所有文件
2. 启动 `python search_api.py` 开启搜索 API
3. 在应用中集成搜索功能

---

详见 `ELASTICSEARCH_GUIDE.md` 获取完整文档
