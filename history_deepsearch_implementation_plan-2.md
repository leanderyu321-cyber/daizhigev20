# 本地历史知识库 Deep Search 系统 —— 实施方案文档

> 本文档用于指导 Claude Code 完成系统的模块化开发。文档只定义架构、接口、数据契约和实施顺序，不包含完整代码实现，具体代码由 Claude Code 按本文档拆分的模块逐步生成。

---

## 0. 项目目标与设计原则

### 0.1 核心目标

给定一个历史研究话题（如"建炎南渡"），系统在**不限制耗时**的前提下，通过多轮迭代检索 + 多角色协作验证，产出：

1. 一份尽可能全面、准确、有出处的史料汇编（供历史创作参考）
2. 一份完整的搜索过程日志（记录每一轮搜了什么、为什么搜、发现了什么、如何验证）

### 0.2 设计原则（优先级从高到低）

1. **准确性优先于速度**：允许多轮交叉验证、允许重复检索确认，耗时不是约束条件。
2. **过程可追溯**：任何一条最终结论都必须能回溯到具体史料出处（书名/卷/章节/行号）。
3. **模块解耦**：语料库系统与检索系统完全独立，通过稳定的数据契约通信，互不依赖内部实现。
4. **可恢复性**：由于任务耗时可能很长（几十分钟到几小时），系统必须支持中断后从断点恢复，不能因为一次异常导致全部重跑。
5. **可分布式扩展**：计算密集型任务（embedding生成、LLM推理）可以水平扩展到局域网内的多台机器；存储服务（ES/向量库）集中部署在NAS，作为所有计算节点共享的"数据底座"。

### 0.3 明确不做的事情

- 不追求单次查询的低延迟响应（这不是聊天机器人，是深度研究工具）
- 不在v1阶段引入训练/微调任何模型，全部基于现有开源模型和工具组合
- 不在v1阶段做复杂的权限管理，默认单用户本地使用

---

## 1. 总体架构

系统拆分为两个完全独立、可分别部署的子系统，中间通过共享的存储层（部署在NAS）解耦：

```
┌─────────────────────────────────────────────────────────────┐
│                     NAS（数据持久层，常驻）                     │
│  ┌────────────────────┐        ┌─────────────────────────┐  │
│  │  Elasticsearch      │        │  Qdrant（向量数据库）      │  │
│  │  - jieba分词索引     │        │  - bge-m3 embedding      │  │
│  │  - bigram索引       │        │  - 元数据过滤             │  │
│  └────────────────────┘        └─────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  任务状态存储（Redis 或 SQLite）—— 用于断点续跑           │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
              ▲ 局域网读写                    ▲ 局域网读写
              │                              │
┌─────────────┴──────────────┐   ┌───────────┴─────────────────┐
│  系统一：语料库工程            │   │  系统二：Deep Search 引擎      │
│  （离线批处理，可在任意机器跑）  │   │  （在线交互，部署在Mac等算力机）│
│                             │   │                              │
│  清洗→断句→分块→NER→双路索引  │   │  多角色Agent协作 + 迭代检索循环 │
│  → 写入ES + Qdrant           │   │  → 输出汇编报告 + 搜索日志     │
└─────────────────────────────┘   └──────────────────────────────┘
```

**关键约定**：两个子系统之间唯一的耦合点是 ES 和 Qdrant 中的数据 Schema（见第4节）。只要 Schema 不变，两个系统可以独立开发、独立部署、独立重构。

---

## 2. 部署拓扑（分布式方案）

| 节点 | 部署内容 | 硬件要求建议 | 说明 |
|---|---|---|---|
| NAS（常驻） | Elasticsearch、Qdrant、Redis（任务队列/状态存储） | 16GB+ RAM，支持Docker容器 | 这是唯一需要7×24小时运行的节点，其余节点按需启动 |
| 主控机（Mac，Apple Silicon） | Deep Search Agent 主循环、LLM推理（Qwen2.5系列）、结果整合与报告生成 | 16GB+ RAM（推荐） | 承担"大脑"角色，运行主控编排逻辑 |
| 局域网算力节点（可选，0~N台） | Embedding批量生成 worker、语料清洗/分块 worker | 视任务分配，CPU/GPU均可 | 用于并行加速"系统一"的语料处理，通过任务队列领取任务 |

**扩展方式**：如果未来想加快语料处理速度，直接在局域网内新增一台机器，跑一个 worker 进程连接到 NAS 的 Redis 任务队列，领取分块/embedding任务即可，无需改动架构。Deep Search Agent 的主循环建议不做分布式（多轮迭代之间有强依赖关系，拆分收益不大），但**同一批次内的多个子查询可以并行发给检索层**，这一点会在系统二的模块设计里体现。

---

## 3. NAS部署要点

1. **容器化部署**：Elasticsearch、Qdrant、Redis 均以 Docker 容器形式部署在 NAS 上（Synology 用 Container Manager，QNAP 用 Container Station，或直接 SSH 进去用原生 Docker）。
2. **数据持久化**：三个服务的数据目录都挂载到 NAS 的 RAID 存储卷上，利用 NAS 本身的数据冗余能力，避免单点数据丢失——这对历史语料这种"一次建好长期使用"的数据尤其重要。
3. **资源隔离建议**：给 Elasticsearch 分配固定的 JVM 堆内存（建议 4GB，通过 `ES_JAVA_OPTS=-Xms4g -Xmx4g` 配置），避免和 Qdrant 抢内存导致 OOM。
4. **网络暴露范围**：三个服务只监听局域网网段，不做公网映射（本项目定位是家庭本地部署，无需考虑公网访问和相应的安全加固）。
5. **不要**在NAS上尝试运行任何LLM推理或embedding模型，NAS的CPU算力不适合这类任务，只让它专注做"存储+检索响应"。

---

## 4. 数据契约（两个子系统之间唯一的耦合点）

### 4.1 Elasticsearch 索引 Schema

```
索引名: history_corpus

字段:
- line_id       (keyword)  唯一标识，格式建议: {book}_{chapter}_{chunk_index}
- content       (text, 不建索引，仅存储原文用于展示与最终引用溯源)
- content_translation (text, 不建索引，存储文言→白话译文，专供向量embedding与后续理解类任务读取，见12.7节)
- content_jieba (text, whitespace分析器)  基于原文的jieba预分词结果（保留专有名词字面匹配能力，不能改用译文，否则会丢失"建炎""枢密院"这类原文特有词汇的检索精度）
- content_bigram(text, ngram分析器, min_gram=2, max_gram=2)  基于原文切分，双重保障原文字面检索不失真
- book          (keyword)  出处书名
- chapter       (keyword)  卷/章节
- dynasty       (keyword)  朝代，用于分面过滤
- entities      (object)   实体抽取结果 {persons: [], places: [], events: [], offices: []}
- chunk_index   (integer)  在原文中的顺序位置，用于恢复上下文
- source_hash   (keyword)  原始语料的哈希值，用于去重和增量更新判断
```

### 4.2 Qdrant 向量集合 Schema

```
集合名: history_vectors

向量维度: 1024 （bge-m3 默认输出维度，实际以所选模型为准）
距离度量: Cosine

payload（元数据）字段:
- line_id     (与ES中的line_id一一对应，用于跨库关联)
- book, chapter, dynasty, entities, chunk_index  （与ES保持一致，冗余存储便于向量检索时直接过滤，无需二次查ES）
```

### 4.3 共享Schema定义文件

要求 Claude Code 在项目根目录建立一个 `shared/schema.py`（或 `shared/schema.json`），两个子系统都从这里导入字段定义，禁止在各自代码里硬编码字段名字符串，避免未来修改字段时出现遗漏。

### 4.4 任务状态存储 Schema（用于断点续跑，见第7节）

```
Redis / SQLite 中记录：
- corpus_pipeline_progress: {source_file_hash: 处理状态(pending/done/failed), 失败原因, 时间戳}
- deepsearch_task_state: {task_id: 当前轮次, 已执行的查询列表, 已获取的line_id集合, 各角色的中间产出}
```

---

## 5. 系统一：语料库工程 —— 模块拆分

```
corpus_pipeline/
├── config.py                  # 配置：ES/Qdrant连接地址、分块参数、模型路径等
├── ingestion/
│   ├── loader.py               # 读取原始文献（txt/OCR结果/已有电子文本），统一转为内部格式
│   └── ocr_corrector.py         # 针对OCR错误的规则/模型混合纠错（如有扫描件输入）
├── preprocessing/
│   ├── cleaner.py               # 文本清洗（繁简处理、异体字映射、特殊符号处理）
│   ├── punctuator.py            # 古文断句，优先接入GuwenBERT系微调模型（如guwen-seg/guwen-punc），
│   │                            # 而非通用Qwen，编码器类模型在断句/标点这类序列标注任务上更准确、更省算力
│   └── deduplicator.py          # 基于SimHash/MinHash的近似去重（处理正史互相抄录问题）
├── chunking/
│   └── chunker.py               # 分块逻辑（语义/段落边界 + 20%重叠），可插拔多种策略
├── translation/
│   └── classical_translator.py  # 文言→白话翻译层（详见12.7节）：接入专门的古文理解模型
│                                # （如荀子XunziALLM/XunziChat），为每个chunk生成现代文译文，
│                                # 与原文一并存储；后续embedding与理解类任务默认基于译文进行，
│                                # 原文仅保留用于溯源引用
├── enrichment/
│   ├── ner_extractor.py         # 实体抽取（人物/地点/朝代/官职），可结合原文与译文交叉验证，
│   │                            # 优先用古文专用BERT模型（如GuwenBERT/SikuBERT/bert-ancient-chinese）
│   │                            # 处理原文，通用小模型能力不足时译文可作为辅助参照
│   └── term_dict.py             # 历史专有名词词典管理（年号/官职/地名别名，供jieba和NER共用）
├── indexing/
│   ├── es_indexer.py            # 写入Elasticsearch（jieba分词+bigram均基于原文，保留专有名词字面检索精度）
│   └── vector_indexer.py        # 基于译文生成embedding并写入Qdrant（原因见12.7节：通用embedding模型对现代文语义表征更强）
├── pipeline_runner.py            # 编排以上所有步骤，支持断点续跑（读取任务状态存储）
├── worker.py                     # 分布式worker入口，从Redis任务队列领取分块/embedding任务
└── tests/
    ├── test_chunking.py
    ├── test_dedup.py
    ├── test_translation_quality.py  # 抽样对比译文与原文，人工核查翻译准确度，作为质量门禁
    └── test_end_to_end_sample.py  # 用小样本语料跑通整个pipeline的集成测试
```

**健壮性要求（明确写给Claude Code）**：
- `pipeline_runner.py` 必须支持"从任意步骤失败后重跑"，不能要求每次都从头开始处理全部文献。每处理完一个文档，立即在任务状态存储中打点记录进度。
- 所有对ES/Qdrant的写入操作必须包裹重试逻辑（建议指数退避重试，最多3-5次），网络抖动不应导致整批数据处理失败。
- `ner_extractor.py` 如果调用本地小模型做抽取，必须对模型输出做严格的JSON格式校验和异常兜底（模型偶尔会输出格式错误的结果），格式错误时记录日志并跳过该字段，不能让整个pipeline因此崩溃。
- `classical_translator.py` 的翻译结果必须保留与原文的对应关系（同一line_id），任何后续环节引用史料原句时都必须回查原文，不能用译文冒充原文呈现给用户，避免因翻译误差导致的以讹传讹。

---

## 6. 系统二：Deep Search 引擎 —— 模块拆分

### 6.1 设计思路：多角色协作（复用你已有的多智能体经验）

不同于此前讨论的"单一小模型自己决定何时停止"的简单循环，Deep Search场景下建议采用**多角色分工**，让每个角色只负责一件事，判断更稳定，也更容易调试和替换：

| 角色 | 职责 | 对应此前的收敛问题 |
|---|---|---|
| PLANNER（规划者） | 拆解初始话题为多个研究维度（人物/事件/制度/地理/时间线），生成初始子查询列表 | 避免"单轮查询覆盖不全"的问题 |
| RESEARCHER（检索者） | 执行具体检索（调用ES+Qdrant混合检索），对每个子查询独立执行 | 纯工具调用，不涉及模型推理，稳定可靠 |
| ANALYST（分析者） | 分析当前已获取的所有史料，识别信息缺口和新线索（人名/地名/事件），生成下一轮子查询 | 这是驱动"递归深挖"的核心角色 |
| FACTCHECKER（核查者） | 对比同一史实在不同史料中的记述是否冲突，标注存疑点和互相印证的条目 | 保证"准确性优先"这个设计原则的落地 |
| COVERAGE_JUDGE（覆盖度评估者） | 独立评估当前信息是否已覆盖PLANNER最初列出的所有研究维度，只有这个角色说"够了"才终止循环 | 用一个**独立角色**做终止判断，而不是让同一个模型在生成子查询的同时判断"我自己是否该停了"，判断更客观 |
| WRITER（整合者） | 将所有验证过的史料整合成结构化报告，附带出处 | 最终产出环节 |

**为什么要拆这么细**：把"生成子查询"和"判断是否该停止"分给两个不同角色（ANALYST vs COVERAGE_JUDGE），比让同一次模型调用同时做两件事更稳定——一个角色一次只专注一个判断，输出格式和逻辑更容易约束和校验，这对使用中小模型本地推理的场景尤其重要。

### 6.2 模块拆分

```
deepsearch_engine/
├── config.py                     # 配置：LLM地址（本地Qwen或云端API）、检索层地址、最大轮次等
├── roles/
│   ├── planner.py                 # PLANNER角色：话题拆解 + 初始子查询生成
│   ├── researcher.py               # RESEARCHER角色：封装对retrieval_layer的调用
│   ├── analyst.py                  # ANALYST角色：信息缺口识别 + 新子查询生成
│   ├── factchecker.py              # FACTCHECKER角色：史料交叉验证与冲突标注
│   ├── coverage_judge.py           # COVERAGE_JUDGE角色：独立的终止条件判断
│   └── writer.py                   # WRITER角色：最终报告生成
├── retrieval_layer/
│   ├── es_client.py                 # ES检索封装（jieba路 + bigram路）
│   ├── vector_client.py             # Qdrant检索封装
│   └── hybrid_search.py             # 三路RRF融合逻辑（复用此前讨论的RRF实现）
├── orchestrator/
│   ├── search_loop.py               # 主循环：串联PLANNER→(RESEARCHER↔ANALYST循环)→FACTCHECKER→WRITER
│   ├── state_manager.py             # 任务状态管理，支持中断恢复（读写Redis/SQLite）
│   ├── convergence_guard.py         # 硬性收敛控制：最大轮次、去重检测、超时保护（多重保险，不完全依赖COVERAGE_JUDGE）
│   └── context_manager.py           # 上下文窗口管理：结构化事实卡片提取、滚动摘要维护、按需构造每次角色调用的prompt（详见第12节，本地小模型上下文有限时的核心保护机制）
├── evidence_store/
│   ├── fact_card.py                  # 定义"结构化事实卡片"的数据结构（dataclass/pydantic）
│   └── evidence_pool.py              # 全局证据池的读写接口，原文与结构化卡片分离存储，供各角色按需查询而非整体注入上下文
├── logging/
│   ├── trace_logger.py              # 结构化搜索过程日志（JSON Lines格式，记录每一轮每个角色的输入输出）
│   └── report_formatter.py          # 将trace_logger的日志渲染成可读的"搜索过程报告"（供用户查看AI是如何一步步深挖的）
├── llm_backend/
│   ├── local_qwen_client.py         # 本地Qwen模型调用封装（如通过llama.cpp/Ollama等本地推理服务）
│   └── llm_router.py                # 可选：轻量任务走本地模型，关键判断任务可切换云端API（复用你已有的多provider抽象层经验）
├── main.py                          # CLI入口：输入话题，输出报告+日志
└── tests/
    ├── test_hybrid_search.py
    ├── test_convergence_guard.py     # 重点测试：确保极端情况下（模型判断异常）也能正确终止，不会死循环
    └── test_role_output_validation.py # 测试每个角色的输出是否符合预期JSON格式
```

### 6.3 主循环伪代码逻辑（供Claude Code理解编排关系，非最终实现）

```
1. PLANNER(初始话题) → 研究维度列表 + 初始子查询列表
2. 记录任务初始状态到 state_manager（用于断点恢复）
3. rolling_summary = ""（滚动摘要初始为空，由context_manager维护）
4. while True:
     a. RESEARCHER 并行执行当前批次所有子查询 → 原始检索结果
     b. 去重（基于line_id），原文写入 evidence_pool（外部存储，不进模型上下文）
     c. context_manager 将本轮新增的原始结果压缩为"结构化事实卡片"（见12.2），
        卡片写入 evidence_pool，原文本身不再传递给后续角色
     d. state_manager 打点保存当前进度（关键：每轮结束都保存，中断后可从这里恢复）
     e. ANALYST(rolling_summary, 本轮新增事实卡片, 研究维度列表) → 识别缺口 → 生成下一批子查询
        　　　　　　── 注意：ANALYST只接收"滚动摘要+本轮新增"，不接收全部历史原文 ──
     f. COVERAGE_JUDGE(rolling_summary, 研究维度列表) → 是否所有维度都已覆盖？
     g. context_manager 用"rolling_summary + 本轮新增事实卡片"重新生成新的rolling_summary，
        替换旧摘要（保持摘要长度基本恒定，不随轮次线性增长）
     h. convergence_guard 检查硬性条件（是否超过最大轮次/是否本轮无新增结果/是否超时）
     i. 如果 COVERAGE_JUDGE说够了 或 convergence_guard触发 → 跳出循环
5. FACTCHECKER 采用Map-Reduce方式处理evidence_pool中全部事实卡片（分批交叉验证，
   再汇总各批次结果），避免卡片总量超出上下文窗口
6. WRITER 同样以Map-Reduce方式整合FACTCHECKER标注后的结果，生成最终结构化报告
7. trace_logger 输出完整过程日志（日志本身独立存储，不受上下文窗口限制）
```

**给Claude Code的健壮性要求**：
- `convergence_guard.py` 必须是独立于任何模型判断的"硬保险"，即使 COVERAGE_JUDGE 角色因为模型异常永远返回"未覆盖"，`convergence_guard` 也必须能在设定的最大轮次或超时后强制终止循环，绝不允许无限运行。
- 由于"耗时不重要"，最大轮次可以设得比较宽松（比如15-20轮），但必须是一个明确配置项，不能不设上限。
- `state_manager` 必须在每一轮结束后立即持久化状态，如果程序因任何原因中断（崩溃/手动停止/机器重启），重新运行时应能提示"检测到未完成任务，是否从断点继续"。

---

## 7. 断点续跑机制（重点，因任务耗时长而必要）

由于Deep Search任务可能运行数十分钟甚至数小时，且分布式场景下语料处理任务量可能很大，**中断恢复能力是必须项，不是可选优化**。

设计要点：
1. 每个任务（无论是语料处理批次，还是一次Deep Search查询）在启动时生成唯一的 `task_id`。
2. 每完成一个可恢复的最小单元（语料处理中的"一个文档"，Deep Search中的"一轮检索循环"），立即向状态存储写入进度快照。
3. 重启时，程序先检查状态存储里是否存在同一 `task_id` 的未完成记录，如果存在，加载快照恢复内部状态（已处理的文档列表/已执行的子查询与已获取的史料池），跳过已完成部分，从断点继续。
4. 状态存储推荐用 Redis（如果追求简单粗暴，SQLite也完全够用，家庭本地场景不需要Redis的高并发能力，选择哪个由Claude Code根据实现便利性决定即可）。

---

## 8. 搜索过程日志设计（用户明确要求的核心产出之一）

日志不是简单的print调试信息，而是**面向用户可读的"AI研究轨迹"**，设计为结构化JSON Lines格式，每一行记录一个事件：

```json
{"timestamp": "...", "round": 2, "role": "ANALYST", "input_summary": "已获取15条史料，涉及建炎南渡时间线", "output": "发现多处提及扬州溃败但细节不足，生成新查询：扬州之变 建炎三年", "reasoning": "..."}
{"timestamp": "...", "round": 2, "role": "RESEARCHER", "query": "扬州之变 建炎三年", "results_count": 8, "new_results_count": 6}
{"timestamp": "...", "round": 3, "role": "COVERAGE_JUDGE", "covered_dimensions": ["时间线", "军事细节"], "missing_dimensions": ["人物动机"], "decision": "continue"}
```

`report_formatter.py` 负责把这份原始日志渲染成一份人类可读的Markdown报告，类似"研究过程叙事"，让用户能直观看到AI是如何一步步从"建炎南渡"深挖到"扬州溃败"再到"李纲罢相"的。这份报告和最终的史料汇编报告应该是两份独立文件，分开呈现。

---

## 9. 测试与评估框架

1. **单元测试**：每个角色（PLANNER/ANALYST/COVERAGE_JUDGE等）的输出格式校验，重点测试模型输出格式异常时代码是否能正确捕获并降级处理，而不是直接崩溃。
2. **检索质量基线测试**：复用此前讨论过的 Recall@K 评估方法，针对底层 `hybrid_search.py` 单独测试，确保这一层的质量不会被上层的Agent逻辑问题掩盖。
3. **端到端覆盖度测试**：准备5-10个历史话题，人工列出"一份合格的研究报告应该覆盖哪些子话题"，跑完整Deep Search流程后，人工比对报告是否覆盖了这些预期子话题，作为整个系统质量的验收标准。
4. **收敛性压力测试**：故意构造模型返回异常/模糊结果的场景（mock掉LLM返回垃圾数据），验证 `convergence_guard` 是否总能在设定轮次内正确终止，这是保证系统健壮性的关键测试项，不能省略。

---

## 10. 分阶段实施路线图（建议Claude Code按此顺序开发）

**阶段一：数据底座**
1. 部署NAS上的ES + Qdrant + Redis（Docker Compose文件）
2. 实现 `shared/schema.py`
3. 实现 `corpus_pipeline` 的核心链路（不含分布式worker），先用通用工具跑通端到端流程
4. 接入古文专用模型：断句/NER替换为GuwenBERT系模型，接入`classical_translator.py`生成译文（见12.7节），
   人工抽查一批译文质量，确认可用后再批量跑全部语料
5. 编写检索质量基线测试，验证jieba+bigram+向量三路融合的Recall表现（注意向量检索基于译文生成的embedding）

**阶段二：单角色验证**
5. 实现 `retrieval_layer`（三路RRF融合）
6. 实现 PLANNER 和 RESEARCHER 两个角色，先跑"单轮无循环"的检索改写效果，验证子查询质量

**阶段三：完整循环**
7. 实现 `evidence_store`（fact_card + evidence_pool）和 `context_manager`（结构化卡片压缩 + 滚动摘要维护），这一步应先于ANALYST/COVERAGE_JUDGE实现，因为后两者依赖context_manager提供的组装接口，不能直接拼接原始检索结果
8. 实现 ANALYST、COVERAGE_JUDGE、convergence_guard，组装出完整的多轮循环
9. 实现 state_manager，验证中断恢复功能
10. 实现 trace_logger 和 report_formatter
11. 专项测试：模拟20轮以上的长循环，验证滚动摘要和事实卡片机制确实能将单次prompt大小控制在安全阈值内，不出现窗口溢出

**阶段四：质量强化**
12. 实现 FACTCHECKER 和 WRITER（Map-Reduce方式处理事实卡片，见第12.4节），产出最终报告
13. 跑端到端覆盖度测试，针对表现不佳的话题类型调整PLANNER的维度拆解逻辑或ANALYST的Prompt

**阶段五：分布式扩展（可选，视语料规模决定是否需要）**
14. 实现 `corpus_pipeline/worker.py`，接入Redis任务队列，验证多机并行处理语料的效果
15. 如有需要，实现 `llm_router.py`，为关键判断角色（COVERAGE_JUDGE/FACTCHECKER）接入云端API作为本地模型的质量兜底选项

---

## 12. 上下文窗口管理（本地小模型多轮迭代的核心保护机制）

### 12.1 问题背景

本地部署的中小参数模型（如 Qwen2.5-7B）实际可用上下文窗口通常受限（受推理框架配置和内存共同约束，常见为8K左右，理论上模型架构可支持更长，但受限于本地硬件资源，不宜依赖"无限加大窗口"作为解法）。而 Deep Search 场景的设计前提是"允许多轮交叉验证、反复检索确认"，如果朴素地把每一轮累积的全部原始检索结果都拼接进模型的prompt，几轮之后必然超出窗口容量，导致内容被截断（且往往是早期轮次的发现被截掉），这直接违背系统"信息全面、可追溯"的设计目标。

**核心原则：上下文窗口只应承载"当前这一次角色调用所必需的最小信息"，累积的全部证据永远存放在外部存储（evidence_pool，基于Qdrant/ES之上的一层封装），不随轮次增长而注入模型上下文。**

### 12.2 结构化事实卡片（Fact Card）

这是解决上下文膨胀问题的核心手段。每一轮 RESEARCHER 检索到原始文本片段后，不直接把原文交给 ANALYST 等角色，而是先压缩提取成结构化卡片，仅保留判断所需的关键信息：

```python
# evidence_store/fact_card.py 中定义的数据结构示意
@dataclass
class FactCard:
    line_id: str          # 关联到ES/Qdrant中的原文，需要查证原文时按此ID回查
    summary: str           # 一句话概要（而非原文）
    event: str | None      # 涉及的核心事件
    persons: list[str]     # 涉及人物
    time: str | None       # 涉及的时间/年号
    dynasty: str | None
    source: str            # 出处（书名·卷·章节）
```

后续 ANALYST、COVERAGE_JUDGE、FACTCHECKER 的判断均基于这些卡片，而不是原始长文本。假设单条原文片段300字，压缩后的卡片可能只有30-50字，即使累积上百条史料，卡片总量也大概率能控制在几千字以内，远比堆叠原文轻量。**FACTCHECKER 和 WRITER 在需要核实具体措辞或引用原文时，才按 line_id 单独回查 evidence_pool 获取原文，属于按需查询，不是批量注入。**

### 12.3 滚动摘要（Rolling Summary）

除了单条卡片的压缩，还需要对"整体研究进展"做持续压缩，而不是让传给 ANALYST 的"历史上下文"变成一份不断变长的列表：

- 每轮结束后，`context_manager` 用一次模型调用，把"上一轮的滚动摘要 + 本轮新增的事实卡片"重新总结为一份新的滚动摘要，**替换**旧摘要，而不是追加。
- 这样无论系统跑了5轮还是20轮，喂给下一轮 ANALYST/COVERAGE_JUDGE 的"历史上下文"始终是一份大小基本恒定的摘要（可以设定一个目标长度，比如控制在500-800字以内），不会线性增长到撑爆窗口。

### 12.4 Map-Reduce式的最终整合

到了 FACTCHECKER 和 WRITER 阶段，即使有事实卡片压缩，证据总量在长时间深挖后仍可能变得较大（比如上百张卡片）。这两个角色应采用经典的长文本处理模式：

1. 将全部事实卡片按一定规则分批（比如每批15-20张）
2. 对每一批单独调用一次 FACTCHECKER/WRITER，产出"批次小结"
3. 将所有批次小结（数量少、内容精炼，通常能整体塞入一次窗口）再做一次最终整合调用，生成完整报告

这样无论证据规模多大，单次模型调用的输入始终可控，不依赖"一次性看完所有内容"。

### 12.5 如果条件允许，仍建议适度扩大可用上下文

结构化管理是治本的方法，但如果硬件条件允许（内存充裕），适度调大本地推理框架的上下文长度配置（比如从8K提到16K），并考虑对KV Cache做量化（多数本地推理引擎支持将KV Cache本身量化为int8等更省内存的格式，从而在相同内存预算下支撑更长上下文），能为上述机制提供更多缓冲空间，减少滚动摘要压缩过于激进导致细节丢失的风险。但这只是"加大缓冲垫"，不能替代12.2-12.4描述的架构性解法，因为任何固定窗口在"允许无限反复确认"的设计前提下终究会被填满。

### 12.7 文言文理解能力不足的解决方案（与上下文管理配合）

除了窗口大小本身的限制，本地通用小模型（Qwen2.5-7B等）对文言文的语义理解能力也弱于对现代白话文的理解，这是独立于窗口大小的另一个短板，会直接影响 ANALYST/WRITER 等角色的判断质量。解决思路不是让通用模型硬啃原文，而是**在语料入库阶段就把"理解"这件事情提前做好，交给专门的古文模型完成**：

- **语料库阶段**：`corpus_pipeline/translation/classical_translator.py` 为每个chunk生成现代文译文，与原文一并存入 `content` 和 `content_translation` 两个字段（见第4.1节Schema）。翻译建议使用专门的古文大模型（如荀子系列 XunziALLM/XunziChat，开源地址：`github.com/Xunzi-LLM-of-Chinese-classics/XunziALLM`），而非通用Qwen模型，因为专用模型在文言文翻译准确度上明显更可靠。断句、标点、实体识别等结构化理解任务，优先接入 GuwenBERT/SikuBERT/bert-ancient-chinese 等专门的古文BERT系模型，这类是编码器模型，不能对话生成，但在序列标注类任务上准确率和效率都优于通用生成式模型，正好匹配这几个子任务的需求。
- **检索与推理阶段**：向量embedding基于译文而非原文生成（原文依然用于关键词字面检索，见第4.1节字段说明），`context_manager` 组装给 ANALYST/COVERAGE_JUDGE/WRITER 的事实卡片内容也优先基于译文压缩生成。这样通用小模型在整个Agent循环中，实际"读"的内容大部分是它更擅长处理的现代白话文，古文理解能力的短板被前置到语料库阶段、交给专门模型解决，不会在每一轮Agent推理时反复暴露出来。
- **原文与译文的关系必须显式保留**：任何最终呈现给用户的引用，必须回查原文（通过line_id关联），不能让译文冒充原文展示，避免翻译误差被误当作史料原意传播。

**给Claude Code的实现要求**：`classical_translator.py` 需要支持"翻译置信度较低时的降级策略"（比如翻译结果与原文长度比例异常、或模型输出包含明显的拒绝/报错模式时，标记该条记录为`translation_status: uncertain`，后续人工抽查或在报告中特别标注"此处译文可能不准确，请参照原文"），不能默认所有译文都可信。

---

## 14. 代码质量要求（写给Claude Code的通用约束）

- 所有跨模块调用通过明确定义的接口（Python中建议用 `dataclass` 或 `pydantic` 模型定义角色间传递的数据结构，禁止用裸字典传递关键数据，减少运行时因字段拼写错误导致的隐性bug）。
- 所有对外部服务（ES/Qdrant/LLM API）的调用必须有超时设置和异常捕获，不允许出现未处理异常导致整个进程崩溃。
- 关键函数和模块顶部需要有清晰的中文注释，说明其职责边界、输入输出格式、以及"为什么这么设计"（尤其是 `convergence_guard.py` 这类涉及重要设计权衡的模块）。
- 配置项统一从 `config.py` 读取，不允许在业务代码中硬编码任何地址、路径、阈值参数。
- 日志分级：调试细节用 DEBUG 级别，搜索过程叙事用专门的 `trace_logger`（面向用户），系统运行状态（连接失败/重试等）用标准 logging 模块的 INFO/WARNING/ERROR 级别，两类日志不要混在一起。
