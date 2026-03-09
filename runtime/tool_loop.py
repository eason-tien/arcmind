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
import traceback
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("arcmind.tool_loop")

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


# ── Tool Implementations ─────────────────────────────────────────────────────

def _tool_web_search(query: str, max_results: int = 5, **kwargs) -> str:
    """Web search using ddgs."""
    try:
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


def _tool_run_command(command: str, timeout: int = 30, **kwargs) -> str:
    """Execute a shell command."""
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
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
    """Read a file."""
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return f"File not found: {path}"
        if p.stat().st_size > 100_000:
            return f"File too large ({p.stat().st_size} bytes). Read first 5000 chars.\n\n" + p.read_text(encoding="utf-8")[:5000]
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Read error: {e}"


def _tool_write_file(path: str, content: str, **kwargs) -> str:
    """Write a file."""
    try:
        p = Path(path).expanduser()
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
    """Evaluate Python code."""
    try:
        # Try eval first (for expressions)
        try:
            result = eval(code)
            return str(result)
        except SyntaxError:
            pass

        # Fall back to exec (for statements)
        local_vars: dict = {}
        exec(code, {"__builtins__": __builtins__}, local_vars)

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
    tool_schemas = registry.get_schemas() if tools_enabled else []
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
    is_openai_compat = provider_name in ("openai", "ollama", "groq", "mistral", "custom")

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
    GLOBAL_FAIL_SAFE = 500        # absolute maximum iterations
    MAX_STEP_RETRIES = 5          # max retries for a single step
    CHECKPOINT_PRUNE_KEEP = 4     # keep last N tool messages after pruning

    iteration = 0
    step_retry_count = 0       # retries for current step
    last_error_tool = ""       # track which tool is failing
    checkpoint_count = 0       # number of checkpoints passed

    while iteration < GLOBAL_FAIL_SAFE:
        iteration += 1
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

        # ── No tool calls → return text ──
        if not tool_uses:
            clean_text = _strip_status_tags(text_response)
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

            handler = registry.get_handler(tool_name)
            if handler:
                try:
                    result_str = handler(**tool_input)
                    # Reset step retry on successful tool execution
                    if step_retry_count > 0 and tool_name != last_error_tool:
                        step_retry_count = 0
                except Exception as e:
                    result_str = f"Tool execution error: {e}"
                    last_error_tool = tool_name
            else:
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

    resp = client.chat.completions.create(**kwargs)
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

    resp = client.messages.create(**kwargs)

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
