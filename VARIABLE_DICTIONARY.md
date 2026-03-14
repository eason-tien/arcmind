# ArcMind — Variable Dictionary

> Last Updated: 2026-03-14
> Scope: PM System core variables and state fields

---

## PMAgent Instance Variables

| Variable | Type | Module | Purpose | Critical | Affects Main Chain |
|----------|------|--------|---------|----------|-------------------|
| `task_id` | str | pm_agent | Unique PM task identifier (format: `pm_{uuid[:8]}`) | Yes | Yes |
| `command` | str | pm_agent | Original user task description | Yes | Yes |
| `session_context` | dict | pm_agent | Session context including `session_db_id`, `project_id` | Yes | Yes |
| `model` | str | pm_agent | LLM model name for this PM (from `model_router`) | Yes | Yes |
| `worker_id` | str | pm_agent | Worker thread identifier | No | No |
| `_consecutive_failures` | int | pm_agent | Consecutive step failure count (triggers escalation at ≥2) | Yes | Yes |
| `_total_failures` | int | pm_agent | Total step failures across all steps | No | No |
| `_total_steps_executed` | int | pm_agent | Total steps executed counter | No | No |

## PMPool Instance Variables

| Variable | Type | Module | Purpose | Critical |
|----------|------|--------|---------|----------|
| `_executor` | ThreadPoolExecutor | pm_agent | Thread pool (max 5 workers) | Yes |
| `_active` | dict[str, Future] | pm_agent | Currently running PM tasks | Yes |
| `_workers` | dict[str, PMAgent] | pm_agent | PM agent instances by task_id | Yes |
| `_lock` | threading.Lock | pm_agent | Thread safety for _active/_workers | Yes |
| `_total_submitted` | int | pm_agent | Total tasks submitted counter | No |
| `_total_completed` | int | pm_agent | Total tasks completed counter | No |
| `_total_failed` | int | pm_agent | Total tasks failed counter | No |

## Quality Gate Constants

| Variable | Type | Module | Value | Purpose |
|----------|------|--------|-------|---------|
| `_SUBSTANTIVE_OUTPUT_THRESHOLD` | int | pm_quality_gate | 200 | Min output length to skip LLM verification |

## Step Result Dict Structure

| Field | Type | Source | Purpose |
|-------|------|--------|---------|
| `success` | bool | `_execute_step` | Whether step execution succeeded |
| `output` | str | `_execute_step` | Step output text |
| `error` | str/None | `_execute_step` | Error message if failed |
| `tokens` | int | `_execute_step_with_retry` | Total tokens used (including retries) |

## Verification Result Dict Structure

| Field | Type | Source | Purpose |
|-------|------|--------|---------|
| `pass` | bool | `pm_quality_gate.verify_step` | Whether step output meets requirements |
| `reason` | str | `pm_quality_gate.verify_step` | Explanation of pass/fail |
| `suggestion` | str | `pm_quality_gate.verify_step` | Improvement suggestion for retry |

## QA Rating Dict Structure

| Field | Type | Source | Values | Purpose |
|-------|------|--------|--------|---------|
| `rating` | str | `pm_quality_gate.evaluate_*` | "pass", "marginal", "fail" | Quality assessment |
| `reason` | str | `pm_quality_gate.evaluate_*` | Free text | Explanation |

## Escalation Response Dict Structure

| Field | Type | Source | Values | Purpose |
|-------|------|--------|--------|---------|
| `decision` | str | `pm_escalation.escalate` | "continue", "skip_step", "cancel" | Escalation decision |

## TaskTracker State

| Field | Type | Module | Purpose |
|-------|------|--------|---------|
| `TaskStatus.CREATED` | enum | task_tracker | Initial state |
| `TaskStatus.QUEUED` | enum | task_tracker | Waiting for execution |
| `TaskStatus.PLANNING` | enum | task_tracker | PM creating plan |
| `TaskStatus.EXECUTING` | enum | task_tracker | Steps being executed |
| `TaskStatus.COMPLETED` | enum | task_tracker | Successfully finished |
| `TaskStatus.FAILED` | enum | task_tracker | Failed after retries/escalation |
| `TaskStatus.CANCELLED` | enum | task_tracker | Cancelled by escalation |
| `TaskStatus.PAUSED` | enum | task_tracker | Paused (unused currently) |
| `TaskStatus.AUDIT_REVIEW` | enum | task_tracker | Under audit review (unused currently) |

## EventType (PM-Related)

| Value | Module | Emitter | Handler | Purpose |
|-------|--------|---------|---------|---------|
| `PM_RESULT_READY` | event_bus | pm_agent.py:390 | progress_notifier._on_event | Deliver PM result to user |
| `PROJECT_CREATED` | event_bus | main_loop.py | event_handlers | New project created |
| `PROJECT_STATUS_CHANGED` | event_bus | project_registry | event_handlers | Project state transition |
| `PROJECT_COMPLETED` | event_bus | project_registry | event_handlers | Project finished |

## Project Registry States

| State | Module | Transitions To |
|-------|--------|---------------|
| `proposed` | project_registry | planning |
| `planning` | project_registry | in_progress, cancelled |
| `in_progress` | project_registry | review, failed, paused |
| `review` | project_registry | completed, in_progress |
| `completed` | project_registry | archived |
| `failed` | project_registry | in_progress, closed |
| `paused` | project_registry | in_progress, cancelled |
| `archived` | project_registry | closed |
| `cancelled` | project_registry | closed |
| `closed` | project_registry | (terminal) |

## Configuration Keys (PM-Related)

| Key | Source | Default | Purpose |
|-----|--------|---------|---------|
| `arcmind_port` | settings.py | 8100 | Service port |
| `telegram_bot_token` | settings.py | - | Telegram bot authentication |
| `telegram_chat_id` | settings.py | - | Default Telegram chat for notifications |
