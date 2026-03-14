#!/usr/bin/env python3
"""
迭代追踪脚本模板
用于记录修复操作到迭代追踪系统

用法:
    python3 record_iteration.py --content "修复了数据库连接问题" --result success --files "db/connection.py,config/db.yaml"
    python3 record_iteration.py --list  # 列出最近记录
"""

import argparse
import json
import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

# 配置
DB_PATH = os.environ.get('ARCMIND_DB_PATH', '/Users/eason/Code/arcmind/db/arcmind.db')


def init_db():
    """初始化迭代追踪表"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS am_iterations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            iteration_id TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            发现问题时间 TEXT,
            修复开始时间 TEXT,
            修复完成时间 TEXT,
            修复结果 TEXT CHECK(修复结果 IN ('success', 'failure', 'partial_success')),
            涉及文件 TEXT,
            修复人 TEXT DEFAULT 'system',
            操作日志 TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.commit()
    conn.close()


def generate_iteration_id() -> str:
    """生成迭代ID"""
    now = datetime.now()
    return f"ITER-{now.strftime('%Y%m%d')}-{now.strftime('%H%M%S')}"


def record_iteration(
    content: str,
    发现问题时间: str = None,
    修复开始时间: str = None,
    修复完成时间: str = None,
    修复结果: str = 'success',
    涉及文件: str = '',
    修复人: str = 'system',
    操作日志: str = ''
) -> dict:
    """记录迭代到数据库"""
    
    init_db()
    
    iteration_id = generate_iteration_id()
    now = datetime.now().isoformat()
    
    if not 修复开始时间:
        修复开始时间 = now
    if not 修复完成时间:
        修复完成时间 = now
    if not 发现问题时间:
        发现问题时间 = now
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO am_iterations (
                iteration_id, content, 发现问题时间, 修复开始时间, 
                修复完成时间, 修复结果, 涉及文件, 修复人, 操作日志
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            iteration_id, content, 发现问题时间, 修复开始时间,
            修复完成时间, 修复结果, 涉及文件, 修复人, 操作日志
        ))
        
        conn.commit()
        
        return {
            "status": "success",
            "iteration_id": iteration_id,
            "message": "迭代记录已保存"
        }
        
    except Exception as e:
        conn.rollback()
        return {
            "status": "error",
            "message": str(e)
        }
    finally:
        conn.close()


def list_iterations(limit: int = 20) -> list:
    """列出最近的迭代记录"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM am_iterations 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]


def main():
    parser = argparse.ArgumentParser(description='迭代追踪记录工具')
    parser.add_argument('--content', '-c', help='修复内容描述')
    parser.add_argument('--problem-time', '-pt', help='发现问题时间 (ISO格式)')
    parser.add_argument('--start-time', '-st', help='修复开始时间 (ISO格式)')
    parser.add_argument('--end-time', '-et', help='修复完成时间 (ISO格式)')
    parser.add_argument('--result', '-r', choices=['success', 'failure', 'partial_success'], 
                        default='success', help='修复结果')
    parser.add_argument('--files', '-f', help='涉及文件 (逗号分隔)')
    parser.add_argument('--operator', '-o', default='system', help='修复人')
    parser.add_argument('--log', help='操作日志')
    parser.add_argument('--list', dest='list_mode', action='store_true', 
                        help='列出最近迭代记录')
    parser.add_argument('--limit', type=int, default=20, help='列出记录数量')
    
    args = parser.parse_args()
    
    # 列出模式
    if args.list_mode:
        init_db()
        iterations = list_iterations(args.limit)
        print(json.dumps(iterations, indent=2, ensure_ascii=False))
        return
    
    # 记录模式
    if not args.content:
        parser.error("--content 是必填项")
    
    result = record_iteration(
        content=args.content,
        发现问题时间=args.problem_time,
        修复开始时间=args.start_time,
        修复完成时间=args.end_time,
        修复结果=args.result,
        涉及文件=args.files or '',
        修复人=args.operator,
        操作日志=args.log or ''
    )
    
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    sys.exit(0 if result['status'] == 'success' else 1)


if __name__ == '__main__':
    main()
