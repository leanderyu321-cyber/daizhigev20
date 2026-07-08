# 🔍 Elasticsearch 搜索模式详解

## 问题描述

当搜索"诸葛亮"这样的中文短语时，URL 编码后为 `%E8%AF%B8%E8%91%9B%E4%BA%AE`。
默认搜索会将其分解为单个字符 "诸"、"葛"、"亮" 分别搜索，导致结果不够精确。

## 解决方案：三种搜索模式

现在已支持三种搜索模式，针对不同场景优化搜索结果。

### 1️⃣ **best 模式**（默认，推荐）

**特点**：优先短语匹配，备选单词匹配
- 短语精确匹配得分更高
- 单字/单词作为备选
- 平衡精度和召回率

**使用场景**：
- 通用搜索
- 不确定搜索词是短语还是单词

**示例**：
```bash
# HTTP API
curl "http://localhost:8000/search?q=诸葛亮&mode=best"
curl "http://localhost:8000/search?q=Docker&mode=best"

# 命令行
python index_markdown_to_es.py --search "诸葛亮" --search-mode best
```

**结果特点**：
- 匹配度高的文档排在前面
- 包含"诸"或"葛"或"亮"的文档也会返回（召回率高）

---

### 2️⃣ **phrase 模式**（精确短语匹配）

**特点**：只匹配完整的连续短语
- 要求词序完全相同
- 只返回包含整个短语的文档
- 精度最高，但召回率较低

**使用场景**：
- 精确搜索人名、地名、专业术语
- 搜索多词复合词
- 需要精确结果的场景

**示例**：
```bash
# HTTP API - 搜索"诸葛亮"作为完整短语
curl "http://localhost:8000/search?q=诸葛亮&mode=phrase"

# HTTP API - 搜索"Docker 容器"
curl "http://localhost:8000/search?q=Docker容器&mode=phrase"

# 命令行
python index_markdown_to_es.py --search "诸葛亮" --search-mode phrase
```

**结果特点**：
- 只返回包含"诸葛亮"（连续）的文档
- 不返回只有"诸"或"葛"或"亮"的文档
- 完全准确但可能遗漏相关文档

---

### 3️⃣ **fuzzy 模式**（模糊匹配）

**特点**：容错拼写错误，支持近似匹配
- 允许字符替换、插入、删除
- 自动计算编辑距离
- 适合处理输入错误

**使用场景**：
- 用户可能输入有误
- 处理多字输入的容错
- 方言或简体/繁体转换

**示例**：
```bash
# HTTP API - 搜索"Docker"（容错）
curl "http://localhost:8000/search?q=Dockar&mode=fuzzy"

# 命令行
python index_markdown_to_es.py --search "Dockar" --search-mode fuzzy
```

**结果特点**：
- 能匹配轻微的拼写错误
- 返回相似的结果
- 召回率高但可能包含不相关结果

---

## 🎯 搜索建议

### 按搜索类型选择模式

| 搜索类型 | 推荐模式 | 示例 |
|---------|--------|------|
| 英文词汇（单个）| best | `Docker`, `Python` |
| 中文词汇（单个）| best | `诗`, `藏` |
| 人名/地名 | phrase | `诸葛亮`, `长安城` |
| 多词短语 | phrase | `容器化部署`, `知识库系统` |
| 有输入错误 | fuzzy | `Dokcer`, `Esaticsearch` |
| 英文短语 | best | `Deep Search`, `Docker Compose` |

### 实际搜索示例

#### ✅ 搜索"诸葛亮"的正确方式

```bash
# 方式 1：phrase 模式（最精确）
curl "http://localhost:8000/search?q=诸葛亮&mode=phrase&size=10"

# 方式 2：best 模式（平衡）
curl "http://localhost:8000/search?q=诸葛亮&mode=best&size=10"

# 命令行版本
python index_markdown_to_es.py --search "诸葛亮" --search-mode phrase
```

#### ✅ 搜索"Docker"的正确方式

```bash
# 推荐：best 模式（包括 Docker、docker、Docker 相关内容）
curl "http://localhost:8000/search?q=Docker&mode=best&size=10"

# 严格模式：phrase（只要"Docker"连续出现的）
curl "http://localhost:8000/search?q=Docker&mode=phrase&size=10"
```

---

## 📊 搜索模式性能对比

| 指标 | best | phrase | fuzzy |
|------|------|--------|-------|
| 精度 | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| 召回率 | ⭐⭐⭐⭐ | ⭐⭐ | ⭐⭐⭐⭐ |
| 速度 | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ |
| 推荐频度 | 🔥🔥🔥 | 🔥🔥 | 🔥 |

---

## 🛠 API 文档

### GET /search

**参数**：
- `q` (必需)：搜索关键词
- `size` (可选，默认10)：返回结果数，最多100
- `mode` (可选，默认best)：搜索模式 `best|phrase|fuzzy`
- `highlight` (可选，默认true)：是否返回高亮内容

**响应格式**：
```json
{
  "query": "诸葛亮",
  "mode": "phrase",
  "total": 42,
  "took_ms": 15,
  "results": [
    {
      "file_name": "三国演义.md",
      "file_path": "诗藏/三国演义.md",
      "title": "三国演义第一卷",
      "score": 4.87,
      "word_count": 5000,
      "size_kb": 120.5,
      "title_highlight": "...关于<em>诸葛亮</em>的故事...",
      "content_highlights": [
        "...在三国时期，<em>诸葛亮</em>是杰出的...",
        "...<em>诸葛亮</em>辅佐刘备建立蜀汉...",
        "...后人评价<em>诸葛亮</em>为智者..."
      ]
    }
  ]
}
```

---

## 💡 高级用法

### 结合 jq 处理结果

```bash
# 只显示文件名和标题
curl -s "http://localhost:8000/search?q=诸葛亮&mode=phrase" | \
  jq '.results[] | "\(.file_name): \(.title)"'

# 按匹配度排序
curl -s "http://localhost:8000/search?q=Docker&mode=best" | \
  jq '.results | sort_by(-.score) | .[] | {file_name, score}'

# 统计搜索结果
curl -s "http://localhost:8000/search?q=诗" | \
  jq '.total'
```

### 编程使用（Python）

```python
import requests

# best 模式搜索
response = requests.get("http://localhost:8000/search", params={
    "q": "诸葛亮",
    "mode": "phrase",
    "size": 10
})

results = response.json()
for item in results['results']:
    print(f"{item['file_name']}: {item['score']}")
```

---

## ❓ 常见问题

**Q: 为什么 phrase 模式有时返回 0 结果？**  
A: phrase 模式要求精确匹配短语。如果文档中词序不同或有其他词插入，就不会匹配。改用 best 模式或检查搜索词拼写。

**Q: 搜索"东西"为什么返回很多无关结果？**  
A: 这是中文分词的挑战。"东"和"西"各自都能单独匹配很多文档。建议用 phrase 模式精确搜索"东西"短语。

**Q: 如何搜索带空格的短语？**  
A: 可以直接搜索：`"Docker Compose"` 或 `"Docker容器"`。API 会自动处理。

**Q: fuzzy 模式太慢了？**  
A: 模糊匹配确实较慢。建议只在需要容错时使用。对于大规模索引，建议使用 best 或 phrase。

---

## 📝 更新日志

### v2.0 (当前版本)
- ✅ 新增三种搜索模式
- ✅ 支持短语精确匹配
- ✅ 添加模糊搜索
- ✅ 改进中文搜索体验
- ✅ 完善搜索高亮显示

