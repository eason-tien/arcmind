# -*- coding: utf-8 -*-
"""
ArcMind — Iteration Engine
============================
每週自我迭代系統：
1. 收集系統情報（錯誤、任務統計、Agent 使用、資源）
2. 多 Agent 圓桌會議（各自角度評估）
3. 生成迭代計劃（目標、任務、優先級）
4. 排程執行（自動建立 CRON 任務）
5. 報告通知（Telegram）
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.iteration_engine")

_ARCMIND_DIR = Path(__file__).resolve().parent.parent


# ── 1. System Intelligence Collection ─────────────────────────────────────────

def collect_system_intel() -> dict:
    """
    收集過去一週的系統狀態情報。
    Returns a dict with all collected intel for agent review.
    """
    intel: dict[str, Any] = {}

    # 1a. Error log analysis (last 7 days)
    intel["error_summary"] = _collect_error_logs()

    # 1b. Task statistics
    intel["task_stats"] = _collect_task_stats()

    # 1c. CRON job health
    intel["cron_health"] = _collect_cron_health()

    # 1d. Agent usage
    intel["agent_usage"] = _collect_agent_usage()

    # 1e. Skill invocation stats
    intel["skill_stats"] = _collect_skill_stats()

    # 1f. Incident history (from watchdog)
    intel["incidents"] = _collect_incidents()

    # 1g. System resources
    intel["resources"] = _collect_resources()

    # 1h. Current config overview
    intel["config"] = _collect_config_overview()

    # 1i. User feedback from Telegram conversations
    intel["user_feedback"] = collect_user_feedback()

    # 1j. Iteration effect (week-over-week comparison)
    intel["iteration_effect"] = measure_iteration_effect()

    logger.info("[IterationEngine] Collected system intel: %d categories",
                len(intel))
    return intel


def _collect_error_logs() -> dict:
    """Parse recent error/warning lines from arcmind.log."""
    log_file = _ARCMIND_DIR / "logs" / "arcmind.log"
    errors = []
    warnings = []
    try:
        if log_file.exists():
            lines = log_file.read_text(encoding="utf-8", errors="replace").split("\n")
            # Last 7 days cutoff
            cutoff = datetime.now() - timedelta(days=7)
            for line in lines[-5000:]:  # scan last 5000 lines
                if "[ERROR]" in line:
                    errors.append(line.strip()[:200])
                elif "[WARNING]" in line:
                    warnings.append(line.strip()[:200])
    except Exception as e:
        logger.warning("[Intel] Error log parse failed: %s", e)

    # Deduplicate and count
    error_counts: dict[str, int] = {}
    for err in errors:
        # Extract the core error message (after the module name)
        key = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ \[ERROR\] \S+ — ", "", err)
        key = key[:100]
        error_counts[key] = error_counts.get(key, 0) + 1

    return {
        "total_errors": len(errors),
        "total_warnings": len(warnings),
        "unique_errors": len(error_counts),
        "top_errors": sorted(error_counts.items(), key=lambda x: -x[1])[:10],
    }


def _collect_task_stats() -> dict:
    """Query task success/failure rates from DB."""
    try:
        from db.schema import Task_, get_db, get_db_session
        with get_db_session() as db:
            cutoff = datetime.utcnow() - timedelta(days=7)
            total = db.query(Task_).filter(Task_.created_at >= cutoff).count()
            closed = db.query(Task_).filter(
                Task_.created_at >= cutoff, Task_.status == "closed"
            ).count()
            failed = db.query(Task_).filter(
                Task_.created_at >= cutoff, Task_.status == "failed"
            ).count()
            return {
                "total_tasks_7d": total,
                "closed": closed,
                "failed": failed,
                "success_rate": round(closed / max(total, 1) * 100, 1),
            }
    except Exception as e:
        return {"error": str(e)}


def _collect_cron_health() -> list:
    """List all CRON jobs and their health."""
    try:
        from runtime.cron import cron_system
        return cron_system.list_jobs()
    except Exception as e:
        return [{"error": str(e)}]


def _collect_agent_usage() -> dict:
    """Collect agent configuration and IAMP communication stats."""
    try:
        from runtime.agent_registry import agent_registry
        agents = agent_registry.list_agents()  # Returns list of dicts

        # IAMP message bus stats
        iamp_stats = {}
        try:
            from runtime.iamp import message_bus
            iamp_stats = message_bus.stats()
        except Exception:
            pass

        return {
            "count": len(agents),
            "agents": [
                {"id": a["id"], "name": a["name"], "model": a.get("default_model", ""),
                 "capabilities": a.get("capabilities", []), "enabled": a.get("enabled", True)}
                for a in agents
            ],
            "iamp": iamp_stats,
        }
    except Exception as e:
        return {"error": str(e)}


def _collect_skill_stats() -> list:
    """Collect skill invoke/error counts."""
    try:
        from db.schema import SkillRegistry_, get_db, get_db_session
        with get_db_session() as db:
            skills = db.query(SkillRegistry_).all()
            return [
                {"name": s.name, "invokes": s.invoke_count,
                 "errors": s.error_count, "enabled": s.enabled}
                for s in skills
            ]
    except Exception as e:
        return [{"error": str(e)}]


def _collect_incidents() -> list:
    """Read watchdog incident history."""
    try:
        incident_log = _ARCMIND_DIR / "evidence" / "ARCMIND_VERIFY.json"
        if incident_log.exists():
            data = json.loads(incident_log.read_text(encoding="utf-8"))
            incidents = data.get("incidents", [])
            return incidents[-10:]  # last 10
        return []
    except Exception as e:
        return [{"error": str(e)}]


def _collect_resources() -> dict:
    """Basic system resource check."""
    try:
        # Disk usage
        result = subprocess.run(
            ["df", "-h", str(_ARCMIND_DIR)],
            capture_output=True, text=True, timeout=5,
        )
        disk = result.stdout.strip().split("\n")[-1] if result.stdout else "unknown"

        # DB size
        db_path = _ARCMIND_DIR / "data" / "arcmind.db"
        db_size = db_path.stat().st_size if db_path.exists() else 0

        # Log size
        log_dir = _ARCMIND_DIR / "logs"
        log_size = sum(f.stat().st_size for f in log_dir.glob("*") if f.is_file()) if log_dir.exists() else 0

        return {
            "disk_usage": disk,
            "db_size_mb": round(db_size / 1024 / 1024, 2),
            "log_size_mb": round(log_size / 1024 / 1024, 2),
        }
    except Exception as e:
        return {"error": str(e)}


def _collect_config_overview() -> dict:
    """Summarize current configuration."""
    try:
        from config.settings import settings
        return {
            "version": "0.3.0",
            "providers": settings.available_providers(),
            "cron_timezone": settings.cron_timezone,
            "skills_dir": str(settings.skills_dir),
        }
    except Exception as e:
        return {"error": str(e)}


# ── 2. Agent Roundtable Meeting ──────────────────────────────────────────────

def run_agent_roundtable(intel: dict) -> dict:
    """
    召開多 Agent 圓桌會議。
    每個 Agent 從自己的專業角度評估系統情報，提出改進建議。
    MAIN Agent 最後綜合所有建議。
    """
    from runtime.tool_loop import agentic_complete
    from runtime.agent_registry import agent_registry

    intel_text = json.dumps(intel, ensure_ascii=False, default=str, indent=2)
    if len(intel_text) > 8000:
        intel_text = intel_text[:8000] + "\n... (truncated)"

    perspectives: dict[str, str] = {}
    agents = agent_registry.list_agents()

    # Each sub-agent reviews from its perspective
    for agent in agents:
        if agent.id == "main":
            continue  # MAIN summarizes at the end

        prompt_map = {
            "code": (
                f"你是 ArcMind 的 Code Agent。以下是過去一週的系統運行報告：\n\n{intel_text}\n\n"
                "請從代碼品質和可靠性的角度分析：\n"
                "1. 最常見的錯誤模式及根因\n"
                "2. 代碼改進建議（bug修復、重構、新功能）\n"
                "3. 本週最緊急需要修的問題\n"
                "用繁中回答，簡潔扼要，每點不超過2行。"
            ),
            "analysis": (
                f"你是 ArcMind 的 Analysis Agent。以下是過去一週的系統運行報告：\n\n{intel_text}\n\n"
                "請從數據和效能的角度分析：\n"
                "1. 任務成功率趨勢及瓶頸\n"
                "2. 資源使用效率\n"
                "3. 需要優化的績效指標\n"
                "用繁中回答，簡潔扼要，每點不超過2行。"
            ),
            "search": (
                f"你是 ArcMind 的 Search Agent。以下是過去一週的系統運行報告：\n\n{intel_text}\n\n"
                "請從外部資訊和工具的角度建議：\n"
                "1. 可以引入的新工具或庫來改善系統\n"
                "2. 業界最佳實踐參考\n"
                "3. 安全性和穩定性建議\n"
                "用繁中回答，簡潔扼要，每點不超過2行。"
            ),
        }

        prompt = prompt_map.get(agent.id)
        if not prompt:
            continue

        try:
            logger.info("[Roundtable] Consulting agent: %s (%s)", agent.name, agent.model)
            result = agentic_complete(
                prompt=prompt,
                model=agent.model,
                task_type="analysis",
                budget="medium",
                max_tokens=1500,
                tools_enabled=False,  # No tools during review
            )
            perspectives[agent.id] = result.get("content", "（無回應）")
            logger.info("[Roundtable] %s responded (%d chars)",
                        agent.name, len(perspectives[agent.id]))
        except Exception as e:
            perspectives[agent.id] = f"（Agent 錯誤: {e}）"
            logger.error("[Roundtable] Agent %s failed: %s", agent.id, e)

    # MAIN agent synthesizes all perspectives
    main_agent = agent_registry.get_default()
    synthesis_prompt = (
        "你是 ArcMind 的主調度 Agent (MAIN)。今天是每週自我迭代會議日。\n"
        f"以下是各 Agent 對過去一週系統運行的評估：\n\n"
    )
    for agent_id, review in perspectives.items():
        synthesis_prompt += f"### {agent_id.upper()} Agent 評估\n{review}\n\n"

    synthesis_prompt += (
        f"### 系統關鍵指標\n"
        f"- 錯誤數: {intel.get('error_summary', {}).get('total_errors', 'N/A')}\n"
        f"- 任務成功率: {intel.get('task_stats', {}).get('success_rate', 'N/A')}%\n"
        f"- 事故數: {len(intel.get('incidents', []))}\n\n"
        "請綜合所有評估，產出：\n"
        "1. **本週系統健康度評分** (1-10)\n"
        "2. **Top 3 最優先改進目標**（每個包含：目標、原因、具體任務、預期效果）\n"
        "3. **風險提醒**（任何需要使用者確認的breaking change）\n"
        "用繁中回答，格式清晰。"
    )

    try:
        synthesis = agentic_complete(
            prompt=synthesis_prompt,
            model=main_agent.model if main_agent else None,
            task_type="analysis",
            budget="high",
            max_tokens=3000,
            tools_enabled=False,
        )
        perspectives["main_synthesis"] = synthesis.get("content", "")
    except Exception as e:
        perspectives["main_synthesis"] = f"（綜合失敗: {e}）"
        logger.error("[Roundtable] MAIN synthesis failed: %s", e)

    logger.info("[Roundtable] Meeting complete. %d perspectives collected.",
                len(perspectives))
    return perspectives


# ── 3. Iteration Plan Production ─────────────────────────────────────────────

def produce_iteration_plan(roundtable: dict, intel: dict) -> list[dict]:
    """
    根據圓桌會議結果，生成具體可執行的迭代計劃。
    每個計劃任務包含：goal, task, priority, type, estimated_effort
    """
    from runtime.tool_loop import agentic_complete

    synthesis = roundtable.get("main_synthesis", "")

    prompt = (
        f"根據以下的週度系統評估報告，生成具體的迭代任務清單。\n\n"
        f"### 評估報告\n{synthesis}\n\n"
        f"### 系統現有技能\n"
        f"{json.dumps(intel.get('skill_stats', []), ensure_ascii=False)}\n\n"
        "請用 **嚴格 JSON 格式** 輸出最多 5 個任務，每個任務格式：\n"
        "```json\n"
        "[\n"
        '  {"goal": "目標", "task": "具體任務描述", '
        '"priority": "critical|important|nice_to_have", '
        '"type": "code_fix|config_update|new_feature|optimization|monitoring", '
        '"estimated_effort": "small|medium|large", '
        '"requires_user_approval": true/false, '
        '"description": "給使用者看的說明"}\n'
        "]\n"
        "```\n"
        "只輸出 JSON 陣列，不要其他內容。"
    )

    try:
        result = agentic_complete(
            prompt=prompt,
            task_type="analysis",
            budget="medium",
            max_tokens=2000,
            tools_enabled=False,
        )
        content = result.get("content", "[]")

        # Extract JSON from response
        match = re.search(r"\[[\s\S]*\]", content)
        if match:
            plan = json.loads(match.group())
            # Validate structure
            validated: list[dict] = []
            for item in plan[:5]:  # max 5 tasks
                validated.append({
                    "goal": item.get("goal", ""),
                    "task": item.get("task", ""),
                    "priority": item.get("priority", "nice_to_have"),
                    "type": item.get("type", "optimization"),
                    "estimated_effort": item.get("estimated_effort", "small"),
                    "requires_user_approval": item.get("requires_user_approval", True),
                    "description": item.get("description", ""),
                    "status": "planned",
                })
            logger.info("[IterationPlan] Generated %d tasks", len(validated))
            return validated
        else:
            logger.warning("[IterationPlan] Could not parse JSON from LLM output")
            return []
    except Exception as e:
        logger.error("[IterationPlan] Plan generation failed: %s", e)
        return []


# ── 4. Save Iteration Record ─────────────────────────────────────────────────

def save_iteration_record(
    week_id: str,
    report: dict,
    plan: list[dict],
    phase: str = "planned",
) -> int:
    """Save the iteration meeting results to DB."""
    try:
        from db.schema import IterationRecord_, get_db, get_db_session
        with get_db_session() as db:
            rec = IterationRecord_(
                week_id=week_id,
                phase=phase,
                report=json.dumps(report, ensure_ascii=False, default=str),
                plan=json.dumps(plan, ensure_ascii=False, default=str),
            )
            db.add(rec)
            db.commit()
            db.refresh(rec)
            logger.info("[IterationRecord] Saved: week=%s id=%d phase=%s",
                        week_id, rec.id, phase)
            return rec.id
    except Exception as e:
        logger.error("[IterationRecord] Save failed: %s", e)
        return -1


# ── 5. Send Report to User ───────────────────────────────────────────────────

def send_iteration_report(
    week_id: str,
    intel: dict,
    roundtable: dict,
    plan: list[dict],
) -> None:
    """Send a concise iteration report via Telegram."""
    from config.settings import settings

    # Build report text
    error_count = intel.get("error_summary", {}).get("total_errors", "?")
    task_stats = intel.get("task_stats", {})
    success_rate = task_stats.get("success_rate", "?")

    lines = [
        f"📊 <b>ArcMind 週度自我迭代報告 ({week_id})</b>",
        "",
        f"🔍 <b>系統健康</b>",
        f"  • 錯誤數: {error_count}",
        f"  • 任務成功率: {success_rate}%",
        f"  • 事故數: {len(intel.get('incidents', []))}",
        "",
    ]

    # Main synthesis excerpt (first 500 chars)
    synthesis = roundtable.get("main_synthesis", "")
    if synthesis:
        lines.append("📋 <b>MAIN Agent 綜合評估</b>")
        # Remove markdown formatting for Telegram
        clean = synthesis.replace("**", "").replace("###", "").replace("##", "")
        lines.append(clean[:500])
        lines.append("")

    # Plan summary
    if plan:
        lines.append(f"🎯 <b>本週迭代計劃 ({len(plan)} 項)</b>")
        for i, task in enumerate(plan, 1):
            priority_icon = {"critical": "🔴", "important": "🟡", "nice_to_have": "🟢"}.get(
                task.get("priority", ""), "⚪"
            )
            approval = "⚠️需確認" if task.get("requires_user_approval") else "✅自動"
            lines.append(f"  {i}. {priority_icon} {task.get('goal', '')} [{approval}]")
        lines.append("")
        lines.append("回覆「確認」開始執行，或指定修改。")
    else:
        lines.append("✅ 系統運行良好，本週無需迭代。")

    message = "\n".join(lines)

    # Send via Telegram
    try:
        import urllib.request
        import urllib.parse

        token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        if not token or not chat_id:
            logger.warning("[IterationReport] No Telegram credentials")
            return

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        # Telegram has 4096 char limit
        if len(message) > 4000:
            message = message[:4000] + "\n...(truncated)"

        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        resp = urllib.request.urlopen(req, timeout=15)
        logger.info("[IterationReport] Telegram report sent (week=%s)", week_id)
    except Exception as e:
        logger.error("[IterationReport] Telegram send failed: %s", e)

        # Fallback: save report to file
        report_file = _ARCMIND_DIR / f"iteration_report_{week_id}.md"
        report_file.write_text(message.replace("<b>", "**").replace("</b>", "**"),
                               encoding="utf-8")
        logger.info("[IterationReport] Saved to file: %s", report_file)


# ── 6. Full Meeting Flow ─────────────────────────────────────────────────────

def run_weekly_meeting() -> dict:
    """Full weekly meeting flow: collect → roundtable → plan → save → report."""
    now = datetime.now()
    week_id = now.strftime("%Y-W%W")

    logger.info("=" * 60)
    logger.info("[IterationEngine] Weekly Agent Meeting Starting")
    logger.info("[IterationEngine] Week: %s", week_id)
    logger.info("=" * 60)

    # Step 1: Collect intel (includes user feedback + effect tracking)
    logger.info("[Meeting] Step 1/6: Collecting system intelligence...")
    intel = collect_system_intel()

    # Step 2: Agent roundtable
    logger.info("[Meeting] Step 2/6: Running agent roundtable...")
    roundtable = run_agent_roundtable(intel)

    # Step 3: Produce plan
    logger.info("[Meeting] Step 3/6: Producing iteration plan...")
    plan = produce_iteration_plan(roundtable, intel)

    # Step 4: Save to DB
    logger.info("[Meeting] Step 4/6: Saving iteration record...")
    record_id = save_iteration_record(
        week_id=week_id,
        report={"intel": intel, "roundtable": roundtable},
        plan=plan,
        phase="planned",
    )

    # Step 5: Send report
    logger.info("[Meeting] Step 5/6: Sending report to user...")
    send_iteration_report(week_id, intel, roundtable, plan)

    # Step 6: Shadow system status check
    logger.info("[Meeting] Step 6/6: Checking shadow system...")
    try:
        from runtime.shadow_runner import shadow_runner
        shadow_status = shadow_runner.status()
        logger.info("[Meeting] Shadow system: %s", shadow_status.get('active', False))
    except Exception as e:
        logger.warning("[Meeting] Shadow status check failed: %s", e)

    logger.info("=" * 60)
    logger.info("[IterationEngine] Weekly Meeting Complete (record=%d)", record_id)
    logger.info("=" * 60)

    return {
        "week_id": week_id,
        "record_id": record_id,
        "plan_count": len(plan),
        "user_sentiment": intel.get('user_feedback', {}).get('summary', {}).get('sentiment', 'unknown'),
        "status": "completed",
    }


# ── 7. Execute Iteration Tasks (via Shadow) ──────────────────────────────────

def execute_daily_check() -> dict:
    """
    每日執行檢查：查看是否有待執行的迭代任務。
    - 只自動執行不需要使用者批准的任務
    - 所有代碼變更先在影子區測試，通過後才推到主系統
    """
    try:
        from db.schema import IterationRecord_, get_db, get_db_session
        with get_db_session() as db:

            # Find the latest planned/executing iteration
            rec = db.query(IterationRecord_).filter(
                IterationRecord_.phase.in_(["planned", "executing"])
            ).order_by(IterationRecord_.created_at.desc()).first()

            if not rec:
                logger.info("[DailyCheck] No pending iterations.")
                return {"status": "no_pending"}

            plan = json.loads(rec.plan or "[]")
            executed = []
            failed = []

            for task in plan:
                if task.get("status") != "planned":
                    continue
                if task.get("requires_user_approval", True):
                    continue

                goal = task.get("goal", "unknown")
                logger.info("[DailyCheck] Executing: %s", goal)

                try:
                    result = _execute_single_task(task)
                    if result.get("success"):
                        task["status"] = "completed"
                        task["executed_at"] = datetime.now().isoformat()
                        task["result"] = result.get("summary", "")
                        executed.append(goal)
                    else:
                        task["status"] = "failed"
                        task["error"] = result.get("error", "unknown")
                        failed.append(goal)
                except Exception as e:
                    task["status"] = "failed"
                    task["error"] = str(e)
                    failed.append(goal)
                    logger.error("[DailyCheck] Task failed: %s — %s", goal, e)

            if executed or failed:
                rec.plan = json.dumps(plan, ensure_ascii=False, default=str)
                rec.phase = "executing"

                all_done = all(t.get("status") != "planned" for t in plan)
                if all_done:
                    rec.phase = "completed"
                    rec.completed_at = datetime.utcnow()

                db.commit()
                logger.info("[DailyCheck] Done: %d executed, %d failed",
                            len(executed), len(failed))

            return {"status": "checked", "executed": executed, "failed": failed}
    except Exception as e:
        logger.error("[DailyCheck] Error: %s", e)
        return {"status": "error", "error": str(e)}


def _execute_single_task(task: dict) -> dict:
    """
    執行單一迭代任務。
    使用 Code Agent 生成代碼 → 影子測試 → 推到主系統。
    """
    from runtime.tool_loop import agentic_complete
    from runtime.shadow_runner import shadow_runner

    task_type = task.get("type", "")
    goal = task.get("goal", "")
    description = task.get("task", "")

    # ── Config updates: apply directly (low risk) ──
    if task_type == "config_update":
        prompt = (
            f"你是 ArcMind 的 Code Agent。請執行以下配置更新任務：\n"
            f"目標: {goal}\n"
            f"描述: {description}\n\n"
            "使用工具完成任務。只修改配置文件（.json, .yaml, .env 等），不要修改 Python 代碼。"
        )
        result = agentic_complete(
            prompt=prompt,
            task_type="code",
            budget="medium",
            max_tokens=2000,
            tools_enabled=True,
        )
        return {"success": True, "summary": result.get("content", "")[:200]}

    # ── Code changes: go through shadow ──
    if task_type in ("code_fix", "new_feature", "optimization"):
        # Step 1: Ask Code Agent to produce the changes as a patch
        prompt = (
            f"你是 ArcMind 的 Code Agent。請為以下任務生成代碼變更：\n"
            f"目標: {goal}\n"
            f"描述: {description}\n\n"
            f"ArcMind 系統目錄: {Path(__file__).resolve().parent.parent}/\n\n"
            "請用 **嚴格 JSON 格式** 輸出變更清單：\n"
            "```json\n"
            '[{"action": "create|modify", "path": "relative/path", "content": "完整文件內容"}]\n'
            "```\n"
            "path 使用相對路徑（如 skills/new_skill.py）。只輸出 JSON。"
        )

        result = agentic_complete(
            prompt=prompt,
            task_type="code",
            budget="high",
            max_tokens=4000,
            tools_enabled=False,
        )

        content = result.get("content", "")
        match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", content)
        if not match:
            return {"success": False, "error": "Code Agent 未產生有效的 JSON 變更"}

        try:
            changes = json.loads(match.group())
        except json.JSONDecodeError as e:
            return {"success": False, "error": f"JSON 解析失敗: {e}"}

        # Step 2: Setup shadow
        setup = shadow_runner.setup()
        if setup.get("status") != "ready":
            return {"success": False, "error": f"影子系統建立失敗: {setup}"}

        # Step 3: Apply changes in shadow
        apply_result = shadow_runner.apply_changes(changes)
        if apply_result.get("errors"):
            shadow_runner.rollback()
            shadow_runner.cleanup()
            return {"success": False, "error": f"變更應用失敗: {apply_result['errors']}"}

        # Step 4: Test in shadow
        test_result = shadow_runner.test()
        if not test_result.get("all_passed"):
            shadow_runner.rollback()
            shadow_runner.cleanup()
            return {
                "success": False,
                "error": f"影子測試失敗: {test_result.get('tests', [])}",
            }

        # Step 5: Promote to main
        promote_result = shadow_runner.promote()
        shadow_runner.cleanup()

        if promote_result.get("status") == "promoted":
            return {
                "success": True,
                "summary": f"已通過影子測試並推到主系統。變更: {apply_result['applied']}",
            }
        else:
            return {"success": False, "error": f"推送失敗: {promote_result}"}

    # ── Monitoring tasks: just run analysis ──
    if task_type == "monitoring":
        return {"success": True, "summary": "監控任務已記錄，將在下次會議中追蹤"}

    return {"success": False, "error": f"不支援的任務類型: {task_type}"}


# ── 8. Effect Tracking ───────────────────────────────────────────────────────

def measure_iteration_effect() -> dict:
    """
    比較本週與上週的系統指標，追蹤迭代效果。
    """
    try:
        from db.schema import IterationRecord_, get_db, get_db_session
        with get_db_session() as db:

            records = db.query(IterationRecord_).order_by(
                IterationRecord_.created_at.desc()
            ).limit(2).all()

            if len(records) < 2:
                return {"status": "insufficient_data", "message": "需要至少兩週數據才能比較"}

            current = records[0]
            previous = records[1]

            current_report = json.loads(current.report or "{}")
            previous_report = json.loads(previous.report or "{}")

            # Extract metrics for comparison
            current_intel = current_report.get("intel", {})
            previous_intel = previous_report.get("intel", {})

            current_errors = current_intel.get("error_summary", {}).get("total_errors", 0)
            previous_errors = previous_intel.get("error_summary", {}).get("total_errors", 0)

            current_success = current_intel.get("task_stats", {}).get("success_rate", 0)
            previous_success = previous_intel.get("task_stats", {}).get("success_rate", 0)

            # Plan completion stats
            current_plan = json.loads(current.plan or "[]")
            completed = sum(1 for t in current_plan if t.get("status") == "completed")
            total = len(current_plan)

            delta = {
                "error_delta": current_errors - previous_errors,
                "error_direction": "📉 改善" if current_errors < previous_errors else "📈 增加" if current_errors > previous_errors else "➡️ 持平",
                "success_rate_delta": round(current_success - previous_success, 1),
                "success_direction": "📈 改善" if current_success > previous_success else "📉 下降" if current_success < previous_success else "➡️ 持平",
                "plan_completion": f"{completed}/{total}",
                "current_week": current.week_id,
                "previous_week": previous.week_id,
            }

            # Save effect data back to current record
            current.results = json.dumps(delta, ensure_ascii=False)
            db.commit()

            logger.info("[EffectTracking] Week %s vs %s: errors %s, success %s",
                        current.week_id, previous.week_id,
                        delta["error_direction"], delta["success_direction"])
            return delta
    except Exception as e:
        logger.error("[EffectTracking] Error: %s", e)
        return {"status": "error", "error": str(e)}


# ── 9. User Feedback Integration ─────────────────────────────────────────────

def collect_user_feedback() -> dict:
    """
    從 Telegram 對話歷史中收集使用者回饋。
    分析不滿、需求、功能請求。
    """
    feedback = {
        "complaints": [],
        "requests": [],
        "positive": [],
    }

    # Scan session logs for user messages
    try:
        from db.schema import Session_, get_db, get_db_session
        with get_db_session() as db:

            cutoff = datetime.utcnow() - timedelta(days=7)
            all_sessions = db.query(Session_).filter(
                Session_.created_at >= cutoff,
            ).all()

            # Filter sessions by channel from context JSON
            sessions = []
            for s in all_sessions:
                try:
                    ctx = json.loads(s.context or "{}")
                    if ctx.get("channel") == "telegram":
                        sessions.append(s)
                except:
                    pass

            for session in sessions:
                ctx = json.loads(session.context or "{}")
                history = ctx.get("history", [])
                for msg in history:
                    if msg.get("role") != "user":
                        continue
                    text = msg.get("content", "")
                    if not isinstance(text, str) or len(text) < 5:
                        continue

                    # Simple sentiment signals (not keyword-based, but pattern-based)
                    lower = text.lower()
                    if any(p in text for p in ["不會", "不行", "又", "怎麼還", "死卡", "被限制", "不應該"]):
                        feedback["complaints"].append(text[:100])
                    elif any(p in text for p in ["要做", "希望", "可以加", "需要", "幫我", "設定"]):
                        feedback["requests"].append(text[:100])
                    elif any(p in text for p in ["好", "讚", "不錯", "LGTM", "OK"]):
                        feedback["positive"].append(text[:100])
    except Exception as e:
        logger.warning("[UserFeedback] Could not parse sessions: %s", e)

    # Also check for iteration-specific feedback
    try:
        log_file = _ARCMIND_DIR / "logs" / "arcmind.log"
        if log_file.exists():
            lines = log_file.read_text(encoding="utf-8", errors="replace").split("\n")
            for line in lines[-2000:]:
                if "user_feedback" in line.lower() or "iteration_feedback" in line.lower():
                    feedback["requests"].append(line.strip()[:100])
    except Exception:
        pass

    feedback["summary"] = {
        "complaints_count": len(feedback["complaints"]),
        "requests_count": len(feedback["requests"]),
        "positive_count": len(feedback["positive"]),
        "sentiment": (
            "negative" if len(feedback["complaints"]) > len(feedback["positive"])
            else "positive" if len(feedback["positive"]) > len(feedback["complaints"])
            else "neutral"
        ),
    }

    logger.info("[UserFeedback] Collected: %d complaints, %d requests, %d positive",
                len(feedback["complaints"]), len(feedback["requests"]),
                len(feedback["positive"]))
    return feedback

