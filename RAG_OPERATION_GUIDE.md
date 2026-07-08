# 殆知阁古籍 RAG 操作指南

> 将 800+ 册中国古典文献向量化，为本地大模型提供知识库，
> 实现基于古籍资料的智能问答。

---

## 目录

1. [项目概览](#1-项目概览)
2. [环境准备](#2-环境准备)
3. [向量化流程](#3-向量化流程)
4. [RAG 测试](#4-rag-测试)
5. [双方案切分说明](#5-双方案切分说明)
6. [命令速查表](#6-命令速查表)
7. [常见问题](#7-常见问题)

---

## 1. 项目概览

### 1.1 系统架构

```
┌─────────────────────────────────────────────────────┐
│  古籍文本 (800+ .md 文件 / 儒藏医藏史藏等 9 大类)    │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│  双方案切分                                           │
│  ├─ 方案A: 语义切分 (500字/20%重叠)                 │
│  └─ 方案B: 精确切分 (150字/30%重叠)                 │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│  Ollama nomic-embed-text → 768维向量                  │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│  ChromaDB (本地持久化向量库)                          │
│  集合: classical_chinese_corpus                      │
│  每条记录带 chunk_scheme 标签区分方案                 │
└──────────────────┬──────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────┐
│  RAG 问答                                            │
│  ├─ 搜索: 你的问题 → nomic-embed → ChromaDB 检索     │
│  └─ 回答: 检索结果 + qwen3:8b → 带引用的回答          │
└─────────────────────────────────────────────────────┘
```

### 1.2 依赖组件

| 组件 | 版本 | 说明 |
|------|------|------|
| Ollama | 0.31+ | 本地模型运行框架 |
| nomic-embed-text | latest | 向量嵌入模型（274MB） |
| qwen3:8b-q4_K_M | latest | 问答大模型（5.2GB） |
| ChromaDB | 1.5+ | 本地向量数据库 |
| Python | 3.12+ | 运行环境 |

---

## 2. 环境准备

### 2.1 启动 Ollama

```bash
# 启动 Ollama 服务（如果已在后台运行则跳过）
ollama serve

# 确认可用模型
ollama list
```

预期输出应包含：

```
NAME                       ID              SIZE      MODIFIED
qwen3:8b-q4_K_M            500a1f067a9f    5.2 GB    ...
nomic-embed-text:latest    0a109f422b47    274 MB    ...
```

> ⚠️ 如果缺少某个模型，用 `ollama pull <模型名>` 下载。

### 2.2 激活 Python 环境

```bash
cd /path/to/daizhigev20
source .venv/bin/activate
```

> 首次使用需要创建虚拟环境并安装依赖：
> ```bash
> uv venv .venv
> source .venv/bin/activate
> uv pip install chromadb tqdm requests PyYAML
> ```

---

## 3. 向量化流程

### 3.1 快速上手

最小的完整流程：

```bash
source .venv/bin/activate

# 先测试一个小范围
python vectorize_for_rag.py --source 医藏 --limit 3

# 确认无误后处理全部
python vectorize_for_rag.py --source 医藏
```

### 3.2 分步说明

#### ① 先预览统计（不写入）

```bash
python vectorize_for_rag.py --dry-run --source 医藏
```

输出示例：

```
📊 Dry-run 统计:
  文件数: 911
  语义切片: 1258
  精确切片: 6245
  合计切片: 7503
```

#### ② 正式索引

```bash
# 处理单个目录（推荐先试这个）
python vectorize_for_rag.py --source 医藏

# 处理全部 9 个目录（800+ 文件，预计 6-8 小时）
python vectorize_for_rag.py
```

#### ③ 清空重建

```bash
python vectorize_for_rag.py --clear --source 医藏
```

### 3.3 查看索引状态

```bash
python vectorize_for_rag.py --stats
```

输出示例：

```
📊 ChromaDB 索引统计
  集合: classical_chinese_corpus
  总记录: 7503

按方案:
  semantic    : 1258
  precision   : 6245

按藏书分类:
  医藏      : 7503

  磁盘占用: 35.58 MB
```

---

## 4. RAG 测试

### 4.1 基本问答

```bash
source .venv/bin/activate

# 最简用法（自动混合两种方案检索）
python rag_test.py "太阳病有什么症状"
```

输出示例：

```
📖 检索到 8 条相关片段 (双方案合并)
  [1] (0.7374) [semantic] 辨术者太素脉论...
  [2] (0.7374) [precision] 辨术者太素脉论...
  [...]

🤖 正在调用 qwen3:8b-q4_K_M 生成回答...

────────────────────────────────────────────
  ❓ 太阳病有什么症状
────────────────────────────────────────────

  根据《伤寒论》记载，太阳病的典型症状包括：
  1. **脉浮**：脉象浮取即得
  2. **头项强痛**：头痛、颈项僵硬疼痛
  3. **恶寒**：怕冷
  [出处: 医藏/伤寒论.md]

────────────────────────────────────────────
  引用 8 条文献 | 方案: 双方案合并
────────────────────────────────────────────
```

### 4.2 单方案测试

```bash
# 只用语义切分
python rag_test.py --scheme semantic "辨证论治的核心思想"

# 只用精确切分
python rag_test.py --scheme precision "太阳之为病"
```

### 4.3 双方案对比测试

```bash
python rag_test.py --compare "六经辨证"
```

分别输出两种方案的检索结果和 AI 回答，直观对比效果。

### 4.4 交互模式

```bash
python rag_test.py --interactive
```

进入交互式问答界面，支持以下命令：

| 命令 | 说明 |
|------|------|
| 输入问题 | 直接提问 |
| `/compare` | 进入双方案对比 |
| `/help` | 显示帮助 |
| `/quit` | 退出 |

### 4.5 其他输出模式

```bash
# 简洁模式（只显示问答，不显示检索细节）
python rag_test.py --raw "脉浮是什么意思"

# 详细模式（显示完整检索到的原文）
python rag_test.py --verbose "伤寒论"

# 控制检索条数
python rag_test.py --top-k 12 "阳明病"
```

---

## 5. 双方案切分说明

### 5.1 设计背景

古文与现代文差异巨大：

- 古文极简，单字即可成词成句
- 缺少空格和现代标点
- 同一段话在不同上下文中意义不同

单一分块策略要么丢失细节，要么丢失上下文。
两种方案互补，兼顾 **精度** 和 **语义**。

### 5.2 方案对比

| 特性 | 方案A：语义切分 | 方案B：精确切分 |
|------|---------------|---------------|
| **chunk_size** | 500 字符 | 150 字符 |
| **重叠率** | 20% | 30% |
| **断开策略** | 段落 > 句号 | 句号 > 逗号 > 硬切 |
| **切片数占比** | ~17% | ~83% |
| **目标** | 语义检索、RAG 问答 | 精确匹配、典出查询 |
| **适合问题** | "解释辨证论治" | "太阳之为病出自哪里" |

### 5.3 数据流向

```
古籍.md
   │
   ├─→ SemanticChunker → 语义切片 → ChromaDB (chunk_scheme="semantic")
   │
   └─→ PrecisionChunker → 精确切片 → ChromaDB (chunk_scheme="precision")
```

搜索时，`rag_test.py` 默认同时检索两种方案并合并排序，
也可以通过 `--scheme` 只检索其中一种。

---

## 6. 命令速查表

### 向量化

| 命令 | 说明 |
|------|------|
| `python vectorize_for_rag.py` | 处理全部 9 个藏书目录 |
| `python vectorize_for_rag.py --source 医藏` | 只处理指定目录 |
| `python vectorize_for_rag.py --limit 10` | 只处理前 10 个文件 |
| `python vectorize_for_rag.py --dry-run` | 只统计，不写入 |
| `python vectorize_for_rag.py --clear` | 清空后重建 |
| `python vectorize_for_rag.py --stats` | 查看索引统计 |

### RAG 测试

| 命令 | 说明 |
|------|------|
| `python rag_test.py "问题"` | 基本问答（双方案合并） |
| `python rag_test.py --scheme semantic "问题"` | 只用语意方案 |
| `python rag_test.py --scheme precision "问题"` | 只用精确方案 |
| `python rag_test.py --compare "问题"` | 双方案对比 |
| `python rag_test.py --verbose "问题"` | 详细模式 |
| `python rag_test.py --raw "问题"` | 简洁模式 |
| `python rag_test.py --top-k 20 "问题"` | 更多检索结果 |
| `python rag_test.py --interactive` | 交互模式 |
| `python rag_test.py --help` | 查看完整帮助 |

---

## 7. 常见问题

### Q: Ollama 连接失败

```
❌ Ollama 连接失败: ...
```

**解决**：先启动 Ollama 服务

```bash
# 后台启动
ollama serve &

# 确认可用
curl http://localhost:11434/api/tags
```

### Q: ChromaDB 集合不存在

```
❌ ChromaDB 连接失败: Collection [classical_chinese_corpus] does not exist
```

**解决**：先运行向量化脚本

```bash
python vectorize_for_rag.py --source 医藏 --limit 5
```

### Q: 搜索不到相关内容

```
❌ 未找到与 '...' 相关的内容
```

**原因**：当前索引的数据量不足以覆盖查询。例如只索引了医藏，却问儒藏的内容。

**解决**：

```bash
# 查看当前索引了哪些分类
python vectorize_for_rag.py --stats

# 增加数据
python vectorize_for_rag.py --source 儒藏
```

### Q: 模型回答质量不理想

**原因排查**：

1. **检索不足** → 增加 `--top-k`（如 `--top-k 15`）
2. **数据不足** → 向量化更多相关目录
3. **切分方案不匹配** → 切换 `--scheme` 试试
4. **模型能力限制** → qwen3:8b 对古文有一定理解力，但仍有限

### Q: 索引时间太长

9 个目录约 800 个文件，全量索引预计 6-8 小时。

**分批策略**：

```bash
# 逐个分类处理
python vectorize_for_rag.py --source 医藏   # ~1小时
python vectorize_for_rag.py --source 儒藏   # ~1小时
python vectorize_for_rag.py --source 史藏   # ~2小时
# ... 依此类推
```

每次处理会自动追加到已有索引，不会覆盖。

---

> **最后更新**: 2026-07-08
> **脚本文件**: `vectorize_for_rag.py` | `rag_test.py`
> 
> 关于双方案的设计细节或参数调优，请查看脚本开头的注释文档。
