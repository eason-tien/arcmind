# ArcMind — Logic Flow

> Last Updated: 2026-03-14
> Scope: PM System execution flows

---

## 1. PM Task Lifecycle (Main Flow)

```
User Message
  → Gateway (server.py: process_message)
    → Router (router.py: classify → NEW_TASK)
      → MainLoop.run() (main_loop.py)
        → DECIDE phase: classify_complexity()
          → complexity == "project"
            → Create project in ProjectRegistry
            → Instantiate PMAgent(task_id, command, session_ctx)
            → pm_pool.submit(pm)  ← ThreadPoolExecutor
            → Return ack to user immediately
              (user sees "已创建项目...")

[Background Thread]
  PMAgent.run()
    → Phase 1: PLAN
    → Phase 2: EXECUTE (per step)
    → Phase 3: SYNTHESIZE
    → Emit PM_RESULT_READY event
      → ProgressNotifier → Telegram

[Async Event Loop]
  EventBus._worker() picks up PM_RESULT_READY
    → ProgressNotifier._on_event()
      → Extract session_id → Telegram chat_id
      → POST to Telegram Bot API
```

## 2. PM Plan Phase

```
PMAgent.run()
  → _create_plan(self.command)
    → model_router.complete() with planning prompt
    → Strip <think> tags (MiniMax)
    → Parse JSON array → plan_steps: list[str]
    → Fallback: single step if parsing fails
    → Record to decision_journal (if available)
  → pm_quality_gate.evaluate_plan(plan_steps, command)
    → LLM judges plan quality → {rating, reason}
    → "fail" → log warning (plan still executes — no block)
    → "marginal" → ignored (known gap)
  → task_tracker.set_plan(task_id, plan_steps)
  → Emit "pm_plan_created" event
```

## 3. PM Step Execution with Self-Iteration

```
For each step_desc in plan_steps:
  _execute_step_with_retry(step_desc, prior_results, max_retries=2)
    │
    ├── attempt 0: _execute_step(step_desc, prior_results)
    │     → Build system prompt with environment context + prior results
    │     → run_agentic_loop(command, system, model, max_turns=8)
    │       → tool_loop.agentic_complete() — LLM + tool state machine
    │     → Return {success, output, error, tokens}
    │
    ├── _verify_step_output(step_desc, step_result)
    │     → Delegates to pm_quality_gate.verify_step()
    │     → Fast path: success=False → immediate fail
    │     → Fast path: output > 200 chars → assume pass
    │     → Otherwise: LLM judges → {pass, reason, suggestion}
    │
    ├── Record attempt to attempt_history[]
    │
    ├── IF pass → return step_result ✅
    │
    ├── IF fail AND attempt < max_retries:
    │     → _reflect_and_retry(step_desc, result, verification,
    │                          prior_results, attempt, attempt_history)
    │       → Build reflection context with ALL prior attempts
    │       → Inject failure reasons + suggestions into system prompt
    │       → run_agentic_loop() with enriched context
    │       → Return to verify loop ↑
    │
    └── IF fail AND attempt >= max_retries:
          → Downgrade success=True to success=False
          → Return with error: "Verification failed after N attempts"
```

## 4. Post-Step Processing

```
After _execute_step_with_retry returns:
  │
  ├── IF success:
  │     → task_tracker.advance_step(COMPLETED)
  │     → _consecutive_failures = 0
  │
  ├── IF failure:
  │     → task_tracker.advance_step(FAILED)
  │     → _total_failures += 1
  │     → _consecutive_failures += 1
  │     → _diagnose_failure(step_desc, step_result)
  │       → LLM classifies error type + suggests fix
  │       → Emit "pm_step_diagnosed" event
  │       → (NOTE: diagnosis NOT fed back to retry — P2 gap)
  │
  └── IF _consecutive_failures >= 2:
        → pm_escalation.escalate(task_id, reason, context)
          → LLM auto-resolve with 60s timeout
          → Decision: "continue" | "skip_step" | "cancel"
          → "cancel" → TaskStatus.FAILED, return
          → "skip_step" → append result, continue to next step
          → "continue" → reset _consecutive_failures, proceed
```

## 5. PM Synthesis Phase

```
After all steps complete:
  → _synthesize(all_results)
    → Combine step results into summary prompt
    → model_router.complete() → final_output
  → _extract_and_record_artifacts(all_results, plan_steps)
    → LLM identifies created files/artifacts
    → Record to project_registry
  → pm_quality_gate.evaluate_completion(command, results, output)
    → Holistic quality audit
  → task_tracker.set_result(task_id, final_output, tokens)
  → task_tracker.update_status(COMPLETED)
  → _sync_project_status("completed")
  → Emit PM_RESULT_READY → user notification
```

## 6. Event Flow: PM_RESULT_READY

```
PMAgent.run() [worker thread]
  → event_bus.emit(Event(type=PM_RESULT_READY, payload={...}))
    → EventBus.emit() detects worker thread
    → call_soon_threadsafe(enqueue) → main event loop queue
      → EventBus._worker() dequeues
        → _dispatch() → matching handlers
          → ProgressNotifier._on_event()
            → Extracts session_id (e.g., "tg_123456" → "123456")
            → Strips <think> tags
            → Truncates to 3800 chars
            → _send_telegram(msg, chat_id_override)
              → aiohttp POST to Telegram Bot API
```

## 7. Tool Loop State Machine (agentic_complete)

```
States: RUNNING → CHECKPOINT → RETRY → COMPLETED → ESCALATE

RUNNING:
  → LLM call with tools
  → If tool_calls in response → execute tools → continue RUNNING
  → If no tool_calls → CHECKPOINT (check if done)

CHECKPOINT:
  → LLM audit: "Is the task complete?"
  → If yes → COMPLETED
  → If no → RUNNING (continue)
  → If stuck/looping → RETRY

RETRY:
  → Inject retry hint into system prompt
  → Reset turn counter partially
  → → RUNNING

COMPLETED:
  → Return {output, tokens_used}

ESCALATE (max turns reached):
  → Return partial result with warning
```

## 8. Complexity Classification

```
User message → MainLoop._decide()
  → classify_complexity(command)
    → LLM judges: "simple" | "complex" | "project"
    → "simple" → direct tool_loop execution
    → "complex" → direct tool_loop with more turns
    → "project" → spawn PMAgent in thread pool
```

## Key Decision Points

| Decision | Where | Logic | Consequence |
|----------|-------|-------|-------------|
| Task complexity | main_loop._decide() | LLM classification | simple/complex → inline, project → PM |
| Step pass/fail | pm_quality_gate.verify_step() | Fast path + LLM | Controls retry loop |
| Retry vs give up | _execute_step_with_retry() | attempt < max_retries | Max 3 attempts per step |
| Escalate vs continue | run() post-step | _consecutive_failures >= 2 | LLM auto-decides |
| Cancel vs proceed | pm_escalation.escalate() | LLM decision (60s timeout) | Cancel stops entire PM |

## Known Gaps in Current Flow

1. **Diagnosis → Retry disconnect**: `_diagnose_failure` runs AFTER retry loop exhaustion, so its insights never feed back into retries
2. **"marginal" rating ignored**: evaluate_plan and evaluate_completion can return "marginal" but nothing happens
3. **Telegram-only delivery**: PM_RESULT_READY only reaches Telegram users, not WebSocket/HTTP
4. **Plan "fail" not blocking**: evaluate_plan("fail") logs warning but plan executes anyway
