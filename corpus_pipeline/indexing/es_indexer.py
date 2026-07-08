"""
Elasticsearch索引模块 —— 写入jieba分词+bigram索引
"""
import logging
import time
from typing import List
import jieba

from shared.schema import CorpusChunk, ESFields
from shared.config import get_es_config


logger = logging.getLogger(__name__)


class ESIndexer:
    """Elasticsearch索引写入器"""
    
    def __init__(self):
        self.config = get_es_config()
        # 初始化Elasticsearch连接
        # TODO: 实现真实的ES连接和客户端
        logger.info(f"初始化Elasticsearch索引器: {self.config.URL}")
    
    def index_chunks(self, chunks: List[CorpusChunk], batch_size: int = 100) -> int:
        """
        批量索引chunks
        
        Args:
            chunks: CorpusChunk列表
            batch_size: 每批提交的大小
        
        Returns:
            成功索引的数量
        
        Note:
            当前实现为占位符。生产环境应集成真实的Elasticsearch客户端。
        """
        if not chunks:
            return 0
        
        try:
            # TODO: 集成真实的elasticsearch-py客户端
            # 这里是占位符实现，生产环境需要：
            # 1. 连接到Elasticsearch服务
            # 2. 为每个chunk：
            #    a. 对content_jieba字段进行jieba分词
            #    b. 对content_bigram字段生成双字符ngram
            #    c. 调用bulk API批量索引
            # 3. 处理索引失败并重试
            
            success_count = 0
            
            for chunk in chunks:
                # 对原文进行jieba分词
                jieba_tokens = list(jieba.cut(chunk.content))
                jieba_text = ' '.join(jieba_tokens)
                
                # 生成bigram
                bigram_tokens = []
                for i in range(len(chunk.content) - 1):
                    bigram_tokens.append(chunk.content[i:i+2])
                bigram_text = ' '.join(bigram_tokens)
                
                # 构建ES文档
                doc = chunk.to_es_doc()
                doc[ESFields.CONTENT_JIEBA] = jieba_text
                doc[ESFields.CONTENT_BIGRAM] = bigram_text
                
                # TODO: 调用ES bulk API写入
                # 这里暂时只记录日志
                success_count += 1
            
            logger.info(f"索引{success_count}条chunks到Elasticsearch（占位符）")
            return success_count
            
        except Exception as e:
            logger.error(f"ES索引失败: {e}", exc_info=True)
            raise
    
    def _retry_with_backoff(self, operation, max_attempts: int = 5):
        """
        带指数退避的重试逻辑
        
        Args:
            operation: 可调用对象
            max_attempts: 最大重试次数
        
        Returns:
            操作结果
        
        Raises:
            Exception: 重试全部失败后的异常
        """
        for attempt in range(max_attempts):
            try:
                return operation()
            except Exception as e:
                if attempt == max_attempts - 1:
                    raise
                wait_time = self.config.RETRY_INITIAL_WAIT * (2 ** attempt)
                wait_time = min(wait_time, self.config.RETRY_MAX_WAIT)
                logger.warning(f"操作失败 (第{attempt+1}次), 等待{wait_time}秒后重试: {e}")
                time.sleep(wait_time)
