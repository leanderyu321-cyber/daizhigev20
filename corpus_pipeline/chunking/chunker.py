"""
文本分块模块 —— 语义/段落边界 + 重叠
"""
import logging
import re
from typing import List


logger = logging.getLogger(__name__)


class TextChunker:
    """文本分块器"""
    
    def __init__(self, chunk_size: int = 300, overlap_ratio: float = 0.2):
        """
        初始化分块器
        
        Args:
            chunk_size: 单个chunk的字符数目标
            overlap_ratio: 重叠比例（0-1）
        """
        self.chunk_size = chunk_size
        self.overlap_ratio = overlap_ratio
        self.overlap_size = max(1, int(chunk_size * overlap_ratio))
    
    def chunk(self, text: str) -> List[str]:
        """
        对文本进行分块
        
        策略：
        1. 优先按自然段落（双换行）分块
        2. 超大段落再进行字符级别的切分
        3. 添加适当的重叠以保留上下文
        
        Args:
            text: 输入文本
        
        Returns:
            分块列表
        """
        if not text:
            return []
        
        chunks = []
        
        # Step 1: 按自然段落分块
        paragraphs = text.split('\n\n')
        
        for para in paragraphs:
            if not para.strip():
                continue
            
            # 如果单个段落较小，直接添加
            if len(para) <= self.chunk_size:
                chunks.append(para)
            else:
                # 否则需要进行字符级别分块
                para_chunks = self._chunk_paragraph(para)
                chunks.extend(para_chunks)
        
        logger.info(f"文本分块完成：总共{len(chunks)}个chunk")
        return chunks
    
    def _chunk_paragraph(self, para: str) -> List[str]:
        """
        对单个段落进行字符级别的分块
        
        Args:
            para: 段落文本
        
        Returns:
            分块列表
        """
        chunks = []
        pos = 0
        
        while pos < len(para):
            # 取chunk_size大小的文本
            chunk_end = min(pos + self.chunk_size, len(para))
            
            # 尝试在句号/分号等处断开，而不是生硬地从中间断
            potential_end = chunk_end
            for i in range(chunk_end, max(pos + self.chunk_size // 2, pos), -1):
                if i < len(para) and para[i] in '。！？；，、':
                    potential_end = i + 1
                    break
            
            chunk_text = para[pos:potential_end].strip()
            if chunk_text:
                chunks.append(chunk_text)
            
            # 计算下一个chunk的起始位置，添加重叠
            pos = max(pos + 1, potential_end - self.overlap_size)
        
        return chunks
