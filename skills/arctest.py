# -*- coding: utf-8 -*-
"""
ArcMind Architecture Integration Test Skill (arctest)
======================================================
用自然語言測試 ArcMind 架構，採集程序反應，驗證邏輯正確性。

Suites:
  A — 分類器準確度（classify_complexity 直接呼叫）
  B — 路由正確性（MainLoop.run 端到端）
  C — 反幻覺驗證（CEO 回覆 fact-check）
"""
from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

logger = logging.getLogger("arcmind.skill.arctest")


# ── Data Structures (plain dicts to avoid dataclass import issues) ────────────


def _result(name, suite, passed, elapsed_s, expected, actual, details=""):
    return {"name": name, "suite": suite, "passed": passed,
            "elapsed_s": elapsed_s, "expected": expected,
            "actual": actual, "details": details}


def _new_report():
    return {"total": 0, "passed": 0, "failed": 0,
            "elapsed_s": 0.0, "results": []}


# ── Test Runner ──────────────────────────────────────────────────────────────


def _test_case(name, suite, expected, fn, timeout_s=30):
    """Run a single test case with timeout."""
    start = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(fn)
            passed, actual, details = future.result(timeout=timeout_s)
        elapsed = time.monotonic() - start
        return _result(name, suite, passed, round(elapsed, 2),
                       expected, str(actual), str(details)[:500])
    except TimeoutError:
        return _result(name, suite, False, timeout_s,
                       expected, "TIMEOUT", f"Exceeded {timeout_s}s")
    except Exception as e:
        elapsed = time.monotonic() - start
        return _result(name, suite, False, round(elapsed, 2),
                       expected, "ERROR", str(e)[:500])


# ── Suite A: Classification Accuracy ─────────────────────────────────────────


_CLASSIFY_CASES = [
    ("A1_greeting_zh", "你好", "simple"),
    ("A2_greeting_en", "hello", "simple"),
    ("A3_project", "帮我搭建完整监控系统包含告警和仪表板", "project"),
    ("A4_progress", "进度?", "progress_query"),
    ("A5_complex", "帮我写一段Python代码然后测试一下", "complex"),
    ("A6_ack", "ok", "simple"),
]


def _check_classify(command: str, expected: str):
    from runtime.project_classifier import classify_complexity
    result = classify_complexity(command)
    passed = result == expected
    return (passed, result, f"classify('{command}') → '{result}', expected '{expected}'")


def _run_suite_classify() -> list[TestResult]:
    results = []
    for name, command, expected in _CLASSIFY_CASES:
        r = _test_case(
            name=name, suite="classify", expected=expected,
            fn=lambda cmd=command, exp=expected: _check_classify(cmd, exp),
            timeout_s=15,
        )
        logger.info("[arctest] %s: %s (%.1fs)", name, "PASS" if r["passed"] else "FAIL", r["elapsed_s"])
        results.append(r)
    return results


# ── Suite B: Routing Correctness ─────────────────────────────────────────────


def _check_simple_routing():
    """B1: 打招呼 → CEO 直接回覆，不走 PM"""
    from loop.main_loop import main_loop, LoopInput
    from runtime.task_tracker import task_tracker

    before_pm = {t.task_id for t in task_tracker.get_all_active()
                 if t.task_id.startswith("pm-")}

    inp = LoopInput(command="你好", source="skill", session_id=None)
    result = main_loop.run(inp)

    after_pm = {t.task_id for t in task_tracker.get_all_active()
                if t.task_id.startswith("pm-")}
    new_pm = after_pm - before_pm

    passed = (result.success
              and len(new_pm) == 0
              and result.output
              and len(str(result.output)) > 0)
    return (passed,
            f"output_len={len(str(result.output))}, new_pm={len(new_pm)}",
            str(result.output)[:200])


def _check_complex_routing():
    """B2: 複雜任務 → PM 被啟動"""
    from loop.main_loop import main_loop, LoopInput
    from runtime.task_tracker import task_tracker

    before_pm = {t.task_id for t in task_tracker.get_all_active()
                 if t.task_id.startswith("pm-")}

    inp = LoopInput(
        command="分析arcmind的代码结构并生成一份完整的架构报告",
        source="skill", session_id=None,
    )
    result = main_loop.run(inp)

    time.sleep(1)  # Give PM pool a moment to register
    after_pm = {t.task_id for t in task_tracker.get_all_active()
                if t.task_id.startswith("pm-")}
    new_pm = after_pm - before_pm

    # PM should have been spawned
    passed = len(new_pm) > 0 or "PM" in str(result.output)
    return (passed,
            f"new_pm_tasks={list(new_pm)}, output_preview={str(result.output)[:100]}",
            f"skill_used={getattr(result, 'skill_used', 'N/A')}")


def _check_progress_routing():
    """B3: 進度查詢 → 直接回覆 dashboard，不走 PM"""
    from loop.main_loop import main_loop, LoopInput
    from runtime.task_tracker import task_tracker

    before_pm = {t.task_id for t in task_tracker.get_all_active()
                 if t.task_id.startswith("pm-")}

    inp = LoopInput(command="进度?", source="skill", session_id=None)
    result = main_loop.run(inp)

    after_pm = {t.task_id for t in task_tracker.get_all_active()
                if t.task_id.startswith("pm-")}
    new_pm = after_pm - before_pm

    passed = result.success and len(new_pm) == 0
    return (passed,
            f"new_pm={len(new_pm)}, output_len={len(str(result.output))}",
            str(result.output)[:200])


def _check_cron_isolation():
    """B4: CRON 路徑直接呼叫 skill，不經 classifier/PM"""
    from runtime.task_tracker import task_tracker

    before_pm = {t.task_id for t in task_tracker.get_all_active()
                 if t.task_id.startswith("pm-")}

    # Simulate CRON: direct skill_manager.invoke (no MainLoop)
    try:
        from runtime.skill_manager import skill_manager
        skill_manager.invoke("file_ops", {"operation": "list", "path": "/tmp"})
    except Exception:
        pass  # Skill may fail, but should not spawn PM

    after_pm = {t.task_id for t in task_tracker.get_all_active()
                if t.task_id.startswith("pm-")}
    new_pm = after_pm - before_pm

    passed = len(new_pm) == 0
    return (passed, f"new_pm={len(new_pm)}", "CRON path should not spawn PM")


def _run_suite_routing() -> list[TestResult]:
    results = []

    results.append(_test_case(
        "B1_simple_route", "routing", "CEO direct, no PM",
        _check_simple_routing, timeout_s=30,
    ))
    logger.info("[arctest] B1: %s", "PASS" if results[-1]["passed"] else "FAIL")

    results.append(_test_case(
        "B2_complex_route", "routing", "PM spawned",
        _check_complex_routing, timeout_s=30,
    ))
    logger.info("[arctest] B2: %s", "PASS" if results[-1]["passed"] else "FAIL")

    results.append(_test_case(
        "B3_progress_route", "routing", "dashboard, no PM",
        _check_progress_routing, timeout_s=30,
    ))
    logger.info("[arctest] B3: %s", "PASS" if results[-1]["passed"] else "FAIL")

    results.append(_test_case(
        "B4_cron_isolation", "routing", "no PM from CRON path",
        _check_cron_isolation, timeout_s=10,
    ))
    logger.info("[arctest] B4: %s", "PASS" if results[-1]["passed"] else "FAIL")

    return results


# ── Suite C: Anti-Hallucination ──────────────────────────────────────────────


def _check_no_fabricated_price():
    """C1: 問不存在的東西，回覆不應該編造具體數字"""
    from loop.main_loop import main_loop, LoopInput

    inp = LoopInput(
        command="ArcMind当前的股价是多少",
        source="skill", session_id=None,
    )
    result = main_loop.run(inp)
    output = str(result.output)

    # Should not contain fabricated prices like $123.45 or ¥89.00
    has_price = bool(re.search(r'[\$¥￥]\s*\d+\.?\d*', output))
    passed = not has_price
    return (passed, f"contains_fabricated_price={has_price}", output[:300])


def _check_pm_count_accuracy():
    """C2: 問 PM 數量，回覆必須與實際一致"""
    from loop.main_loop import main_loop, LoopInput

    # Get real count first
    try:
        from runtime.pm_agent import pm_pool
        real_count = pm_pool.get_active_count()
    except Exception:
        real_count = 0

    inp = LoopInput(
        command="系统现在有几个PM在工作",
        source="skill", session_id=None,
    )
    result = main_loop.run(inp)
    output = str(result.output)

    # Re-check actual count AFTER CEO response (PM may have been spawned by B2)
    try:
        real_count_after = pm_pool.get_active_count()
    except Exception:
        real_count_after = real_count

    # Extract numbers: "N/5 活跃" or "N 个 PM"
    match_ratio = re.search(r'(\d+)/\d+\s*(?:活|active)', output)
    match_count = re.findall(r'(\d+)\s*(?:个|個)\s*(?:PM|pm|worker)', output)

    if match_ratio:
        claimed = int(match_ratio.group(1))
        # Accept if claimed matches either before or after count
        passed = claimed == real_count or claimed == real_count_after
        return (passed,
                f"claimed={claimed}, actual_before={real_count}, actual_after={real_count_after}",
                output[:300])
    elif match_count:
        claimed = int(match_count[0])
        passed = claimed == real_count or claimed == real_count_after
        return (passed,
                f"claimed={claimed}, actual_before={real_count}, actual_after={real_count_after}",
                output[:300])
    else:
        # No specific number claimed — acceptable (e.g. "let me check")
        return (True,
                f"no_specific_count_claimed, actual={real_count_after}",
                output[:300])


def _run_suite_hallucination() -> list[TestResult]:
    results = []

    results.append(_test_case(
        "C1_no_fake_price", "hallucination", "no fabricated price",
        _check_no_fabricated_price, timeout_s=30,
    ))
    logger.info("[arctest] C1: %s", "PASS" if results[-1]["passed"] else "FAIL")

    results.append(_test_case(
        "C2_pm_count_accuracy", "hallucination", "PM count matches reality",
        _check_pm_count_accuracy, timeout_s=30,
    ))
    logger.info("[arctest] C2: %s", "PASS" if results[-1]["passed"] else "FAIL")

    return results


# ── Report Formatter ─────────────────────────────────────────────────────────


def _format_report(report):
    lines = []
    lines.append("=" * 50)
    lines.append("ArcMind 架構測試報告")
    lines.append(f"  {report['passed']}/{report['total']} passed | "
                 f"{report['failed']} failed | {report['elapsed_s']}s")
    lines.append("=" * 50)

    for suite_name in ["classify", "routing", "hallucination"]:
        suite_results = [r for r in report["results"] if r["suite"] == suite_name]
        if not suite_results:
            continue
        suite_pass = sum(1 for r in suite_results if r["passed"])
        lines.append(f"\n--- {suite_name.upper()} ({suite_pass}/{len(suite_results)}) ---")
        for r in suite_results:
            icon = "✅" if r["passed"] else "❌"
            lines.append(f"  {icon} {r['name']} ({r['elapsed_s']}s)")
            if not r["passed"]:
                lines.append(f"     expected: {r['expected']}")
                lines.append(f"     actual:   {r['actual']}")
                if r.get("details"):
                    lines.append(f"     details:  {r['details'][:200]}")

    lines.append("\n" + "=" * 50)
    return "\n".join(lines)


# ── Main Handler ─────────────────────────────────────────────────────────────


def run(inputs: dict) -> dict:
    """
    ArcMind 架構集成測試。

    inputs:
      action: "full" | "classify" | "routing" | "hallucination"

    returns:
      success, summary, report_text, results[]
    """
    action = inputs.get("action", "full")
    logger.info("[arctest] Starting suite=%s", action)

    suites = {
        "full": [_run_suite_classify, _run_suite_routing, _run_suite_hallucination],
        "classify": [_run_suite_classify],
        "routing": [_run_suite_routing],
        "hallucination": [_run_suite_hallucination],
    }

    report = _new_report()
    start = time.monotonic()

    for suite_fn in suites.get(action, suites["full"]):
        try:
            results = suite_fn()
            report["results"].extend(results)
        except Exception as e:
            logger.error("[arctest] Suite %s crashed: %s", suite_fn.__name__, e)
            report["results"].append(_result(
                f"{suite_fn.__name__}_crash", "error",
                False, 0, "no crash", "CRASH", str(e)[:500],
            ))

    report["total"] = len(report["results"])
    report["passed"] = sum(1 for r in report["results"] if r["passed"])
    report["failed"] = report["total"] - report["passed"]
    report["elapsed_s"] = round(time.monotonic() - start, 2)

    report_text = _format_report(report)
    logger.info("[arctest] Done: %s", report_text.split("\n")[2])

    return {
        "success": report["failed"] == 0,
        "summary": f"{report['passed']}/{report['total']} passed in {report['elapsed_s']}s",
        "total": report["total"],
        "passed": report["passed"],
        "failed": report["failed"],
        "elapsed_s": report["elapsed_s"],
        "report_text": report_text,
        "results": report["results"],
    }
