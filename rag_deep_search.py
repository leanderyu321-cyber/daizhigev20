#!/usr/bin/env python3
"""
RAG 深度搜索脚本 —— 围绕一个"话题"做多跳检索，产出可供文案写作直接使用的素材文档

为什么要有这个脚本（别忘了最初的目的）：
  完全让AI直接写文案，会有两个躲不开的问题——AI风味的表达、AI幻觉编造的
  事实。所以退而求其次：不让AI写文案本身，只让它帮你从本地知识库（daizhige
  古籍语料）里高效地"查资料"，资料本身必须是逐字摘录的原文，模型只负责
  判断相关性和定位摘录位置，不负责"写"。这份素材文档最终是给你（或者
  CrewAI里的WRITER角色）看的参考资料，不是成稿。

跟 rag_test.py 的关系：
  这个脚本直接复用 rag_test.py 里已经写好、测过的检索层（ChromaDB连接、
  BM25索引、RRF混合检索、相似度下限过滤、父块回溯），不重新实现一遍。
  必须把这两个文件放在同一目录下。

核心设计（对应我们讨论过的几条原则，不是随手写的）：
  1. 探索深度是代码写死的（--hops，默认2跳），不是让模型自己判断"够不够"、
     "要不要继续搜"——小模型不适合自主决定探索该在哪里停。
  2. 第2跳的关键词来自对第1跳"摘录内容"的分析（模型看到的是已经验证过
     的摘录，不是原始话题本身），这样跳数之间有真实的信息增量，而不是
     把同一个话题换个说法问两次。
  3. 相关性判断+摘录，一次只给模型看一段原文，不是几十条一起塞——上次
     "癌症"那次教训就是任务粒度太粗，模型处理不过来。
  4. 摘录内容强制程序化校验是否为原文逐字子串。校验不通过不会被静默
     丢弃或静默采信，而是保留在素材文档里并明确标红，需要你人工复核。
  5. 判断+摘录环节强制JSON结构化输出（Ollama的format=json），不依赖
     模型"记得"按格式回答。
  6. 全过程留痕：每一跳用了什么关键词、关键词从哪来、检索到什么、模型
     怎么判的、摘录是否通过校验——全部存成一份审计JSON，最终的素材
     文档只是这份审计记录的人类可读摘要。

用法:
  python rag_deep_search.py "汉代察举制的演变"
  python rag_deep_search.py "汉代察举制的演变" --hops 2 --keywords-per-hop 4
  python rag_deep_search.py "汉代察举制的演变" --output-dir ./materials
  python rag_deep_search.py --interactive

环境变量: 与 rag_test.py 共用同一套（OLLAMA_BASE_URL / EMBEDDING_MODEL /
          LLM_MODEL / CHROMA_DB_PATH / COLLECTION_NAME / MIN_SIMILARITY）

依赖: 与 rag_test.py 相同（chromadb requests numpy），无新增依赖。
      必须和 rag_test.py 放在同一目录，本脚本会直接 import 它。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

try:
    import requests
except ImportError as e:
    print(f"❌ 缺少依赖: {e}")
    print("   请运行: pip install chromadb requests numpy --break-system-packages")
    sys.exit(1)

try:
    import rag_test as base
except ImportError as e:
    print(f"❌ 找不到 rag_test.py: {e}")
    print("   本脚本需要和 rag_test.py 放在同一目录下（复用它的检索层）")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════════════════════════════

DEFAULT_HOPS = 2                    # 固定跳数，代码写死，不由模型判断
DEFAULT_KEYWORDS_PER_HOP = 4        # 每一跳生成几个检索关键词
DEFAULT_TOP_K_PER_KEYWORD = 8       # 每个关键词检索几条候选片段
DEFAULT_MAX_CHUNKS_JUDGE = 50       # 全流程最多对多少条唯一片段做逐条判断（控制总耗时）
DEFAULT_QUOTE_MAX_CHARS = 80        # 摘录句子的建议最大长度（模型端约束，非硬切）
DEFAULT_OUTPUT_DIR = str(_SCRIPT_DIR / "materials")


# ═══════════════════════════════════════════════════════════════════════
#  JSON 结构化输出调用（比 rag_test.py 的 ask_ollama_chat 多了 format=json）
# ═══════════════════════════════════════════════════════════════════════

def ask_ollama_json(messages: List[Dict], timeout: int = 120) -> Tuple[Optional[Dict], str]:
    """调用 Ollama chat，强制 JSON 结构化输出。

    返回 (解析后的dict或None, 原始返回文本)。原始文本始终返回，即便解析
    失败也要留痕，方便你在审计日志里查到底模型说了什么、为什么解析失败，
    而不是让失败静默变成一条空记录。
    """
    payload = {
        "model": base.LLM_MODEL,
        "messages": messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "top_p": 0.9},
    }
    resp = requests.post(f"{base.OLLAMA_BASE_URL}/api/chat", json=payload, timeout=timeout)
    resp.raise_for_status()
    raw = resp.json()["message"]["content"]

    text = raw.strip()
    # 少数模型即便给了format=json，仍会习惯性包一层```json代码块，这里兜底剥掉
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())

    try:
        return json.loads(text), raw
    except json.JSONDecodeError:
        # 再兜底一次：截取第一个 { 到最后一个 } 之间的内容再试
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0)), raw
            except json.JSONDecodeError:
                pass
        return None, raw


# ═══════════════════════════════════════════════════════════════════════
#  逐字校验：模型说"我摘了这句"，程序去原文里核实是不是真的逐字子串
# ═══════════════════════════════════════════════════════════════════════

def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def verify_verbatim(quote: str, source_text: str, fallback_text: str = "") -> bool:
    """检查 quote 是否为 source_text（或 fallback_text）的连续子串。

    只做空白字符归一化，不做任何语义/编辑距离上的"差不多算通过"——这道
    校验存在的意义就是拒绝"看起来像但其实不是"的内容，标准必须严格。
    """
    if not quote:
        return False
    q = _normalize(quote)
    if not q:
        return False
    if q in _normalize(source_text):
        return True
    if fallback_text and q in _normalize(fallback_text):
        return True
    return False


# ═══════════════════════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class JudgedChunk:
    chunk_id: str
    keyword: str
    hop: int
    source_file: str
    book: str
    relevant: bool
    quote: str
    reason: str
    verified: bool
    raw_model_output: str
    rrf_score: float = 0.0


@dataclass
class HopRecord:
    hop: int
    keywords: List[Dict[str, str]] = field(default_factory=list)   # [{"query":..., "origin":...}]
    retrieval_debug: Dict[str, Any] = field(default_factory=dict)  # keyword -> debug info
    judged_chunks: List[JudgedChunk] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════
#  第1跳：话题 → 检索关键词（结构化生成，覆盖不同角度）
# ═══════════════════════════════════════════════════════════════════════

KEYWORD_GEN_SYSTEM = (
    "你是一位古籍检索助手。你的任务不是回答问题，而是把一个写作话题拆解成"
    "几个适合拿去检索古籍语料库的具体检索词。\n"
    "要求：\n"
    "1. 每个检索词应聚焦话题的一个不同角度（例如：相关人物、具体事件、"
    "核心概念/术语、相关地点或朝代背景、他人评价或后世论述等），不要生成"
    "几个意思重复的近义词。\n"
    "2. 检索词要具体、适合字面/语义检索，不要生成完整问句。\n"
    "3. 只输出JSON，不要有任何其他文字，格式严格如下：\n"
    '{"queries": ["检索词1", "检索词2", "检索词3"]}'
)


def generate_initial_keywords(topic: str, n: int) -> Tuple[List[str], str]:
    messages = [
        {"role": "system", "content": KEYWORD_GEN_SYSTEM},
        {"role": "user", "content": f"写作话题: {topic}\n请生成 {n} 个检索词。"},
    ]
    parsed, raw = ask_ollama_json(messages)
    if parsed and isinstance(parsed.get("queries"), list):
        queries = [str(q).strip() for q in parsed["queries"] if str(q).strip()]
        if queries:
            return queries[:n], raw
    # 解析失败的兜底：直接用话题本身当唯一检索词，保证流程不中断，
    # 但会在审计日志里留下"关键词生成解析失败"的痕迹供你排查。
    print(f"  ⚠️  第1跳关键词生成解析失败，回退为使用话题原文检索。原始返回: {raw[:200]}")
    return [topic], raw


# ═══════════════════════════════════════════════════════════════════════
#  第2跳（及之后）：基于上一跳已验证的摘录，生成延伸检索词
# ═══════════════════════════════════════════════════════════════════════

FOLLOWUP_KEYWORD_GEN_SYSTEM = (
    "你是一位古籍检索助手。你会看到某个写作话题，以及针对这个话题已经"
    "从古籍库中检索并验证过的一批原文摘录。你的任务是找出这些摘录里"
    "出现的、值得进一步深挖的具体线索（比如摘录里提到的人名、地名、"
    "官职名、专有概念、引用的其他篇目等），并生成新的检索词去挖掘这些"
    "线索的更多细节。\n"
    "要求：\n"
    "1. 新检索词必须是从已有摘录内容延伸出来的具体线索，不能是原始话题"
    "本身的同义改写。\n"
    "2. 如果已有摘录信息量太少、看不出值得深挖的具体线索，可以少生成"
    "甚至返回空列表，不要为了凑数硬编。\n"
    "3. 只输出JSON，不要有任何其他文字，格式严格如下：\n"
    '{"queries": [{"query": "检索词", "origin": "这个检索词来自哪条摘录中的哪个线索，一句话说明"}]}'
)


def generate_followup_keywords(
    topic: str, prior_quotes: List[JudgedChunk], n: int
) -> Tuple[List[Dict[str, str]], str]:
    if not prior_quotes:
        return [], "(上一跳没有可用摘录，跳过)"

    material_lines = []
    for c in prior_quotes:
        material_lines.append(f"- 摘录: {c.quote}\n  相关性说明: {c.reason}")
    material_block = "\n".join(material_lines[:30])  # 防止上一跳摘录过多把prompt撑爆

    messages = [
        {"role": "system", "content": FOLLOWUP_KEYWORD_GEN_SYSTEM},
        {
            "role": "user",
            "content": (
                f"写作话题: {topic}\n\n已验证的摘录:\n{material_block}\n\n"
                f"请生成最多 {n} 个延伸检索词。"
            ),
        },
    ]
    parsed, raw = ask_ollama_json(messages)
    if parsed and isinstance(parsed.get("queries"), list):
        out = []
        for item in parsed["queries"][:n]:
            if isinstance(item, dict) and str(item.get("query", "")).strip():
                out.append({
                    "query": str(item["query"]).strip(),
                    "origin": str(item.get("origin", "")).strip(),
                })
            elif isinstance(item, str) and item.strip():
                out.append({"query": item.strip(), "origin": ""})
        return out, raw
    print(f"  ⚠️  延伸关键词生成解析失败，本跳不再新增检索词。原始返回: {raw[:200]}")
    return [], raw


# ═══════════════════════════════════════════════════════════════════════
#  逐条判断 + 摘录（一次只看一段原文）
# ═══════════════════════════════════════════════════════════════════════

JUDGE_SYSTEM_TEMPLATE = (
    "你是一位古籍文献助手，正在为一篇写作话题收集素材。你每次只会看到"
    "一段古籍原文，你的任务是：\n"
    "1. 判断这段原文是否与给定的话题/检索词相关，能否为写作提供有用的"
    "事实、说法或背景。\n"
    "2. 如果相关，从这段原文中【逐字摘录】一句最能支持相关性的话，"
    "必须是原文中连续出现的文字，不能改写、概括、翻译或拼接不连续的"
    "片段，长度控制在约{max_chars}字以内，若原文本身较短可全文摘录。\n"
    "3. 如果不相关，quote 留空字符串。\n"
    "4. 只输出JSON，不要有任何其他文字，格式严格如下：\n"
    '{{"relevant": true或false, "quote": "逐字摘录的原文", "reason": "一句话说明相关或不相关的理由"}}'
)


def judge_and_extract(topic: str, keyword: str, chunk_text: str, quote_max_chars: int) -> Tuple[Optional[Dict], str]:
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM_TEMPLATE.format(max_chars=quote_max_chars)},
        {
            "role": "user",
            "content": (
                f"写作话题: {topic}\n检索词: {keyword}\n\n"
                f"古籍原文:\n{chunk_text}"
            ),
        },
    ]
    return ask_ollama_json(messages, timeout=90)


# ═══════════════════════════════════════════════════════════════════════
#  跑一跳：关键词 → 检索 → 去重 → 逐条判断
# ═══════════════════════════════════════════════════════════════════════

def run_hop(
    hop: int,
    keywords: List[Dict[str, str]],
    topic: str,
    collection,
    bm25_indices,
    space: str,
    top_k_per_keyword: int,
    scheme: Optional[str],
    use_bm25: bool,
    quote_max_chars: int,
    already_judged_ids: Dict[str, JudgedChunk],
    remaining_budget: int,
) -> HopRecord:
    hop_record = HopRecord(hop=hop, keywords=keywords)
    print(f"\n{'━' * 60}\n  第 {hop} 跳：{len(keywords)} 个检索词\n{'━' * 60}")

    # 先把这一跳所有关键词的检索结果收集起来，按chunk去重，避免同一段
    # 原文因为被多个关键词命中而被判断好几遍（浪费时间，也让统计失真）。
    pending: Dict[str, Dict[str, Any]] = {}  # chunk_id -> {chunk, first_keyword}
    for kw_item in keywords:
        kw = kw_item["query"]
        print(f"  🔍 检索: {kw}")
        chunks, debug = base.hybrid_search(
            collection, bm25_indices, space, kw, top_k_per_keyword, scheme, use_bm25
        )
        hop_record.retrieval_debug[kw] = debug
        print(f"     候选 {debug.get('vector_candidates', 0)} (向量) / "
              f"{debug.get('bm25_candidates', 0)} (BM25) → 融合后 {debug.get('fused_count', 0)}")
        for c in chunks:
            cid = c.get("id")
            if not cid or cid in already_judged_ids or cid in pending:
                continue
            pending[cid] = {"chunk": c, "keyword": kw}

    if not pending:
        print("  （本跳所有检索词均无新增候选片段，可能已在上一跳全部覆盖过）")
        return hop_record

    todo = list(pending.items())
    if len(todo) > remaining_budget:
        print(f"  ⚠️  本跳候选 {len(todo)} 条，超出剩余判断预算 {remaining_budget}，"
              f"按融合排序只判断前 {remaining_budget} 条")
        todo = todo[:remaining_budget]

    print(f"  📋 开始逐条判断相关性（共 {len(todo)} 条唯一候选片段）...")
    for i, (cid, item) in enumerate(todo, 1):
        chunk = item["chunk"]
        keyword = item["keyword"]
        meta = chunk.get("metadata") or {}
        source_text = base.resolve_context_text(chunk, base.DEFAULT_MAX_CHUNK_CHARS)
        raw_chunk_text = chunk.get("text", "")

        t0 = time.time()
        parsed, raw = judge_and_extract(topic, keyword, source_text, quote_max_chars)
        elapsed = time.time() - t0

        if parsed is None:
            jc = JudgedChunk(
                chunk_id=cid, keyword=keyword, hop=hop,
                source_file=meta.get("source_file", "?"), book=meta.get("book", "?"),
                relevant=False, quote="", reason="模型输出JSON解析失败，判定为不相关（需人工核实原文）",
                verified=False, raw_model_output=raw, rrf_score=chunk.get("rrf_score", 0.0),
            )
        else:
            relevant = bool(parsed.get("relevant", False))
            quote = str(parsed.get("quote", "")).strip()
            reason = str(parsed.get("reason", "")).strip()
            verified = verify_verbatim(quote, source_text, raw_chunk_text) if relevant and quote else False
            jc = JudgedChunk(
                chunk_id=cid, keyword=keyword, hop=hop,
                source_file=meta.get("source_file", "?"), book=meta.get("book", "?"),
                relevant=relevant, quote=quote, reason=reason,
                verified=verified, raw_model_output=raw, rrf_score=chunk.get("rrf_score", 0.0),
            )

        already_judged_ids[cid] = jc
        hop_record.judged_chunks.append(jc)

        status = "✅相关" if jc.relevant else "・不相关"
        vflag = ""
        if jc.relevant and jc.quote:
            vflag = " [逐字校验通过]" if jc.verified else " [⚠️未通过逐字校验]"
        print(f"    [{i}/{len(todo)}] ({elapsed:.1f}s) {status}{vflag}  {cid[:40]}")

    return hop_record


# ═══════════════════════════════════════════════════════════════════════
#  素材文档组装
# ═══════════════════════════════════════════════════════════════════════

def build_materials_markdown(
    topic: str, hop_records: List[HopRecord], audit_path: Path
) -> str:
    all_judged: List[JudgedChunk] = [jc for hr in hop_records for jc in hr.judged_chunks]
    relevant = [jc for jc in all_judged if jc.relevant and jc.quote]
    verified = [jc for jc in relevant if jc.verified]
    unverified = [jc for jc in relevant if not jc.verified]

    lines: List[str] = []
    lines.append(f"# 素材文档：{topic}")
    lines.append("")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append(
        "> 本文档由本地知识库深度检索自动生成，供文案写作参考，**不是成稿**。"
        "所有摘录均为古籍原文的逐字摘录，并经程序自动校验是否为原文连续子串；"
        "标注\"⚠️未通过逐字校验\"的条目请务必对照原文人工核实后再使用，"
        "不要直接采信。"
    )
    lines.append("")

    # ── 搜索过程记录 ──
    lines.append("## 一、搜索过程记录")
    lines.append("")
    for hr in hop_records:
        lines.append(f"### 第 {hr.hop} 跳")
        if not hr.keywords:
            lines.append("（本跳未生成新检索词）")
        for kw in hr.keywords:
            origin = kw.get("origin", "")
            debug = hr.retrieval_debug.get(kw["query"], {})
            origin_str = f"　— 来源: {origin}" if origin else ""
            lines.append(
                f"- **{kw['query']}**{origin_str}　"
                f"（检索到候选 {debug.get('fused_count', 0)} 条）"
            )
        lines.append("")

    # ── 统计 ──
    lines.append("## 二、统计")
    lines.append("")
    lines.append(f"- 累计判断唯一片段: {len(all_judged)} 条")
    lines.append(f"- 判定为相关: {len(relevant)} 条")
    lines.append(f"- 其中通过逐字校验: {len(verified)} 条")
    lines.append(f"- 其中**未通过**逐字校验（需人工核实）: {len(unverified)} 条")
    lines.append("")

    # ── 摘录素材（按跳+关键词分组）──
    lines.append("## 三、摘录素材")
    lines.append("")
    counter = 0
    for hr in hop_records:
        by_keyword: Dict[str, List[JudgedChunk]] = {}
        for jc in hr.judged_chunks:
            if jc.relevant and jc.quote:
                by_keyword.setdefault(jc.keyword, []).append(jc)
        if not by_keyword:
            continue
        lines.append(f"### 第 {hr.hop} 跳检索结果")
        lines.append("")
        for kw, items in by_keyword.items():
            lines.append(f"#### 检索词: {kw}")
            lines.append("")
            for jc in items:
                counter += 1
                badge = "✅ 逐字校验通过" if jc.verified else "⚠️ 未通过逐字校验，请人工核实"
                lines.append(f"**[{counter}]** 出处: {jc.book}（{jc.source_file}） | {badge}")
                lines.append("")
                lines.append(f"> {jc.quote}")
                lines.append("")
                lines.append(f"相关性说明: {jc.reason}")
                lines.append("")
    if counter == 0:
        lines.append("（本次检索未找到任何判定为相关且成功摘录的素材，建议更换话题措辞后重试，"
                      "或检查知识库是否覆盖该话题的古今异名问题。）")
        lines.append("")

    # ── 附录 ──
    lines.append("## 四、附录")
    lines.append("")
    lines.append(f"- 完整检索与模型交互审计日志: `{audit_path}`")
    lines.append(f"- 检索模型: {base.EMBEDDING_MODEL}　问答/判断模型: {base.LLM_MODEL}")
    lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
#  审计日志组装
# ═══════════════════════════════════════════════════════════════════════

def build_audit_record(topic: str, hop_records: List[HopRecord]) -> Dict[str, Any]:
    return {
        "topic": topic,
        "timestamp": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "llm_model": base.LLM_MODEL,
        "embedding_model": base.EMBEDDING_MODEL,
        "hops": [
            {
                "hop": hr.hop,
                "keywords": hr.keywords,
                "retrieval_debug": hr.retrieval_debug,
                "judged_chunks": [
                    {
                        "chunk_id": jc.chunk_id,
                        "keyword": jc.keyword,
                        "source_file": jc.source_file,
                        "book": jc.book,
                        "relevant": jc.relevant,
                        "quote": jc.quote,
                        "reason": jc.reason,
                        "verified": jc.verified,
                        "rrf_score": jc.rrf_score,
                        "raw_model_output": jc.raw_model_output,
                    }
                    for jc in hr.judged_chunks
                ],
            }
            for hr in hop_records
        ],
    }


# ═══════════════════════════════════════════════════════════════════════
#  主流程：一个话题的完整深度搜索
# ═══════════════════════════════════════════════════════════════════════

def run_deep_search(
    topic: str,
    collection,
    bm25_indices,
    space: str,
    hops: int,
    keywords_per_hop: int,
    top_k_per_keyword: int,
    max_chunks_judge: int,
    quote_max_chars: int,
    scheme: Optional[str],
    use_bm25: bool,
    output_dir: Path,
) -> Tuple[Path, Path]:
    print(f"\n📝 话题: {topic}")
    print(f"⚙️  参数: {hops}跳 / 每跳{keywords_per_hop}个关键词 / 每关键词检索{top_k_per_keyword}条 / "
          f"总判断上限{max_chunks_judge}条")

    already_judged: Dict[str, JudgedChunk] = {}
    hop_records: List[HopRecord] = []
    budget = max_chunks_judge

    # ── 第1跳 ──
    initial_keywords, raw = generate_initial_keywords(topic, keywords_per_hop)
    hop1_keywords = [{"query": q, "origin": "话题直接扩展"} for q in initial_keywords]
    hop1 = run_hop(
        1, hop1_keywords, topic, collection, bm25_indices, space,
        top_k_per_keyword, scheme, use_bm25, quote_max_chars, already_judged, budget,
    )
    hop_records.append(hop1)
    budget -= len(hop1.judged_chunks)

    # ── 第2跳及之后（固定跳数，代码控制，不由模型判断是否继续）──
    for hop_n in range(2, hops + 1):
        if budget <= 0:
            print(f"\n  ⚠️  判断预算已用完（上限{max_chunks_judge}条），跳过第{hop_n}跳。"
                  f"如需更深入检索，可加大 --max-chunks-judge 重跑。")
            break

        prior_relevant = [jc for jc in hop_records[-1].judged_chunks if jc.relevant and jc.quote and jc.verified]
        followup_keywords, _ = generate_followup_keywords(topic, prior_relevant, keywords_per_hop)
        if not followup_keywords:
            print(f"\n  （未能从上一跳摘录中提炼出新的延伸检索词，第{hop_n}跳提前结束）")
            break

        hop_n_record = run_hop(
            hop_n, followup_keywords, topic, collection, bm25_indices, space,
            top_k_per_keyword, scheme, use_bm25, quote_max_chars, already_judged, budget,
        )
        hop_records.append(hop_n_record)
        budget -= len(hop_n_record.judged_chunks)

    # ── 落盘 ──
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    safe_topic = re.sub(r"[^\w\u4e00-\u9fff]+", "_", topic)[:40].strip("_") or "topic"

    audit_path = output_dir / f"{ts}_{safe_topic}_audit.json"
    audit_record = build_audit_record(topic, hop_records)
    audit_path.write_text(json.dumps(audit_record, ensure_ascii=False, indent=2), encoding="utf-8")

    doc_path = output_dir / f"{ts}_{safe_topic}_素材.md"
    doc_text = build_materials_markdown(topic, hop_records, audit_path)
    doc_path.write_text(doc_text, encoding="utf-8")

    all_judged = [jc for hr in hop_records for jc in hr.judged_chunks]
    relevant = [jc for jc in all_judged if jc.relevant and jc.quote]
    verified = [jc for jc in relevant if jc.verified]

    print(f"\n{'═' * 60}")
    print(f"  ✅ 完成: 共判断 {len(all_judged)} 条唯一片段，"
          f"{len(relevant)} 条相关，{len(verified)} 条通过逐字校验")
    print(f"  📄 素材文档: {doc_path}")
    print(f"  🗂  审计日志: {audit_path}")
    print(f"{'═' * 60}\n")

    return doc_path, audit_path


# ═══════════════════════════════════════════════════════════════════════
#  交互模式
# ═══════════════════════════════════════════════════════════════════════

def interactive_mode(collection, bm25_indices, space: str, args):
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   古籍 RAG 深度搜索 —— 素材收集模式        ")
    print(f"  ║   LLM: {base.LLM_MODEL:<30}")
    print(f"  ║   {args.hops}跳 / 每跳{args.keywords_per_hop}词 / 判断上限{args.max_chunks_judge}条")
    print("  ║   输入话题开始搜索，或 /quit 退出           ")
    print("  ╚══════════════════════════════════════════╝")
    print()
    while True:
        try:
            topic = input("  📝 话题 ❯ ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not topic:
            continue
        if topic == "/quit":
            break
        run_deep_search(
            topic, collection, bm25_indices, space,
            args.hops, args.keywords_per_hop, args.top_k_per_keyword,
            args.max_chunks_judge, args.quote_max_chars, args.scheme,
            not args.no_bm25, Path(args.output_dir),
        )


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="古籍 RAG 深度搜索 — 围绕一个话题多跳检索，产出可供文案写作使用的素材文档",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            '  python rag_deep_search.py "汉代察举制的演变"\n'
            '  python rag_deep_search.py "汉代察举制的演变" --hops 3 --keywords-per-hop 5\n'
            '  python rag_deep_search.py --interactive\n'
        ),
    )
    parser.add_argument("topic", nargs="?", help="写作话题")
    parser.add_argument("--hops", type=int, default=DEFAULT_HOPS,
                         help=f"固定跳数（代码控制，非模型自主判断，默认{DEFAULT_HOPS}）")
    parser.add_argument("--keywords-per-hop", type=int, default=DEFAULT_KEYWORDS_PER_HOP,
                         help=f"每跳生成的检索词数量（默认{DEFAULT_KEYWORDS_PER_HOP}）")
    parser.add_argument("--top-k-per-keyword", type=int, default=DEFAULT_TOP_K_PER_KEYWORD,
                         help=f"每个检索词取回的候选片段数（默认{DEFAULT_TOP_K_PER_KEYWORD}）")
    parser.add_argument("--max-chunks-judge", type=int, default=DEFAULT_MAX_CHUNKS_JUDGE,
                         help=f"全流程最多逐条判断多少条唯一片段，控制总耗时（默认{DEFAULT_MAX_CHUNKS_JUDGE}）")
    parser.add_argument("--quote-max-chars", type=int, default=DEFAULT_QUOTE_MAX_CHARS,
                         help=f"摘录建议最大字数（模型端约束，默认{DEFAULT_QUOTE_MAX_CHARS}）")
    parser.add_argument("--scheme", choices=["semantic", "precision"], default=None,
                         help="指定检索方案（默认双方案合并，与rag_test.py一致）")
    parser.add_argument("--no-bm25", action="store_true", help="关闭BM25，只用向量检索")
    parser.add_argument("--output-dir", type=str, default=DEFAULT_OUTPUT_DIR,
                         help=f"素材文档和审计日志的输出目录（默认 {DEFAULT_OUTPUT_DIR}）")
    parser.add_argument("--bm25-cache-dir", type=str, default=str(_SCRIPT_DIR / ".bm25_cache"),
                         help="BM25索引缓存目录（与rag_test.py共用同一份缓存）")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互模式，可连续输入多个话题")

    args = parser.parse_args()

    # ── 检查 Ollama ──
    try:
        resp = requests.get(f"{base.OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        print("🔗 Ollama: 已连接")
        if base.LLM_MODEL not in models:
            print(f"⚠️  模型 '{base.LLM_MODEL}' 未在 Ollama 中找到")
            print(f"   可用模型: {', '.join(models)}")
    except requests.RequestException as e:
        print(f"❌ Ollama 连接失败: {e}")
        print("   请先启动: ollama serve")
        sys.exit(1)

    # ── 连接 ChromaDB ──
    try:
        collection, space = base.connect_chromadb()
    except Exception as e:
        print(f"❌ ChromaDB 连接失败: {e}")
        print("   请先运行: python vectorize_for_rag.py")
        sys.exit(1)

    # ── 建/加载 BM25 索引 ──
    use_bm25 = not args.no_bm25
    bm25_indices = None
    if use_bm25:
        try:
            bm25_indices = base.build_or_load_bm25_index(collection, Path(args.bm25_cache_dir))
        except Exception as e:
            print(f"⚠️  BM25索引构建失败，本次退化为纯向量检索: {e}")
            use_bm25 = False

    if args.interactive:
        interactive_mode(collection, bm25_indices, space, args)
        return

    if not args.topic:
        parser.print_help()
        sys.exit(1)

    run_deep_search(
        args.topic, collection, bm25_indices, space,
        args.hops, args.keywords_per_hop, args.top_k_per_keyword,
        args.max_chunks_judge, args.quote_max_chars, args.scheme,
        use_bm25, Path(args.output_dir),
    )


if __name__ == "__main__":
    main()
