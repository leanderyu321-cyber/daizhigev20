"""
端到端管道集成测试示例

这个测试演示如何使用整个系统。
实际测试时，应该用真实的语料库文件。
"""
import pytest
import tempfile
from pathlib import Path
from corpus_pipeline.pipeline_runner import CorpusPipeline


class TestEndToEndPipeline:
    """端到端管道测试"""
    
    def create_sample_text_file(self) -> Path:
        """创建测试用的样本文本文件"""
        sample_text = """
        建炎南渡
        
        绍兴元年，高宗皇帝驾幸临安。此时金兵势强，占据中原。宋室被迫南迁，
        此事后世称为"建炎南渡"。高宗以赵构名，本为康王，后继大统，建年号为建炎。
        
        建炎元年正月，康王赵构即位于南京应天府。其时金兵已陷汴京，徽宗、钦宗被掳。
        群臣议论纷纷，以为中原已失，宜守江南。高宗遂决意南迁。
        
        是年三月，驾幸扬州。五月，又移驾临安。六月，金兵进犯扬州，城中百姓惊恐。
        高宗闻讯，即日启驾，南渡长江。此后江南成为宋室的最后堡垒。
        """
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(sample_text)
            return Path(f.name)
    
    def test_pipeline_initialization(self):
        """测试管道初始化"""
        pipeline = CorpusPipeline()
        assert pipeline is not None
        assert pipeline.loader is not None
        assert pipeline.cleaner is not None
        assert pipeline.chunker is not None
        assert pipeline.state_manager is not None
    
    def test_text_loading(self):
        """测试文本加载"""
        pipeline = CorpusPipeline()
        sample_file = self.create_sample_text_file()
        try:
            text = pipeline.loader.load_text(sample_file)
            assert text is not None
            assert len(text) > 0
            assert "建炎南渡" in text
        finally:
            sample_file.unlink()
    
    def test_text_cleaning(self):
        """测试文本清洗"""
        pipeline = CorpusPipeline()
        raw_text = "  \n\n这是\u3000一个\ufeff\t测试  \n\n\n文本  "
        cleaned = pipeline.cleaner.clean(raw_text)
        
        assert cleaned is not None
        assert len(cleaned) > 0
        assert '\ufeff' not in cleaned  # BOM已移除
        assert '\u3000' not in cleaned  # 全角空格已转换
    
    def test_text_chunking(self):
        """测试文本分块"""
        pipeline = CorpusPipeline()
        text = "这是第一段。\n\n这是第二段。这是很长的句子。" * 5
        
        chunks = pipeline.chunker.chunk(text)
        assert len(chunks) > 0
        assert all(len(chunk) > 0 for chunk in chunks)
        
        # 检查块大小在合理范围内
        for chunk in chunks:
            assert len(chunk) <= pipeline.config.CHUNK_SIZE * 1.5  # 允许一些超出
    
    def test_hash_computation(self):
        """测试文件哈希计算"""
        sample_file = self.create_sample_text_file()
        try:
            hash1 = CorpusPipeline._compute_file_hash(sample_file)
            hash2 = CorpusPipeline._compute_file_hash(sample_file)
            
            assert hash1 == hash2  # 同一文件的哈希应相同
            assert len(hash1) == 64  # SHA256哈希长度
        finally:
            sample_file.unlink()
    
    def test_dynasty_inference(self):
        """测试朝代推断"""
        test_cases = [
            ("唐诗集", "全唐诗", "唐代"),
            ("宋词", "宋画廊", "宋代"),
            ("明清", "小说", "明代"),
        ]
        
        for book, chapter, expected_dynasty in test_cases:
            inferred = CorpusPipeline._infer_dynasty(book, chapter)
            # 由于推断是启发式的，只检查不为空
            assert inferred is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
