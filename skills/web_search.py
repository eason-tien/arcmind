"""
Skill: web_search
使用 DuckDuckGo 搜尋網路，返回摘要結果列表。
"""
from __future__ import annotations


def run(inputs: dict) -> dict:
    """
    inputs:
      - query (str): 搜尋關鍵字
      - max_results (int): 最多返回幾筆，預設 5
    returns:
      - results: [{title, href, body}, ...]
      - query: str
      - count: int
    """
    query = inputs.get("query", "").strip()
    if not query:
        return {"error": "query is required", "results": [], "count": 0}

    max_results = int(inputs.get("max_results", 5))

    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return {
                "error": "ddgs not installed. Run: pip install ddgs",
                "results": [],
                "count": 0,
            }

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "href": r.get("href", ""),
                    "body": r.get("body", "")[:500],  # 截斷避免過長
                })
    except Exception as e:
        return {"error": str(e), "results": [], "count": 0, "query": query}

    return {
        "query": query,
        "results": results,
        "count": len(results),
    }
