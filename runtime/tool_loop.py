# -*- coding: utf-8 -*-
"""
ArcMind — Agentic Tool Execution Loop
========================================
OpenClaw 的核心執行力來源：Tool Loop。

當 LLM 回傳 tool_use 時，系統：
1. 解析 tool_use block
2. 查找對應的 tool 執行函數
3. 執行 tool，收集結果
4. 把 tool_result 加入 messages，再次呼叫 LLM
5. 重複直到 LLM 產生文字回應（stop_reason != "tool_use"）

這就是為什麼 OpenClaw 有「執行力」而 ARCHILLX 沒有：
ARCHILLX = 單次 LLM → 文字
OpenClaw = LLM ↔ Tool Loop → 最終文字
"""
from __future__ import annotations

import json
import os
import re
import logging
import subprocess
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("arcmind.tool_loop")

# V3.1: Thread-local storage for current agent identity (skill ACL)
_thread_ctx = threading.local()


def set_caller_agent(agent_id: str | None) -> None:
    """Set the current agent identity for skill ACL in this thread."""
    _thread_ctx.caller_agent = agent_id


def get_caller_agent() -> str | None:
    """Get the current agent identity for skill ACL."""
    return getattr(_thread_ctx, "caller_agent", None)


def _parse_xml_tool_calls(text: str) -> list[dict]:
    """
    Parse MiniMax-style XML tool calls from LLM text output.
    MiniMax-M2.5 sometimes emits tool calls as XML instead of using
    the OpenAI function calling API:

        <minimax:tool_call>
        <invoke name="run_command">
        <parameter name="command">whoami</parameter>
        </invoke>
        </minimax:tool_call>

    Also handles [TOOL_CALL] blocks:
        [TOOL_CALL]
        {tool => "run_command", args => { --command "whoami" }}
        [/TOOL_CALL]
    """
    results = []

    # Pattern 1: <minimax:tool_call> XML format
    for match in re.finditer(
        r'<minimax:tool_call>\s*<invoke\s+name="([^"]+)">(.*?)</invoke>\s*</minimax:tool_call>',
        text, re.DOTALL
    ):
        tool_name = match.group(1)
        params_block = match.group(2)
        params = {}
        for pm in re.finditer(
            r'<parameter\s+name="([^"]+)">(.*?)</parameter>',
            params_block, re.DOTALL
        ):
            params[pm.group(1)] = pm.group(2).strip()
        results.append({
            "id": f"xml_{tool_name}_{len(results)}",
            "name": tool_name,
            "input": params,
        })

    # Pattern 2: [TOOL_CALL] block format
    for match in re.finditer(
        r'\[TOOL_CALL\]\s*\{tool\s*=>\s*"([^"]+)",\s*args\s*=>\s*\{(.*?)\}\}\s*\[/TOOL_CALL\]',
        text, re.DOTALL
    ):
        tool_name = match.group(1)
        args_str = match.group(2).strip()
        params = {}
        for pm in re.finditer(r'--(\w+)\s+"([^"]*)"', args_str):
            params[pm.group(1)] = pm.group(2)
        if params:
            results.append({
                "id": f"block_{tool_name}_{len(results)}",
                "name": tool_name,
                "input": params,
            })

    if results:
        logger.info("[AgenticLoop] Parsed %d XML/block tool calls from text", len(results))
    return results


# ── Tool Definitions ─────────────────────────────────────────────────────────

class ToolRegistry:
    """
    Registry of executable tools that the LLM can invoke.
    Maps tool names → execution functions.
    """

    def __init__(self):
        self._tools: dict[str, dict] = {}  # name → {schema, handler}
        self._register_builtin_tools()

    def register(self, name: str, description: str,
                 input_schema: dict, handler: Callable) -> None:
        """Register a tool."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "input_schema": input_schema,
            "handler": handler,
        }
        logger.info("[ToolRegistry] registered: %s", name)

    def get_handler(self, name: str) -> Callable | None:
        tool = self._tools.get(name)
        return tool["handler"] if tool else None

    def get_schemas(self) -> list[dict]:
        """Get tool schemas for LLM API call."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in self._tools.values()
        ]

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def _register_builtin_tools(self) -> None:
        """Register built-in tools available to the agent."""

        # ── Web Search (V3.2: multi-engine + deep + research) ──────────
        self.register(
            name="web_search",
            description=(
                "Search the web for information. Three modes available:\n"
                "- mode='fast' (default): quick search, returns snippets only\n"
                "- mode='deep': reads full page content from top results\n"
                "- mode='research': multi-round search with LLM query rewriting, "
                "full page reading, and synthesized analysis report (best for solving problems)\n"
                "Use 'research' when you need to deeply investigate an issue or error.\n"
                "Use 'extract_urls' to read specific web pages without searching."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query keywords",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 5)",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["fast", "deep", "research"],
                        "description": "fast=snippets, deep=full pages, research=multi-round analysis",
                    },
                    "extract_urls": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Read content from specific URLs (skips search)",
                    },
                    "rewrite": {
                        "type": "boolean",
                        "description": "Use LLM to rewrite query for better results (default: auto)",
                    },
                },
                "required": ["query"],
            },
            handler=_tool_web_search,
        )

        # ── Shell Command ─────────────────────────────────────────────
        self.register(
            name="run_command",
            description="Execute a shell command on the local system. Returns stdout and stderr.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30)",
                    },
                },
                "required": ["command"],
            },
            handler=_tool_run_command,
        )

        # ── File Read ─────────────────────────────────────────────────
        self.register(
            name="read_file",
            description="Read the contents of a file from the filesystem.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute or relative file path",
                    },
                },
                "required": ["path"],
            },
            handler=_tool_read_file,
        )

        # ── File Write ────────────────────────────────────────────────
        self.register(
            name="write_file",
            description="Write content to a file. Creates the file if it doesn't exist.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to write",
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write",
                    },
                },
                "required": ["path", "content"],
            },
            handler=_tool_write_file,
        )

        # ── Execute Python ───────────────────────────────────────────
        self.register(
            name="execute_python",
            description="Execute Python code directly. Runs in a subprocess with project PYTHONPATH. Returns stdout/stderr. Use for data processing, calculations, scripting.",
            input_schema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 60, max 300)",
                    },
                },
                "required": ["code"],
            },
            handler=_tool_execute_python,
        )

        # ── Execute Shell ────────────────────────────────────────────
        self.register(
            name="execute_shell",
            description="Execute a shell command with full shell features: pipes (|), redirects (>, >>), chaining (&&, ||), subshells, etc. Use this instead of run_command when you need shell features.",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command (supports pipes, redirects, &&, etc)",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 60, max 300)",
                    },
                },
                "required": ["command"],
            },
            handler=_tool_execute_shell,
        )

        # ── Execute Node.js ──────────────────────────────────────────
        self.register(
            name="execute_node",
            description="Execute Node.js/JavaScript code directly. Runs via node. Use for JS scripting, npm tasks, web scraping helpers.",
            input_schema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "JavaScript/Node.js code to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 60, max 300)",
                    },
                },
                "required": ["code"],
            },
            handler=_tool_execute_node,
        )

        # ── Edit File (patch-style) ──────────────────────────────────
        self.register(
            name="edit_file",
            description="Patch-style file editing: find a text pattern and replace it. More precise than write_file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to edit",
                    },
                    "find": {
                        "type": "string",
                        "description": "Text to find (exact match, supports multi-line)",
                    },
                    "replace": {
                        "type": "string",
                        "description": "Replacement text",
                    },
                },
                "required": ["path", "find", "replace"],
            },
            handler=_tool_edit_file,
        )

        # ── Search Code ──────────────────────────────────────────────
        self.register(
            name="search_code",
            description="Search for text across project files using grep. Returns matching lines with file paths and line numbers.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text/pattern to search for",
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: project root)",
                    },
                    "file_pattern": {
                        "type": "string",
                        "description": "File glob pattern, e.g. '*.py' (default: common code files)",
                    },
                },
                "required": ["query"],
            },
            handler=_tool_search_code,
        )

        # ── Fetch URL ────────────────────────────────────────────────
        self.register(
            name="fetch_url",
            description="Fetch web page content and return as readable text. Strips HTML tags. Useful for reading docs, APIs, articles.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch",
                    },
                },
                "required": ["url"],
            },
            handler=_tool_fetch_url,
        )

        # ── Send Notification ────────────────────────────────────────
        self.register(
            name="send_notification",
            description="Send a notification message to the user via Telegram.",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Message text to send",
                    },
                },
                "required": ["message"],
            },
            handler=_tool_send_notification,
        )

        # ── Create Directory ─────────────────────────────────────────
        self.register(
            name="create_directory",
            description="Create a directory (including parent directories if needed).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to create",
                    },
                },
                "required": ["path"],
            },
            handler=_tool_create_directory,
        )

        # ── Delete File ──────────────────────────────────────────────
        self.register(
            name="delete_file",
            description="Delete a file or directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to delete",
                    },
                },
                "required": ["path"],
            },
            handler=_tool_delete_file,
        )

        # ── Move File ────────────────────────────────────────────────
        self.register(
            name="move_file",
            description="Move or rename a file/directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Source path",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Destination path",
                    },
                },
                "required": ["source", "destination"],
            },
            handler=_tool_move_file,
        )

        # ── Copy File ────────────────────────────────────────────────
        self.register(
            name="copy_file",
            description="Copy a file or directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "Source path",
                    },
                    "destination": {
                        "type": "string",
                        "description": "Destination path",
                    },
                },
                "required": ["source", "destination"],
            },
            handler=_tool_copy_file,
        )

        # ── Apply Patch ──────────────────────────────────────────────
        self.register(
            name="apply_patch",
            description="Apply a unified diff patch to a file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to patch"},
                    "patch": {"type": "string", "description": "Unified diff content"},
                },
                "required": ["path", "patch"],
            },
            handler=_tool_apply_patch,
        )

        # ── Append File ──────────────────────────────────────────────
        self.register(
            name="append_file",
            description="Append content to end of a file (creates if not exists).",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "Content to append"},
                },
                "required": ["path", "content"],
            },
            handler=_tool_append_file,
        )

        # ── File Info ────────────────────────────────────────────────
        self.register(
            name="file_info",
            description="Get file/directory metadata: size, permissions, timestamps, type.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File or directory path"},
                },
                "required": ["path"],
            },
            handler=_tool_file_info,
        )

        # ── Get System Info ──────────────────────────────────────────
        self.register(
            name="get_system_info",
            description="Get system information: OS, hostname, CPU, memory, disk, Python version.",
            input_schema={"type": "object", "properties": {}},
            handler=_tool_get_system_info,
        )

        # ── HTTP Request ─────────────────────────────────────────────
        self.register(
            name="http_request",
            description="Make an HTTP request (GET/POST/PUT/DELETE/PATCH). Returns status, headers, body. Useful for API calls.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Request URL"},
                    "method": {"type": "string", "description": "HTTP method (default: GET)"},
                    "headers": {"type": "object", "description": "Request headers (optional)"},
                    "body": {"type": "string", "description": "Request body (optional)"},
                },
                "required": ["url"],
            },
            handler=_tool_http_request,
        )

        # ── Screenshot ───────────────────────────────────────────────
        self.register(
            name="screenshot",
            description="Take a screenshot of the current screen (macOS). Saves to /tmp/.",
            input_schema={"type": "object", "properties": {}},
            handler=_tool_screenshot,
        )

        # ── Generate Image ───────────────────────────────────────────
        self.register(
            name="generate_image",
            description="Generate an image using DALL-E API from a text prompt.",
            input_schema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Image description prompt"},
                    "output_path": {"type": "string", "description": "Save path (optional, default: /tmp/)"},
                },
                "required": ["prompt"],
            },
            handler=_tool_generate_image,
        )

        # ── Read PDF ─────────────────────────────────────────────────
        self.register(
            name="read_pdf",
            description="Read and extract text content from a PDF file.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "PDF file path"},
                },
                "required": ["path"],
            },
            handler=_tool_read_pdf,
        )

        # ── Cron Manage ──────────────────────────────────────────────
        self.register(
            name="cron_manage",
            description="Manage ArcMind scheduled tasks. Actions: list, status.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action: list, status"},
                },
                "required": ["action"],
            },
            handler=_tool_cron_manage,
        )

        # ── Session Status ───────────────────────────────────────────
        self.register(
            name="session_status",
            description="Get current ArcMind session status: active sessions, tool count, uptime.",
            input_schema={"type": "object", "properties": {}},
            handler=_tool_session_status,
        )

        # ── LLM Task ─────────────────────────────────────────────────
        self.register(
            name="llm_task",
            description="Run a sub-LLM task: send a prompt for summarization, translation, analysis, etc.",
            input_schema={
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Task prompt for the LLM"},
                    "model": {"type": "string", "description": "Model override (optional)"},
                },
                "required": ["task"],
            },
            handler=_tool_llm_task,
        )

        # ── Browser Action ───────────────────────────────────────────
        self.register(
            name="browser_action",
            description="Browser automation via Chrome CDP: navigate, get_text, screenshot.",
            input_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action: navigate, get_text, screenshot"},
                    "url": {"type": "string", "description": "URL for navigate action"},
                    "selector": {"type": "string", "description": "CSS selector (optional)"},
                    "text": {"type": "string", "description": "Text for type action (optional)"},
                },
                "required": ["action"],
            },
            handler=_tool_browser_action,
        )

        # ── List Directory ────────────────────────────────────────────
        self.register(
            name="list_directory",
            description="List files and subdirectories in a directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list",
                    },
                },
                "required": ["path"],
            },
            handler=_tool_list_directory,
        )

        # ── Python Eval ───────────────────────────────────────────────
        self.register(
            name="python_eval",
            description="Evaluate a Python expression or short script. Returns the result.",
            input_schema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to evaluate",
                    },
                },
                "required": ["code"],
            },
            handler=_tool_python_eval,
        )

        # ── Memory Query (MGIS) ──────────────────────────────────────
        self.register(
            name="memory_query",
            description="Query ArcMind's long-term memory (MGIS) for relevant information.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Memory search query",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of results (default 3)",
                    },
                },
                "required": ["query"],
            },
            handler=_tool_memory_query,
        )

        # ── Memory Save ─────────────────────────────────────────────
        self.register(
            name="memory_save",
            description=(
                "Save important information to long-term memory. "
                "Use this when the user says '記住', 'remember', or when you discover "
                "important facts, user preferences, or lessons learned that should be "
                "retained across sessions. Types: semantic (knowledge/preferences), "
                "procedural (how-to/patterns), causal (cause-effect relationships)."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The information to save",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["semantic", "procedural", "causal"],
                        "description": "Memory type (default: semantic)",
                    },
                    "importance": {
                        "type": "number",
                        "description": "Importance 0.0-1.0 (default: 0.7, user preferences should be 0.9)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for categorization",
                    },
                },
                "required": ["content"],
            },
            handler=_tool_memory_save,
        )

        # ── Agent management tools ──
        self.register(
            name="list_agents",
            description="列出所有已配置的 Agent（子模型）。",
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=_tool_list_agents,
        )
        self.register(
            name="add_agent",
            description="添加一個新的子 Agent。需要 id、name、model、purpose、capabilities。",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "Agent ID (英文，如 translate、design)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Agent 顯示名稱",
                    },
                    "model": {
                        "type": "string",
                        "description": "模型 (如 ollama:qwen3:8b 或 custom:MiniMax-M2.5)",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Agent 用途描述",
                    },
                    "capabilities": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "能力標籤列表 (如 ['translate', 'language'])",
                    },
                    "system_prompt": {
                        "type": "string",
                        "description": "Agent 的 system prompt (可選)",
                    },
                },
                "required": ["agent_id", "name", "model", "purpose", "capabilities"],
            },
            handler=_tool_add_agent,
        )
        self.register(
            name="remove_agent",
            description="移除一個子 Agent（不能移除 MAIN）。",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "要移除的 Agent ID",
                    },
                },
                "required": ["agent_id"],
            },
            handler=_tool_remove_agent,
        )

        # ── Agent delegation tools — CEO 委派任務給子 Agent ──
        self.register(
            name="delegate_task",
            description=(
                "CEO 委派任務給子 Agent。用於將耗時任務（搜尋、寫代碼、分析、測試）"
                "交給專業 Agent 在背景處理。任務會在 Heartbeat 排程中自動執行。\n"
                "可用 Agent: search(搜尋), code(寫代碼), analysis(分析), "
                "qa(測試), devops(部署), pm(需求分析), windows(遠端操作)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "assignee": {
                        "type": "string",
                        "description": "Agent ID: search, code, analysis, qa, devops, pm, windows",
                    },
                    "title": {
                        "type": "string",
                        "description": "任務標題（簡短描述）",
                    },
                    "task_data": {
                        "type": "object",
                        "description": "任務詳細內容和指示",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "優先級 (預設 medium)",
                    },
                },
                "required": ["assignee", "title"],
            },
            handler=_tool_delegate_task,
        )
        self.register(
            name="delegate_pipeline",
            description=(
                "CEO 建立多 Agent 協作 Pipeline。多個 Agent 按順序執行，"
                "每步結果自動傳遞給下一步。適合複雜任務如：先調研 → 再開發 → 再測試。\n"
                "最多 5 個步驟。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Pipeline 總標題",
                    },
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "assignee": {
                                    "type": "string",
                                    "description": "Agent ID",
                                },
                                "instruction": {
                                    "type": "string",
                                    "description": "這一步的具體指示",
                                },
                            },
                            "required": ["assignee", "instruction"],
                        },
                        "description": "按順序執行的步驟列表",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "優先級",
                    },
                },
                "required": ["title", "steps"],
            },
            handler=_tool_delegate_pipeline,
        )
        self.register(
            name="agent_inbox",
            description="查看 CEO 的收件箱 — 顯示子 Agent 回報的任務完成、升級、交接等訊息。",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "最多顯示幾筆 (預設 10)",
                    },
                },
            },
            handler=_tool_agent_inbox,
        )

        # ── Skill invocation — 讓 Agent 呼叫任何已註冊的 skill ──
        self.register(
            name="invoke_skill",
            description=(
                "Invoke a registered ArcMind skill by name. "
                "Use get_skill_info(skill_name) first to see usage and available actions. "
                "Use list_skills to see all available skill names. "
                "The 'inputs' object is passed directly to the skill handler."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill to invoke",
                    },
                    "inputs": {
                        "type": "object",
                        "description": "Input parameters for the skill (usually includes an 'action' field)",
                    },
                },
                "required": ["skill_name", "inputs"],
            },
            handler=_tool_invoke_skill,
        )

        self.register(
            name="list_skills",
            description="List all available ArcMind skills with brief descriptions.",
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=_tool_list_skills,
        )
        self.register(
            name="get_skill_info",
            description=(
                "Get detailed usage info for a specific skill: "
                "description, setup requirements, example usage, and available actions. "
                "Call this BEFORE invoke_skill to learn how to use a skill."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill to get info for",
                    },
                },
                "required": ["skill_name"],
            },
            handler=_tool_get_skill_info,
        )


        # ── Agent Template Library — 聘用/解僱 Agent ─────────────────────
        self.register(
            name="hire_agent",
            description=(
                "從模板庫聘用新 Agent。可用模板：security(安全), data_engineer(數據), "
                "frontend(前端), designer(UI/UX), copywriter(文案), "
                "financial(財務), translator(翻譯), sre(可靠性)。\n"
                "聘用後 Agent 可接受委派任務。不預裝，按需聘用。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "template_id": {
                        "type": "string",
                        "description": "模板 ID: security, data_engineer, frontend, designer, copywriter, financial, translator, sre",
                    },
                    "custom_model": {
                        "type": "string",
                        "description": "自訂模型 (可選，預設用模板定義的模型)",
                    },
                },
                "required": ["template_id"],
            },
            handler=_tool_hire_agent,
        )
        self.register(
            name="fire_agent",
            description="解僱已聘用的非核心 Agent。核心 Agent (main/search/analysis/code/qa/devops/pm/windows) 不可解僱。",
            input_schema={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "要解僱的 Agent ID",
                    },
                },
                "required": ["agent_id"],
            },
            handler=_tool_fire_agent,
        )
        self.register(
            name="list_agent_templates",
            description="列出所有可用的 Agent 模板及聘用狀態。CEO 用此了解可聘用的專業人才。",
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=_tool_list_agent_templates,
        )

        # ── Agent Handoff — Agent 之間任務交接 ────────────────────────────
        self.register(
            name="agent_handoff",
            description=(
                "Agent 任務交接 — 將任務從一個 Agent 轉移給另一個 Agent。\n"
                "交接會保留上下文，確保接收方能繼續執行。\n"
                "透過 EventBus AGENT_HANDOFF 事件處理。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "from_agent": {
                        "type": "string",
                        "description": "交出方 Agent ID",
                    },
                    "to_agent": {
                        "type": "string",
                        "description": "接收方 Agent ID",
                    },
                    "command": {
                        "type": "string",
                        "description": "要交接的任務指令",
                    },
                    "reason": {
                        "type": "string",
                        "description": "交接原因",
                    },
                    "context": {
                        "type": "object",
                        "description": "交接上下文（先前結果等）",
                    },
                },
                "required": ["from_agent", "to_agent", "command"],
            },
            handler=_tool_agent_handoff,
        )

        # ── Webhook — 主動發送 Webhook ────────────────────────────────────
        self.register(
            name="send_webhook",
            description="主動發送 Webhook 到外部服務（N8N、Zapier 等）。用於通知外部系統任務完成或觸發外部工作流。",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "目標 URL",
                    },
                    "payload": {
                        "type": "object",
                        "description": "JSON payload",
                    },
                    "method": {
                        "type": "string",
                        "enum": ["POST", "PUT", "PATCH"],
                        "description": "HTTP method (預設 POST)",
                    },
                },
                "required": ["url"],
            },
            handler=_tool_send_webhook,
        )

        # ── Task Planner — 任務規劃與分工 ─────────────────────────────────
        self.register(
            name="plan_task",
            description="""任務規劃工具。收到複雜需求時，用這個工具將需求拆解為多步驟執行計畫。
每個步驟會指定負責的 Agent、具體指令和驗收標準。
適合用於：多步驟任務、需要多個 Agent 協作的工作、複雜的開發/調研/分析需求。
簡單的單一問答或閒聊不需要使用此工具。""",
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "需要規劃的目標或需求描述",
                    },
                },
                "required": ["goal"],
            },
            handler=_tool_plan_task,
        )
        self.register(
            name="execute_plan",
            description="執行已規劃好的任務計畫。需要提供 plan_id（由 plan_task 工具回傳）。會按步驟順序委派給子 Agent 執行，每步結果傳遞給下一步。",
            input_schema={
                "type": "object",
                "properties": {
                    "plan_id": {
                        "type": "string",
                        "description": "由 plan_task 回傳的 plan_id",
                    },
                },
                "required": ["plan_id"],
            },
            handler=_tool_execute_plan,
        )

        # ── System Management — 重啟 & 健康檢查 ─────────────────────────
        self.register(
            name="restart_arcmind",
            description=(
                "Restart the ArcMind server. Performs a graceful shutdown; "
                "the macOS LaunchAgent will automatically restart the process. "
                "Use when: configuration changes need to take effect, "
                "the system is unstable, or after installing new dependencies."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Reason for restart (logged for audit)",
                    },
                    "delay_seconds": {
                        "type": "integer",
                        "description": "Seconds to wait before restarting (default 3)",
                    },
                },
                "required": ["reason"],
            },
            handler=_tool_restart_arcmind,
        )

        self.register(
            name="preflight_check",
            description=(
                "Run ArcMind pre-flight diagnostics without restarting. "
                "Checks: PID lock, port availability, JSON configs, imports, "
                "log sizes, .env file, and critical files."
            ),
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=_tool_preflight_check,
        )

        # ── Harness — 長時間任務編排 ────────────────────────────────────
        try:
            from runtime.harness_tool import HARNESS_TOOL_SCHEMAS
            for tool_name, spec in HARNESS_TOOL_SCHEMAS.items():
                self.register(
                    name=tool_name,
                    description=spec["description"],
                    input_schema=spec["input_schema"],
                    handler=spec["handler"],
                )
        except Exception as e:
            logger.warning("[ToolRegistry] Harness tools not loaded: %s", e)

        # ── P2-1: MCP Servers — 自動連線 ────────────────────────────────
        try:
            from runtime.mcp_client import mcp_client_manager
            import asyncio
            configs = mcp_client_manager.load_config()
            if configs:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.ensure_future(mcp_client_manager.connect_all())
                    else:
                        loop.run_until_complete(mcp_client_manager.connect_all())
                except RuntimeError:
                    asyncio.run(mcp_client_manager.connect_all())
        except Exception as e:
            logger.debug("[ToolRegistry] MCP auto-connect skipped: %s", e)


# ── Tool Implementations ─────────────────────────────────────────────────────

def _tool_web_search(query: str = "", max_results: int = 5,
                     mode: str = "fast", extract_urls: list = None,
                     rewrite: bool = None, **kwargs) -> str:
    """V3.2: Multi-engine web search with deep/research modes."""
    try:
        from skills.web_search import run as web_search_run

        inputs = {
            "query": query,
            "max_results": int(max_results),
            "mode": mode,
        }
        if extract_urls:
            inputs["extract_urls"] = extract_urls
        if rewrite is not None:
            inputs["rewrite"] = rewrite

        result = web_search_run(inputs)

        if result.get("error"):
            return f"Search error: {result['error']}"

        if not result.get("results"):
            return "No results found."

        lines = [f"[Engine: {result.get('engine', '?')} | Mode: {result.get('mode', '?')}]"]
        if result.get("queries_used"):
            lines.append(f"[Queries: {', '.join(result['queries_used'][:3])}]")
        lines.append("")

        # Research mode: show synthesis first
        if result.get("synthesis"):
            lines.append("## Research Summary")
            lines.append(result["synthesis"][:3000])
            lines.append("")
            lines.append(f"---\n[Sources read: {result.get('sources_read', 0)}]\n")

        for r in result["results"]:
            lines.append(f"**{r.get('title', '')}**")
            full = r.get("full_content", "")
            body = r.get("body", "")
            if full:
                lines.append(f"  {full[:1500]}")
            elif body:
                lines.append(f"  {body[:500]}")
            if r.get("href"):
                lines.append(f"  URL: {r['href']}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"


def _tool_run_command(command: str, timeout: int = 30, **kwargs) -> str:
    """Execute a shell command.

    Uses shell=False with shlex.split.
    [DEV MODE] All commands allowed — no whitelist.
    """
    import shlex

    # Kill-switch: only block absolute system destruction
    if 'rm -rf /' in command and 'rm -rf //' not in command:
        cmd_stripped = command.replace(' ', '')
        if 'rm-rf/' == cmd_stripped or 'rm-rf/*' in cmd_stripped:
            return "Blocked: absolute system destruction command."

    try:
        # Expand ~ to home directory (shell=False doesn't do tilde expansion)
        home = str(Path.home())
        expanded_command = command.replace("~/", f"{home}/")
        if expanded_command.startswith("~"):
            expanded_command = home + expanded_command[1:]

        # Parse command safely — no shell injection
        args = shlex.split(expanded_command)
        if not args:
            return "Empty command."

        # Expand ~ in individual args too
        args = [str(Path(a).expanduser()) if a.startswith("~") else a for a in args]

        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=min(timeout, 120),  # Cap at 2 minutes
            cwd=str(Path(__file__).resolve().parent.parent),  # project root
        )
        output = ""
        if result.stdout:
            output += f"STDOUT:\n{result.stdout[:3000]}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr[:1000]}\n"
        output += f"Exit code: {result.returncode}"
        return output or "Command completed with no output."
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s"
    except Exception as e:
        return f"Command error: {e}"


def _tool_execute_python(code: str, timeout: int = 60, **kwargs) -> str:
    """Execute Python code in a subprocess.

    Runs in a fresh Python interpreter with project root on PYTHONPATH.
    Returns stdout + stderr. No persistent state between calls.
    [DEV MODE] No pattern blocking.
    """
    import tempfile

    try:
        project_root = str(Path(__file__).resolve().parent.parent)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", dir="/tmp", delete=False
        ) as f:
            f.write(code)
            script_path = f.name

        env = os.environ.copy()
        env["PYTHONPATH"] = project_root
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True,
            text=True,
            timeout=min(timeout, 300),  # Cap at 5 minutes
            cwd=project_root,
            env=env,
        )

        output = ""
        if result.stdout:
            output += result.stdout[:5000]
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr[:2000]}"
        output += f"\n[Exit code: {result.returncode}]"

        # Cleanup
        try:
            os.unlink(script_path)
        except OSError:
            pass

        return output.strip() or "Code executed with no output."
    except subprocess.TimeoutExpired:
        return f"Python execution timed out after {timeout}s"
    except Exception as e:
        return f"Python execution error: {e}"


def _tool_execute_shell(command: str, timeout: int = 60, **kwargs) -> str:
    """Execute a shell command with full shell features (pipes, redirects, etc).

    Uses shell=True with safety blocks. Supports |, >, >>, &&, ||, etc.
    """
    # [DEV MODE] Kill-switch only: block absolute destruction
    if 'rm -rf /' in command.lower() and '/' == command.lower().strip().split('rm -rf ')[-1].strip()[:1]:
        if command.strip() in ('rm -rf /', 'rm -rf /*'):
            return "Blocked: absolute system destruction command."

    try:
        project_root = str(Path(__file__).resolve().parent.parent)
        env = os.environ.copy()
        env["PATH"] = f"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{env.get('PATH', '')}"

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=min(timeout, 300),
            cwd=project_root,
            env=env,
        )

        output = ""
        if result.stdout:
            output += f"{result.stdout[:5000]}"
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr[:2000]}"
        output += f"\n[Exit code: {result.returncode}]"
        return output.strip() or "Command completed with no output."
    except subprocess.TimeoutExpired:
        return f"Shell command timed out after {timeout}s"
    except Exception as e:
        return f"Shell error: {e}"


def _tool_execute_node(code: str, timeout: int = 60, **kwargs) -> str:
    """Execute Node.js code in a subprocess.

    Runs via `node -e` for short code or temp file for longer code.
    Returns stdout + stderr.
    """
    import tempfile

    try:
        project_root = str(Path(__file__).resolve().parent.parent)
        env = os.environ.copy()
        env["PATH"] = f"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{env.get('PATH', '')}"

        # For longer code, use a temp file
        if len(code) > 500 or "\n" in code:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".js", dir="/tmp", delete=False
            ) as f:
                f.write(code)
                script_path = f.name

            result = subprocess.run(
                ["node", script_path],
                capture_output=True,
                text=True,
                timeout=min(timeout, 300),
                cwd=project_root,
                env=env,
            )

            try:
                os.unlink(script_path)
            except OSError:
                pass
        else:
            result = subprocess.run(
                ["node", "-e", code],
                capture_output=True,
                text=True,
                timeout=min(timeout, 300),
                cwd=project_root,
                env=env,
            )

        output = ""
        if result.stdout:
            output += result.stdout[:5000]
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr[:2000]}"
        output += f"\n[Exit code: {result.returncode}]"
        return output.strip() or "Node.js executed with no output."
    except subprocess.TimeoutExpired:
        return f"Node.js execution timed out after {timeout}s"
    except FileNotFoundError:
        return "Error: node is not installed or not in PATH. Install via: brew install node"
    except Exception as e:
        return f"Node.js execution error: {e}"

def _tool_read_file(path: str, **kwargs) -> str:
    """Read a file. [DEV MODE] No path restrictions."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"File not found: {path}"
        file_stat = p.stat()
        if file_stat.st_size > 500_000:
            return f"File too large ({file_stat.st_size} bytes). Read first 10000 chars.\n\n" + p.read_text(encoding="utf-8")[:10000]
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Read error: {e}"


def _tool_write_file(path: str, content: str, **kwargs) -> str:
    """Write a file. [DEV MODE] No path restrictions."""
    try:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"Write error: {e}"


def _tool_list_directory(path: str, **kwargs) -> str:
    """List directory contents."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"Directory not found: {path}"
        if not p.is_dir():
            return f"Not a directory: {path}"
        entries = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name))
        lines = []
        for entry in entries[:50]:
            prefix = "📁" if entry.is_dir() else "📄"
            size = ""
            if entry.is_file():
                size = f" ({entry.stat().st_size:,} bytes)"
            lines.append(f"  {prefix} {entry.name}{size}")
        result = f"Contents of {path}:\n" + "\n".join(lines)
        if len(entries) > 50:
            result += f"\n  ... and {len(entries) - 50} more"
        return result
    except Exception as e:
        return f"List error: {e}"


def _tool_edit_file(path: str, find: str, replace: str, **kwargs) -> str:
    """Patch-style file editing: find text and replace it.

    More precise than write_file — only changes the matched portion.
    Supports multi-line find/replace.
    """
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"File not found: {path}"
        content = p.read_text(encoding="utf-8")
        count = content.count(find)
        if count == 0:
            # Show a preview of the file to help debug
            preview = content[:500]
            return f"Pattern not found in {path}. File preview:\n{preview}"
        if count > 1:
            # Replace all occurrences but warn
            new_content = content.replace(find, replace)
            p.write_text(new_content, encoding="utf-8")
            return f"Replaced {count} occurrences in {path} ({len(new_content)} chars total)"
        new_content = content.replace(find, replace, 1)
        p.write_text(new_content, encoding="utf-8")
        return f"Edited {path}: replaced 1 occurrence ({len(new_content)} chars total)"
    except Exception as e:
        return f"Edit error: {e}"


def _tool_search_code(query: str, path: str = ".", file_pattern: str = "", **kwargs) -> str:
    """Search for text across files using grep -rn.

    Recursive search with line numbers and context.
    """
    try:
        search_path = Path(path).expanduser().resolve()
        if not search_path.exists():
            return f"Path not found: {path}"

        cmd = ["grep", "-rn", "--include=*.py", "--include=*.js",
               "--include=*.ts", "--include=*.md", "--include=*.yaml",
               "--include=*.yml", "--include=*.json", "--include=*.html",
               "--include=*.css", "--include=*.sh", "--include=*.txt",
               "-I",  # skip binary files
               query, str(search_path)]

        if file_pattern:
            cmd = ["grep", "-rn", f"--include={file_pattern}", "-I",
                   query, str(search_path)]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout[:5000] if result.stdout else "No matches found."
        lines = output.strip().split("\n")
        if len(lines) > 30:
            output = "\n".join(lines[:30]) + f"\n\n... ({len(lines)} total matches, showing first 30)"
        return output
    except subprocess.TimeoutExpired:
        return "Search timed out after 30s"
    except Exception as e:
        return f"Search error: {e}"


def _tool_fetch_url(url: str, **kwargs) -> str:
    """Fetch web page content and return as text.

    Strips HTML tags for readability. Useful for reading docs, APIs, articles.
    """
    import urllib.request
    import re as _re

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) ArcMind/1.0"
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        # Strip HTML tags for readability
        text = _re.sub(r'<script[^>]*>.*?</script>', '', raw, flags=_re.DOTALL | _re.IGNORECASE)
        text = _re.sub(r'<style[^>]*>.*?</style>', '', text, flags=_re.DOTALL | _re.IGNORECASE)
        text = _re.sub(r'<[^>]+>', ' ', text)
        text = _re.sub(r'\s+', ' ', text).strip()

        if len(text) > 8000:
            text = text[:8000] + "\n\n... (truncated)"
        return text or "Page fetched but no text content found."
    except Exception as e:
        return f"Fetch error: {e}"


def _tool_send_notification(message: str, **kwargs) -> str:
    """Send a notification message to the user via Telegram."""
    import asyncio

    async def _send():
        try:
            from config.settings import settings
            import aiohttp
            import ssl
            import certifi
            chat_id = settings.telegram_chat_id
            bot_token = settings.telegram_bot_token
            if not chat_id or not bot_token:
                return "Telegram not configured."
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            conn = aiohttp.TCPConnector(ssl=ssl_ctx)
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            async with aiohttp.ClientSession(connector=conn) as session:
                resp = await session.post(url, json={
                    "chat_id": chat_id,
                    "text": message[:4000],
                })
                if resp.status == 200:
                    return "Notification sent."
                body = await resp.text()
                return f"Telegram API error {resp.status}: {body[:200]}"
        except Exception as e:
            return f"Notification error: {e}"

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                result = pool.submit(lambda: asyncio.run(_send())).result(timeout=10)
            return result
        return asyncio.run(_send())
    except Exception as e:
        return f"Notification error: {e}"


def _tool_create_directory(path: str, **kwargs) -> str:
    """Create a directory (including parent directories)."""
    try:
        p = Path(path).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return f"Directory created: {p}"
    except Exception as e:
        return f"Create directory error: {e}"


def _tool_delete_file(path: str, **kwargs) -> str:
    """Delete a file or empty directory."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Not found: {path}"
        # Kill-switch: prevent deleting critical system paths
        critical = ["/", "/Users", "/System", "/Applications", "/Library"]
        if str(p) in critical:
            return f"Blocked: cannot delete critical path '{p}'"
        if p.is_dir():
            import shutil
            shutil.rmtree(p)
            return f"Directory deleted: {p}"
        else:
            p.unlink()
            return f"File deleted: {p}"
    except Exception as e:
        return f"Delete error: {e}"


def _tool_move_file(source: str, destination: str, **kwargs) -> str:
    """Move or rename a file/directory."""
    import shutil
    try:
        src = Path(source).expanduser().resolve()
        dst = Path(destination).expanduser().resolve()
        if not src.exists():
            return f"Source not found: {source}"
        shutil.move(str(src), str(dst))
        return f"Moved: {src} → {dst}"
    except Exception as e:
        return f"Move error: {e}"


def _tool_copy_file(source: str, destination: str, **kwargs) -> str:
    """Copy a file or directory."""
    import shutil
    try:
        src = Path(source).expanduser().resolve()
        dst = Path(destination).expanduser().resolve()
        if not src.exists():
            return f"Source not found: {source}"
        if src.is_dir():
            shutil.copytree(str(src), str(dst))
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(src), str(dst))
        return f"Copied: {src} → {dst}"
    except Exception as e:
        return f"Copy error: {e}"


def _tool_apply_patch(path: str, patch: str, **kwargs) -> str:
    """Apply a unified diff patch to a file.

    Accepts standard unified diff format (like `diff -u` output).
    Falls back to line-by-line apply if `patch` command unavailable.
    """
    import tempfile
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"File not found: {path}"
        # Write patch to temp file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch", delete=False) as f:
            f.write(patch)
            patch_path = f.name
        result = subprocess.run(
            ["patch", str(p), patch_path],
            capture_output=True, text=True, timeout=15,
        )
        os.unlink(patch_path)
        if result.returncode == 0:
            return f"Patch applied to {path}"
        return f"Patch failed: {result.stderr[:500]}"
    except FileNotFoundError:
        return "Error: 'patch' command not installed."
    except Exception as e:
        return f"Patch error: {e}"


def _tool_append_file(path: str, content: str, **kwargs) -> str:
    """Append content to the end of a file (creates if not exists)."""
    try:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Appended {len(content)} chars to {path}"
    except Exception as e:
        return f"Append error: {e}"


def _tool_file_info(path: str, **kwargs) -> str:
    """Get file/directory metadata: size, permissions, timestamps, type."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"Not found: {path}"
        stat = p.stat()
        import time as _time
        info = {
            "path": str(p),
            "type": "directory" if p.is_dir() else "file",
            "size": stat.st_size,
            "permissions": oct(stat.st_mode)[-3:],
            "modified": _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(stat.st_mtime)),
            "created": _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(stat.st_ctime)),
            "is_symlink": p.is_symlink(),
        }
        if p.is_dir():
            info["children"] = len(list(p.iterdir()))
        if p.is_file():
            info["extension"] = p.suffix
            info["size_human"] = f"{stat.st_size:,} bytes"
            if stat.st_size > 1024 * 1024:
                info["size_human"] = f"{stat.st_size / 1024 / 1024:.1f} MB"
            elif stat.st_size > 1024:
                info["size_human"] = f"{stat.st_size / 1024:.1f} KB"
        return json.dumps(info, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"File info error: {e}"


def _tool_get_system_info(**kwargs) -> str:
    """Get system information: OS, hostname, CPU, memory, disk, Python version."""
    import platform
    try:
        info = {
            "os": platform.system(),
            "os_version": platform.version(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "python_version": platform.python_version(),
            "processor": platform.processor(),
        }
        # Disk usage
        import shutil
        total, used, free = shutil.disk_usage("/")
        info["disk"] = {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
        }
        # Memory (macOS)
        try:
            mem_result = subprocess.run(
                ["sysctl", "-n", "hw.memsize"],
                capture_output=True, text=True, timeout=5,
            )
            if mem_result.returncode == 0:
                mem_bytes = int(mem_result.stdout.strip())
                info["memory_gb"] = round(mem_bytes / (1024**3), 1)
        except Exception:
            pass
        # Uptime
        try:
            uptime_result = subprocess.run(
                ["uptime"], capture_output=True, text=True, timeout=5,
            )
            info["uptime"] = uptime_result.stdout.strip()
        except Exception:
            pass
        return json.dumps(info, indent=2, ensure_ascii=False)
    except Exception as e:
        return f"System info error: {e}"


def _tool_http_request(url: str, method: str = "GET", headers: dict = None,
                       body: str = None, **kwargs) -> str:
    """Make an HTTP request (GET, POST, PUT, DELETE, PATCH).

    Returns status code, headers, and body. Useful for API calls.
    """
    import urllib.request
    import urllib.error

    try:
        req = urllib.request.Request(url, method=method.upper())
        req.add_header("User-Agent", "ArcMind/1.0")
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        data = body.encode("utf-8") if body else None
        if data and "Content-Type" not in (headers or {}):
            req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, data=data, timeout=30) as resp:
            status = resp.status
            resp_headers = dict(resp.headers)
            resp_body = resp.read().decode("utf-8", errors="replace")

        result = f"Status: {status}\n"
        result += f"Headers: {json.dumps(resp_headers, indent=2)}\n"
        if len(resp_body) > 5000:
            result += f"Body (first 5000 chars):\n{resp_body[:5000]}\n...(truncated)"
        else:
            result += f"Body:\n{resp_body}"
        return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:2000]
        return f"HTTP Error {e.code}: {e.reason}\nBody: {body}"
    except Exception as e:
        return f"HTTP request error: {e}"


def _tool_screenshot(**kwargs) -> str:
    """Take a screenshot of the current screen (macOS). Saves to /tmp/."""
    try:
        output_path = f"/tmp/arcmind_screenshot_{int(time.time())}.png"
        result = subprocess.run(
            ["screencapture", "-x", output_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and Path(output_path).exists():
            size = Path(output_path).stat().st_size
            return f"Screenshot saved: {output_path} ({size:,} bytes)"
        return f"Screenshot failed: {result.stderr}"
    except Exception as e:
        return f"Screenshot error: {e}"


def _tool_generate_image(prompt: str, output_path: str = None, **kwargs) -> str:
    """Generate an image using DALL-E or similar API.

    Returns the path to the saved image.
    """
    try:
        from config.settings import settings
        import urllib.request

        if not settings.openai_api_key:
            return "Error: OPENAI_API_KEY not configured."

        api_url = "https://api.openai.com/v1/images/generations"
        req_data = json.dumps({
            "model": "dall-e-3",
            "prompt": prompt,
            "n": 1,
            "size": "1024x1024",
        }).encode("utf-8")

        req = urllib.request.Request(api_url, data=req_data)
        req.add_header("Authorization", f"Bearer {settings.openai_api_key}")
        req.add_header("Content-Type", "application/json")

        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))

        image_url = result["data"][0]["url"]
        save_path = output_path or f"/tmp/arcmind_image_{int(time.time())}.png"

        urllib.request.urlretrieve(image_url, save_path)
        return f"Image generated and saved: {save_path}"
    except Exception as e:
        return f"Image generation error: {e}"


def _tool_read_pdf(path: str, **kwargs) -> str:
    """Read text content from a PDF file."""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return f"File not found: {path}"
        # Try PyPDF2 first
        try:
            import PyPDF2
            with open(p, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                text = ""
                for page in reader.pages[:50]:  # Cap at 50 pages
                    text += page.extract_text() + "\n"
            if text.strip():
                return text[:10000] if len(text) > 10000 else text
        except ImportError:
            pass
        # Fallback: Use pdftotext if available
        result = subprocess.run(
            ["pdftotext", str(p), "-"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            text = result.stdout[:10000]
            return text
        return "Could not extract PDF text. Install PyPDF2: pip install PyPDF2"
    except Exception as e:
        return f"PDF read error: {e}"


def _tool_cron_manage(action: str, **kwargs) -> str:
    """Manage ArcMind scheduled tasks (heartbeat/cron).

    Actions: list, add, remove, status
    """
    try:
        if action == "list":
            from heartbeat.engine import heartbeat_engine
            tasks = heartbeat_engine.list_tasks()
            if not tasks:
                return "No scheduled tasks."
            lines = []
            for t in tasks:
                lines.append(f"  [{t.get('id', '?')}] {t.get('name', '?')} — {t.get('schedule', '?')} (active: {t.get('active', '?')})")
            return "Scheduled tasks:\n" + "\n".join(lines)
        elif action == "status":
            from heartbeat.engine import heartbeat_engine
            return f"Heartbeat engine status: {heartbeat_engine.status()}"
        else:
            return f"Supported actions: list, status. For add/remove, use plan_task or the PM agent."
    except ImportError:
        return "Heartbeat engine not available."
    except Exception as e:
        return f"Cron manage error: {e}"


def _tool_session_status(**kwargs) -> str:
    """Get current ArcMind session status: active sessions, tool count, uptime."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8100/v1/gateway/status", timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return json.dumps(data, indent=2, ensure_ascii=False)[:5000]
    except Exception as e:
        return f"Session status error: {e}"


def _tool_llm_task(task: str, model: str = None, **kwargs) -> str:
    """Run a sub-LLM task: send a prompt to the LLM and get a response.

    Useful for summarization, translation, analysis, etc.
    Uses the configured model unless overridden.
    """
    try:
        from runtime.model_router import model_router
        result = model_router.chat(
            messages=[{"role": "user", "content": task}],
            model_override=model,
            max_tokens=2000,
        )
        return result.get("content", str(result))[:5000]
    except Exception as e:
        return f"LLM task error: {e}"


def _tool_browser_action(action: str, url: str = None, selector: str = None,
                         text: str = None, **kwargs) -> str:
    """Browser automation: navigate, click, type, extract text.

    Actions: navigate, click, type, get_text, screenshot, get_html
    Requires a running browser with CDP enabled.
    """
    try:
        # Check if we have a browser CDP session
        import urllib.request

        cdp_url = "http://127.0.0.1:9222/json"
        try:
            with urllib.request.urlopen(cdp_url, timeout=3) as resp:
                pages = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return ("Browser not connected. Start Chrome with: "
                    "open -a 'Google Chrome' --args --remote-debugging-port=9222")

        if action == "navigate" and url:
            # Use CDP to navigate
            return f"Browser CDP available. {len(pages)} tabs open. Navigate to: {url} (use execute_shell with 'open {url}' for now)"
        elif action == "get_text":
            if pages:
                return f"Browser has {len(pages)} tabs. Tab 0: {pages[0].get('title', '?')} — {pages[0].get('url', '?')}"
            return "No browser tabs open."
        else:
            return f"Browser CDP available ({len(pages)} tabs). Supported actions: navigate, get_text. Full CDP coming soon."
    except Exception as e:
        return f"Browser error: {e}"


def _tool_python_eval(code: str, **kwargs) -> str:
    """Evaluate Python code in a restricted sandbox.

    Uses AST validation (whitelist of allowed node types) instead of string
    matching, which is resistant to encoding tricks and string concatenation
    bypasses.  Only safe built-ins are exposed; dangerous modules are not
    importable.
    """
    import ast

    # ── AST whitelist — only these node types are permitted ──
    _ALLOWED_NODES = {
        # Literals & containers
        ast.Module, ast.Expression, ast.Constant, ast.List, ast.Tuple,
        ast.Set, ast.Dict, ast.FormattedValue, ast.JoinedStr,
        # Variables & names
        ast.Name, ast.Load, ast.Store, ast.Del, ast.Starred,
        # Expressions
        ast.UnaryOp, ast.UAdd, ast.USub, ast.Not, ast.Invert,
        ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
        ast.Mod, ast.Pow, ast.LShift, ast.RShift, ast.BitOr, ast.BitXor,
        ast.BitAnd, ast.MatMult,
        ast.BoolOp, ast.And, ast.Or,
        ast.Compare, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
        ast.Is, ast.IsNot, ast.In, ast.NotIn,
        ast.IfExp, ast.Subscript, ast.Slice,
        *([] if not hasattr(ast, "Index") else [ast.Index]),  # ast.Index removed in Python 3.9+
        # Comprehensions
        ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
        ast.comprehension,
        # Statements
        ast.Expr, ast.Assign, ast.AugAssign, ast.AnnAssign,
        ast.If, ast.For, ast.While, ast.Break, ast.Continue, ast.Pass,
        ast.Return,
        # Function calls (allowed — dangerous callables blocked via builtins)
        ast.Call, ast.keyword,
    }

    # ── Parse and validate AST ──
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return f"Syntax error: {e}"

    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_NODES:
            return f"Blocked: AST node '{type(node).__name__}' is not allowed in sandbox."
        # Block dunder attribute access
        if isinstance(node, ast.Name) and node.id.startswith("__") and node.id.endswith("__"):
            return f"Blocked: access to '{node.id}' is not allowed."

    # ── Safe builtins whitelist (no type/dir/isinstance to prevent class hierarchy walks) ──
    _SAFE_BUILTINS = {
        "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
        "chr": chr, "dict": dict, "divmod": divmod,
        "enumerate": enumerate, "filter": filter, "float": float,
        "format": format, "frozenset": frozenset, "hash": hash,
        "hex": hex, "int": int, "iter": iter, "len": len, "list": list,
        "map": map, "max": max, "min": min, "next": next, "oct": oct,
        "ord": ord, "pow": pow, "print": print, "range": range,
        "repr": repr, "reversed": reversed, "round": round, "set": set,
        "slice": slice, "sorted": sorted, "str": str, "sum": sum,
        "tuple": tuple, "zip": zip,
        "True": True, "False": False, "None": None,
    }
    # Allow safe stdlib modules
    import math, json as _json, re as _re, datetime as _dt, collections as _col
    _SAFE_MODULES = {
        "math": math, "json": _json, "re": _re,
        "datetime": _dt, "collections": _col,
    }

    sandbox_globals = {"__builtins__": _SAFE_BUILTINS, **_SAFE_MODULES}
    local_vars: dict = {}

    try:
        compiled = compile(tree, "<sandbox>", "exec")
        exec(compiled, sandbox_globals, local_vars)

        if "result" in local_vars:
            return str(local_vars["result"])
        if local_vars:
            return str(local_vars)
        return "Code executed successfully (no explicit result)"
    except Exception as e:
        return f"Python error: {traceback.format_exc()}"


def _tool_memory_query(query: str, top_k: int = 3, **kwargs) -> str:
    """Query memory - tries MGIS first, falls back to local MemoryStore."""
    # Try MGIS first
    try:
        from foundation.mgis_client import mgis
        if mgis.is_online():
            result = mgis.memory_query(query=query, top_k=top_k, tags=["arcmind"])
            hits = result.get("results", [])
            if hits:
                lines = ["[MGIS] Related memories:"]
                for h in hits:
                    lines.append(f"  - {h.get('content', '')[:200]}")
                return "\n".join(lines)
    except Exception as e:
        logger.debug("[MemoryQuery] MGIS unavailable: %s", e)
    
    # Fallback to local MemoryStore
    try:
        from memory.memory_store import memory_store
        results = memory_store.query(query=query, top_k=top_k)
        if not results:
            return "No relevant memories found (local)."
        lines = ["[Local] Related memories:"]
        for r in results:
            lines.append(f"  - {r.get('content', '')[:200]}")
        return "\n".join(lines)
    except Exception as e:
        return f"Memory query error: {e}"


def _tool_memory_save(content: str, memory_type: str = "semantic",
                      importance: float = 0.7, tags: list = None, **kwargs) -> str:
    """Save information to long-term memory."""
    if not content or not content.strip():
        return "Error: content is required."

    try:
        from memory.memory_store import memory_store
        valid_types = ("episodic", "semantic", "procedural", "causal")
        if memory_type not in valid_types:
            memory_type = "semantic"

        mid = memory_store.add(
            content=content.strip(),
            source="ceo_explicit",
            memory_type=memory_type,
            importance=min(max(importance, 0.1), 1.0),
            tags=tags,
            dedup=True,
        )
        if mid:
            return f"Saved to {memory_type} memory (id={mid}, importance={importance})."
        else:
            return "Skipped: similar memory already exists (dedup)."
    except Exception as e:
        return f"Memory save error: {e}"


# ── Agent Management Tools ───────────────────────────────────────────────────

def _tool_list_agents(**kwargs) -> str:
    """List all configured agents."""
    try:
        from runtime.agent_registry import agent_registry
        return agent_registry.format_roster()
    except Exception as e:
        return f"Error listing agents: {e}"


def _tool_add_agent(
    agent_id: str, name: str, model: str, purpose: str,
    capabilities: list | None = None, system_prompt: str = "", **kwargs
) -> str:
    """Add a new agent."""
    try:
        from runtime.agent_registry import agent_registry
        return agent_registry.add_agent(
            agent_id=agent_id, name=name, model=model,
            purpose=purpose, capabilities=capabilities,
            system_prompt=system_prompt,
        )
    except Exception as e:
        return f"Error adding agent: {e}"


def _tool_remove_agent(agent_id: str, **kwargs) -> str:
    """Remove an agent."""
    try:
        from runtime.agent_registry import agent_registry
        return agent_registry.remove_agent(agent_id)
    except Exception as e:
        return f"Error removing agent: {e}"


# ── Agent Delegation Tools ───────────────────────────────────────────────────

def _tool_delegate_task(
    assignee: str, title: str,
    task_data: dict | None = None,
    priority: str = "medium",
    **kwargs,
) -> str:
    """Delegate a task to a sub-agent."""
    try:
        from skills.agent_delegation import delegate_task
        result = delegate_task({
            "assignee": assignee,
            "title": title,
            "task_data": task_data or {},
            "priority": priority,
        })
        if "error" in result:
            return f"委派失敗: {result['error']}"
        return (
            f"✅ 任務已委派給 {assignee}\n"
            f"Task ID: {result.get('task_id')}\n"
            f"Priority: {priority}\n"
            f"狀態: 已排入佇列，Heartbeat 會自動處理。"
        )
    except Exception as e:
        return f"委派錯誤: {e}"


def _tool_delegate_pipeline(
    title: str, steps: list,
    priority: str = "medium",
    **kwargs,
) -> str:
    """Create a multi-agent pipeline."""
    try:
        from skills.agent_delegation import delegate_multi
        result = delegate_multi({
            "title": title,
            "steps": steps,
            "priority": priority,
        })
        if "error" in result:
            return f"Pipeline 建立失敗: {result['error']}"
        step_desc = " → ".join(s.get("assignee", "?") for s in steps)
        return (
            f"✅ 多 Agent Pipeline 已建立\n"
            f"Pipeline ID: {result.get('pipeline_id')}\n"
            f"步驟: {step_desc}\n"
            f"共 {result.get('steps', 0)} 步，Heartbeat 會按順序執行。"
        )
    except Exception as e:
        return f"Pipeline 錯誤: {e}"


def _tool_agent_inbox(limit: int = 10, **kwargs) -> str:
    """Show CEO's inbox from IAMP message bus."""
    try:
        from runtime.iamp import message_bus
        messages = message_bus.get_inbox("main", limit=limit)
        if not messages:
            return "收件箱為空 — 目前沒有子 Agent 回報。"
        lines = [f"## CEO 收件箱 ({len(messages)} 筆)", ""]
        for m in messages:
            ts = time.strftime("%m/%d %H:%M", time.localtime(m.timestamp))
            payload_summary = str(m.payload.get("output",
                                  m.payload.get("reason",
                                  m.payload.get("review", ""))))[:150]
            lines.append(
                f"**[{m.msg_type.value}]** from `{m.sender}` ({ts})\n"
                f"  Task: {m.task_id or 'N/A'}\n"
                f"  {payload_summary}"
            )
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"收件箱讀取錯誤: {e}"


# ── Skill Invocation Tools ───────────────────────────────────────────────────

def _tool_invoke_skill(skill_name: str, inputs: dict | None = None, **kwargs) -> str:
    """Invoke a registered ArcMind skill."""
    try:
        from runtime.skill_manager import skill_manager
        # V3.1: Pass caller agent identity for skill ACL
        caller_agent = kwargs.get("_agent_id") or get_caller_agent()
        result = skill_manager.invoke(skill_name, inputs or {},
                                      caller_agent=caller_agent)
        if result.get("success"):
            import json
            output = result.get("output", {})
            return json.dumps(output, ensure_ascii=False, indent=2, default=str)
        else:
            return f"Skill error: {result.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Invoke skill error: {e}"


def _tool_list_skills(**kwargs) -> str:
    """List all available skills."""
    try:
        from runtime.skill_manager import skill_manager
        skills = skill_manager.list_skills()
        lines = ["Available ArcMind Skills:", ""]
        for s in skills:
            name = s["name"]
            manifest = s.get("manifest", {})
            desc = manifest.get("description", "No description")
            tags = manifest.get("tags", [])
            lines.append(f"  📦 {name}")
            lines.append(f"     Description: {desc}")
            if tags:
                lines.append(f"     Tags: {', '.join(tags)}")
            # Show skill-specific actions if available
            inputs = manifest.get("inputs", [])
            for inp in inputs:
                if inp.get("name") == "action":
                    lines.append(f"     Actions: {inp.get('description', '')}")
            lines.append("")
        return "\n".join(lines) if skills else "No skills registered."
    except Exception as e:
        return f"Error listing skills: {e}"


def _tool_get_skill_info(skill_name: str, **kwargs) -> str:
    """Get detailed usage info for a specific skill from tools_registry.json."""
    import json
    try:
        # 1. Read from tools_registry.json (detailed usage docs)
        registry_path = Path(__file__).resolve().parent.parent / "config" / "tools_registry.json"
        registry_info = None
        if registry_path.exists():
            with open(registry_path, "r") as f:
                registry = json.load(f)
            registry_info = registry.get("skills", {}).get(skill_name)

        # 2. Read from skill_manager manifest (inputs/outputs/permissions)
        from runtime.skill_manager import skill_manager
        manifest = skill_manager.get_manifest(skill_name)

        if not registry_info and not manifest:
            # List similar names
            all_skills = [s["name"] for s in skill_manager.list_skills()]
            similar = [n for n in all_skills if skill_name.lower() in n.lower()]
            hint = f" Similar: {', '.join(similar)}" if similar else f" Available: {', '.join(all_skills[:10])}..."
            return f"Skill '{skill_name}' not found.{hint}"

        lines = [f"📦 Skill: {skill_name}", ""]

        # Registry info (description, setup, usage, actions)
        if registry_info:
            if registry_info.get("description"):
                lines.append(f"Description: {registry_info['description']}")
            if registry_info.get("setup"):
                lines.append(f"\nSetup: {registry_info['setup']}")
            if registry_info.get("usage"):
                lines.append(f"\nUsage Example:\n{json.dumps(registry_info['usage'], ensure_ascii=False, indent=2)}")
            if registry_info.get("actions"):
                lines.append(f"\nAvailable Actions: {', '.join(registry_info['actions'])}")
            # Extra fields (themes, formats, etc.)
            for key in registry_info:
                if key not in ("description", "setup", "usage", "actions", "dependencies"):
                    lines.append(f"\n{key}: {json.dumps(registry_info[key], ensure_ascii=False)}")

        # Manifest info (inputs/outputs/tags)
        if manifest:
            if manifest.get("inputs"):
                lines.append("\nInputs:")
                for inp in manifest["inputs"]:
                    req = " (required)" if inp.get("required") else ""
                    lines.append(f"  - {inp['name']}: {inp.get('type', 'string')}{req} — {inp.get('description', '')}")
            if manifest.get("tags"):
                lines.append(f"\nTags: {', '.join(manifest['tags'])}")

        return "\n".join(lines)
    except Exception as e:
        return f"Error getting skill info: {e}"




def _tool_hire_agent(template_id: str, custom_model: str | None = None, **kwargs) -> str:
    """Hire an agent from the template library."""
    try:
        from runtime.agent_templates import template_manager
        result = template_manager.hire(template_id, custom_model)
        if result["success"]:
            return f"✅ 已聘用 {result['name']} (ID: {result['agent_id']}, Model: {result['model']})"
        return f"❌ 聘用失敗: {result.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Error hiring agent: {e}"


def _tool_fire_agent(agent_id: str, **kwargs) -> str:
    """Fire a hired agent (cannot fire core agents)."""
    try:
        from runtime.agent_templates import template_manager
        result = template_manager.fire(agent_id)
        if result["success"]:
            return f"✅ 已解僱 Agent: {agent_id}"
        return f"❌ 解僱失敗: {result.get('error', 'Unknown error')}"
    except Exception as e:
        return f"Error firing agent: {e}"


def _tool_list_agent_templates(**kwargs) -> str:
    """List all available agent templates with hire status."""
    try:
        from runtime.agent_templates import template_manager
        templates = template_manager.list_templates()
        if not templates:
            return "No agent templates available."
        lines = ["Available Agent Templates:", ""]
        for t in templates:
            status = "✅ 已聘用" if t["hired"] else "📋 可聘用"
            lines.append(f"  {status} {t['name']} ({t['template_id']})")
            lines.append(f"     Purpose: {t['purpose']}")
            lines.append(f"     Capabilities: {', '.join(t['capabilities'])}")
            lines.append(f"     Category: {t['category']}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Error listing templates: {e}"


def _tool_agent_handoff(
    from_agent: str,
    to_agent: str,
    command: str,
    reason: str = "Task handoff",
    context: dict | None = None,
    **kwargs,
) -> str:
    """Initiate an agent-to-agent task handoff via EventBus."""
    try:
        from runtime.event_bus import event_bus, Event, EventType, EventPriority
        event_bus.emit(Event(
            type=EventType.AGENT_HANDOFF,
            source=f"tool:agent_handoff",
            payload={
                "from_agent": from_agent,
                "to_agent": to_agent,
                "command": command,
                "reason": reason,
                "context": context or {},
            },
            priority=EventPriority.HIGH,
        ))
        return f"✅ 交接已發起: {from_agent} → {to_agent} | 原因: {reason}"
    except Exception as e:
        return f"Error initiating handoff: {e}"


def _tool_restart_arcmind(reason: str = "unspecified", delay_seconds: int = 3, **kwargs) -> str:
    """Gracefully restart ArcMind. LaunchAgent KeepAlive will auto-restart."""
    import os
    import threading
    import time as _time

    logger.warning("[restart_arcmind] Restart requested: %s (delay=%ds)", reason, delay_seconds)

    # Log incident
    try:
        from ops.incident_logger import log_incident
        log_incident(cause=f"Manual restart: {reason}", action="graceful_shutdown", resolved=True)
    except Exception:
        pass

    # Notify via Telegram if possible
    try:
        from channels.telegram import send_message_sync
        send_message_sync(f"🔄 ArcMind 重啟中...\n原因: {reason}")
    except Exception:
        pass

    def _delayed_exit():
        _time.sleep(delay_seconds)
        logger.warning("[restart_arcmind] Shutting down NOW (LaunchAgent will restart)")
        # Remove PID file to allow clean restart
        try:
            pid_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "arcmind.pid")
            if os.path.exists(pid_file):
                os.unlink(pid_file)
        except Exception:
            pass
        os._exit(1)  # Non-zero exit triggers LaunchAgent KeepAlive restart

    t = threading.Thread(target=_delayed_exit, daemon=True)
    t.start()

    return f"✅ ArcMind will restart in {delay_seconds} seconds. Reason: {reason}"


def _tool_preflight_check(**kwargs) -> str:
    """Run pre-flight diagnostics without restarting."""
    lines = []
    try:
        from ops.repair_agent import run_diagnostics
        result = run_diagnostics()
        lines.append("🔍 ArcMind Pre-flight Diagnostics")
        lines.append("=" * 40)
        for c in result.checks:
            icon = {"OK": "✅", "REPAIRED": "🔧", "FAILED": "❌"}.get(c["status"], "❓")
            detail = f" — {c['detail']}" if c.get('detail') else ""
            lines.append(f"  {icon} [{c['status']}] {c['name']}{detail}")
        lines.append("=" * 40)
        lines.append(f"Summary: {result.summary}")
    except Exception as e:
        lines.append(f"❌ Pre-flight check failed: {e}")

    return "\n".join(lines)


def _tool_send_webhook(
    url: str,
    payload: dict | None = None,
    method: str = "POST",
    **kwargs,
) -> str:
    """Send a webhook to an external service with SSRF protection."""
    try:
        import urllib.request
        import json as _json
        from urllib.parse import urlparse

        # SSRF protection: block private/internal IPs
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        _BLOCKED_HOSTS = [
            "localhost", "127.0.0.1", "0.0.0.0", "::1",
            "metadata.google.internal", "169.254.169.254",
        ]
        if hostname in _BLOCKED_HOSTS:
            return f"❌ Blocked: cannot send webhooks to internal address '{hostname}'"
        # Block private IP ranges
        import ipaddress
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return f"❌ Blocked: cannot send webhooks to private IP '{hostname}'"
        except ValueError:
            pass  # hostname is a domain name, not an IP — allowed

        data = _json.dumps(payload or {}).encode()
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            body = resp.read().decode()[:500]
        return f"✅ Webhook sent: {method} {url} → {status}\n{body}"
    except Exception as e:
        return f"❌ Webhook failed: {e}"


def _tool_plan_task(goal: str, **kwargs) -> str:
    """Plan a complex task by decomposing it into steps."""
    try:
        from runtime.task_planner import task_planner
        plan = task_planner.plan(goal)
        return (
            f"✅ 計畫已建立\n\n"
            f"{plan.summary()}\n\n"
            f"📌 Plan ID: `{plan.plan_id}`\n"
            f"👉 確認後請呼叫 execute_plan(plan_id=\"{plan.plan_id}\") 開始執行"
        )
    except Exception as e:
        return f"❌ 規劃失敗: {e}"


def _tool_execute_plan(plan_id: str, **kwargs) -> str:
    """Execute a previously planned task."""
    try:
        from runtime.task_planner import task_planner
        result = task_planner.execute(plan_id)
        if result["success"]:
            # Auto-verify
            verification = task_planner.verify(plan_id)
            return f"✅ 計畫執行完成\n\n{result['summary']}\n\n## CEO 驗收\n{verification}"
        else:
            return f"⚠️ 計畫部分失敗\n\n{result['summary']}"
    except Exception as e:
        return f"❌ 執行失敗: {e}"


# ── Agentic Loop ─────────────────────────────────────────────────────────────

def agentic_complete(
    prompt: str,
    system: str | None = None,
    messages: list[dict] | None = None,
    model: str | None = None,
    task_type: str = "general",
    budget: str = "medium",
    max_tokens: int | None = None,
    tools_enabled: bool = True,
    require_tool_usage: bool = False,
    tool_filter: list[str] | None = None,
    skip_auto_memory: bool = False,
) -> dict:
    """
    Agentic completion with state-driven tool execution loop.
    This is the CORE that gives ArcMind OpenClaw-level execution power.

    Supports BOTH Anthropic AND OpenAI-compatible providers (OLLAMA, OpenAI, Groq, Mistral).

    State Machine:
      - RUNNING: normal tool execution
      - CHECKPOINT: LLM emitted <Status>Checkpoint_Passed</Status> → prune context
      - RETRY: LLM emitted <Status>Retry</Status> → retry current step
      - COMPLETED: LLM emitted <Status>Project_Completed</Status> → exit
      - ESCALATE: single-step retries exceeded → abort with escalation
    """
    from runtime.model_router import model_router
    from memory.working_memory import flush_step_logs, inject_checkpoint

    # ── 審計: 記錄原始指令（供 tool param 防幻覺檢查）──
    try:
        from runtime.audit import set_context as _set_audit_ctx
        _set_audit_ctx(prompt)
    except Exception:
        pass

    registry = tool_registry  # singleton
    # ── 語義工具篩選 ──
    if tools_enabled:
        all_schemas = registry.get_schemas()
        if tool_filter is not None and len(tool_filter) > 0:
            # 只暴露指定的工具 schema
            tool_schemas = [s for s in all_schemas if s["name"] in tool_filter]
            if not tool_schemas:
                # filter 指定的工具全部不存在 — 用全部（防禦性）
                logger.warning("[AgenticLoop] Tool filter matched 0 schemas, falling back to all")
                tool_schemas = all_schemas
            else:
                logger.info("[AgenticLoop] Tool filter active: %d/%d tools exposed",
                            len(tool_schemas), len(all_schemas))
        else:
            # 無指定 tool_filter 或空 list → 使用全部工具
            tool_schemas = all_schemas
    else:
        tool_schemas = []
    # 保留完整工具列表用於動態追加（安全閥）
    _all_tool_names = {s["name"] for s in registry.get_schemas()} if tools_enabled else set()
    tool_calls_log: list[dict] = []
    total_tokens = 0

    chosen = model or model_router.select_model(task_type, budget)[0]
    final_max = max_tokens or 4096

    provider_name, model_id = model_router._parse_model(chosen)
    provider = model_router._providers.get(provider_name)

    if not provider:
        raise RuntimeError(f"Provider {provider_name} not available")

    # Determine which call format to use
    is_anthropic = provider_name == "anthropic"
    # All providers except anthropic and google use OpenAI-compatible format
    _OPENAI_COMPAT_PROVIDERS = {
        "openai", "ollama", "ollama_remote", "groq", "mistral", "custom", "nvidia",
        "deepseek", "xai", "cohere", "together", "fireworks", "perplexity",
        "openrouter", "cerebras", "hyperbolic", "siliconflow", "minimax",
        "moonshot", "zhipu", "yi", "baichuan", "stepfun",
    }
    is_openai_compat = provider_name in _OPENAI_COMPAT_PROVIDERS

    # Build initial messages for OpenAI format (system goes in messages)
    if is_openai_compat:
        oai_messages: list[dict] = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        if messages:
            oai_messages.extend(messages)
        else:
            oai_messages.append({"role": "user", "content": prompt})

        # Convert tool schemas to OpenAI format
        oai_tools = _schemas_to_openai_tools(tool_schemas) if tool_schemas else None
    else:
        # Anthropic format
        oai_messages = messages if messages else [{"role": "user", "content": prompt}]
        oai_tools = None

    # ── Auto Memory Injection ────────────────────────────────────────────────
    # Automatically query relevant memories based on user input and inject into context
    # Skip when caller (e.g. main_loop) already injected memory to avoid duplication
    if prompt and not messages and not skip_auto_memory:
        try:
            from memory.memory_store import memory_store
            # Extract key terms from prompt for memory query
            query = prompt[:200]  # Use first 200 chars as query
            
            # Query recent episodic and semantic memories
            results = memory_store.query(
                query=query, 
                top_k=3,
                memory_types=["episodic", "semantic"],
                min_importance=0.4
            )
            
            if results:
                memory_context = "\n\n[相關記憶上下文]\n"
                for r in results[:3]:
                    snippet = r.get("content", "")[:150]
                    memory_context += f"- {snippet}...\n"
                memory_context += "[/記憶上下文]"
                
                # Inject into system prompt or first user message
                if oai_messages and oai_messages[0].get("role") == "system":
                    oai_messages[0]["content"] += memory_context
                elif oai_messages:
                    oai_messages[0]["content"] = memory_context + "\n\n" + oai_messages[0].get("content", "")
                logger.info("[Memory] Injected %d relevant memories into context", len(results))
        except Exception as e:
            logger.debug("[Memory] Auto-injection failed (non-fatal): %s", e)

    # ── State Machine Variables ──
    # 不限步數。Gateway 的 300s timeout 才是真正的時間安全網。
    # 這裡只偵測「有沒有在做正事」：
    #   - 卡死偵測：同一 tool+params 連續重複 → 沒在做正事
    #   - 連續失敗：tool 一直報錯 → 沒在做正事
    #   - 正常工作：tool 不同、params 不同、有結果 → 繼續幹
    MAX_STEP_RETRIES = 5          # max retries for a single step
    CHECKPOINT_PRUNE_KEEP = 4     # keep last N tool messages after pruning
    STUCK_THRESHOLD = 5           # 同一 tool+params 連續呼叫 N 次 = 卡死
    CONSEC_ERROR_LIMIT = 8        # 連續 N 次 tool 全部失敗 = 沒救了
    MAX_ITERATIONS = 50           # 絕對步數上限，防止無限迴圈

    iteration = 0
    step_retry_count = 0       # retries for current step
    last_error_tool = ""       # track which tool is failing
    checkpoint_count = 0       # number of checkpoints passed
    _recent_calls: list[str] = []   # 最近的 tool call 指紋，用於卡死偵測
    _consecutive_errors = 0         # 連續失敗次數

    while True:  # 靠 MAX_ITERATIONS + timeout + 卡死偵測 + 連續失敗偵測
        iteration += 1
        if iteration > MAX_ITERATIONS:
            logger.warning("[AgenticLoop] MAX_ITERATIONS (%d) reached, forcing exit", MAX_ITERATIONS)
            break
        logger.info("[AgenticLoop] iteration=%d, model=%s, messages=%d, checkpoints=%d",
                     iteration, chosen, len(oai_messages), checkpoint_count)

        # ── LLM Call ──
        try:
            if is_anthropic:
                resp = _anthropic_call_with_tools(
                    provider, model_id, oai_messages, system, final_max, tool_schemas
                )
            elif is_openai_compat:
                resp = _openai_call_with_tools(
                    provider, model_id, oai_messages, final_max, oai_tools
                )
            else:
                # Unknown provider — single shot, no tools
                result = provider.complete(model_id, oai_messages, system, final_max)
                return {
                    "content": result.content,
                    "tool_calls": tool_calls_log,
                    "total_tokens": result.total_tokens,
                    "iterations": iteration,
                }
        except Exception as e:
            logger.error("[AgenticLoop] LLM call failed: %s", e)
            # Try to recover from bad_request_error by trimming context
            if "bad_request_error" in str(e) and iteration > 1:
                logger.warning("[AgenticLoop] Attempting recovery: trimming context")
                # Remove last assistant + tool messages, but keep at least system + 1 user msg
                while len(oai_messages) > 2 and oai_messages[-1].get("role") in ("tool", "assistant"):
                    oai_messages.pop()
                if len(oai_messages) < 2:
                    return {
                        "content": f"⚠️ 上下文恢复失败，请重新发送请求。错误: {e}",
                        "tool_calls": tool_calls_log,
                        "total_tokens": total_tokens,
                        "iterations": iteration,
                    }
                continue  # retry the loop
            return {
                "content": f"⚠️ AI 服務錯誤: {e}",
                "tool_calls": tool_calls_log,
                "total_tokens": total_tokens,
                "iterations": iteration,
            }

        total_tokens += resp.get("total_tokens", 0)
        text_response = resp.get("text", "")
        tool_uses = resp.get("tool_uses", [])

        # ── A. Parse Status Tags ──
        status, state_summary = _parse_status_tags(text_response)

        # ── B. State-Driven Transitions ──
        if status == "Project_Completed":
            logger.info("[AgenticLoop] ✅ Project_Completed after %d iterations, %d checkpoints",
                        iteration, checkpoint_count)
            # Strip tags from final output
            clean_text = _strip_status_tags(text_response)

            # ── Fire-and-forget: 保存成功 SOP 到向量快取 ──
            try:
                from memory.sop_manager import _fire_and_forget_save
                _fire_and_forget_save(prompt, clean_text)
            except Exception:
                pass

            return {
                "content": clean_text,
                "tool_calls": tool_calls_log,
                "total_tokens": total_tokens,
                "iterations": iteration,
                "checkpoints": checkpoint_count,
                "status": "completed",
            }

        if status == "Checkpoint_Passed":
            checkpoint_count += 1
            step_retry_count = 0  # reset retry counter on checkpoint
            logger.info("[AgenticLoop] 📌 Checkpoint #%d passed, pruning context", checkpoint_count)

            # C. Dynamic Context Pruning
            oai_messages = flush_step_logs(oai_messages, keep_recent=CHECKPOINT_PRUNE_KEEP)
            if state_summary:
                oai_messages = inject_checkpoint(oai_messages, state_summary)
            continue  # Force fresh LLM call with pruned context

        if status == "Retry":
            step_retry_count += 1
            if step_retry_count >= MAX_STEP_RETRIES:
                logger.warning("[AgenticLoop] ⚠️ Max retries (%d) exceeded, escalating",
                               MAX_STEP_RETRIES)
                return {
                    "content": f"⚠️ 單步重試超過 {MAX_STEP_RETRIES} 次上限，自動中斷。\n"
                               f"最後錯誤工具: {last_error_tool}\n"
                               f"已完成 checkpoint: {checkpoint_count}\n"
                               f"建議人工檢查或拆分任務。",
                    "tool_calls": tool_calls_log,
                    "total_tokens": total_tokens,
                    "iterations": iteration,
                    "checkpoints": checkpoint_count,
                    "status": "escalated",
                }
            logger.info("[AgenticLoop] 🔄 Retry #%d for current step", step_retry_count)

        # ── No tool calls → check for XML/block tool calls in text ──
        if not tool_uses and text_response:
            xml_tools = _parse_xml_tool_calls(text_response)
            if xml_tools:
                # Execute XML tool calls immediately and return results.
                # Don't continue the loop — MiniMax XML format doesn't support
                # multi-turn tool calling, so continuing would cause infinite loops.
                xml_results = []
                for tu in xml_tools:
                    t_name = tu.get("name", "")
                    t_input = tu.get("input", {})
                    logger.info("[AgenticLoop] 🔧 XML tool: %s(%s)",
                                t_name, json.dumps(t_input, ensure_ascii=False)[:100])
                    handler = registry.get_handler(t_name)
                    if handler:
                        try:
                            # Unwrap {"raw": "..."} LLM parameter wrapping
                            if "raw" in t_input and len(t_input) == 1:
                                raw_val = t_input["raw"]
                                if isinstance(raw_val, str):
                                    try:
                                        unwrapped = json.loads(raw_val)
                                        if isinstance(unwrapped, dict):
                                            t_input = unwrapped
                                    except (json.JSONDecodeError, ValueError):
                                        pass
                                elif isinstance(raw_val, dict):
                                    t_input = raw_val

                            from runtime.tracing import get_tracer
                            _tracer = get_tracer("arcmind.tool")
                            with _tracer.start_as_current_span(f"tool.{t_name}") as _span:
                                _span.set_attribute("tool.name", t_name)
                                _span.set_attribute("tool.input", json.dumps(t_input, ensure_ascii=False)[:200])
                                result = handler(**t_input)
                                _span.set_attribute("tool.success", True)

                            # Post-execution file audit for XML tools too
                            if t_name == "write_file" and "path" in t_input:
                                _audit_path = Path(t_input["path"]).expanduser()
                                if not _audit_path.exists():
                                    result = (
                                        f"⚠️ AUDIT FAIL: write_file reported success but "
                                        f"'{t_input['path']}' does NOT exist on disk. "
                                        f"The file was NOT created. Do NOT tell the user it was created."
                                    )
                                    logger.warning("[AgenticLoop] 🔴 AUDIT: write_file path missing: %s", t_input["path"])
                        except Exception as e:
                            result = (
                                f"⚠️ Tool execution FAILED: {e}\n"
                                f"Do NOT tell the user this action succeeded. Report the error honestly."
                            )
                    else:
                        result = f"Unknown tool: {t_name}"
                    xml_results.append(str(result))
                    tool_calls_log.append({
                        "tool": t_name,
                        "input": t_input,
                        "output": str(result)[:500],
                    })
                    logger.info("[AgenticLoop] 📋 XML result: %s → %s",
                                t_name, str(result)[:200])

                # Strip XML tags from any surrounding text
                clean_prefix = re.sub(
                    r'<minimax:tool_call>.*?</minimax:tool_call>', '', text_response, flags=re.DOTALL
                ).strip()
                clean_prefix = re.sub(
                    r'\[TOOL_CALL\].*?\[/TOOL_CALL\]', '', clean_prefix, flags=re.DOTALL
                ).strip()

                final_output = "\n\n".join(filter(None, [clean_prefix] + xml_results))
                return {
                    "content": final_output,
                    "tool_calls": tool_calls_log,
                    "total_tokens": total_tokens,
                    "iterations": iteration,
                    "checkpoints": checkpoint_count,
                    "status": "completed",
                }

        if not tool_uses:
            clean_text = _strip_status_tags(text_response)

            # ── 審計邊界: 偵測洩漏的 tool call JSON，清掉別給用戶看 ──
            try:
                from runtime.audit import is_leaked_tool_call
                if clean_text and is_leaked_tool_call(clean_text):
                    logger.warning("[AgenticLoop] 🛡️ Stripped leaked tool call from response")
                    clean_text = "我正在處理你的請求，請稍候。"
            except Exception:
                pass

            return {
                "content": clean_text,
                "tool_calls": tool_calls_log,
                "total_tokens": total_tokens,
                "iterations": iteration,
                "checkpoints": checkpoint_count,
                "status": "completed" if status == "Project_Completed" else "done",
            }

        # ── Execute tool calls ──
        if is_openai_compat:
            # Add assistant message with tool_calls
            oai_messages.append(resp.get("assistant_message", {
                "role": "assistant", "content": text_response
            }))
        elif is_anthropic:
            oai_messages.append({
                "role": "assistant",
                "content": resp.get("content_blocks", []),
            })

        for tu in tool_uses:
            tool_name = tu.get("name", "")
            tool_input = tu.get("input", {})
            tool_id = tu.get("id", "")

            logger.info("[AgenticLoop] 🔧 executing: %s(%s)",
                         tool_name, json.dumps(tool_input, ensure_ascii=False)[:100])

            # Broadcast to Live Feed Dashboard
            try:
                import urllib.request
                import threading
                def _post_activity():
                    try:
                        req = urllib.request.Request(
                            "http://127.0.0.1:8100/v1/internal/broadcast_activity",
                            data=json.dumps({
                                "agent": "ceo",  # In the future, this can dynamic per-agent
                                "action": f"Executing Tool: {tool_name}",
                                "details": json.dumps(tool_input, ensure_ascii=False)[:300],
                                "status": "pending"
                            }).encode(),
                            headers={'Content-Type': 'application/json'}
                        )
                        urllib.request.urlopen(req, timeout=1)
                    except Exception:
                        pass
                threading.Thread(target=_post_activity, daemon=True).start()
            except Exception:
                pass

            # ── 審計邊界: delegate_* 參數防幻覺 ──
            _audit_reject = None
            try:
                from runtime.audit import check_tool_params
                _audit_reject = check_tool_params(tool_name, tool_input)
            except Exception:
                pass

            # ── V3: Governor + PolicyEngine pre-flight for high-risk tools ──
            _gov_reject = None
            if not _audit_reject and tool_name in (
                "run_command", "python_eval", "write_file", "shell_exec",
                "code_exec", "file_ops", "system_control",
                "execute_python", "execute_shell", "execute_node",
            ):
                try:
                    from governor.governor import governor as _gov
                    gov_result = _gov.evaluate_with_policy(
                        action=f"tool:{tool_name}",
                        context={
                            "skill": tool_name,
                            "command": str(tool_input.get("command", ""))[:200],
                            "session_id": _session_id if '_session_id' in dir() else "",
                        },
                    )
                    if gov_result.decision == "BLOCKED":
                        _gov_reject = f"🛡️ Governor blocked tool '{tool_name}': {gov_result.reason}"
                    elif gov_result.decision == "APPROVAL_REQUIRED":
                        _gov_reject = f"⏸️ Tool '{tool_name}' requires approval: {gov_result.reason}"
                except Exception:
                    pass  # fail-open for tool-level (main_loop already did pre-flight)

            if _audit_reject:
                result_str = _audit_reject
                logger.warning("[AgenticLoop] 🛡️ Audit blocked %s: %s",
                               tool_name, _audit_reject[:60])
            elif _gov_reject:
                result_str = _gov_reject
                logger.warning("[AgenticLoop] 🛡️ Governor blocked tool %s: %s",
                               tool_name, _gov_reject[:80])
            else:
                handler = registry.get_handler(tool_name)
                if handler:
                    try:
                        # Unwrap {"raw": "..."} LLM parameter wrapping
                        if "raw" in tool_input and len(tool_input) == 1:
                            raw_val = tool_input["raw"]
                            if isinstance(raw_val, str):
                                try:
                                    unwrapped = json.loads(raw_val)
                                    if isinstance(unwrapped, dict):
                                        tool_input = unwrapped
                                        logger.debug("[AgenticLoop] unwrapped raw param for %s", tool_name)
                                except (json.JSONDecodeError, ValueError):
                                    pass
                            elif isinstance(raw_val, dict):
                                tool_input = raw_val

                        from runtime.tracing import get_tracer
                        _tracer = get_tracer("arcmind.tool")
                        with _tracer.start_as_current_span(f"tool.{tool_name}") as _span:
                            _span.set_attribute("tool.name", tool_name)
                            _span.set_attribute("tool.input", json.dumps(tool_input, ensure_ascii=False)[:200])
                            result_str = handler(**tool_input)
                            _span.set_attribute("tool.success", True)

                        # ── Post-execution file audit ──
                        if tool_name == "write_file" and "path" in tool_input:
                            _audit_path = Path(tool_input["path"]).expanduser()
                            if not _audit_path.exists():
                                result_str = (
                                    f"⚠️ AUDIT FAIL: write_file reported success but "
                                    f"'{tool_input['path']}' does NOT exist on disk. "
                                    f"The file was NOT created. Do NOT tell the user it was created."
                                )
                                logger.warning("[AgenticLoop] 🔴 AUDIT: write_file path missing: %s", tool_input["path"])
                                _consecutive_errors += 1

                        # 成功 → reset 連續失敗計數
                        if _consecutive_errors == 0:
                            if step_retry_count > 0 and tool_name != last_error_tool:
                                step_retry_count = 0
                    except Exception as e:
                        result_str = (
                            f"⚠️ Tool execution FAILED: {e}\n"
                            f"Do NOT tell the user this action succeeded. Report the error honestly."
                        )
                        last_error_tool = tool_name
                        _consecutive_errors += 1
                else:
                    result_str = f"Unknown tool: {tool_name}"
                    _consecutive_errors += 1

            tool_calls_log.append({
                "tool": tool_name,
                "input": tool_input,
                "output": str(result_str)[:500],
                "success": _consecutive_errors == 0,  # P6: track success/fail
            })

            # P6-Layer2: Traceable tool result marker
            _marker_status = "✓" if _consecutive_errors == 0 else "✗"
            _marker = f"[TOOL_RESULT:{tool_name}] {_marker_status}"
            result_str = f"{_marker}\n{result_str}"

            logger.info("[AgenticLoop] 📋 result: %s → %s",
                         tool_name, str(result_str)[:200])

            # Add tool result in provider-specific format
            if is_openai_compat:
                oai_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": str(result_str),
                })
            elif is_anthropic:
                oai_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": str(result_str),
                    }],
                })

        # ── 「有沒有在做正事」偵測 ──

        # 1. 卡死偵測：同一 tool+params 連續重複 = 空轉
        for tu in tool_uses:
            fingerprint = f"{tu.get('name')}:{json.dumps(tu.get('input',{}), sort_keys=True)}"
            _recent_calls.append(fingerprint)
        _recent_calls = _recent_calls[-STUCK_THRESHOLD:]
        if (len(_recent_calls) >= STUCK_THRESHOLD
                and len(set(_recent_calls)) == 1):
            stuck_tool = tool_uses[0].get("name", "?")
            logger.warning("[AgenticLoop] 🔄 卡死: %s 同參數呼叫 %d 次，停止",
                           stuck_tool, STUCK_THRESHOLD)
            last_result = tool_calls_log[-1].get("output", "") if tool_calls_log else ""
            return {
                "content": last_result or f"⚠️ {stuck_tool} 重複執行 {STUCK_THRESHOLD} 次，已自動停止。",
                "tool_calls": tool_calls_log,
                "total_tokens": total_tokens,
                "iterations": iteration,
                "checkpoints": checkpoint_count,
                "status": "stuck_break",
            }

        # 2. 連續失敗偵測：tool 一直報錯 = 沒在做正事
        if _consecutive_errors >= CONSEC_ERROR_LIMIT:
            logger.warning("[AgenticLoop] ❌ 連續 %d 次 tool 失敗，停止", _consecutive_errors)
            return {
                "content": f"⚠️ 連續 {_consecutive_errors} 次工具執行失敗，已自動停止。請檢查工具配置或簡化指令。",
                "tool_calls": tool_calls_log,
                "total_tokens": total_tokens,
                "iterations": iteration,
                "checkpoints": checkpoint_count,
                "status": "error_break",
            }

        # ── Auto-prune: 保持 context 精簡，避免 MiniMax API 延遲爆炸 ──
        # MiniMax-M2.5 在 msgs>20 時延遲從 3s 飆到 30s+
        # 積極裁剪：每次超過 20 條就裁到最近 8 條
        if len(oai_messages) > 20:
            logger.info("[AgenticLoop] Auto-pruning: %d messages → keeping recent %d",
                        len(oai_messages), CHECKPOINT_PRUNE_KEEP * 2)
            oai_messages = flush_step_logs(oai_messages, keep_recent=CHECKPOINT_PRUNE_KEEP * 2)

    # while True 只會透過 return 退出，此處不可達
    # (保留作為防禦性程式碼，以防 Python 異常跳出迴圈)


# ── PM Step Execution Helper ─────────────────────────────────────────────────


def run_agentic_loop(command: str, system: str, model: str,
                     max_turns: int = 8, max_tokens: int = 4096,
                     task_type: str = "general", budget: str = "high",
                     tool_filter: list[str] | None = None) -> dict:
    """
    Lightweight wrapper around agentic_complete for PM step execution.
    Skips full MainLoop OODA cycle — goes straight to LLM + tools.

    Returns: {"output": str, "tokens_used": int}
    """
    # Default tool filter for PM: only the tools PM workers actually need
    if tool_filter is None:
        tool_filter = [
            "web_search", "run_command", "read_file", "write_file",
            "list_directory", "python_eval", "memory_query", "memory_save",
        ]

    result = agentic_complete(
        prompt=command,
        system=system,
        model=model,
        task_type=task_type,
        budget=budget,
        max_tokens=max_tokens,
        tools_enabled=True,
        tool_filter=tool_filter,
    )

    return {
        "output": result.get("output", ""),
        "tokens_used": result.get("total_tokens", 0),
    }


# ── Tag Parsing Helpers ──────────────────────────────────────────────────────

def _parse_status_tags(text: str) -> tuple[str, str]:
    """
    Parse <Status> and <State_Summary> tags from LLM response text.
    Returns (status, state_summary).
    Status: 'Checkpoint_Passed' | 'Retry' | 'Project_Completed' | ''
    """
    if not text:
        return ("", "")

    status = ""
    summary = ""

    status_match = re.search(r"<Status>\s*(.*?)\s*</Status>", text, re.IGNORECASE | re.DOTALL)
    if status_match:
        raw = status_match.group(1).strip()
        # Normalize to known values
        if "checkpoint" in raw.lower() or "passed" in raw.lower():
            status = "Checkpoint_Passed"
        elif "retry" in raw.lower():
            status = "Retry"
        elif "complete" in raw.lower() or "done" in raw.lower():
            status = "Project_Completed"
        else:
            status = raw  # pass through unknown

    summary_match = re.search(
        r"<State_Summary>\s*(.*?)\s*</State_Summary>", text, re.IGNORECASE | re.DOTALL
    )
    if summary_match:
        summary = summary_match.group(1).strip()

    return (status, summary)


def _strip_status_tags(text: str) -> str:
    """Remove <Status> and <State_Summary> tags from text for clean output."""
    if not text:
        return text
    text = re.sub(r"<Status>.*?</Status>\s*", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<State_Summary>.*?</State_Summary>\s*", "", text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()


# ── OpenAI-compatible Helper (OLLAMA / OpenAI / Groq / Mistral) ──────────────


def _safe_arguments_json(raw: str | None) -> str:
    """Ensure arguments is always valid JSON to prevent API 400 errors on echo-back."""
    if not raw:
        return "{}"
    try:
        json.loads(raw)  # validate
        return raw
    except (json.JSONDecodeError, TypeError):
        logger.warning("[AgenticLoop] Sanitized malformed tool arguments: %s", raw[:100])
        return "{}"


def _schemas_to_openai_tools(schemas: list[dict]) -> list[dict]:
    """Convert our tool schemas to OpenAI function calling format."""
    tools = []
    for s in schemas:
        tools.append({
            "type": "function",
            "function": {
                "name": s["name"],
                "description": s["description"],
                "parameters": s["input_schema"],
            },
        })
    return tools


def _openai_call_with_tools(
    provider, model_id: str, messages: list[dict],
    max_tokens: int, tools: list[dict] | None,
) -> dict:
    """
    Call OpenAI-compatible API with function calling.
    Works with OLLAMA, OpenAI, Groq, Mistral, LM Studio, etc.
    """
    client = provider._client

    kwargs: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "max_tokens": max_tokens,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    _t0 = time.time()
    resp = client.chat.completions.create(**kwargs)
    _elapsed = time.time() - _t0
    if _elapsed > 15:
        logger.warning("[AgenticLoop] ⏱️ LLM API slow: %.1fs (model=%s, msgs=%d)",
                       _elapsed, model_id, len(messages))
    else:
        logger.info("[AgenticLoop] ⏱️ LLM API: %.1fs (model=%s)", _elapsed, model_id)
    choice = resp.choices[0]
    message = choice.message

    usage = resp.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0

    # Parse tool calls
    tool_uses = []
    if message.tool_calls:
        for tc in message.tool_calls:
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {"raw": tc.function.arguments}

            tool_uses.append({
                "id": tc.id,
                "name": tc.function.name,
                "input": args,
            })

    # Build the assistant message to echo back (needed for multi-turn)
    assistant_msg: dict[str, Any] = {
        "role": "assistant",
        "content": message.content or "",
    }
    if message.tool_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": _safe_arguments_json(tc.function.arguments),
                },
            }
            for tc in message.tool_calls
        ]

    return {
        "text": message.content or "",
        "tool_uses": tool_uses,
        "stop_reason": choice.finish_reason or "stop",
        "total_tokens": in_tok + out_tok,
        "assistant_message": assistant_msg,
    }


# ── Anthropic Helper ─────────────────────────────────────────────────────────

def _anthropic_call_with_tools(
    provider, model_id: str, messages: list[dict],
    system: str | None, max_tokens: int,
    tool_schemas: list[dict],
) -> dict:
    """Call Anthropic API with tool definitions."""
    import anthropic as _anthropic

    client = provider._client
    kwargs: dict[str, Any] = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if tool_schemas:
        kwargs["tools"] = tool_schemas

    _t0 = time.time()
    resp = client.messages.create(**kwargs)
    _elapsed = time.time() - _t0
    if _elapsed > 15:
        logger.warning("[AgenticLoop] ⏱️ Anthropic API slow: %.1fs (model=%s, msgs=%d)",
                       _elapsed, model_id, len(messages))
    else:
        logger.info("[AgenticLoop] ⏱️ Anthropic API: %.1fs (model=%s)", _elapsed, model_id)

    text_parts = []
    content_blocks = []
    tool_uses = []

    for block in resp.content:
        if hasattr(block, "text"):
            text_parts.append(block.text)
            content_blocks.append({"type": "text", "text": block.text})
        elif hasattr(block, "type") and block.type == "tool_use":
            cb = {"type": "tool_use", "id": block.id,
                  "name": block.name, "input": block.input}
            content_blocks.append(cb)
            tool_uses.append(cb)

    return {
        "text": "".join(text_parts),
        "content_blocks": content_blocks,
        "tool_uses": tool_uses,
        "stop_reason": resp.stop_reason or "end_turn",
        "total_tokens": resp.usage.input_tokens + resp.usage.output_tokens,
    }


# ── Singleton ──
tool_registry = ToolRegistry()
