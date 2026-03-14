"""
Skill: notion_skill
Notion API 整合 — 頁面/資料庫/區塊 CRUD

需要: NOTION_API_KEY 環境變數
Notion integration token 從 https://www.notion.so/my-integrations 取得
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("arcmind.skill.notion")

_API_KEY = os.environ.get("NOTION_API_KEY", "")
_BASE = "https://api.notion.com/v1"
_VERSION = "2022-06-28"


def _request(method: str, path: str, body: dict | None = None) -> dict:
    """Make a Notion API request."""
    if not _API_KEY:
        raise RuntimeError("NOTION_API_KEY 環境變數未設定")
    try:
        import httpx
    except ImportError:
        raise RuntimeError("需要安裝 httpx: pip install httpx")

    headers = {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": _VERSION,
    }
    with httpx.Client(timeout=20) as client:
        if method == "GET":
            resp = client.get(f"{_BASE}{path}", headers=headers)
        elif method == "POST":
            resp = client.post(f"{_BASE}{path}", headers=headers, json=body or {})
        elif method == "PATCH":
            resp = client.patch(f"{_BASE}{path}", headers=headers, json=body or {})
        elif method == "DELETE":
            resp = client.delete(f"{_BASE}{path}", headers=headers)
        else:
            raise ValueError(f"Unsupported method: {method}")
    resp.raise_for_status()
    return resp.json() if resp.content else {}


def _extract_title(page: dict) -> str:
    """Extract title from a Notion page object."""
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            titles = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in titles)
    return "(untitled)"


def _search(inputs: dict) -> dict:
    """Search pages and databases."""
    query = inputs.get("query", "")
    filter_type = inputs.get("filter_type", "")  # "page" or "database"
    max_results = int(inputs.get("max_results", 20))

    body = {"page_size": max_results}
    if query:
        body["query"] = query
    if filter_type in ("page", "database"):
        body["filter"] = {"value": filter_type, "property": "object"}

    result = _request("POST", "/search", body)
    items = []
    for r in result.get("results", []):
        item = {
            "id": r["id"],
            "type": r["object"],
            "url": r.get("url", ""),
            "created_time": r.get("created_time", ""),
            "last_edited_time": r.get("last_edited_time", ""),
        }
        if r["object"] == "page":
            item["title"] = _extract_title(r)
        elif r["object"] == "database":
            titles = r.get("title", [])
            item["title"] = "".join(t.get("plain_text", "") for t in titles)
        items.append(item)

    return {"success": True, "results": items, "count": len(items)}


def _get_page(inputs: dict) -> dict:
    """Get a page's properties."""
    page_id = inputs.get("page_id", "")
    if not page_id:
        return {"success": False, "error": "page_id 為必填"}

    result = _request("GET", f"/pages/{page_id}")
    return {
        "success": True,
        "id": result["id"],
        "title": _extract_title(result),
        "url": result.get("url", ""),
        "created_time": result.get("created_time", ""),
        "last_edited_time": result.get("last_edited_time", ""),
        "properties": {k: v.get("type") for k, v in result.get("properties", {}).items()},
    }


def _get_page_content(inputs: dict) -> dict:
    """Get a page's block children (content)."""
    page_id = inputs.get("page_id", inputs.get("block_id", ""))
    if not page_id:
        return {"success": False, "error": "page_id 為必填"}

    result = _request("GET", f"/blocks/{page_id}/children?page_size=100")
    blocks = []
    for b in result.get("results", []):
        block = {"id": b["id"], "type": b["type"]}
        block_data = b.get(b["type"], {})
        if "rich_text" in block_data:
            block["text"] = "".join(t.get("plain_text", "") for t in block_data["rich_text"])
        elif "text" in block_data:
            block["text"] = "".join(t.get("plain_text", "") for t in block_data["text"])
        blocks.append(block)

    return {"success": True, "blocks": blocks, "count": len(blocks)}


def _create_page(inputs: dict) -> dict:
    """Create a new page in a parent page or database."""
    parent_id = inputs.get("parent_id", "")
    parent_type = inputs.get("parent_type", "page_id")  # "page_id" or "database_id"
    title = inputs.get("title", "")
    content = inputs.get("content", "")

    if not parent_id:
        return {"success": False, "error": "parent_id 為必填"}

    body = {
        "parent": {parent_type: parent_id},
        "properties": {
            "title": {"title": [{"text": {"content": title}}]}
        } if parent_type == "page_id" else {
            "Name": {"title": [{"text": {"content": title}}]}
        },
    }

    # Add content blocks
    if content:
        paragraphs = content.split("\n")
        body["children"] = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": p}}]
                },
            }
            for p in paragraphs
            if p.strip()
        ]

    result = _request("POST", "/pages", body)
    return {
        "success": True,
        "page_id": result["id"],
        "url": result.get("url", ""),
    }


def _update_page(inputs: dict) -> dict:
    """Update page properties."""
    page_id = inputs.get("page_id", "")
    properties = inputs.get("properties", {})

    if not page_id:
        return {"success": False, "error": "page_id 為必填"}

    result = _request("PATCH", f"/pages/{page_id}", {"properties": properties})
    return {"success": True, "page_id": result["id"]}


def _append_blocks(inputs: dict) -> dict:
    """Append content blocks to a page."""
    page_id = inputs.get("page_id", inputs.get("block_id", ""))
    content = inputs.get("content", "")

    if not page_id or not content:
        return {"success": False, "error": "page_id 和 content 為必填"}

    paragraphs = content.split("\n")
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": p}}]
            },
        }
        for p in paragraphs
        if p.strip()
    ]

    result = _request("PATCH", f"/blocks/{page_id}/children", {"children": children})
    return {"success": True, "appended_blocks": len(children)}


def _query_database(inputs: dict) -> dict:
    """Query a Notion database."""
    database_id = inputs.get("database_id", "")
    filter_obj = inputs.get("filter")
    sorts = inputs.get("sorts")
    max_results = int(inputs.get("max_results", 50))

    if not database_id:
        return {"success": False, "error": "database_id 為必填"}

    body = {"page_size": min(max_results, 100)}
    if filter_obj:
        body["filter"] = filter_obj
    if sorts:
        body["sorts"] = sorts

    result = _request("POST", f"/databases/{database_id}/query", body)
    rows = []
    for page in result.get("results", []):
        row = {"id": page["id"], "url": page.get("url", "")}
        for prop_name, prop_val in page.get("properties", {}).items():
            ptype = prop_val.get("type", "")
            if ptype == "title":
                row[prop_name] = "".join(t.get("plain_text", "") for t in prop_val.get("title", []))
            elif ptype == "rich_text":
                row[prop_name] = "".join(t.get("plain_text", "") for t in prop_val.get("rich_text", []))
            elif ptype in ("number", "checkbox", "url", "email", "phone_number"):
                row[prop_name] = prop_val.get(ptype)
            elif ptype == "select":
                sel = prop_val.get("select")
                row[prop_name] = sel.get("name", "") if sel else ""
            elif ptype == "date":
                d = prop_val.get("date")
                row[prop_name] = d.get("start", "") if d else ""
        rows.append(row)

    return {"success": True, "rows": rows, "count": len(rows)}


def run(inputs: dict) -> dict:
    """
    Notion skill entry point.

    inputs:
      action: search | get_page | get_page_content | create_page |
              update_page | append_blocks | query_database
    """
    action = inputs.get("action", "search")
    handlers = {
        "search": _search,
        "get_page": _get_page,
        "get_page_content": _get_page_content,
        "create_page": _create_page,
        "update_page": _update_page,
        "append_blocks": _append_blocks,
        "query_database": _query_database,
    }
    handler = handlers.get(action)
    if not handler:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[notion] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
