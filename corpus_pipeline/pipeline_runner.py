"""
语料库处理管道主入口 —— 阶段一的核心实现

职责：
- 编排所有处理步骤（清洗→断句→分块→翻译→NER→索引）
- 支持断点续跑
- 记录进度，处理失败恢复
"""
import logging
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from dataclasses import asdict

from shared.schema import CorpusChunk, CorpusPipelineProgress, ProcessingStatus, ESFields, QdrantFields
from shared.config import get_corpus_pipeline_config, get_path_config
import sys
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from corpus_pipeline.ingestion.loader import CorpusLoader
from corpus_pipeline.preprocessing.cleaner import TextCleaner
from corpus_pipeline.preprocessing.punctuator import ClassicalPunctuator
from corpus_pipeline.chunking.chunker import TextChunker
from corpus_pipeline.translation.classical_translator import ClassicalTranslator
from corpus_pipeline.enrichment.ner_extractor import NERExtractor
from corpus_pipeline.indexing.es_indexer import ESIndexer
from corpus_pipeline.indexing.vector_indexer import VectorIndexer
from corpus_pipeline.state_manager import StateManager


logger = logging.getLogger(__name__)


class CorpusPipeline:
    """语料库处理管道编排器"""
    
    def __init__(self):
        self.config = get_corpus_pipeline_config()
        self.path_config = get_path_config()
        
        # 初始化各处理模块
        self.loader = CorpusLoader()
        self.cleaner = TextCleaner()
        self.punctuator = ClassicalPunctuator()
        self.chunker = TextChunker(
            chunk_size=self.config.CHUNK_SIZE,
            overlap_ratio=self.config.CHUNK_OVERLAP_RATIO,
        )
        self.translator = ClassicalTranslator()
        self.ner_extractor = NERExtractor()
        self.es_indexer = ESIndexer()
        self.vector_indexer = VectorIndexer()
        
        # 状态管理
        self.state_manager = StateManager()
    
    def process_file(self, file_path: Path, book_name: str, chapter_name: str, dynasty: str) -> int:
        """
        处理单个文件
        
        Args:
            file_path: 原始文件路径
            book_name: 出处书名
            chapter_name: 章节名
            dynasty: 朝代
        
        Returns:
            处理的chunk总数
        """
        logger.info(f"开始处理文件: {file_path} ({book_name}·{chapter_name})")
        
        # 计算源文件哈希值
        source_hash = self._compute_file_hash(file_path)
        task_id = f"{book_name}_{chapter_name}_{source_hash[:8]}"
        
        # 检查之前是否处理过此文件
        progress = self.state_manager.load_progress(task_id)
        if progress and progress.status == ProcessingStatus.DONE.value:
            logger.info(f"文件已处理过，跳过: {task_id}")
            return 0
        
        try:
            # 标记为处理中
            self.state_manager.save_progress(CorpusPipelineProgress(
                task_id=task_id,
                source_file_hash=source_hash,
                status=ProcessingStatus.IN_PROGRESS.value,
                timestamp=datetime.now().isoformat(),
            ))
            
            # 1. 加载原始文本
            logger.debug(f"加载文本...")
            raw_text = self.loader.load_text(file_path)
            
            # 2. 文本清洗
            logger.debug(f"清洗文本...")
            cleaned_text = self.cleaner.clean(raw_text)
            
            # 3. 古文断句/标点
            logger.debug(f"古文断句...")
            punctuated_text = self.punctuator.punctuate(cleaned_text)
            
            # 4. 文本分块
            logger.debug(f"文本分块...")
            sentence_chunks = self.chunker.chunk(punctuated_text)
            
            # 5. 逐chunk处理：翻译 + NER + 索引
            processed_count = 0
            chunks_to_index = []
            
            for chunk_index, chunk_text in enumerate(sentence_chunks):
                try:
                    # 翻译
                    logger.debug(f"翻译chunk {chunk_index}...")
                    translation_result = self.translator.translate(chunk_text)
                    
                    # NER抽取
                    logger.debug(f"NER抽取chunk {chunk_index}...")
                    entities = self.ner_extractor.extract(
                        original_text=chunk_text,
                        translated_text=translation_result.get("translation", ""),
                    )
                    
                    # 构建CorpusChunk
                    line_id = f"{book_name}_{chapter_name}_{chunk_index}"
                    corpus_chunk = CorpusChunk(
                        line_id=line_id,
                        content=chunk_text,
                        content_translation=translation_result.get("translation", ""),
                        book=book_name,
                        chapter=chapter_name,
                        dynasty=dynasty,
                        chunk_index=chunk_index,
                        entities=entities,
                        source_hash=source_hash,
                        translation_status=translation_result.get("status", "good"),
                    )
                    
                    chunks_to_index.append(corpus_chunk)
                    processed_count += 1
                    
                    # 定期索引（每100条提交一次，避免一次堆积过多）
                    if len(chunks_to_index) >= 100:
                        logger.info(f"批量索引{len(chunks_to_index)}条chunk...")
                        self._index_chunks(chunks_to_index)
                        chunks_to_index = []
                    
                except Exception as e:
                    logger.error(f"处理chunk {chunk_index}失败: {e}", exc_info=True)
                    # 记录错误但继续处理下一个chunk
                    continue
            
            # 最后一批提交
            if chunks_to_index:
                logger.info(f"批量索引最后{len(chunks_to_index)}条chunk...")
                self._index_chunks(chunks_to_index)
            
            # 标记为完成
            self.state_manager.save_progress(CorpusPipelineProgress(
                task_id=task_id,
                source_file_hash=source_hash,
                status=ProcessingStatus.DONE.value,
                timestamp=datetime.now().isoformat(),
            ))
            
            logger.info(f"文件处理完成: {file_path}, 共处理{processed_count}个chunk")
            return processed_count
            
        except Exception as e:
            logger.error(f"处理文件失败: {file_path}, 错误: {e}", exc_info=True)
            # 标记为失败
            self.state_manager.save_progress(CorpusPipelineProgress(
                task_id=task_id,
                source_file_hash=source_hash,
                status=ProcessingStatus.FAILED.value,
                error_reason=str(e),
                timestamp=datetime.now().isoformat(),
            ))
            raise
    
    def process_corpus_directory(self, corpus_root: Path) -> Dict[str, int]:
        """
        处理整个语料库目录（例如 "史藏" 目录）
        
        Args:
            corpus_root: 语料库根目录
        
        Returns:
            {"file_path": chunk_count, ...}
        """
        results = {}
        
        logger.info(f"开始处理语料库目录: {corpus_root}")
        
        # 递归查找所有.md文件
        for md_file in corpus_root.rglob("*.md"):
            # 从文件路径推断书名、章节名
            relative_path = md_file.relative_to(corpus_root)
            path_parts = relative_path.parts
            
            if len(path_parts) >= 2:
                book_name = path_parts[0]
                chapter_name = md_file.stem
            else:
                book_name = corpus_root.name
                chapter_name = md_file.stem
            
            # 推断朝代（可根据具体项目调整逻辑）
            dynasty = self._infer_dynasty(book_name, chapter_name)
            
            try:
                count = self.process_file(
                    file_path=md_file,
                    book_name=book_name,
                    chapter_name=chapter_name,
                    dynasty=dynasty,
                )
                results[str(md_file)] = count
            except Exception as e:
                logger.error(f"处理文件失败: {md_file}, 错误: {e}")
                results[str(md_file)] = 0
        
        logger.info(f"语料库目录处理完成: {corpus_root}")
        return results
    
    def _index_chunks(self, chunks: List[CorpusChunk]) -> None:
        """
        批量索引chunks到ES和Qdrant
        
        Args:
            chunks: 待索引的chunks列表
        """
        if not chunks:
            return
        
        try:
            # 索引到ES
            logger.debug(f"索引{len(chunks)}条到Elasticsearch...")
            self.es_indexer.index_chunks(chunks)
            
            # 生成embedding并索引到Qdrant
            logger.debug(f"生成embedding并索引{len(chunks)}条到Qdrant...")
            self.vector_indexer.index_chunks(chunks)
            
        except Exception as e:
            logger.error(f"索引失败: {e}", exc_info=True)
            raise
    
    @staticmethod
    def _compute_file_hash(file_path: Path) -> str:
        """计算文件哈希值（去重用）"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    
    @staticmethod
    def _infer_dynasty(book_name: str, chapter_name: str) -> str:
        """
        从书名推断朝代
        
        这是一个简化版本，实际项目中应该维护一个详细的书籍元数据库
        """
        # 简单的启发式规则
        dynasty_keywords = {
            "唐": "唐代",
            "宋": "宋代",
            "元": "元代",
            "明": "明代",
            "清": "清代",
            "汉": "汉代",
            "晋": "晋代",
            "南北": "南北朝",
            "三国": "三国",
        }
        
        combined_text = f"{book_name}_{chapter_name}".lower()
        for keyword, dynasty in dynasty_keywords.items():
            if keyword in combined_text:
                return dynasty
        
        return "未知"


def main():
    """CLI入口示例"""
    import sys
    
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s",
    )
    
    pipeline = CorpusPipeline()
    path_config = get_path_config()
    
    # 处理所有语料库来源
    total_chunks = 0
    for corpus_source in path_config.CORPUS_SOURCES:
        if corpus_source.exists():
            results = pipeline.process_corpus_directory(corpus_source)
            for file_path, count in results.items():
                total_chunks += count
                logger.info(f"  {file_path}: {count}个chunk")
    
    logger.info(f"全部处理完成，总共处理{total_chunks}个chunk")


if __name__ == "__main__":
    main()
