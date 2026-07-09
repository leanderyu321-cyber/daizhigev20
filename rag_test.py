#!/usr/bin/env python3
"""
RAG 测试脚本 v2 —— 用本地模型测试向量化知识库的检索效果
（在原版基础上做的审计修复，改动说明见文末 CHANGELOG）

工作流程：
  1. 接收用户问题
  2. 向量检索（ChromaDB） + BM25检索（本地内存索引），RRF融合排序
  3. 优先用"父块"（完整段落/篇章）拼上下文，而不是零散子块，避免语境缺失导致的歧义
  4. 严格模式下强制模型只用给定原文作答，不允许模型用自己的古文知识补充
     （评估检索质量时必须这样，否则你分不清答案是检索给对的还是模型本来就会）
  5. 输出答案 + 完整检索/prompt日志（可选落盘，便于批量复盘）

用法:
  python rag_test.py "伤寒论中太阳病的症状是什么"
  python rag_test.py --scheme semantic "辨证论治的核心思想"
  python rag_test.py --scheme precision "太阳之为病" --top-k 5
  python rag_test.py --interactive                       # 交互模式
  python rag_test.py --no-bm25 "太阳之为病"                # 对比：只用向量检索（复现旧版行为）
  python rag_test.py --allow-supplement "太阳之为病"        # 允许模型补充自己的知识（生产模式行为）
  python rag_test.py --log-dir ./eval_logs "太阳之为病"     # 把完整检索/prompt/答案落盘

环境变量:
  OLLAMA_BASE_URL     Ollama 地址（默认 http://localhost:11434）
  EMBEDDING_MODEL     向量模型（默认 nomic-embed-text）
  LLM_MODEL           问答模型（默认 qwen3:8b-q4_K_M）
  CHROMA_DB_PATH      ChromaDB 路径（默认 ./chroma_db）
  COLLECTION_NAME     集合名（默认 classical_chinese_corpus）

依赖（比原版多了 numpy，用于 BM25 计算；其余不变）:
  pip install chromadb requests numpy --break-system-packages
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pickle
import re
import sys
import textwrap
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── 依赖检查 ──────────────────────────────────────────────────────────

try:
    import chromadb
    from chromadb.config import Settings
    import requests
except ImportError as e:
    print(f"❌ 缺少依赖: {e}")
    print("   请运行: pip install chromadb requests numpy --break-system-packages")
    sys.exit(1)


# ── 配置 ──────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_CHROMA_PATH = str(_SCRIPT_DIR / "chroma_db")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:8b-q4_K_M")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", _DEFAULT_CHROMA_PATH)
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "classical_chinese_corpus")

# 上下文截断的默认上限（字符数）。比原版的300大，且不再硬切，
# 而是尽量在句读符号处收尾，避免把"徧於五嶽、四瀆矣"这类需要
# 完整语境才能消歧的句子从中间切断。
DEFAULT_MAX_CHUNK_CHARS = 500

# RRF (Reciprocal Rank Fusion) 融合常数，值越大，排名靠后的结果
# 对最终分数的贡献差异越平滑；60是文献里常见的默认值。
RRF_K = 60

# 句读切分正则：用于BM25分词兜底，以及"智能截断"寻找收尾点
SENTENCE_END = re.compile(r"[。！？；\n]")


# ═══════════════════════════════════════════════════════════════════════
#  ChromaDB 连接 + 距离度量检测
# ═══════════════════════════════════════════════════════════════════════

def connect_chromadb() -> Tuple[chromadb.Collection, str]:
    """连接 ChromaDB 并获取集合，同时探测实际使用的距离度量。

    ChromaDB 默认距离度量是 L2（欧氏距离平方），只有建库时显式指定
    hnsw:space="cosine" 才是 cosine 距离。这两种度量的取值范围完全
    不同，"score = 1 - distance" 这个公式只在 cosine 下成立，L2 下
    算出来的数字没有"相似度"含义。这里做检测，避免在错误的度量下
    误导你判断检索质量。
    """
    client = chromadb.PersistentClient(
        path=CHROMA_DB_PATH,
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_collection(COLLECTION_NAME)
    count = collection.count()

    abs_path = os.path.abspath(CHROMA_DB_PATH)
    space = "l2"
    try:
        meta = collection.metadata or {}
        space = meta.get("hnsw:space", "l2")
    except Exception:
        pass

    print(f"📚 ChromaDB 实际路径: {abs_path}")
    print(f"📚 集合: {COLLECTION_NAME} ({count} 条记录) | 距离度量: {space}")
    if space != "cosine":
        print(
            "   ⚠️  当前集合不是用 cosine 距离建的索引。下面显示的\"score\"是"
            "原始 distance（越小越相关），不是 0-1 的相似度百分比，"
            "请不要把它当百分比读。"
        )
    return collection, space


# ═══════════════════════════════════════════════════════════════════════
#  向量检索
# ═══════════════════════════════════════════════════════════════════════

def embed_query(query: str) -> List[float]:
    """调用 Ollama 生成查询向量"""
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBEDDING_MODEL, "input": [query]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


# 向量检索的最低相似度阈值（仅在cosine距离下生效）。低于这个值的结果会被
# 过滤掉，不管top_k设多大——向量最近邻检索永远会返回"最不离谱的N个"，
# 哪怕语料库里根本没有真正相关的内容，所以必须有一道硬性下限，不能只靠
# 排名前几就默认"足够相关"。这个值需要你根据实际语料调，0.35是保守的
# 起点，如果发现明显相关的内容也被过滤掉了，适当调低；如果发现"癌症"
# 这类语料库里根本没有的词还是能查出内容，适当调高。
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.35"))


def vector_search(
    collection: chromadb.Collection,
    query_embedding: List[float],
    top_k: int,
    scheme: Optional[str],
    space: str,
    min_similarity: float = MIN_SIMILARITY,
) -> List[Dict[str, Any]]:
    """向量检索，返回统一格式的候选列表（不做相似度语义，只保留原始distance+排名）。

    在cosine距离下会按min_similarity过滤掉相关性太低的结果——这是这次
    审计新加的：之前完全没有下限，导致查询一个语料库里根本不存在的
    概念（比如问古籍库"癌症"），向量检索依然会硬凑出一堆"矬子里拔
    将军"的候选，而不会诚实地说"没有相关内容"。
    """
    where = {"chunk_scheme": scheme} if scheme else None

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    out = []
    filtered_count = 0
    if results["ids"]:
        for rank, i in enumerate(range(len(results["ids"][0])), start=1):
            distance = results["distances"][0][i]
            similarity = (1.0 - distance) if space == "cosine" else None

            if space == "cosine" and similarity is not None and similarity < min_similarity:
                filtered_count += 1
                continue

            out.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": distance,
                "similarity": similarity,
                "vector_rank": rank,
            })

    if filtered_count > 0:
        logger.info(f"向量检索: {filtered_count} 条结果因相似度低于{min_similarity}被过滤")

    return out


# ═══════════════════════════════════════════════════════════════════════
#  BM25 检索（本地内存索引，字符 bigram 分词）
# ═══════════════════════════════════════════════════════════════════════
#
# 为什么不用 jieba 分词：现代中文分词器对古汉语的分词准确率没有保障
# （训练语料是现代文本），错误的分词边界会直接破坏BM25的词频统计。
# 字符bigram（每两个相邻字组成一个"词"）不依赖任何分词模型，对文言文
# 这种字词密度高、虚词少的文本反而更稳健，是古文检索场景常见的兜底方案。
# 如果你后续接入了专门的古汉语分词器（比如荀子模型的词法分析功能），
# 可以把 _tokenize() 换成那个，其余逻辑不用动。

def _tokenize(text: str) -> List[str]:
    text = re.sub(r"\s+", "", text)
    if len(text) < 2:
        return [text] if text else []
    return [text[i:i + 2] for i in range(len(text) - 1)]


@dataclass
class BM25Index:
    doc_ids: List[str] = field(default_factory=list)
    doc_freqs: List[Counter] = field(default_factory=list)
    doc_lens: List[int] = field(default_factory=list)
    avg_doc_len: float = 0.0
    df: Counter = field(default_factory=Counter)  # 每个词出现在多少篇文档里
    n_docs: int = 0
    k1: float = 1.5
    b: float = 0.75

    @classmethod
    def build(cls, doc_ids: List[str], texts: List[str]) -> "BM25Index":
        idx = cls()
        idx.doc_ids = doc_ids
        idx.n_docs = len(texts)
        for text in texts:
            toks = _tokenize(text)
            freq = Counter(toks)
            idx.doc_freqs.append(freq)
            idx.doc_lens.append(len(toks))
            for term in freq:
                idx.df[term] += 1
        idx.avg_doc_len = (sum(idx.doc_lens) / idx.n_docs) if idx.n_docs else 0.0
        return idx

    def _idf(self, term: str) -> float:
        n_qualify = self.df.get(term, 0)
        # BM25标准idf公式，加0.5平滑，防止除零/负值
        return math.log(1 + (self.n_docs - n_qualify + 0.5) / (n_qualify + 0.5))

    def search(self, query: str, top_k: int) -> List[Tuple[str, float]]:
        q_terms = _tokenize(query)
        if not q_terms or self.n_docs == 0:
            return []
        scores = [0.0] * self.n_docs
        for term in q_terms:
            idf = self._idf(term)
            if idf <= 0:
                continue
            for i, freq in enumerate(self.doc_freqs):
                f = freq.get(term, 0)
                if f == 0:
                    continue
                dl = self.doc_lens[i]
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avg_doc_len or 1))
                scores[i] += idf * (f * (self.k1 + 1)) / (denom or 1)
        ranked = sorted(
            ((self.doc_ids[i], s) for i, s in enumerate(scores) if s > 0),
            key=lambda x: -x[1],
        )
        return ranked[:top_k]


def build_or_load_bm25_index(collection: chromadb.Collection, cache_dir: Path) -> Dict[str, BM25Index]:
    """
    为每个 chunk_scheme 分别建一个 BM25 索引（保持和向量检索一样可以按方案过滤）。
    索引会缓存到磁盘，按集合记录数做简单的失效判断——记录数变了就重建。
    对于几万条量级的语料，全量拉取 + 建索引通常在几秒到几十秒内，可以接受；
    如果你的语料规模上到百万级，这里需要换成磁盘化的BM25实现，现在这版
    不支持这么大规模，先用着，规模上来了再优化。
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    count = collection.count()
    cache_file = cache_dir / f"bm25_{COLLECTION_NAME}_{count}.pkl"

    if cache_file.exists():
        with open(cache_file, "rb") as f:
            print(f"🔎 BM25索引: 从缓存加载 ({cache_file.name})")
            return pickle.load(f)

    print("🔎 BM25索引: 缓存未命中，正在全量拉取语料并建索引...")
    all_data = collection.get(include=["documents", "metadatas"])
    ids = all_data["ids"]
    docs = all_data["documents"]
    metas = all_data["metadatas"]

    by_scheme: Dict[str, Tuple[List[str], List[str]]] = defaultdict(lambda: ([], []))
    by_scheme["__all__"] = ([], [])
    for doc_id, text, meta in zip(ids, docs, metas):
        scheme = (meta or {}).get("chunk_scheme", "unknown")
        by_scheme[scheme][0].append(doc_id)
        by_scheme[scheme][1].append(text)
        by_scheme["__all__"][0].append(doc_id)
        by_scheme["__all__"][1].append(text)

    indices = {scheme: BM25Index.build(ids_, texts_) for scheme, (ids_, texts_) in by_scheme.items()}

    with open(cache_file, "wb") as f:
        pickle.dump(indices, f)
    print(f"🔎 BM25索引: 建好了 {len(ids)} 条文档，已缓存到 {cache_file.name}")
    return indices


def bm25_search(
    indices: Dict[str, BM25Index],
    id_to_record: Dict[str, Dict[str, Any]],
    query: str,
    top_k: int,
    scheme: Optional[str],
) -> List[Dict[str, Any]]:
    index = indices.get(scheme or "__all__")
    if index is None:
        return []
    ranked = index.search(query, top_k)
    out = []
    for rank, (doc_id, score) in enumerate(ranked, start=1):
        rec = id_to_record.get(doc_id, {})
        out.append({
            "id": doc_id,
            "text": rec.get("text", ""),
            "metadata": rec.get("metadata", {}),
            "bm25_score": score,
            "bm25_rank": rank,
        })
    return out


# ═══════════════════════════════════════════════════════════════════════
#  RRF融合 + 父块回溯 + 智能截断
# ═══════════════════════════════════════════════════════════════════════

def rrf_fuse(
    vector_results: List[Dict[str, Any]],
    bm25_results: List[Dict[str, Any]],
    top_k: int,
    rrf_k: int = RRF_K,
) -> List[Dict[str, Any]]:
    """
    Reciprocal Rank Fusion：把两条独立的检索路径按各自的排名（而不是分数，
    因为向量distance和BM25 score量纲完全不同，没法直接相加）融合成一个
    排序。这是你之前RAG系统里定的"BM25+向量+RRF"设计。

    融合之后还做了一步"按文本内容去重"：同一段原文如果同时存在
    semantic和precision两个方案的副本（内容完全相同，只是chunk_scheme
    标签不同——常见于短于两种方案切分窗口的短句/标题），只保留rrf_score
    更高的那一条，避免同一句话占掉两个top-k名额，把真正该出现的
    不同内容挤出候选范围。
    """
    fused: Dict[str, Dict[str, Any]] = {}

    for r in vector_results:
        fused.setdefault(r["id"], {**r})
        fused[r["id"]]["rrf_score"] = fused[r["id"]].get("rrf_score", 0.0) + 1.0 / (rrf_k + r["vector_rank"])
        fused[r["id"]]["from_vector"] = True

    for r in bm25_results:
        entry = fused.setdefault(r["id"], {**r})
        # 如果这条记录只在bm25里出现，要把text/metadata补上（vector分支没写过）
        if not entry.get("text"):
            entry["text"] = r["text"]
            entry["metadata"] = r["metadata"]
        entry["rrf_score"] = entry.get("rrf_score", 0.0) + 1.0 / (rrf_k + r["bm25_rank"])
        entry["from_bm25"] = True

    merged = sorted(fused.values(), key=lambda x: -x["rrf_score"])

    # 按文本内容去重：同一段原文的多个方案副本，只保留分数最高的一条
    seen_text: Dict[str, bool] = {}
    deduped: List[Dict[str, Any]] = []
    for entry in merged:
        norm_text = re.sub(r"\s+", "", entry.get("text", ""))
        if norm_text and norm_text in seen_text:
            continue
        if norm_text:
            seen_text[norm_text] = True
        deduped.append(entry)

    return deduped[:top_k]


def smart_truncate(text: str, max_chars: int) -> str:
    """
    在句读符号处收尾的截断，而不是硬切字符数。找不到合适的收尾点
    （比如长句本身就超过max_chars）才退化成硬切。
    """
    if len(text) <= max_chars:
        return text
    window = text[:max_chars]
    matches = list(SENTENCE_END.finditer(window))
    if matches:
        cut = matches[-1].end()
        # 收尾点太靠前（比如只截了20%内容）就不用它，避免过度丢内容
        if cut >= max_chars * 0.5:
            return text[:cut]
    return text[:max_chars] + "……"


def resolve_context_text(chunk: Dict[str, Any], max_chars: int) -> str:
    """
    优先使用父块（完整段落/篇章），没有父块字段就退化用子块本身。
    这里假设 vectorize_for_rag.py 在写入metadata时提供了 parent_text
    字段；如果你的建库脚本还没做父子分块，这里会自动回退到子块文本，
    但强烈建议尽快把父子分块补上（上一轮讨论过的原因：子块脱离语境
    是"徧於五嶽四瀆"这类翻译错误的根源之一）。
    """
    meta = chunk.get("metadata") or {}
    parent_text = meta.get("parent_text")
    source_text = parent_text if parent_text else chunk.get("text", "")
    return smart_truncate(source_text, max_chars)


# ═══════════════════════════════════════════════════════════════════════
#  Prompt 构建（统一入口，之前三处各写各的，现在收口成一个函数）
# ═══════════════════════════════════════════════════════════════════════

STRICT_SYSTEM_PROMPT = (
    "你是一位中国古典文献助手。你的任务是评估检索系统的效果，因此有严格要求：\n"
    "1. 只能依据下面提供的【参考文献】原文作答，不允许使用你自己已有的古文知识补充或纠正。\n"
    "2. 如果参考文献不足以回答问题，必须直接说明"
    "\"现有资料库检索到的内容不足以回答此问题\"，不要编造或用自己的知识填补。\n"
    "3. 回答用简洁的白话文，逐条说明依据的是哪条参考文献（用编号标注，如[1]）。\n"
    "4. 如果多条参考文献之间信息有冲突或不确定，明确指出，不要强行给出唯一答案。"
)

LOOSE_SYSTEM_PROMPT = (
    "你是一位精通中国古典文献的助手，请根据以下提供的古籍原文回答问题。\n"
    "1. 优先使用提供的原文作为依据，回答时用编号引用出处（如[1]）。\n"
    "2. 如果提供的原文不足以回答，坦诚说明，再补充你自己的古文知识作答，"
    "但必须明确标注哪些内容来自参考文献、哪些来自你自己的知识，不要混为一谈。\n"
    "3. 回答尽量用简洁的白话文。"
)


def build_context_block(chunks: List[Dict[str, Any]], max_chars: int) -> str:
    lines = []
    for i, c in enumerate(chunks, 1):
        meta = c.get("metadata") or {}
        source = meta.get("source_file", "?")
        book = meta.get("book", "?")
        text = resolve_context_text(c, max_chars)
        used_parent = "（完整段落）" if meta.get("parent_text") else "（片段，无父块回溯）"
        lines.append(f"[{i}] 出处: {source} ({book}) {used_parent}\n    原文: {text}")
    return "\n\n".join(lines)


def build_messages(query: str, chunks: List[Dict[str, Any]], max_chars: int, allow_supplement: bool) -> List[Dict]:
    """统一的messages构建入口，main/compare/interactive三处都应该调这个，
    不要再各自内联拼prompt——之前那样做，三处system prompt互相不一致，
    会让你没法判断评估结果的差异是来自检索方案还是prompt本身的随机扰动。"""
    system_prompt = LOOSE_SYSTEM_PROMPT if allow_supplement else STRICT_SYSTEM_PROMPT
    context = build_context_block(chunks, max_chars)
    user_prompt = f"问题: {query}\n\n参考文献:\n{context}\n\n请基于以上参考文献回答问题，并注明引用编号。"
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


# ═══════════════════════════════════════════════════════════════════════
#  LLM 调用
# ═══════════════════════════════════════════════════════════════════════

def ask_ollama_chat(messages: List[Dict]) -> str:
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "top_p": 0.9,
        },
    }
    resp = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=payload, timeout=180)
    resp.raise_for_status()
    return resp.json()["message"]["content"]


# ═══════════════════════════════════════════════════════════════════════
#  检索总入口：向量 + BM25 + RRF
# ═══════════════════════════════════════════════════════════════════════

def hybrid_search(
    collection: chromadb.Collection,
    bm25_indices: Optional[Dict[str, BM25Index]],
    space: str,
    query: str,
    top_k: int,
    scheme: Optional[str],
    use_bm25: bool,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """返回 (融合后的结果, 调试信息字典)"""
    query_emb = embed_query(query)
    # 向量和BM25各自多召回一些候选（top_k*3），再融合截断到top_k，
    # 避免两条路径各自只取top_k导致召回覆盖面太窄
    fetch_k = max(top_k * 3, 10)
    vec_results = vector_search(collection, query_emb, fetch_k, scheme, space)

    debug: Dict[str, Any] = {"vector_candidates": len(vec_results)}

    if use_bm25 and bm25_indices is not None:
        id_to_record = {r["id"]: r for r in vec_results}
        bm25_results = bm25_search(bm25_indices, id_to_record, query, fetch_k, scheme)
        debug["bm25_candidates"] = len(bm25_results)
        fused = rrf_fuse(vec_results, bm25_results, top_k)
    else:
        # 不用BM25时，退化成纯向量排序（对应 --no-bm25，方便你对比新旧行为）
        fused = sorted(vec_results, key=lambda x: x["vector_rank"])[:top_k]
        debug["bm25_candidates"] = 0

    debug["fused_count"] = len(fused)
    return fused, debug


# ═══════════════════════════════════════════════════════════════════════
#  显示
# ═══════════════════════════════════════════════════════════════════════

def print_divider(title: str = ""):
    width = 60
    if title:
        print(f"\n{'=' * 3} {title} {'=' * max(width - len(title) - 5, 0)}")
    else:
        print("=" * width)


def display_chunks(chunks: List[Dict[str, Any]]):
    print_divider("检索结果")
    print(f"找到 {len(chunks)} 条相关片段（融合排序）:\n")
    for i, c in enumerate(chunks, 1):
        meta = c.get("metadata") or {}
        text_short = (c.get("text") or "")[:100].replace("\n", " ")
        src = []
        if c.get("from_vector"):
            src.append(f"向量#{c.get('vector_rank', '?')}")
        if c.get("from_bm25"):
            src.append(f"BM25#{c.get('bm25_rank', '?')}")
        print(f"  [{i}] RRF分数: {c.get('rrf_score', 0):.4f}  来源: {', '.join(src) or '?'}")
        print(f"      方案:   {meta.get('chunk_scheme', '?')}")
        print(f"      出处:   {meta.get('source_file', '?')}")
        print(f"      ─ {text_short}...")
        print()


def display_answer_block(query: str, answer: str, model: str, chunks: List[Dict[str, Any]]):
    print("─" * 60)
    print(f"  ❓ {query}")
    print("─" * 60)
    print()
    for line in answer.strip().split("\n"):
        for wrapped in textwrap.wrap(line, width=72) or [""]:
            print(f"  {wrapped}")
    print()
    print("─" * 60)
    print(f"  引用 {len(chunks)} 条文献 | 模型: {model}")
    print("─" * 60)
    print()


# ═══════════════════════════════════════════════════════════════════════
#  结果落盘（用于批量评估复盘）
# ═══════════════════════════════════════════════════════════════════════

def log_result(
    log_dir: Optional[Path],
    query: str,
    chunks: List[Dict[str, Any]],
    messages: List[Dict],
    answer: str,
    debug: Dict[str, Any],
):
    if log_dir is None:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    record = {
        "timestamp": ts,
        "query": query,
        "model": LLM_MODEL,
        "embedding_model": EMBEDDING_MODEL,
        "debug": debug,
        "retrieved_chunks": [
            {
                "id": c.get("id"),
                "rrf_score": c.get("rrf_score"),
                "distance": c.get("distance"),
                "bm25_score": c.get("bm25_score"),
                "from_vector": c.get("from_vector", False),
                "from_bm25": c.get("from_bm25", False),
                "source_file": (c.get("metadata") or {}).get("source_file"),
                "text": c.get("text"),
                "has_parent_text": bool((c.get("metadata") or {}).get("parent_text")),
            }
            for c in chunks
        ],
        "full_messages": messages,
        "answer": answer,
    }
    path = log_dir / f"{ts}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  💾 完整记录已保存: {path}")


# ═══════════════════════════════════════════════════════════════════════
#  单次查询的完整流程（供 main / compare / interactive 复用）
# ═══════════════════════════════════════════════════════════════════════

def run_single_query(
    collection: chromadb.Collection,
    bm25_indices: Optional[Dict[str, BM25Index]],
    space: str,
    query: str,
    top_k: int,
    scheme: Optional[str],
    use_bm25: bool,
    max_chunk_chars: int,
    allow_supplement: bool,
    log_dir: Optional[Path],
    verbose: bool,
) -> Optional[str]:
    chunks, debug = hybrid_search(collection, bm25_indices, space, query, top_k, scheme, use_bm25)

    if not chunks:
        print(f"\n❌ 未找到与 '{query}' 相关的内容")
        print(f"   （向量候选经相似度过滤后为0 / BM25候选为0，说明语料库中大概率不包含这个主题，"
              f"未调用模型，避免在无关内容上强行拼凑答案）\n")
        return None

    if verbose:
        display_chunks(chunks)
    else:
        print(f"\n📖 检索到 {len(chunks)} 条片段 "
              f"(向量候选{debug['vector_candidates']} / BM25候选{debug['bm25_candidates']} / 融合后{debug['fused_count']})")
        for i, c in enumerate(chunks[:5], 1):
            txt = (c.get("text") or "")[:80].replace("\n", " ")
            print(f"  [{i}] (rrf={c.get('rrf_score', 0):.4f}) {txt}...")

    messages = build_messages(query, chunks, max_chunk_chars, allow_supplement)

    mode_label = "宽松模式(允许模型补充自身知识)" if allow_supplement else "严格模式(仅用检索到的原文)"
    print(f"\n🤖 正在调用 {LLM_MODEL} 生成回答... [{mode_label}]\n")
    t0 = time.time()
    answer = ask_ollama_chat(messages)
    elapsed = time.time() - t0

    display_answer_block(query, answer, f"{LLM_MODEL} ({elapsed:.1f}s)", chunks)
    log_result(log_dir, query, chunks, messages, answer, debug)
    return answer


# ═══════════════════════════════════════════════════════════════════════
#  双方案对比模式（semantic vs precision）
# ═══════════════════════════════════════════════════════════════════════

def run_compare(
    collection: chromadb.Collection,
    bm25_indices: Optional[Dict[str, BM25Index]],
    space: str,
    query: str,
    top_k: int,
    use_bm25: bool,
    max_chunk_chars: int,
    allow_supplement: bool,
    log_dir: Optional[Path],
):
    print(f"\n📝 问题: {query}")
    print(f"🔍 检索方案对比 (top-{top_k})")

    for scheme in ("semantic", "precision"):
        print_divider(f"方案: {scheme}")
        chunks, debug = hybrid_search(collection, bm25_indices, space, query, top_k, scheme, use_bm25)
        print(f"  向量候选{debug['vector_candidates']} / BM25候选{debug['bm25_candidates']} / 融合后{debug['fused_count']}")
        for i, c in enumerate(chunks[:3], 1):
            txt = (c.get("text") or "")[:80].replace("\n", " ")
            print(f"    [{i}] (rrf={c.get('rrf_score', 0):.4f}) {txt}...")
        if len(chunks) > 3:
            print(f"    ... 还有 {len(chunks) - 3} 条")

        if not chunks:
            print("  ❌ 该方案未检索到内容\n")
            continue

        messages = build_messages(query, chunks, max_chunk_chars, allow_supplement)
        answer = ask_ollama_chat(messages)
        print(f"\n  回答:\n")
        for line in answer.strip().split("\n"):
            print(f"    {line}")
        print()
        log_result(log_dir, f"{query} [{scheme}]", chunks, messages, answer, debug)


# ═══════════════════════════════════════════════════════════════════════
#  交互模式
# ═══════════════════════════════════════════════════════════════════════

def interactive_mode(
    collection: chromadb.Collection,
    bm25_indices: Optional[Dict[str, BM25Index]],
    space: str,
    top_k: int,
    use_bm25: bool,
    max_chunk_chars: int,
    allow_supplement: bool,
    log_dir: Optional[Path],
):
    print()
    print("  ╔══════════════════════════════════════════╗")
    print(f"  ║   古籍 RAG 交互测试 v2                    ")
    print(f"  ║   LLM: {LLM_MODEL:<30}")
    print(f"  ║   检索: 向量+BM25(RRF融合)                 ")
    print(f"  ║   模式: {'宽松(允许补充)' if allow_supplement else '严格(仅用检索原文)':<28}")
    print("  ║   输入问题或: /help /compare /quit         ")
    print("  ╚══════════════════════════════════════════╝")
    print()

    while True:
        try:
            query = input("  ❓ ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not query:
            continue
        if query == "/quit":
            break
        if query == "/help":
            print("  /help    显示帮助")
            print("  /compare 双方案对比模式")
            print("  /quit    退出")
            continue
        if query == "/compare":
            q2 = input("  输入要对比的问题: ").strip()
            if q2:
                run_compare(collection, bm25_indices, space, q2, top_k, use_bm25, max_chunk_chars, allow_supplement, log_dir)
            continue

        run_single_query(
            collection, bm25_indices, space, query, top_k, None,
            use_bm25, max_chunk_chars, allow_supplement, log_dir, verbose=False,
        )


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="古籍 RAG 测试 v2 — 向量+BM25混合检索，本地 Qwen3 评估",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python rag_test.py "伤寒论太阳病的症状"
              python rag_test.py --scheme semantic "辨证论治"
              python rag_test.py --compare "六经辨证"
              python rag_test.py --interactive
              python rag_test.py --no-bm25 "太阳之为病"
              python rag_test.py --allow-supplement "太阳之为病"
              python rag_test.py --log-dir ./eval_logs "太阳之为病"
        """),
    )

    parser.add_argument("query", nargs="?", help="搜索问题")
    parser.add_argument("--scheme", choices=["semantic", "precision"], help="指定检索方案（默认双方案合并）")
    parser.add_argument("--top-k", type=int, default=100, help="最终返回的片段数（默认 8）")
    parser.add_argument("--compare", "-c", action="store_true", help="双方案对比模式")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互模式")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示完整检索调试信息")
    parser.add_argument("--no-bm25", action="store_true", help="关闭BM25，只用向量检索（用于对比旧版行为）")
    parser.add_argument("--allow-supplement", action="store_true",
                         help="允许模型用自己的古文知识补充回答（默认关闭，评估检索质量时不建议开）")
    parser.add_argument("--max-chunk-chars", type=int, default=DEFAULT_MAX_CHUNK_CHARS,
                         help=f"送入prompt的单条上下文最大字符数（默认{DEFAULT_MAX_CHUNK_CHARS}，在句读处收尾，不硬切）")
    parser.add_argument("--log-dir", type=str, default=None,
                         help="把完整检索结果/prompt/回答落盘到这个目录，便于批量复盘评估")
    parser.add_argument("--bm25-cache-dir", type=str, default=str(_SCRIPT_DIR / ".bm25_cache"),
                         help="BM25索引缓存目录（默认 ./.bm25_cache）")

    args = parser.parse_args()

    # ── 检查 Ollama ──
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        print(f"🔗 Ollama: 已连接")
        if LLM_MODEL not in models:
            print(f"⚠️  模型 '{LLM_MODEL}' 未在 Ollama 中找到")
            print(f"   可用模型: {', '.join(models)}")
    except requests.RequestException as e:
        print(f"❌ Ollama 连接失败: {e}")
        print("   请先启动: ollama serve")
        sys.exit(1)

    # ── 连接 ChromaDB ──
    try:
        collection, space = connect_chromadb()
    except Exception as e:
        print(f"❌ ChromaDB 连接失败: {e}")
        print("   请先运行: python vectorize_for_rag.py")
        sys.exit(1)

    # ── 建/加载 BM25 索引 ──
    use_bm25 = not args.no_bm25
    bm25_indices = None
    if use_bm25:
        try:
            bm25_indices = build_or_load_bm25_index(collection, Path(args.bm25_cache_dir))
        except Exception as e:
            print(f"⚠️  BM25索引构建失败，本次退化为纯向量检索: {e}")
            use_bm25 = False

    log_dir = Path(args.log_dir) if args.log_dir else None

    # ── 交互模式 ──
    if args.interactive:
        interactive_mode(collection, bm25_indices, space, args.top_k, use_bm25,
                          args.max_chunk_chars, args.allow_supplement, log_dir)
        return

    # ── 对比模式 ──
    if args.compare:
        if not args.query:
            print("❌ 对比模式需要提供问题")
            sys.exit(1)
        run_compare(collection, bm25_indices, space, args.query, args.top_k, use_bm25,
                    args.max_chunk_chars, args.allow_supplement, log_dir)
        return

    # ── 单次问答 ──
    if not args.query:
        parser.print_help()
        sys.exit(1)

    run_single_query(
        collection, bm25_indices, space, args.query, args.top_k, args.scheme,
        use_bm25, args.max_chunk_chars, args.allow_supplement, log_dir, args.verbose,
    )


if __name__ == "__main__":
    main()


# ═══════════════════════════════════════════════════════════════════════
# CHANGELOG（相对上一版审计发现的修复）
# ═══════════════════════════════════════════════════════════════════════
#
# [高优先级修复]
# 1. 接入BM25（字符bigram分词，内存索引+磁盘缓存）+ RRF融合，不再是纯向量检索。
# 2. 上下文截断从硬切300字符改成"句读处收尾"的智能截断，默认上限提到500，
#    且优先使用metadata里的parent_text（父块/完整段落）而不是零散子块——
#    前提是你的建库脚本(vectorize_for_rag.py)要在metadata里写入parent_text
#    字段，这版脚本会自动检测，没有就回退到子块本身并在prompt里标注"无父块回溯"。
# 3. score计算改为先探测collection实际的距离度量（cosine还是L2），
#    不是cosine就不再硬算一个没有意义的"相似度"，只展示原始distance。
# 4. 新增严格模式(默认)：system prompt强制模型只用给定原文回答，不允许
#    补充自己的古文知识，用--allow-supplement切回宽松模式(生产场景用)。
#
# [中优先级修复]
# 5. 三处各写各的prompt统一收口到 build_messages()，不再有互相不一致的
#    system prompt措辞污染评估结果。
# 6. 新增 --log-dir，把每次查询的完整检索结果、完整prompt、完整回答
#    落盘成JSON，方便批量跑完之后统一复盘打分，而不是只看终端截断输出。
#
# [未处理，留给你下一步决定]
# - Query expansion / 古今词汇实体链接层：这版还是直接把原始问题拿去
#   embedding和BM25检索，没有做"现代词→古代异名"的转换。上次讨论过
#   这个必要性，建议先跑几十条真实查询看看命中率，再决定要不要接进来。
# - BM25全量拉取语料建索引，语料规模到百万级时需要换成磁盘化实现，
#   现在这版没做这个优化。