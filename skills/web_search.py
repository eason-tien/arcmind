"""
Skill: web_search
V3.2: Multi-engine web search with content extraction, query rewriting,
      Perplexity integration, and iterative research mode.

搜尋引擎優先級:
1. Perplexity (搜尋+摘要一體, 需要 API Key)
2. Tavily (AI-optimized, 需要 API Key)
3. DuckDuckGo (免費 fallback)

搜尋模式:
- "fast"     : 只返回 snippet 摘要 (預設, 快)
- "deep"     : 搜尋後用 Jina Reader 讀取前 N 個結果全文 (慢但準)
- "research" : 多輪搜尋 + LLM 查詢重寫 + 全文讀取 + 綜合報告 (最慢最準)

內容提取:
- Jina Reader API (r.jina.ai) — 免費, 無需 Key, 從 URL 提取乾淨文字
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger("arcmind.skill.web_search")


# ── 搜尋引擎 ──────────────────────────────────────────────────

def _search_perplexity(query: str, max_results: int = 5) -> dict | None:
    """
    Perplexity Online — 搜尋+摘要一體.
    返回結構化的搜尋摘要 + 引用來源.
    """
    api_key = os.environ.get("PERPLEXITY_API_KEY", "")
    if not api_key:
        return None

    try:
        import httpx
        resp = httpx.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "sonar",
                "messages": [
                    {"role": "system", "content": "Be precise and concise. Include specific technical details."},
                    {"role": "user", "content": query},
                ],
                "max_tokens": 1024,
                "return_citations": True,
                "return_related_questions": True,
            },
            timeout=25,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        citations = data.get("citations", [])

        if not content:
            return None

        # 構造搜尋結果格式
        results = [{
            "title": f"Perplexity Summary: {query[:50]}",
            "href": citations[0] if citations else "",
            "body": content[:2000],
            "full_content": content,
            "source": "perplexity",
        }]

        # 引用來源作為額外結果
        for i, url in enumerate(citations[:max_results - 1]):
            results.append({
                "title": f"Source {i + 1}",
                "href": url,
                "body": "",
                "source": "perplexity_citation",
            })

        return {
            "results": results,
            "summary": content,
            "citations": citations,
            "related_questions": data.get("related_questions", []),
        }

    except Exception as e:
        logger.warning("[web_search] Perplexity failed: %s", e)
        return None


def _search_tavily(query: str, max_results: int = 5,
                   search_depth: str = "basic") -> list[dict] | None:
    """Tavily Search — AI 專用搜尋 API, 內建內容提取."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return None

    try:
        import httpx
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": search_depth,  # "basic" or "advanced"
                "include_raw_content": search_depth == "advanced",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for r in data.get("results", []):
            item = {
                "title": r.get("title", ""),
                "href": r.get("url", ""),
                "body": r.get("content", "")[:2000],
                "source": "tavily",
            }
            raw = r.get("raw_content", "")
            if raw:
                item["full_content"] = raw[:5000]
            results.append(item)
        return results

    except Exception as e:
        logger.warning("[web_search] Tavily failed: %s", e)
        return None


def _search_ddg(query: str, max_results: int = 5) -> list[dict] | None:
    """DuckDuckGo — 免費 fallback."""
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return None

    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title": r.get("title", ""),
                    "href": r.get("href", ""),
                    "body": r.get("body", "")[:500],
                    "source": "ddg",
                })
        return results
    except Exception as e:
        logger.warning("[web_search] DDG failed: %s", e)
        return None


# ── 內容提取 ──────────────────────────────────────────────────

def _extract_url_content(url: str, max_chars: int = 5000,
                         timeout: int = 15) -> str:
    """
    使用 Jina Reader API 提取 URL 的乾淨文字內容.
    免費, 無需 API Key, 支援大多數網頁.
    """
    if not url:
        return ""

    try:
        import httpx
        jina_url = f"https://r.jina.ai/{url}"
        resp = httpx.get(
            jina_url,
            headers={
                "Accept": "text/plain",
                "X-Return-Format": "text",
            },
            timeout=timeout,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            content = resp.text.strip()
            # 過濾 Cloudflare challenge 頁面
            if len(content) < 500 and "security" in content.lower() and "bot" in content.lower():
                logger.debug("[web_search] Jina: CF challenge for %s", url[:60])
                return ""
            return content[:max_chars]
        else:
            logger.debug("[web_search] Jina Reader %d for %s", resp.status_code, url[:60])
            return ""
    except Exception as e:
        logger.debug("[web_search] Jina Reader failed for %s: %s", url[:60], e)
        return ""


def _extract_multiple(urls: list[str], max_chars: int = 5000,
                      max_concurrent: int = 3, timeout: int = 15) -> dict[str, str]:
    """並行提取多個 URL 的內容."""
    results = {}
    with ThreadPoolExecutor(max_workers=max_concurrent) as pool:
        future_map = {
            pool.submit(_extract_url_content, url, max_chars, timeout): url
            for url in urls[:max_concurrent]
        }
        for future in as_completed(future_map, timeout=timeout + 5):
            url = future_map[future]
            try:
                content = future.result()
                if content:
                    results[url] = content
            except Exception:
                pass
    return results


# ── LLM 查詢重寫 ─────────────────────────────────────────────

def _rewrite_queries(original_query: str, max_variants: int = 3) -> list[str]:
    """
    用 LLM 將用戶的原始問題重寫為多個優化的搜尋查詢.
    例: "為什麼 Pollo AI API 被擋了" → [
        "Pollo AI API 403 Cloudflare blocked",
        "pollo.ai API authentication error fix",
        "kling video API cloudflare managed challenge bypass",
    ]
    """
    queries = [original_query]  # 始終保留原始查詢

    try:
        from runtime.model_router import model_router
        resp = model_router.complete(
            prompt=(
                f"將以下用戶問題改寫為 {max_variants} 個優化的英文搜尋查詢。\n"
                f"要求:\n"
                f"- 用英文（搜尋引擎對英文效果更好）\n"
                f"- 包含具體技術關鍵字\n"
                f"- 每個查詢角度不同（如: 錯誤訊息、解決方案、官方文檔）\n"
                f"- 只回覆 JSON 陣列\n\n"
                f"用戶問題: {original_query}\n\n"
                f'回覆格式: ["query1", "query2", "query3"]'
            ),
            system="你是搜尋查詢優化專家。將用戶問題轉為多個精確搜尋查詢。只回覆 JSON 陣列。",
            max_tokens=256,
            task_type="general",
            budget="low",
        )
        text = resp.content.strip()
        # Strip think tags
        import re
        text = re.sub(r'<think>[\s\S]*?</think>\s*', '', text).strip()
        s = text.find("[")
        e = text.rfind("]") + 1
        if s >= 0 and e > s:
            variants = json.loads(text[s:e])
            if isinstance(variants, list):
                # 去重, 保持原始查詢在最前
                seen = {original_query.lower()}
                for v in variants[:max_variants]:
                    v_str = str(v).strip()
                    if v_str and v_str.lower() not in seen:
                        queries.append(v_str)
                        seen.add(v_str.lower())
        logger.info("[web_search] Query rewrite: %d variants", len(queries))
    except Exception as e:
        logger.debug("[web_search] Query rewrite failed: %s", e)

    return queries[:max_variants + 1]


# ── Research 模式 (多輪迭代搜尋) ─────────────────────────────

def _research(query: str, max_results: int = 5, max_rounds: int = 2) -> dict:
    """
    Research 模式: 多輪搜尋 + 讀全文 + LLM 綜合.

    流程:
    Round 1: LLM 重寫查詢 → 多查詢搜尋 → 讀全文
    Round 2: LLM 判斷是否需要追問 → 如需要則用新查詢再搜
    Final:   LLM 綜合所有收集到的資料 → 生成研究報告
    """
    all_results = []
    all_content = []
    queries_used = []

    # Round 1: 重寫查詢 + 多查詢搜尋
    search_queries = _rewrite_queries(query, max_variants=2)
    queries_used.extend(search_queries)

    for sq in search_queries:
        results = _search_tavily(sq, max_results=3, search_depth="advanced")
        engine = "tavily"
        if not results:
            results = _search_ddg(sq, max_results=3)
            engine = "ddg"
        if results:
            for r in results:
                r["search_query"] = sq
            all_results.extend(results)

    # 去重 (by URL)
    seen_urls = set()
    unique_results = []
    for r in all_results:
        url = r.get("href", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique_results.append(r)
    all_results = unique_results

    # 讀全文 (如果搜尋引擎沒有提供)
    urls_need_extract = [
        r["href"] for r in all_results
        if r.get("href") and not r.get("full_content")
    ][:5]

    if urls_need_extract:
        logger.info("[web_search] Research: extracting %d URLs...", len(urls_need_extract))
        extracted = _extract_multiple(urls_need_extract, max_chars=5000, max_concurrent=3)
        for r in all_results:
            url = r.get("href", "")
            if url in extracted:
                r["full_content"] = extracted[url]

    # 收集所有有效內容
    for r in all_results:
        content = r.get("full_content") or r.get("body", "")
        if content and len(content) > 100:
            all_content.append({
                "url": r.get("href", ""),
                "title": r.get("title", ""),
                "content": content[:3000],
            })

    # Round 2: LLM 判斷是否需要追問
    if max_rounds >= 2 and all_content:
        followup_query = _assess_and_followup(query, all_content)
        if followup_query:
            logger.info("[web_search] Research round 2: %s", followup_query[:60])
            queries_used.append(followup_query)

            r2_results = _search_tavily(followup_query, max_results=3, search_depth="advanced")
            if not r2_results:
                r2_results = _search_ddg(followup_query, max_results=3)

            if r2_results:
                # 提取新結果全文
                new_urls = [
                    r["href"] for r in r2_results
                    if r.get("href") and r["href"] not in seen_urls and not r.get("full_content")
                ][:3]
                if new_urls:
                    extracted2 = _extract_multiple(new_urls, max_chars=5000)
                    for r in r2_results:
                        url = r.get("href", "")
                        if url in extracted2:
                            r["full_content"] = extracted2[url]

                for r in r2_results:
                    url = r.get("href", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        all_results.append(r)
                        content = r.get("full_content") or r.get("body", "")
                        if content and len(content) > 100:
                            all_content.append({
                                "url": url,
                                "title": r.get("title", ""),
                                "content": content[:3000],
                            })

    # Final: LLM 綜合報告
    synthesis = _synthesize_research(query, all_content)

    return {
        "query": query,
        "results": all_results,
        "count": len(all_results),
        "engine": "multi",
        "mode": "research",
        "queries_used": queries_used,
        "synthesis": synthesis,
        "sources_read": len(all_content),
    }


def _assess_and_followup(original_query: str, contents: list[dict]) -> str | None:
    """LLM 判斷已收集的資料是否足夠回答問題，不夠則生成追問查詢."""
    try:
        from runtime.model_router import model_router

        summary = "\n".join(
            f"- {c['title']}: {c['content'][:200]}"
            for c in contents[:5]
        )

        resp = model_router.complete(
            prompt=(
                f"用戶問題: {original_query}\n\n"
                f"已找到的資料摘要:\n{summary}\n\n"
                f"判斷:\n"
                f"1. 現有資料能否回答用戶問題？\n"
                f"2. 如果不夠，還需要搜尋什麼？\n\n"
                f"如果資料已足夠，回覆: SUFFICIENT\n"
                f'如果需要追加搜尋，回覆一個英文搜尋查詢字串（不要引號，不要 JSON）'
            ),
            system="你是研究助手。判斷資料是否充分，不夠則提出追加搜尋查詢。",
            max_tokens=128,
            task_type="general",
            budget="low",
        )
        text = resp.content.strip()
        import re
        text = re.sub(r'<think>[\s\S]*?</think>\s*', '', text).strip()

        if "SUFFICIENT" in text.upper():
            return None
        # 取第一行作為追加查詢
        followup = text.split("\n")[0].strip().strip('"').strip("'")
        if followup and len(followup) > 5:
            return followup
    except Exception as e:
        logger.debug("[web_search] Follow-up assessment failed: %s", e)
    return None


def _synthesize_research(query: str, contents: list[dict]) -> str:
    """LLM 綜合所有收集到的資料，生成結構化研究報告."""
    if not contents:
        return "No content collected for synthesis."

    try:
        from runtime.model_router import model_router

        material = "\n\n---\n\n".join(
            f"Source: {c['title']} ({c['url']})\n{c['content'][:2000]}"
            for c in contents[:8]
        )

        resp = model_router.complete(
            prompt=(
                f"根據以下搜尋到的多個來源資料，對用戶問題進行綜合分析。\n\n"
                f"用戶問題: {query}\n\n"
                f"資料來源:\n{material[:6000]}\n\n"
                f"要求:\n"
                f"1. 綜合多個來源的資訊，給出完整的答案\n"
                f"2. 標出關鍵發現和具體解決方案\n"
                f"3. 如有矛盾資訊，說明不同觀點\n"
                f"4. 用中文回覆，技術術語保留英文\n"
                f"5. 列出引用來源\n"
            ),
            system="你是研究分析師。綜合多個來源的資料，生成準確的研究報告。",
            max_tokens=2048,
            task_type="general",
            budget="high",
        )
        text = resp.content.strip()
        import re
        text = re.sub(r'<think>[\s\S]*?</think>\s*', '', text).strip()
        return text

    except Exception as e:
        logger.warning("[web_search] Synthesis failed: %s", e)
        # Fallback: 直接拼接
        return "\n".join(
            f"## {c['title']}\n{c['content'][:500]}"
            for c in contents[:5]
        )


# ── 主入口 ────────────────────────────────────────────────────

def run(inputs: dict) -> dict:
    """
    inputs:
      - query (str): 搜尋關鍵字 (必須)
      - max_results (int): 最多返回幾筆, 預設 5
      - mode (str): "fast" | "deep" | "research"
        - fast: 只返回搜尋引擎 snippet
        - deep: 搜尋後提取前 3 個結果的全文
        - research: 多輪搜尋 + LLM 查詢重寫 + 全文讀取 + 綜合報告
      - extract_urls (list[str]): 直接提取指定 URL 的內容 (跳過搜尋)
      - rewrite (bool): 是否用 LLM 重寫查詢 (fast/deep 預設 false, research 預設 true)

    returns:
      - results: [{title, href, body, source, full_content?}, ...]
      - query: str
      - count: int
      - engine: str
      - mode: str
      - synthesis: str (research mode only)
      - queries_used: list[str] (research mode only)
    """
    # 直接 URL 提取模式
    extract_urls = inputs.get("extract_urls")
    if extract_urls and isinstance(extract_urls, list):
        contents = _extract_multiple(extract_urls, max_chars=8000)
        results = [
            {"title": url.split("/")[-1][:50], "href": url,
             "body": content[:500], "full_content": content, "source": "jina_reader"}
            for url, content in contents.items()
        ]
        return {
            "query": "url_extraction",
            "results": results,
            "count": len(results),
            "engine": "jina_reader",
            "mode": "extract",
        }

    # 搜尋模式
    query = inputs.get("query", "").strip()
    if not query:
        return {"error": "query is required", "results": [], "count": 0}

    max_results = int(inputs.get("max_results", 5))
    mode = inputs.get("mode", "fast")
    rewrite = inputs.get("rewrite", mode == "research")

    # Research 模式走獨立流程
    if mode == "research":
        return _research(query, max_results)

    # LLM 查詢重寫 (如果開啟)
    search_queries = [query]
    if rewrite:
        search_queries = _rewrite_queries(query, max_variants=2)

    # Multi-engine search: Perplexity → Tavily → DDG
    all_results = []
    engine = "none"

    for sq in search_queries:
        results = None

        # fast 模式跳過 Perplexity (太慢)
        if mode != "fast":
            pplx = _search_perplexity(sq, max_results)
            if pplx:
                results = pplx.get("results")
                engine = "perplexity"

        if not results:
            tavily_depth = "advanced" if mode == "deep" else "basic"
            results = _search_tavily(sq, max_results, search_depth=tavily_depth)
            if results:
                engine = "tavily"

        if not results:
            results = _search_ddg(sq, max_results)
            if results:
                engine = "ddg"

        if results:
            for r in results:
                r["search_query"] = sq
            all_results.extend(results)

        # 如果第一個查詢已經找到足夠結果, 跳過後續查詢
        if all_results and not rewrite:
            break

    # 去重
    seen_urls = set()
    unique = []
    for r in all_results:
        url = r.get("href", "")
        if not url or url not in seen_urls:
            if url:
                seen_urls.add(url)
            unique.append(r)
    all_results = unique[:max_results]

    if not all_results:
        return {
            "error": "All search engines failed",
            "results": [],
            "count": 0,
            "query": query,
            "engine": "none",
            "mode": mode,
        }

    # Deep mode: extract full content
    if mode == "deep":
        urls_need_extract = [
            r["href"] for r in all_results[:3]
            if r.get("href") and not r.get("full_content")
        ]
        if urls_need_extract:
            logger.info("[web_search] Deep mode: extracting %d URLs...", len(urls_need_extract))
            extracted = _extract_multiple(urls_need_extract, max_chars=5000)
            for r in all_results:
                url = r.get("href", "")
                if url in extracted:
                    r["full_content"] = extracted[url]

    output = {
        "query": query,
        "results": all_results,
        "count": len(all_results),
        "engine": engine,
        "mode": mode,
    }
    if len(search_queries) > 1:
        output["queries_used"] = search_queries
    return output
