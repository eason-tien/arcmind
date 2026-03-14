# -*- coding: utf-8 -*-
"""
ArcMind Persona — Loader
==========================
OpenClaw 風格的分層人格載入器。

載入三個核心人格檔案：
- SOUL.md     — 身份/個性/核心價值觀
- AGENTS.md   — 行為規則/操作指南
- TOOLS.md    — 環境/工具/能力描述

支持運行時熱更新：檔案變更自動生效。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.persona.loader")


class PersonaLoader:
    """
    Load and manage personality layer files.
    OpenClaw-style: SOUL + AGENTS + TOOLS layered injection.
    """

    # Default persona file names
    PERSONA_FILES = {
        "soul": "SOUL.md",
        "soul_compact": "SOUL_COMPACT.md",
        "agents": "AGENTS.md",
        "tools": "TOOLS.md",
        "user": "USER.md",           # Optional: user preferences
        "identity": "IDENTITY.md",   # Optional: compact identity
    }

    def __init__(self, persona_dir: Path | str | None = None):
        if persona_dir is None:
            # Default: project root
            persona_dir = Path(__file__).parent.parent
        self.persona_dir = Path(persona_dir)
        self._cache: dict[str, str] = {}
        self._mtimes: dict[str, float] = {}
        logger.info("[PersonaLoader] dir=%s", self.persona_dir)

    def load(self, name: str) -> str:
        """
        Load a persona file by name (e.g., 'soul', 'agents', 'tools').
        Returns empty string if file doesn't exist.
        Caches content and auto-reloads on file change.
        """
        filename = self.PERSONA_FILES.get(name, f"{name.upper()}.md")
        filepath = self.persona_dir / filename

        if not filepath.exists():
            return ""

        # Check mtime for hot-reload
        current_mtime = filepath.stat().st_mtime
        cached_mtime = self._mtimes.get(name, 0)

        if name in self._cache and current_mtime == cached_mtime:
            return self._cache[name]

        # Load / reload
        try:
            content = filepath.read_text(encoding="utf-8").strip()
            self._cache[name] = content
            self._mtimes[name] = current_mtime
            logger.info("[PersonaLoader] loaded %s (%d chars)", filename, len(content))
            return content
        except Exception as e:
            logger.warning("[PersonaLoader] failed to load %s: %s", filename, e)
            return ""

    def load_all(self) -> dict[str, str]:
        """Load all persona files."""
        result = {}
        for name in self.PERSONA_FILES:
            content = self.load(name)
            if content:
                result[name] = content
        return result

    def get_soul(self, compact: bool = False) -> str:
        if compact:
            result = self.load("soul_compact")
            if result:
                return result
        return self.load("soul")

    def get_agents(self) -> str:
        return self.load("agents")

    def get_tools(self) -> str:
        return self.load("tools")

    def get_user(self) -> str:
        return self.load("user")

    def status(self) -> dict:
        loaded = {k: len(v) for k, v in self._cache.items()}
        return {
            "persona_dir": str(self.persona_dir),
            "loaded_files": loaded,
            "total_chars": sum(loaded.values()),
        }


# ── Singleton ──
persona_loader = PersonaLoader()
