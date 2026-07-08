#!/usr/bin/env python3
"""
向量化脚本 —— 将「殆知阁」古文资料切分并向量化到 ChromaDB

双方案切分（解决古文搜索不准问题）：
  方案A (语义切分 / semantic): 大窗口500字 + 段落保持 + 20%重叠
    → 适合语义检索、问答检索（RAG 主通道）
  方案B (精确切分 / precision): 小窗口150字 + 句边界优先 + 30%重叠
    → 适合精确匹配、典出查询、短句检索（精度通道）

存储策略：
  同一 ChromaDB 集合，通过 metadata.chunk_scheme 字段区分方案。
  每条 chunk 携带原文、出处、朝代等元信息，可直接用于 RAG 检索。

用法:
  # 首次运行前安装依赖
  uv pip install chromadb tqdm requests PyYAML

  # 处理全部藏书目录（约800个文件）
  python vectorize_for_rag.py

  # 仅处理指定目录
  python vectorize_for_rag.py --source 医藏

  # 清空后重新索引
  python vectorize_for_rag.py --clear

  # 仅处理前 N 个文件（测试用）
  python vectorize_for_rag.py --limit 10

  # 搜索测试
  python vectorize_for_rag.py --search "伤寒论"

  # 索引统计
  python vectorize_for_rag.py --stats
"""

import argparse
import hashlib
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

# ── 依赖检查 ──────────────────────────────────────────────────────────

try:
    import chromadb
    from chromadb.config import Settings
    import requests
    from tqdm import tqdm
except ImportError as e:
    print(f"❌ 缺少依赖: {e}")
    print("   请运行: uv pip install chromadb tqdm requests PyYAML")
    sys.exit(1)

try:
    import yaml
except ImportError:
    yaml = None  # fallback: 手动解析 front matter


# ── 日志 ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vectorize")


# ── 配置 ──────────────────────────────────────────────────────────────

@dataclass
class Config:
    """可调配置参数"""
    # Ollama
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))

    # ChromaDB
    CHROMA_DB_PATH: str = os.getenv("CHROMA_DB_PATH", "./chroma_db")
    COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "classical_chinese_corpus")

    # 语料来源
    CORPUS_DIRS: List[str] = None

    # 方案A：语义切分
    SEMANTIC_CHUNK_SIZE: int = 500
    SEMANTIC_OVERLAP: float = 0.2

    # 方案B：精确切分
    PRECISION_CHUNK_SIZE: int = 150
    PRECISION_OVERLAP: float = 0.3

    def __post_init__(self):
        if self.CORPUS_DIRS is None:
            self.CORPUS_DIRS = [
                "史藏", "诗藏", "子藏", "艺藏",
                "儒藏", "易藏", "道藏", "医藏", "集藏",
            ]


# ═══════════════════════════════════════════════════════════════════════
#  第一步：YAML Front Matter 解析
# ═══════════════════════════════════════════════════════════════════════

def parse_front_matter(content: str) -> Tuple[Dict[str, Any], str]:
    """
    解析 Markdown 文件的 YAML front matter

    Args:
        content: 完整文件内容

    Returns:
        (metadata_dict, body_text)
    """
    if not content.startswith("---"):
        return {}, content

    # 找到第二个 ---
    second = content.find("\n---", 3)
    if second == -1:
        return {}, content

    yaml_block = content[3:second].strip()
    body = content[second + 4:].strip()

    metadata: Dict[str, Any] = {}

    if yaml and yaml_block:
        try:
            metadata = yaml.safe_load(yaml_block) or {}
        except Exception:
            pass

    if not metadata:
        # 手动降级解析：只提取顶级简单字段
        for line in yaml_block.split("\n"):
            line = line.strip()
            m = re.match(r'^(\w[\w_-]*)\s*:\s*(.+)$', line)
            if m:
                key = m.group(1)
                val = m.group(2).strip().strip("'\"")
                metadata[key] = val

    return metadata, body


# ═══════════════════════════════════════════════════════════════════════
#  第二步：双方案切分器
# ═══════════════════════════════════════════════════════════════════════

class SemanticChunker:
    """
    方案A — 语义切分

    策略:
      - chunk_size=500, overlap=20%
      - 优先按自然段落 (\n\n) 分块
      - 超大段落按句号/感叹号/问号断开
      - 保留完整段落上下文，适合语义检索
    """

    def __init__(self, chunk_size: int = 500, overlap_ratio: float = 0.2):
        self.chunk_size = chunk_size
        self.overlap_size = max(1, int(chunk_size * overlap_ratio))

    def chunk(self, text: str) -> List[Dict]:
        """
        切分文本

        Returns:
            [{"text": "...", "chunk_index": 0}, ...]
        """
        if not text.strip():
            return []

        chunks = []
        paragraphs = text.split("\n\n")

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(para) <= self.chunk_size:
                chunks.append({"text": para})
            else:
                for c in self._chunk_large_para(para):
                    chunks.append({"text": c})

        # 打上索引
        for i, c in enumerate(chunks):
            c["chunk_index"] = i

        return chunks

    def _chunk_large_para(self, para: str) -> Iterator[str]:
        """大段落字符级切分，优先在句边界断开"""
        pos = 0
        while pos < len(para):
            end = min(pos + self.chunk_size, len(para))

            # 在 chunk_size 范围内从后往前找句边界
            break_at = None
            for i in range(end, max(pos + self.chunk_size // 2, pos), -1):
                if i < len(para) and para[i] in "。！？\n":
                    break_at = i + 1
                    break

            if break_at is None or break_at <= pos:
                break_at = end

            chunk = para[pos:break_at].strip()
            if chunk:
                yield chunk

            pos = max(pos + 1, break_at - self.overlap_size)


class PrecisionChunker:
    """
    方案B — 精确切分

    策略:
      - chunk_size=150, overlap=30%
      - 更小窗口，更高重叠率
      - 严格优先按句号/感叹号/问号边界断开
      - 确保短句和短语不被切散，适合精确匹配
    """

    def __init__(self, chunk_size: int = 150, overlap_ratio: float = 0.3):
        self.chunk_size = chunk_size
        self.overlap_size = max(1, int(chunk_size * overlap_ratio))

    def chunk(self, text: str) -> List[Dict]:
        if not text.strip():
            return []

        chunks = []
        paragraphs = text.split("\n\n")

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(para) <= self.chunk_size:
                chunks.append({"text": para})
            else:
                for c in self._chunk_large_para(para):
                    chunks.append({"text": c})

        for i, c in enumerate(chunks):
            c["chunk_index"] = i

        return chunks

    def _chunk_large_para(self, para: str) -> Iterator[str]:
        """高精度滑动窗口，句边界优先"""
        pos = 0
        while pos < len(para):
            end = min(pos + self.chunk_size, len(para))

            # 优先在句边界断开（从 end 往前找）
            break_at = None
            for i in range(end, pos, -1):
                if i < len(para) and para[i] in "。！？；\n":
                    break_at = i + 1
                    break

            # 没找到句边界，退一步找逗号/顿号
            if break_at is None:
                for i in range(end, pos, -1):
                    if i < len(para) and para[i] in "，、：":
                        break_at = i + 1
                        break

            # 实在没有，就在 chunk_size 处硬切
            if break_at is None or break_at <= pos:
                break_at = end

            chunk = para[pos:break_at].strip()
            if chunk:
                yield chunk

            pos = max(pos + 1, break_at - self.overlap_size)


# ═══════════════════════════════════════════════════════════════════════
#  第三步：Ollama Embedding 生成
# ═══════════════════════════════════════════════════════════════════════

class OllamaEmbedder:
    """
    通过 Ollama API 批量生成 embedding

    使用 nomic-embed-text 模型（768维），支持批量请求
    """

    def __init__(self, base_url: str, model: str, batch_size: int = 32):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.batch_size = batch_size

    def health_check(self) -> bool:
        """检查 Ollama 是否可用"""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            logger.info(f"Ollama 可用，已加载模型: {', '.join(m for m in models if m)}")
            return True
        except requests.RequestException as e:
            logger.error(f"Ollama 连接失败: {e}")
            return False

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成 embedding

        Args:
            texts: 文本列表

        Returns:
            [[0.1, 0.2, ...], ...]  每个文本对应一个 768维向量
        """
        all_embeddings: List[List[float]] = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            try:
                resp = requests.post(
                    f"{self.base_url}/api/embed",
                    json={"model": self.model, "input": batch},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                batch_embeddings = data.get("embeddings", [])
                all_embeddings.extend(batch_embeddings)
            except requests.RequestException as e:
                logger.error(f"Embedding 请求失败 (batch {i // self.batch_size}): {e}")
                # 退回到逐条请求（更慢但可靠）
                for text in batch:
                    try:
                        resp = requests.post(
                            f"{self.base_url}/api/embed",
                            json={"model": self.model, "input": [text]},
                            timeout=60,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        emb = data.get("embeddings", [[0.0] * 768])[0]
                        all_embeddings.append(emb)
                    except requests.RequestException:
                        logger.warning(f"单条 embedding 也失败，用零向量代替: {text[:30]}...")
                        all_embeddings.append([0.0] * 768)

        return all_embeddings

    @property
    def vector_dim(self) -> int:
        """获取 embedding 向量维度（nomic-embed-text = 768）"""
        test_emb = self.embed(["测试"])
        return len(test_emb[0]) if test_emb else 768


# ═══════════════════════════════════════════════════════════════════════
#  第四步：ChromaDB 向量存储
# ═══════════════════════════════════════════════════════════════════════

class VectorStore:
    """ChromaDB 持久化向量存储管理"""

    def __init__(self, persist_dir: str, collection_name: str):
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self._client: Optional[chromadb.PersistentClient] = None
        self._collection: Optional[chromadb.Collection] = None

    def connect(self):
        """连接/创建 ChromaDB"""
        os.makedirs(self.persist_dir, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        logger.info(f"ChromaDB 已连接: {self.persist_dir}")

    def get_or_create_collection(self):
        """获取或创建集合"""
        if self._client is None:
            self.connect()
        try:
            self._collection = self._client.get_collection(self.collection_name)
            count = self._collection.count()
            logger.info(
                f"集合 '{self.collection_name}' 已存在，当前 {count} 条记录"
            )
        except (ValueError, chromadb.errors.NotFoundError):
            self._collection = self._client.create_collection(self.collection_name)
            logger.info(f"已创建新集合 '{self.collection_name}'")

        return self._collection

    def delete_collection(self):
        """删除集合"""
        if self._client is None:
            self.connect()
        try:
            self._client.delete_collection(self.collection_name)
            logger.info(f"已删除集合 '{self.collection_name}'")
        except (ValueError, chromadb.errors.NotFoundError):
            logger.info(f"集合 '{self.collection_name}' 不存在，跳过删除")

    def add_chunks(
        self,
        chunks: List[Dict],
        embeddings: List[List[float]],
        batch_size: int = 100,
    ):
        """
        批量写入 chunks 到 ChromaDB

        Args:
            chunks: [{"id", "text", "metadata", ...}, ...]
            embeddings: 对应的向量列表
            batch_size: 每批写入数
        """
        if self._collection is None:
            raise RuntimeError("请先调用 get_or_create_collection()")

        total = len(chunks)
        for i in range(0, total, batch_size):
            batch = chunks[i:i + batch_size]
            emb_batch = embeddings[i:i + batch_size]

            ids = [c["id"] for c in batch]
            texts = [c["text"] for c in batch]
            metas = [c["metadata"] for c in batch]

            self._collection.add(
                ids=ids,
                embeddings=emb_batch,
                documents=texts,
                metadatas=metas,
            )

        logger.info(f"写入 {total} 条到 ChromaDB")

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        scheme_filter: Optional[str] = None,
    ) -> List[Dict]:
        """
        搜索

        Args:
            query_embedding: 查询向量
            top_k: 返回条数
            scheme_filter: 过滤方案 None=全部, "semantic", "precision"

        Returns:
            [{"id", "text", "metadata", "distance"}, ...]
        """
        if self._collection is None:
            raise RuntimeError("请先调用 get_or_create_collection()")

        where: Optional[Dict] = None
        if scheme_filter:
            where = {"chunk_scheme": scheme_filter}

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        output = []
        if results["ids"]:
            for i in range(len(results["ids"][0])):
                output.append({
                    "id": results["ids"][0][i],
                    "text": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i],
                })
        return output

    def count(self) -> int:
        """获取集合中的记录数"""
        if self._collection is None:
            return 0
        return self._collection.count()

    def count_by_scheme(self) -> Dict[str, int]:
        """按方案统计"""
        if self._collection is None:
            return {"semantic": 0, "precision": 0}
        counts = {}
        for scheme in ("semantic", "precision"):
            try:
                cnt = self._collection.count(where={"chunk_scheme": scheme})
                counts[scheme] = cnt
            except Exception:
                counts[scheme] = 0
        return counts


# ═══════════════════════════════════════════════════════════════════════
#  第五步：文件扫描与元数据提取
# ═══════════════════════════════════════════════════════════════════════

def scan_md_files(
    workspace: Path, source_dirs: List[str], limit: Optional[int] = None
) -> List[Path]:
    """扫描所有目录下的 .md 文件"""
    files: List[Path] = []
    for dir_name in source_dirs:
        dir_path = workspace / dir_name
        if not dir_path.exists():
            logger.warning(f"目录不存在，跳过: {dir_path}")
            continue
        md_files = sorted(dir_path.rglob("*.md"))
        files.extend(md_files)
        logger.info(f"  {dir_name}: {len(md_files)} 个文件")

    if limit and limit < len(files):
        logger.info(f"  限制处理前 {limit} 个文件")
        files = files[:limit]

    return files


def extract_metadata_from_path(
    file_path: Path, front_matter: Dict[str, Any]
) -> Dict[str, str]:
    """
    从文件路径和 front matter 提取元数据

    Returns:
        {
            "book": "伤寒论",
            "category": "医藏",
            "author": "张仲景",
            "dynasty": "汉",
            "source_file": "医藏/伤寒论.md",
        }
    """
    # 从路径推断
    relative = file_path.relative_to(file_path.parent.parent)
    parts = relative.parts

    category = parts[0] if len(parts) >= 1 else ""
    book = file_path.stem

    # 从 front matter 尝试提取更多元数据
    author = ""
    dynasty = ""

    if front_matter:
        # author 可能在多个字段
        author_raw = front_matter.get("author", "")
        if author_raw:
            # 格式如 "[汉]张仲景" 或 "张仲景"
            m = re.match(r'\[([^\]]+)\](.*)', str(author_raw))
            if m:
                dynasty = m.group(1)
                author = m.group(2).strip()
            else:
                author = str(author_raw).strip("'\" ")

        # 如果 title 有嵌套结构
        title_info = front_matter.get("title", "")
        if isinstance(title_info, dict):
            book = title_info.get("zh-hans", title_info.get("zh-hant", book))

    return {
        "book": book,
        "category": category,
        "author": author,
        "dynasty": dynasty,
        "source_file": str(relative),
    }


# ═══════════════════════════════════════════════════════════════════════
#  第六步：主处理管道
# ═══════════════════════════════════════════════════════════════════════

def build_chunk_id(
    source_file: str, scheme: str, chunk_index: int
) -> str:
    """生成唯一 chunk ID"""
    raw = f"{source_file}_{scheme}_{chunk_index}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def process_file(
    file_path: Path,
    semantic_chunker: SemanticChunker,
    precision_chunker: PrecisionChunker,
) -> Tuple[List[Dict], List[Dict]]:
    """
    处理单个文件：读档 → 解析 front matter → 双方案切分

    Returns:
        (semantic_chunks, precision_chunks)
        每个 chunk 格式:
            {"id": "...", "text": "...", "metadata": {...}}
    """
    # 读文件
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = file_path.read_text(encoding="gbk")
        except UnicodeDecodeError:
            logger.warning(f"编码识别失败: {file_path}")
            return [], []

    # 解析 front matter
    front_matter, body = parse_front_matter(content)
    base_meta = extract_metadata_from_path(file_path, front_matter)

    if not body.strip():
        return [], []

    # 方案A：语义切分
    semantic_raw = semantic_chunker.chunk(body)
    semantic_chunks = []
    for c in semantic_raw:
        chunk_id = build_chunk_id(
            base_meta["source_file"], "semantic", c["chunk_index"]
        )
        semantic_chunks.append({
            "id": chunk_id,
            "text": c["text"],
            "metadata": {
                **base_meta,
                "chunk_scheme": "semantic",
                "chunk_index": c["chunk_index"],
            },
        })

    # 方案B：精确切分
    precision_raw = precision_chunker.chunk(body)
    precision_chunks = []
    for c in precision_raw:
        chunk_id = build_chunk_id(
            base_meta["source_file"], "precision", c["chunk_index"]
        )
        precision_chunks.append({
            "id": chunk_id,
            "text": c["text"],
            "metadata": {
                **base_meta,
                "chunk_scheme": "precision",
                "chunk_index": c["chunk_index"],
            },
        })

    return semantic_chunks, precision_chunks


def run_indexing(
    cfg: Config,
    vector_store: VectorStore,
    embedder: OllamaEmbedder,
    files: List[Path],
    clear_first: bool = False,
):
    """执行完整索引流程"""
    if clear_first:
        logger.info("清空现有集合...")
        vector_store.delete_collection()

    collection = vector_store.get_or_create_collection()

    # 初始化双方案切分器
    semantic_chunker = SemanticChunker(
        cfg.SEMANTIC_CHUNK_SIZE, cfg.SEMANTIC_OVERLAP
    )
    precision_chunker = PrecisionChunker(
        cfg.PRECISION_CHUNK_SIZE, cfg.PRECISION_OVERLAP
    )

    total_semantic = 0
    total_precision = 0
    all_chunks: List[Dict] = []
    failed_files = 0

    # ── 第1阶段：扫描 + 切分（仅展示统计） ──
    logger.info("=" * 50)
    logger.info("阶段1/3: 扫描并切分文件")
    logger.info("=" * 50)

    for fp in tqdm(files, desc="切分", unit="file"):
        sem_chunks, prec_chunks = process_file(
            fp, semantic_chunker, precision_chunker
        )
        if not sem_chunks and not prec_chunks:
            failed_files += 1
            continue
        total_semantic += len(sem_chunks)
        total_precision += len(prec_chunks)

    logger.info(f"  语义切片: {total_semantic}")
    logger.info(f"  精确切片: {total_precision}")
    logger.info(f"  合计: {total_semantic + total_precision}")
    if failed_files:
        logger.warning(f"  失败文件: {failed_files}")

    logger.info("")
    logger.info("=" * 50)
    logger.info("阶段2/3: 生成 Embedding + 写入 ChromaDB")
    logger.info("=" * 50)

    # 第2阶段：逐文件处理并写入
    # 每处理一个文件就切分、embedding、写入，避免内存爆炸
    processed_files = 0
    current_semantic = 0
    current_precision = 0

    for fp in tqdm(files, desc="索引", unit="file"):
        sem_chunks, prec_chunks = process_file(
            fp, semantic_chunker, precision_chunker
        )
        if not sem_chunks and not prec_chunks:
            continue

        # 合并两个方案的 chunks
        file_chunks = sem_chunks + prec_chunks
        texts = [c["text"] for c in file_chunks]

        # 生成 embedding
        embeddings = embedder.embed(texts)

        # 写入 ChromaDB（分批）
        batch_size = 50
        for i in range(0, len(file_chunks), batch_size):
            batch = file_chunks[i:i + batch_size]
            emb_batch = embeddings[i:i + batch_size]
            collection.add(
                ids=[c["id"] for c in batch],
                embeddings=emb_batch,
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
            )

        processed_files += 1
        current_semantic += len(sem_chunks)
        current_precision += len(prec_chunks)

    logger.info("")
    logger.info("=" * 50)
    logger.info("索引完成")
    logger.info("=" * 50)
    logger.info(f"  处理文件: {processed_files}")
    logger.info(f"  语义切片: {current_semantic}")
    logger.info(f"  精确切片: {current_precision}")
    logger.info(f"  合计: {current_semantic + current_precision}")

    # 提交确认
    count = vector_store.count()
    logger.info(f"  ChromaDB 最终记录数: {count}")


# ═══════════════════════════════════════════════════════════════════════
#  第七步：搜索命令
# ═══════════════════════════════════════════════════════════════════════

def run_search(
    cfg: Config,
    vector_store: VectorStore,
    embedder: OllamaEmbedder,
    query: str,
    top_k: int = 10,
    scheme: Optional[str] = None,
):
    """执行搜索"""
    collection = vector_store.get_or_create_collection()

    # 生成查询向量
    logger.info(f"搜索: '{query}'")
    query_embedding = embedder.embed([query])[0]

    # 搜索（ChromaDB 用 collection.query 替代 vector_store.search）
    where: Optional[Dict] = None
    if scheme:
        where = {"chunk_scheme": scheme}

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"] or not results["ids"][0]:
        print("\n没有找到相关结果\n")
        return

    print(f"\n🔍 搜索结果: '{query}'")
    print(f"   模式: {scheme or '全部'}")
    print(f"   结果数: {len(results['ids'][0])}\n")

    for i in range(len(results["ids"][0])):
        meta = results["metadatas"][0][i]
        text_preview = results["documents"][0][i][:120].replace("\n", " ")
        score = 1.0 - results["distances"][0][i]  # Cosine → similarity

        print(f"── [{i + 1}] 相似度: {score:.4f} ──")
        print(f"   出处: {meta.get('source_file', '?')}")
        print(f"   方案: {meta.get('chunk_scheme', '?')}")
        print(f"   文本: {text_preview}...")
        print()


# ═══════════════════════════════════════════════════════════════════════
#  第八步：统计命令
# ═══════════════════════════════════════════════════════════════════════

def run_stats(cfg: Config, vector_store: VectorStore):
    """显示索引统计"""
    collection = vector_store.get_or_create_collection()
    total = collection.count()

    # 按方案统计
    schemes: Dict[str, int] = {}
    try:
        # ChromaDB 的 count 不支持 where 过滤，需要改用 get
        all_data = collection.get(include=["metadatas"])
        if all_data["metadatas"]:
            for m in all_data["metadatas"]:
                s = m.get("chunk_scheme", "unknown")
                schemes[s] = schemes.get(s, 0) + 1
    except Exception:
        pass

    # 按分类统计
    categories: Dict[str, int] = {}
    if all_data and all_data.get("metadatas"):
        for m in all_data["metadatas"]:
            cat = m.get("category", "其他")
            categories[cat] = categories.get(cat, 0) + 1

    print("\n📊 ChromaDB 索引统计")
    print(f"  集合: {cfg.COLLECTION_NAME}")
    print(f"  存储路径: {cfg.CHROMA_DB_PATH}")
    print(f"  总记录: {total}")
    print()
    print("按方案:")
    for scheme, count in sorted(schemes.items()):
        print(f"  {scheme:12s}: {count}")
    print()
    print("按藏书分类:")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat:8s}: {count}")
    print()

    # 查看存储大小
    db_path = Path(cfg.CHROMA_DB_PATH)
    if db_path.exists():
        size_mb = sum(f.stat().st_size for f in db_path.rglob("*") if f.is_file())
        print(f"  磁盘占用: {size_mb / 1024 / 1024:.2f} MB")
    print()


# ═══════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="殆知阁古文资料向量化脚本 — 双方案切分 + ChromaDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python vectorize_for_rag.py                    # 处理全部藏书
  python vectorize_for_rag.py --source 医藏       # 指定目录
  python vectorize_for_rag.py --clear            # 清空重建
  python vectorize_for_rag.py --limit 10         # 仅测试前10个
  python vectorize_for_rag.py --search "太阳之为病"
  python vectorize_for_rag.py --stats
        """,
    )

    parser.add_argument(
        "--source", "-s",
        help="指定处理哪个藏书目录（如 医藏），不指定则处理全部",
    )
    parser.add_argument(
        "--limit", "-n", type=int, default=None,
        help="限制处理的文件数（测试用）",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="清空已有 ChromaDB 集合后重建",
    )
    parser.add_argument(
        "--search", type=str,
        help="搜索查询（不执行索引，只搜索）",
    )
    parser.add_argument(
        "--scheme", choices=["semantic", "precision"],
        help="搜索时指定方案过滤",
    )
    parser.add_argument(
        "--top-k", type=int, default=10,
        help="搜索返回条数（默认 10）",
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="显示索引统计（不执行索引）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只扫描统计，不写入 ChromaDB",
    )

    args = parser.parse_args()

    workspace = Path(__file__).parent.resolve()

    # 配置
    cfg = Config()
    if args.source:
        cfg.CORPUS_DIRS = [args.source]

    # 初始化
    embedder = OllamaEmbedder(
        cfg.OLLAMA_BASE_URL, cfg.EMBEDDING_MODEL, cfg.EMBEDDING_BATCH_SIZE
    )

    vector_store = VectorStore(cfg.CHROMA_DB_PATH, cfg.COLLECTION_NAME)

    # ── 搜索模式 ──
    if args.search:
        if not embedder.health_check():
            sys.exit(1)
        run_search(cfg, vector_store, embedder, args.search, args.top_k, args.scheme)
        return

    # ── 统计模式 ──
    if args.stats:
        run_stats(cfg, vector_store)
        return

    # ── 检查 Ollama ──
    if not embedder.health_check():
        logger.error("请先启动 Ollama: ollama serve")
        sys.exit(1)

    # ── 扫描文件 ──
    logger.info("扫描文件...")
    files = scan_md_files(workspace, cfg.CORPUS_DIRS, args.limit)
    if not files:
        logger.error(f"未找到 .md 文件（目录: {cfg.CORPUS_DIRS}）")
        sys.exit(1)
    logger.info(f"共发现 {len(files)} 个 Markdown 文件")

    # 估算 token 用量
    total_chars = sum(f.stat().st_size for f in files)
    logger.info(f"总文本大小: {total_chars / 1024 / 1024:.1f} MB")
    # nomic-embed-text: ~350 chars per batch, roughly estimate
    estimated_semantic = total_chars // cfg.SEMANTIC_CHUNK_SIZE * 2
    estimated_precision = total_chars // cfg.PRECISION_CHUNK_SIZE * 2
    estimated_total = estimated_semantic + estimated_precision
    logger.info(f"预估切片数: 语义 {estimated_semantic} + 精确 {estimated_precision} = {estimated_total}")
    logger.info("")

    # ── Dry run ──
    if args.dry_run:
        logger.info("Dry-run 模式：仅统计，不写入")
        total_sem = 0
        total_pre = 0
        semantic_chunker = SemanticChunker(cfg.SEMANTIC_CHUNK_SIZE, cfg.SEMANTIC_OVERLAP)
        precision_chunker = PrecisionChunker(cfg.PRECISION_CHUNK_SIZE, cfg.PRECISION_OVERLAP)
        for fp in tqdm(files, desc="分析", unit="file"):
            sem_chunks, prec_chunks = process_file(fp, semantic_chunker, precision_chunker)
            total_sem += len(sem_chunks)
            total_pre += len(prec_chunks)
        print(f"\n📊 Dry-run 统计:")
        print(f"  文件数: {len(files)}")
        print(f"  语义切片: {total_sem}")
        print(f"  精确切片: {total_pre}")
        print(f"  合计切片: {total_sem + total_pre}")
        return

    # ── 主索引流程 ──
    run_indexing(cfg, vector_store, embedder, files, args.clear)

    # ── 完成 ──
    print("\n✅ 向量化完成！\n")
    print("  搜索示例:")
    print("    python vectorize_for_rag.py --search \"太阳之为病\"")
    print("    python vectorize_for_rag.py --search \"辨证论治\" --scheme semantic")
    print("    python vectorize_for_rag.py --stats\n")


if __name__ == "__main__":
    main()
