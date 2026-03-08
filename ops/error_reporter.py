"""
ArcMind Error Reporter
自動向 GitHub Issues 回報運行時錯誤。
"""
import os
import json
import logging
import traceback
import subprocess
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("arcmind.error_reporter")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = PROJECT_ROOT / "VERSION"
GITHUB_REPO = "eason-tien/arcmind"
REPORT_LOG = PROJECT_ROOT / "logs" / "error_reports.jsonl"


def _get_version() -> str:
    try:
        return (PROJECT_ROOT / "VERSION").read_text().strip()
    except Exception:
        return "unknown"


def _get_github_token() -> str | None:
    """從 .env 或環境變數取得 GitHub token"""
    token = os.getenv("GITHUB_TOKEN", "")
    if token:
        return token
    
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GITHUB_TOKEN="):
                return line.split("=", 1)[1].strip()
    return None


def report_error(
    title: str,
    error: Exception | str,
    context: dict | None = None,
    component: str = "unknown",
    severity: str = "medium",
) -> dict:
    """
    回報錯誤到 GitHub Issues。
    
    Args:
        title: 問題標題
        error: 異常或錯誤訊息
        context: 額外上下文
        component: 出錯的模組名稱
        severity: low / medium / high / critical
    
    Returns:
        {"success": bool, "issue_url": str | None, "issue_number": int | None}
    """
    version = _get_version()
    timestamp = datetime.now().isoformat()
    
    # 取得堆疊追蹤
    if isinstance(error, Exception):
        tb = traceback.format_exception(type(error), error, error.__traceback__)
        error_str = "".join(tb)
        error_type = type(error).__name__
    else:
        error_str = str(error)
        error_type = "Error"
    
    # 構建 Issue body
    body = f"""## 🔴 Runtime Error Report

**Version:** `{version}`
**Component:** `{component}`
**Severity:** `{severity}`
**Timestamp:** `{timestamp}`
**Environment:** `{os.getenv('ARCMIND_ENV', 'unknown')}`

### Error
```
{error_type}: {str(error)[:200]}
```

### Stack Trace
```python
{error_str[:2000]}
```
"""
    
    if context:
        ctx_str = json.dumps(context, ensure_ascii=False, indent=2, default=str)[:1000]
        body += f"\n### Context\n```json\n{ctx_str}\n```\n"
    
    body += f"\n---\n*Auto-reported by ArcMind Error Reporter v{version}*"
    
    # 記錄到本地日誌
    report = {
        "ts": timestamp, "title": title, "component": component,
        "severity": severity, "error": str(error)[:500], "version": version,
    }
    try:
        REPORT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(REPORT_LOG, "a") as f:
            f.write(json.dumps(report, ensure_ascii=False) + "\n")
    except Exception:
        pass
    
    # 發送到 GitHub Issues
    token = _get_github_token()
    if not token:
        logger.warning("[ErrorReporter] No GITHUB_TOKEN, error logged locally only")
        return {"success": False, "message": "No GITHUB_TOKEN configured", "logged_locally": True}
    
    severity_labels = {
        "critical": ["bug", "critical", "auto-report"],
        "high": ["bug", "high-priority", "auto-report"],
        "medium": ["bug", "auto-report"],
        "low": ["bug", "low-priority", "auto-report"],
    }
    labels = severity_labels.get(severity, ["bug", "auto-report"])
    
    payload = json.dumps({
        "title": f"🔴 [{severity.upper()}] {title}",
        "body": body,
        "labels": labels,
    })
    
    try:
        result = subprocess.run(
            ["curl", "-s", "-X", "POST",
             f"https://api.github.com/repos/{GITHUB_REPO}/issues",
             "-H", f"Authorization: Bearer {token}",
             "-H", "Accept: application/vnd.github.v3+json",
             "-d", payload],
            capture_output=True, text=True, timeout=15
        )
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            issue_url = data.get("html_url")
            issue_number = data.get("number")
            
            if issue_url:
                logger.info(f"[ErrorReporter] Issue #{issue_number} created: {issue_url}")
                return {"success": True, "issue_url": issue_url, "issue_number": issue_number}
            else:
                error_msg = data.get("message", "Unknown error")
                logger.warning(f"[ErrorReporter] GitHub API error: {error_msg}")
                return {"success": False, "message": error_msg, "logged_locally": True}
        
    except Exception as e:
        logger.warning(f"[ErrorReporter] Failed to create issue: {e}")
    
    return {"success": False, "message": "Failed to create GitHub issue", "logged_locally": True}


# 裝飾器：自動回報未捕獲的異常
def auto_report(component: str = "unknown", severity: str = "medium"):
    """裝飾器：自動回報函數中的異常"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                report_error(
                    title=f"{component}: {type(e).__name__} in {func.__name__}",
                    error=e,
                    context={"args_count": len(args), "kwargs_keys": list(kwargs.keys())},
                    component=component,
                    severity=severity,
                )
                raise  # 繼續拋出異常
        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        return wrapper
    return decorator


# Tool 介面
def run(inputs: dict) -> dict:
    """
    Error reporter tool interface.
    
    inputs:
      - action: "report" | "list" | "stats"
      - title: (report) 問題標題
      - error: (report) 錯誤訊息
      - component: (report) 模組名稱
      - severity: (report) low/medium/high/critical
    """
    action = inputs.get("action", "report")
    
    if action == "report":
        return report_error(
            title=inputs.get("title", "Manual Error Report"),
            error=inputs.get("error", "No error details"),
            context=inputs.get("context"),
            component=inputs.get("component", "manual"),
            severity=inputs.get("severity", "medium"),
        )
    elif action == "list":
        # 列出最近的錯誤報告
        try:
            if REPORT_LOG.exists():
                lines = REPORT_LOG.read_text().strip().splitlines()
                recent = [json.loads(l) for l in lines[-10:]]
                return {"reports": recent, "total": len(lines)}
        except Exception:
            pass
        return {"reports": [], "total": 0}
    elif action == "stats":
        try:
            if REPORT_LOG.exists():
                lines = REPORT_LOG.read_text().strip().splitlines()
                reports = [json.loads(l) for l in lines]
                by_severity = {}
                by_component = {}
                for r in reports:
                    by_severity[r.get("severity", "?")] = by_severity.get(r.get("severity", "?"), 0) + 1
                    by_component[r.get("component", "?")] = by_component.get(r.get("component", "?"), 0) + 1
                return {"total": len(reports), "by_severity": by_severity, "by_component": by_component}
        except Exception:
            pass
        return {"total": 0}
    else:
        return {"error": f"Unknown action: {action}"}
