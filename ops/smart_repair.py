"""
ArcMind — Smart Repair (自學習修復引擎)
========================================
當 repair_agent 的本地 6 項靜態檢查無法解決問題時：
1. 解析 error log 提取真正的錯誤訊息
2. 先查詢本地「解決方案記憶庫」是否有已知修復
3. 若無→用 web_search 搜尋解決方案
4. 分析搜尋結果，嘗試自動修復
5. 將成功的修復方案存入記憶庫（下次直接使用）

由 watchdog.py 在 repair_agent 無法修復時調用。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("arcmind.smart_repair")

_ARCMIND_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_ERR_LOG = _ARCMIND_DIR / "logs" / "arcmind_err.log"
_SOLUTION_DB = _ARCMIND_DIR / "data" / "repair_solutions.jsonl"
_REPAIR_LOG = _ARCMIND_DIR / "logs" / "smart_repair.log"
_PIP = str(_ARCMIND_DIR / ".venv" / "bin" / "pip")
_PYTHON = str(_ARCMIND_DIR / ".venv" / "bin" / "python")


# ── 1. 錯誤解析 ──────────────────────────────────────────────

def parse_error(err_log_path: Path = _ERR_LOG) -> dict | None:
    """
    解析 stderr log，提取最後一個真正的 Python 錯誤。
    
    Returns:
        {
            "error_type": "ValidationError",
            "error_message": "3 validation errors for Settings ...",
            "full_traceback": "...",
            "module": "pydantic_core",
            "search_query": "pydantic ValidationError Settings field",
        }
    """
    if not err_log_path.exists():
        return None
    
    content = err_log_path.read_text(encoding="utf-8", errors="replace")
    lines = content.strip().split("\n")[-50:]  # 最後 50 行
    
    # 過濾正常行
    benign = ["INFO:", "Uvicorn running", "Started server", "startup complete",
              "CTRL+C", "HTTP Request:", "lifespan", "Waiting for"]
    error_lines = [l for l in lines if not any(b in l for b in benign) and l.strip()]
    
    if not error_lines:
        return None
    
    # 尋找 Traceback 區塊
    traceback_start = None
    error_type = ""
    error_message = ""
    
    for i, line in enumerate(error_lines):
        if "Traceback" in line:
            traceback_start = i
        if re.match(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*Error:", line) or \
           re.match(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*Exception:", line):
            parts = line.split(":", 1)
            error_type = parts[0].strip()
            error_message = parts[1].strip() if len(parts) > 1 else ""
    
    if not error_type:
        # 沒有標準 traceback，取最後一行
        last = error_lines[-1]
        error_type = "UnknownError"
        error_message = last[:200]
    
    # 提取模組名
    module = error_type.split(".")[0] if "." in error_type else ""
    
    # 建構搜尋查詢
    search_query = f"python {error_type}"
    if error_message:
        # 取前幾個關鍵字
        keywords = error_message[:100].split()[:6]
        search_query += " " + " ".join(keywords)
    
    full_tb = "\n".join(error_lines[traceback_start:]) if traceback_start is not None else "\n".join(error_lines[-5:])
    
    return {
        "error_type": error_type,
        "error_message": error_message[:300],
        "full_traceback": full_tb[:1000],
        "module": module,
        "search_query": search_query,
    }


# ── 2. 解決方案記憶庫 ────────────────────────────────────────

def _lookup_known_solution(error_type: str, error_message: str) -> dict | None:
    """查詢本地已知的修復方案"""
    if not _SOLUTION_DB.exists():
        return None
    
    try:
        for line in _SOLUTION_DB.read_text().strip().splitlines():
            solution = json.loads(line)
            # 匹配錯誤類型 + 關鍵字
            if solution.get("error_type") == error_type:
                if solution.get("keyword", "") in error_message:
                    logger.info("[SmartRepair] Found known solution: %s", solution.get("fix_action"))
                    return solution
    except Exception:
        pass
    return None


def _save_solution(error_type: str, keyword: str, fix_action: str, 
                   fix_command: str, success: bool):
    """儲存修復方案到記憶庫"""
    try:
        _SOLUTION_DB.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(),
            "error_type": error_type,
            "keyword": keyword,
            "fix_action": fix_action,
            "fix_command": fix_command,
            "success": success,
            "used_count": 1,
        }
        with open(_SOLUTION_DB, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("[SmartRepair] Saved solution: %s → %s", error_type, fix_action)
    except Exception as e:
        logger.warning("[SmartRepair] Failed to save solution: %s", e)


# ── 3. Web 搜尋修復 ──────────────────────────────────────────

def _web_search(query: str, max_results: int = 5) -> list[dict]:
    """使用 web_search skill 搜尋"""
    try:
        from skills.web_search import run as web_search_run
        result = web_search_run({"query": query, "max_results": max_results})
        return result.get("results", [])
    except Exception as e:
        logger.warning("[SmartRepair] Web search failed: %s", e)
        return []


def _analyze_search_results(error_info: dict, results: list[dict]) -> dict | None:
    """
    分析搜尋結果，提取可行的修復動作。
    
    支援的自動修復模式：
    1. pip install <package>  — 缺少模組
    2. 配置修改建議 — Settings/pydantic 錯誤
    3. 命令執行 — 系統層修復
    """
    error_type = error_info.get("error_type", "")
    error_message = error_info.get("error_message", "")
    
    combined_text = "\n".join(r.get("body", "") for r in results)
    
    # === 模式 1: ModuleNotFoundError → pip install ===
    if "ModuleNotFoundError" in error_type:
        module_match = re.search(r"No module named '(\w+)'", error_message)
        if module_match:
            mod = module_match.group(1)
            return {
                "fix_action": f"pip install {mod}",
                "fix_command": f"{_PIP} install {mod}",
                "fix_type": "pip_install",
                "confidence": 0.9,
                "keyword": mod,
            }
    
    # === 模式 2: ImportError → 搜尋替代安裝名 ===
    if "ImportError" in error_type:
        # 從搜尋結果中找 pip install 建議
        pip_matches = re.findall(r"pip install ([a-zA-Z0-9_-]+)", combined_text)
        if pip_matches:
            pkg = pip_matches[0]
            return {
                "fix_action": f"pip install {pkg} (from web)",
                "fix_command": f"{_PIP} install {pkg}",
                "fix_type": "pip_install",
                "confidence": 0.7,
                "keyword": pkg,
            }
    
    # === 模式 3: ValidationError → 配置檔問題 ===
    if "ValidationError" in error_type:
        # 提取缺少的欄位名
        field_match = re.search(r"(\w+)\n.*field required", error_message, re.IGNORECASE)
        if not field_match:
            field_match = re.search(r"validation errors for (\w+)", error_message)
        
        return {
            "fix_action": f"Configuration validation error in {error_message[:50]}. Needs manual field addition.",
            "fix_command": "",  # 不自動修改配置
            "fix_type": "config_fix",
            "confidence": 0.5,
            "keyword": "ValidationError",
            "web_suggestions": [r.get("body", "")[:200] for r in results[:3]],
        }
    
    # === 模式 4: ConnectionError → 服務未啟動 ===
    if "ConnectionError" in error_type or "ConnectionRefused" in error_message:
        service_match = re.search(r"(localhost|127\.0\.0\.1|192\.\d+\.\d+\.\d+):(\d+)", error_message)
        if service_match:
            host = service_match.group(1)
            port = service_match.group(2)
            return {
                "fix_action": f"Service at {host}:{port} unreachable",
                "fix_command": "",
                "fix_type": "service_check",
                "confidence": 0.6,
                "keyword": f"{host}:{port}",
                "web_suggestions": [r.get("body", "")[:200] for r in results[:3]],
            }
    
    # === 模式 5: 通用 — 提取搜尋結果中的修復建議 ===
    if results:
        return {
            "fix_action": "Web search found suggestions (needs manual review)",
            "fix_command": "",
            "fix_type": "manual",
            "confidence": 0.3,
            "keyword": error_type,
            "web_suggestions": [
                {"title": r.get("title", ""), "body": r.get("body", "")[:200], "url": r.get("href", "")}
                for r in results[:5]
            ],
        }
    
    return None


# ── 4. 自動修復執行 ──────────────────────────────────────────

def _execute_fix(fix: dict) -> bool:
    """執行修復動作"""
    fix_cmd = fix.get("fix_command", "")
    fix_type = fix.get("fix_type", "")
    
    if not fix_cmd:
        logger.info("[SmartRepair] Fix requires manual action: %s", fix.get("fix_action"))
        return False
    
    # 安全檢查：只允許特定修復類型
    safe_types = ["pip_install"]
    if fix_type not in safe_types:
        logger.warning("[SmartRepair] Fix type '%s' not auto-executable", fix_type)
        return False
    
    # 額外安全檢查
    if any(danger in fix_cmd for danger in ["rm ", "sudo", "chmod", "> /", "| sh"]):
        logger.warning("[SmartRepair] Dangerous command blocked: %s", fix_cmd)
        return False
    
    logger.info("[SmartRepair] Executing fix: %s", fix_cmd)
    try:
        result = subprocess.run(
            fix_cmd.split(),
            capture_output=True, text=True, timeout=120,
            cwd=str(_ARCMIND_DIR),
        )
        if result.returncode == 0:
            logger.info("[SmartRepair] Fix succeeded: %s", fix.get("fix_action"))
            return True
        else:
            logger.warning("[SmartRepair] Fix failed: %s", result.stderr[:200])
            return False
    except Exception as e:
        logger.warning("[SmartRepair] Fix execution error: %s", e)
        return False


# ── 5. 主入口 ─────────────────────────────────────────────────

def smart_repair(err_log_path: Path = _ERR_LOG) -> dict:
    """
    智能修復流程：
    1. 解析錯誤 → 2. 查本地記憶 → 3. Web 搜尋 → 4. 嘗試修復 → 5. 學習記錄
    
    Returns:
        {
            "status": "repaired" | "suggestion" | "no_error" | "failed",
            "error": {...},
            "fix": {...},
            "web_searched": bool,
            "learned": bool,
        }
    """
    # 1. 解析錯誤
    error_info = parse_error(err_log_path)
    if not error_info:
        return {"status": "no_error", "message": "stderr 中無真正的錯誤"}
    
    error_type = error_info["error_type"]
    error_message = error_info["error_message"]
    logger.info("[SmartRepair] Detected: %s: %s", error_type, error_message[:100])
    
    # 記錄到修復日誌
    _log_repair_event("detected", error_info)
    
    # 2. 查本地記憶庫
    known = _lookup_known_solution(error_type, error_message)
    if known:
        logger.info("[SmartRepair] Using known solution: %s", known.get("fix_action"))
        fix = {
            "fix_action": known["fix_action"],
            "fix_command": known.get("fix_command", ""),
            "fix_type": known.get("fix_type", ""),
            "confidence": 0.95,
            "source": "memory",
        }
        success = _execute_fix(fix)
        return {
            "status": "repaired" if success else "suggestion",
            "error": error_info,
            "fix": fix,
            "web_searched": False,
            "learned": False,
            "source": "memory",
        }
    
    # 3. Web 搜尋
    logger.info("[SmartRepair] No known solution, searching web: %s", error_info["search_query"])
    search_results = _web_search(error_info["search_query"])
    
    if not search_results:
        logger.warning("[SmartRepair] Web search returned no results")
        _log_repair_event("web_search_empty", error_info)
        return {
            "status": "failed",
            "error": error_info,
            "fix": None,
            "web_searched": True,
            "learned": False,
            "message": "Web 搜尋無結果",
        }
    
    # 4. 分析並嘗試修復
    fix = _analyze_search_results(error_info, search_results)
    if not fix:
        return {
            "status": "failed",
            "error": error_info,
            "fix": None,
            "web_searched": True,
            "learned": False,
            "message": "無法從搜尋結果提取修復方案",
        }
    
    fix["source"] = "web_search"
    success = _execute_fix(fix)
    
    # 5. 學習記錄
    if success:
        keyword = fix.get("keyword", error_type)
        _save_solution(error_type, keyword, fix["fix_action"], 
                      fix.get("fix_command", ""), True)
    
    _log_repair_event("attempted" if success else "suggestion", {
        **error_info,
        "fix": fix,
        "success": success,
        "web_results_count": len(search_results),
    })
    
    return {
        "status": "repaired" if success else "suggestion",
        "error": error_info,
        "fix": fix,
        "web_searched": True,
        "learned": success,
    }


def _log_repair_event(event_type: str, data: dict):
    """記錄修復事件"""
    try:
        _REPAIR_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(),
            "event": event_type,
            **{k: v for k, v in data.items() if isinstance(v, (str, int, float, bool))},
        }
        with open(_REPAIR_LOG, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── CLI 入口 ──────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    result = smart_repair()
    print(f"\n{'='*50}")
    print(f"  Smart Repair: {result['status']}")
    print(f"{'='*50}")
    if result.get("error"):
        print(f"  Error: {result['error']['error_type']}: {result['error']['error_message'][:80]}")
    if result.get("fix"):
        print(f"  Fix: {result['fix'].get('fix_action', 'N/A')}")
        print(f"  Confidence: {result['fix'].get('confidence', 0):.0%}")
        print(f"  Source: {result['fix'].get('source', 'N/A')}")
    print(f"  Web Searched: {result.get('web_searched', False)}")
    print(f"  Learned: {result.get('learned', False)}")
