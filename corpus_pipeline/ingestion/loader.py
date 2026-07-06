"""
文本加载模块 —— 从各种格式（txt/md/已OCR结果）加载原始文本
"""
import logging
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


class CorpusLoader:
    """语料库文本加载器"""
    
    def load_text(self, file_path: Path) -> str:
        """
        加载文本文件
        
        Args:
            file_path: 文件路径
        
        Returns:
            原始文本
        
        Raises:
            FileNotFoundError: 文件不存在
            UnicodeDecodeError: 编码错误
        """
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 尝试多种编码
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "big5"]
        
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.read()
                logger.debug(f"成功加载文件 (编码: {encoding}): {file_path}")
                return content
            except UnicodeDecodeError:
                continue
        
        raise UnicodeDecodeError(
            "unknown", b"", 0, 1,
            f"无法使用任何已知编码打开文件: {file_path}"
        )
