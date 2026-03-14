"""
Iteration Tracker API — 迭代追踪系统 CRUD 接口
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


# ── Request Models ──────────────────────────────────────────────────────────

class CreateIterationRequest(BaseModel):
    title: str
    description: str = ""
    issue_found_at: Optional[str] = None
    files_involved: List[str] = []
    fixer: str = "system"
    iteration_type: str = "fix"           # fix|improvement|feature
    severity: str = "medium"               # low|medium|high|critical
    tags: List[str] = []


class UpdateIterationRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    fix_started_at: Optional[str] = None
    fix_completed_at: Optional[str] = None
    result: Optional[str] = None           # pending|success|partial|failed
    result_detail: Optional[str] = None
    files_involved: Optional[List[str]] = None
    operation_log: Optional[List[dict]] = None
    tags: Optional[List[str]] = None


class AddLogEntryRequest(BaseModel):
    step: str
    message: str
    status: str = "running"                # running|success|failed|skipped


# ── Helper Functions ─────────────────────────────────────────────────────────

def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _to_json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _from_json(s: str):
    if not s:
        return []
    try:
        return json.loads(s)
    except Exception:
        return []


# ── CRUD Endpoints ───────────────────────────────────────────────────────────

@router.get("/iterations")
def list_iterations(
    limit: int = 50,
    offset: int = 0,
    result: Optional[str] = None,
    fixer: Optional[str] = None,
):
    """列出所有迭代记录"""
    from db.v3_schema import get_v3_db, IterationRecord_
    
    db = get_v3_db()
    try:
        query = db.query(IterationRecord_)
        
        if result:
            query = query.filter(IterationRecord_.result == result)
        if fixer:
            query = query.filter(IterationRecord_.fixer == fixer)
        
        total = query.count()
        records = query.order_by(IterationRecord_.created_at.desc()) \
            .offset(offset).limit(limit).all()
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "iterations": [
                {
                    "id": r.id,
                    "title": r.title,
                    "description": r.description,
                    "issue_found_at": r.issue_found_at.isoformat() if r.issue_found_at else None,
                    "fix_started_at": r.fix_started_at.isoformat() if r.fix_started_at else None,
                    "fix_completed_at": r.fix_completed_at.isoformat() if r.fix_completed_at else None,
                    "result": r.result,
                    "result_detail": r.result_detail,
                    "files_involved": _from_json(r.files_involved),
                    "fixer": r.fixer,
                    "operation_log": _from_json(r.operation_log),
                    "iteration_type": r.iteration_type,
                    "severity": r.severity,
                    "tags": _from_json(r.tags),
                    "created_at": r.created_at.isoformat(),
                }
                for r in records
            ]
        }
    finally:
        db.close()


@router.get("/iterations/{iteration_id}")
def get_iteration(iteration_id: int):
    """获取单条迭代记录详情"""
    from db.v3_schema import get_v3_db, IterationRecord_
    
    db = get_v3_db()
    try:
        r = db.query(IterationRecord_).filter(IterationRecord_.id == iteration_id).first()
        if not r:
            raise HTTPException(404, f"Iteration {iteration_id} not found")
        
        return {
            "id": r.id,
            "title": r.title,
            "description": r.description,
            "issue_found_at": r.issue_found_at.isoformat() if r.issue_found_at else None,
            "fix_started_at": r.fix_started_at.isoformat() if r.fix_started_at else None,
            "fix_completed_at": r.fix_completed_at.isoformat() if r.fix_completed_at else None,
            "result": r.result,
            "result_detail": r.result_detail,
            "files_involved": _from_json(r.files_involved),
            "fixer": r.fixer,
            "operation_log": _from_json(r.operation_log),
            "iteration_type": r.iteration_type,
            "severity": r.severity,
            "tags": _from_json(r.tags),
            "created_at": r.created_at.isoformat(),
            "updated_at": r.updated_at.isoformat(),
        }
    finally:
        db.close()


@router.post("/iterations")
def create_iteration(req: CreateIterationRequest):
    """创建新的迭代记录"""
    from db.v3_schema import get_v3_db, IterationRecord_
    
    db = get_v3_db()
    try:
        record = IterationRecord_(
            title=req.title,
            description=req.description,
            issue_found_at=_parse_dt(req.issue_found_at) if req.issue_found_at else datetime.utcnow(),
            fix_started_at=None,
            fix_completed_at=None,
            result="pending",
            files_involved=_to_json(req.files_involved),
            fixer=req.fixer,
            iteration_type=req.iteration_type,
            severity=req.severity,
            tags=_to_json(req.tags),
            operation_log="[]",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        
        return {
            "id": record.id,
            "title": record.title,
            "status": "created",
            "result": record.result,
        }
    finally:
        db.close()


@router.patch("/iterations/{iteration_id}")
def update_iteration(iteration_id: int, req: UpdateIterationRequest):
    """更新迭代记录"""
    from db.v3_schema import get_v3_db, IterationRecord_
    
    db = get_v3_db()
    try:
        r = db.query(IterationRecord_).filter(IterationRecord_.id == iteration_id).first()
        if not r:
            raise HTTPException(404, f"Iteration {iteration_id} not found")
        
        if req.title is not None:
            r.title = req.title
        if req.description is not None:
            r.description = req.description
        if req.fix_started_at is not None:
            r.fix_started_at = _parse_dt(req.fix_started_at)
        if req.fix_completed_at is not None:
            r.fix_completed_at = _parse_dt(req.fix_completed_at)
        if req.result is not None:
            r.result = req.result
        if req.result_detail is not None:
            r.result_detail = req.result_detail
        if req.files_involved is not None:
            r.files_involved = _to_json(req.files_involved)
        if req.operation_log is not None:
            r.operation_log = _to_json(req.operation_log)
        if req.tags is not None:
            r.tags = _to_json(req.tags)
        
        db.commit()
        return {"updated": iteration_id, "result": r.result}
    finally:
        db.close()


@router.post("/iterations/{iteration_id}/start")
def start_iteration(iteration_id: int):
    """开始修复 — 记录开始时间"""
    from db.v3_schema import get_v3_db, IterationRecord_
    
    db = get_v3_db()
    try:
        r = db.query(IterationRecord_).filter(IterationRecord_.id == iteration_id).first()
        if not r:
            raise HTTPException(404, f"Iteration {iteration_id} not found")
        
        r.fix_started_at = datetime.utcnow()
        r.result = "running"
        
        # 添加日志
        logs = _from_json(r.operation_log)
        logs.append({
            "step": "start",
            "message": "修复开始",
            "timestamp": datetime.utcnow().isoformat(),
            "status": "running"
        })
        r.operation_log = _to_json(logs)
        
        db.commit()
        return {"started": iteration_id, "fix_started_at": r.fix_started_at.isoformat()}
    finally:
        db.close()


@router.post("/iterations/{iteration_id}/complete")
def complete_iteration(
    iteration_id: int,
    result: str = "success",
    result_detail: str = "",
):
    """完成修复 — 记录完成时间和结果"""
    from db.v3_schema import get_v3_db, IterationRecord_
    
    db = get_v3_db()
    try:
        r = db.query(IterationRecord_).filter(IterationRecord_.id == iteration_id).first()
        if not r:
            raise HTTPException(404, f"Iteration {iteration_id} not found")
        
        r.fix_completed_at = datetime.utcnow()
        r.result = result
        r.result_detail = result_detail
        
        # 添加日志
        logs = _from_json(r.operation_log)
        logs.append({
            "step": "complete",
            "message": f"修复完成，结果: {result}",
            "timestamp": datetime.utcnow().isoformat(),
            "status": result
        })
        r.operation_log = _to_json(logs)
        
        db.commit()
        return {
            "completed": iteration_id,
            "result": result,
            "fix_completed_at": r.fix_completed_at.isoformat()
        }
    finally:
        db.close()


@router.post("/iterations/{iteration_id}/log")
def add_log_entry(iteration_id: int, req: AddLogEntryRequest):
    """添加操作日志条目"""
    from db.v3_schema import get_v3_db, IterationRecord_
    
    db = get_v3_db()
    try:
        r = db.query(IterationRecord_).filter(IterationRecord_.id == iteration_id).first()
        if not r:
            raise HTTPException(404, f"Iteration {iteration_id} not found")
        
        logs = _from_json(r.operation_log)
        logs.append({
            "step": req.step,
            "message": req.message,
            "timestamp": datetime.utcnow().isoformat(),
            "status": req.status
        })
        r.operation_log = _to_json(logs)
        
        db.commit()
        return {"added": iteration_id, "log_count": len(logs)}
    finally:
        db.close()


@router.delete("/iterations/{iteration_id}")
def delete_iteration(iteration_id: int):
    """删除迭代记录"""
    from db.v3_schema import get_v3_db, IterationRecord_
    
    db = get_v3_db()
    try:
        r = db.query(IterationRecord_).filter(IterationRecord_.id == iteration_id).first()
        if not r:
            raise HTTPException(404, f"Iteration {iteration_id} not found")
        
        db.delete(r)
        db.commit()
        return {"deleted": iteration_id}
    finally:
        db.close()


@router.get("/iterations/stats/summary")
def get_iteration_stats():
    """获取迭代统计摘要"""
    from db.v3_schema import get_v3_db, IterationRecord_
    
    db = get_v3_db()
    try:
        total = db.query(IterationRecord_).count()
        
        success = db.query(IterationRecord_).filter(IterationRecord_.result == "success").count()
        partial = db.query(IterationRecord_).filter(IterationRecord_.result == "partial").count()
        failed = db.query(IterationRecord_).filter(IterationRecord_.result == "failed").count()
        pending = db.query(IterationRecord_).filter(IterationRecord_.result == "pending").count()
        running = db.query(IterationRecord_).filter(IterationRecord_.result == "running").count()
        
        # 按类型统计
        fix_count = db.query(IterationRecord_).filter(IterationRecord_.iteration_type == "fix").count()
        improvement_count = db.query(IterationRecord_).filter(IterationRecord_.iteration_type == "improvement").count()
        
        # 按严重程度统计
        critical = db.query(IterationRecord_).filter(IterationRecord_.severity == "critical").count()
        high = db.query(IterationRecord_).filter(IterationRecord_.severity == "high").count()
        
        return {
            "total": total,
            "by_result": {
                "success": success,
                "partial": partial,
                "failed": failed,
                "pending": pending,
                "running": running
            },
            "by_type": {
                "fix": fix_count,
                "improvement": improvement_count
            },
            "by_severity": {
                "critical": critical,
                "high": high
            },
            "success_rate": round(success / total * 100, 1) if total > 0 else 0
        }
    finally:
        db.close()
