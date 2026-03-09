# -*- coding: utf-8 -*-
"""ArcMind version — single source of truth (reads from VERSION file)."""
from pathlib import Path

_VERSION_FILE = Path(__file__).parent / "VERSION"

try:
    __version__ = _VERSION_FILE.read_text().strip()
except Exception:
    __version__ = "0.0.0"
