#!/usr/bin/env python3
"""
迭代追踪记录器 - 快速记录修复/改进
用法: python3 scripts/auto_repair/record_iteration.py <操作> [参数]
操作:
  start <标题> --desc <描述> --severity <low|medium|high|critical>
  complete <id> --result <success|partial|failed> --detail <详情>
  log <id> <步骤内容>
  list
  show <id>
"""
import sys
import json
import argparse
from datetime import datetime, timezone

sys.path.insert(0, '/Users/eason/Code/arcmind')

from db.v3_schema import IterationRecord_, get_v3_db


def utcnow():
    return datetime.now(timezone.utc)


def start_iteration(title, description='', severity='medium'):
    """开始一个新的迭代记录"""
    db = get_v3_db()
    try:
        record = IterationRecord_(
            title=title,
            description=description,
            issue_found_at=utcnow(),
            fix_started_at=utcnow(),
            severity=severity,
            result='pending'
        )
        db.add(record)
        db.commit()
        print(f"✅ 迭代记录已创建: ID={record.id}, 标题={title}")
        return record.id
    finally:
        db.close()


def complete_iteration(record_id, result, result_detail=''):
    """完成迭代记录"""
    db = get_v3_db()
    try:
        record = db.query(IterationRecord_).filter(IterationRecord_.id == record_id).first()
        if record:
            record.result = result
            record.result_detail = result_detail
            record.fix_completed_at = utcnow()
            db.commit()
            print(f"✅ 迭代 {record_id} 已标记为: {result}")
        else:
            print(f"❌ 未找到迭代 {record_id}")
    finally:
        db.close()


def add_operation_log(record_id, log_entry):
    """添加操作日志"""
    db = get_v3_db()
    try:
        record = db.query(IterationRecord_).filter(IterationRecord_.id == record_id).first()
        if record:
            logs = json.loads(record.operation_log or '[]')
            logs.append({
                'time': utcnow().isoformat(),
                'entry': log_entry
            })
            record.operation_log = json.dumps(logs, ensure_ascii=False)
            db.commit()
            print(f"✅ 已添加日志到迭代 {record_id}")
    finally:
        db.close()


def list_iterations():
    """列出所有迭代记录"""
    db = get_v3_db()
    try:
        records = db.query(IterationRecord_).order_by(IterationRecord_.created_at.desc()).all()
        print(f"\n📋 共 {len(records)} 条迭代记录:\n")
        print(f"{'ID':<4} {'标题':<30} {'状态':<10} {'严重性':<8} {'创建时间'}")
        print("-" * 80)
        for r in records:
            print(f"{r.id:<4} {r.title[:28]:<30} {r.result:<10} {r.severity:<8} {r.created_at}")
    finally:
        db.close()


def show_iteration(record_id):
    """显示迭代详情"""
    db = get_v3_db()
    try:
        record = db.query(IterationRecord_).filter(IterationRecord_.id == record_id).first()
        if not record:
            print(f"❌ 未找到迭代 {record_id}")
            return
        
        print(f"\n{'='*60}")
        print(f"迭代 #{record.id}: {record.title}")
        print(f"{'='*60}")
        print(f"描述: {record.description}")
        print(f"状态: {record.result}")
        print(f"严重性: {record.severity}")
        print(f"类型: {record.iteration_type}")
        print(f"修复人: {record.fixer}")
        print(f"发现时间: {record.issue_found_at}")
        print(f"开始时间: {record.fix_started_at}")
        print(f"完成时间: {record.fix_completed_at}")
        print(f"结果详情: {record.result_detail}")
        print(f"涉及文件: {record.files_involved}")
        
        logs = json.loads(record.operation_log or '[]')
        if logs:
            print(f"\n📝 操作日志 ({len(logs)} 条):")
            for i, log in enumerate(logs, 1):
                print(f"  {i}. [{log['time']}] {log['entry']}")
    finally:
        db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='迭代追踪记录器')
    parser.add_argument('action', choices=['start', 'complete', 'log', 'list', 'show'])
    parser.add_argument('params', nargs='*', help='参数')
    parser.add_argument('--desc', '--description', dest='description', default='')
    parser.add_argument('--severity', default='medium')
    parser.add_argument('--result', default='success')
    parser.add_argument('--detail', '--result_detail', dest='result_detail', default='')
    
    args = parser.parse_args()
    
    if args.action == 'start':
        title = args.params[0] if args.params else '未命名迭代'
        start_iteration(title, args.description, args.severity)
    elif args.action == 'complete':
        record_id = int(args.params[0]) if args.params else None
        if not record_id:
            print("❌ 需要指定记录ID")
        else:
            complete_iteration(record_id, args.result, args.result_detail)
    elif args.action == 'log':
        record_id = int(args.params[0]) if args.params else None
        log_entry = ' '.join(args.params[1:]) if len(args.params) > 1 else ''
        if not record_id or not log_entry:
            print("❌ 需要指定记录ID和日志内容")
        else:
            add_operation_log(record_id, log_entry)
    elif args.action == 'list':
        list_iterations()
    elif args.action == 'show':
        record_id = int(args.params[0]) if args.params else None
        if not record_id:
            print("❌ 需要指定记录ID")
        else:
            show_iteration(record_id)
