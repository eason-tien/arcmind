# ArcMind — TODO & Next Steps

> Last Updated: 2026-03-14
> Context: PM System Audit & Remediation

---

## Immediate (P2)

### Recovery Chain Closure
- [ ] Split `_diagnose_failure()` into `quick_classify()` (fast, pattern-based) + `deep_diagnose()` (LLM-based)
- [ ] Feed diagnosis results into `_reflect_and_retry()` — currently diagnosis and retry operate in silos
- [ ] Ensure diagnosis info flows: `_diagnose_failure` → `_reflect_and_retry` → retry prompt
- **Files**: `runtime/pm_agent.py`
- **Risk**: Medium — changes internal flow but doesn't affect external interfaces

## Next Steps (P1-B)

### Multi-Channel PM Result Delivery
- [ ] Make PM_RESULT_READY handler also push to `delivery_queue` (not just Telegram)
- [ ] Ensure WebSocket/HTTP users receive PM completion results
- [ ] Review `gateway/server.py` delivery_queue pattern from FEDERATION_RESULT handler
- **Files**: `runtime/progress_notifier.py`, possibly `loop/event_handlers.py`
- **Risk**: Medium — affects user experience for non-Telegram channels

## Discovered But Deferred (P3)

### File Structure
- [ ] Split `PMPool` class out of `pm_agent.py` into `runtime/pm_pool.py`
- [ ] pm_agent.py is 1190 lines — still manageable but approaching split threshold

### QA Gate Enhancement
- [ ] Handle "marginal" rating from `pm_quality_gate` — currently ignored
- [ ] Consider: marginal = trigger verify but don't count as failure?

### task_tracker Persistence
- [ ] `runtime/task_tracker.py` is purely in-memory — all state lost on restart
- [ ] Consider: periodic snapshots to SQLite? Or accept ephemeral nature?

### decision_journal Verification
- [ ] `_create_plan()` references `runtime/decision_journal.py` — verify it exists and works
- [ ] If it doesn't exist, either create or remove reference (another ghost module risk)

## Risk Items to Verify

- [ ] Escalation 60s timeout with "continue" fallback — may mask genuine blockers
- [ ] `_sync_project_status` error handling — failures logged at debug level, may hide issues
- [ ] `evaluate_plan()` "marginal" result not acted upon — plan executes regardless

## Future Optimization

- [ ] Token usage tracking per PM task — measure actual cost of verify/retry loop
- [ ] PM step parallelization — some plans have independent steps that could run concurrently
- [ ] Quality gate learning — feed historical pass/fail patterns back for improved thresholds
