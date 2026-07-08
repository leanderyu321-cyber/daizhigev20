#!/usr/bin/env python3
"""
RAG 测试脚本 —— 用本地模型测试向量化知识库的检索效果

工作流程：
  1. 接收用户问题
  2. 用 nomic-embed-text 将问题向量化，到 ChromaDB 检索相关古文段落
  3. 构建 prompt（带上下文）
  4. 调用 qwen3:8b 回答问题
  5. 输出答案 + 引用来源

用法:
  python rag_test.py "伤寒论中太阳病的症状是什么"
  python rag_test.py --scheme semantic "辨证论治的核心思想"
  python rag_test.py --scheme precision "太阳之为病" --top-k 5
  python rag_test.py --interactive               # 交互模式

环境变量:
  OLLAMA_BASE_URL     Ollama 地址（默认 http://localhost:11434）
  EMBEDDING_MODEL     向量模型（默认 nomic-embed-text）
  LLM_MODEL           问答模型（默认 qwen3:8b-q4_K_M）
  CHROMA_DB_PATH      ChromaDB 路径（默认 ./chroma_db）
  COLLECTION_NAME     集合名（默认 classical_chinese_corpus）
"""

import argparse
import os
import sys
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Any

# ── 依赖检查 ──────────────────────────────────────────────────────────

try:
    import chromadb
    from chromadb.config import Settings
    import requests
except ImportError as e:
    print(f"❌ 缺少依赖: {e}")
    print("   请运行: source .venv/bin/activate && uv pip install chromadb requests")
    sys.exit(1)


# ── 配置 ──────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3:8b-q4_K_M")
CHROMA_DB_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "classical_chinese_corpus")


# ═══════════════════════════════════════════════════════════════════════
#  检索模块
# ═══════════════════════════════════════════════════════════════════════

def connect_chromadb() -> chromadb.Collection:
    """连接 ChromaDB 并获取集合"""
    client = chromadb.PersistentClient(
        path=CHROMA_DB_PATH,
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_collection(COLLECTION_NAME)
    count = collection.count()
    print(f"📚 ChromaDB: {COLLECTION_NAME} ({count} 条记录)")
    return collection


def embed_query(query: str) -> List[float]:
    """调用 Ollama 生成查询向量"""
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={"model": EMBEDDING_MODEL, "input": [query]},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["embeddings"][0]


def search_chunks(
    collection: chromadb.Collection,
    query_embedding: List[float],
    top_k: int = 8,
    scheme: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """检索相似片段"""
    where = {"chunk_scheme": scheme} if scheme else None

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    if results["ids"]:
        for i in range(len(results["ids"][0])):
            chunks.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "score": 1.0 - results["distances"][0][i],
            })
    return chunks


# ═══════════════════════════════════════════════════════════════════════
#  Prompt 构建 & LLM 调用
# ═══════════════════════════════════════════════════════════════════════

def build_prompt(query: str, chunks: List[Dict]) -> str:
    """构建带上下文的 prompt"""

    # 整理上下文
    context_lines = []
    for i, c in enumerate(chunks, 1):
        source = c["metadata"].get("source_file", "?")
        scheme = c["metadata"].get("chunk_scheme", "?")
        book = c["metadata"].get("book", "?")
        # 截取太长文本防止窗口溢出
        text = c["text"]
        if len(text) > 300:
            text = text[:300] + "……"
        context_lines.append(
            f"[{i}] 出处: {source} ({book})\n"
            f"    原文: {text}\n"
        )

    context = "\n".join(context_lines)

    system_prompt = """你是一位精通中国古典文献的 AI 助手。请根据以下提供的古籍原文回答问题。

要求：
1. 优先使用提供的原文作为依据，回答时引用出处
2. 如果提供的原文不足以回答，坦诚说明，并基于你自己的古文知识补充回答（但仍需注明哪些来自参考文献、哪些来自你的知识）
3. 回答尽量用简洁的白话文
4. 引用格式：[数字]表示第几条参考文献

以下是与问题相关的古籍原文："""

    user_prompt = f"""问题: {query}

参考文献:
{context}

请基于以上参考文献回答问题，并注明引用编号。"""

    return f"{system_prompt}\n\n{user_prompt}"


def ask_ollama(prompt: str) -> str:
    """调用本地模型生成回答"""
    payload = {
        "model": LLM_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "top_p": 0.9,
            "num_predict": 2048,
        },
    }

    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["response"]


def ask_ollama_chat(messages: List[Dict]) -> str:
    """调用 Ollama chat API（qwen3 支持 chat 格式）"""
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "top_p": 0.9,
        },
    }

    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/chat",
        json=payload,
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["message"]["content"]


# ═══════════════════════════════════════════════════════════════════════
#  显示
# ═══════════════════════════════════════════════════════════════════════

def print_divider(title: str = ""):
    width = 60
    if title:
        print(f"\n{'=' * 3} {title} {'=' * (width - len(title) - 5)}")
    else:
        print("=" * width)


def display_chunks(chunks: List[Dict]):
    """显示检索结果"""
    print_divider("检索结果")
    print(f"找到 {len(chunks)} 条相关片段:\n")

    for i, c in enumerate(chunks, 1):
        meta = c["metadata"]
        text_short = c["text"][:100].replace("\n", " ")
        print(f"  [{i}] 相似度: {c['score']:.4f}")
        print(f"      方案:   {meta.get('chunk_scheme', '?')}")
        print(f"      出处:   {meta.get('source_file', '?')}")
        print(f"      ─ {text_short}...")
        print()


def display_answer(answer: str, model: str):
    """显示 AI 回答"""
    print_divider(f"模型回答 ({model})")
    print()
    # 自动换行使其更易读
    for line in answer.strip().split("\n"):
        for wrapped in textwrap.wrap(line, width=72):
            print(f"  {wrapped}")
    print()


def display_answer_raw(query: str, answer: str, model: str):
    """显示简洁版 Q&A"""
    print()
    print(f"  ❓ {query}")
    print(f"  🤖 [{model}]")
    for line in answer.strip().split("\n"):
        print(f"     {line}")
    print()


# ═══════════════════════════════════════════════════════════════════════
#  双方案对比模式
# ═══════════════════════════════════════════════════════════════════════

def run_compare(
    collection: chromadb.Collection,
    query: str,
    top_k: int = 6,
):
    """
    双方案对比：分别用 semantic 和 precision 检索 + 问答，对比效果
    """
    query_emb = embed_query(query)

    print(f"\n📝 问题: {query}")
    print(f"🔍 检索方案对比 (top-{top_k})")

    for scheme in ("semantic", "precision"):
        print_divider(f"方案: {scheme}")

        # 检索
        chunks = search_chunks(collection, query_emb, top_k, scheme)

        # 显示检索结果摘要
        print(f"  检索到 {len(chunks)} 条片段")
        for i, c in enumerate(chunks[:3], 1):
            txt = c["text"][:80].replace("\n", " ")
            print(f"    [{i}] ({c['score']:.4f}) {txt}...")
        if len(chunks) > 3:
            print(f"    ... 还有 {len(chunks)-3} 条")

        # 生成回答
        prompt_content = []
        for c in chunks:
            prompt_content.append(
                f"[{c['metadata'].get('source_file','?')}] {c['text']}"
            )
        context = "\n\n".join(prompt_content)

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位精通中国古典文献的 AI 助手。请根据以下提供的古籍原文回答问题。"
                    "回答要简洁，引用出处。如果原文不足，坦诚说明。"
                ),
            },
            {
                "role": "user",
                "content": f"问题: {query}\n\n古籍原文:\n{context}\n\n请回答：{query}",
            },
        ]

        answer = ask_ollama_chat(messages)
        print(f"\n  回答:\n")
        for line in answer.strip().split("\n"):
            print(f"    {line}")
        print()


# ═══════════════════════════════════════════════════════════════════════
#  交互模式
# ═══════════════════════════════════════════════════════════════════════

def interactive_mode(collection: chromadb.Collection):
    """交互式问答"""
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║   殆知阁古籍 RAG 交互测试               ║")
    print("  ║   LLM: qwen3:8b  Embedding: nomic       ║")
    print("  ║   输入问题或: /help /compare /quit       ║")
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
                run_compare(collection, q2)
            continue

        # 正常检索 + 问答
        query_emb = embed_query(query)

        # 同时检索两种方案
        sem_chunks = search_chunks(collection, query_emb, 4, "semantic")
        prec_chunks = search_chunks(collection, query_emb, 4, "precision")
        all_chunks = sem_chunks + prec_chunks
        # 按分数排序去重
        seen = set()
        merged = []
        for c in all_chunks:
            if c["id"] not in seen:
                seen.add(c["id"])
                merged.append(c)
        merged.sort(key=lambda x: -x["score"])

        if not merged:
            print("  ❌ 未找到相关内容\n")
            continue

        # 显示检索结果
        print(f"\n  📖 找到 {len(merged)} 条相关片段")
        for i, c in enumerate(merged[:5], 1):
            txt = c["text"][:80].replace("\n", " ")
            print(f"    [{i}] ({c['score']:.4f}) [{c['metadata']['chunk_scheme']}] {txt}...")
        print()

        # 生成回答
        context_parts = []
        for c in merged[:8]:
            meta = c["metadata"]
            context_parts.append(f"[{meta.get('source_file','?')}] {c['text']}")
        context = "\n\n".join(context_parts)

        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位精通中国古典文献的 AI 助手。"
                    "根据以下提供的古籍原文回答问题。引用出处。"
                ),
            },
            {
                "role": "user",
                "content": f"问题: {query}\n\n古籍原文:\n{context}\n\n请回答：{query}",
            },
        ]

        print("  🤖 思考中...")
        answer = ask_ollama_chat(messages)
        print()
        for line in answer.strip().split("\n"):
            print(f"  {line}")
        print("\n" + "-" * 50 + "\n")


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="殆知阁古籍 RAG 测试 — 用本地 Qwen3 测试向量化效果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            示例:
              python rag_test.py "伤寒论太阳病的症状"
              python rag_test.py --scheme semantic "辨证论治"
              python rag_test.py --scheme precision "太阳之为病"
              python rag_test.py --compare "六经辨证"
              python rag_test.py --interactive
              python rag_test.py --top-k 12 "阳明病"
        """),
    )

    parser.add_argument("query", nargs="?", help="搜索问题")
    parser.add_argument(
        "--scheme", choices=["semantic", "precision"],
        help="指定使用哪个检索方案（默认同时使用两个方案合并）",
    )
    parser.add_argument(
        "--top-k", type=int, default=8,
        help="检索的片段数（默认 8）",
    )
    parser.add_argument(
        "--compare", "-c", action="store_true",
        help="双方案对比模式：分别展示两个方案的检索和回答效果",
    )
    parser.add_argument(
        "--interactive", "-i", action="store_true",
        help="交互模式：连续问答",
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="简洁输出模式（只显示 Q&A，不显示检索细节）",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="详细输出（显示完整检索结果）",
    )

    args = parser.parse_args()

    # ── 检查 Ollama ──
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        print(f"🔗 Ollama: 已连接")
        if LLM_MODEL not in models:
            print(f"⚠️  模型 '{LLM_MODEL}' 未在 Ollama 中找到")
            print(f"   可用模型: {', '.join(m for m in models)}")
    except requests.RequestException as e:
        print(f"❌ Ollama 连接失败: {e}")
        print("   请先启动: ollama serve")
        sys.exit(1)

    # ── 连接 ChromaDB ──
    try:
        collection = connect_chromadb()
    except Exception as e:
        print(f"❌ ChromaDB 连接失败: {e}")
        print("   请先运行: python vectorize_for_rag.py")
        sys.exit(1)

    # ── 交互模式 ──
    if args.interactive:
        interactive_mode(collection)
        return

    # ── 对比模式 ──
    if args.compare:
        if not args.query:
            print("❌ 对比模式需要提供问题")
            sys.exit(1)
        run_compare(collection, args.query, args.top_k)
        return

    # ── 单次问答 ──
    if not args.query:
        parser.print_help()
        sys.exit(1)

    query = args.query
    query_emb = embed_query(query)

    # 检索
    if args.scheme:
        chunks = search_chunks(collection, query_emb, args.top_k, args.scheme)
        label = f"方案: {args.scheme}"
    else:
        # 默认同时检索两种方案合并
        sem = search_chunks(collection, query_emb, args.top_k // 2, "semantic")
        prec = search_chunks(collection, query_emb, args.top_k // 2, "precision")
        seen = set()
        chunks = []
        for c in sem + prec:
            if c["id"] not in seen:
                seen.add(c["id"])
                chunks.append(c)
        chunks.sort(key=lambda x: -x["score"])
        chunks = chunks[:args.top_k]
        label = "双方案合并"

    if not chunks:
        print(f"\n❌ 未找到与 '{query}' 相关的内容\n")
        print("  提示：可能需要先向量化更多数据")
        print(f"    python vectorize_for_rag.py --source 医藏\n")
        return

    # 显示结果
    if args.verbose:
        display_chunks(chunks)
    elif not args.raw:
        print(f"\n📖 检索到 {len(chunks)} 条相关片段 ({label})")
        for i, c in enumerate(chunks[:5], 1):
            txt = c["text"][:80].replace("\n", " ")
            print(f"  [{i}] ({c['score']:.4f}) [{c['metadata']['chunk_scheme']}] {txt}...")

    # 构建 prompt
    context_parts = []
    for c in chunks:
        meta = c["metadata"]
        context_parts.append(f"[出处: {meta.get('source_file','?')}] {c['text']}")
    context = "\n\n".join(context_parts)

    # 调用 LLM
    if args.raw:
        # 简洁模式
        messages = [
            {
                "role": "system",
                "content": "你是中国古典文献专家。根据提供的古籍原文回答，引用出处。",
            },
            {
                "role": "user",
                "content": f"问题: {query}\n\n古籍原文:\n{context}\n\n请回答：{query}",
            },
        ]
        print(f"\n  ❓ {query}")
        print(f"  🤖 {LLM_MODEL}")
        answer = ask_ollama_chat(messages)
        for line in answer.strip().split("\n"):
            print(f"     {line}")
        print()
    else:
        # 详细模式
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一位精通中国古典文献的 AI 助手。请根据以下提供的古籍原文回答问题。\n\n"
                    "要求：\n"
                    "1. 优先使用提供的原文作为依据，回答时引用出处\n"
                    "2. 如果原文不足以回答，坦诚说明，再补充你的知识\n"
                    "3. 回答尽量用白话文\n"
                    "4. 引用格式：[出处文件名]"
                ),
            },
            {
                "role": "user",
                "content": f"问题: {query}\n\n古籍原文:\n{context}\n\n请基于以上古籍原文回答：{query}",
            },
        ]

        print(f"\n🤖 正在调用 {LLM_MODEL} 生成回答...\n")
        answer = ask_ollama_chat(messages)

        print("─" * 60)
        print(f"  ❓ {query}")
        print("─" * 60)
        print()
        for line in answer.strip().split("\n"):
            print(f"  {line}")
        print()
        print("─" * 60)
        print(f"  引用 {len(chunks)} 条文献 | 方案: {label}")
        print("─" * 60)
        print()


if __name__ == "__main__":
    main()
