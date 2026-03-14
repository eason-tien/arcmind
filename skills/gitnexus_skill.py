# -*- coding: utf-8 -*-
"""
ArcMind Skill: GitNexus — Code Intelligence Bridge
=====================================================
Wraps GitNexus MCP tools as ArcMind skill actions via a persistent
MCP subprocess connection.

GitNexus indexes codebases into knowledge graphs (nodes, edges, clusters,
execution flows) and exposes 7 MCP tools for code analysis.

Actions:
  query        — 用概念搜索相關的執行流程
  context      — 360° 查看某個符號的上下游依賴
  impact       — 修改前的爆炸半徑分析
  detect       — 分析 uncommitted 改動影響
  rename       — 跨文件智能重命名 (dry_run 支持)
  list_repos   — 列出所有已索引的 repo
  reindex      — 重新索引某個 repo
  status       — 查看索引狀態

Cross-platform: macOS + Linux + Windows (需要 Node.js + npx)
"""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skills.gitnexus")

_DEFAULT_REPO = str(Path.home() / "Code" / "arcmind")


# ═══════════════════════════════════════════════════════════════════════════════
#  MCP Client — Persistent Subprocess Singleton
# ═══════════════════════════════════════════════════════════════════════════════

class _MCPClient:
    """
    Persistent MCP client that maintains a long-lived subprocess.
    Thread-safe singleton with auto-reconnect.
    """

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._request_id = 0
        self._initialized = False

    def _start(self) -> None:
        """Start the MCP subprocess and do the initialization handshake."""
        if self._proc and self._proc.poll() is None:
            return  # already running

        logger.info("[GitNexus] Starting MCP subprocess...")
        self._proc = subprocess.Popen(
            ["npx", "-y", "gitnexus@latest", "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=_DEFAULT_REPO,
        )

        # Initialize handshake
        resp = self._send_recv({
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": "init",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "arcmind", "version": "1.0"},
            },
        })

        if resp and "result" in resp:
            server_info = resp["result"].get("serverInfo", {})
            logger.info("[GitNexus] MCP connected: %s v%s",
                        server_info.get("name"), server_info.get("version"))
        else:
            logger.warning("[GitNexus] MCP init failed: %s", resp)
            return

        # Send initialized notification
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            )
            self._proc.stdin.flush()
            time.sleep(0.3)

        self._initialized = True

    def _send_recv(self, msg: dict) -> dict | None:
        """Send a JSON-RPC message and read the response."""
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            return None
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
            line = self._proc.stdout.readline()
            if line:
                return json.loads(line)
        except Exception as e:
            logger.warning("[GitNexus] send_recv error: %s", e)
            self._initialized = False
        return None

    def call_tool(self, tool_name: str, arguments: dict, timeout: int = 30) -> dict:
        """Call an MCP tool. Auto-reconnects if needed."""
        with self._lock:
            if not self._initialized or (self._proc and self._proc.poll() is not None):
                self._initialized = False
                self._start()

            if not self._initialized:
                return {"error": "GitNexus MCP not available. Is Node.js installed?"}

            self._request_id += 1
            resp = self._send_recv({
                "jsonrpc": "2.0",
                "method": "tools/call",
                "id": str(self._request_id),
                "params": {"name": tool_name, "arguments": arguments},
            })

        if not resp:
            self._initialized = False
            return {"error": "No response from GitNexus MCP"}

        if "error" in resp:
            return {"error": resp["error"]}

        # Extract text content
        result = resp.get("result", {})
        contents = result.get("content", [])
        texts = []
        for item in contents:
            if isinstance(item, dict) and item.get("text"):
                texts.append(item["text"])

        if texts:
            combined = "\n".join(texts)
            try:
                return json.loads(combined)
            except json.JSONDecodeError:
                return {"result": combined}

        return result

    def stop(self) -> None:
        """Stop the MCP subprocess."""
        with self._lock:
            if self._proc:
                self._proc.terminate()
                self._proc = None
                self._initialized = False
                logger.info("[GitNexus] MCP subprocess stopped")


# Singleton
_mcp = _MCPClient()


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _cmd_call(args: list[str], timeout: int = 15) -> str:
    """Run a GitNexus CLI command directly."""
    try:
        proc = subprocess.run(
            ["npx", "-y", "gitnexus@latest"] + args,
            capture_output=True, text=True, timeout=timeout,
            cwd=_DEFAULT_REPO,
        )
        return proc.stdout.strip() or proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return f"Command timeout ({timeout}s)"
    except Exception as e:
        return str(e)


# ═══════════════════════════════════════════════════════════════════════════════
#  Actions
# ═══════════════════════════════════════════════════════════════════════════════

def _query(inputs: dict) -> dict:
    """Search the knowledge graph for execution flows."""
    query = inputs.get("query", "")
    repo = inputs.get("repo", "arcmind")
    if not query:
        return {"error": "query is required"}
    return _mcp.call_tool("query", {"query": query, "repo": repo})


def _context(inputs: dict) -> dict:
    """360° view of a symbol — callers, callees, processes."""
    name = inputs.get("name", "")
    repo = inputs.get("repo", "arcmind")
    if not name:
        return {"error": "name is required (function/class name)"}
    return _mcp.call_tool("context", {"name": name, "repo": repo})


def _impact(inputs: dict) -> dict:
    """Blast radius analysis before modifying a symbol."""
    target = inputs.get("target", "")
    direction = inputs.get("direction", "upstream")
    repo = inputs.get("repo", "arcmind")
    if not target:
        return {"error": "target symbol name is required"}
    return _mcp.call_tool("impact", {
        "target": target, "direction": direction, "repo": repo
    })


def _detect_changes(inputs: dict) -> dict:
    """Analyze uncommitted changes and blast radius."""
    scope = inputs.get("scope", "all")
    repo = inputs.get("repo", "arcmind")
    return _mcp.call_tool("detect_changes", {"scope": scope, "repo": repo})


def _rename(inputs: dict) -> dict:
    """Multi-file rename using the knowledge graph."""
    symbol = inputs.get("symbol_name", "")
    new_name = inputs.get("new_name", "")
    dry_run = inputs.get("dry_run", True)
    repo = inputs.get("repo", "arcmind")
    if not symbol or not new_name:
        return {"error": "symbol_name and new_name required"}
    return _mcp.call_tool("rename", {
        "symbol_name": symbol, "new_name": new_name,
        "dry_run": dry_run, "repo": repo,
    })


def _list_repos(inputs: dict) -> dict:
    """List all indexed repositories."""
    return _mcp.call_tool("list_repos", {})


def _reindex(inputs: dict) -> dict:
    """Re-index a repository."""
    repo_path = inputs.get("repo_path", _DEFAULT_REPO)
    force = inputs.get("force", False)
    args = ["analyze", repo_path]
    if force:
        args.append("--force")
    output = _cmd_call(args, timeout=60)
    return {"output": output, "repo_path": repo_path}


def _status(inputs: dict) -> dict:
    """Check GitNexus index status."""
    output = _cmd_call(["status"], timeout=10)
    info: dict[str, Any] = {"raw": output}
    for line in output.split("\n"):
        line = line.strip()
        if ":" in line:
            key, val = line.split(":", 1)
            info[key.strip().lower().replace(" ", "_")] = val.strip()
    meta_path = Path(_DEFAULT_REPO) / ".gitnexus" / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            info["stats"] = meta.get("stats", {})
        except Exception:
            pass
    return info


# ═══════════════════════════════════════════════════════════════════════════════
#  Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

_ACTIONS = {
    "query": _query,
    "context": _context,
    "impact": _impact,
    "detect": _detect_changes,
    "rename": _rename,
    "list_repos": _list_repos,
    "reindex": _reindex,
    "status": _status,
}


def run(inputs: dict) -> dict:
    """
    GitNexus — 代碼智慧引擎。

    知識圖譜查詢:
      query        — 搜索執行流程 (query=搜索詞)
      context      — 符號 360° 視圖 (name=函數/類名)
      impact       — 爆炸半徑分析 (target=符號名, direction=upstream|downstream)

    變更分析:
      detect       — uncommitted 改動影響 (scope=all|compare)
      rename       — 智能重命名 (symbol_name=舊名, new_name=新名, dry_run=true)

    管理:
      list_repos   — 列出已索引 repo
      reindex      — 重新索引 (repo_path=路徑, force=false)
      status       — 索引狀態
    """
    action = inputs.get("action", "")
    handler = _ACTIONS.get(action)
    if not handler:
        return {"error": f"Unknown action: {action}", "available": list(_ACTIONS.keys())}
    try:
        return handler(inputs)
    except Exception as e:
        logger.error("[GitNexus] %s failed: %s", action, e)
        return {"error": str(e), "action": action}
