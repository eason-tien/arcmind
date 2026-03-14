# ArcMind v0.7.2 Knowledge Base & Audit Report
> Generated: 2026-03-12 | Deep audit of entire codebase

---

## 1. Architecture Overview

### System Flow
```
User (Telegram/CLI/WS/API)
  → Channel Layer (telegram.py, cli.py, voice.py)
    → Gateway (server.py + router.py)
      → Session Manager (session_manager.py)
      → Message Router (router.py) → RouteAction
        → SYSTEM_COMMAND → /help, /reset, /status
        → NEW_TASK → OODA Main Loop
        → CONTINUE_TASK → Resume existing session
  → Main Loop (main_loop.py)
    → OBSERVE: Receive command
    → ORIENT: Memory retrieval (working_memory, embedding, sop_manager)
    → DECIDE: Intent classification (_llm_classify_intent) + Delegation check
    → ACT: Execute via skill or agentic loop
      → Tool Loop (tool_loop.py) — agentic_complete()
        → LLM Call (model_router.py → Provider)
        → Tool Execution (run_command, read_file, write_file, etc.)
        → LLM Audit (_llm_audit_response)
        → Heartbeat updates (_update_heartbeat)
        → Dead loop / repeat detection
      → Result → Strip tags → Return to Gateway → Channel → User
```

### Key Files (by layer)

| Layer | File | Lines | Purpose |
|-------|------|-------|---------|
| **Entry** | `main.py` | ~110 | FastAPI app creation, uvicorn startup |
| **Gateway** | `gateway/server.py` | ~838 | REST/WS endpoints, process_message, heartbeat monitor |
| **Gateway** | `gateway/router.py` | ~235 | Route classification (system_cmd/new_task/continue) |
| **Gateway** | `gateway/session_manager.py` | ~388 | Session state, history, DB persistence |
| **Core** | `loop/main_loop.py` | ~1100 | OODA loop, intent classification, delegation |
| **Core** | `runtime/tool_loop.py` | ~1600 | Agentic tool execution loop, LLM audit, heartbeat |
| **Core** | `runtime/audit.py` | ~130 | Anti-hallucination checks |
| **Runtime** | `runtime/model_router.py` | ~585 | Multi-provider model routing + fallback |
| **Runtime** | `runtime/delegator.py` | ~300 | Sub-agent delegation |
| **Runtime** | `runtime/capability_selector.py` | ~200 | Semantic agent matching |
| **Runtime** | `runtime/skill_manager.py` | ~180 | Skill loading from manifest |
| **Runtime** | `runtime/event_bus.py` | ~200 | Async event dispatch |
| **Runtime** | `runtime/agent_registry.py` | ~150 | Agent CRUD |
| **Channel** | `channels/telegram.py` | ~500 | Telegram bot integration |
| **Channel** | `channels/supervisor.py` | ~100 | Channel lifecycle manager |
| **Memory** | `memory/working_memory.py` | ~200 | Short-term per-task memory |
| **Memory** | `memory/embedding.py` | ~150 | Ollama embedding with cache |
| **Memory** | `memory/sop_manager.py` | ~150 | SOP (Standard Operating Procedure) storage |
| **Persona** | `persona/loader.py` | ~80 | Load SOUL.md, TOOLS.md, etc. |
| **Persona** | `persona/injector.py` | ~100 | Build system prompt from persona |
| **Config** | `config/agents.json` | - | Agent definitions (10 agents) |
| **Config** | `config/routing_rules.yaml` | - | Model routing rules |
| **Config** | `config/settings.py` | - | Pydantic settings from .env |
| **Config** | `skills/__manifest__.yaml` | - | Skill tool definitions |

### Agents (agents.json)
| ID | Role | Model |
|----|------|-------|
| main | CEO/Coordinator | custom:MiniMax-M2.5 |
| planning | Task decomposition | custom:MiniMax-M2.5 |
| search | Web/info search | custom:MiniMax-M2.5 |
| analysis | Data analysis | custom:MiniMax-M2.5 |
| code | Code generation | custom:MiniMax-M2.5 |
| qa | Quality assurance | custom:MiniMax-M2.5 |
| windows | Windows PC ops | custom:MiniMax-M2.5 |
| sre | Site reliability | custom:MiniMax-M2.5 |
| data_engineer | Data pipeline | custom:MiniMax-M2.5 |
| security | Security audit | custom:MiniMax-M2.5 |

### Model Routing (routing_rules.yaml)
- Primary: `custom:MiniMax-M2.5` (all task types)
- Fallback: `ollama:qwen3:8b` → `ollama:qwen3:14b@192.168.1.151`
- Provider: MiniMax API (`https://api.minimax.chat/v1`)

---

## 2. CRITICAL BUGS (P0 — Must Fix Immediately)

### BUG-P0-01: Intent classifier doesn't see user command
- **File**: `loop/main_loop.py:89-99`
- **Impact**: ALL requests. Intent classification is random since LLM never sees what to classify
- **Root cause**: v0.7.2 refactor lost `f"用户请求: {command}\n\n"` from prompt
- **Fix**: Add `f"用户请求: {command}\n\n"` before line 99

### BUG-P0-02: Telegram crashes on audio attachments
- **File**: `channels/telegram.py:244`
- **Impact**: Every audio file sent via Telegram crashes
- **Root cause**: `file_path.endswith('.mp3', '.ogg', '.wav')` — wrong syntax, needs tuple
- **Fix**: Change to `file_path.endswith(('.mp3', '.ogg', '.wav'))`

### BUG-P0-03: Ghost skills in manifest — missing files
- **File**: `skills/__manifest__.yaml`
- **Impact**: `video_generator`, `claude_bridge`, `claude_status` reference non-existent .py files
- **Fix**: Remove these entries or create the files

### BUG-P0-04: capability_selector calls non-existent method
- **File**: `runtime/capability_selector.py:185-186`
- **Impact**: Skill semantic routing completely broken
- **Root cause**: Calls `skill_manager.get_info()` but method is `get_manifest()`. Also `list_skills()` returns dicts, code expects strings
- **Fix**: `skill_entry["name"]` + `get_manifest()`

### BUG-P0-05: Hardcoded skill imports crash startup
- **File**: `runtime/skill_manager.py:54-55`
- **Impact**: `import skills.comfyui` and `import skills.ffmpeg` crash if files don't exist (they don't)
- **Fix**: Remove or wrap in try/except

### BUG-P0-06: API key exposed in routing_rules.yaml
- **File**: `config/routing_rules.yaml:7`
- **Impact**: NVIDIA API key in plain text, committed to git
- **Fix**: Move to .env, remove from yaml

### BUG-P0-07: Error recovery can empty all messages → infinite loop
- **File**: `runtime/tool_loop.py:1335-1340`
- **Impact**: `bad_request_error` handler strips messages; if all are tool/assistant, list empties → crash loop
- **Fix**: Guard `len(oai_messages) > 1` in while condition

### BUG-P0-08: Symlink security checks are dead code
- **File**: `runtime/tool_loop.py:693-706, 714-731`
- **Impact**: `is_symlink()` checked AFTER `resolve()` — symlink already resolved, check never triggers
- **Fix**: Check `is_symlink()` BEFORE `resolve()`

---

## 3. HIGH PRIORITY BUGS (P1 — Fix This Sprint)

### BUG-P1-01: HTTPException raised in non-HTTP contexts
- **File**: `gateway/server.py:500-502`
- **Impact**: Telegram/WS callers get unhandled exception, crash connection
- **Fix**: Return error string instead of raising HTTPException

### BUG-P1-02: WebSocket client can overwrite session_id (security)
- **File**: `gateway/server.py:666-671`
- **Impact**: `**data` spread after explicit fields lets client hijack sessions
- **Fix**: Filter `data` to exclude `session_id`, `user_id`, `text`

### BUG-P1-03: Session history grows unbounded in RAM
- **File**: `gateway/session_manager.py:88`
- **Impact**: Memory leak — history list never capped in-memory
- **Fix**: Cap at 100 entries in `add_turn()`

### BUG-P1-04: SOUL.md/TOOLS.md reference non-existent agents
- **Files**: `SOUL.md`, `TOOLS.md`
- **Impact**: AI believes it can delegate to `devops`/`pm` agents that don't exist → hallucination
- **Fix**: Update docs to match actual agents.json

### BUG-P1-05: SOUL.md says macOS but server is Ubuntu
- **File**: `SOUL.md:7`
- **Impact**: AI gives macOS commands (`launchctl`) on Linux server
- **Fix**: Update to Ubuntu 22.04 LTS (x86_64)

### BUG-P1-06: Model tiering in SOUL.md doesn't match reality
- **File**: `SOUL.md`
- **Impact**: Docs say different models per tier, all actually use MiniMax-M2.5
- **Fix**: Align documentation with actual config

### BUG-P1-07: Fallback chain has 3 identical entries
- **File**: `config/routing_rules.yaml:40-44`
- **Impact**: If MiniMax is down, retries same endpoint 3x before real fallback
- **Fix**: Remove duplicates, use distinct fallback models

### BUG-P1-08: require_tool_usage parameter accepted but never used
- **File**: `runtime/tool_loop.py:1171`
- **Impact**: Caller expects tool usage enforcement but it's not implemented
- **Fix**: Implement or remove parameter

### BUG-P1-09: max_tokens not recomputed per fallback model
- **File**: `runtime/model_router.py:complete()`
- **Impact**: Fallback model may reject requests with primary model's max_tokens
- **Fix**: Recompute `final_max` per model in fallback chain

### BUG-P1-10: EventBus metrics count per-handler, not per-event
- **File**: `runtime/event_bus.py:175-185`
- **Impact**: Inflated metrics, duplicate dead letter entries
- **Fix**: Move `_processed` increment outside handler loop

### BUG-P1-11: WebSocket endpoints bypass API key auth
- **File**: `api/server.py:232-259`
- **Impact**: All WS endpoints (`/ws`, `/ws/activity`, `/ws/voice`) unauthenticated
- **Fix**: Add auth check in WS handshake

### BUG-P1-12: Checkpoint doesn't skip tool execution
- **File**: `runtime/tool_loop.py:1378-1387`
- **Impact**: Checkpoint_Passed falls through to execute tools with pruned context
- **Fix**: Add `continue` after checkpoint handling

---

## 4. MEDIUM PRIORITY (P2 — Fix Next Sprint)

### P2-01: `_any_overlap` in audit.py too permissive (2-char tokens match anything)
### P2-02: Memory auto-injection mutates shared message list in-place
### P2-03: `compress_context()` defined but never called
### P2-04: `/model` and `/mode` commands advertised in /help but have no handlers
### P2-05: SOUL_COMPACT.md missing — compact mode silently falls back to full 9KB
### P2-06: Orphan skills on disk not in manifest (template_analyzer, trading_enhanced)
### P2-07: Agents exist both as permanent AND hireable templates (security, sre, data_engineer)
### P2-08: Ollama default model mismatch (settings.py: llama3.2, routing: qwen3:8b)
### P2-09: Full message payloads logged at INFO level (security/privacy)
### P2-10: `skill_manager.invoke()` timeout parameter never enforced
### P2-11: `agent_registry.save_config()` not thread-safe
### P2-12: Events emitted before bus starts are silently lost
### P2-13: Internal broadcast_activity endpoint has no access restriction
### P2-14: session_id input not sanitized in audio endpoint (path traversal risk)
### P2-15: Delegator confidence thresholds inconsistent (local 0.85 vs federated 0.50)
### P2-16: `a2a_hub.py` is entirely dead code — never wired up
### P2-17: Embedding cache TTL 60s too short for deterministic embeddings
### P2-18: 30+ bare `except Exception: pass` blocks swallow errors silently
### P2-19: Command blocklist in run_command is substring-based, trivially bypassed
### P2-20: Python eval sandbox exposes `dir` and `type` builtins

---

## 5. Cross-File Dependency Map

```
main.py
  └─ api/server.py (create_app)
       ├─ gateway/server.py (REST/WS endpoints)
       │    ├─ gateway/router.py (message classification)
       │    ├─ gateway/session_manager.py (session state)
       │    └─ loop/main_loop.py (OODA loop)
       │         ├─ runtime/model_router.py (LLM calls)
       │         ├─ runtime/delegator.py (sub-agent dispatch)
       │         │    ├─ runtime/capability_selector.py (semantic matching)
       │         │    └─ runtime/agent_registry.py (agent lookup)
       │         ├─ runtime/tool_loop.py (agentic execution)
       │         │    ├─ runtime/model_router.py
       │         │    ├─ runtime/audit.py (hallucination guard)
       │         │    └─ runtime/skill_manager.py (skill invocation)
       │         ├─ persona/injector.py → persona/loader.py
       │         │    └─ SOUL.md, TOOLS.md, AGENTS.md, USER.md
       │         └─ memory/
       │              ├─ working_memory.py (per-task short-term)
       │              ├─ embedding.py (Ollama embeddings + cache)
       │              └─ sop_manager.py (procedure storage)
       ├─ runtime/event_bus.py (async events)
       ├─ governor/governor.py (rate limiting)
       └─ channels/
            ├─ telegram.py (Telegram bot)
            ├─ supervisor.py (channel lifecycle)
            └─ cli.py, voice.py, voice_ws.py
```

---

## 6. Key Mechanisms

### Intent Classification Flow
```
User input → _llm_classify_intent()
  → LLM call (budget=low, max_tokens=10)
  → Returns: "action" | "question" | "chat"
  → action: enters tool_loop with tools
  → question: enters tool_loop WITHOUT tools (or direct LLM)
  → chat: lightweight direct LLM response (no tools)
```

### Heartbeat Monitoring (No Hard Timeout)
```
Gateway:
  _run_with_heartbeat_monitor(loop_input, main_loop)
  → asyncio.to_thread(main_loop.run)
  → Every 30s: check heartbeat timestamp
  → If no update for 300s → stall detected → cancel

Tool Loop:
  _update_heartbeat(iteration, "start")     ← each iteration
  _update_heartbeat(iteration, f"tool:{name}") ← before tool exec
  _update_heartbeat(iteration, "loop_end")  ← end of iteration
```

### Dead Loop Detection
```
tool_loop.py:
  no_tool_streak counter
  → 5 consecutive no-tool iterations → warning injected
  → 8 consecutive → terminate with error message

  Repeat tool detection (existing):
  → Same tool call 10 times → terminate
```

### LLM Audit System
```
_llm_audit_response(user_prompt, ai_response, model)
  → If require_tool_usage=True AND no tool calls AND audit_retry < 2:
    → LLM checks if response just describes steps without executing
    → Returns RETRY with feedback, or OK
    → On RETRY: injects feedback as user message, continues loop
```

### Model Fallback Chain
```
routing_rules.yaml → task_type → primary model
  → If primary fails → try fallback_chain in order
  → custom:MiniMax-M2.5 → ollama:qwen3:8b → ollama:qwen3:14b@192.168.1.151
```

### Persona System
```
PersonaLoader reads:
  SOUL.md → Identity, rules, personality (9KB)
  TOOLS.md → Available tools, agent team description
  AGENTS.md → Agent capabilities reference
  USER.md → User profile/preferences

PersonaInjector.build_system_prompt():
  → Combines persona docs into system prompt
  → Appends anti-hallucination rules
  → Injects memory context
```

---

## 7. Server Environment

| Item | Value |
|------|-------|
| OS | Ubuntu 22.04.5 LTS (x86_64) |
| Python | 3.10.12 (venv) |
| Entry | `/home/engineering/ArcMind/venv/bin/python main.py` |
| Port | 8100 |
| GPU | NVIDIA (CUDA available) |
| Storage | 466GB root (55%) + 3.7TB data (51%) |
| Model API | MiniMax M2.5 (`https://api.minimax.chat/v1`) |
| Local LLM | Ollama (port 11434) — qwen3:8b, qwen3:14b |
| DB | SQLite (SQLAlchemy) |
| Vector | Qdrant (port 6333) |
| Telegram | Bot polling (chat_id=8541856901) |

---

## 8. Deployment Notes

- **Start**: `cd /home/engineering/ArcMind && venv/bin/python main.py`
- **Logs**: `logs/arcmind.log` (new), `/tmp/arcmind.log` (legacy redirect)
- **Config**: `.env` (secrets), `config/` (routing, agents, settings)
- **Git**: `https://github.com/eason-tien/arcmind.git` (main branch)
- **SSH**: See `.env` for connection credentials (never hardcode)

---

## 9. Fix Priority Matrix

| Priority | Count | Examples |
|----------|-------|---------|
| **P0 (Immediate)** | 8 | Intent classifier blind, Telegram crash, ghost skills, symlink bypass |
| **P1 (This Sprint)** | 12 | HTTPException in WS, session hijack, memory leak, doc drift |
| **P2 (Next Sprint)** | 20 | Audit overlap too permissive, dead code, thread safety, auth gaps |
| **Total** | 40 | Across 15+ files |
