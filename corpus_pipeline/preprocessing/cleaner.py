"""
文本清洗模块 —— 处理繁简转换、异体字映射、特殊符号处理
"""
import re
import logging
from typing import Optional


logger = logging.getLogger(__name__)


class TextCleaner:
    """文本清洗器"""
    
    # 常见特殊符号映射
    SPECIAL_SYMBOLS_CLEAN = {
        '\u3000': ' ',  # 全角空格 -> 半角空格
        '\ufeff': '',   # BOM标记
        '\r': '\n',     # Windows换行符统一
    }
    
    def clean(self, text: str) -> str:
        """
        清洗文本
        
        Args:
            text: 原始文本
        
        Returns:
            清洗后的文本
        """
        if not text:
            return ""
        
        # 1. 移除特殊控制字符和BOM
        text = self._remove_special_chars(text)
        
        # 2. 标准化换行符
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        
        # 3. 移除多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        # 4. 移除行首尾空白
        lines = text.split('\n')
        lines = [line.strip() for line in lines]
        text = '\n'.join(lines)
        
        # 5. 移除完全空行
        text = '\n'.join(line for line in text.split('\n') if line)
        
        logger.debug(f"文本清洗完成，原文长度{len(text)}")
        return text
    
    def _remove_special_chars(self, text: str) -> str:
        """移除特殊控制字符"""
        for char, replacement in self.SPECIAL_SYMBOLS_CLEAN.items():
            text = text.replace(char, replacement)
        
        # 移除其他控制字符（0x00-0x1F，除了\t\n）
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\t\n')
        
        return text
