# Changelog

All notable changes to ArcMind will be documented in this file.

## [0.9.3] — 2026-03-15

### Task Resilience Framework
- **`runtime/task_resilience.py`** (NEW, ~510 lines) — TaskResilienceEngine：timeout 保護、7 種故障診斷（Timeout/SSL/Import/Network/DB/OOM/Unknown）、自動修復、指數退避重試、Circuit Breaker（3 次失敗 → 5 分鐘冷卻）、Telegram 升級通知。
- **CRON Handler V4** — 排程任務透過 resilience_engine 執行，不再直接呼叫 `skill_manager.invoke`。
- **TASK_FAILED 擴展** — 失敗事件寫入因果記憶（causal memory），系統可學習歷史故障模式。
- **API**: `GET /v1/resilience/status` + `POST /v1/resilience/reset/{skill}`。

### UX 改進
- **移除原始工具日誌注入** — `main_loop.py` P6-Layer3 不再把 raw tool_call dump 貼到回覆末尾，改為 `🔧 完成 N/N 項操作`。
- **SOUL_COMPACT.md** — 修正矛盾的 Proof-of-Work 規則（「行動簡述要自然」取代「必須包含行動摘要」）。

### Skill 治理
- **`skills/__manifest__.yaml`** — 升級至 64 skills，全部含 `category`（9 類）+ `timeout_s`。補齊 5 個缺失 skill 登錄。

### Bug Fixes
- **daily_report SSL** — 新增 `_make_ssl_context()` fallback，天氣 API 從 42s 降至 ~1s。
- **Admin API** — 補齊 `/v1/tools`、`/v1/agents`、`/v1/analytics/tokens`、`/v1/iterations/incidents` 4 個端點。

## [0.8.0] — 2026-03-13

### Enterprise UI Dashboard
- **5 頁管理後台**：SkillBrowser、CronDashboard、SystemDashboard、ToolBrowser、AgentManager、TokenAnalytics、AuditLog。
- **深色/淺色主題切換** + Toast 通知系統。
- **Code Splitting** — 動態 import 減少初始載入體積。
- **ChatInput 修復** — API endpoint 對齊、mock response 清理。
- **Session 管理** — 新增 New Chat、Delete Session 功能。

### Documentation & Deployment
- **QUICKSTART.md** — 快速入門文件。
- **API.md** — API 參考文件。
- **Dockerfile + docker-compose.yml** — 容器化部署。
- **Makefile** — 標準化建構/測試/部署流程。
- **README** — 架構圖、徽章、文件連結。

### New Skills
- **email_kb_skill** — PST 郵件知識庫（讀取/搜尋/LLM 摘要）。

## [0.7.0] — 2026-03-09

### Webhook 事件驅動 + Agent 模板招聘系統

#### Phase 1 — Generic Webhook Endpoint
- **`POST /v1/webhook`** 和 **`POST /v1/webhook/{source}`** — 通用 Webhook 接收端點，支援 N8N、Zapier、自定義服務回調。
- **`X-Webhook-Secret`** header 簽名驗證（可選）。
- Webhook 收到後發佈 `EventType.WEBHOOK` 到 EventBus，由 `handle_webhook` handler 走 OODA Loop 處理。
- 支援 skill hint 從 payload 中提取（`skill` / `skill_name` 欄位）。

#### Phase 2 — Agent Handoff 事件
- 新增 **`EventType.AGENT_HANDOFF`** — Agent 任務交接事件類型。
- **`handle_agent_handoff`** handler — 寫入 SharedMemory 保持交接上下文、發送 IAMP HANDOFF 訊息、通過 OODA Loop 執行接收方任務。
- IAMP Bridge 新增 `"handoff"` 訊息類型轉發到 `AGENT_HANDOFF` 事件。

#### Phase 3 — Agent 模板招聘系統
- **`config/agent_templates.json`** — 8 個 Agent 模板：Security Engineer、Data Engineer、Frontend Engineer、UI/UX Designer、Copywriter、Financial Analyst、Translator、SRE Engineer。
- **`runtime/agent_templates.py`** — TemplateManager：`hire()`、`fire()`、`suggest_hire()`、`list_templates()`、`find_by_capability()`。
- **API 端點**：`GET /v1/agent/templates`、`POST /v1/agent/hire`、`POST /v1/agent/fire/{id}`、`GET /v1/agent/roster`。
- **Delegator 增強** — 新增 security / etl / database / frontend / design / copywriting / finance / translation / sre 等 9 組 capability keywords。
- **`suggest_hire`** — Delegator 找不到 active agent 時，自動推薦可聘用的模板（`DelegationMatch.hire_suggestion`）。
- 核心 Agent（main/search/analysis/code/qa/devops/pm/windows）不可被解僱。

#### Phase 4 — Pipeline 事件驅動可觀測性
- **Pipeline 觀測事件** — `execute_plan()` 在每步發射 `step_start` / `step_complete` / `step_failed` 以及 `pipeline_complete` / `pipeline_failed` 事件。
- **SharedMemory 持久化** — Pipeline 執行期間將計劃和每步結果寫入 SharedMemory，支援跨步驟可見性和故障恢復。
- **Pipeline ID** — 每次 Pipeline 執行自動分配唯一 `pipeline_id` 用於事件關聯。
- **Dead Letter Retry** — EventBus 新增 `retry_dead_letters()` 和 `dead_letter_summary()`，支援失敗事件重試和診斷。

#### New Tools (ToolRegistry)
- **`hire_agent`** — CEO 從模板庫聘用 Agent。
- **`fire_agent`** — CEO 解僱非核心 Agent。
- **`list_agent_templates`** — 列出所有可用 Agent 模板及聘用狀態。
- **`agent_handoff`** — Agent 之間任務交接（含上下文傳遞）。
- **`send_webhook`** — 主動發送 Webhook 到外部服務。

#### Bug Fixes
- **CircuitBreaker Lock** — 修復 `_check_circuit_breaker()` 中 `_lock` 可能為 `None` 導致的 `AttributeError`。
- **Async Route Fix** — 修復 `_route_model()` 非同步函式被同步呼叫的問題，改用 `_route_model_sync()`。
- **SQLite busy_timeout** — 設置 5 秒 busy_timeout 避免並發寫入時的 `database is locked` 錯誤。

## [0.6.0] — 2026-03-09

### Event-Driven 混合驅動架構

- **EventBus** (`runtime/event_bus.py`) — Central async event bus with typed events (`EventType`), priority queue processing, dead letter queue, and metrics tracking. Supports both sync `emit()` and async `emit_async()` dispatch.
- **Event Handlers** (`runtime/event_handlers.py`) — Wires EventBus events into OODA Loop. Handles `cron_trigger` → OODA, `agent_complete` → Lifecycle update, `agent_escalate` → CEO re-route, `system_event` → logging/memory, `iamp_message` → event chain.
- **IAMP → EventBus Bridge** — All IAMP messages automatically bridged to EventBus as `IAMP_MESSAGE` events, enabling event-driven Agent collaboration.
- **Cron → EventBus** — Cron triggers now emit `CRON_TRIGGER` events to EventBus (with fallback to direct execution if EventBus unavailable).
- **OODA Loop Events** — MainLoop emits `TASK_CREATED`, `AGENT_COMPLETE`, `TASK_FAILED` events at lifecycle boundaries for system-wide observability.
- **Server Integration** — EventBus starts/stops with FastAPI lifespan. `/healthz` now includes EventBus stats.
- **Hybrid Design** — Synchronous API/WebSocket path preserved (`MainLoop.run()`), async event-driven path added via EventBus handlers. Both paths coexist.

## [0.5.0] — 2026-03-09

### Phase 3 — System Integration

- **Iteration Engine v2** — Fixed roundtable `list_agents()` dict-vs-object bugs, added `get_default()`, new QA/DevOps/PM agents participate in weekly meetings, IAMP roundtable message logging.
- **Gateway Commands** — `/agents` shows full agent roster, `/agent_stats` shows IAMP communication stats, `/health` and `/version` updated to v0.5.0.
- **Worker Heartbeat CRON** — Auto-registered 60s interval heartbeat for processing delegated tasks.
- **Agent-Aware `/help`** — Added agent management section to help text.

### Phase 2 — OODA Loop Multi-Agent Integration

- **OODA Observe** — Agent status monitoring, message bus stats awareness.
- **OODA Orient** — Delegation history injection (recent completions/escalations).
- **OODA Decide** — Multi-agent pipeline routing via `route_multi()`.
- **OODA Act** — `_try_multi_agent()` for automatic pipeline execution.
- **OODA Learn** — Agent performance tracking via IAMP `STATUS_REPORT`.
- **Bug Fix** — `iteration_engine._collect_agent_usage()` dict access fix.

### Phase 1 — Agent Collaboration Infrastructure

- **Agent Registry v2** — Loads agents from `agents.json` with capability-based lookup, dynamic registration, runtime save. Fixes `find_by_capability()` bug.
- **New Agent Roles** — Added QA Agent, DevOps Agent, Product Manager to the zero-human company roster (8 agents total).
- **Delegation Pipeline v2** — Intent-based routing with multi-dimensional keyword scoring. Multi-agent `route_multi()` detects sequential collaboration signals (e.g., "先調研再開發").
- **Inter-Agent Message Protocol (IAMP)** — Structured message bus with `task_assign`, `task_complete`, `task_escalate`, `info_request`, `handoff` types. Thread-safe with bounded message history.
- **Shared Working Memory** — Per-task `SharedMemory` enables pipeline steps to pass context automatically. Managed by `SharedMemoryManager` with auto-cleanup.
- **Multi-Agent Pipeline Delegation** — `delegate_multi()` creates sequential task chains. Worker heartbeat processes steps in order with context handoff.
- **Task Escalation** — Sub-agents can escalate tasks back to CEO when beyond their capability.
- **Task Handoff** — Mid-pipeline agent-to-agent task transfer with context preservation.

## [0.4.0] — 2026-03-09

### Security (12 CRITICAL fixes)

- **[C-01] Sandbox Python eval** — `tool_loop.py` `_tool_python_eval()` now runs in a restricted sandbox with safe builtins whitelist. Blocks `__import__`, `subprocess`, `os.system`, `open()`, and all other dangerous operations.
- **[C-02] Prevent shell injection** — `_tool_run_command()` changed from `shell=True` to `shell=False` with `shlex.split()`. Added blocked command pattern detection.
- **[C-03] Path traversal protection** — `_tool_read_file()` and `_tool_write_file()` now block sensitive system paths (`/etc/shadow`, `/.ssh`, etc.) and refuse to follow symlinks.
- **[C-04] Safe condition evaluation** — `agent_builder.py` replaced raw `eval()` with AST-validated expression evaluation. Function calls, imports, and attribute access are blocked.
- **[C-05] Whitelist command filter** — `smart_repair.py` replaced blacklist-based command filtering with strict regex whitelist for pip install commands only.
- **[C-06] Remove hardcoded credentials** — `repair_agent.py` MySQL credentials now read from environment variables (`MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`).
- **[C-09] Restrict CORS origins** — `api/server.py` CORS changed from `allow_origins=["*"]` to localhost-only defaults. Configurable via `settings.cors_allowed_origins`.
- **[C-10] Electron security hardening** — Enabled `contextIsolation: true`, disabled `nodeIntegration`, devtools only in dev mode, certificate error bypass only in dev mode.
- **[C-11] Fail-closed governor** — `cron.py` governor audit default changed from `True` (approve) to `False` (deny). Missing or malformed governor responses now block execution.
- **[C-12] Remove governor bypass** — Removed `governor_bypass` parameter from `skill_routes.py` API. All skill invocations now require governor approval.

### Reliability (12 HIGH fixes)

- **[H-01] Fix task orphaning** — `a2a_hub.py` now sets `ConnectionError` on all pending futures when a client disconnects, preventing callers from hanging forever.
- **[H-02] Fix broadcaster memory leak** — `ActivityBroadcaster` now caps connections at 100 and iterates over a copy during broadcast.
- **[H-03] Fix session ID collision** — WebSocket sessions now use `uuid4` hex instead of Python `id()` which can be reused after object GC.
- **[H-04] Remove duplicate audio endpoint** — Removed the second `/v1/chat/audio` definition that shadowed the first.
- **[H-05] Fix DB session leaks** — `session_manager.py` now uses `try/finally` for all DB operations with `db.rollback()` on errors.
- **[H-07] Add request timeout** — Gateway `_handle_agent_task` now uses `asyncio.wait_for(timeout=300)`.
- **[H-12] Auto-reset LIMITED mode** — `circuit_breaker.py` auto-recovers from LIMITED mode after 30 minutes.
- **[H-13] Fix task ID memory leak** — `circuit_breaker.py` now uses `OrderedDict` with max 10,000 tracked tasks.
- **[H-17] Fix UI path traversal** — `serve_ui()` validates normalized paths stay within `ui_dist_path`.
- **[H-19] Fix token exposure** — `error_reporter.py` replaced `curl` subprocess with `httpx` in-process call.
- **[H-20] Block symlinks** — `file_ops.py` rejects symlinks to prevent TOCTOU attacks.
- **[H-21] Fix shell injection** — `env_discovery.py` `_find_configs()` changed to `shell=False`.

### Bug Fixes

- Governor `warn_threshold` now logs a warning when clamped instead of silently changing.
- `preference_manager.py` JSON extraction no longer crashes on strings without code blocks.
- MGIS client — Added JSON decode error handling for non-JSON responses.
- Global exception handler no longer leaks internal error details to API responses.
- A2A Hub — Added heartbeat message handling for connection keepalive.
- Async tasks — WebSocket background tasks now properly handle uncaught exceptions.

### Architecture

- Graceful shutdown — Added `session_manager.stop()` to server shutdown lifecycle.

### Breaking Changes

- `governor_bypass` parameter removed from `/v1/skills/invoke` API
- CORS no longer allows all origins by default — configure `cors_allowed_origins`
- Electron app requires `NODE_ENV=development` or `ELECTRON_START_URL` for devtools
- MySQL credentials must be set via environment variables

## [0.3.0] - 2026-03-08

### Added
- OODA-based main loop with 5-stage processing
- 16 tools (run_command, read_file, write_file, web_search, python_eval, memory_query, list/add/remove_agents, invoke/list_skills, harness create/status/control)
- 10 skills (web_search, file_ops, code_exec, trading, self_iteration, daily_report, github, document, env_discovery, gitnexus)
- Multi-provider model routing (MiniMax, Ollama, OpenAI, Anthropic, Google, Groq, Mistral)
- 4-layer memory system (episodic/semantic/procedural/causal) with SQLite + Vector
- Governor safety system with risk assessment + circuit breaker
- Self-healing watchdog + repair agent + incident logging
- Harness system for resumable multi-step tasks
- Gemini Bridge for Antigravity CLI integration
- Telegram, REST API, WebSocket, Voice channels
- Android hybrid app (Chaquopy + AccessibilityService)
- GitHub Actions CI/CD pipeline
- Auto-update mechanism
- Error reporting to GitHub Issues

### Fixed
- memory_compressor.py: ChromaDB API migration to SQLite
- test_gateway.py: Python 3.14 asyncio compatibility
- test_harness.py: UNIQUE constraint test isolation
