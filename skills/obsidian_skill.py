"""
Skill: obsidian_skill
Obsidian Vault 整合 — 筆記搜尋、讀寫、反向連結

Vault 路徑設定:
- env var: OBSIDIAN_VAULT_PATH
- config: <arcmind>/config/obsidian.json → {"vault_path": "..."}
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.obsidian")

_ARCMIND_DIR = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _ARCMIND_DIR / "config" / "obsidian.json"


def _get_vault_path() -> Path:
    """Get Obsidian vault path from env or config."""
    # 1. Environment variable
    env_path = os.environ.get("OBSIDIAN_VAULT_PATH", "")
    if env_path:
        p = Path(env_path).expanduser()
        if p.exists():
            return p

    # 2. Config file
    if _CONFIG_FILE.exists():
        try:
            config = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            p = Path(config.get("vault_path", "")).expanduser()
            if p.exists():
                return p
        except Exception:
            pass

    # 3. Common default locations
    for candidate in [
        Path.home() / "Documents" / "Obsidian",
        Path.home() / "Obsidian",
        Path.home() / "obsidian-vault",
    ]:
        if candidate.exists():
            return candidate

    raise RuntimeError(
        "Obsidian vault 路徑未設定。請設定 OBSIDIAN_VAULT_PATH 環境變數，"
        f"或建立 {_CONFIG_FILE}"
    )


def _search_notes(inputs: dict) -> dict:
    """Search notes by keyword in filename and content."""
    vault = _get_vault_path()
    query = inputs.get("query", "").strip().lower()
    max_results = int(inputs.get("max_results", 20))

    if not query:
        return {"success": False, "error": "query 為必填"}

    results = []

    for md_file in vault.rglob("*.md"):
        # Skip hidden dirs (like .obsidian)
        if any(part.startswith(".") for part in md_file.relative_to(vault).parts):
            continue

        score = 0
        snippet = ""
        rel_path = str(md_file.relative_to(vault))

        # Filename match (higher score)
        if query in md_file.stem.lower():
            score += 10

        # Content match
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            lower_content = content.lower()
            idx = lower_content.find(query)
            if idx >= 0:
                score += 5
                start = max(0, idx - 50)
                end = min(len(content), idx + len(query) + 100)
                snippet = content[start:end].replace("\n", " ").strip()
        except Exception:
            continue

        if score > 0:
            results.append({
                "path": rel_path,
                "name": md_file.stem,
                "score": score,
                "snippet": snippet[:200],
            })

    results.sort(key=lambda x: x["score"], reverse=True)
    results = results[:max_results]

    return {"success": True, "results": results, "count": len(results)}


def _read_note(inputs: dict) -> dict:
    """Read a note by path or name."""
    vault = _get_vault_path()
    note_path = inputs.get("path", inputs.get("name", ""))

    if not note_path:
        return {"success": False, "error": "path 或 name 為必填"}

    # Add .md extension if missing
    if not note_path.endswith(".md"):
        note_path += ".md"

    full_path = vault / note_path
    if not full_path.exists():
        # Try searching by name
        candidates = list(vault.rglob(f"*{note_path}"))
        if candidates:
            full_path = candidates[0]
        else:
            return {"success": False, "error": f"筆記不存在: {note_path}"}

    content = full_path.read_text(encoding="utf-8", errors="replace")

    # Parse frontmatter
    metadata = {}
    if content.startswith("---"):
        end = content.find("---", 3)
        if end > 0:
            try:
                import yaml
                metadata = yaml.safe_load(content[3:end]) or {}
            except Exception:
                pass

    return {
        "success": True,
        "path": str(full_path.relative_to(vault)),
        "name": full_path.stem,
        "content": content[:10000],
        "metadata": metadata,
        "size": len(content),
    }


def _create_note(inputs: dict) -> dict:
    """Create a new note."""
    vault = _get_vault_path()
    name = inputs.get("name", "").strip()
    content = inputs.get("content", "")
    folder = inputs.get("folder", "")
    tags = inputs.get("tags", [])

    if not name:
        return {"success": False, "error": "name 為必填"}

    if not name.endswith(".md"):
        name += ".md"

    if folder:
        target_dir = vault / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        full_path = target_dir / name
    else:
        full_path = vault / name

    if full_path.exists():
        return {"success": False, "error": f"筆記已存在: {name}"}

    # Build content with frontmatter
    parts = []
    if tags:
        parts.append("---")
        parts.append(f"tags: {json.dumps(tags)}")
        parts.append("---")
        parts.append("")
    parts.append(content)

    full_path.write_text("\n".join(parts), encoding="utf-8")

    return {
        "success": True,
        "path": str(full_path.relative_to(vault)),
        "name": full_path.stem,
    }


def _update_note(inputs: dict) -> dict:
    """Update an existing note."""
    vault = _get_vault_path()
    note_path = inputs.get("path", inputs.get("name", ""))
    content = inputs.get("content", "")
    append = inputs.get("append", False)

    if not note_path:
        return {"success": False, "error": "path 或 name 為必填"}

    if not note_path.endswith(".md"):
        note_path += ".md"

    full_path = vault / note_path
    if not full_path.exists():
        candidates = list(vault.rglob(f"*{note_path}"))
        if candidates:
            full_path = candidates[0]
        else:
            return {"success": False, "error": f"筆記不存在: {note_path}"}

    if append:
        existing = full_path.read_text(encoding="utf-8", errors="replace")
        full_path.write_text(existing + "\n" + content, encoding="utf-8")
    else:
        full_path.write_text(content, encoding="utf-8")

    return {
        "success": True,
        "path": str(full_path.relative_to(vault)),
        "mode": "append" if append else "overwrite",
    }


def _list_notes(inputs: dict) -> dict:
    """List notes in the vault."""
    vault = _get_vault_path()
    folder = inputs.get("folder", "")
    max_results = int(inputs.get("max_results", 50))

    search_root = vault / folder if folder else vault

    notes = []
    for md_file in sorted(search_root.rglob("*.md")):
        if any(part.startswith(".") for part in md_file.relative_to(vault).parts):
            continue
        stat = md_file.stat()
        notes.append({
            "path": str(md_file.relative_to(vault)),
            "name": md_file.stem,
            "size": stat.st_size,
            "modified": stat.st_mtime,
        })
        if len(notes) >= max_results:
            break

    return {"success": True, "notes": notes, "count": len(notes)}


def _get_backlinks(inputs: dict) -> dict:
    """Find all notes that link to the specified note."""
    vault = _get_vault_path()
    note_name = inputs.get("name", "").strip()

    if not note_name:
        return {"success": False, "error": "name 為必填"}

    # Remove .md extension for link matching
    if note_name.endswith(".md"):
        note_name = note_name[:-3]

    # Pattern: [[note_name]] or [[note_name|alias]]
    pattern = re.compile(
        rf'\[\[{re.escape(note_name)}(?:\|[^\]]+)?\]\]',
        re.IGNORECASE
    )

    backlinks = []
    for md_file in vault.rglob("*.md"):
        if any(part.startswith(".") for part in md_file.relative_to(vault).parts):
            continue
        if md_file.stem.lower() == note_name.lower():
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            matches = pattern.findall(content)
            if matches:
                backlinks.append({
                    "path": str(md_file.relative_to(vault)),
                    "name": md_file.stem,
                    "link_count": len(matches),
                })
        except Exception:
            continue

    return {"success": True, "backlinks": backlinks, "count": len(backlinks)}


def _set_vault_path(inputs: dict) -> dict:
    """Set or update the Obsidian vault path."""
    vault_path = inputs.get("vault_path", "")
    if not vault_path:
        return {"success": False, "error": "vault_path 為必填"}

    p = Path(vault_path).expanduser()
    if not p.exists():
        return {"success": False, "error": f"路徑不存在: {vault_path}"}

    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(
        json.dumps({"vault_path": str(p)}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    return {"success": True, "vault_path": str(p)}


# ── Main Entry ────────────────────────────────────────────────

def run(inputs: dict) -> dict:
    """
    Obsidian skill entry point.

    inputs:
      action: search_notes | read_note | create_note | update_note |
              list_notes | get_backlinks | set_vault_path
    """
    action = inputs.get("action", "list_notes")

    handlers = {
        "search_notes": _search_notes,
        "read_note": _read_note,
        "create_note": _create_note,
        "update_note": _update_note,
        "list_notes": _list_notes,
        "get_backlinks": _get_backlinks,
        "set_vault_path": _set_vault_path,
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
        logger.error("[obsidian] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
