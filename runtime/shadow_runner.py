# -*- coding: utf-8 -*-
"""
ArcMind — Shadow Runner
=========================
影子迭代系統：使用 git worktree 建立鏡射區，
所有代碼變更先在影子中測試，通過後才合併到主系統。

流程：
  setup() → apply(changes) → test() → promote() or rollback()
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.shadow_runner")

_ARCMIND_DIR = Path(__file__).resolve().parent.parent
_SHADOW_DIR = _ARCMIND_DIR.parent / "arcmind_shadow"
_SHADOW_BRANCH = "shadow-staging"


class ShadowRunner:
    """
    影子系統管理器。
    使用 git worktree 建立輕量級鏡射區（共享 .git，零磁碟複製開銷）。
    """

    def __init__(self):
        self.main_dir = _ARCMIND_DIR
        self.shadow_dir = _SHADOW_DIR
        self.branch = _SHADOW_BRANCH
        self._test_log: list[dict] = []

    # ── Setup ────────────────────────────────────────────────────────────────

    def setup(self) -> dict:
        """建立或重置影子 worktree。"""
        try:
            # Ensure we have a clean branch
            if self.shadow_dir.exists():
                self.cleanup()

            # Create shadow branch from current HEAD
            self._git(["branch", "-D", self.branch], check=False)
            self._git(["branch", self.branch])

            # Create worktree
            self._git(["worktree", "add", str(self.shadow_dir), self.branch])

            # Copy runtime files not tracked by git (.env, data/)
            env_file = self.main_dir / ".env"
            if env_file.exists():
                shutil.copy2(env_file, self.shadow_dir / ".env")

            # Create data dir for shadow DB
            (self.shadow_dir / "data").mkdir(exist_ok=True)

            logger.info("[Shadow] Worktree created at %s", self.shadow_dir)
            return {"status": "ready", "path": str(self.shadow_dir)}

        except Exception as e:
            logger.error("[Shadow] Setup failed: %s", e)
            return {"status": "error", "error": str(e)}

    # ── Apply Changes ────────────────────────────────────────────────────────

    def apply_changes(self, changes: list[dict]) -> dict:
        """
        應用代碼變更到影子區。

        changes: list of {
            "action": "create" | "modify" | "delete",
            "path": "relative/path/to/file",
            "content": "file content" (for create/modify)
        }
        """
        applied = []
        errors = []

        for change in changes:
            action = change.get("action", "modify")
            rel_path = change.get("path", "")
            content = change.get("content", "")

            target = self.shadow_dir / rel_path
            try:
                if action == "create" or action == "modify":
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content, encoding="utf-8")
                    applied.append(f"{action}: {rel_path}")

                elif action == "delete":
                    if target.exists():
                        target.unlink()
                        applied.append(f"delete: {rel_path}")
                    else:
                        errors.append(f"not found: {rel_path}")

            except Exception as e:
                errors.append(f"{action} {rel_path}: {e}")

        logger.info("[Shadow] Applied %d changes, %d errors", len(applied), len(errors))
        return {"applied": applied, "errors": errors}

    # ── Test ─────────────────────────────────────────────────────────────────

    def test(self, test_commands: list[str] | None = None) -> dict:
        """
        在影子區運行測試。

        Default tests:
        1. Python syntax check (compile all .py files)
        2. Import check (try importing key modules)
        3. Custom test commands (if provided)
        """
        self._test_log = []
        all_passed = True

        # Test 1: Syntax check — compile all changed .py files
        result = self._run_test(
            "syntax_check",
            [
                sys.executable, "-c",
                "import py_compile; import glob; "
                f"files = glob.glob('{self.shadow_dir}/**/*.py', recursive=True); "
                "errors = []; "
                "[errors.append(f) for f in files "
                "if not f.startswith(str(__import__('pathlib').Path('" + str(self.shadow_dir) + "') / '.venv'))"
                " and __import__('py_compile').compile(f, doraise=False) is None]; "
                "print(f'Checked {len(files)} files, {len(errors)} errors'); "
                "exit(1 if errors else 0)"
            ],
        )
        if not result["passed"]:
            all_passed = False

        # Test 2: Import check — try importing core modules
        import_test = (
            "import sys; "
            f"sys.path.insert(0, '{self.shadow_dir}'); "
            "from config.settings import settings; "
            "from db.schema import init_db; "
            "from runtime.tool_loop import tool_registry; "
            "from runtime.iteration_engine import collect_system_intel; "
            "print('All imports OK')"
        )
        result = self._run_test(
            "import_check",
            [sys.executable, "-c", import_test],
        )
        if not result["passed"]:
            all_passed = False

        # Test 3: Custom tests
        if test_commands:
            for i, cmd in enumerate(test_commands):
                result = self._run_test(
                    f"custom_test_{i}",
                    ["bash", "-c", f"cd {self.shadow_dir} && {cmd}"],
                )
                if not result["passed"]:
                    all_passed = False

        summary = {
            "all_passed": all_passed,
            "tests": self._test_log,
            "total": len(self._test_log),
            "passed": sum(1 for t in self._test_log if t["passed"]),
            "failed": sum(1 for t in self._test_log if not t["passed"]),
        }
        logger.info("[Shadow] Tests complete: %d/%d passed",
                    summary["passed"], summary["total"])
        return summary

    def _run_test(self, name: str, cmd: list[str], timeout: int = 30) -> dict:
        """Run a single test command."""
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.shadow_dir),
                env={**os.environ, "PYTHONPATH": str(self.shadow_dir)},
            )
            passed = proc.returncode == 0
            result = {
                "name": name,
                "passed": passed,
                "stdout": proc.stdout[-500:] if proc.stdout else "",
                "stderr": proc.stderr[-500:] if proc.stderr else "",
            }
        except subprocess.TimeoutExpired:
            result = {"name": name, "passed": False, "error": "timeout"}
        except Exception as e:
            result = {"name": name, "passed": False, "error": str(e)}

        self._test_log.append(result)
        level = logging.INFO if result.get("passed") else logging.WARNING
        logger.log(level, "[Shadow] Test '%s': %s",
                   name, "PASS" if result.get("passed") else "FAIL")
        return result

    # ── Promote ──────────────────────────────────────────────────────────────

    def promote(self) -> dict:
        """
        影子測試通過 → 合併到主系統。
        1. Commit shadow changes
        2. Switch to main and merge
        3. Restart the main agent
        """
        try:
            # Commit all shadow changes
            self._git_shadow(["add", "-A"])
            self._git_shadow([
                "commit", "-m",
                f"auto-iteration: shadow promote {datetime.now().strftime('%Y%m%d-%H%M')}"
            ], check=False)

            # Merge into main
            self._git(["merge", self.branch, "--no-edit"])

            logger.info("[Shadow] Promoted shadow changes to main")

            # Restart main agent
            restart_result = self._restart_main()

            return {
                "status": "promoted",
                "restart": restart_result,
            }

        except Exception as e:
            logger.error("[Shadow] Promote failed: %s", e)
            return {"status": "error", "error": str(e)}

    # ── Rollback ─────────────────────────────────────────────────────────────

    def rollback(self) -> dict:
        """放棄影子中的所有變更。"""
        try:
            self._git_shadow(["checkout", "--", "."])
            self._git_shadow(["clean", "-fd"])
            logger.info("[Shadow] Rollback complete")
            return {"status": "rolled_back"}
        except Exception as e:
            logger.error("[Shadow] Rollback failed: %s", e)
            return {"status": "error", "error": str(e)}

    # ── Cleanup ──────────────────────────────────────────────────────────────

    def cleanup(self) -> dict:
        """Remove shadow worktree."""
        try:
            self._git(["worktree", "remove", str(self.shadow_dir), "--force"],
                      check=False)
            if self.shadow_dir.exists():
                shutil.rmtree(self.shadow_dir, ignore_errors=True)
            logger.info("[Shadow] Cleanup complete")
            return {"status": "cleaned"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # ── Status ───────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Get current shadow system status."""
        exists = self.shadow_dir.exists()
        if not exists:
            return {"active": False, "path": str(self.shadow_dir)}

        # Get diff summary
        try:
            diff = self._git_shadow(["diff", "--stat", "HEAD"], capture=True)
        except Exception:
            diff = ""

        return {
            "active": True,
            "path": str(self.shadow_dir),
            "branch": self.branch,
            "diff_summary": diff.strip() if diff else "no changes",
        }

    # ── Git Helpers ──────────────────────────────────────────────────────────

    def _git(self, args: list[str], check: bool = True, capture: bool = False) -> str:
        """Run git command in main repo."""
        cmd = ["git", "-C", str(self.main_dir)] + args
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout if capture else ""

    def _git_shadow(self, args: list[str], check: bool = True, capture: bool = False) -> str:
        """Run git command in shadow repo."""
        cmd = ["git", "-C", str(self.shadow_dir)] + args
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )
        if check and proc.returncode != 0:
            raise RuntimeError(f"git (shadow) {' '.join(args)} failed: {proc.stderr}")
        return proc.stdout if capture else ""

    def _restart_main(self) -> str:
        """Restart the main agent via launchctl."""
        try:
            uid = os.getuid()
            subprocess.run(
                ["launchctl", "kickstart", "-k", f"gui/{uid}/com.arcmind.server"],
                capture_output=True, timeout=10,
            )
            return "restarted"
        except Exception as e:
            return f"restart_failed: {e}"


# ── Singleton ──
shadow_runner = ShadowRunner()
