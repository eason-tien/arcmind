"""
Skill: browser_skill
Headless 瀏覽器自動化 — 網頁擷取、截圖、表單填寫

後端: Playwright (需安裝) 或 fallback 到 Jina Reader
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.browser")

_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "browser_output"


def _jina_fetch(url: str, max_chars: int = 15000) -> str:
    """Fallback: fetch URL content via Jina Reader."""
    try:
        import httpx
        resp = httpx.get(
            f"https://r.jina.ai/{url}",
            headers={"Accept": "text/plain", "X-Return-Format": "text"},
            timeout=20, follow_redirects=True,
        )
        if resp.status_code == 200:
            return resp.text.strip()[:max_chars]
    except Exception as e:
        logger.warning("[browser] Jina fetch failed: %s", e)
    return ""


def _get_playwright():
    """Get Playwright browser context."""
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        return None


def _fetch_page(inputs: dict) -> dict:
    """Fetch a web page's text content."""
    url = inputs.get("url", "")
    if not url:
        return {"success": False, "error": "url 為必填"}

    max_chars = int(inputs.get("max_chars", 15000))
    wait_seconds = int(inputs.get("wait_seconds", 2))

    pw_factory = _get_playwright()
    if pw_factory:
        try:
            with pw_factory() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                if wait_seconds:
                    page.wait_for_timeout(wait_seconds * 1000)
                title = page.title()
                content = page.inner_text("body")[:max_chars]
                current_url = page.url
                browser.close()

            return {
                "success": True,
                "backend": "playwright",
                "url": current_url,
                "title": title,
                "content": content,
                "length": len(content),
            }
        except Exception as e:
            logger.warning("[browser] Playwright failed, falling back to Jina: %s", e)

    # Fallback to Jina Reader
    content = _jina_fetch(url, max_chars)
    if content:
        return {
            "success": True,
            "backend": "jina_reader",
            "url": url,
            "title": url.split("/")[-1][:50],
            "content": content,
            "length": len(content),
        }

    return {"success": False, "error": f"無法取得頁面內容: {url}"}


def _screenshot(inputs: dict) -> dict:
    """Take a screenshot of a web page."""
    url = inputs.get("url", "")
    if not url:
        return {"success": False, "error": "url 為必填"}

    pw_factory = _get_playwright()
    if not pw_factory:
        return {"success": False, "error": "需要安裝 Playwright: pip install playwright && playwright install chromium"}

    width = int(inputs.get("width", 1280))
    height = int(inputs.get("height", 720))
    full_page = inputs.get("full_page", False)
    wait_seconds = int(inputs.get("wait_seconds", 2))

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"screenshot_{int(time.time())}.png"
    out_path = _OUTPUT_DIR / filename

    try:
        with pw_factory() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            if wait_seconds:
                page.wait_for_timeout(wait_seconds * 1000)
            page.screenshot(path=str(out_path), full_page=full_page)
            title = page.title()
            browser.close()

        return {
            "success": True,
            "path": str(out_path),
            "title": title,
            "url": url,
            "size": f"{width}x{height}",
            "full_page": full_page,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _extract_links(inputs: dict) -> dict:
    """Extract all links from a web page."""
    url = inputs.get("url", "")
    if not url:
        return {"success": False, "error": "url 為必填"}

    pw_factory = _get_playwright()
    if not pw_factory:
        return {"success": False, "error": "需要安裝 Playwright"}

    try:
        with pw_factory() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")

            links = page.eval_on_selector_all(
                "a[href]",
                """els => els.map(el => ({
                    text: el.innerText.trim().substring(0, 100),
                    href: el.href,
                })).filter(l => l.href && l.href.startsWith('http'))"""
            )
            browser.close()

        # Deduplicate
        seen = set()
        unique = []
        for link in links:
            if link["href"] not in seen:
                seen.add(link["href"])
                unique.append(link)

        return {"success": True, "links": unique[:100], "count": len(unique)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _fill_form(inputs: dict) -> dict:
    """Fill and submit a form on a web page."""
    url = inputs.get("url", "")
    fields = inputs.get("fields", {})  # {selector: value}
    submit_selector = inputs.get("submit_selector", "")

    if not url or not fields:
        return {"success": False, "error": "url 和 fields 為必填"}

    pw_factory = _get_playwright()
    if not pw_factory:
        return {"success": False, "error": "需要安裝 Playwright"}

    try:
        with pw_factory() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")

            for selector, value in fields.items():
                page.fill(selector, str(value))

            if submit_selector:
                page.click(submit_selector)
                page.wait_for_timeout(3000)

            result_url = page.url
            result_content = page.inner_text("body")[:5000]
            browser.close()

        return {
            "success": True,
            "result_url": result_url,
            "result_content": result_content,
            "fields_filled": len(fields),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def _evaluate_js(inputs: dict) -> dict:
    """Execute JavaScript on a page and return the result."""
    url = inputs.get("url", "")
    script = inputs.get("script", "")

    if not url or not script:
        return {"success": False, "error": "url 和 script 為必填"}

    pw_factory = _get_playwright()
    if not pw_factory:
        return {"success": False, "error": "需要安裝 Playwright"}

    try:
        with pw_factory() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            result = page.evaluate(script)
            browser.close()

        return {"success": True, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def run(inputs: dict) -> dict:
    """
    Browser skill entry point.

    inputs:
      action: fetch_page | screenshot | extract_links | fill_form | evaluate_js
      url: str (必填)
    """
    action = inputs.get("action", "fetch_page")
    handlers = {
        "fetch_page": _fetch_page,
        "screenshot": _screenshot,
        "extract_links": _extract_links,
        "fill_form": _fill_form,
        "evaluate_js": _evaluate_js,
    }
    handler = handlers.get(action)
    if not handler:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[browser] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
