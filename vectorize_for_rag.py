#!/usr/bin/env python3
"""
向量化脚本 v2 —— 将「殆知阁」古文资料切分并向量化到 ChromaDB
（在原版基础上做的审计修复，改动说明见文末 CHANGELOG）

三层切分结构（这版最核心的改动）：
  父块 (paragraph unit)：按段落/结构边界切出的完整语义单元，不做二次
                          切碎，只用来在检索命中子块时提供完整上下文，
                          本身不参与向量检索。
  子块A (semantic)：大窗口500字，供语义检索
  子块B (precision)：小窗口150字，供精确匹配
  → semantic 和 precision 两种子块的 metadata 里都带着各自所属父块的
    parent_id 和完整 parent_text，检索命中任意一个子块，都能拿到完整
    上下文，而不是只有被截断的片段本身。

用法:
  # 首次运行前安装依赖
  uv pip install chromadb tqdm requests PyYAML
  # 可选：如果要用繁简归一化功能
  uv pip install opencc-python-reimplemented

  python vectorize_for_rag.py                    # 处理全部藏书
  python vectorize_for_rag.py --source 医藏       # 指定目录
  python vectorize_for_rag.py --clear             # 清空重建
  python vectorize_for_rag.py --limit 10          # 仅测试前10个
  python vectorize_for_rag.py --normalize-variants # 归一化繁简/异体字
  python vectorize_for_rag.py --search "太阳之为病"
  python vectorize_for_rag.py --stats
"""

import argparse
import hashlib
import logging
import os
import re
import sys
from dataclasses import dataclass, field
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

try:
    from opencc import OpenCC
    _OPENCC_AVAILABLE = True
except ImportError:
    _OPENCC_AVAILABLE = False


# ── 日志 ──────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("vectorize")


# ── 配置 ──────────────────────────────────────────────────────────────

_SCRIPT_DIR = Path(__file__).resolve().parent
_DEFAULT_CHROMA_PATH = str(_SCRIPT_DIR / "chroma_db")


@dataclass
class Config:
    """可调配置参数"""
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    EMBEDDING_BATCH_SIZE: int = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))

    CHROMA_DB_PATH: str = os.getenv("CHROMA_DB_PATH", _DEFAULT_CHROMA_PATH)
    COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "classical_chinese_corpus")

    CORPUS_DIRS: List[str] = field(default_factory=list)

    # 方案A：语义切分（子块）
    SEMANTIC_CHUNK_SIZE: int = 500
    SEMANTIC_OVERLAP: float = 0.2

    # 方案B：精确切分（子块）
    PRECISION_CHUNK_SIZE: int = 150
    PRECISION_OVERLAP: float = 0.3

    # 父块：段落原文如果超过这个长度，说明该"段落"本身可能是整篇未分段
    # 的文本（比如没有\n\n分隔），会被记录一条警告，提示你去检查源文件
    # 的排版格式，而不是默默按这个上限硬切父块本身。
    PARENT_SANITY_LIMIT: int = 4000

    def __post_init__(self):
        if not self.CORPUS_DIRS:
            self.CORPUS_DIRS = [
                "史藏", "诗藏", "子藏", "艺藏",
                "儒藏", "易藏", "道藏", "医藏", "集藏",
            ]


# ═══════════════════════════════════════════════════════════════════════
#  第一步：YAML Front Matter 解析
# ═══════════════════════════════════════════════════════════════════════

def parse_front_matter(content: str) -> Tuple[Dict[str, Any], str]:
    if not content.startswith("---"):
        return {}, content

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
        for line in yaml_block.split("\n"):
            line = line.strip()
            m = re.match(r'^(\w[\w_-]*)\s*:\s*(.+)$', line)
            if m:
                key = m.group(1)
                val = m.group(2).strip().strip("'\"")
                metadata[key] = val

    return metadata, body


# ═══════════════════════════════════════════════════════════════════════
#  第二步：文本归一化（可选，繁简/异体字）
# ═══════════════════════════════════════════════════════════════════════

class TextNormalizer:
    """
    统一繁简体，避免同一实体因为繁简不一致，在BM25(字面匹配)和向量检索
    里都出现该命中却没命中的情况。默认关闭——如果你的语料本来就是统一
    繁体、且你希望保留原貌，不要开这个选项；只有当你确认语料存在繁简
    混用时才建议开启。
    """

    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.converter = None
        if enabled:
            if not _OPENCC_AVAILABLE:
                logger.warning(
                    "已请求 --normalize-variants，但未安装 opencc-python-reimplemented，"
                    "本次运行将跳过归一化。请运行: "
                    "uv pip install opencc-python-reimplemented"
                )
                self.enabled = False
            else:
                # t2s: 繁体转简体。如果你希望统一成繁体，改成 's2t'
                self.converter = OpenCC('t2s')

    def normalize(self, text: str) -> str:
        if not self.enabled or self.converter is None:
            return text
        return self.converter.convert(text)


# ═══════════════════════════════════════════════════════════════════════
#  第三步：父块切分 + 双方案子块切分
# ═══════════════════════════════════════════════════════════════════════

SENTENCE_END = "。！？\n"
SENTENCE_END_STRICT = "。！？；\n"
PAUSE_MARKS = "，、："


SENTENCE_PUNCT = "。！？；，、："
HEADING_MAX_CHARS = 20  # 超过这个长度不太可能是纯标题，按正文处理


def _looks_like_heading(paragraph: str) -> bool:
    """
    识别"纯标题"段落的启发式规则：短、且不含任何句读标点。
    古籍的章节标题（如"辨太阳病脉证并治上"）通常符合这个特征，
    正文即使很短，一般也会带标点。这个规则不针对任何具体书名/
    篇名硬编码，靠的是结构特征，适用于不同典籍。

    这类段落如果单独存成一个chunk，会因为文本极短、检索词占比高，
    在BM25里获得不成比例的高分（把它挤进top-k却没有实际内容），
    所以改成合并进下一段正文，作为该段正文的前缀语境，而不是
    自己单独可被检索到。
    """
    p = paragraph.strip()
    if not p or len(p) > HEADING_MAX_CHARS:
        return False
    return not any(ch in p for ch in SENTENCE_PUNCT)


def split_into_parent_units(text: str, sanity_limit: int) -> List[str]:
    """
    父块 = 段落。这一版明确把"父块划分"和"子块切分"拆成两个独立步骤，
    父块本身不做二次截断（除非单个段落长到超过sanity_limit，这种情况
    大概率是源文件没有用\\n\\n分段，只是警告提示，不静默硬切，避免
    你误以为父块划分正常工作了）。

    额外处理：识别出的"纯标题"段落不会单独成为一个父块，而是合并
    进紧随其后的正文段落，作为该段正文的前缀（保留标题信息用于
    展示/溯源，但不让它单独被检索命中）。
    """
    raw_paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    if len(raw_paragraphs) <= 1 and len(text.strip()) > sanity_limit:
        logger.warning(
            f"检测到一个疑似未正确分段的文本块（长度{len(text.strip())}字，"
            f"未找到\\n\\n分隔）。父块回溯功能在这种文件上效果会打折扣，"
            f"建议检查源文件排版，或考虑改用按句号分段的兜底策略。"
        )

    merged: List[str] = []
    pending_heading = ""
    for para in raw_paragraphs:
        if _looks_like_heading(para):
            # 连续多个标题（比如卷标题+篇标题连在一起）就累积拼在一起
            pending_heading = f"{pending_heading}{para}　" if pending_heading else para
            continue
        if pending_heading:
            merged.append(f"【{pending_heading}】{para}")
            pending_heading = ""
        else:
            merged.append(para)

    if pending_heading:
        # 整篇最后剩一个孤立标题（没有正文跟在后面），只能单独保留，
        # 这种情况很少见，不强行丢弃以免漏内容
        merged.append(pending_heading)

    return merged


class SubChunker:
    """
    通用滑动窗口切分器，供 SemanticChunker / PrecisionChunker 复用，
    去掉原版里两个类几乎重复的 _chunk_large_para 实现。
    """

    def __init__(self, chunk_size: int, overlap_ratio: float, strict_boundary: bool):
        self.chunk_size = chunk_size
        self.overlap_size = max(1, int(chunk_size * overlap_ratio))
        self.boundary_chars = SENTENCE_END_STRICT if strict_boundary else SENTENCE_END
        self.strict_boundary = strict_boundary

    def chunk_paragraph(self, para: str) -> List[str]:
        if len(para) <= self.chunk_size:
            return [para]
        return list(self._chunk_large(para))

    def _chunk_large(self, para: str) -> Iterator[str]:
        pos = 0
        n = len(para)
        while pos < n:
            end = min(pos + self.chunk_size, n)
            break_at = self._find_boundary(para, pos, end)
            if break_at is None or break_at <= pos:
                break_at = end

            chunk = para[pos:break_at].strip()
            if chunk:
                yield chunk

            pos = max(pos + 1, break_at - self.overlap_size)

    def _find_boundary(self, para: str, pos: int, end: int) -> Optional[int]:
        search_floor = max(pos + self.chunk_size // 2, pos) if not self.strict_boundary else pos
        for i in range(end, search_floor, -1):
            if i < len(para) and para[i] in self.boundary_chars:
                return i + 1
        if self.strict_boundary:
            # 精确切分：句边界找不到，退一步找逗号/顿号
            for i in range(end, pos, -1):
                if i < len(para) and para[i] in PAUSE_MARKS:
                    return i + 1
        return None


def make_semantic_chunker(cfg: Config) -> SubChunker:
    return SubChunker(cfg.SEMANTIC_CHUNK_SIZE, cfg.SEMANTIC_OVERLAP, strict_boundary=False)


def make_precision_chunker(cfg: Config) -> SubChunker:
    return SubChunker(cfg.PRECISION_CHUNK_SIZE, cfg.PRECISION_OVERLAP, strict_boundary=True)


# ═══════════════════════════════════════════════════════════════════════
#  第四步：Ollama Embedding 生成
# ═══════════════════════════════════════════════════════════════════════

class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, batch_size: int = 32):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.batch_size = batch_size

    def health_check(self) -> bool:
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


# ═══════════════════════════════════════════════════════════════════════
#  第五步：ChromaDB 向量存储
# ═══════════════════════════════════════════════════════════════════════
# hnsw:space 显式设为 cosine——这是上一轮审计发现的问题：默认是L2，
# "score = 1 - distance" 这个公式只有在cosine距离下才有意义。这里
# 显式声明，检索端就不用再猜了。

class VectorStore:
    def __init__(self, persist_dir: str, collection_name: str):
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self._client: Optional[chromadb.PersistentClient] = None
        self._collection: Optional[chromadb.Collection] = None

    def connect(self):
        os.makedirs(self.persist_dir, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        logger.info(f"ChromaDB 已连接，实际路径: {os.path.abspath(self.persist_dir)}")

    def get_or_create_collection(self):
        if self._client is None:
            self.connect()
        try:
            self._collection = self._client.get_collection(self.collection_name)
            count = self._collection.count()
            logger.info(f"集合 '{self.collection_name}' 已存在，当前 {count} 条记录")
        except (ValueError, chromadb.errors.NotFoundError):
            self._collection = self._client.create_collection(
                self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"已创建新集合 '{self.collection_name}' (距离度量: cosine)")

        return self._collection

    def delete_collection(self):
        if self._client is None:
            self.connect()
        try:
            self._client.delete_collection(self.collection_name)
            logger.info(f"已删除集合 '{self.collection_name}'")
        except (ValueError, chromadb.errors.NotFoundError):
            logger.info(f"集合 '{self.collection_name}' 不存在，跳过删除")

    def add_chunks(self, chunks: List[Dict], embeddings: List[List[float]], batch_size: int = 100):
        if self._collection is None:
            raise RuntimeError("请先调用 get_or_create_collection()")

        total = len(chunks)
        for i in range(0, total, batch_size):
            batch = chunks[i:i + batch_size]
            emb_batch = embeddings[i:i + batch_size]
            self._collection.upsert(
                ids=[c["id"] for c in batch],
                embeddings=emb_batch,
                documents=[c["text"] for c in batch],
                metadatas=[c["metadata"] for c in batch],
            )
        logger.info(f"写入 {total} 条到 ChromaDB")

    def count(self) -> int:
        if self._collection is None:
            return 0
        return self._collection.count()


# ═══════════════════════════════════════════════════════════════════════
#  第六步：文件扫描与元数据提取
# ═══════════════════════════════════════════════════════════════════════

def scan_md_files(
    workspace: Path,
    source_dirs: List[str],
    limit: Optional[int] = None,
    explicit_files: Optional[List[str]] = None,
) -> List[Path]:
    """
    扫描 .md 文件。

    如果传入了 explicit_files（对应CLI的 --file），直接用这批文件，
    完全跳过目录扫描逻辑——这是给"测试性切分某几个具体文件"用的，
    不受 --source/--limit 影响。路径可以是相对workspace的相对路径，
    也可以是绝对路径。
    """
    if explicit_files:
        files: List[Path] = []
        for raw in explicit_files:
            p = Path(raw)
            if not p.is_absolute():
                p = workspace / raw
            if not p.exists():
                logger.warning(f"指定的文件不存在，跳过: {p}")
                continue
            if p.suffix != ".md":
                logger.warning(f"指定的文件不是 .md，跳过: {p}")
                continue
            files.append(p)
        logger.info(f"  --file 模式: 指定了 {len(explicit_files)} 个路径，实际有效 {len(files)} 个")
        return files

    files = []
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


def extract_metadata_from_path(file_path: Path, front_matter: Dict[str, Any]) -> Dict[str, str]:
    """
    从文件路径和 front matter 提取元数据。这版加了 edition 字段——
    从front matter的 edition/version/底本 几个可能的键名里尝试取值，
    取不到就留空并不强行猜测，方便你后续按"有无版本信息"筛出需要
    人工补充的条目。
    """
    relative = file_path.relative_to(file_path.parent.parent)
    parts = relative.parts

    category = parts[0] if len(parts) >= 1 else ""
    book = file_path.stem

    author = ""
    dynasty = ""
    edition = ""

    if front_matter:
        author_raw = front_matter.get("author", "")
        if author_raw:
            m = re.match(r'\[([^\]]+)\](.*)', str(author_raw))
            if m:
                dynasty = m.group(1)
                author = m.group(2).strip()
            else:
                author = str(author_raw).strip("'\" ")

        title_info = front_matter.get("title", "")
        if isinstance(title_info, dict):
            book = title_info.get("zh-hans", title_info.get("zh-hant", book))

        for key in ("edition", "version", "底本", "source_edition"):
            if front_matter.get(key):
                edition = str(front_matter[key]).strip("'\" ")
                break

    return {
        "book": book,
        "category": category,
        "author": author,
        "dynasty": dynasty,
        "edition": edition,
        "source_file": str(relative),
    }


# ═══════════════════════════════════════════════════════════════════════
#  第七步：主处理管道 —— 父块 → 双方案子块（这版的核心改动）
# ═══════════════════════════════════════════════════════════════════════

def build_chunk_id(source_file: str, scheme: str, index: int, text: str) -> str:
    """
    ID 现在把文本内容的哈希也纳入进去，而不是只用文件名+方案+序号。
    好处：以后调整 chunk_size 重新索引，同一个位置如果文本内容变了，
    会自然生成新ID，不会用旧ID静默覆盖成完全不同的内容；重复运行
    参数不变时，同样的内容会得到同样的ID，配合 upsert 天然去重。
    """
    content_hash = hashlib.md5(text.encode("utf-8")).hexdigest()[:8]
    raw = f"{source_file}_{scheme}_{index}_{content_hash}"
    return hashlib.md5(raw.encode()).hexdigest()[:20]


def build_parent_id(source_file: str, para_index: int) -> str:
    raw = f"{source_file}_parent_{para_index}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def process_file(
    file_path: Path,
    semantic_chunker: SubChunker,
    precision_chunker: SubChunker,
    normalizer: TextNormalizer,
    sanity_limit: int,
) -> List[Dict]:
    """
    处理单个文件：读档 → 解析 front matter → 按段落划父块 →
    每个父块派生出 semantic + precision 两级子块，子块 metadata
    都携带完整的 parent_text，同一父块下的子块之间还互相记录了
    prev_chunk_id / next_chunk_id，供检索端做"再往前后各拉一条"
    式的轻量扩展（比整段父块更便宜的一种冗余手段）。

    Returns:
        一个扁平的 chunk 列表（semantic + precision 混合），每条：
            {"id", "text", "metadata"}
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            content = file_path.read_text(encoding="gbk")
        except UnicodeDecodeError:
            logger.warning(f"编码识别失败: {file_path}")
            return []

    front_matter, body = parse_front_matter(content)
    base_meta = extract_metadata_from_path(file_path, front_matter)

    if not body.strip():
        return []

    body = normalizer.normalize(body)

    parent_units = split_into_parent_units(body, sanity_limit)
    if not parent_units:
        return []

    all_chunks: List[Dict] = []

    for para_idx, parent_text in enumerate(parent_units):
        parent_id = build_parent_id(base_meta["source_file"], para_idx)

        for scheme, chunker in (("semantic", semantic_chunker), ("precision", precision_chunker)):
            sub_texts = chunker.chunk_paragraph(parent_text)
            scheme_chunks = []

            for sub_idx, sub_text in enumerate(sub_texts):
                chunk_id = build_chunk_id(base_meta["source_file"], scheme, f"{para_idx}_{sub_idx}", sub_text)
                scheme_chunks.append({
                    "id": chunk_id,
                    "text": sub_text,
                    "metadata": {
                        **base_meta,
                        "chunk_scheme": scheme,
                        "parent_id": parent_id,
                        "parent_index": para_idx,
                        "sub_index": sub_idx,
                        # parent_text 是这版最关键的新增字段，rag_test_v2.py
                        # 的 resolve_context_text() 会优先读这个字段。
                        "parent_text": parent_text,
                    },
                })

            # 同方案内相邻子块的前后向链接，供检索端做更轻量的上下文扩展
            for i, c in enumerate(scheme_chunks):
                c["metadata"]["prev_chunk_id"] = scheme_chunks[i - 1]["id"] if i > 0 else ""
                c["metadata"]["next_chunk_id"] = scheme_chunks[i + 1]["id"] if i < len(scheme_chunks) - 1 else ""

            all_chunks.extend(scheme_chunks)

    return all_chunks


def run_indexing(
    cfg: Config,
    vector_store: VectorStore,
    embedder: OllamaEmbedder,
    normalizer: TextNormalizer,
    files: List[Path],
    clear_first: bool = False,
):
    """
    执行完整索引流程。这版去掉了原来"先切一遍算统计、再切一遍真正写入"
    的重复计算——切分本身不贵，但800个文件跑两遍终究是浪费，现在只跑
    一遍，统计数字在真正处理的同时累加。
    """
    if clear_first:
        logger.info("清空现有集合...")
        vector_store.delete_collection()

    vector_store.get_or_create_collection()

    semantic_chunker = make_semantic_chunker(cfg)
    precision_chunker = make_precision_chunker(cfg)

    total_semantic = 0
    total_precision = 0
    processed_files = 0
    failed_files = 0

    logger.info("=" * 50)
    logger.info("开始处理（切分 + Embedding + 写入 一遍完成）")
    logger.info("=" * 50)

    for fp in tqdm(files, desc="索引", unit="file"):
        chunks = process_file(fp, semantic_chunker, precision_chunker, normalizer, cfg.PARENT_SANITY_LIMIT)
        if not chunks:
            failed_files += 1
            continue

        texts = [c["text"] for c in chunks]
        embeddings = embedder.embed(texts)
        vector_store.add_chunks(chunks, embeddings, batch_size=50)

        processed_files += 1
        total_semantic += sum(1 for c in chunks if c["metadata"]["chunk_scheme"] == "semantic")
        total_precision += sum(1 for c in chunks if c["metadata"]["chunk_scheme"] == "precision")

    logger.info("")
    logger.info("=" * 50)
    logger.info("索引完成")
    logger.info("=" * 50)
    logger.info(f"  处理文件: {processed_files}")
    logger.info(f"  失败/空文件: {failed_files}")
    logger.info(f"  语义切片: {total_semantic}")
    logger.info(f"  精确切片: {total_precision}")
    logger.info(f"  合计: {total_semantic + total_precision}")
    logger.info(f"  ChromaDB 最终记录数: {vector_store.count()}")


# ═══════════════════════════════════════════════════════════════════════
#  第八步：搜索命令（这版会正确展示是否用到了 parent_text）
# ═══════════════════════════════════════════════════════════════════════

def run_search(
    cfg: Config,
    vector_store: VectorStore,
    embedder: OllamaEmbedder,
    query: str,
    top_k: int = 10,
    scheme: Optional[str] = None,
):
    collection = vector_store.get_or_create_collection()

    logger.info(f"搜索: '{query}'")
    query_embedding = embedder.embed([query])[0]

    where: Optional[Dict] = {"chunk_scheme": scheme} if scheme else None

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
        # collection 已固定用 cosine 距离创建，这里的换算是可靠的
        score = 1.0 - results["distances"][0][i]
        has_parent = bool(meta.get("parent_text"))

        print(f"── [{i + 1}] 相似度: {score:.4f} {'(有父块可回溯)' if has_parent else '(⚠️无父块)'} ──")
        print(f"   出处: {meta.get('source_file', '?')}")
        print(f"   方案: {meta.get('chunk_scheme', '?')}")
        print(f"   文本: {text_preview}...")
        print()


# ═══════════════════════════════════════════════════════════════════════
#  第九步：统计命令
# ═══════════════════════════════════════════════════════════════════════

def run_stats(cfg: Config, vector_store: VectorStore):
    collection = vector_store.get_or_create_collection()
    total = collection.count()

    schemes: Dict[str, int] = {}
    categories: Dict[str, int] = {}
    with_parent = 0
    missing_edition = 0

    all_data = collection.get(include=["metadatas"])
    metadatas = all_data.get("metadatas") or []
    for m in metadatas:
        s = m.get("chunk_scheme", "unknown")
        schemes[s] = schemes.get(s, 0) + 1
        cat = m.get("category", "其他")
        categories[cat] = categories.get(cat, 0) + 1
        if m.get("parent_text"):
            with_parent += 1
        if not m.get("edition"):
            missing_edition += 1

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
    print(f"  带父块回溯的记录: {with_parent}/{total}")
    print(f"  缺失版本信息的记录: {missing_edition}/{total}")
    print()

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
        description="殆知阁古文资料向量化脚本 v2 — 父块回溯 + 双方案切分 + ChromaDB",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python vectorize_for_rag.py                    # 处理全部藏书
  python vectorize_for_rag.py --source 医藏       # 指定目录
  python vectorize_for_rag.py --file 医藏/伤寒论.md              # 测试单个文件
  python vectorize_for_rag.py --file 医藏/伤寒论.md --dry-run    # 只看切分结果，不写入
  python vectorize_for_rag.py --file 医藏/伤寒论.md --file 史藏/史记.md  # 测试多个指定文件
  python vectorize_for_rag.py --clear             # 清空重建
  python vectorize_for_rag.py --limit 10          # 仅测试前10个（不能和--file同时用）
  python vectorize_for_rag.py --normalize-variants # 归一化繁简体
  python vectorize_for_rag.py --search "太阳之为病"
  python vectorize_for_rag.py --stats
        """,
    )

    parser.add_argument("--source", "-s", help="指定处理哪个藏书目录（如 医藏），不指定则处理全部")
    parser.add_argument("--file", "-f", action="append", default=None,
                         help="指定单个文件路径进行测试性切分/向量化，可重复传入多次指定多个文件，"
                              "会完全跳过 --source/--limit 的目录扫描逻辑。相对路径按脚本所在目录解析。")
    parser.add_argument("--limit", "-n", type=int, default=None, help="限制处理的文件数（测试用，对 --file 无效）")
    parser.add_argument("--clear", action="store_true", help="清空已有 ChromaDB 集合后重建")
    parser.add_argument("--search", type=str, help="搜索查询（不执行索引，只搜索）")
    parser.add_argument("--scheme", choices=["semantic", "precision"], help="搜索时指定方案过滤")
    parser.add_argument("--top-k", type=int, default=10, help="搜索返回条数（默认 10）")
    parser.add_argument("--stats", action="store_true", help="显示索引统计（不执行索引）")
    parser.add_argument("--dry-run", action="store_true", help="只扫描统计，不写入 ChromaDB")
    parser.add_argument("--normalize-variants", action="store_true",
                         help="归一化繁简体（需要 opencc-python-reimplemented），默认关闭")

    args = parser.parse_args()

    workspace = Path(__file__).parent.resolve()

    cfg = Config()
    if args.source:
        cfg.CORPUS_DIRS = [args.source]

    normalizer = TextNormalizer(enabled=args.normalize_variants)

    embedder = OllamaEmbedder(cfg.OLLAMA_BASE_URL, cfg.EMBEDDING_MODEL, cfg.EMBEDDING_BATCH_SIZE)
    vector_store = VectorStore(cfg.CHROMA_DB_PATH, cfg.COLLECTION_NAME)

    if args.search:
        if not embedder.health_check():
            sys.exit(1)
        run_search(cfg, vector_store, embedder, args.search, args.top_k, args.scheme)
        return

    if args.stats:
        run_stats(cfg, vector_store)
        return

    if not embedder.health_check():
        logger.error("请先启动 Ollama: ollama serve")
        sys.exit(1)

    logger.info("扫描文件...")
    files = scan_md_files(workspace, cfg.CORPUS_DIRS, args.limit, explicit_files=args.file)
    if not files:
        if args.file:
            logger.error(f"指定的 --file 均无效或不存在: {args.file}")
        else:
            logger.error(f"未找到 .md 文件（目录: {cfg.CORPUS_DIRS}）")
        sys.exit(1)
    logger.info(f"共发现 {len(files)} 个 Markdown 文件")

    total_chars = sum(f.stat().st_size for f in files)
    logger.info(f"总文本大小: {total_chars / 1024 / 1024:.1f} MB")
    logger.info("")

    if args.dry_run:
        logger.info("Dry-run 模式：仅统计，不写入")
        semantic_chunker = make_semantic_chunker(cfg)
        precision_chunker = make_precision_chunker(cfg)
        total_sem, total_pre, total_parents = 0, 0, 0
        for fp in tqdm(files, desc="分析", unit="file"):
            chunks = process_file(fp, semantic_chunker, precision_chunker, normalizer, cfg.PARENT_SANITY_LIMIT)
            total_sem += sum(1 for c in chunks if c["metadata"]["chunk_scheme"] == "semantic")
            total_pre += sum(1 for c in chunks if c["metadata"]["chunk_scheme"] == "precision")
            total_parents += len({c["metadata"]["parent_id"] for c in chunks})
        print(f"\n📊 Dry-run 统计:")
        print(f"  文件数: {len(files)}")
        print(f"  父块数: {total_parents}")
        print(f"  语义切片: {total_sem}")
        print(f"  精确切片: {total_pre}")
        print(f"  合计切片: {total_sem + total_pre}")
        return

    run_indexing(cfg, vector_store, embedder, normalizer, files, args.clear)

    print("\n✅ 向量化完成！\n")
    print("  搜索示例:")
    print("    python vectorize_for_rag.py --search \"太阳之为病\"")
    print("    python vectorize_for_rag.py --search \"辨证论治\" --scheme semantic")
    print("    python vectorize_for_rag.py --stats\n")


if __name__ == "__main__":
    main()


# ═══════════════════════════════════════════════════════════════════════
# CHANGELOG（相对上一版审计发现的修复）
# ═══════════════════════════════════════════════════════════════════════
#
# [最高优先级]
# 1. 引入"父块"概念：先按段落切出完整语义单元，semantic/precision两级
#    子块都从父块派生，metadata里都带上完整parent_text——这是这次
#    审计最关键的修复，直接对应你"给小模型冗余上下文"的目标，也是
#    上一版 rag_test_v2.py 检测parent_text字段、但一直取不到值的原因。
# 2. 同方案内相邻子块记录 prev_chunk_id/next_chunk_id，供检索端做
#    比"整段父块"更轻量的上下文扩展（比如只想多拿前后各一句）。
#
# [高优先级]
# 3. ChromaDB集合创建时显式指定 hnsw:space="cosine"，不再依赖默认的
#    L2度量——上一轮审计发现的"score=1-distance"公式只在cosine下
#    成立的问题，这次从源头上解决，不用在检索端再做探测和警告。
# 4. chunk ID加入内容哈希，重新索引且切分参数变化时不会用旧ID静默
#    覆盖成不同内容；写入操作从add()改成upsert()，配合内容哈希天然
#    支持增量重跑去重。
# 5. 新增 edition 字段追踪（从front matter的edition/version/底本等
#    键尝试提取），--stats 会报告缺失版本信息的记录占比，方便你评估
#    版本一致性问题的严重程度。
# 6. run_indexing 去掉了"先切一遍统计、再切一遍写入"的重复计算，
#    现在只处理一遍文件。
#
# [中优先级]
# 7. 新增可选的繁简体归一化(--normalize-variants，默认关闭，需要
#    opencc-python-reimplemented)。
# 8. split_into_parent_units() 增加了"疑似未正确分段"的健全性检查，
#    如果发现一个段落异常长且没有\\n\\n分隔，会打日志警告而不是
#    默默硬切，提示你去核实源文件排版格式。
# 9. SemanticChunker/PrecisionChunker 原来几乎重复的_chunk_large_para
#    实现合并成一个通用的SubChunker类，用strict_boundary参数区分两种
#    行为，减少后续维护时两处改一处漏改的风险。
#
# [未处理，留给你按需迭代]
# - 卷/篇/条这类文献结构层面的切分感知，现在还是只到段落粒度。
# - 段落切分强依赖\\n\\n，如果源文件排版不是这个格式，父块划分会
#   退化，运行时会看到警告日志，需要你根据实际情况决定是否要为
#   殆知阁语料写一个专门的段落边界识别规则。