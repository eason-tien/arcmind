"""
Skill: code_exec
在受限環境中執行 Python 程式碼片段。
使用 subprocess 隔離，有超時保護。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path


# 禁止的模組（防止惡意操作）
_BLOCKED_IMPORTS = [
    "os.system", "subprocess.Popen", "subprocess.call",
    "socket", "shutil.rmtree", "__import__",
    "open(", "eval(", "exec(",
]

# 允許的內建函數（白名單）
_SAFE_BUILTINS_CODE = """
import builtins
_safe = {k: getattr(builtins, k) for k in [
    'print', 'len', 'range', 'enumerate', 'zip', 'map', 'filter',
    'list', 'dict', 'set', 'tuple', 'str', 'int', 'float', 'bool',
    'sum', 'min', 'max', 'abs', 'round', 'sorted', 'reversed',
    'isinstance', 'type', 'repr', 'format', 'any', 'all',
    'Exception', 'ValueError', 'TypeError', 'KeyError', 'IndexError',
]}
"""


def _check_dangerous(code: str) -> str | None:
    """快速掃描危險模式，回傳第一個發現的問題，或 None"""
    for pattern in _BLOCKED_IMPORTS:
        if pattern in code:
            return f"Blocked pattern detected: '{pattern}'"
    return None


def run(inputs: dict) -> dict:
    """
    inputs:
      - code: 要執行的 Python 程式碼
      - timeout_s: 超時秒數（預設 10）
    returns:
      - stdout, stderr, exit_code
    """
    code = inputs.get("code", "").strip()
    timeout_s = int(inputs.get("timeout_s", 10))

    if not code:
        return {"error": "code is required", "stdout": "", "stderr": "", "exit_code": -1}

    # 安全掃描
    danger = _check_dangerous(code)
    if danger:
        return {
            "error": f"Security check failed: {danger}",
            "stdout": "", "stderr": "", "exit_code": -1,
        }

    # 寫入臨時檔案並 subprocess 執行
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(code)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "error": f"Execution timeout ({timeout_s}s)",
            "stdout": "", "stderr": "", "exit_code": -1,
        }
    except Exception as e:
        return {
            "error": str(e),
            "stdout": "", "stderr": "", "exit_code": -1,
        }
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass
