#!/usr/bin/env python3
"""
索引 Markdown 文件到 Elasticsearch
用法: python index_markdown_to_es.py [--clear] [--limit 100]
"""

import os
import sys
import json
import argparse
from pathlib import Path
from elasticsearch import Elasticsearch
from datetime import datetime

# Elasticsearch 连接
es = Elasticsearch(["http://localhost:9200"])
INDEX_NAME = "markdown_docs"

def create_index_mapping():
    """创建索引并设置映射"""
    mapping = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    "default": {
                        "type": "standard",
                        "stopwords": "_english_"
                    },
                    "chinese_analyzer": {
                        "type": "standard"
                    }
                }
            }
        },
        "mappings": {
            "properties": {
                "file_path": {"type": "keyword"},
                "file_name": {"type": "keyword"},
                "title": {"type": "text", "analyzer": "standard"},
                "content": {"type": "text", "analyzer": "standard"},
                "content_preview": {"type": "text"},
                "file_size": {"type": "long"},
                "indexed_at": {"type": "date"},
                "word_count": {"type": "integer"},
            }
        }
    }
    
    if es.indices.exists(index=INDEX_NAME):
        print(f"索引 {INDEX_NAME} 已存在，跳过创建")
        return
    
    es.indices.create(index=INDEX_NAME, body=mapping)
    print(f"✓ 创建索引: {INDEX_NAME}")

def extract_title(content):
    """从内容中提取标题（第一个 # 标题）"""
    for line in content.split('\n'):
        line = line.strip()
        if line.startswith('#'):
            return line.lstrip('#').strip()
    return ""

def get_content_preview(content, max_length=500):
    """获取内容预览"""
    text = content.replace('\n', ' ').strip()
    if len(text) > max_length:
        return text[:max_length] + "..."
    return text

def index_markdown_file(file_path):
    """索引单个 Markdown 文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        file_size = os.path.getsize(file_path)
        word_count = len(content.split())
        title = extract_title(content)
        
        doc = {
            "file_path": str(file_path.relative_to(Path.cwd())),
            "file_name": file_path.name,
            "title": title or file_path.stem,
            "content": content,
            "content_preview": get_content_preview(content),
            "file_size": file_size,
            "word_count": word_count,
            "indexed_at": datetime.now().isoformat()
        }
        
        # 使用文件路径作为文档 ID
        doc_id = str(file_path.relative_to(Path.cwd())).replace('/', '_').replace('.md', '')
        
        es.index(index=INDEX_NAME, id=doc_id, document=doc)
        return True
    except Exception as e:
        print(f"✗ 错误 {file_path}: {str(e)}", file=sys.stderr)
        return False

def index_all_markdown_files(limit=None):
    """索引所有 Markdown 文件"""
    cwd = Path.cwd()
    md_files = list(cwd.rglob('*.md'))
    
    if limit:
        md_files = md_files[:limit]
    
    print(f"找到 {len(md_files)} 个 Markdown 文件")
    
    success_count = 0
    for i, file_path in enumerate(md_files, 1):
        if index_markdown_file(file_path):
            success_count += 1
        
        if i % 100 == 0:
            print(f"已处理: {i}/{len(md_files)}")
    
    print(f"\n✓ 成功索引: {success_count}/{len(md_files)} 个文件")

def clear_index():
    """清空索引"""
    if es.indices.exists(index=INDEX_NAME):
        es.indices.delete(index=INDEX_NAME)
        print(f"✓ 已删除索引: {INDEX_NAME}")

def search_content(query, size=10, mode="best"):
    """
    搜索内容
    
    mode: "best" (默认), "phrase" (精确短语), "fuzzy" (模糊匹配)
    """
    try:
        if mode == "phrase":
            # 短语搜索 - 精确匹配连续的词
            body = {
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase": {"title": {"query": query, "boost": 3}}},
                            {"match_phrase": {"content": {"query": query}}}
                        ]
                    }
                },
                "size": size
            }
        elif mode == "fuzzy":
            # 模糊搜索
            body = {
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["title^3", "content"],
                        "fuzziness": "AUTO"
                    }
                },
                "size": size
            }
        else:  # best (default)
            # 最佳匹配 - 结合短语和单词搜索
            body = {
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase": {"title": {"query": query, "boost": 5}}},
                            {"match_phrase": {"content": {"query": query, "boost": 2}}},
                            {"multi_match": {
                                "query": query,
                                "fields": ["title^2", "content"]
                            }}
                        ]
                    }
                },
                "size": size
            }
        
        results = es.search(index=INDEX_NAME, body=body)
        return results
    except Exception as e:
        print(f"搜索错误: {str(e)}")
        return None

def get_index_stats():
    """获取索引统计信息"""
    try:
        stats = es.indices.stats(index=INDEX_NAME)
        count = es.count(index=INDEX_NAME)
        
        print(f"\n📊 索引统计:")
        print(f"  文档数: {count['count']}")
        print(f"  索引大小: {stats['indices'][INDEX_NAME]['primaries']['store']['size_in_bytes'] / 1024 / 1024:.2f} MB")
    except Exception as e:
        print(f"统计错误: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="索引 Markdown 文件到 Elasticsearch")
    parser.add_argument("--clear", action="store_true", help="清空现有索引")
    parser.add_argument("--limit", type=int, help="限制索引文件数量")
    parser.add_argument("--search", type=str, help="搜索内容")
    parser.add_argument("--search-mode", type=str, default="best", 
                        choices=["best", "phrase", "fuzzy"],
                        help="搜索模式: best(默认), phrase(精确短语), fuzzy(模糊)")
    parser.add_argument("--stats", action="store_true", help="显示索引统计")
    
    args = parser.parse_args()
    
    if not es.ping():
        print("✗ 无法连接到 Elasticsearch")
        sys.exit(1)
    
    print("✓ Elasticsearch 连接成功\n")
    
    if args.clear:
        clear_index()
    
    create_index_mapping()
    
    if args.search:
        results = search_content(args.search, size=10, mode=args.search_mode)
        if results and results['hits']['hits']:
            print(f"\n🔍 搜索: '{args.search}' (模式: {args.search_mode})")
            print(f"找到 {results['hits']['total']['value']} 个结果 (耗时: {results['took']}ms)\n")
            
            for i, hit in enumerate(results['hits']['hits'], 1):
                print(f"{i}. 📄 {hit['_source']['file_name']}")
                print(f"   路径: {hit['_source']['file_path']}")
                print(f"   标题: {hit['_source']['title']}")
                print(f"   匹配度: {hit['_score']:.2f}")
                print(f"   字数: {hit['_source']['word_count']}")
                print()
        else:
            print(f"❌ 未找到关于 '{args.search}' 的结果")
    elif args.stats:
        get_index_stats()
    else:
        index_all_markdown_files(limit=args.limit)
        get_index_stats()
