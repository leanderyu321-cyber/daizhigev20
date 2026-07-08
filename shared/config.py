"""
全局配置 —— 所有子系统（语料库工程 + Deep Search）共享

通过环境变量覆盖，或直接修改此文件的默认值。
"""
import os
from pathlib import Path
from typing import Optional


class ESConfig:
    """Elasticsearch 配置"""
    HOST = os.getenv("ES_HOST", "localhost")
    PORT = int(os.getenv("ES_PORT", "9200"))
    TIMEOUT = int(os.getenv("ES_TIMEOUT", "30"))
    
    @property
    def URL(self) -> str:
        return f"http://{self.HOST}:{self.PORT}"
    
    # 重试配置
    RETRY_MAX_ATTEMPTS = int(os.getenv("ES_RETRY_MAX_ATTEMPTS", "5"))
    RETRY_INITIAL_WAIT = float(os.getenv("ES_RETRY_INITIAL_WAIT", "1.0"))  # 秒
    RETRY_MAX_WAIT = float(os.getenv("ES_RETRY_MAX_WAIT", "30.0"))  # 秒


class QdrantConfig:
    """Qdrant 配置"""
    HOST = os.getenv("QDRANT_HOST", "localhost")
    PORT = int(os.getenv("QDRANT_PORT", "6333"))
    API_KEY = os.getenv("QDRANT_API_KEY", None)
    TIMEOUT = int(os.getenv("QDRANT_TIMEOUT", "30"))
    
    @property
    def URL(self) -> str:
        return f"http://{self.HOST}:{self.PORT}"
    
    # 重试配置
    RETRY_MAX_ATTEMPTS = int(os.getenv("QDRANT_RETRY_MAX_ATTEMPTS", "5"))
    RETRY_INITIAL_WAIT = float(os.getenv("QDRANT_RETRY_INITIAL_WAIT", "1.0"))


class RedisConfig:
    """Redis 配置 —— 用于任务队列和断点续跑状态存储"""
    HOST = os.getenv("REDIS_HOST", "localhost")
    PORT = int(os.getenv("REDIS_PORT", "6379"))
    DB = int(os.getenv("REDIS_DB", "0"))
    PASSWORD = os.getenv("REDIS_PASSWORD", None)
    TIMEOUT = int(os.getenv("REDIS_TIMEOUT", "10"))


class CorpusPipelineConfig:
    """语料库处理管道配置"""
    
    # 分块参数
    CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "300"))  # 单个chunk的字符数目标
    CHUNK_OVERLAP_RATIO = float(os.getenv("CHUNK_OVERLAP_RATIO", "0.2"))  # 20%重叠
    
    # 古文模型配置
    GUWEN_PUNCTUATION_MODEL = os.getenv(
        "GUWEN_PUNCTUATION_MODEL",
        "GuwenBERT/guwen-punc"  # 古文标点模型
    )
    GUWEN_NER_MODEL = os.getenv(
        "GUWEN_NER_MODEL",
        "GuwenBERT/guwen-ner"  # 古文NER模型
    )
    CLASSICAL_TRANSLATOR_MODEL = os.getenv(
        "CLASSICAL_TRANSLATOR_MODEL",
        "Xunzi-LLM-of-Chinese-classics/XunziChat"  # 古文翻译模型
    )
    BGE_M3_EMBEDDING_MODEL = os.getenv(
        "BGE_M3_EMBEDDING_MODEL",
        "BAAI/bge-m3"  # Embedding模型
    )
    
    # Embedding 生成配置
    EMBEDDING_BATCH_SIZE = int(os.getenv("EMBEDDING_BATCH_SIZE", "32"))
    EMBEDDING_GPU_ID = os.getenv("EMBEDDING_GPU_ID", "0")  # 使用的GPU ID，为空表示CPU
    
    # 文本清洗配置
    ENABLE_SIMPLIFIED_CONVERSION = os.getenv("ENABLE_SIMPLIFIED_CONVERSION", "false").lower() == "true"
    
    # 去重配置
    DEDUP_SIMHASH_DISTANCE_THRESHOLD = int(os.getenv("DEDUP_SIMHASH_DISTANCE_THRESHOLD", "5"))
    
    # Jieba分词配置
    JIEBA_USER_DICT_PATH = os.getenv(
        "JIEBA_USER_DICT_PATH",
        str(Path(__file__).parent.parent / "corpus_pipeline" / "term_dict.txt")
    )
    
    # 处理并发配置
    MAX_WORKERS = int(os.getenv("MAX_WORKERS", "4"))


class DeepSearchConfig:
    """Deep Search 引擎配置"""
    
    # LLM 配置
    LLM_BACKEND = os.getenv("LLM_BACKEND", "local")  # local 或 api
    LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct")
    LLM_LOCAL_ENDPOINT = os.getenv("LLM_LOCAL_ENDPOINT", "http://localhost:8000/v1")
    LLM_API_KEY = os.getenv("LLM_API_KEY", None)
    LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "120"))
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    LLM_TOP_P = float(os.getenv("LLM_TOP_P", "0.9"))
    
    # 上下文窗口配置
    MAX_CONTEXT_WINDOW = int(os.getenv("MAX_CONTEXT_WINDOW", "8192"))
    ROLLING_SUMMARY_TARGET_LENGTH = int(os.getenv("ROLLING_SUMMARY_TARGET_LENGTH", "500"))
    
    # 搜索循环配置
    MAX_ROUNDS = int(os.getenv("MAX_ROUNDS", "15"))
    MAX_TIMEOUT_SECONDS = int(os.getenv("MAX_TIMEOUT_SECONDS", "1800"))  # 30分钟
    FACTS_PER_BATCH = int(os.getenv("FACTS_PER_BATCH", "15"))  # FACTCHECKER和WRITER每批处理的事实卡片数
    
    # 搜索参数
    RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "10"))  # 每次检索返回的top-k
    HYBRID_SEARCH_ALPHA = float(os.getenv("HYBRID_SEARCH_ALPHA", "0.5"))  # RRF融合权重
    
    # 并发配置
    CONCURRENT_QUERIES = int(os.getenv("CONCURRENT_QUERIES", "3"))


class PathConfig:
    """路径配置"""
    PROJECT_ROOT = Path(__file__).parent.parent
    
    CORPUS_DIR = PROJECT_ROOT / "corpus_pipeline"
    DEEPSEARCH_DIR = PROJECT_ROOT / "deepsearch_engine"
    SHARED_DIR = PROJECT_ROOT / "shared"
    
    # 语料来源目录
    CORPUS_SOURCES = [
        PROJECT_ROOT / "史藏",
        PROJECT_ROOT / "诗藏",
        PROJECT_ROOT / "子藏",
        PROJECT_ROOT / "艺藏",
        PROJECT_ROOT / "佛藏",
        PROJECT_ROOT / "儒藏",
        PROJECT_ROOT / "易藏",
        PROJECT_ROOT / "道藏",
        PROJECT_ROOT / "医藏",
        PROJECT_ROOT / "集藏",
    ]
    
    # 输出目录
    OUTPUT_DIR = PROJECT_ROOT / "output"
    REPORTS_DIR = OUTPUT_DIR / "reports"  # 最终报告
    LOGS_DIR = OUTPUT_DIR / "logs"  # 搜索过程日志
    CHECKPOINTS_DIR = OUTPUT_DIR / "checkpoints"  # 断点续跑快照
    
    @classmethod
    def ensure_dirs(cls):
        """确保所有输出目录存在"""
        cls.OUTPUT_DIR.mkdir(exist_ok=True)
        cls.REPORTS_DIR.mkdir(exist_ok=True)
        cls.LOGS_DIR.mkdir(exist_ok=True)
        cls.CHECKPOINTS_DIR.mkdir(exist_ok=True)


class LoggingConfig:
    """日志配置"""
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FORMAT = "[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s"
    TRACE_LOG_FORMAT = "%(message)s"  # trace_logger使用JSON Lines格式
    
    # 标准日志文件
    STANDARD_LOG_FILE = PathConfig.LOGS_DIR / "system.log"
    
    # Trace日志（搜索过程）
    TRACE_LOG_FILE = PathConfig.LOGS_DIR / "search_trace.jsonl"


# ============ 便利函数 ============

def get_es_config() -> ESConfig:
    """获取Elasticsearch配置实例"""
    return ESConfig()


def get_qdrant_config() -> QdrantConfig:
    """获取Qdrant配置实例"""
    return QdrantConfig()


def get_redis_config() -> RedisConfig:
    """获取Redis配置实例"""
    return RedisConfig()


def get_corpus_pipeline_config() -> CorpusPipelineConfig:
    """获取语料库处理配置实例"""
    return CorpusPipelineConfig()


def get_deepsearch_config() -> DeepSearchConfig:
    """获取Deep Search配置实例"""
    return DeepSearchConfig()


def get_path_config() -> PathConfig:
    """获取路径配置实例"""
    PathConfig.ensure_dirs()
    return PathConfig()
