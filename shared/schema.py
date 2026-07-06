"""
共享数据契约定义 —— 两个子系统（语料库工程 + Deep Search 引擎）唯一的耦合点

所有跨模块的字段名必须从这里导入，禁止硬编码字符串。
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum
import json


class ProcessingStatus(str, Enum):
    """处理状态枚举"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"


class TranslationStatus(str, Enum):
    """翻译质量状态"""
    GOOD = "good"  # 翻译质量可信
    UNCERTAIN = "uncertain"  # 翻译置信度较低，用户应参照原文
    FAILED = "failed"  # 翻译失败


# ============ Elasticsearch 字段定义 ============
class ESFields:
    """Elasticsearch 索引字段常量"""
    INDEX_NAME = "history_corpus"
    
    # 字段名常量
    LINE_ID = "line_id"  # 唯一标识 {book}_{chapter}_{chunk_index}
    CONTENT = "content"  # 原文（仅存储，不分词）
    CONTENT_TRANSLATION = "content_translation"  # 白话译文（供embedding和理解任务）
    CONTENT_JIEBA = "content_jieba"  # jieba分词结果
    CONTENT_BIGRAM = "content_bigram"  # bigram结果
    BOOK = "book"  # 出处书名
    CHAPTER = "chapter"  # 卷/章节
    DYNASTY = "dynasty"  # 朝代
    ENTITIES = "entities"  # 实体抽取结果
    CHUNK_INDEX = "chunk_index"  # 分块顺序
    SOURCE_HASH = "source_hash"  # 原始语料哈希值
    
    # 字段映射（用于动态访问）
    ALL_FIELDS = {
        LINE_ID, CONTENT, CONTENT_TRANSLATION, CONTENT_JIEBA, 
        CONTENT_BIGRAM, BOOK, CHAPTER, DYNASTY, ENTITIES, 
        CHUNK_INDEX, SOURCE_HASH
    }


# ============ Qdrant 字段定义 ============
class QdrantFields:
    """Qdrant 向量集合字段常量"""
    COLLECTION_NAME = "history_vectors"
    VECTOR_DIM = 1024  # bge-m3 默认维度
    DISTANCE_METRIC = "Cosine"
    
    # Payload 字段名常量
    LINE_ID = "line_id"
    BOOK = "book"
    CHAPTER = "chapter"
    DYNASTY = "dynasty"
    ENTITIES = "entities"
    CHUNK_INDEX = "chunk_index"
    
    # Payload 字段映射
    ALL_FIELDS = {LINE_ID, BOOK, CHAPTER, DYNASTY, ENTITIES, CHUNK_INDEX}


# ============ 核心数据结构定义 ============

@dataclass
class EntityInfo:
    """实体信息"""
    persons: List[str] = field(default_factory=list)  # 人物
    places: List[str] = field(default_factory=list)  # 地点
    events: List[str] = field(default_factory=list)  # 事件
    offices: List[str] = field(default_factory=list)  # 官职
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "persons": self.persons,
            "places": self.places,
            "events": self.events,
            "offices": self.offices,
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "EntityInfo":
        return EntityInfo(
            persons=data.get("persons", []),
            places=data.get("places", []),
            events=data.get("events", []),
            offices=data.get("offices", []),
        )


@dataclass
class CorpusChunk:
    """语料库分块 —— 被索引到ES和Qdrant的基本单位"""
    line_id: str  # {book}_{chapter}_{chunk_index}
    content: str  # 原文
    content_translation: str  # 白话译文
    book: str  # 出处书名
    chapter: str  # 卷/章节
    dynasty: str  # 朝代
    chunk_index: int  # 分块顺序
    entities: EntityInfo = field(default_factory=EntityInfo)  # 实体信息
    source_hash: str = ""  # 原始语料哈希（去重用）
    translation_status: str = TranslationStatus.GOOD.value  # 翻译质量标记
    
    def to_es_doc(self) -> Dict[str, Any]:
        """转换为Elasticsearch文档格式"""
        return {
            ESFields.LINE_ID: self.line_id,
            ESFields.CONTENT: self.content,
            ESFields.CONTENT_TRANSLATION: self.content_translation,
            ESFields.BOOK: self.book,
            ESFields.CHAPTER: self.chapter,
            ESFields.DYNASTY: self.dynasty,
            ESFields.CHUNK_INDEX: self.chunk_index,
            ESFields.ENTITIES: self.entities.to_dict(),
            ESFields.SOURCE_HASH: self.source_hash,
        }
    
    def to_qdrant_payload(self) -> Dict[str, Any]:
        """转换为Qdrant payload格式"""
        return {
            QdrantFields.LINE_ID: self.line_id,
            QdrantFields.BOOK: self.book,
            QdrantFields.CHAPTER: self.chapter,
            QdrantFields.DYNASTY: self.dynasty,
            QdrantFields.CHUNK_INDEX: self.chunk_index,
            QdrantFields.ENTITIES: self.entities.to_dict(),
        }


@dataclass
class FactCard:
    """结构化事实卡片 —— 用于减少上下文膨胀"""
    line_id: str  # 关联到ES/Qdrant中的原文
    summary: str  # 一句话概要
    event: Optional[str] = None  # 核心事件
    persons: List[str] = field(default_factory=list)  # 涉及人物
    time: Optional[str] = None  # 时间/年号
    dynasty: Optional[str] = None  # 朝代
    source: str = ""  # 出处（书名·卷·章节）
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "line_id": self.line_id,
            "summary": self.summary,
            "event": self.event,
            "persons": self.persons,
            "time": self.time,
            "dynasty": self.dynasty,
            "source": self.source,
        }
    
    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "FactCard":
        return FactCard(
            line_id=data.get("line_id", ""),
            summary=data.get("summary", ""),
            event=data.get("event"),
            persons=data.get("persons", []),
            time=data.get("time"),
            dynasty=data.get("dynasty"),
            source=data.get("source", ""),
        )


@dataclass
class CorpusPipelineProgress:
    """语料处理进度快照"""
    task_id: str  # 唯一任务ID
    source_file_hash: str  # 源文件哈希
    status: str = ProcessingStatus.PENDING.value  # 处理状态
    error_reason: Optional[str] = None  # 失败原因
    timestamp: str = ""  # 时间戳
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "source_file_hash": self.source_file_hash,
            "status": self.status,
            "error_reason": self.error_reason,
            "timestamp": self.timestamp,
        }


@dataclass
class DeepSearchTaskState:
    """Deep Search任务状态 —— 用于断点续跑"""
    task_id: str  # 唯一任务ID
    current_round: int = 0  # 当前轮次
    executed_queries: List[str] = field(default_factory=list)  # 已执行的子查询
    gathered_line_ids: List[str] = field(default_factory=list)  # 已获取的line_id集合
    timestamp: str = ""  # 最后更新时间
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "current_round": self.current_round,
            "executed_queries": self.executed_queries,
            "gathered_line_ids": self.gathered_line_ids,
            "timestamp": self.timestamp,
        }


@dataclass
class SearchTraceEvent:
    """搜索过程日志事件 —— 面向用户可读的trace"""
    timestamp: str
    round_num: int
    role: str  # PLANNER, RESEARCHER, ANALYST, COVERAGE_JUDGE, FACTCHECKER, WRITER
    event_type: str  # input, output, decision, error
    input_summary: Optional[str] = None
    output: Optional[str] = None
    reasoning: Optional[str] = None
    query: Optional[str] = None  # for RESEARCHER
    results_count: Optional[int] = None
    new_results_count: Optional[int] = None
    
    def to_json_line(self) -> str:
        """转换为JSON Lines格式"""
        data = {
            "timestamp": self.timestamp,
            "round": self.round_num,
            "role": self.role,
            "event_type": self.event_type,
        }
        if self.input_summary:
            data["input_summary"] = self.input_summary
        if self.output:
            data["output"] = self.output
        if self.reasoning:
            data["reasoning"] = self.reasoning
        if self.query:
            data["query"] = self.query
        if self.results_count is not None:
            data["results_count"] = self.results_count
        if self.new_results_count is not None:
            data["new_results_count"] = self.new_results_count
        return json.dumps(data, ensure_ascii=False)
    
    @staticmethod
    def from_json_line(line: str) -> "SearchTraceEvent":
        """从JSON Lines反序列化"""
        data = json.loads(line)
        return SearchTraceEvent(
            timestamp=data.get("timestamp", ""),
            round_num=data.get("round", 0),
            role=data.get("role", ""),
            event_type=data.get("event_type", ""),
            input_summary=data.get("input_summary"),
            output=data.get("output"),
            reasoning=data.get("reasoning"),
            query=data.get("query"),
            results_count=data.get("results_count"),
            new_results_count=data.get("new_results_count"),
        )
