"""
实体抽取模块 —— 人物/地点/朝代/官职

使用古文专用BERT模型（GuwenBERT/SikuBERT等）
"""
import logging
from typing import Optional

from shared.schema import EntityInfo


logger = logging.getLogger(__name__)


class NERExtractor:
    """命名实体识别提取器"""
    
    def __init__(self, model_name: str = "GuwenBERT/guwen-ner"):
        """
        初始化NER模型
        
        Args:
            model_name: 古文NER模型名称
        
        Note:
            当前实现为占位符。生产环境应集成真实的GuwenBERT NER模型。
        """
        self.model_name = model_name
        logger.info(f"初始化古文NER提取器: {model_name}")
    
    def extract(self, original_text: str, translated_text: Optional[str] = None) -> EntityInfo:
        """
        从文本中抽取命名实体
        
        Args:
            original_text: 原始古文
            translated_text: 翻译后的现代文（可选，用于辅助理解）
        
        Returns:
            EntityInfo对象
        
        Note:
            当前实现为占位符，返回空的EntityInfo。
            生产环境应调用真实的NER模型。
        """
        try:
            # TODO: 集成真实的GuwenBERT NER模型
            # 这里是占位符实现，生产环境需要：
            # 1. 加载预训练的GuwenBERT NER模型
            # 2. 对原文进行序列标注
            # 3. 解析标注结果，提取实体
            # 4. 返回EntityInfo对象
            
            # 暂时返回空的EntityInfo
            logger.debug(f"NER抽取完成 (占位符实现): {original_text[:50]}...")
            return EntityInfo(
                persons=[],
                places=[],
                events=[],
                offices=[],
            )
            
        except Exception as e:
            logger.error(f"NER抽取失败: {e}", exc_info=True)
            return EntityInfo()  # 返回空EntityInfo，不中断处理流程
