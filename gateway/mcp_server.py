# -*- coding: utf-8 -*-
"""
ArcMind MCP Server — 對外暴露安全工具給外部 AI Agent。

P3-1: 使用 FastMCP 建立 MCP Server，白名單機制控制哪些工具可暴露。
掛載到 FastAPI `/mcp` 路徑，讓外部 MCP Client 連接。

無硬依賴：未安裝 `mcp` 時返回 None。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("arcmind.gateway.mcp_server")

# ── 白名單：只暴露安全的工具 ──────────────────────────────────────────────
_SAFE_TOOLS = {
    "web_search",
    "remember",
    "recall",
    "read_file",
    "list_directory",
}


def create_mcp_server():
    """
    Create a FastMCP server instance exposing ArcMind's safe tools.
    Returns None if mcp is not installed.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        logger.info("[MCPServer] mcp package not installed — MCP Server disabled")
        return None

    mcp = FastMCP(
        "ArcMind",
        json_response=True,
    )

    # ── Register hardcoded whitelisted tools ─────────────────────────────
    _register_safe_tools(mcp)

    # ── P4-3: Dynamic tool discovery from ToolRegistry ──────────────────
    _registered_names = {"web_search", "remember", "recall", "read_file", "list_directory"}
    dynamic_count = _register_dynamic_tools(mcp, _registered_names)

    total = len(_registered_names) + dynamic_count
    logger.info("[MCPServer] Created with %d tools exposed (%d hardcoded + %d dynamic)",
                total, len(_registered_names), dynamic_count)
    return mcp


def _register_dynamic_tools(mcp, already_registered: set) -> int:
    """
    Dynamically discover tools from ToolRegistry and register whitelisted ones.
    Returns count of dynamically registered tools.
    """
    count = 0
    try:
        from runtime.tool_loop import tool_registry
        for tool_name in tool_registry.list_tool_names():
            if tool_name in already_registered:
                continue
            if tool_name not in _SAFE_TOOLS:
                continue

            # Create a generic wrapper
            _name = tool_name  # capture for closure

            @mcp.tool(name=_name)
            def _dynamic_tool(input_text: str = "", _tool_name: str = _name) -> str:
                f"""Execute ArcMind tool: {_tool_name}"""
                try:
                    from runtime.tool_loop import tool_registry as _reg
                    handler = _reg.get_handler(_tool_name)
                    if handler:
                        return str(handler(input_text=input_text))
                    return f"{_tool_name} not available"
                except Exception as e:
                    return f"Error: {e}"

            count += 1
            already_registered.add(tool_name)
    except Exception as e:
        logger.debug("[MCPServer] Dynamic tool discovery skipped: %s", e)

    return count


def _register_safe_tools(mcp) -> None:
    """Register whitelisted tools from ToolRegistry into the MCP server."""

    # ── web_search ──────────────────────────────────────────────────────
    @mcp.tool()
    def web_search(query: str, max_results: int = 5) -> str:
        """Search the web for information. Returns search results as text."""
        try:
            from runtime.tool_loop import tool_registry
            handler = tool_registry.get_handler("web_search")
            if handler:
                return handler(query=query, max_results=max_results, mode="fast")
            return "web_search tool not available"
        except Exception as e:
            return f"Error: {e}"

    # ── remember ────────────────────────────────────────────────────────
    @mcp.tool()
    def remember(content: str, tags: str = "") -> str:
        """Store information in ArcMind's long-term memory."""
        try:
            from runtime.tool_loop import tool_registry
            handler = tool_registry.get_handler("remember")
            if handler:
                tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
                return handler(content=content, tags=tag_list)
            return "remember tool not available"
        except Exception as e:
            return f"Error: {e}"

    # ── recall ──────────────────────────────────────────────────────────
    @mcp.tool()
    def recall(query: str, top_k: int = 5) -> str:
        """Search ArcMind's long-term memory for relevant information."""
        try:
            from runtime.tool_loop import tool_registry
            handler = tool_registry.get_handler("recall")
            if handler:
                return handler(query=query, top_k=top_k)
            return "recall tool not available"
        except Exception as e:
            return f"Error: {e}"

    # ── read_file ───────────────────────────────────────────────────────
    @mcp.tool()
    def read_file(path: str, max_lines: int = 200) -> str:
        """Read a file's contents (limited to safe directories)."""
        try:
            from runtime.tool_loop import tool_registry
            handler = tool_registry.get_handler("read_file")
            if handler:
                return handler(path=path, max_lines=max_lines)
            return "read_file tool not available"
        except Exception as e:
            return f"Error: {e}"

    # ── list_directory ──────────────────────────────────────────────────
    @mcp.tool()
    def list_directory(path: str = ".") -> str:
        """List files in a directory."""
        try:
            from runtime.tool_loop import tool_registry
            handler = tool_registry.get_handler("list_directory")
            if handler:
                return handler(path=path)
            return "list_directory tool not available"
        except Exception as e:
            return f"Error: {e}"


# ── Agent Card (A2A Protocol) ───────────────────────────────────────────────

def get_agent_card(host: str = "localhost", port: int = 8000) -> dict:
    """
    Generate A2A Agent Card for ArcMind.
    Spec: https://google.github.io/A2A/specification/
    """
    try:
        from version import __version__
        version = __version__
    except Exception:
        version = "0.9.5"

    return {
        "name": "ArcMind",
        "description": "Situated AI Agent with OODA-based reasoning, multi-agent orchestration, and comprehensive tool ecosystem.",
        "url": f"http://{host}:{port}",
        "version": version,
        "protocol_version": "0.1",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        },
        "authentication": {
            "schemes": ["bearer"],
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": [
            {
                "id": "web_search",
                "name": "Web Search",
                "description": "Search the web for real-time information",
                "tags": ["search", "web", "information"],
                "examples": ["Search for latest AI news", "What is MCP protocol?"],
            },
            {
                "id": "memory",
                "name": "Memory Management",
                "description": "Store and retrieve information from long-term memory",
                "tags": ["memory", "knowledge", "storage"],
                "examples": ["Remember this fact", "Recall information about X"],
            },
            {
                "id": "code_execution",
                "name": "Code Execution",
                "description": "Execute code and shell commands (restricted)",
                "tags": ["code", "execution", "development"],
                "examples": ["Run a Python script", "List directory contents"],
            },
            {
                "id": "task_management",
                "name": "Task Management",
                "description": "Create and manage multi-step PM tasks",
                "tags": ["task", "project", "management"],
                "examples": ["Build a web scraper", "Analyze this codebase"],
            },
        ],
    }
