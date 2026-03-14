# ArcMind — Code Index

> Version: 0.9.3
> Last Updated: 2026-03-14
> Total: ~57 Python files, ~20,000+ lines

---

## Core Files (High Impact — Do Not Modify Without Impact Analysis)

| File | Lines | Purpose | Key Classes/Functions |
|------|-------|---------|----------------------|
| `runtime/tool_loop.py` | 2,069 | Agentic tool execution loop, LLM+tool state machine | `ToolRegistry`, `agentic_complete()`, `run_agentic_loop()` |
| `loop/main_loop.py` | 1,238 | OODA main loop: OBSERVE→ORIENT→DECIDE→ACT→LEARN | `MainLoop`, `LoopInput`, `LoopResult` |
| `runtime/pm_agent.py` | 1,190 | Project Manager agent with self-iteration | `PMAgent`, `PMPool` |
| `runtime/model_router.py` | 596 | Multi-provider LLM routing with fallback | `ModelRouter` |
| `runtime/event_bus.py` | 390 | Async event dispatch with priority queue | `EventBus`, `Event`, `EventType`, `EventPriority` |
| `gateway/server.py` | 852 | FastAPI REST/WS endpoints, app lifecycle | `create_app()`, health/status endpoints |
| `gateway/session_manager.py` | 391 | Session state, history, DB persistence | `SessionManager` |

## PM System Files (Current Audit Focus)

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `runtime/pm_agent.py` | 1,190 | PM agent: plan → execute → verify → retry → synthesize | 3 rounds audited, 20 bugs fixed |
| `runtime/pm_quality_gate.py` | 226 | Unified LLM quality gate (verify_step, evaluate_plan, evaluate_completion) | Refactored: P1-A unified audit path |
| `runtime/pm_escalation.py` | 226 | Auto-escalation on consecutive failures | Reviewed, no changes needed |
| `runtime/task_tracker.py` | 280 | In-memory task state tracking | Reviewed — no persistence (known limitation) |
| `runtime/project_registry.py` | 789 | SQLAlchemy project lifecycle (10-state FSM) | Reviewed |
| `runtime/progress_notifier.py` | 131 | PM_RESULT_READY → Telegram delivery | Reviewed — Telegram-only (P1-B target) |

## Runtime Layer

| File | Lines | Purpose |
|------|-------|---------|
| `runtime/delegator.py` | 811 | Sub-agent delegation and capability matching |
| `runtime/capability_selector.py` | 466 | Semantic agent matching for delegation |
| `runtime/iteration_engine.py` | 955 | Iteration/improvement engine |
| `runtime/federation.py` | 526 | Cross-instance federation protocol |
| `runtime/harness.py` | 589 | Test harness for agent evaluation |
| `runtime/skill_installer.py` | 391 | Dynamic skill installation |
| `runtime/shadow_runner.py` | 334 | Shadow execution for validation |
| `runtime/iamp.py` | 312 | Inter-Agent Messaging Protocol |
| `runtime/lifecycle.py` | 295 | Agent lifecycle management |
| `runtime/agent_registry.py` | 279 | Agent CRUD operations |
| `runtime/cron.py` | 272 | Scheduled task execution |
| `runtime/skill_manager.py` | 249 | Skill loading from manifest |
| `runtime/harness_tool.py` | 253 | Harness tool definitions |
| `runtime/project_classifier.py` | 209 | Task complexity classification |
| `runtime/agent_templates.py` | 197 | Agent template system (hire/fire) |
| `runtime/project_state_machine.py` | 147 | Project state transitions |
| `runtime/audit.py` | 129 | Anti-hallucination checks |
| `runtime/complexity_classifier.py` | 88 | Simple/complex/project classification |

## Event Handling

| File | Lines | Purpose |
|------|-------|---------|
| `runtime/event_bus.py` | 390 | Core event infrastructure |
| `runtime/event_handlers.py` | 411 | Runtime event handlers (SYSTEM_EVENT, AGENT_COMPLETE, etc.) |
| `loop/event_handlers.py` | 250 | Loop-level event handlers (FEDERATION_RESULT, TASK_CREATED, etc.) |

## Gateway & Channels

| File | Lines | Purpose |
|------|-------|---------|
| `gateway/server.py` | 852 | FastAPI app, REST endpoints |
| `gateway/router.py` | 235 | Message routing (system_cmd/new_task/continue) |
| `gateway/session_manager.py` | 391 | Session state management |
| `gateway/a2a_hub.py` | 115 | Agent-to-Agent communication hub |
| `channels/telegram.py` | 833 | Telegram bot integration |
| `channels/supervisor.py` | 200 | Channel lifecycle supervisor |
| `channels/voice.py` | 161 | Voice channel |
| `channels/voice_ws.py` | 223 | Voice WebSocket |
| `channels/cli.py` | 98 | CLI channel |
| `channels/base.py` | 65 | Base channel interface |

## Operations

| File | Lines | Purpose |
|------|-------|---------|
| `ops/smart_repair.py` | 471 | Intelligent self-repair |
| `ops/commit_guard.py` | 356 | Git commit safety checks |
| `ops/repair_agent.py` | 321 | Automated repair agent |
| `ops/error_reporter.py` | 234 | Error classification and reporting |
| `ops/auto_updater.py` | 174 | Auto-update mechanism |
| `ops/incident_logger.py` | 84 | Incident logging |

## Configuration

| File | Lines | Purpose |
|------|-------|---------|
| `config/settings.py` | 322 | All environment settings (pydantic) |
| `main.py` | 111 | Entry point, uvicorn startup |

## Key Entry Points

| Entry Point | File | Function | Description |
|-------------|------|----------|-------------|
| Service startup | `main.py` | `main()` | uvicorn + FastAPI |
| Message processing | `gateway/server.py` | `process_message()` | User message → OODA loop |
| OODA loop | `loop/main_loop.py` | `MainLoop.run()` | OBSERVE→ORIENT→DECIDE→ACT→LEARN |
| PM spawning | `loop/main_loop.py` | `MainLoop._decide()` | complexity="project" → PMAgent |
| PM execution | `runtime/pm_agent.py` | `PMAgent.run()` | Plan → Execute → Synthesize |
| Tool execution | `runtime/tool_loop.py` | `agentic_complete()` | LLM + tool state machine |
| Step verification | `runtime/pm_quality_gate.py` | `verify_step()` | Unified quality gate |
