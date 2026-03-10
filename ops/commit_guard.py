"""
ArcMind Commit Guard
自動驗證 commit message 和文件修改是否符合 CONTRIBUTING.md 規範。
可作為 git hook、CI check、或 Agent 提交前驗證使用。
"""
from __future__ import annotations

import re
import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── CONTRIBUTING.md 規則定義 ──

VALID_TYPES = [
    "feat", "fix", "perf", "refactor", "test", "docs", "chore", "ci", "style",
    "feat!", "release",
]

VALID_SCOPES = [
    "loop", "memory", "skills", "tools", "governor", "gateway", "channels",
    "runtime", "ops", "config", "api", "db", "persona", "android", "bridge", "ci",
]

# 禁止 Agent 修改的文件
PROTECTED_FILES = {
    ".env",
    "config/agents.json",
    "governor/governor.py",
    "governor/circuit_breaker.py",
}

# Level 3 文件（需 Human 審批）
LEVEL3_PATHS = [
    "loop/main_loop.py",
    "governor/",
    "config/agents.json",
    "db/schema.py",
]

# Key 洩漏模式
SECRET_PATTERNS = [
    r"gho_[A-Za-z0-9]{36}",           # GitHub token
    r"sk-[A-Za-z0-9]{32,}",           # OpenAI / MiniMax key
    r"\d{9,10}:\w{35}",               # Telegram bot token
    r"/Users/\w+/",                    # 硬編碼用戶路徑
    r"AKIA[0-9A-Z]{16}",              # AWS key
    r"AIza[0-9A-Za-z_-]{35}",         # Google API key
]


def validate_commit_message(message: str) -> dict:
    """
    驗證 commit message 是否符合規範。
    
    Returns:
        {"valid": bool, "errors": list[str], "warnings": list[str]}
    """
    errors = []
    warnings = []
    
    lines = message.strip().split("\n")
    subject = lines[0].strip()
    
    # 1. 檢查 type(scope): subject 格式
    pattern = r"^(feat!?|fix|perf|refactor|test|docs|chore|ci|style|release)(\([a-z]+\))?:\s.+"
    if not re.match(pattern, subject):
        errors.append(
            f"Commit subject 不符合格式: `type(scope): subject`\n"
            f"  有效 type: {', '.join(VALID_TYPES)}\n"
            f"  有效 scope: {', '.join(VALID_SCOPES)}\n"
            f"  收到: `{subject}`"
        )
    else:
        # 驗證 scope 是否有效
        scope_match = re.match(r"^[a-z!]+\(([a-z]+)\):", subject)
        if scope_match:
            scope = scope_match.group(1)
            if scope not in VALID_SCOPES:
                warnings.append(f"Scope `{scope}` 不在預定義列表中（可能需要新增到 VALID_SCOPES）")
    
    # 2. 檢查 subject 長度
    if len(subject) > 72:
        warnings.append(f"Subject 過長 ({len(subject)} 字元，建議 ≤ 72)")
    
    # 3. 檢查 Agent-By footer
    has_agent_by = any("Agent-By:" in line for line in lines)
    if not has_agent_by:
        warnings.append("缺少 `Agent-By: <name>` footer（建議加上 agent 身份標註）")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "subject": subject,
    }


def validate_changed_files(files: list[str], agent: str = "unknown") -> dict:
    """
    驗證修改的文件是否在 Agent 的權限範圍內。
    
    Args:
        files: 修改的文件列表（相對路徑）
        agent: Agent 名稱
    
    Returns:
        {"valid": bool, "errors": list[str], "warnings": list[str], "level": int}
    """
    errors = []
    warnings = []
    max_level = 0
    
    for f in files:
        # 檢查禁止文件
        if f in PROTECTED_FILES:
            errors.append(f"🔒 禁止修改: `{f}` — 此文件僅 Human 可修改")
        
        # 判定更新等級
        if any(f.startswith(p) or f == p for p in LEVEL3_PATHS):
            max_level = max(max_level, 3)
            warnings.append(f"⚠️ Level 3 文件: `{f}` — 需要 Human (Eason) 審批")
        elif f.startswith("api/") or f.startswith("channels/") or f.startswith("memory/"):
            max_level = max(max_level, 2)
        elif f.startswith("tests/") or f == "CHANGELOG.md":
            max_level = max(max_level, 0)
        else:
            max_level = max(max_level, 1)
    
    # Agent 權限檢查
    agent_max_level = {
        "arcmind": 2,
        "antigravity": 2,
        "sub-agent": 1,
        "external": 0,
    }
    allowed = agent_max_level.get(agent, 1)
    if max_level > allowed:
        errors.append(
            f"Agent `{agent}` 的最高權限是 Level {allowed}，"
            f"但此次修改涉及 Level {max_level} 文件"
        )
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "level": max_level,
        "file_count": len(files),
    }


def scan_secrets(files: list[str]) -> dict:
    """
    掃描修改的文件中是否有洩漏的密鑰或個人路徑。
    
    Returns:
        {"clean": bool, "violations": list[dict]}
    """
    violations = []
    
    for f in files:
        filepath = PROJECT_ROOT / f
        if not filepath.exists() or filepath.suffix in (".db", ".sqlite", ".pyc", ".pyo"):
            continue
        
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        
        for i, line in enumerate(content.splitlines(), 1):
            for pattern in SECRET_PATTERNS:
                if re.search(pattern, line):
                    # 排除 .env.example 和 CONTRIBUTING.md 本身的範例
                    if f in (".env.example", "CONTRIBUTING.md", "ops/commit_guard.py"):
                        continue
                    violations.append({
                        "file": f,
                        "line": i,
                        "pattern": pattern,
                        "preview": line[:80].strip(),
                    })
    
    return {
        "clean": len(violations) == 0,
        "violations": violations,
    }


def check_required_updates(files: list[str], commit_type: str) -> dict:
    """
    檢查是否有必須同步更新的文件。
    例如：feat 類型的 commit 必須更新 TOOLS.md
    
    Returns:
        {"valid": bool, "missing": list[str]}
    """
    missing = []
    
    # feat/fix 類型需要更新 CHANGELOG（版本發佈時）
    if commit_type in ("feat", "feat!"):
        if "TOOLS.md" not in files:
            missing.append("TOOLS.md — 新功能需同步更新工具文檔")
    
    # 修改 skills/ 或 ops/ 需要更新 TOOLS.md
    skill_changed = any(f.startswith("skills/") and f.endswith(".py") for f in files)
    ops_changed = any(f.startswith("ops/") and f.endswith(".py") for f in files)
    if (skill_changed or ops_changed) and "TOOLS.md" not in files:
        missing.append("TOOLS.md — 技能/運維模組修改需同步更新文檔")
    
    return {
        "valid": len(missing) == 0,
        "missing": missing,
    }


def full_validate(commit_message: str, agent: str = "unknown") -> dict:
    """
    完整驗證：commit message + 文件變更 + 密鑰掃描 + 必要更新檢查。
    
    Returns:
        {
            "passed": bool,
            "commit": {...},
            "files": {...},
            "secrets": {...},
            "required_updates": {...},
            "summary": str,
        }
    """
    # 取得 staged files
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=5
        )
        staged_files = [f for f in result.stdout.strip().splitlines() if f]
    except Exception:
        staged_files = []
    
    commit_check = validate_commit_message(commit_message)
    files_check = validate_changed_files(staged_files, agent)
    secrets_check = scan_secrets(staged_files)
    
    # 提取 commit type
    type_match = re.match(r"^([a-z!]+)", commit_message)
    commit_type = type_match.group(1) if type_match else ""
    required_check = check_required_updates(staged_files, commit_type)
    
    passed = (
        commit_check["valid"]
        and files_check["valid"]
        and secrets_check["clean"]
    )
    
    # 生成摘要
    parts = []
    if not commit_check["valid"]:
        parts.append(f"❌ Commit 格式錯誤 ({len(commit_check['errors'])})")
    if not files_check["valid"]:
        parts.append(f"❌ 文件權限違規 ({len(files_check['errors'])})")
    if not secrets_check["clean"]:
        parts.append(f"🔴 密鑰洩漏 ({len(secrets_check['violations'])})")
    if not required_check["valid"]:
        parts.append(f"⚠️ 缺少必要更新 ({len(required_check['missing'])})")
    
    if commit_check.get("warnings") or files_check.get("warnings"):
        total_warnings = len(commit_check.get("warnings", [])) + len(files_check.get("warnings", []))
        parts.append(f"⚠️ {total_warnings} 個警告")
    
    summary = " | ".join(parts) if parts else "✅ 所有檢查通過"
    
    return {
        "passed": passed,
        "commit": commit_check,
        "files": files_check,
        "secrets": secrets_check,
        "required_updates": required_check,
        "level": files_check.get("level", 0),
        "summary": summary,
        "timestamp": datetime.now().isoformat(),
    }


# ── CLI 入口 ──

def main():
    """用作 git hook: .git/hooks/commit-msg"""
    if len(sys.argv) < 2:
        print("Usage: python commit_guard.py <commit-msg-file>")
        print("       python commit_guard.py --check '<message>'")
        sys.exit(1)
    
    if sys.argv[1] == "--check":
        message = sys.argv[2] if len(sys.argv) > 2 else ""
        agent = sys.argv[3] if len(sys.argv) > 3 else "unknown"
    else:
        msg_file = Path(sys.argv[1])
        message = msg_file.read_text().strip()
        # 從 commit message 的 Agent-By footer 提取 agent 身份
        agent = "unknown"
        for line in message.splitlines():
            m = re.match(r"Agent-By:\s*(\S+)", line)
            if m:
                agent = m.group(1)
                break
    
    result = full_validate(message, agent)
    
    print(f"\n{'='*50}")
    print(f"  ArcMind Commit Guard — {result['summary']}")
    print(f"{'='*50}")
    
    if result["commit"]["errors"]:
        print("\n❌ Commit Message Errors:")
        for e in result["commit"]["errors"]:
            print(f"  • {e}")
    
    if result["files"]["errors"]:
        print("\n❌ File Permission Errors:")
        for e in result["files"]["errors"]:
            print(f"  • {e}")
    
    if not result["secrets"]["clean"]:
        print("\n🔴 SECRET LEAK DETECTED:")
        for v in result["secrets"]["violations"]:
            print(f"  • {v['file']}:{v['line']} — {v['preview']}")
    
    if result["required_updates"]["missing"]:
        print("\n⚠️ Missing Required Updates:")
        for m in result["required_updates"]["missing"]:
            print(f"  • {m}")
    
    for w in result["commit"].get("warnings", []):
        print(f"\n⚠️ {w}")
    for w in result["files"].get("warnings", []):
        print(f"\n⚠️ {w}")
    
    print(f"\n📊 Update Level: {result['level']}")
    print()
    
    if not result["passed"]:
        print("🚫 COMMIT BLOCKED — 請修正以上錯誤後重試")
        sys.exit(1)
    else:
        print("✅ COMMIT APPROVED")
        sys.exit(0)


if __name__ == "__main__":
    main()
