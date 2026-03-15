# -*- coding: utf-8 -*-
"""
ArcMind — Core Module Unit Tests
=================================
Tests for critical runtime components:
- TaskResilienceEngine (diagnosis, CB, retry)
- Governor (risk scoring, decisions)
- CircuitBreaker (task freeze, global mode)
- CronSystem (basic API)
"""
import os
import sys
import time
import unittest

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestTaskResilienceEngine(unittest.TestCase):
    """Test runtime/task_resilience.py core logic."""

    def setUp(self):
        from runtime.task_resilience import TaskResilienceEngine
        self.engine = TaskResilienceEngine()

    def test_diagnose_timeout(self):
        from runtime.task_resilience import FailureType
        d = self.engine._diagnose(TimeoutError("test"), "test_skill", 30.0)
        self.assertEqual(d.failure_type, FailureType.TIMEOUT)
        self.assertIn("30", d.message)

    def test_diagnose_ssl_error(self):
        from runtime.task_resilience import FailureType
        d = self.engine._diagnose(Exception("SSL: CERTIFICATE_VERIFY_FAILED"), "s", 1)
        self.assertEqual(d.failure_type, FailureType.SSL_ERROR)
        self.assertTrue(d.repairable)

    def test_diagnose_import_error(self):
        from runtime.task_resilience import FailureType
        d = self.engine._diagnose(
            ModuleNotFoundError("No module named 'foobar'"), "s", 0.1
        )
        self.assertEqual(d.failure_type, FailureType.IMPORT_ERROR)
        self.assertTrue(d.repairable)
        self.assertIn("foobar", d.repair_action or "")

    def test_diagnose_network_error(self):
        from runtime.task_resilience import FailureType
        d = self.engine._diagnose(Exception("Connection refused"), "s", 0.5)
        self.assertEqual(d.failure_type, FailureType.NETWORK_ERROR)

    def test_diagnose_db_error(self):
        from runtime.task_resilience import FailureType
        d = self.engine._diagnose(Exception("MySQL OperationalError"), "s", 0.5)
        self.assertEqual(d.failure_type, FailureType.DB_ERROR)
        self.assertTrue(d.repairable)

    def test_diagnose_oom(self):
        from runtime.task_resilience import FailureType
        d = self.engine._diagnose(MemoryError(), "s", 0.1)
        self.assertEqual(d.failure_type, FailureType.OOM)
        self.assertFalse(d.repairable)

    def test_diagnose_unknown(self):
        from runtime.task_resilience import FailureType
        d = self.engine._diagnose(Exception("something weird"), "s", 0.1)
        self.assertEqual(d.failure_type, FailureType.UNKNOWN)

    def test_circuit_breaker_opens(self):
        from runtime.task_resilience import SkillHealthState
        h = SkillHealthState(name="test")
        for _ in range(4):
            h.record_failure("error")
        self.assertEqual(h.consecutive_failures, 4)
        self.engine._open_circuit(h)
        self.assertTrue(h.circuit_open)

    def test_circuit_breaker_reset(self):
        from runtime.task_resilience import SkillHealthState
        h = SkillHealthState(name="test_reset")
        self.engine._skill_health["test_reset"] = h
        h.circuit_open = True
        ok = self.engine.reset_circuit("test_reset")
        self.assertTrue(ok)
        self.assertFalse(h.circuit_open)

    def test_get_status(self):
        status = self.engine.get_status()
        self.assertIn("total_skills_tracked", status)
        self.assertIn("open_circuits", status)
        self.assertIn("skills", status)

    def test_skill_health_record_success(self):
        from runtime.task_resilience import SkillHealthState
        h = SkillHealthState(name="ok_skill")
        h.record_success(1.5)
        self.assertEqual(h.total_calls, 1)
        self.assertEqual(h.fail_count, 0)
        self.assertEqual(h.consecutive_failures, 0)


class TestGovernor(unittest.TestCase):
    """Test governor/governor.py risk scoring and decisions."""

    def setUp(self):
        from governor.governor import Governor
        self.gov = Governor(mode="soft_block", warn_threshold=40, block_threshold=70)

    def test_low_risk_approved(self):
        d = self.gov.evaluate("list files", {"skill": "web_search"})
        self.assertEqual(d.decision, "APPROVED")
        self.assertLess(d.risk_score, 40)

    def test_high_risk_blocked(self):
        d = self.gov.evaluate("rm -rf /", {"skill": "code_exec"})
        self.assertEqual(d.decision, "BLOCKED")
        self.assertGreaterEqual(d.risk_score, 70)

    def test_medium_risk_warned(self):
        d = self.gov.evaluate("write config", {"skill": "file_ops", "operation": "write"})
        self.assertIn(d.decision, ("WARNED", "BLOCKED"))

    def test_off_mode_always_approved(self):
        from governor.governor import Governor
        gov_off = Governor(mode="off")
        d = gov_off.evaluate("rm -rf /", {"skill": "code_exec"})
        self.assertEqual(d.decision, "APPROVED")

    def test_hallucination_detection(self):
        d = self.gov.evaluate("我已经买入", {"skill": "web_search", "command": "我已经买入台积电"})
        self.assertGreaterEqual(d.risk_score, 30)


class TestCircuitBreaker(unittest.TestCase):
    """Test governor/circuit_breaker.py."""

    def setUp(self):
        from governor.circuit_breaker import CircuitBreaker
        self.cb = CircuitBreaker()

    def test_not_frozen_initially(self):
        self.assertFalse(self.cb.is_frozen("task-1"))

    def test_freeze_after_threshold(self):
        for _ in range(3):
            self.cb.record_reject("task-freeze-test")
        self.assertTrue(self.cb.is_frozen("task-freeze-test"))

    def test_reject_count(self):
        self.cb.record_reject("task-count")
        self.cb.record_reject("task-count")
        self.assertEqual(self.cb.reject_count("task-count"), 2)

    def test_normal_mode_default(self):
        from governor.circuit_breaker import SystemMode
        self.assertEqual(self.cb.mode, SystemMode.NORMAL)

    def test_limited_mode_after_vetos(self):
        from governor.circuit_breaker import SystemMode
        for _ in range(5):
            self.cb.record_veto()
        self.assertEqual(self.cb.mode, SystemMode.LIMITED)

    def test_reset_veto_streak(self):
        from governor.circuit_breaker import SystemMode
        for _ in range(5):
            self.cb.record_veto()
        self.cb.reset_veto_streak()
        self.assertEqual(self.cb.mode, SystemMode.NORMAL)


class TestGovernanceRoutes(unittest.TestCase):
    """Test governance routes can be imported."""

    def test_router_import(self):
        from api.routes.governance_routes import router
        self.assertGreater(len(router.routes), 0)

    def test_router_has_status_route(self):
        from api.routes.governance_routes import router
        paths = [r.path for r in router.routes]
        self.assertIn("/status", paths)
        self.assertIn("/audit", paths)
        self.assertIn("/approvals", paths)


class TestManifest(unittest.TestCase):
    """Test skills/__manifest__.yaml integrity."""

    def test_manifest_loads(self):
        import yaml
        with open("skills/__manifest__.yaml") as f:
            data = yaml.safe_load(f)
        self.assertIn("skills", data)
        self.assertGreaterEqual(len(data["skills"]), 62)

    def test_all_skills_have_required_fields(self):
        import yaml
        with open("skills/__manifest__.yaml") as f:
            data = yaml.safe_load(f)
        for skill in data["skills"]:
            self.assertIn("name", skill, f"Skill missing 'name': {skill}")
            self.assertIn("handler", skill, f"Skill {skill.get('name')} missing 'handler'")
            self.assertIn("category", skill, f"Skill {skill.get('name')} missing 'category'")
            self.assertIn("timeout_s", skill, f"Skill {skill.get('name')} missing 'timeout_s'")

    def test_categories_are_valid(self):
        import yaml
        valid_cats = {"core", "dev", "data", "search", "comm", "ops", "media", "finance", "ext"}
        with open("skills/__manifest__.yaml") as f:
            data = yaml.safe_load(f)
        for skill in data["skills"]:
            self.assertIn(
                skill.get("category"), valid_cats,
                f"Skill {skill['name']} has invalid category: {skill.get('category')}"
            )


if __name__ == "__main__":
    unittest.main()
