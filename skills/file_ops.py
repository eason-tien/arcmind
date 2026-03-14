"""
Skill: file_ops
本地檔案讀寫、列目錄等操作。
安全限制：只允許操作 ArcMind 資料目錄內的檔案，或絕對路徑白名單中的目錄。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# 允許操作的根目錄白名單
_ALLOWED_ROOTS: list[Path] = []

def _get_allowed_roots() -> list[Path]:
    if not _ALLOWED_ROOTS:
        from config.settings import settings
        _ALLOWED_ROOTS.append(settings.evidence_dir)
        _ALLOWED_ROOTS.append(settings.db_path.parent)
    return _ALLOWED_ROOTS


def _check_path(path: Path) -> None:
    """確認路徑在允許範圍內，且不是符號鏈接"""
    # Block symlinks to prevent TOCTOU attacks
    if path.exists() and path.is_symlink():
        raise PermissionError(f"Symlinks are not allowed: '{path}'")
    resolved = path.resolve()
    for root in _get_allowed_roots():
        try:
            resolved.relative_to(root.resolve())
            return  # OK
        except ValueError:
            continue
    raise PermissionError(
        f"Path '{path}' is outside allowed directories. "
        f"Allowed: {[str(r) for r in _get_allowed_roots()]}"
    )


def run(inputs: dict) -> dict:
    """
    inputs:
      - operation: read | write | list | delete | exists | mkdir
      - path: 目標路徑
      - content: 寫入內容（operation=write 時）
    """
    operation = inputs.get("operation", "").lower()
    path_str = inputs.get("path", "").strip()

    if not operation:
        return {"error": "operation is required"}
    if not path_str:
        return {"error": "path is required"}

    path = Path(path_str)

    if operation == "exists":
        return {"exists": path.exists(), "path": str(path)}

    if operation == "list":
        _check_path(path)
        if not path.is_dir():
            return {"error": f"Not a directory: {path}"}
        items = [
            {
                "name": p.name,
                "is_dir": p.is_dir(),
                "size": p.stat().st_size if p.is_file() else None,
            }
            for p in sorted(path.iterdir())
        ]
        return {"path": str(path), "items": items, "count": len(items)}

    if operation == "mkdir":
        _check_path(path.parent if not path.exists() else path)
        path.mkdir(parents=True, exist_ok=True)
        return {"created": str(path)}

    if operation == "read":
        _check_path(path)
        if not path.exists():
            return {"error": f"File not found: {path}"}
        content = path.read_text(encoding="utf-8")
        return {"path": str(path), "content": content, "size": len(content)}

    if operation == "write":
        _check_path(path.parent)
        content = inputs.get("content", "")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"path": str(path), "written_bytes": len(content.encode())}

    if operation == "delete":
        _check_path(path)
        if not path.exists():
            return {"error": f"File not found: {path}"}
        if path.is_file():
            path.unlink()
        else:
            import shutil
            shutil.rmtree(path)
        return {"deleted": str(path)}

    return {"error": f"Unknown operation: {operation}"}
