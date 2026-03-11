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
import re
import logging
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("arcmind.tool_loop")


# ── Heartbeat tracking (for gateway stall detection) ──
import threading as _threading
import time as _time

_heartbeat_lock = _threading.Lock()
_heartbeats = {}  # thread_id -> {ts, iteration, action}


def _update_heartbeat(iteration: int, action: str = ""):
    """Update heartbeat for current thread."""
    tid = _threading.get_ident()
    with _heartbeat_lock:
        _heartbeats[tid] = {
            "ts": _time.time(),
            "iteration": iteration,
            "action": action,
        }


def get_heartbeat_by_thread(thread_id: int):
    """Get heartbeat for a specific thread (called from gateway)."""
    with _heartbeat_lock:
        return _heartbeats.get(thread_id)


def clear_heartbeat_by_thread(thread_id: int):
    """Clear heartbeat for a specific thread."""
    with _heartbeat_lock:
        _heartbeats.pop(thread_id, None)


# Maximum number of tool loop iterations to prevent infinite loops
MAX_TOOL_ITERATIONS = 50


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

    def get_schema(self, name: str) -> dict | None:
        """Get the registered schema for a single tool by name."""
        tool = self._tools.get(name)
        if tool:
            return {
                "name": tool["name"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            }
        return None

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def _register_builtin_tools(self) -> None:
        """Register built-in tools available to the agent."""

        # ── Web Search ────────────────────────────────────────────────
        self.register(
            name="web_search",
            description="Search the web for information. Returns search results.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results (default 5)",
                    },
                },
                "required": ["query"],
            },
            handler=_tool_web_search,
        )

        # ── Read URL Content ─────────────────────────────────────────
        self.register(
            name="read_url_content",
            description="读取URL网页内容工具 - 获取任何URL/链接/网址的文本内容。用于：分析文章、读取网页、获取微信公众号文章、读取新闻。输入URL返回纯文本。Fetch URL content, read web page, analyze article.",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要读取的URL地址",
                    },
                },
                "required": ["url"],
            },
            handler=_tool_read_url_content,
        )

        # ── Shell Command ─────────────────────────────────────────────
        self.register(
            name="run_command",
            description="Execute a shell command on the local system. Returns stdout and stderr. Default timeout is 120s. For long operations (docker pull/build, pip install, apt install), set timeout=300 or timeout=600. Max timeout is 600s.",
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
                "⚠️ 仅用于需要长时间在后台运行的任务（如：持续监控、定时报告、大规模批量处理）。"
                "⛔ 禁止用于：分析文章/URL、搜索信息、端口扫描、回答问题等日常任务。"
                "这些任务你应该自己用 read_url_content / web_search / security_port_scan 等工具完成。\n"
                "可用 Agent: search, code, analysis, qa, devops, windows"
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
            description="⚠️ 仅用于复杂多步骤项目的流水线。日常任务禁止使用。",
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
                "Use list_skills first to see available skills and their actions. "
                "Skills include: github_skill (GitHub operations), "
                "document_skill (PPT/Excel generation with template learning), "
                "daily_report (morning briefings), self_iteration (system self-improvement). "
                "The 'inputs' object is passed directly to the skill handler."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "description": "Name of the skill to invoke (e.g. github_skill, document_skill)",
                    },
                    "inputs": {
                        "type": "object",
                        "description": "Input parameters for the skill. Each skill has different 'action' values. Check list_skills for details.",
                    },
                },
                "required": ["skill_name", "inputs"],
            },
            handler=_tool_invoke_skill,
        )
        self.register(
            name="list_skills",
            description="List all available ArcMind skills and their capabilities.",
            input_schema={
                "type": "object",
                "properties": {},
            },
            handler=_tool_list_skills,
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

        # ── Security Scan Tools ──────────────────────────────────────────
        try:
            self.register(
                name="security_port_scan",
                description="端口扫描工具 - 使用 nmap 扫描目标的开放端口和服务。支持快速扫描、标准扫描、全端口扫描、服务识别、漏洞扫描。scan_type: quick/standard/full/service/vuln",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "目标 IP 或域名"},
                        "scan_type": {"type": "string", "description": "扫描类型: quick/standard/full/service/vuln"},
                        "ports": {"type": "string", "description": "自定义端口范围"},
                    },
                    "required": ["target"],
                },
                handler=_tool_security_port_scan,
            )
            self.register(
                name="security_web_scan",
                description="使用 nikto 扫描 Web 服务器漏洞 (OWASP Top 10, 配置错误等)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "目标主机"},
                        "port": {"type": "integer", "description": "端口号"},
                        "ssl": {"type": "boolean", "description": "是否 SSL"},
                    },
                    "required": ["target"],
                },
                handler=_tool_security_web_scan,
            )
            self.register(
                name="security_system_audit",
                description="使用 lynis 执行系统安全审计 (检查防火墙/SSH/权限/内核等)",
                input_schema={"type": "object", "properties": {}},
                handler=_tool_security_system_audit,
            )
            self.register(
                name="security_ssl_check",
                description="检查 SSL/TLS 证书有效性、过期时间和弱协议",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "目标域名"},
                        "port": {"type": "integer", "description": "SSL 端口"},
                    },
                    "required": ["target"],
                },
                handler=_tool_security_ssl_check,
            )
            self.register(
                name="security_dns_recon",
                description="DNS 信息收集 — A/MX/NS/TXT 记录 + WHOIS",
                input_schema={
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "目标域名"},
                    },
                    "required": ["domain"],
                },
                handler=_tool_security_dns_recon,
            )
            self.register(
                name="security_code_audit",
                description="使用 bandit 审计 Python 代码安全漏洞 (SQL注入/XSS/硬编码密码等)",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "审计目录或文件路径"},
                        "severity": {"type": "string", "description": "最低级别: low/medium/high"},
                    },
                    "required": ["path"],
                },
                handler=_tool_security_code_audit,
            )
            self.register(
                name="security_infra_check",
                description="基础设施安全检查 — 监听端口/防火墙/SSH/用户权限/自动更新",
                input_schema={"type": "object", "properties": {}},
                handler=_tool_security_infra_check,
            )
            self.register(
                name="security_full_audit",
                description="一键综合安全审计 (端口扫描+系统审计+代码审计+依赖检查+基础设施) 并生成报告",
                input_schema={
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "description": "扫描目标"},
                        "include_web": {"type": "boolean", "description": "是否包含 Web 漏洞扫描"},
                    },
                },
                handler=_tool_security_full_audit,
            )
            logger.info("[ToolRegistry] Security scan tools loaded (8 tools)")
        except Exception as e:
            logger.warning("[ToolRegistry] Security tools not loaded: %s", e)


# ── Security Scan Tool Implementations ─────────────────────────────────────

def _tool_security_port_scan(target: str, scan_type: str = "quick", ports: str = "", **kw) -> str:
    try:
        from skills.security_scan import port_scan
        result = port_scan(target, scan_type, ports)
        if result.get("open_ports"):
            lines = ["Port scan for %s (%s):" % (target, scan_type)]
            lines.append("Found %d open ports:" % result["port_count"])
            for p in result["open_ports"]:
                lines.append("  %s %s %s" % (p["port"], p["state"], p["service"]))
            return "\n".join(lines)
        return "Port scan for %s: no open ports found." % target
    except Exception as e:
        return "Port scan error: %s" % e

def _tool_security_web_scan(target: str, port: int = 80, ssl: bool = False, **kw) -> str:
    try:
        from skills.security_scan import web_vuln_scan
        result = web_vuln_scan(target, port, ssl)
        if result.get("findings"):
            lines = ["Web scan for %s:%d:" % (target, port)]
            lines.append("Found %d findings:" % result["finding_count"])
            for f in result["findings"][:15]:
                lines.append("  %s" % f)
            return "\n".join(lines)
        return "Web scan for %s:%d: no significant findings." % (target, port)
    except Exception as e:
        return "Web scan error: %s" % e

def _tool_security_system_audit(**kw) -> str:
    try:
        from skills.security_scan import system_audit
        r = system_audit()
        lines = ["System Audit (lynis):"]
        lines.append("  Hardening Index: %s/100" % r.get("hardening_index", "N/A"))
        lines.append("  Warnings: %d" % r.get("warning_count", 0))
        lines.append("  Suggestions: %d" % r.get("suggestion_count", 0))
        if r.get("warnings"):
            lines.append("\nTop warnings:")
            for w in r["warnings"][:10]:
                lines.append("  %s" % w)
        return "\n".join(lines)
    except Exception as e:
        return "System audit error: %s" % e

def _tool_security_ssl_check(target: str, port: int = 443, **kw) -> str:
    try:
        from skills.security_scan import ssl_check
        r = ssl_check(target, port)
        lines = ["SSL/TLS check for %s:%d:" % (target, port)]
        lines.append("  Cert: %s" % r.get("cert_info", "N/A"))
        weak = r.get("weak_protocols", [])
        if weak:
            lines.append("  WARNING: Weak protocols: %s" % ", ".join(weak))
        else:
            lines.append("  OK: No weak protocols detected")
        return "\n".join(lines)
    except Exception as e:
        return "SSL check error: %s" % e

def _tool_security_dns_recon(domain: str, **kw) -> str:
    try:
        from skills.security_scan import dns_recon
        r = dns_recon(domain)
        lines = ["DNS Recon for %s:" % domain]
        lines.append("  A: %s" % ", ".join(r.get("a_records", [])))
        lines.append("  MX: %s" % ", ".join(r.get("mx_records", [])))
        lines.append("  NS: %s" % ", ".join(r.get("ns_records", [])))
        return "\n".join(lines)
    except Exception as e:
        return "DNS recon error: %s" % e

def _tool_security_code_audit(path: str, severity: str = "medium", **kw) -> str:
    try:
        from skills.security_scan import code_audit
        r = code_audit(path, severity)
        lines = ["Code Audit (%s):" % path]
        lines.append("  Issues: %d (severity >= %s)" % (r.get("issue_count", 0), severity))
        if r.get("issues"):
            lines.append("\nTop issues:")
            for i in r["issues"][:10]:
                lines.append("  [%s] %s:%s - %s" % (i["severity"], i["file"], i["line"], i["text"]))
        return "\n".join(lines)
    except Exception as e:
        return "Code audit error: %s" % e

def _tool_security_infra_check(**kw) -> str:
    try:
        from skills.security_scan import infra_security_check
        r = infra_security_check()
        lines = ["Infrastructure Security:"]
        lines.append("  Users: %s" % ", ".join(r.get("login_users", [])))
        ssh_issues = r.get("ssh_issues", [])
        for s in ssh_issues:
            lines.append("  SSH WARNING: %s" % s)
        if not ssh_issues:
            lines.append("  SSH: OK")
        lines.append("  Auto-updates: %s" % r.get("auto_updates", "unknown"))
        lines.append("\nListening ports:\n%s" % r.get("listening_ports", "N/A"))
        return "\n".join(lines)
    except Exception as e:
        return "Infra check error: %s" % e

def _tool_security_full_audit(target: str = "localhost", include_web: bool = False, **kw) -> str:
    try:
        from skills.security_scan import full_security_audit
        r = full_security_audit(target, include_web)
        s = r.get("summary", {})
        lines = ["=" * 50, "COMPREHENSIVE SECURITY AUDIT", "=" * 50]
        lines.append("Target: %s" % target)
        lines.append("Total issues: %d" % s.get("total_issues", 0))
        lines.append("Report: %s" % r.get("report_path", "N/A"))
        for name, data in r.get("sections", {}).items():
            if isinstance(data, dict):
                if "error" in data:
                    lines.append("  %s: ERROR - %s" % (name, data["error"]))
                elif "port_count" in data:
                    lines.append("  %s: %d open ports" % (name, data["port_count"]))
                elif "hardening_index" in data:
                    lines.append("  %s: hardening=%s, warnings=%d" % (name, data["hardening_index"], data.get("warning_count", 0)))
                elif "issue_count" in data:
                    lines.append("  %s: %d issues" % (name, data["issue_count"]))
                elif "vulnerable_packages" in data:
                    lines.append("  %s: %d vulnerable" % (name, data["vulnerable_packages"]))
        return "\n".join(lines)
    except Exception as e:
        return "Full audit error: %s" % e


# ── Tool Implementations ─────────────────────────────────────────────────────

def _tool_read_url_content(url: str, **kwargs) -> str:
    """Fetch and return the text content of a URL."""
    import urllib.request
    import re as _re
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].strip()
            raw = resp.read()
            html = raw.decode(charset, errors="replace")

        # Strip HTML tags to get text content
        # Remove script and style blocks first
        html = _re.sub(r'<script[^>]*>.*?</script>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
        html = _re.sub(r'<style[^>]*>.*?</style>', '', html, flags=_re.DOTALL | _re.IGNORECASE)
        # Remove HTML comments
        html = _re.sub(r'<!--.*?-->', '', html, flags=_re.DOTALL)
        # Replace br/p/div/li tags with newlines
        html = _re.sub(r'<br\s*/?>|</p>|</div>|</li>|</h[1-6]>', '\n', html, flags=_re.IGNORECASE)
        # Remove remaining HTML tags
        text = _re.sub(r'<[^>]+>', '', html)
        # Clean up whitespace
        text = _re.sub(r'\n\s*\n+', '\n\n', text)
        text = text.strip()

        # Truncate if too long
        if len(text) > 4000:
            text = text[:4000] + "\n\n... (内容已截断，共 %d 字符)" % len(text)

        return f"URL: {url}\n\n{text}" if text else f"URL: {url}\n(页面内容为空或无法解析)"
    except Exception as e:
        return f"读取URL失败: {url}\n错误: {e}"


def _tool_web_search(query: str, max_results: int = 5, **kwargs) -> str:
    """Web search using ddgs."""
    try:
        max_results = int(max_results)
        from ddgs import DDGS
        results = DDGS().text(query, max_results=max_results)
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(f"**{r.get('title', '')}**")
            lines.append(f"  {r.get('body', '')[:200]}")
            lines.append(f"  URL: {r.get('href', '')}")
            lines.append("")
        return "\n".join(lines)
    except Exception as e:
        return f"Search error: {e}"


def _tool_run_command(command: str, timeout: int = 120, **kwargs) -> str:
    """Execute a shell command with safety restrictions.

    Uses shell=False with shlex.split to prevent command injection.
    Blocks dangerous commands via whitelist approach.
    """
    import shlex

    # ── Blocked command patterns ──
    _BLOCKED = [
        "rm -rf /", "rm -rf ~", "mkfs", "dd if=", "> /dev/",
        ":(){ :|:& };:", "chmod -R 777 /", "shutdown", "reboot",
        "halt", "init 0", "init 6",
    ]
    cmd_lower = command.lower().strip()
    for pat in _BLOCKED:
        if pat in cmd_lower:
            return f"Blocked: dangerous command pattern '{pat}' detected."

    try:
        # Parse command safely — no shell injection
        args = shlex.split(command)
        if not args:
            return "Empty command."

        result = subprocess.run(
            args,
            shell=False,
            capture_output=True,
            text=True,
            timeout=min(timeout, 600),  # Cap at 2 minutes
            cwd=str(Path.home()),
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


def _tool_read_file(path: str, **kwargs) -> str:
    """Read a file with path traversal protection."""
    try:
        p = Path(path).expanduser().resolve()
        # Block access to sensitive system paths
        _SENSITIVE = ["/etc/shadow", "/etc/passwd", "/proc", "/sys",
                      "/.ssh", "/id_rsa", "/.gnupg", "/.aws/credentials"]
        for s in _SENSITIVE:
            if s in str(p):
                return f"Access denied: path contains sensitive location '{s}'"
        if p.is_symlink():
            return f"Access denied: symlinks are not followed for security"
        if not p.exists():
            return f"File not found: {path}"
        if p.stat().st_size > 100_000:
            return f"File too large ({p.stat().st_size} bytes). Read first 5000 chars.\n\n" + p.read_text(encoding="utf-8")[:5000]
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Read error: {e}"


def _tool_write_file(path: str, content: str, **kwargs) -> str:
    """Write a file with path traversal protection."""
    try:
        p = Path(path).expanduser().resolve()
        # Block writing to sensitive system paths
        _BLOCKED_ROOTS = ["/etc", "/usr", "/bin", "/sbin", "/boot",
                          "/proc", "/sys", "/dev", "/root"]
        for root in _BLOCKED_ROOTS:
            if str(p).startswith(root):
                return f"Access denied: cannot write to system path '{root}'"
        # Block overwriting critical project config files
        _PROTECTED_NAMES = [".env", "settings.py", "agents.json",
                            "routing_rules.yaml", "requirements.txt",
                            "main.py", "Makefile", "docker-compose.yml"]
        if p.name in _PROTECTED_NAMES:
            return f"Access denied: '{p.name}' is a protected config file. Manual edit required."
        if p.is_symlink():
            return f"Access denied: will not write through symlinks"
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


def _tool_python_eval(code: str, **kwargs) -> str:
    """Evaluate Python code in a restricted sandbox.

    Only safe built-ins are exposed. Dangerous modules (os, sys, subprocess,
    shutil, importlib, etc.) are blocked. The code runs in an isolated
    namespace so it cannot access the ArcMind runtime.
    """
    # ── Blocked patterns (static check before execution) ──
    _BLOCKED_PATTERNS = [
        "__import__", "importlib", "subprocess", "os.system", "os.popen",
        "shutil", "exec(", "eval(", "compile(", "open(",
        "globals(", "locals(", "getattr(", "setattr(", "delattr(",
        "__builtins__", "__class__", "__subclasses__",
    ]
    code_lower = code.lower()
    for pat in _BLOCKED_PATTERNS:
        if pat.lower() in code_lower:
            return f"Blocked: '{pat}' is not allowed in sandboxed Python eval."

    # ── Safe builtins whitelist ──
    _SAFE_BUILTINS = {
        "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
        "chr": chr, "dict": dict, "dir": dir, "divmod": divmod,
        "enumerate": enumerate, "filter": filter, "float": float,
        "format": format, "frozenset": frozenset, "hash": hash,
        "hex": hex, "int": int, "isinstance": isinstance,
        "issubclass": issubclass, "iter": iter, "len": len, "list": list,
        "map": map, "max": max, "min": min, "next": next, "oct": oct,
        "ord": ord, "pow": pow, "print": print, "range": range,
        "repr": repr, "reversed": reversed, "round": round, "set": set,
        "slice": slice, "sorted": sorted, "str": str, "sum": sum,
        "tuple": tuple, "type": type, "zip": zip,
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
        # Try eval first (for expressions)
        try:
            result = eval(code, sandbox_globals, local_vars)
            return str(result)
        except SyntaxError:
            pass

        # Fall back to exec (for statements)
        exec(code, sandbox_globals, local_vars)

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
        result = skill_manager.invoke(skill_name, inputs or {})
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


# ── Agent Template Tools ──────────────────────────────────────────────────────

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


def _tool_send_webhook(
    url: str,
    payload: dict | None = None,
    method: str = "POST",
    **kwargs,
) -> str:
    """Send a webhook to an external service."""
    try:
        import urllib.request
        import json as _json
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


# ── Tool Argument Type Coercion ─────────────────────────────────────
def _coerce_tool_args(tool_name: str, args: dict, registry) -> dict:
    """
    Coerce tool arguments to their declared types based on input_schema.
    Fixes: LLM often passes "1" (string) instead of 1 (int) for integer params.
    """
    try:
        schema = registry.get_schema(tool_name)
        if not schema:
            return args
        properties = schema.get("input_schema", {}).get("properties", {})
        coerced = {}
        for key, value in args.items():
            if key in properties:
                declared_type = properties[key].get("type", "string")
                try:
                    if declared_type == "integer" and not isinstance(value, int):
                        coerced[key] = int(value)
                    elif declared_type == "number" and not isinstance(value, (int, float)):
                        coerced[key] = float(value)
                    elif declared_type == "boolean" and not isinstance(value, bool):
                        coerced[key] = str(value).lower() in ("true", "1", "yes")
                    elif declared_type == "string" and not isinstance(value, str):
                        coerced[key] = str(value)
                    else:
                        coerced[key] = value
                except (ValueError, TypeError):
                    coerced[key] = value
            else:
                coerced[key] = value
        return coerced
    except Exception:
        return args

# ── Text-mode Tool Call Fallback Parser ──────────────────────────────
def _extract_tool_calls_from_text(text: str, registry) -> list[dict]:
    """
    Fallback parser: extract tool calls from LLM text when it outputs
    function calls as text instead of using structured tool_calls format.
    Common with weaker models (70B, etc.)
    """
    if not text:
        return []
    tool_uses = []
    # Pattern 1: JSON-like {"name": "tool_name", "arguments": {...}}
    json_pattern = r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"(?:arguments|parameters)"\s*:\s*(\{[^}]*\})'
    for m in re.finditer(json_pattern, text):
        tool_name = m.group(1)
        if registry.get_handler(tool_name):
            try:
                args = json.loads(m.group(2))
                tool_uses.append({
                    "id": "text_fallback_%d" % len(tool_uses),
                    "name": tool_name,
                    "input": args,
                })
            except json.JSONDecodeError:
                pass
    if tool_uses:
        return tool_uses
    # Pattern 2: tool_name({"key": "value"}) or tool_name({key: value})
    func_pattern = r'(\w+)\s*\(\s*(\{[^)]*\})\s*\)'
    for m in re.finditer(func_pattern, text):
        tool_name = m.group(1)
        if registry.get_handler(tool_name):
            try:
                args = json.loads(m.group(2))
                tool_uses.append({
                    "id": "text_fallback_%d" % len(tool_uses),
                    "name": tool_name,
                    "input": args,
                })
            except json.JSONDecodeError:
                pass
    return tool_uses



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

    registry = tool_registry  # singleton
    # ── P1-4: 語義工具篩選 ──
    if tools_enabled:
        all_schemas = registry.get_schemas()
        # CEO主导原则：从工具列表中排除委派类工具，防止CEO偷懒
        _CEO_BLOCKED_TOOLS = {"delegate_task", "delegate_pipeline", "fire_agent", "agent_handoff"}

        if tool_filter is not None:  # None=all tools, []=no tools
            # 只暴露指定的工具 schema
            tool_schemas = [s for s in all_schemas if s["name"] in tool_filter and s["name"] not in _CEO_BLOCKED_TOOLS]
            # 安全閥：如果過濾後太少，保留全部
            # 但 tool_filter=[] (顯式空列表) 表示「不需要工具」，跳過安全閥
            if len(tool_schemas) < 3 and len(tool_filter) > 0:
                tool_schemas = [s for s in all_schemas if s["name"] not in _CEO_BLOCKED_TOOLS]
            else:
                logger.info("[AgenticLoop] Tool filter active: %d/%d tools exposed",
                            len(tool_schemas), len(all_schemas))
        else:
            # 無指定 tool_filter → 使用全部工具（語義篩選已由 main_loop 處理，
            # 避免此處重複呼叫 CapabilitySelector 增加 2-5s 延遲）
            tool_schemas = [s for s in all_schemas if s["name"] not in _CEO_BLOCKED_TOOLS]
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
    if prompt and not messages:  # Only for new conversations (not continuations)
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
    GLOBAL_FAIL_SAFE = 200        # absolute maximum iterations
    MAX_STEP_RETRIES = 5          # max retries for a single step
    CHECKPOINT_PRUNE_KEEP = 4     # keep last N tool messages after pruning

    iteration = 0
    audit_retry_count = 0  # LLM audit retry counter
    no_tool_streak = 0        # consecutive iterations without tool calls
    step_retry_count = 0       # retries for current step
    last_error_tool = ""       # track which tool is failing
    checkpoint_count = 0       # number of checkpoints passed
    # Repeat tool call detection
    _recent_tool_calls = []
    REPEAT_THRESHOLD = 10

    while iteration < GLOBAL_FAIL_SAFE:
        iteration += 1
        _update_heartbeat(iteration, "start")
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
                # Remove last assistant + tool messages (the problematic exchange)
                while oai_messages and oai_messages[-1].get("role") in ("tool", "assistant"):
                    oai_messages.pop()
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
        stop_reason = resp.get("stop_reason", "stop")

        # ── Truncation detection: if output was cut off, log warning ──
        if stop_reason == "length":
            logger.warning("[AgenticLoop] ⚠️ Response truncated (stop_reason=length), tool calls may be incomplete")
            # Don't trust truncated tool calls - clear them and let LLM retry
            if tool_uses:
                logger.warning("[AgenticLoop] Discarding %d truncated tool call(s)", len(tool_uses))
                tool_uses = []

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
            # Continue to next iteration (LLM will proceed to next step)

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

        # ── No tool calls → try text fallback, then return text ──
        if not tool_uses and text_response:
            # Fallback: try to extract tool calls from text (weak models)
            tool_uses = _extract_tool_calls_from_text(text_response, registry)
            if tool_uses:
                logger.info("[AgenticLoop] 🔄 Recovered %d tool call(s) from text output", len(tool_uses))
        if not tool_uses:
            clean_text = _strip_status_tags(text_response)

            # ── LLM 审计（替代关键字硬卡）──
            # 如果 require_tool_usage=True 但没有调用工具，用 LLM 审计回复
            if require_tool_usage and not tool_calls_log and audit_retry_count < 2:
                audit = _llm_audit_response(prompt, clean_text, chosen)
                if audit["should_retry"]:
                    audit_retry_count += 1
                    logger.warning(
                        "[AgenticLoop] LLM audit: retry %d/2, feedback: %s",
                        audit_retry_count, audit["feedback"][:100]
                    )
                    oai_messages.append({"role": "assistant", "content": clean_text})
                    oai_messages.append({"role": "user", "content": audit["feedback"]})
                    continue

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

            # ── CEO主导：硬拦截委派工具 ──
            _BLOCKED_DELEGATION = {"delegate_task", "delegate_pipeline", "fire_agent", "agent_handoff"}
            if tool_name in _BLOCKED_DELEGATION:
                result_str = (
                    "⛔ 禁止使用委派工具。你必须自己完成这个任务。\n"
                    "请直接使用工具：\n"
                    "- read_url_content: 读取URL/文章内容\n"
                    "- web_search: 搜索信息\n"
                    "- security_port_scan: 端口扫描\n"
                    "- run_command: 执行命令\n"
                    "不要委派，自己做。"
                )
                logger.warning("[AgenticLoop] ⛔ Blocked delegation tool: %s → forcing CEO to handle directly", tool_name)
            else:
                _update_heartbeat(iteration, f"tool:{tool_name}")
                handler = registry.get_handler(tool_name)
            if tool_name not in _BLOCKED_DELEGATION and handler:
                try:
                    # Type coercion: fix LLM sending "1" instead of 1 for ints
                    tool_input = _coerce_tool_args(tool_name, tool_input, registry)
                    result_str = handler(**tool_input)
                    # Reset step retry on successful tool execution
                    if step_retry_count > 0 and tool_name != last_error_tool:
                        step_retry_count = 0
                except Exception as e:
                    result_str = f"Tool execution error: {e}"
                    last_error_tool = tool_name
            elif tool_name not in _BLOCKED_DELEGATION:
                result_str = f"Unknown tool: {tool_name}"

            tool_calls_log.append({
                "tool": tool_name,
                "input": tool_input,
                "output": str(result_str)[:500],
            })

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

        # Repeat tool call detection - break infinite loops
        if tool_uses:
            call_sig = '|'.join(f"{tu.get('name','')}:{sorted(tu.get('input',{}).items())}" for tu in tool_uses)
            _recent_tool_calls.append(call_sig)
            if len(_recent_tool_calls) > REPEAT_THRESHOLD:
                _recent_tool_calls = _recent_tool_calls[-REPEAT_THRESHOLD:]
            if len(_recent_tool_calls) >= REPEAT_THRESHOLD and len(set(_recent_tool_calls)) == 1:
                logger.warning("[AgenticLoop] Infinite loop detected: same tool call repeated %d times, breaking", REPEAT_THRESHOLD)
                return {
                    "content": "System detected infinite loop, auto-terminated.\n"
                               f"Repeated call: {tool_uses[0].get('name','')}\n"
                               f"Iterations: {iteration}",
                    "tool_calls": tool_calls_log,
                    "total_tokens": total_tokens,
                    "iterations": iteration,
                    "checkpoints": checkpoint_count,
                    "status": "loop_detected",
                }

        # ── Dead loop detection: no tool calls for too many iterations ──
        if tool_uses:
            no_tool_streak = 0
        else:
            no_tool_streak += 1
            if require_tool_usage and no_tool_streak >= 5 and no_tool_streak < 8:
                logger.warning("[AgenticLoop] ⚠️ No tool calls for %d consecutive iterations", no_tool_streak)
                oai_messages.append({"role": "user", "content":
                    "你已经连续多次回复都没有调用任何工具。你必须使用 run_command、write_file 等工具来完成任务。"
                    "如果你无法完成，请明确说明原因。不要再重复描述步骤。"
                })
            elif require_tool_usage and no_tool_streak >= 8:
                logger.error("[AgenticLoop] 🔴 Dead loop: %d iterations without tool calls, terminating", no_tool_streak)
                return {
                    "content": f"⚠️ 检测到空转循环：连续{no_tool_streak}次回复没有调用工具，已终止。请重新描述需求。",
                    "tool_calls": tool_calls_log,
                    "total_tokens": total_tokens,
                    "iterations": iteration,
                    "checkpoints": checkpoint_count,
                    "status": "dead_loop",
                }
        _update_heartbeat(iteration, "loop_end", )

        # ── Auto-prune if messages getting too long (token pressure relief) ──
        if len(oai_messages) > 40 and iteration % 10 == 0:
            logger.info("[AgenticLoop] Auto-pruning: %d messages → context pressure", len(oai_messages))
            oai_messages = flush_step_logs(oai_messages, keep_recent=CHECKPOINT_PRUNE_KEEP * 2)

    # ── Global fail-safe reached ──
    summary_parts = [f"已執行 {GLOBAL_FAIL_SAFE} 步全局上限。"]
    for msg in reversed(oai_messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            content = msg["content"]
            if isinstance(content, str) and content.strip():
                summary_parts.append(content.strip())
                break
    if tool_calls_log:
        tool_names = [tc.get("tool", "?") for tc in tool_calls_log[-10:]]
        summary_parts.append(f"最近執行的工具: {', '.join(tool_names)}")
    return {
        "content": "\n\n".join(summary_parts),
        "tool_calls": tool_calls_log,
        "total_tokens": total_tokens,
        "iterations": GLOBAL_FAIL_SAFE,
        "checkpoints": checkpoint_count,
        "status": "fail_safe",
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



def _normalize_content(content):
    """Normalize LLM response content to a plain string.
    Some models (kimi-k2) return content in non-standard formats:
    - list of content blocks: [{'type': 'text', 'text': '...'}]
    - single content block dict: {'type': 'text', 'text': '...'}
    - ContentBlock objects with .text attribute
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # Single dict content block
    if isinstance(content, dict):
        return content.get("text", content.get("content", "")) or ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", block.get("content", ""))
                if text:
                    parts.append(str(text))
            elif isinstance(block, str):
                parts.append(block)
            elif hasattr(block, "text"):
                # ContentBlock objects
                if block.text:
                    parts.append(str(block.text))
        return "\n".join(parts) if parts else ""
    # Object with .text attribute
    if hasattr(content, "text"):
        return str(content.text) if content.text else ""
    # Last resort: convert to string but filter content-block patterns
    s = str(content)
    if s.startswith("{") and "'type': 'text'" in s:
        # This is a stringified content block - extract the text value
        import ast
        try:
            d = ast.literal_eval(s)
            if isinstance(d, dict):
                return d.get("text", d.get("content", "")) or ""
        except (ValueError, SyntaxError):
            pass
    return s



def _llm_audit_response(user_prompt: str, ai_response: str, model: str) -> dict:
    """LLM-based response audit. Replaces hard-coded guard layers.
    Checks if the AI response appropriately addresses the user's request.
    Returns: {"should_retry": bool, "feedback": str}
    """
    from runtime.model_router import model_router
    try:
        truncated = ai_response[:800] if len(ai_response) > 800 else ai_response
        audit_prompt = (
            "你是AI回复审计器。用户要求AI执行一个操作任务，但AI没有调用任何工具就回复了。\n\n"
            f"用户请求: {user_prompt[:300]}\n\n"
            f"AI回复: {truncated}\n\n"
            "请判断AI的回复是否存在以下问题：\n"
            "1. AI只是描述/解释操作步骤，而没有用工具实际执行（应该用run_command执行命令）\n"
            "2. AI展示了代码块/命令/YAML/配置文件，而不是用run_command或write_file实际执行\n"
            "3. AI声称已完成了操作（已安装/已创建/已部署/已生成），但没有工具调用证据\n"
            "4. AI编造了文件路径、执行结果或服务状态\n\n"
            "如果存在以上任何问题，回复: RETRY: [用中文具体指示AI应该怎么做]\n"
            "如果AI的回复是合理的（比如在回答问题、解释限制、确认信息、或任务确实不需要工具），回复: OK\n\n"
            "只回复 OK 或 RETRY: 开头的一行。"
        )
        resp = model_router.complete(
            prompt=audit_prompt,
            system="你是回复审计器。只回复 OK 或 RETRY: 开头的一行，不要多余解释。",
            model=model,
            max_tokens=150,
            task_type="general",
            budget="low",
        )
        result = resp.content.strip()

        if "RETRY" in result.upper():
            colon_pos = result.find(":")
            feedback = result[colon_pos + 1:].strip() if colon_pos != -1 else ""
            if not feedback:
                feedback = (
                    "你必须使用工具来完成用户的请求。"
                    "使用 run_command 执行系统命令，write_file 写文件，"
                    "read_url_content 读取网页，web_search 搜索信息。"
                    "不要只是描述步骤或展示代码块，要实际执行。"
                )
            return {"should_retry": True, "feedback": feedback}
        return {"should_retry": False, "feedback": ""}
    except Exception as e:
        logger.warning("[AgenticLoop] LLM audit failed: %s, allowing response", e)
        return {"should_retry": False, "feedback": ""}


def _detect_false_claims(text: str, tool_calls_log: list) -> bool:
    """Detect when AI claims to have completed actions that weren't actually performed.
    Returns True if the response contains completion claims but tool_calls_log
    doesn't contain the corresponding run_command/write_file calls.
    """
    if not text:
        return False

    # Check if any run_command was actually called
    actual_tools = {tc.get("tool", "") for tc in tool_calls_log}
    has_run_command = "run_command" in actual_tools
    has_write_file = "write_file" in actual_tools

    # Completion claim patterns (Chinese + English)
    claim_patterns = [
        r"已完成", r"已安装", r"已生成", r"已创建", r"已部署",
        r"已clone", r"已拉取", r"已下载", r"已配置", r"已启动",
        r"成功安装", r"成功生成", r"成功创建", r"成功部署",
        r"安装完毕", r"部署完毕", r"生成完毕",
        r"video.*generated", r"successfully installed",
        r"successfully created", r"successfully deployed",
        r"clone.*完成", r"安装.*成功",
    ]

    # Action keywords that require run_command
    action_claims = [
        r"clone", r"git clone", r"pip install", r"apt install",
        r"docker pull", r"docker-compose up", r"npm install",
        r"启动.*服务", r"拉起.*容器",
    ]

    text_lower = text.lower()

    # Check for completion claims
    has_completion_claim = any(re.search(p, text, re.IGNORECASE) for p in claim_patterns)
    has_action_claim = any(re.search(p, text, re.IGNORECASE) for p in action_claims)

    # If claims completion + action but never used run_command, it's a false claim
    if has_completion_claim and has_action_claim and not has_run_command and not has_write_file:
        return True

    # Also detect file path claims without verification
    file_path_claim = re.search(
        r'(?:~/|/home/|/tmp/|/var/|/opt/|/usr/)\S+\.\w{2,4}(?:\s|，|。|,|$)',
        text
    )
    file_action_claim = re.search(
        r'(?:已生成|已创建|已保存|已写入|saved|created|generated|written)',
        text, re.IGNORECASE
    )
    if file_path_claim and file_action_claim and not has_run_command and not has_write_file:
        return True

    return False


def _contains_executable_code_blocks(text: str) -> bool:
    """Detect fenced code blocks containing executable shell/docker commands.
    Returns True if the text contains code blocks that should be executed
    via run_command rather than shown to the user.
    """
    if not text:
        return False
    # Match fenced code blocks with shell-like language hints
    shell_block_re = re.compile(
        r'```(?:bash|sh|shell|console|dockerfile)\s*\n(.*?)```',
        re.DOTALL | re.IGNORECASE
    )
    # Also check unlabeled code blocks
    unlabeled_block_re = re.compile(
        r'```\s*\n(.*?)```',
        re.DOTALL
    )
    # Executable command patterns
    exec_cmd_re = re.compile(
        r'^\s*(?:sudo\s+)?(?:'
        r'docker(?:\s+|-compose\s+)|'
        r'pip3?\s+install|'
        r'apt(?:-get)?\s+install|'
        r'npm\s+install|'
        r'yarn\s+add|'
        r'systemctl\s+|'
        r'service\s+|'
        r'kubectl\s+|'
        r'curl\s+|'
        r'wget\s+|'
        r'make\s|'
        r'cat\s+>|'
        r'mkdir\s+'
        r')',
        re.MULTILINE | re.IGNORECASE
    )
    for pattern in [shell_block_re, unlabeled_block_re]:
        for match in pattern.finditer(text):
            block_content = match.group(1)
            if exec_cmd_re.search(block_content):
                return True
    return False


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
        "content": _normalize_content(message.content),
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
        "text": _normalize_content(message.content),
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
