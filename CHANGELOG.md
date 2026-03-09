# Changelog

All notable changes to ArcMind will be documented in this file.

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
