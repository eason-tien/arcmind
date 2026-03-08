# -*- coding: utf-8 -*-
"""
ArcMind — Harness Engine Tests
================================
Tests for runtime/harness.py, db/harness_schema.py, and runtime/harness_tool.py.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Use test environment so Settings loads safely
os.environ["ARCMIND_ENV"] = "test"

import pytest
from unittest.mock import patch, AsyncMock
from datetime import datetime


# ── Helper ──────────────────────────────────────────────────────────────────

def _make_loop_result(success=True, output="test output", error=None, tokens=100):
    """Create a mock LoopResult."""
    from loop.main_loop import LoopResult
    return LoopResult(
        success=success,
        task_id=1,
        skill_used="_model_direct",
        model_used="test:model",
        output=output,
        tokens_used=tokens,
        elapsed_s=0.5,
        governor_approved=True,
        error=error,
    )


# ── DB Schema Tests ─────────────────────────────────────────────────────────

class TestHarnessSchema:
    """Tests for db/harness_schema.py"""

    def test_tables_created(self):
        from db.schema import engine, init_db
        from sqlalchemy import inspect
        init_db()
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "am_harness_runs" in tables
        assert "am_harness_steps" in tables

    def test_run_record_insert(self):
        import uuid
        from db.schema import get_db, init_db
        from db.harness_schema import HarnessRun_
        init_db()
        run_id = f"test-{uuid.uuid4().hex[:8]}"
        db = next(get_db())
        try:
            run = HarnessRun_(
                id=run_id,
                title="Test Run",
                status="pending",
                plan_json='[{"name":"s1","command":"do thing"}]',
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(run)
            db.commit()

            loaded = db.query(HarnessRun_).filter_by(id=run_id).first()
            assert loaded is not None
            assert loaded.title == "Test Run"
            assert loaded.status == "pending"

            # Cleanup
            db.delete(loaded)
            db.commit()
        finally:
            db.close()

    def test_step_record_insert(self):
        import uuid
        from db.schema import get_db, init_db
        from db.harness_schema import HarnessRun_, HarnessStep_
        init_db()
        run_id = f"test-{uuid.uuid4().hex[:8]}"
        db = next(get_db())
        try:
            run = HarnessRun_(
                id=run_id, title="Test", status="pending",
                created_at=datetime.utcnow(), updated_at=datetime.utcnow(),
            )
            db.add(run)

            step = HarnessStep_(
                run_id=run_id,
                step_idx=0,
                name="step_0",
                command="do something",
                status="pending",
            )
            db.add(step)
            db.commit()

            loaded = db.query(HarnessStep_).filter_by(run_id=run_id).first()
            assert loaded is not None
            assert loaded.name == "step_0"
            assert loaded.command == "do something"

            # Cleanup (steps first due to FK)
            db.query(HarnessStep_).filter_by(run_id=run_id).delete()
            db.query(HarnessRun_).filter_by(id=run_id).delete()
            db.commit()
        finally:
            db.close()


# ── Engine Lifecycle Tests ──────────────────────────────────────────────────

class TestHarnessEngine:
    """Tests for runtime/harness.py — HarnessEngine"""

    def setup_method(self):
        """Ensure DB tables exist."""
        from db.schema import init_db
        init_db()

    @pytest.mark.asyncio
    async def test_create_run(self):
        from runtime.harness import HarnessEngine
        engine = HarnessEngine()

        run_id = await engine.create_run(
            title="Research Task",
            plan=[
                {"name": "research", "command": "搜集資料"},
                {"name": "analyze",  "command": "分析資料"},
                {"name": "report",   "command": "撰寫報告"},
            ],
        )

        assert run_id is not None
        assert len(run_id) == 8

        info = engine.get_run(run_id)
        assert info["title"] == "Research Task"
        assert info["status"] == "pending"
        assert len(info["steps"]) == 3
        assert info["steps"][0]["name"] == "research"

    @pytest.mark.asyncio
    async def test_execute_run_success(self):
        from runtime.harness import HarnessEngine
        engine = HarnessEngine()

        run_id = await engine.create_run(
            title="Simple Task",
            plan=[
                {"name": "step1", "command": "do step 1"},
                {"name": "step2", "command": "do step 2"},
            ],
        )

        mock_result = _make_loop_result(success=True, output="done")
        with patch("loop.main_loop.main_loop") as mock_loop:
            mock_loop.run.return_value = mock_result
            with patch.object(engine, "_notify_progress", new_callable=AsyncMock):
                result = await engine.execute_run(run_id)

        assert result["status"] == "completed"
        assert all(s["status"] == "completed" for s in result["steps"])

    @pytest.mark.asyncio
    async def test_execute_run_step_failure(self):
        from runtime.harness import HarnessEngine
        engine = HarnessEngine()

        run_id = await engine.create_run(
            title="Failing Task",
            plan=[
                {"name": "ok_step", "command": "this works"},
                {"name": "fail_step", "command": "this fails"},
            ],
            retry_max=0,
        )

        call_count = 0
        def mock_run(inp):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_loop_result(success=True, output="ok")
            return _make_loop_result(success=False, error="step failed")

        with patch("loop.main_loop.main_loop") as mock_loop:
            mock_loop.run.side_effect = mock_run
            with patch.object(engine, "_notify_progress", new_callable=AsyncMock):
                result = await engine.execute_run(run_id)

        assert result["status"] == "failed"
        assert result["steps"][0]["status"] == "completed"
        assert result["steps"][1]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_cancel_run(self):
        from runtime.harness import HarnessEngine
        engine = HarnessEngine()

        run_id = await engine.create_run(
            title="To Cancel",
            plan=[{"name": "s1", "command": "do"}],
        )

        result = await engine.cancel_run(run_id)
        assert result["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_list_runs(self):
        from runtime.harness import HarnessEngine
        engine = HarnessEngine()

        await engine.create_run(title="Run A", plan=[{"name": "s", "command": "c"}])
        await engine.create_run(title="Run B", plan=[{"name": "s", "command": "c"}])

        runs = engine.list_runs()
        assert len(runs) >= 2

    @pytest.mark.asyncio
    async def test_retry_failed_run(self):
        from runtime.harness import HarnessEngine
        engine = HarnessEngine()

        run_id = await engine.create_run(
            title="Retry Test",
            plan=[{"name": "s1", "command": "fail then succeed"}],
            retry_max=0,
        )

        # First: fail
        with patch("loop.main_loop.main_loop") as mock_loop:
            mock_loop.run.return_value = _make_loop_result(success=False, error="oops")
            with patch.object(engine, "_notify_progress", new_callable=AsyncMock):
                result = await engine.execute_run(run_id)
        assert result["status"] == "failed"

        # Retry: succeed
        with patch("loop.main_loop.main_loop") as mock_loop:
            mock_loop.run.return_value = _make_loop_result(success=True, output="fixed")
            with patch.object(engine, "_notify_progress", new_callable=AsyncMock):
                result = await engine.retry_run(run_id)
        assert result["status"] == "completed"


# ── Tool Function Tests ─────────────────────────────────────────────────────

class TestHarnessTools:
    """Tests for runtime/harness_tool.py"""

    def setup_method(self):
        from db.schema import init_db
        init_db()

    def test_tool_harness_status_empty(self):
        from runtime.harness_tool import tool_harness_status
        result = json.loads(tool_harness_status(list_all=True))
        assert isinstance(result, list)

    def test_tool_harness_create_validation(self):
        from runtime.harness_tool import tool_harness_create
        result = json.loads(tool_harness_create(title="Bad", steps=[]))
        assert "error" in result

    def test_tool_harness_control_unknown_action(self):
        from runtime.harness_tool import tool_harness_control
        result = json.loads(tool_harness_control(run_id="nonexistent", action="explode"))
        assert "error" in result

    def test_harness_tool_schemas_complete(self):
        from runtime.harness_tool import HARNESS_TOOL_SCHEMAS
        assert "harness_create" in HARNESS_TOOL_SCHEMAS
        assert "harness_status" in HARNESS_TOOL_SCHEMAS
        assert "harness_control" in HARNESS_TOOL_SCHEMAS

        for name, spec in HARNESS_TOOL_SCHEMAS.items():
            assert "description" in spec
            assert "input_schema" in spec
            assert "handler" in spec
            assert callable(spec["handler"])


# ── LoopResult Extension Test ───────────────────────────────────────────────

class TestLoopResultExtension:
    """Tests for harness_run_id field in LoopResult"""

    def test_loop_result_has_harness_field(self):
        from loop.main_loop import LoopResult
        result = LoopResult(
            success=True, task_id=1, skill_used="test",
            model_used="test", output="hi", tokens_used=0,
            elapsed_s=0.1, governor_approved=True,
            harness_run_id="abc-123",
        )
        assert result.harness_run_id == "abc-123"

    def test_loop_result_harness_field_default_none(self):
        from loop.main_loop import LoopResult
        result = LoopResult(
            success=True, task_id=1, skill_used="test",
            model_used="test", output="hi", tokens_used=0,
            elapsed_s=0.1, governor_approved=True,
        )
        assert result.harness_run_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
