# 本地历史知识库 Deep Search 系统 —— 快速开始指南

## 系统架构概览

这是一个分布式的古籍深度搜索系统，包含两个独立的子系统：

1. **语料库工程（系统一）**：处理、切分、翻译、索引古籍文献
2. **Deep Search引擎（系统二）**：多角色协作的迭代检索系统

两个子系统通过NAS上的共享存储（Elasticsearch + Qdrant + Redis）解耦。

## 第一步：部署底层存储服务（NAS/本地）

### 使用Docker Compose启动服务

```bash
# 1. 复制环境配置
cp .env.example .env

# 2. 启动Docker容器（需要安装Docker和Docker Compose）
docker-compose up -d

# 3. 验证服务状态
docker-compose ps

# 4. 检查各服务健康状态
curl http://localhost:9200/_cluster/health     # Elasticsearch
curl http://localhost:6333/health               # Qdrant
redis-cli ping                                   # Redis
```

### 验证服务连接

```bash
python -c "
from shared.config import get_es_config, get_qdrant_config, get_redis_config
es = get_es_config()
qdrant = get_qdrant_config()
redis = get_redis_config()
print(f'ES: {es.URL}')
print(f'Qdrant: {qdrant.URL}')
print(f'Redis: {redis.HOST}:{redis.PORT}')
"
```

## 第二步：安装Python依赖

```bash
pip install -r requirements.txt
```

### 模型下载（可选，首次需要）

```bash
# 古文断句模型
python -m huggingface_hub download GuwenBERT/guwen-punc --local-dir ./models/guwen-punc

# 古文NER模型
python -m huggingface_hub download GuwenBERT/guwen-ner --local-dir ./models/guwen-ner

# Embedding模型（bge-m3）
python -m huggingface_hub download BAAI/bge-m3 --local-dir ./models/bge-m3

# 古文翻译模型（XunziChat）
python -m huggingface_hub download Xunzi-LLM-of-Chinese-classics/XunziChat --local-dir ./models/XunziChat
```

## 第三步：处理语料库

### 快速测试（小规模样本）

```bash
# 处理单个语料库目录
cd corpus_pipeline
python pipeline_runner.py

# 或指定特定的语料库来源
python -c "
from pipeline_runner import CorpusPipeline
from pathlib import Path

pipeline = CorpusPipeline()
corpus_dir = Path('../史藏')
if corpus_dir.exists():
    results = pipeline.process_corpus_directory(corpus_dir)
    for file_path, count in results.items():
        print(f'{file_path}: {count} chunks')
"
```

### 监控处理进度

```bash
# 查看处理状态
redis-cli KEYS "corpus_pipeline:progress:*"
redis-cli GET "corpus_pipeline:progress:某个任务ID"

# 查看索引统计
curl -X GET "http://localhost:9200/history_corpus/_stats"
```

### 断点续跑

```bash
# 重新运行pipeline_runner.py，系统会自动：
# 1. 检查Redis中是否有未完成的任务
# 2. 跳过已处理的文件
# 3. 从断点继续处理
python pipeline_runner.py
```

## 第四步：运行Deep Search查询

```bash
# 示例：查询"建炎南渡"相关的历史资料
python -c "
from deepsearch_engine.main import DeepSearchEngine

engine = DeepSearchEngine()
topic = '建炎南渡'
report = engine.search(topic)
print(report)
"
```

## 文件结构说明

```
daizhigev20/
├── shared/
│   ├── schema.py          # 数据契约定义（所有字段名从这里导入）
│   └── config.py          # 全局配置（从.env读取）
│
├── corpus_pipeline/       # 系统一：语料库工程
│   ├── ingestion/         # 加载原始文本
│   ├── preprocessing/     # 清洗、断句
│   ├── chunking/          # 分块
│   ├── translation/       # 古文翻译
│   ├── enrichment/        # 实体抽取（NER）
│   ├── indexing/          # 写入ES和Qdrant
│   ├── pipeline_runner.py # 主编排脚本
│   └── state_manager.py   # 断点续跑状态管理
│
├── deepsearch_engine/     # 系统二：Deep Search引擎
│   ├── roles/             # 多角色实现（PLANNER, ANALYST等）
│   ├── retrieval_layer/   # 检索封装
│   ├── orchestrator/      # 主循环编排
│   ├── evidence_store/    # 证据池和事实卡片
│   ├── logging/           # 搜索过程日志
│   ├── llm_backend/       # LLM推理后端
│   └── main.py            # CLI入口
│
├── output/                # 输出目录
│   ├── reports/           # 最终报告
│   ├── logs/              # 搜索过程日志（JSON Lines格式）
│   └── checkpoints/       # 断点续跑快照
│
├── docker/                # Docker配置
│   ├── elasticsearch.yml  # ES配置
│   └── redis.conf         # Redis配置
│
├── docker-compose.yml     # 一键启动所有服务
└── requirements.txt       # Python依赖
```

## 关键概念

### 1. 数据契约（Shared Schema）

所有字段名统一在 `shared/schema.py` 中定义，避免硬编码：

```python
from shared.schema import ESFields, QdrantFields

# 使用字段常量，而不是字符串
doc[ESFields.CONTENT]  # ✓
doc["content"]         # ✗ 禁止硬编码
```

### 2. 断点续跑

系统会自动保存进度到Redis，支持中断后恢复：

- 语料库处理：按文件粒度记录进度
- Deep Search：按搜索轮次记录状态

### 3. 上下文窗口管理

为了在小模型上运行长任务，系统采用多层压缩：

- 事实卡片（Fact Card）：将原文压缩为结构化摘要
- 滚动摘要（Rolling Summary）：保持固定长度，避免线性增长

### 4. 混合检索（Hybrid Search）

结合三种检索方式：

- Jieba分词检索（关键词精度高）
- Bigram检索（容错能力强）
- 向量语义检索（语义相似度）

通过RRF（Reciprocal Rank Fusion）融合结果。

## 故障排查

### Elasticsearch连接失败

```bash
# 检查服务是否运行
docker-compose ps | grep elasticsearch

# 查看日志
docker-compose logs elasticsearch

# 重启服务
docker-compose restart elasticsearch
```

### 内存溢出

```bash
# 增加Docker容器内存限制
# 编辑 docker-compose.yml：
# services:
#   elasticsearch:
#     mem_limit: 8g

docker-compose up -d
```

### 模型下载超时

```bash
# 手动指定模型路径
export HF_HOME=/path/to/huggingface/cache

# 或在.env中配置
GUWEN_PUNCTUATION_MODEL=/local/path/to/model
```

## 性能优化建议

1. **增加并发度**：调整 `MAX_WORKERS` 和 `CONCURRENT_QUERIES`
2. **批量索引**：增加 `EMBEDDING_BATCH_SIZE`
3. **启用GPU**：设置 `EMBEDDING_GPU_ID`
4. **缓存embedding**：复用已生成的向量，避免重复计算

## 下一步

- 查看 `history_deepsearch_implementation_plan-2.md` 了解详细的系统设计
- 阅读 `shared/schema.py` 理解数据结构
- 运行单元测试：`pytest corpus_pipeline/tests/`
- 自定义配置：编辑 `.env` 文件

---

**更新日期**：2024-07-06  
**版本**：阶段一（数据底座）
