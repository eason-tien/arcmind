# -*- coding: utf-8 -*-
"""
ArcMind Skill Installer
========================
從 GitHub 安裝、移除、管理外部技能。

安裝流程：
  1. 從 GitHub 下載 repo（或單個檔案）
  2. 驗證 skill.yaml 格式
  3. 安全檢查（禁止危險 import）
  4. 複製到 skills/ 目錄
  5. 更新 __manifest__.yaml
  6. 熱載入到 SkillManager

安全規則：
  - 禁止 eval / exec / __import__ / compile
  - 禁止 os.system / subprocess（需用 code_exec skill）
  - 只允許 GitHub public repos
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

from config.settings import settings

logger = logging.getLogger("arcmind.skill_installer")

# ── Safety ──────────────────────────────────────────────────────────────────

_BANNED_PATTERNS = [
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\b__import__\s*\(",
    r"\bcompile\s*\(",
    r"\bos\.system\s*\(",
    r"\bos\.popen\s*\(",
    r"\bsubprocess\.\w+\s*\(",
    r"\bctypes\b",
    r"\bpickle\.loads?\s*\(",
]

_BANNED_RE = re.compile("|".join(_BANNED_PATTERNS))


def _check_safety(code: str, filename: str) -> list[str]:
    """Check Python code for banned patterns. Returns list of violations."""
    violations = []
    for i, line in enumerate(code.split("\n"), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        matches = _BANNED_RE.findall(line)
        if matches:
            violations.append(f"  {filename}:{i} → {', '.join(matches)}")
    return violations


# ── GitHub Download ─────────────────────────────────────────────────────────

def _parse_github_url(url: str) -> dict:
    """
    Parse GitHub URL into components.
    Supports:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/tree/branch/path/to/skill
      - owner/repo (shorthand)
    """
    url = url.strip().rstrip("/")

    # Shorthand: owner/repo
    if "/" in url and "github.com" not in url and "://" not in url:
        parts = url.split("/")
        if len(parts) == 2:
            return {"owner": parts[0], "repo": parts[1], "branch": "main", "path": ""}

    # Full URL
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)(?:/tree/([^/]+)(?:/(.+))?)?",
        url,
    )
    if m:
        return {
            "owner": m.group(1),
            "repo": m.group(2),
            "branch": m.group(3) or "main",
            "path": m.group(4) or "",
        }

    raise ValueError(f"無法解析 GitHub URL: {url}")


def _download_from_github(url: str, dest: Path) -> Path:
    """Download a GitHub repo (or subdirectory) to dest."""
    info = _parse_github_url(url)

    # Use git clone (shallow)
    clone_url = f"https://github.com/{info['owner']}/{info['repo']}.git"
    tmp = tempfile.mkdtemp(prefix="arcmind_skill_")

    try:
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "-b", info["branch"], clone_url, tmp],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone 失敗: {result.stderr.strip()}")

        # If path specified, use subdirectory
        source = Path(tmp)
        if info["path"]:
            source = source / info["path"]
            if not source.exists():
                raise FileNotFoundError(f"路徑不存在: {info['path']}")

        return source
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


# ── Installer ───────────────────────────────────────────────────────────────

class SkillInstaller:
    """Skill 安裝器：下載、驗證、安裝、移除。"""

    def __init__(self):
        self.skills_dir = settings.skills_dir
        self.manifest_path = self.skills_dir / "__manifest__.yaml"
        # Track installed (non-builtin) skills
        self._installed_file = self.skills_dir / ".installed.json"

    def _load_installed(self) -> dict[str, dict]:
        """Load registry of externally installed skills."""
        if self._installed_file.exists():
            try:
                return json.loads(self._installed_file.read_text())
            except Exception:
                return {}
        return {}

    def _save_installed(self, data: dict) -> None:
        self._installed_file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False)
        )

    def install(self, url: str) -> dict:
        """
        Install a skill from GitHub.
        Returns: {success, name, message, permissions}
        """
        logger.info("[SkillInstaller] Installing from: %s", url)

        # 1. Download
        try:
            source = _download_from_github(url, self.skills_dir)
        except Exception as e:
            return {"success": False, "name": "", "message": f"下載失敗: {e}"}

        try:
            # 2. Find skill.yaml
            skill_yaml = source / "skill.yaml"
            if not skill_yaml.exists():
                # Maybe it's a single-file skill with yaml header
                py_files = list(source.glob("*.py"))
                if len(py_files) == 1:
                    # Single file skill — create a basic skill.yaml
                    name = py_files[0].stem
                    manifest = {
                        "name": name,
                        "version": "1.0",
                        "description": f"Installed from {url}",
                        "handler": "run",
                        "permissions": [],
                    }
                else:
                    return {"success": False, "name": "",
                            "message": "找不到 skill.yaml，無法識別技能格式"}
            else:
                with open(skill_yaml) as f:
                    manifest = yaml.safe_load(f)

            name = manifest.get("name", "")
            if not name:
                return {"success": False, "name": "",
                        "message": "skill.yaml 缺少 name 欄位"}

            # 3. Safety check all .py files
            all_violations = []
            for py_file in source.glob("**/*.py"):
                code = py_file.read_text(errors="ignore")
                violations = _check_safety(code, py_file.name)
                all_violations.extend(violations)

            if all_violations:
                violation_text = "\n".join(all_violations)
                return {"success": False, "name": name,
                        "message": f"⚠️ 安全檢查未通過:\n{violation_text}"}

            # 4. Check if already installed
            target_module = self.skills_dir / f"{name}.py"
            if target_module.exists():
                installed = self._load_installed()
                if name not in installed:
                    return {"success": False, "name": name,
                            "message": f"技能 '{name}' 是內建技能，無法覆蓋"}

            # 5. Copy files to skills/
            module_file = manifest.get("module", f"{name}.py")
            src_module = source / module_file
            if not src_module.exists():
                # Try finding it
                py_files = list(source.glob("*.py"))
                if py_files:
                    src_module = py_files[0]
                else:
                    return {"success": False, "name": name,
                            "message": f"找不到模組檔案: {module_file}"}

            shutil.copy2(src_module, target_module)

            # Copy any extra files (data, configs) but not git stuff
            for extra in source.iterdir():
                if extra.name.startswith(".") or extra.name == "__pycache__":
                    continue
                if extra.suffix in (".py", ".yaml", ".json", ".txt", ".md"):
                    if extra.name != module_file:
                        dest = self.skills_dir / f"{name}_{extra.name}"
                        shutil.copy2(extra, dest)

            # 6. Update __manifest__.yaml
            self._add_to_manifest(manifest)

            # 7. Record installation
            installed = self._load_installed()
            installed[name] = {
                "source": url,
                "version": manifest.get("version", "1.0"),
                "permissions": manifest.get("permissions", []),
            }
            self._save_installed(installed)

            # 8. Hot reload into SkillManager
            try:
                from runtime.skill_manager import skill_manager
                handler = manifest.get("handler", "run")
                skill_manager._load_skill(name, target_module, handler, manifest)
                logger.info("[SkillInstaller] Hot-loaded skill: %s", name)
            except Exception as e:
                logger.warning("[SkillInstaller] Hot-load failed: %s", e)

            permissions = manifest.get("permissions", [])
            return {
                "success": True,
                "name": name,
                "message": f"✅ 技能 '{name}' 安裝成功",
                "permissions": permissions,
                "version": manifest.get("version", "1.0"),
                "description": manifest.get("description", ""),
            }

        finally:
            # Clean up temp directory
            tmp_root = source
            while tmp_root.parent != tmp_root and "arcmind_skill_" not in tmp_root.name:
                tmp_root = tmp_root.parent
            if "arcmind_skill_" in tmp_root.name:
                shutil.rmtree(tmp_root, ignore_errors=True)

    def remove(self, name: str) -> dict:
        """Remove an installed skill."""
        installed = self._load_installed()

        if name not in installed:
            # Check if it's a builtin
            target = self.skills_dir / f"{name}.py"
            if target.exists():
                return {"success": False,
                        "message": f"'{name}' 是內建技能，無法移除"}
            return {"success": False,
                    "message": f"技能 '{name}' 未安裝"}

        # 1. Delete module file
        target = self.skills_dir / f"{name}.py"
        if target.exists():
            target.unlink()

        # Delete any related data files
        for f in self.skills_dir.glob(f"{name}_*"):
            f.unlink()

        # 2. Remove from manifest
        self._remove_from_manifest(name)

        # 3. Remove from installed registry
        del installed[name]
        self._save_installed(installed)

        # 4. Unregister from SkillManager
        try:
            from runtime.skill_manager import skill_manager
            skill_manager.unregister(name)
        except Exception as e:
            logger.warning("[SkillInstaller] Unregister failed: %s", e)

        return {"success": True,
                "message": f"✅ 技能 '{name}' 已移除"}

    def list_installed(self) -> list[dict]:
        """List all skills with source info."""
        installed = self._load_installed()

        try:
            from runtime.skill_manager import skill_manager
            all_skills = skill_manager.list_skills()
        except Exception:
            all_skills = []

        result = []
        for s in all_skills:
            name = s.get("name", "") if isinstance(s, dict) else s
            info = installed.get(name, {})
            result.append({
                "name": name,
                "source": info.get("source", "built-in"),
                "version": info.get("version",
                    s.get("manifest", {}).get("version", "?") if isinstance(s, dict) else "?"),
                "removable": name in installed,
            })
        return result

    # ── Manifest helpers ──

    def _add_to_manifest(self, manifest: dict) -> None:
        """Add a skill entry to __manifest__.yaml."""
        try:
            with open(self.manifest_path) as f:
                data = yaml.safe_load(f) or {}

            skills = data.get("skills", [])

            # Remove existing entry with same name
            skills = [s for s in skills if s.get("name") != manifest["name"]]

            # Add new entry
            entry = {
                "name": manifest["name"],
                "module": manifest.get("module", f"{manifest['name']}.py"),
                "handler": manifest.get("handler", "run"),
                "version": manifest.get("version", "1.0"),
                "description": manifest.get("description", ""),
                "permissions": manifest.get("permissions", []),
                "tags": manifest.get("tags", []),
                "governor_required": manifest.get("governor_required", True),
            }
            skills.append(entry)
            data["skills"] = skills

            with open(self.manifest_path, "w") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                          sort_keys=False)
        except Exception as e:
            logger.warning("[SkillInstaller] Manifest update failed: %s", e)

    def _remove_from_manifest(self, name: str) -> None:
        """Remove a skill entry from __manifest__.yaml."""
        try:
            with open(self.manifest_path) as f:
                data = yaml.safe_load(f) or {}

            skills = data.get("skills", [])
            data["skills"] = [s for s in skills if s.get("name") != name]

            with open(self.manifest_path, "w") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False,
                          sort_keys=False)
        except Exception as e:
            logger.warning("[SkillInstaller] Manifest remove failed: %s", e)


# ── Singleton ──
skill_installer = SkillInstaller()
