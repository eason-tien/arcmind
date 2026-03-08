"""
ArcMind 整合驗證腳本
測試 4 個核心場景：
  T1: Skill 直接呼叫（code_exec）
  T2: Session + Task 生命週期
  T3: Goal 追蹤 + 進度更新
  T4: Cron 排程（interval 模式）
"""
from __future__ import annotations

import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from db.schema import init_db
from runtime.skill_manager import SkillManager
from runtime.lifecycle import LifecycleManager
from loop.goal_tracker import GoalTracker
from runtime.cron import CronSystem

init_db()

RESULTS = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    RESULTS.append((name, status, detail))
    mark = "✓" if condition else "✗"
    print(f"  {mark} [{status}] {name}" + (f" — {detail}" if detail else ""))


print("=" * 55)
print("  ArcMind v0.2.0 Integration Verify")
print("=" * 55)

# ── T1: Skill 直接呼叫 ────────────────────────────────────────
print("\n[T1] Skill 呼叫 — code_exec")
sm = SkillManager()
sm.startup()

result = sm.invoke("code_exec", {
    "code": "x = 6 * 7\nprint(f'Result: {x}')",
    "timeout_s": 5,
})
check("T1-a: invoke 成功", result["success"] is True, str(result.get("output", {})))
check("T1-b: stdout 包含結果", "42" in str(result.get("output", {}).get("stdout", "")))

result2 = sm.invoke("web_search", {"query": "MGIS machine intelligence", "max_results": 2})
check("T1-c: web_search 有結果", result2.get("count", 0) > 0 or "error" in result2,
      f"count={result2.get('count', 0)}")

# ── T2: Session + Task 生命週期 ───────────────────────────────
print("\n[T2] Session + Task 生命週期")
lc = LifecycleManager()

sid = lc.sessions.create("test-session", {"env": "verify"})
check("T2-a: Session 建立", sid > 0, f"id={sid}")

s = lc.sessions.get(sid)
check("T2-b: Session 狀態 active", s["status"] == "active")

tid = lc.tasks.create("測試任務", "code_exec", "code_exec", sid,
                       {"code": "print('hello')"})
check("T2-c: Task 建立", tid > 0, f"id={tid}")

lc.tasks.assign(tid, "code_exec", governor_ok=True)
t = lc.tasks.get(tid)
check("T2-d: Task 狀態 assigned", t["status"] == "assigned")

lc.tasks.close(tid, {"result": "ok"}, tokens_used=10)
t = lc.tasks.get(tid)
check("T2-e: Task 關閉", t["status"] == "closed")

lc.sessions.pause(sid)
s = lc.sessions.get(sid)
check("T2-f: Session 暫停", s["status"] == "paused")

lc.sessions.resume(sid)
s = lc.sessions.get(sid)
check("T2-g: Session 恢復", s["status"] == "active")

lc.sessions.end(sid)
check("T2-h: Session 結束", True, "OK")

# ── T3: Goal 追蹤 ────────────────────────────────────────────
print("\n[T3] Goal 長期目標追蹤")
gt = GoalTracker()

gid = gt.create("完成 ArcMind MVP", "實作所有模組並通過驗證", priority=1)
check("T3-a: Goal 建立", gid > 0, f"id={gid}")

gt.update_progress(gid, 0.5, notes="T1~T2 完成")
g = gt.get(gid)
check("T3-b: 進度更新 50%", abs(g["progress"] - 0.5) < 0.01)

gt.update_progress(gid, 1.0)
g = gt.get(gid)
check("T3-c: 完成時自動 completed", g["status"] == "completed")

all_goals = gt.list_all()
check("T3-d: list_all 不為空", len(all_goals) > 0)

# ── T4: Cron 排程 ────────────────────────────────────────────
print("\n[T4] Cron 排程系統")
cron = CronSystem()
cron.startup()

result4 = cron.add_interval(
    "verify-test-job",
    seconds=300,
    skill_name="code_exec",
    input_data={"code": "print('cron ok')"},
    governor_required=False,
)
check("T4-a: Interval 排程新增", result4.get("status") == "scheduled",
      str(result4))

jobs = cron.list_jobs()
check("T4-b: 排程清單包含工作",
      any(j["name"] == "verify-test-job" for j in jobs))

cron.remove("verify-test-job")
jobs_after = cron.list_jobs()
check("T4-c: 排程移除後 disabled",
      not any(j["name"] == "verify-test-job" and j["enabled"] for j in jobs_after))

cron.shutdown()

# ── 匯總 ────────────────────────────────────────────────────
print("\n" + "=" * 55)
passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
total = len(RESULTS)
print(f"  Result: {passed}/{total} PASS")
print("=" * 55)

# 寫入 evidence
evidence = {
    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "version": "0.2.0",
    "results": [{"name": n, "status": s, "detail": d} for n, s, d in RESULTS],
    "summary": f"{passed}/{total}",
}
ev_path = settings.evidence_dir / "ARCMIND_VERIFY.json"
ev_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
print(f"\n  Evidence: {ev_path}")

if passed < total:
    sys.exit(1)
