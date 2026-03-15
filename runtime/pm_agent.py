# -*- coding: utf-8 -*-
"""
PM Agent — Background Project Manager for complex tasks.
Runs in ThreadPoolExecutor, plans steps, executes via MainLoop,
reports progress via TaskTracker + EventBus.
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

logger = logging.getLogger("arcmind.pm_agent")


class PMAgent:
    """Project Manager Agent. Spawned by Main for complex tasks."""

    def __init__(self, task_id: str, command: str, session_context: dict,
                 worker_id: str = ""):
        self.task_id = task_id
        self.command = command
        self.session_context = session_context
        self.worker_id = worker_id or "pm-worker-0"
        # V3: Read PM model from agent_registry config
        self.model: str = self._resolve_model()
        # V2 Phase 2: QC tracking
        self._consecutive_failures = 0
        self._total_failures = 0
        self._total_steps_executed = 0

    def _resolve_model(self) -> str:
        """Resolve PM Agent's model from agent_registry config."""
        try:
            from runtime.agent_registry import agent_registry
            pm_persona = agent_registry.get("pm")
            if pm_persona and pm_persona.default_model:
                return pm_persona.default_model
        except Exception:
            pass
        return "custom:MiniMax-M2.5"  # Fallback default

    def _get_environment_context(self) -> str:
        """Build environment description so PM plans use real capabilities."""
        lines = [
            "本系统是 ArcMind — 一个运行在本地 macOS 上的 AI 自主代理。",
            "",
            "### 可用工具",
            "- web_search: 搜索互联网（DuckDuckGo），支持 fast/deep/research 模式",
            "- run_command: 在本地 macOS 执行 shell 命令（bash）",
            "- read_file: 读取本地文件内容",
            "- write_file: 写入本地文件",
            "- list_directory: 列出目录内容",
            "- python_eval: 执行 Python 代码",
            "- memory_query: 查询长期记忆",
            "- memory_save: 保存信息到长期记忆",
            "",
            "### run_command 注意事项",
            "- 允许的命令: ls, cat, head, tail, grep, find, echo, mkdir, cp, mv, touch, rm,",
            "  git, npm, node, pip, python3, curl, wget, docker, jq, sed, awk, sort, tar, zip 等",
            "- cd 不可用（每次 run_command 都是独立子进程），请用绝对路径",
            "- 例: mkdir -p /Users/eason/Code/arcmind/output/reports",
            "- 例: ls /Users/eason/Code/arcmind/data/",
            "",
            "### 不可用（禁止生成）",
            "- 没有外部服务器（禁止 ssh、scp、rsync）",
            "- 没有 MySQL/PostgreSQL 客户端（本地只有 SQLite）",
            "- 不能进行人工操作（禁止访谈、开会、面对面沟通）",
            "- 不能发送邮件、打电话",
            "- 没有 Docker/K8s 集群（除非用 run_command 检查是否安装）",
            "",
            "### 本地数据库",
            f"- SQLite 数据库路径: data/arcmind.db",
            f"- 向量记忆库: data/vector_memory.db",
            "",
            "### 项目目录",
            f"- 工作目录: /Users/eason/Code/arcmind",
        ]
        return "\n".join(lines)

    def run(self) -> None:
        """Main PM execution flow. Called by PMPool in a worker thread."""
        from runtime.task_tracker import task_tracker, TaskStatus

        try:
            # V3: Register worker identity in task tracker for monitoring
            task_tracker.set_worker_info(self.task_id, self.worker_id, self.model)
            task_tracker.update_status(
                self.task_id, TaskStatus.PLANNING,
                log_msg=f"PM [{self.worker_id}] 已启动 (model={self.model})，正在分析任务..."
            )
            self._emit("pm_started", {
                "task_id": self.task_id, "command": self.command[:80],
                "worker_id": self.worker_id, "model": self.model,
            })
            # V3: Audit event for PM start
            self._audit("pm_started",
                        f"PM [{self.worker_id}] 已启动 (model={self.model})",
                        severity="info")
            logger.info("[PM:%s][%s] Started with model=%s",
                        self.task_id, self.worker_id, self.model)

            # Phase 1: Plan
            plan_steps = self._create_plan()
            if not plan_steps:
                task_tracker.update_status(
                    self.task_id, TaskStatus.FAILED,
                    log_msg="无法创建执行计划"
                )
                self._emit("pm_failed", {"task_id": self.task_id, "error": "Plan creation failed"})
                return

            # V2 Phase 2: Plan quality review
            try:
                from runtime.pm_quality_gate import pm_quality_gate
                plan_verdict = pm_quality_gate.evaluate_plan(plan_steps, self.command)
                if plan_verdict.get("rating") == "fail":
                    logger.warning("[PM:%s] Plan QA failed: %s, regenerating...",
                                   self.task_id, plan_verdict.get("reason", ""))
                    plan_steps = self._create_plan()
                    if not plan_steps:
                        task_tracker.update_status(self.task_id, TaskStatus.FAILED,
                                                   log_msg="计划质量不合格且重新规划失败")
                        self._emit("pm_failed", {"task_id": self.task_id, "error": "Plan QA failed"})
                        return
            except ImportError:
                pass
            except Exception as e:
                logger.debug("[PM:%s] Plan QA skipped: %s", self.task_id, e)

            task_tracker.set_plan(self.task_id, plan_steps)
            task_tracker.update_status(
                self.task_id, TaskStatus.EXECUTING,
                log_msg=f"计划完成: {len(plan_steps)} 步"
            )
            self._emit("pm_plan_created", {
                "task_id": self.task_id,
                "steps": len(plan_steps),
                "plan": plan_steps,
            })

            # V2: Sync project status to in_progress
            self._sync_project_status("in_progress")

            # Phase 2: Execute steps
            all_results = []
            for i, step_desc in enumerate(plan_steps):
                task_tracker.advance_step(self.task_id, i, TaskStatus.EXECUTING)
                task_tracker.update_status(
                    self.task_id, TaskStatus.EXECUTING,
                    progress_pct=((i + 0.5) / len(plan_steps)),  # mid-step progress
                    log_msg=f"执行步骤 {i+1}/{len(plan_steps)}: {step_desc[:50]}"
                )
                self._emit("pm_step_start", {
                    "task_id": self.task_id,
                    "step": i + 1,
                    "total": len(plan_steps),
                    "description": step_desc,
                })

                step_result = self._execute_step_with_retry(step_desc, all_results)
                self._total_steps_executed += 1
                _step_diagnosis = None  # Initialize before branching

                if step_result.get("success"):
                    task_tracker.advance_step(
                        self.task_id, i, TaskStatus.COMPLETED,
                        result=str(step_result.get("output", ""))[:200]
                    )
                    self._consecutive_failures = 0
                else:
                    task_tracker.advance_step(
                        self.task_id, i, TaskStatus.FAILED,
                        result=str(step_result.get("error", ""))[:200]
                    )
                    self._total_failures += 1
                    self._consecutive_failures += 1
                    logger.warning("[PM:%s] Step %d failed: %s",
                                   self.task_id, i+1, step_result.get("error", ""))

                    # V3.1: Auto-diagnose on first failure
                    try:
                        _step_diagnosis = self._diagnose_failure(step_desc, step_result)
                        if _step_diagnosis and _step_diagnosis.get("repair_status") != "no_fix":
                            logger.info("[PM:%s] Diagnosis found: %s → %s",
                                        self.task_id, _step_diagnosis["error_type"],
                                        _step_diagnosis.get("error_summary", "")[:80])
                            self._emit("pm_step_diagnosed", {
                                "task_id": self.task_id,
                                "step": i + 1,
                                "error_type": _step_diagnosis["error_type"],
                                "repair_status": _step_diagnosis["repair_status"],
                            })
                    except Exception as diag_err:
                        logger.debug("[PM:%s] Step diagnosis failed: %s", self.task_id, diag_err)

                # Check failure threshold → escalate (V3.1: enriched with diagnosis)
                # Note: step verification already happened inside _execute_step_with_retry
                # via pm_quality_gate.verify_step() — no need for a second QA call.
                if self._consecutive_failures >= 2:
                    try:
                        from runtime.pm_escalation import pm_escalation

                        # V3.1: Build enriched escalation context
                        _esc_context = {
                            "original_task": self.command[:300],
                            "current_step": step_desc[:200],
                            "failures": self._total_failures,
                            "steps_executed": self._total_steps_executed,
                        }

                        # Inject diagnosis into escalation
                        if _step_diagnosis:
                            _esc_context["diagnosis"] = {
                                "error_type": _step_diagnosis.get("error_type", "unknown"),
                                "error_summary": _step_diagnosis.get("error_summary", "")[:300],
                                "known_solution": _step_diagnosis.get("known_solution"),
                                "web_suggestions": _step_diagnosis.get("web_suggestions", [])[:3],
                                "repair_status": _step_diagnosis.get("repair_status", "no_fix"),
                            }
                            _esc_reason = (
                                f"连续 {self._consecutive_failures} 步失败 "
                                f"[{_step_diagnosis['error_type']}]: "
                                f"{_step_diagnosis.get('error_summary', '')[:100]}"
                            )
                        else:
                            _esc_reason = f"连续 {self._consecutive_failures} 步失败"

                        _esc_context["last_error"] = str(step_result.get("error", ""))[:500]

                        response = pm_escalation.escalate(
                            task_id=self.task_id,
                            reason=_esc_reason,
                            context=_esc_context,
                        )
                        if response and response.get("decision") == "cancel":
                            logger.info("[PM:%s] Escalation → cancel", self.task_id)
                            task_tracker.update_status(
                                self.task_id, TaskStatus.FAILED,
                                log_msg="升级后决定取消任务"
                            )
                            self._emit("pm_failed", {"task_id": self.task_id,
                                                      "error": "Escalation: cancelled"})
                            self._sync_project_status("failed", "Escalation cancelled")
                            return
                        elif response and response.get("decision") == "skip_step":
                            all_results.append(step_result)
                            # Update progress before skipping to next step
                            task_tracker.update_status(
                                self.task_id, TaskStatus.EXECUTING,
                                progress_pct=((i + 1) / len(plan_steps)),
                                log_msg=f"步骤 {i+1}/{len(plan_steps)} 已跳过"
                            )
                            continue
                        # "continue" or timeout → proceed anyway
                        self._consecutive_failures = 0
                    except ImportError:
                        pass
                    except Exception as esc_err:
                        logger.debug("[PM:%s] Escalation failed: %s", self.task_id, esc_err)

                all_results.append(step_result)

                # Update progress after step completion
                task_tracker.update_status(
                    self.task_id, TaskStatus.EXECUTING,
                    progress_pct=((i + 1) / len(plan_steps)),
                    log_msg=f"步骤 {i+1}/{len(plan_steps)} 完成"
                )

            # Phase 3: Synthesize
            session_db_id = self.session_context.get("session_db_id", "")
            # V2 Phase 2: Extract artifacts before synthesizing
            self._extract_and_record_artifacts(all_results, plan_steps)

            final_output = self._synthesize(all_results)
            # Strip <think> tags from LLM response (MiniMax reasoning artifacts)
            final_output = re.sub(r'<think>[\s\S]*?</think>\s*', '', final_output).strip()
            total_tokens = sum(r.get("tokens", 0) for r in all_results)

            # V2 Phase 2: Completion audit
            try:
                from runtime.pm_quality_gate import pm_quality_gate
                audit = pm_quality_gate.evaluate_completion(
                    self.command, all_results, final_output
                )
                if audit.get("rating") == "fail":
                    logger.warning("[PM:%s] Completion audit FAILED: %s",
                                   self.task_id, audit.get("reason", ""))
                    try:
                        from runtime.pm_escalation import pm_escalation
                        response = pm_escalation.escalate(
                            task_id=self.task_id,
                            reason=f"完成审计不通过: {audit.get('reason', '')}",
                            context={
                                "original_task": self.command[:300],
                                "output_preview": final_output[:500],
                                "step_count": len(all_results),
                            }
                        )
                        if response and response.get("decision") == "cancel":
                            task_tracker.update_status(self.task_id, TaskStatus.FAILED,
                                                       log_msg="审计失败,任务取消")
                            self._emit("pm_failed", {"task_id": self.task_id,
                                                      "error": f"Audit failed: {audit.get('reason', '')}"})
                            self._sync_project_status("failed", audit.get("reason", ""))
                            return
                    except ImportError:
                        pass
            except ImportError:
                pass
            except Exception as audit_err:
                logger.debug("[PM:%s] Completion audit skipped: %s", self.task_id, audit_err)

            # V2 Phase 2: Persist full result to database
            project_id = self.session_context.get("project_id")
            if project_id:
                try:
                    from runtime.project_registry import project_registry
                    project_registry.generate_report(
                        project_id=project_id,
                        report_type="pm_completion",
                        content=final_output,
                        metadata={
                            "pm_task_id": self.task_id,
                            "steps_total": len(plan_steps),
                            "steps_ok": sum(1 for r in all_results if r.get("success")),
                            "steps_failed": sum(1 for r in all_results if not r.get("success")),
                            "total_tokens": total_tokens,
                        }
                    )
                    logger.info("[PM:%s] Result persisted to project %d", self.task_id, project_id)
                except Exception as persist_err:
                    logger.debug("[PM:%s] Result persistence failed: %s", self.task_id, persist_err)

            # ── Audit event for completion ────────────────────────────────
            self._audit("pm_completed", f"PM 完成: {len(plan_steps)} 步, tokens={total_tokens}")

            task_tracker.set_result(self.task_id, final_output, total_tokens)
            task_tracker.update_status(
                self.task_id, TaskStatus.COMPLETED,
                progress_pct=1.0,
                log_msg="所有步骤已完成"
            )
            self._emit("pm_completed", {
                "task_id": self.task_id,
                "output_preview": str(final_output)[:200],
                "tokens": total_tokens,
            })

            # V2 Phase 2: Deliver full result to user's Telegram session
            if final_output:
                if not session_db_id:
                    logger.warning("[PM:%s] No session_db_id — result saved but cannot push to user", self.task_id)
                try:
                    from runtime.event_bus import event_bus, Event, EventType
                    result_event = Event(
                        type=EventType.PM_RESULT_READY,
                        source="pm_agent",
                        payload={
                            "event": "pm_result_ready",
                            "session_id": session_db_id or "",
                            "task_id": self.task_id,
                            "project_id": project_id,
                            "result": final_output,
                        }
                    )
                    event_bus.emit(result_event)  # Thread-safe since v0.9.2
                    logger.info("[PM:%s] Result delivery event emitted (session=%s)", self.task_id, session_db_id)
                except Exception as delivery_err:
                    logger.warning("[PM:%s] Result delivery failed: %s", self.task_id, delivery_err)

            # Sync completion back to ProjectRegistry
            self._sync_project_status("completed", final_output)

        except Exception as e:
            logger.exception("[PM:%s] Crashed: %s", self.task_id, e)
            task_tracker.update_status(
                self.task_id, TaskStatus.FAILED,
                log_msg=f"PM 异常: {e}"
            )
            self._emit("pm_failed", {"task_id": self.task_id, "error": str(e)})
            self._audit("pm_failed", f"PM 异常: {str(e)[:200]}", severity="error")

            # Sync failure back to ProjectRegistry
            self._sync_project_status("failed", str(e))



    def _extract_and_record_artifacts(self, all_results: list[dict], plan_steps: list[str]) -> None:
        """V2 Phase 2: Use LLM to identify created artifacts."""
        project_id = self.session_context.get("project_id")
        if not project_id:
            return
        try:
            from runtime.model_router import model_router
            import json as _json

            summary = "\n".join(
                f"Step {i+1}: {r.get('output', '')[:300]}"
                for i, r in enumerate(all_results) if r.get("success")
            )
            if not summary.strip():
                return

            resp = model_router.complete(
                prompt=(
                    f"分析以下PM Agent执行结果，提取创建的文件/服务/脚本等工作成果。\n\n"
                    f"结果:\n{summary[:2000]}\n\n"
                    f'回复JSON数组: [{{"type":"file|service|script|config", "name":"名称", "path":"路径", "description":"用途"}}]\n'
                    f"没有成果则回复 []"
                ),
                system="你是工作成果提取器。只回复JSON数组。",
                model=self.model, max_tokens=512, task_type="general", budget="medium",
            )
            text = resp.content.strip()
            text = re.sub(r'<think>[\s\S]*?</think>\s*', '', text).strip()
            s = text.find("[")
            e = text.rfind("]") + 1
            if s >= 0 and e > s:
                raw_json = text[s:e]
                # Fix trailing commas before parsing
                raw_json = re.sub(r',\s*]', ']', raw_json)
                raw_json = re.sub(r',\s*}', '}', raw_json)
                artifacts = _json.loads(raw_json)
                if isinstance(artifacts, list):
                    from runtime.project_registry import project_registry
                    sid = str(self.session_context.get("session_db_id", ""))
                    for a in artifacts[:10]:
                        if isinstance(a, dict) and a.get("name"):
                            project_registry.record_artifact(
                                project_id=project_id, artifact_type=a.get("type","file"),
                                name=a.get("name","?"), path=a.get("path",""),
                                description=a.get("description",""),
                                created_by="pm_agent", pm_task_id=self.task_id, session_id=sid,
                            )
                    logger.info("[PM:%s] Recorded %d artifacts", self.task_id, len(artifacts))
        except Exception as e:
            logger.debug("[PM:%s] Artifact extraction failed: %s", self.task_id, e)

    def _sync_project_status(self, status: str, result=None) -> None:
        """V2: Sync PM completion/failure back to ProjectRegistry."""
        project_id = self.session_context.get("project_id")
        if not project_id:
            return
        try:
            from runtime.project_registry import project_registry

            if status == "in_progress":
                project = project_registry.get_project(project_id)
                if project and project["status"] == "planning":
                    project_registry.transition_project(project_id, "in_progress")
                    logger.info("[PM:%s] Project %d synced → in_progress", self.task_id, project_id)

            elif status == "completed":
                project = project_registry.get_project(project_id)
                if project:
                    current = project["status"]
                    # Auto-advance through intermediate states, each step validated
                    _advance_path = {
                        "planning": ["in_progress", "review", "completed"],
                        "in_progress": ["review", "completed"],
                        "review": ["completed"],
                    }
                    for next_status in _advance_path.get(current, []):
                        try:
                            project_registry.transition_project(project_id, next_status)
                        except ValueError as ve:
                            logger.warning("[PM:%s] Project %d transition failed at %s: %s",
                                           self.task_id, project_id, next_status, ve)
                            break
                    project_registry.update_project(project_id, progress=1.0)
                    logger.info("[PM:%s] Project %d synced → completed", self.task_id, project_id)

            elif status == "failed":
                project = project_registry.get_project(project_id)
                if project and project["status"] in ("planning", "in_progress"):
                    project_registry.transition_project(project_id, "failed")
                    logger.info("[PM:%s] Project %d synced → failed", self.task_id, project_id)

        except ImportError:
            pass
        except Exception as e:
            logger.debug("[PM:%s] Project sync error: %s", self.task_id, e)

    # ── V3.1: Step Failure Auto-Diagnosis ─────────────────────────────────

    def _diagnose_failure(self, step_desc: str, step_result: dict,
                          max_seconds: int = 30) -> dict:
        """
        V3.1: 當步驟失敗時自動診斷，嘗試找到根因和修復建議。

        流程:
        1. 解析錯誤文本 → 分類 (HTTP 4xx/5xx, ConnectionError, DNS, Python Error 等)
        2. 查詢 smart_repair 本地記憶庫找已知解決方案
        3. 若無已知方案 → 使用 web_search 搜尋 (有 max_seconds 限制)
        4. 返回診斷結果供 escalation 使用

        max_seconds: 診斷總時長上限，超過則跳過 web_search，只返回分類結果。
                     預設 30s，避免拖慢主流程。

        Returns:
            {
                "error_type": str,
                "error_summary": str,
                "known_solution": dict|None,
                "web_suggestions": list,
                "repair_status": str,
                "raw_error": str,
            }
        """
        import concurrent.futures

        error_text = str(step_result.get("error", ""))
        output_text = str(step_result.get("output", ""))
        combined = f"{error_text}\n{output_text}"

        diagnosis = {
            "error_type": "unknown",
            "error_summary": error_text[:200],
            "known_solution": None,
            "web_suggestions": [],
            "repair_status": "no_fix",
            "raw_error": error_text[:500],
        }

        # ── 1. 錯誤分類 ────────────────────────────────
        error_type, search_query = self._classify_error(combined)
        diagnosis["error_type"] = error_type

        if not search_query:
            search_query = f"{error_type} {error_text[:80]}"

        logger.info("[PM:%s] Diagnosis: error_type=%s", self.task_id, error_type)

        # ── 2. 查詢已知解決方案 (smart_repair 記憶庫) ──────
        try:
            from ops.smart_repair import _lookup_known_solution
            known = _lookup_known_solution(error_type, error_text[:200])
            if known:
                diagnosis["known_solution"] = known
                diagnosis["repair_status"] = "suggestion"
                diagnosis["error_summary"] = (
                    f"{error_type}: 已知方案 → {known.get('fix_action', '')[:100]}"
                )
                logger.info("[PM:%s] Found known solution: %s",
                            self.task_id, known.get("fix_action", "")[:80])
                return diagnosis
        except Exception as e:
            logger.debug("[PM:%s] Known solution lookup failed: %s", self.task_id, e)

        # ── 3. Web 搜尋 (帶超時保護，避免拖慢主流程) ─────
        try:
            from ops.smart_repair import _web_search, _analyze_search_results

            def _do_web_search():
                return _web_search(search_query, max_results=3)

            logger.info("[PM:%s] Searching web (max %ds): %s",
                        self.task_id, max_seconds, search_query[:80])

            results = None
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(_do_web_search)
                try:
                    results = fut.result(timeout=max_seconds)
                except concurrent.futures.TimeoutError:
                    logger.warning("[PM:%s] Web search timed out (%ds), skipping",
                                   self.task_id, max_seconds)

            if results:
                error_info = {
                    "error_type": error_type,
                    "error_message": error_text[:300],
                }
                fix = _analyze_search_results(error_info, results)

                if fix:
                    diagnosis["web_suggestions"] = [
                        fix.get("fix_action", ""),
                        *[s[:200] if isinstance(s, str) else str(s)[:200]
                          for s in fix.get("web_suggestions", [])[:3]],
                    ]
                    diagnosis["repair_status"] = "suggestion"
                    diagnosis["error_summary"] = (
                        f"{error_type}: web建議 → {fix.get('fix_action', '')[:100]}"
                    )
                else:
                    diagnosis["web_suggestions"] = [
                        r.get("title", "") + ": " + r.get("body", "")[:100]
                        for r in results[:3]
                    ]
                    diagnosis["error_summary"] = (
                        f"{error_type}: 搜到 {len(results)} 條結果但無明確方案"
                    )
        except Exception as e:
            logger.debug("[PM:%s] Web search diagnosis failed: %s", self.task_id, e)

        return diagnosis

    def _classify_error(self, error_text: str) -> tuple[str, str]:
        """
        分類錯誤類型並生成搜尋查詢。

        Returns:
            (error_type, search_query)
        """
        text = error_text.lower()

        # HTTP 狀態碼
        http_match = re.search(r'(?:status[_ ]?code|http)[:\s]*(\d{3})', text)
        if http_match:
            code = int(http_match.group(1))
            if code == 403:
                return "http_403_forbidden", "API 403 forbidden cloudflare blocked fix"
            elif code == 401:
                return "http_401_unauthorized", "API 401 unauthorized authentication fix"
            elif code == 429:
                return "http_429_rate_limit", "API 429 rate limit exceeded retry"
            elif code == 500:
                return "http_500_server_error", "API 500 internal server error"
            elif code == 502 or code == 503:
                return f"http_{code}_unavailable", f"API {code} service unavailable"
            elif 400 <= code < 500:
                return f"http_{code}_client_error", f"API HTTP {code} error fix"
            elif 500 <= code < 600:
                return f"http_{code}_server_error", f"API HTTP {code} server error"

        # Cloudflare 特徵 (require cloudflare-specific patterns, not just "challenge")
        if "cloudflare" in text or "cf-mitigated" in text or "managed challenge" in text or "cf-ray" in text:
            return "cloudflare_blocked", "cloudflare managed challenge API blocked bypass"

        # DNS / 連線錯誤
        if "dns" in text or "name or service not known" in text or "getaddrinfo" in text:
            return "dns_failure", "DNS resolution failed fix"
        if "connectionerror" in text or "connection refused" in text:
            return "connection_error", "connection refused server unreachable fix"
        if "timeout" in text or "timed out" in text:
            return "timeout_error", "request timeout connection fix"
        if "ssl" in text and ("certificate" in text or "verify" in text):
            return "ssl_error", "SSL certificate verification failed fix"

        # Python 標準錯誤
        py_match = re.search(r'([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*(?:Error|Exception)):', error_text)
        if py_match:
            err_cls = py_match.group(1)
            if "ModuleNotFoundError" in err_cls:
                mod_match = re.search(r"No module named '(\w+)'", error_text)
                mod_name = mod_match.group(1) if mod_match else ""
                return "module_not_found", f"python ModuleNotFoundError {mod_name} pip install"
            elif "ImportError" in err_cls:
                return "import_error", f"python ImportError {error_text[:60]}"
            elif "ValidationError" in err_cls:
                return "validation_error", f"python ValidationError {error_text[:60]}"
            elif "PermissionError" in err_cls:
                return "permission_error", f"python PermissionError {error_text[:60]}"
            else:
                return err_cls.lower(), f"python {err_cls} {error_text[:60]}"

        # JSON 解析
        if "json" in text and ("decode" in text or "parse" in text):
            return "json_parse_error", "JSON decode error unexpected response"

        # 通用
        return "unknown_error", ""

    def _create_plan(self) -> list[str]:
        """Use LLM to decompose the task into 3-8 executable steps."""
        from runtime.model_router import model_router

        # Build environment context so LLM knows what's available
        env_context = self._get_environment_context()

        try:
            resp = model_router.complete(
                prompt=(
                    f"你是 ArcMind 系统的项目经理。将任务分解为可执行步骤。\n\n"
                    f"## 系统环境\n{env_context}\n\n"
                    f"## 重要规则\n"
                    f"- 每个步骤必须使用上面列出的「可用工具」来执行\n"
                    f"- 禁止生成 ssh、scp、mysql 等系统没有的外部服务命令\n"
                    f"- 禁止生成需要人工操作的步骤（如访谈、开会）\n"
                    f"- 步骤描述应该是具体的操作指令，不是抽象目标\n"
                    f"- 步骤数量控制在 3-6 步\n\n"
                    f"## 任务\n{self.command}\n\n"
                    f"回复格式: JSON 数组\n"
                    f'["步骤1: 用web_search搜索...", "步骤2: 用python_eval分析...", ...]\n'
                    f"只回复 JSON 数组，不要其他内容。"
                ),
                system=(
                    "你是 ArcMind 项目经理。根据系统实际可用的工具来拆解任务。"
                    "不要幻想系统没有的能力。只回复JSON数组。"
                ),
                model=self.model,
                max_tokens=1024,
                task_type="planning",
                budget="high",
            )
            text = resp.content.strip()
            # Strip <think> tags (MiniMax reasoning) before JSON parsing
            text = re.sub(r'<think>[\s\S]*?</think>\s*', '', text).strip()
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                try:
                    steps = json.loads(text[start:end])
                except json.JSONDecodeError:
                    # Try to fix common JSON issues: trailing commas, unescaped quotes
                    fixed = text[start:end]
                    fixed = re.sub(r',\s*]', ']', fixed)  # trailing comma
                    fixed = re.sub(r',\s*}', '}', fixed)  # trailing comma in obj
                    steps = json.loads(fixed)
                if isinstance(steps, list) and len(steps) >= 1:
                    final_steps = [str(s) for s in steps[:8]]

                    # V3: Record planning decision in DecisionJournal
                    try:
                        from runtime.decision_journal import decision_journal
                        decision_journal.record(
                            decision_type="planning",
                            summary=f"PM 将任务分解为 {len(final_steps)} 步",
                            rationale=f"任务: {self.command[:300]}",
                            alternatives=[f"单步执行: {self.command[:100]}"],
                            chosen_action=f"分解为 {len(final_steps)} 步: {', '.join(s[:30] for s in final_steps)}",
                            decided_by="pm_agent",
                            project_id=self.session_context.get("project_id"),
                            task_id=self.task_id,
                        )
                    except Exception:
                        pass

                    return final_steps
        except Exception as e:
            logger.warning("[PM:%s] Plan creation failed: %s", self.task_id, e)

        # Fallback: single step with tool guidance
        return [f"使用可用工具（web_search, run_command, read_file, write_file, python_eval 等）完成: {self.command}"]

    def _execute_step(self, step_desc: str, prior_results: list) -> dict:
        """
        Execute a single step. V5: Try Delegator first for specialist routing,
        then fallback to direct agentic tool loop.

        Priority:
        1. Delegator → sub-agent (search/code/qa/sre) if confidence >= 0.70
        2. Direct run_agentic_loop (PM's own LLM + tools)
        """
        # ── V5: Try Delegator for specialist sub-agent ──
        try:
            from runtime.delegator import delegator
            match = delegator.route(step_desc)
            if match and match.confidence >= 0.70:
                logger.info("[PM:%s] Delegating step to %s (conf=%.2f): %s",
                            self.task_id, match.agent_id, match.confidence,
                            step_desc[:60])
                result = delegator.execute(match, step_desc)
                if result.get("success"):
                    return {
                        "success": True,
                        "output": result.get("output", ""),
                        "error": None,
                        "tokens": result.get("tokens", 0),
                        "delegated_to": match.agent_id,
                    }
                # Delegation failed → fallback to direct execution below
                logger.warning("[PM:%s] Delegated step failed (%s), falling back to direct",
                               self.task_id, match.agent_id)
        except Exception as deleg_err:
            logger.debug("[PM:%s] Delegator routing skipped: %s", self.task_id, deleg_err)

        # ── Fallback: Direct agentic tool loop ──
        from runtime.tool_loop import run_agentic_loop

        # Build prior context summary
        prior_ctx = ""
        if prior_results:
            # Show last 3 results with correct step numbering
            recent = prior_results[-3:]
            offset = len(prior_results) - len(recent)
            prior_ctx = "\n前序步骤结果:\n" + "\n".join(
                f"- Step {offset + i + 1}: {str(r.get('output', ''))[:200]}"
                for i, r in enumerate(recent)
            )

        # Build system prompt for this PM worker
        env = self._get_environment_context()
        system = (
            f"你是 ArcMind PM Worker [{self.worker_id}]。\n"
            f"你正在执行项目任务的一个步骤。使用可用工具完成任务。\n\n"
            f"{env}\n\n"
            f"原始任务: {self.command[:300]}\n"
            f"{prior_ctx}\n\n"
            f"要求: 完成当前步骤并汇报结果。\n"
            f"完成后请说明: 1)你使用了什么工具 2)执行了什么操作 3)得到了什么结果。\n"
            f"简洁、准确、包含具体数据或文件路径。"
        )

        try:
            # Direct agentic tool loop — no MainLoop, no classifier, no task creation
            result = run_agentic_loop(
                command=step_desc,
                system=system,
                model=self.model,
                max_turns=8,
                max_tokens=4096,
                task_type="general",
                budget="high",
            )
            output = result.get("output", "")
            tokens = result.get("tokens_used", 0)

            # Check for substantive output — empty or error-only output is a failure
            if not output or not output.strip():
                return {
                    "success": False,
                    "output": "(empty output)",
                    "error": "Step produced no output",
                    "tokens": tokens,
                }

            return {
                "success": True,
                "output": output,
                "error": None,
                "tokens": tokens,
            }
        except Exception as e:
            logger.error("[PM:%s] Step execution failed: %s", self.task_id, e)
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "tokens": 0,
            }

    # ── Self-Iteration: Verify → Reflect → Retry ─────────────────────────

    def _verify_step_output(self, step_desc: str, step_result: dict) -> dict:
        """
        Verify step output via the unified quality gate.

        Delegates to pm_quality_gate.verify_step() — single source of truth
        for all step-level quality judgments. Returns:
        {"pass": bool, "reason": str, "suggestion": str}
        """
        try:
            from runtime.pm_quality_gate import pm_quality_gate
            return pm_quality_gate.verify_step(step_desc, step_result, model=self.model)
        except ImportError:
            logger.debug("[PM:%s] QA gate not available, falling back", self.task_id)
            # Minimal fallback if module unavailable
            if not step_result.get("success"):
                return {"pass": False, "reason": step_result.get("error", "Failed"), "suggestion": ""}
            return {"pass": True, "reason": "QA unavailable", "suggestion": ""}

    def _reflect_and_retry(self, step_desc: str, step_result: dict,
                           verification: dict, prior_results: list,
                           attempt: int, attempt_history: list = None,
                           diagnosis: dict = None) -> dict:
        """
        Reflect on failure, adjust approach, and retry the step.

        Injects the failure reason, improvement suggestion, and ALL prior
        attempt history into the retry prompt so the LLM can self-correct
        without repeating the same approaches.
        """
        from runtime.tool_loop import run_agentic_loop

        reason = verification.get("reason", "Unknown failure")
        suggestion = verification.get("suggestion", "")
        prev_output = str(step_result.get("output", ""))[:300]

        # Build reflection context with full attempt history
        reflection = f"\n\n## ⚠️ 前次尝试失败 (第 {attempt} 次重试)\n"

        # Include all prior attempts so LLM doesn't repeat failed approaches
        if attempt_history:
            reflection += "### 历次尝试记录:\n"
            for h in attempt_history:
                reflection += (
                    f"- 第 {h['attempt']+1} 次: {h['reason']}\n"
                    f"  输出: {h['output_preview'][:100]}\n"
                )
            reflection += "\n"

        reflection += (
            f"- 最近失败原因: {reason}\n"
            f"- 改进建议: {suggestion}\n"
        )
        if prev_output.strip():
            reflection += f"- 前次输出: {prev_output[:200]}\n"

        # P1-2: 注入診斷結果（error_type, known_solution, web_suggestions）
        if diagnosis:
            reflection += f"\n### 自動診斷\n"
            reflection += f"- 錯誤類型: {diagnosis.get('error_type', 'unknown')}\n"
            if diagnosis.get('known_solution'):
                sol = diagnosis['known_solution']
                reflection += f"- 已知解決方案: {sol.get('fix_action', '')}\n"
            if diagnosis.get('web_suggestions'):
                reflection += "- 網路搜尋建議:\n"
                for ws in diagnosis['web_suggestions'][:3]:
                    reflection += f"  • {ws[:150]}\n"

        reflection += f"\n请根据以上反思和诊断信息，换一种完全不同的方式完成任务。避免重复已尝试过的方法。"

        # Build prior context
        prior_ctx = ""
        if prior_results:
            recent = prior_results[-3:]
            offset = len(prior_results) - len(recent)
            prior_ctx = "\n前序步骤结果:\n" + "\n".join(
                f"- Step {offset + i + 1}: {str(r.get('output', ''))[:200]}"
                for i, r in enumerate(recent)
            )

        env = self._get_environment_context()
        system = (
            f"你是 ArcMind PM Worker [{self.worker_id}]。\n"
            f"你正在重试一个之前失败的步骤。请仔细阅读失败原因并调整策略。\n\n"
            f"{env}\n\n"
            f"原始任务: {self.command[:300]}\n"
            f"{prior_ctx}\n"
            f"{reflection}\n\n"
            f"要求: 完成当前步骤并汇报结果。简洁、准确。"
        )

        try:
            result = run_agentic_loop(
                command=step_desc,
                system=system,
                model=self.model,
                max_turns=8,
                max_tokens=4096,
                task_type="general",
                budget="high",
            )
            output = result.get("output", "")
            tokens = result.get("tokens_used", 0)

            if not output or not output.strip():
                return {
                    "success": False,
                    "output": "(empty output on retry)",
                    "error": f"Retry {attempt} produced no output",
                    "tokens": tokens,
                }

            return {
                "success": True,
                "output": output,
                "error": None,
                "tokens": tokens,
            }
        except Exception as e:
            logger.error("[PM:%s] Retry %d failed: %s", self.task_id, attempt, e)
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "tokens": 0,
            }

    def _execute_step_with_retry(self, step_desc: str, prior_results: list,
                                  max_retries: int = 2) -> dict:
        """
        Execute a step with self-verification, diagnosis, and reflection-based retry.

        Flow: Execute → Verify → (if fail) Diagnose → Reflect → Retry → Verify → ...
        P1-2: Diagnosis results now feed into retry prompt.
        """
        total_tokens = 0
        attempt_history = []  # Track all prior attempts for reflection
        last_diagnosis = None  # P1-2: carry diagnosis across retries

        for attempt in range(max_retries + 1):
            # Execute (first attempt uses _execute_step, retries use _reflect_and_retry)
            if attempt == 0:
                step_result = self._execute_step(step_desc, prior_results)
            else:
                logger.info("[PM:%s] Step retry %d/%d: %s",
                            self.task_id, attempt, max_retries, step_desc[:50])
                step_result = self._reflect_and_retry(
                    step_desc, step_result, verification,
                    prior_results, attempt, attempt_history,
                    diagnosis=last_diagnosis,  # P1-2: inject diagnosis
                )

            total_tokens += step_result.get("tokens", 0)

            # Verify
            verification = self._verify_step_output(step_desc, step_result)

            # Record attempt for future reflection
            attempt_history.append({
                "attempt": attempt,
                "output_preview": str(step_result.get("output", ""))[:150],
                "reason": verification.get("reason", "")[:100],
            })

            if verification["pass"]:
                logger.info("[PM:%s] Step verified OK (attempt %d): %s",
                            self.task_id, attempt + 1, step_desc[:50])
                step_result["tokens"] = total_tokens
                return step_result

            # Log failure
            logger.warning("[PM:%s] Step verify FAIL (attempt %d/%d): %s — %s",
                           self.task_id, attempt + 1, max_retries + 1,
                           step_desc[:50], verification["reason"][:80])

            # P1-2: Diagnose failure before retry (not on last attempt)
            if attempt < max_retries:
                try:
                    last_diagnosis = self._diagnose_failure(step_desc, step_result)
                    if last_diagnosis:
                        logger.info("[PM:%s] Pre-retry diagnosis: %s",
                                    self.task_id, last_diagnosis.get("error_type", "unknown"))
                except Exception as diag_err:
                    logger.debug("[PM:%s] Pre-retry diagnosis failed: %s", self.task_id, diag_err)
                    last_diagnosis = None

        # All retries exhausted — return last result as-is
        step_result["tokens"] = total_tokens
        if step_result.get("success"):
            # Downgrade: verification says fail but execution said success
            step_result["success"] = False
            step_result["error"] = f"Verification failed after {max_retries + 1} attempts: {verification['reason'][:200]}"
        return step_result

    def _synthesize(self, results: list[dict]) -> str:
        """Combine step results into final report."""
        from runtime.model_router import model_router

        parts = []
        for i, r in enumerate(results):
            status = "成功" if r.get("success") else "失败"
            output = str(r.get("output", ""))[:300]
            parts.append(f"步骤 {i+1} ({status}): {output}")

        combined = "\n".join(parts)

        try:
            resp = model_router.complete(
                prompt=(
                    f"以下是复杂任务各步骤的执行结果。请综合汇报。\n\n"
                    f"原始任务: {self.command}\n\n"
                    f"各步骤结果:\n{combined}\n\n"
                    f"请用简洁的中文汇总最终成果:"
                ),
                system="你是项目经理，正在汇报任务完成情况。简洁、准确、使用中文。",
                model=self.model,
                max_tokens=2048,
                task_type="general",
                budget="high",
            )
            return resp.content.strip()
        except Exception:
            return combined

    def _emit(self, event_name: str, payload: dict) -> None:
        """Fire-and-forget event emission (thread-safe via EventBus)."""
        try:
            from runtime.event_bus import event_bus, Event, EventType
            # Always include worker identity in events
            payload.setdefault("worker_id", self.worker_id)
            payload.setdefault("model", self.model)
            event = Event(
                type=EventType.SYSTEM_EVENT,
                source="pm_agent",
                payload={"event": event_name, **payload},
            )
            event_bus.emit(event)  # Thread-safe since v0.9.2
        except Exception:
            pass

    def _audit(self, event_type: str, summary: str, severity: str = "info") -> None:
        """V3: Fire-and-forget audit event recording."""
        try:
            from runtime.audit_events import audit_events
            audit_events.record(
                event_type=event_type,
                source=f"pm_agent/{self.worker_id}",
                summary=summary,
                severity=severity,
                task_id=self.task_id,
                project_id=self.session_context.get("project_id"),
                session_id=self.session_context.get("session_db_id", ""),
                details={"worker_id": self.worker_id, "model": self.model},
            )
        except Exception:
            pass


class PMPool:
    """Thread pool for PM Agents. Max 5 concurrent PMs with worker identity."""

    def __init__(self, max_workers: int = 5):
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="pm-worker",
        )
        self._active: dict[str, Any] = {}  # task_id → Future
        self._workers: dict[str, dict] = {}  # task_id → {worker_id, model, command, started_at}
        self._worker_counter = 0
        self._lock = __import__("threading").Lock()
        self._total_submitted = 0
        self._total_completed = 0
        self._total_failed = 0

    def _next_worker_id(self) -> str:
        """Generate sequential worker ID."""
        self._worker_counter += 1
        return f"pm-worker-{self._worker_counter:03d}"

    def submit(self, pm: PMAgent) -> str:
        """Submit a PM Agent for execution. Assigns worker_id. Returns task_id."""
        from runtime.task_tracker import task_tracker, TaskStatus

        with self._lock:
            # Assign worker identity
            worker_id = self._next_worker_id()
            pm.worker_id = worker_id

            # Clean up completed futures FIRST to get accurate active count
            done_ids = [tid for tid, f in self._active.items() if f.done()]
            for tid in done_ids:
                del self._active[tid]
                self._workers.pop(tid, None)

            active_count = sum(1 for f in self._active.values() if not f.done())
            if active_count >= self.max_workers:
                task_tracker.update_status(
                    pm.task_id, TaskStatus.QUEUED,
                    log_msg=f"排队中 [{worker_id}] (当前 {active_count}/{self.max_workers} 个 PM 在执行)"
                )

            future = self._executor.submit(pm.run)
            self._active[pm.task_id] = future
            self._workers[pm.task_id] = {
                "worker_id": worker_id,
                "model": pm.model,
                "command": pm.command[:100],
                "started_at": time.time(),
            }
            self._total_submitted += 1

        # Track completion/failure via callback — OUTSIDE lock to avoid deadlock
        # (if future is already done when callback is added, it fires synchronously)
        def _on_done(f, tid=pm.task_id):
            with self._lock:
                # Skip if already removed by cancel() to prevent double-counting
                if tid not in self._active:
                    return
                if f.exception():
                    self._total_failed += 1
                else:
                    self._total_completed += 1
                # Clean up from _active/_workers so stats are accurate
                # (prevents inflated 'queued' count in get_pool_stats)
                del self._active[tid]
                self._workers.pop(tid, None)
        future.add_done_callback(_on_done)

        logger.info("[PMPool] Submitted %s as %s (model=%s, active=%d/%d)",
                    pm.task_id, worker_id, pm.model,
                    active_count + 1, self.max_workers)
        return pm.task_id

    def get_active_count(self) -> int:
        with self._lock:
            return sum(1 for f in self._active.values() if not f.done())

    def get_worker_status(self) -> list[dict]:
        """Return status of all active PM workers for monitoring dashboard."""
        with self._lock:
            result = []
            for task_id, future in self._active.items():
                info = self._workers.get(task_id, {})
                elapsed = time.time() - info.get("started_at", time.time())
                result.append({
                    "task_id": task_id,
                    "worker_id": info.get("worker_id", "?"),
                    "model": info.get("model", "?"),
                    "command": info.get("command", "?"),
                    "running": not future.done(),
                    "elapsed_s": round(elapsed, 1),
                })
            return result

    def get_pool_stats(self) -> dict:
        """Return overall pool statistics."""
        with self._lock:
            active = sum(1 for f in self._active.values() if not f.done())
            return {
                "max_workers": self.max_workers,
                "active": active,
                "queued": max(0, len(self._active) - active),
                "total_submitted": self._total_submitted,
                "total_completed": self._total_completed,
                "total_failed": self._total_failed,
            }

    def cancel(self, task_id: str) -> bool:
        cancelled = False
        with self._lock:
            future = self._active.get(task_id)
            if future and not future.done():
                cancelled = future.cancel()
                if cancelled:
                    # Remove from active so _on_done callback won't double-count
                    # (_on_done checks _active but we've removed it, and we count here)
                    del self._active[task_id]
                    self._workers.pop(task_id, None)
                    # Don't increment _total_failed here — _on_done callback will do it
                    # since CancelledError counts as exception in the callback.
                    # But we removed it from _active above, so _on_done may still fire.
                    # To prevent double-count, we mark it and let only cancel() count.
                    self._total_failed += 1

        # Update task_tracker outside lock to avoid potential deadlock
        if cancelled:
            try:
                from runtime.task_tracker import task_tracker, TaskStatus
                task_tracker.update_status(
                    task_id, TaskStatus.FAILED,
                    log_msg="任务被手动取消"
                )
            except Exception:
                pass
        return cancelled


# Singleton
pm_pool = PMPool(max_workers=5)
