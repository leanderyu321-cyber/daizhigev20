# 本地历史知识库 Deep Search 系统 —— 实施计划进度

## 当前状态

**总进度**：阶段一（数据底座）—— 架构和基础模块 100% 完成 ✓

---

## 已完成工作

### ✓ 共享数据契约（Shared Layer）

- `shared/schema.py`：定义所有核心数据结构
  - `ESFields`、`QdrantFields`：字段常量
  - `CorpusChunk`：语料分块模型
  - `FactCard`：结构化事实卡片（用于减少上下文）
  - `EntityInfo`、`SearchTraceEvent`等支持类型
  
- `shared/config.py`：统一配置管理
  - `ESConfig`、`QdrantConfig`、`RedisConfig`：基础设施配置
  - `CorpusPipelineConfig`、`DeepSearchConfig`：业务配置
  - `PathConfig`：路径和输出目录

### ✓ 系统一：语料库处理管道（Corpus Pipeline）- 框架级实现

| 模块 | 文件 | 功能 | 状态 |
|------|------|------|------|
| ingestion | `ingestion/loader.py` | 加载各种格式文本 | ✓ 框架完成 |
| preprocessing | `preprocessing/cleaner.py` | 文本清洗 | ✓ 框架完成 |
| preprocessing | `preprocessing/punctuator.py` | 古文断句（GuwenBERT集成点） | ✓ 框架完成 |
| chunking | `chunking/chunker.py` | 文本分块（段落+重叠） | ✓ 框架完成 |
| translation | `translation/classical_translator.py` | 古文翻译（XunziChat集成点） | ✓ 框架完成 |
| enrichment | `enrichment/ner_extractor.py` | 实体抽取（GuwenBERT NER集成点） | ✓ 框架完成 |
| indexing | `indexing/es_indexer.py` | Elasticsearch索引（jieba+bigram） | ✓ 框架完成 |
| indexing | `indexing/vector_indexer.py` | Qdrant向量索引（bge-m3集成点） | ✓ 框架完成 |
| 主编排 | `pipeline_runner.py` | 管道编排、断点续跑 | ✓ 框架完成 |
| 状态管理 | `state_manager.py` | 进度保存/恢复 | ✓ 框架完成 |

### ✓ 基础设施部署配置

- `docker-compose.yml`：一键启动Elasticsearch、Qdrant、Redis
- `docker/elasticsearch.yml`：Elasticsearch配置
- `docker/redis.conf`：Redis配置
- `requirements.txt`：Python依赖列表

### ✓ 文档

- `QUICKSTART.md`：快速开始指南
- `.env.example`：配置模板

---

## 待完成工作

### 第一层优先级：必须完成（系统才能运行）

#### 1. 模型集成与测试（预计2-3小时）

**目标**：将真实的古文专用模型集成到系统中

```python
# 优先级（按难度递增）：
```

| 任务 | 模块 | 详细要求 | 优先级 |
|------|------|---------|--------|
| 集成GuwenBERT断句模型 | `corpus_pipeline/preprocessing/punctuator.py` | 使用transformers库加载GuwenBERT/guwen-punc模型，对古文进行序列标注以确定句子边界 | 🔴 高 |
| 集成bge-m3 Embedding | `corpus_pipeline/indexing/vector_indexer.py` | 使用FlagEmbedding库或transformers加载bge-m3模型，对译文生成1024维向量 | 🔴 高 |
| 集成GuwenBERT NER模型 | `corpus_pipeline/enrichment/ner_extractor.py` | 加载GuwenBERT/guwen-ner，抽取persons/places/offices等实体 | 🟠 中 |
| 集成古文翻译模型 | `corpus_pipeline/translation/classical_translator.py` | 集成XunziChat或其他古文翻译模型，为原文生成现代文译文 | 🟠 中 |

#### 2. Elasticsearch和Qdrant实际集成（预计1-2小时）

**目标**：连接真实的ES和Qdrant服务，创建索引

| 任务 | 文件 | 详细要求 |
|------|------|---------|
| ES客户端实现 | `corpus_pipeline/indexing/es_indexer.py` | 使用elasticsearch-py连接ES，创建history_corpus索引，使用jieba和ngram分析器，批量索引documents |
| Qdrant客户端实现 | `corpus_pipeline/indexing/vector_indexer.py` | 使用qdrant-client连接Qdrant，创建history_vectors集合，上传向量points |
| Redis客户端实现 | `corpus_pipeline/state_manager.py` | 使用redis-py存储进度快照，支持恢复 |

#### 3. 端到端管道测试（预计1小时）

**目标**：用小规模语料跑通整个管道

```bash
# 测试步骤：
1. 启动Docker服务 ✓
2. 选择 history_deepsearch_implementation_plan-2.md 中的某个小文件作为样本
3. 执行 pipeline_runner.py，观察：
   - 文本是否正确加载、清洗、分块
   - 翻译和NER是否有输出
   - 是否成功索引到ES和Qdrant
   - 进度是否正确保存到Redis
4. 验证检索：
   - 用ES关键词检索
   - 用Qdrant语义检索
   - 验证混合RRF融合逻辑
```

#### 4. 检索质量基线测试（预计2小时）

**目标**：验证底层检索的准确度，确保后续Agent的决策有基础

```python
# 在 corpus_pipeline/tests/test_retrieval_quality.py 中：
# 1. 定义 Recall@K 评估指标
# 2. 准备 gold standard（人工标注的相关文档）
# 3. 对 jieba路、bigram路、向量路分别测试
# 4. 评估RRF融合效果
# 5. 设置通过阈值（例如 Recall@10 >= 0.8）
```

### 第二层优先级：系统二开发（Deep Search引擎）

#### 5. 检索层实现（预计2小时）

| 文件 | 功能 |
|------|------|
| `deepsearch_engine/retrieval_layer/es_client.py` | 封装ES查询（jieba+bigram分词路） |
| `deepsearch_engine/retrieval_layer/vector_client.py` | 封装Qdrant查询（向量路） |
| `deepsearch_engine/retrieval_layer/hybrid_search.py` | 三路RRF融合 |

#### 6. 多角色实现（预计3-4小时）

| 角色 | 文件 | 职责 |
|------|------|------|
| PLANNER | `deepsearch_engine/roles/planner.py` | 拆解初始话题，生成研究维度和初始子查询 |
| RESEARCHER | `deepsearch_engine/roles/researcher.py` | 执行检索，返回原始结果 |
| ANALYST | `deepsearch_engine/roles/analyst.py` | 分析当前结果，识别缺口，生成下一轮子查询 |
| COVERAGE_JUDGE | `deepsearch_engine/roles/coverage_judge.py` | 判断是否覆盖所有研究维度 |
| FACTCHECKER | `deepsearch_engine/roles/factchecker.py` | 交叉验证，标注冲突和印证 |
| WRITER | `deepsearch_engine/roles/writer.py` | 生成最终报告 |

#### 7. 证据管理和上下文控制（预计2小时）

| 文件 | 功能 |
|------|------|
| `deepsearch_engine/evidence_store/fact_card.py` | 事实卡片数据结构（已在schema.py中） |
| `deepsearch_engine/evidence_store/evidence_pool.py` | 证据池CRUD接口 |
| `deepsearch_engine/orchestrator/context_manager.py` | 滚动摘要维护，事实卡片压缩 |

#### 8. 主循环编排（预计3小时）

| 文件 | 功能 |
|------|------|
| `deepsearch_engine/orchestrator/search_loop.py` | 主循环：PLANNER→(RESEARCHER↔ANALYST)→FACTCHECKER→WRITER |
| `deepsearch_engine/orchestrator/convergence_guard.py` | 硬性收敛控制（最大轮次、超时、无新增） |
| `deepsearch_engine/orchestrator/state_manager.py` | 深搜任务状态管理 |

#### 9. 日志和报告生成（预计1.5小时）

| 文件 | 功能 |
|------|------|
| `deepsearch_engine/logging/trace_logger.py` | JSON Lines格式的搜索过程日志 |
| `deepsearch_engine/logging/report_formatter.py` | 将日志渲染成可读的Markdown报告 |

#### 10. LLM后端集成（预计2小时）

| 文件 | 功能 |
|------|------|
| `deepsearch_engine/llm_backend/local_qwen_client.py` | 本地Qwen模型推理（通过ollama/llama.cpp） |
| `deepsearch_engine/llm_backend/llm_router.py` | 轻量任务用本地，关键任务可切换云端API |

### 第三层优先级：测试和优化

#### 11. 单元测试套件

```python
# corpus_pipeline/tests/
test_chunking.py          # 分块逻辑
test_dedup.py             # 近似去重
test_translation_quality.py  # 翻译质量验证
test_end_to_end_sample.py    # 端到端集成测试

# deepsearch_engine/tests/
test_hybrid_search.py     # 检索融合
test_role_output_validation.py  # 各角色输出格式校验
test_convergence_guard.py # 极端情况下的强制终止
```

#### 12. 集成测试和性能基准

```python
# 准备5-10个历史话题的golden标准
# 对每个话题：
#   1. 人工列出"合格的研究报告应包含的内容"
#   2. 运行Deep Search
#   3. 自动化评估覆盖度和准确度
#   4. 人工审查样本
```

### 第四层优先级：分布式扩展（可选）

#### 13. 分布式Worker架构

```python
corpus_pipeline/worker.py  # Worker进程，从Redis任务队列领取job
deepsearch_engine/llm_backend/llm_router.py  # 任务路由
```

---

## 依赖关系和建议实施顺序

```
1. 模型集成和ES/Qdrant连接 (第一层) ✓
   ↓
2. 端到端管道验证 + 检索基线 (第一层) ✓
   ↓
3. 检索层和多角色实现 (第二层) → 可并行
4. 证据管理和主循环 (第二层) → 依赖3
5. 日志和报告 (第二层) → 依赖4
6. LLM后端 (第二层) → 无依赖，可并行
   ↓
7. 单元测试和集成测试 (第三层)
   ↓
8. 分布式扩展（如需要）(第四层)
```

---

## 关键指标和验收标准

### 阶段一验收

- [ ] Docker服务能正常启动
- [ ] 管道能加载任意.md文件
- [ ] 文本能正确清洗、分块
- [ ] 翻译模型集成成功，每条文本有译文输出
- [ ] NER能抽取实体
- [ ] 成功索引到ES和Qdrant（至少100条chunk）
- [ ] 能从ES和Qdrant检索到内容
- [ ] 进度保存到Redis，中断后能恢复

### 阶段二验收

- [ ] 所有6个角色都能调用LLM
- [ ] 主循环能跑完至少5轮不出错
- [ ] 最终生成结构化报告
- [ ] 搜索日志正确记录
- [ ] 能从任意断点恢复继续搜索

---

## 时间估算

| 阶段 | 任务集合 | 估计工作量 | 关键里程碑 |
|------|--------|----------|----------|
| 一 | 模型+ES+检索基线 | 6-8小时 | 能跑通整个管道 |
| 二 | 角色+主循环+日志 | 12-15小时 | 完整Deep Search可用 |
| 三 | 测试和调优 | 6-10小时 | 系统可稳定运行 |
| 四 | 分布式（可选） | 4-6小时 | 支持多机并行 |

**总计**：28-39小时

---

## 当前阶段的推荐下一步

1. ✅ **立即**：集成GuwenBERT断句和bge-m3 embedding模型
2. ✅ **立即**：实现ES和Qdrant的真实客户端
3. ✅ **立即**：用小规模语料（10-20个文件）运行端到端管道验证
4. ⏭️ **完成后**：编写检索质量基线测试
5. ⏭️ **完成后**：开始系统二（角色和主循环）的实现

---

**最后更新**：2024-07-06  
**维护者**：Claude Copilot
