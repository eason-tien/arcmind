"""
ArcMind Skill 管理器
本地技能登錄、發現、執行。格式相容 OpenClaw Skill 協議。
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from config.settings import settings
from db.schema import SkillRegistry_, get_db, get_db_session

logger = logging.getLogger("arcmind.skill_manager")


class SkillError(Exception):
    pass


class SkillNotFound(SkillError):
    pass


class SkillInvocationError(SkillError):
    pass


class SkillPermissionDenied(SkillError):
    """Agent does not have permission to invoke this skill."""
    pass


class SkillManager:
    """
    技能管理器：
    - 從 skills/ 目錄自動掃描並登錄技能
    - 透過名稱呼叫技能
    - 維護呼叫計數與錯誤記錄
    """

    def __init__(self):
        self._local: dict[str, Callable] = {}   # name → callable
        self._manifests: dict[str, dict] = {}    # name → manifest dict

    # ── 啟動：掃描並載入所有本地技能 ─────────────────────────────────────────

    def startup(self) -> None:
        manifest_path = settings.skills_dir / "__manifest__.yaml"
        if manifest_path.exists():
            self._load_from_manifest(manifest_path)
        else:
            logger.warning("No __manifest__.yaml found in skills/. Scanning .py files.")
            self._scan_skills_dir()

    def _load_from_manifest(self, manifest_path: Path) -> None:
        with open(manifest_path, "r") as f:
            data = yaml.safe_load(f)

        for entry in data.get("skills", []):
            name = entry["name"]
            module_file = settings.skills_dir / entry.get("module", f"{name}.py")
            handler = entry.get("handler", "run")
            self._load_skill(name, module_file, handler, entry)

    def _scan_skills_dir(self) -> None:
        for py_file in settings.skills_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            name = py_file.stem
            self._load_skill(name, py_file, "run", {"name": name})

    def _load_skill(self, name: str, module_path: Path,
                    handler: str, manifest: dict) -> None:
        if not module_path.exists():
            logger.warning("Skill module not found: %s", module_path)
            return
        try:
            spec = importlib.util.spec_from_file_location(
                f"arcmind.skills.{name}", module_path
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)

            fn = getattr(mod, handler, None)
            if fn is None:
                logger.warning("Skill %s has no '%s' function.", name, handler)
                return

            self._local[name] = fn
            self._manifests[name] = manifest
            self._upsert_registry(name, manifest)
            logger.info("Loaded skill: %s", name)
        except Exception as e:
            logger.error("Failed to load skill %s: %s", name, e)

    def _upsert_registry(self, name: str, manifest: dict) -> None:
        try:
            with get_db_session() as db:
                existing = db.query(SkillRegistry_).filter_by(name=name).first()
                if existing:
                    existing.manifest = json.dumps(manifest)
                    existing.enabled = True
                else:
                    rec = SkillRegistry_(
                        name=name,
                        version=manifest.get("version", "1.0"),
                        description=manifest.get("description", ""),
                        manifest=json.dumps(manifest),
                        source="local",
                    )
                    db.add(rec)
                db.commit()
        except Exception as e:
            logger.warning("Could not upsert skill registry for %s: %s", name, e)

    # ── 技能呼叫 ──────────────────────────────────────────────────────────────

    def invoke(self, name: str, inputs: dict | None = None,
               timeout: int = 60, caller_agent: str | None = None) -> dict:
        """
        呼叫一個本地技能。
        caller_agent: 呼叫者 agent id（用於權限檢查，None = 不檢查）
        回傳: {success: bool, output: Any, error: str|None, elapsed_s: float}
        """
        if name not in self._local:
            raise SkillNotFound(f"Skill '{name}' not registered.")

        # V3.1: Per-agent skill access control
        if caller_agent:
            self._check_agent_permission(name, caller_agent)

        fn = self._local[name]
        inputs = inputs or {}
        start = time.monotonic()

        try:
            result = fn(inputs)
            elapsed = time.monotonic() - start
            self._increment_count(name, success=True)
            return {"success": True, "output": result, "error": None,
                    "elapsed_s": round(elapsed, 3)}
        except Exception as e:
            elapsed = time.monotonic() - start
            self._increment_count(name, success=False)
            logger.error("Skill %s raised: %s", name, e)
            return {"success": False, "output": None, "error": str(e),
                    "elapsed_s": round(elapsed, 3)}

    def _increment_count(self, name: str, success: bool) -> None:
        try:
            with get_db_session() as db:
                rec = db.query(SkillRegistry_).filter_by(name=name).first()
                if rec:
                    rec.invoke_count += 1
                    if not success:
                        rec.error_count += 1
                    db.commit()
        except Exception:
            pass

    # ── 權限檢查 ────────────────────────────────────────────────────────────────

    def _check_agent_permission(self, skill_name: str, agent_id: str) -> None:
        """V3.1: 檢查 agent 是否有權呼叫此 skill。無權則拋出 SkillPermissionDenied。"""
        try:
            from runtime.agent_registry import agent_registry
            persona = agent_registry.get(agent_id)
            if not persona:
                return  # Agent not found in registry → allow (graceful)
            allowed = persona.allowed_skills
            if not allowed:
                return  # Empty list = no restriction (backward compat)
            if "__all__" in allowed:
                return  # Explicit all-access
            if skill_name in allowed:
                return  # Whitelisted
            # Denied
            logger.warning(
                "[SkillManager] Permission denied: agent '%s' cannot invoke '%s' "
                "(allowed: %s)", agent_id, skill_name, allowed
            )
            raise SkillPermissionDenied(
                f"Agent '{agent_id}' is not permitted to invoke skill '{skill_name}'"
            )
        except SkillPermissionDenied:
            raise
        except Exception as e:
            logger.warning("[SkillManager] Permission check error: %s", e)
            # Fail-open on registry errors to avoid blocking execution
            return

    def list_skills_for_agent(self, agent_id: str) -> list[dict]:
        """V3.1: 返回指定 agent 可用的 skill 列表。"""
        try:
            from runtime.agent_registry import agent_registry
            persona = agent_registry.get(agent_id)
            if not persona or not persona.allowed_skills:
                return self.list_skills()  # No restriction → all skills
            if "__all__" in persona.allowed_skills:
                return self.list_skills()

            return [
                {"name": name, "manifest": manifest}
                for name, manifest in self._manifests.items()
                if name in persona.allowed_skills
            ]
        except Exception:
            return self.list_skills()

    # ── 查詢 ──────────────────────────────────────────────────────────────────

    def list_skills(self) -> list[dict]:
        return [
            {"name": name, "manifest": manifest}
            for name, manifest in self._manifests.items()
        ]

    def get_manifest(self, name: str) -> dict | None:
        return self._manifests.get(name)

    def is_registered(self, name: str) -> bool:
        return name in self._local

    def register(self, name: str, fn: Callable, manifest: dict | None = None) -> None:
        """動態登錄一個技能（runtime 注入）"""
        self._local[name] = fn
        self._manifests[name] = manifest or {"name": name}
        self._upsert_registry(name, self._manifests[name])
        logger.info("Dynamically registered skill: %s", name)

    def unregister(self, name: str) -> bool:
        """動態卸載一個技能"""
        removed = name in self._local
        self._local.pop(name, None)
        self._manifests.pop(name, None)
        if removed:
            logger.info("Unregistered skill: %s", name)
        return removed


# 全域單例（main.py startup() 後呼叫）
skill_manager = SkillManager()
