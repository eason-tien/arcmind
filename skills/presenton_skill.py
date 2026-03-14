# -*- coding: utf-8 -*-
"""
Skill: presenton_skill
Presenton AI — 精美 PPT 簡報生成

使用 Presenton Docker 容器 (ghcr.io/presenton/presenton)
API: POST /api/v1/ppt/presentation/generate
"""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.presenton")

# Presenton 服務地址（Docker 預設）
_BASE_URL = os.getenv("PRESENTON_URL", "http://localhost:5050")
_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "presentations"


def _api_request(endpoint: str, data: dict | None = None,
                 method: str = "GET", timeout: int = 120) -> dict:
    """Send request to Presenton API."""
    url = f"{_BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}

    # Optional: cloud API key
    api_key = os.getenv("PRESENTON_API_KEY", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        return {"success": False, "error": f"HTTP {e.code}: {error_body[:500]}"}
    except urllib.error.URLError as e:
        return {"success": False, "error": f"連線失敗: {e.reason}. Presenton 是否已啟動？"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _generate(inputs: dict) -> dict:
    """Generate a presentation via Presenton API."""
    content = inputs.get("content", "")
    if not content:
        return {"success": False, "error": "content 為必填（簡報主題或詳細描述）"}

    n_slides = int(inputs.get("n_slides", 5))
    language = inputs.get("language", "Chinese")
    template = inputs.get("template", "general")
    export_as = inputs.get("export_as", "pptx")

    payload = {
        "content": content,
        "n_slides": n_slides,
        "language": language,
        "template": template,
        "export_as": export_as,
    }

    logger.info("[presenton] Generating: %s (%d slides, %s)", content[:50], n_slides, export_as)
    result = _api_request("/api/v1/ppt/presentation/generate", data=payload, method="POST")

    if "error" in result and not result.get("presentation_id"):
        return {"success": False, **result}

    # Build download info
    pres_id = result.get("presentation_id", "")
    raw_path = result.get("path", "")
    edit_path = result.get("edit_path", "")

    # For self-hosted: path is a local path like /app_data/xxx/file.pptx
    # We need to download or map it
    download_url = ""
    local_path = ""

    if raw_path.startswith("http"):
        download_url = raw_path
    elif raw_path.startswith("/app_data/"):
        # Docker volume mapped to data/presenton/
        mapped = Path(__file__).resolve().parent.parent / "data" / "presenton" / raw_path[len("/app_data/"):]
        if mapped.exists():
            local_path = str(mapped)
        else:
            # Try downloading from the API
            download_url = f"{_BASE_URL}/static/user_data/{raw_path[len('/app_data/'):]}"

    # If we have a download URL but no local file, try downloading
    if download_url and not local_path:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filename = Path(raw_path).name if raw_path else f"presentation_{pres_id}.{export_as}"
        local_path = str(_OUTPUT_DIR / filename)
        try:
            urllib.request.urlretrieve(download_url, local_path)
        except Exception as dl_err:
            logger.warning("[presenton] Download failed: %s", dl_err)
            local_path = ""

    return {
        "success": True,
        "presentation_id": pres_id,
        "file_path": local_path,
        "download_url": download_url or raw_path,
        "edit_url": f"{_BASE_URL}{edit_path}" if edit_path and not edit_path.startswith("http") else edit_path,
        "slides": n_slides,
        "format": export_as,
        "message": f"簡報已生成！共 {n_slides} 頁 ({export_as.upper()})。",
    }


def _list_presentations(inputs: dict) -> dict:
    """List generated presentations from local storage."""
    output_dir = Path(__file__).resolve().parent.parent / "data" / "presenton"
    if not output_dir.exists():
        return {"success": True, "presentations": [], "message": "尚無已生成的簡報。"}

    presentations = []
    for pptx in sorted(output_dir.rglob("*.pptx"), key=lambda p: p.stat().st_mtime, reverse=True):
        presentations.append({
            "name": pptx.name,
            "path": str(pptx),
            "size_kb": round(pptx.stat().st_size / 1024, 1),
        })
    for pdf in sorted(output_dir.rglob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True):
        presentations.append({
            "name": pdf.name,
            "path": str(pdf),
            "size_kb": round(pdf.stat().st_size / 1024, 1),
        })

    return {
        "success": True,
        "presentations": presentations[:20],
        "total": len(presentations),
    }


def _status(inputs: dict) -> dict:
    """Check Presenton service status."""
    try:
        req = urllib.request.Request(f"{_BASE_URL}/", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            return {
                "success": True,
                "status": "running",
                "url": _BASE_URL,
                "http_code": resp.status,
            }
    except Exception as e:
        return {
            "success": False,
            "status": "offline",
            "url": _BASE_URL,
            "error": str(e),
            "hint": "請執行: docker start presenton 或查看 Docker 狀態",
        }


def run(inputs: dict) -> dict:
    """
    Presenton AI Presentation skill entry point.

    inputs:
      action: generate | list | status
      content: 簡報主題或詳細描述 (generate 時必填)
      n_slides: 頁數 (預設 5)
      language: 語言 (預設 "Chinese")
      template: 模板 (預設 "general")
      export_as: "pptx" | "pdf" (預設 "pptx")
    """
    action = inputs.get("action", "generate")
    handlers = {
        "generate": _generate,
        "list": _list_presentations,
        "status": _status,
    }
    handler = handlers.get(action)
    if not handler:
        return {
            "success": False,
            "error": f"未知 action: {action}",
            "available_actions": list(handlers.keys()),
        }
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[presenton] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
