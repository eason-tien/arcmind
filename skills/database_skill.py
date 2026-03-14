"""
Skill: database_skill
通用 SQL 查詢 — 支援 SQLite / PostgreSQL / MySQL

連線方式:
- SQLite: db_path 參數直接指定檔案路徑
- PostgreSQL/MySQL: DATABASE_URL 環境變數或參數
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger("arcmind.skill.database")

_MAX_ROWS = 500
_MAX_CELL_LEN = 1000


def _query_sqlite(inputs: dict) -> dict:
    """Run SQL on a SQLite database."""
    db_path = inputs.get("db_path", "")
    sql = inputs.get("sql", "")
    params = inputs.get("params", [])

    if not db_path:
        return {"success": False, "error": "db_path 為必填"}
    p = Path(db_path).expanduser()
    if not p.exists():
        return {"success": False, "error": f"資料庫不存在: {db_path}"}

    conn = sqlite3.connect(str(p))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(sql, params)
        if sql.strip().upper().startswith("SELECT") or sql.strip().upper().startswith("PRAGMA"):
            rows = cur.fetchmany(_MAX_ROWS)
            columns = [d[0] for d in cur.description] if cur.description else []
            data = [
                {col: (str(row[col])[:_MAX_CELL_LEN] if row[col] is not None else None) for col in columns}
                for row in rows
            ]
            return {"success": True, "columns": columns, "rows": data, "count": len(data)}
        else:
            conn.commit()
            return {"success": True, "affected_rows": cur.rowcount}
    finally:
        conn.close()


def _query_url(inputs: dict) -> dict:
    """Run SQL using a DATABASE_URL connection string."""
    url = inputs.get("database_url", os.environ.get("DATABASE_URL", ""))
    sql = inputs.get("sql", "")
    params = inputs.get("params", [])

    if not url:
        return {"success": False, "error": "database_url 或 DATABASE_URL 環境變數為必填"}

    try:
        import sqlalchemy
        engine = sqlalchemy.create_engine(url)
        with engine.connect() as conn:
            result = conn.execute(sqlalchemy.text(sql), dict(enumerate(params)) if params else {})
            if result.returns_rows:
                columns = list(result.keys())
                rows = [
                    {col: (str(val)[:_MAX_CELL_LEN] if val is not None else None) for col, val in zip(columns, row)}
                    for row in result.fetchmany(_MAX_ROWS)
                ]
                return {"success": True, "columns": columns, "rows": rows, "count": len(rows)}
            else:
                conn.commit()
                return {"success": True, "affected_rows": result.rowcount}
    except ImportError:
        return {"success": False, "error": "需要安裝 sqlalchemy: pip install sqlalchemy"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _list_tables(inputs: dict) -> dict:
    """List tables in a database."""
    db_path = inputs.get("db_path", "")
    database_url = inputs.get("database_url", os.environ.get("DATABASE_URL", ""))

    if db_path:
        return _query_sqlite({"db_path": db_path, "sql": "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"})
    elif database_url:
        # Auto-detect dialect
        if "postgresql" in database_url or "postgres" in database_url:
            sql = "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        elif "mysql" in database_url:
            sql = "SHOW TABLES"
        else:
            sql = "SELECT name FROM sqlite_master WHERE type='table'"
        return _query_url({"database_url": database_url, "sql": sql})
    else:
        return {"success": False, "error": "db_path 或 database_url 為必填"}


def _describe_table(inputs: dict) -> dict:
    """Describe a table's schema."""
    table = inputs.get("table", "")
    db_path = inputs.get("db_path", "")

    if not table:
        return {"success": False, "error": "table 為必填"}

    if db_path:
        return _query_sqlite({"db_path": db_path, "sql": f"PRAGMA table_info({table})"})
    else:
        database_url = inputs.get("database_url", os.environ.get("DATABASE_URL", ""))
        sql = f"SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name='{table}'"
        return _query_url({"database_url": database_url, "sql": sql})


def run(inputs: dict) -> dict:
    """
    Database skill entry point.
    action: query | list_tables | describe_table
    db_path: SQLite 路徑 | database_url: 連線字串
    sql: SQL 語句 (query)
    """
    action = inputs.get("action", "query")
    handlers = {
        "query": lambda i: _query_sqlite(i) if i.get("db_path") else _query_url(i),
        "list_tables": _list_tables,
        "describe_table": _describe_table,
    }
    handler = handlers.get(action)
    if not handler:
        return {"success": False, "error": f"未知 action: {action}", "available_actions": list(handlers.keys())}
    try:
        sql = inputs.get("sql", "")
        if sql and any(kw in sql.upper() for kw in ["DROP ", "TRUNCATE ", "ALTER "]):
            return {"success": False, "error": "危險操作被攔截（DROP/TRUNCATE/ALTER）。使用 force=true 覆蓋。"}
        return handler(inputs)
    except Exception as e:
        logger.error("[database] %s failed: %s", action, e)
        return {"success": False, "error": str(e), "action": action}
