#!/usr/bin/env python3
"""
搜索模式对比演示
展示 best/phrase/fuzzy 三种模式的区别
"""

import requests
import json
from urllib.parse import quote

API_BASE = "http://localhost:8000"

def test_search(keyword, modes=["best", "phrase", "fuzzy"], size=5):
    """测试不同搜索模式"""
    print(f"\n{'='*70}")
    print(f"🔍 搜索关键词: '{keyword}'")
    print(f"{'='*70}\n")
    
    for mode in modes:
        try:
            url = f"{API_BASE}/search?q={quote(keyword)}&mode={mode}&size={size}"
            response = requests.get(url)
            data = response.json()
            
            total = data.get('total', 0)
            took = data.get('took_ms', 0)
            results = data.get('results', [])
            
            # 模式说明
            mode_desc = {
                'best': '最佳匹配（优先短语，备选单词）',
                'phrase': '精确短语匹配',
                'fuzzy': '模糊匹配（容错）'
            }
            
            print(f"📌 模式: {mode.upper()} - {mode_desc.get(mode, '')}")
            print(f"   找到 {total} 个结果 | 耗时 {took}ms")
            print()
            
            if results:
                for i, item in enumerate(results, 1):
                    print(f"   {i}. 📄 {item['file_name']}")
                    print(f"      标题: {item['title']}")
                    print(f"      相关度: {item['score']:.2f}")
                    
                    # 显示高亮
                    if 'title_highlight' in item:
                        print(f"      标题匹配: {item['title_highlight']}")
                    if 'content_highlights' in item and item['content_highlights']:
                        print(f"      内容片段: {item['content_highlights'][0][:100]}...")
                    print()
            else:
                print(f"   ❌ 未找到结果\n")
                
        except Exception as e:
            print(f"   ⚠️  错误: {str(e)}\n")

if __name__ == "__main__":
    # 测试用例
    test_cases = [
        "诸葛亮",      # 中文人名
        "Docker",      # 英文词
        "Python",      # 英文词
        "红楼梦",      # 中文书名
        "知识库",      # 中文短语
    ]
    
    for keyword in test_cases:
        test_search(keyword, modes=["best", "phrase"])
    
    print("\n" + "="*70)
    print("✅ 测试完成！")
    print("="*70)
    print("""
📚 使用建议：
- 中文短语（人名、地名）：使用 phrase 模式
- 英文单词：使用 best 模式（默认）
- 有输入错误：使用 fuzzy 模式
- 通用搜索：使用 best 模式（默认）
    """)
