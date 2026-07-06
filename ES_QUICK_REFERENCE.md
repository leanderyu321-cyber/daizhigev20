# 🔍 Elasticsearch 快速参考卡

## 立即可用命令

```bash
# 1. 激活环境
source .venv/bin/activate

# 2. 快速索引测试（100个文件）
python index_markdown_to_es.py --limit 100

# 3. 快速搜索测试
python index_markdown_to_es.py --search "Docker"
python index_markdown_to_es.py --search "诗"
python index_markdown_to_es.py --search "Redis"

# 4. 查看统计
python index_markdown_to_es.py --stats
```

## API 搜索（3 个例子）

```bash
# 搜索 Docker
curl "http://localhost:8000/search?q=Docker&size=3" | jq '.results'

# 搜索 Redis
curl "http://localhost:8000/search?q=Redis&size=5" | jq '.results'

# 搜索中文 "诗"
curl "http://localhost:8000/search?q=诗&size=10" | jq '.results'

# 健康检查
curl "http://localhost:8000/health"
```

## 索引选项

| 命令 | 文件数 | 耗时 | 用途 |
|------|--------|------|------|
| `--limit 100` | 100 | <1分钟 | 快速测试 |
| `--limit 500` | 500 | 2分钟 | 中等测试 |
| （默认） | 16,145 | 5-10分钟 | 完整索引 |
| `--clear` | - | - | 清空重建 |

## 关键概念

- **索引名**：`markdown_docs`
- **文档类型**：Markdown 文件
- **搜索字段**：标题（权重 3x）和内容
- **支持语言**：中英文混合

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| ES 无法连接 | `curl http://localhost:9200` |
| 搜索无结果 | 确认文件已索引：`curl localhost:9200/markdown_docs/_count` |
| API 无响应 | 确认服务运行：`curl http://localhost:8000/health` |
| 索引慢 | 增加 JVM 内存：`ES_JAVA_OPTS=-Xms2g -Xmx2g` |

---

**更多信息**：`ELASTICSEARCH_GUIDE.md`
