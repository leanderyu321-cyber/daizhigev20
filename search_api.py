#!/usr/bin/env python3
"""
Markdown 搜索 API 服务
访问: http://localhost:8000
"""

from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from elasticsearch import Elasticsearch
from typing import Optional
import json
import uvicorn

app = FastAPI(title="Markdown Search API", version="1.0")

# Elasticsearch 连接
es = Elasticsearch(["http://localhost:9200"])
INDEX_NAME = "markdown_docs"

@app.get("/")
async def root():
    """API 文档"""
    return {
        "title": "Markdown 搜索 API",
        "endpoints": {
            "GET /search": "搜索 Markdown 文件",
            "GET /stats": "查看索引统计",
            "POST /index": "重新索引所有文件"
        }
    }

@app.get("/search")
async def search(
    q: str = Query(..., description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码（从1开始）"),
    size: int = Query(10, ge=1, le=100, description="每页结果数"),
    highlight: bool = Query(True, description="是否返回高亮内容"),
    mode: str = Query("best", description="搜索模式: best/phrase/fuzzy", pattern="^(best|phrase|fuzzy)$")
):
    """
    搜索 Markdown 内容
    
    支持三种搜索模式：
    - best: 最佳匹配（默认，支持单字和短语）
    - phrase: 短语精确匹配（例如"诸葛亮"只匹配这个短语）
    - fuzzy: 模糊匹配（容错拼写错误）
    
    示例: 
    - /search?q=Docker&size=5
    - /search?q=诸葛亮&mode=phrase
    - /search?q=Elasticsearch&mode=fuzzy
    """
    try:
        # 计算分页偏移
        from_offset = (page - 1) * size
        
        # 构建查询 - 根据模式选择不同策略
        if mode == "phrase":
            # 短语搜索 - 精确匹配连续的词
            query_body = {
                "query": {
                    "bool": {
                        "should": [
                            {"match_phrase": {"title": {"query": q, "boost": 3}}},
                            {"match_phrase": {"content": {"query": q}}}
                        ]
                    }
                },
                "from": from_offset,
                "size": size
            }
        elif mode == "fuzzy":
            # 模糊搜索 - 容错拼写
            query_body = {
                "query": {
                    "multi_match": {
                        "query": q,
                        "fields": ["title^3", "content"],
                        "fuzziness": "AUTO"
                    }
                },
                "from": from_offset,
                "size": size
            }
        else:  # best (default)
            # 最佳匹配 - 结合短语和单词搜索
            query_body = {
                "query": {
                    "bool": {
                        "should": [
                            # 短语匹配 - 连续的词获得更高分
                            {"match_phrase": {"title": {"query": q, "boost": 5}}},
                            {"match_phrase": {"content": {"query": q, "boost": 2}}},
                            # 单词匹配 - 作为备选
                            {"multi_match": {
                                "query": q,
                                "fields": ["title^2", "content"]
                            }}
                        ]
                    }
                },
                "from": from_offset,
                "size": size
            }
        
        if highlight:
            query_body["highlight"] = {
                "fields": {
                    "title": {"fragment_size": 100, "number_of_fragments": 1},
                    "content": {"fragment_size": 150, "number_of_fragments": 3}
                },
                "pre_tags": ["<em>"],
                "post_tags": ["</em>"],
                "max_analyzed_offset": 500000  # 处理大文件
            }
        
        results = es.search(index=INDEX_NAME, body=query_body)
        
        hits = []
        for hit in results['hits']['hits']:
            item = {
                "file_name": hit['_source']['file_name'],
                "file_path": hit['_source']['file_path'],
                "title": hit['_source']['title'],
                "score": round(hit['_score'], 2),
                "word_count": hit['_source']['word_count'],
                "size_kb": round(hit['_source']['file_size'] / 1024, 1)
            }
            
            if highlight and 'highlight' in hit:
                # 优先显示标题高亮，其次显示内容高亮
                if 'title' in hit['highlight']:
                    item['title_highlight'] = hit['highlight']['title'][0]
                if 'content' in hit['highlight']:
                    item['content_highlights'] = hit['highlight']['content']
            
            hits.append(item)
        
        response_data = {
            "query": q,
            "mode": mode,
            "total": results['hits']['total']['value'],
            "page": page,
            "size": size,
            "total_pages": (results['hits']['total']['value'] + size - 1) // size,
            "took_ms": results['took'],
            "results": hits
        }
        
        # 使用 ensure_ascii=False 支持中文
        return JSONResponse(
            content=response_data,
            media_type="application/json; charset=utf-8"
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
            media_type="application/json; charset=utf-8"
        )

@app.get("/stats")
async def stats():
    """查看索引统计信息"""
    try:
        if not es.indices.exists(index=INDEX_NAME):
            return {"error": "索引不存在"}
        
        count = es.count(index=INDEX_NAME)
        
        return {
            "index_name": INDEX_NAME,
            "document_count": count['count']
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/health")
async def health():
    """健康检查"""
    try:
        ping = es.ping()
        cluster_health = es.cluster.health()
        
        return {
            "elasticsearch": "connected" if ping else "disconnected",
            "cluster_status": cluster_health['status'],
            "active_shards": cluster_health['active_shards']
        }
    except Exception as e:
        return {"elasticsearch": "error", "error": str(e)}

if __name__ == "__main__":
    print("🚀 启动 Markdown 搜索 API")
    print("📖 文档地址: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000)
