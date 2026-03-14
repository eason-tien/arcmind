"""
迭代追踪 API 接口
"""

from flask import Blueprint, jsonify, request
from datetime import datetime
import sqlite3
import os

DB_PATH = os.environ.get('ARCMIND_DB_PATH', '/Users/eason/Code/arcmind/db/arcmind.db')

iteration_bp = Blueprint('iteration', __name__, url_prefix='/api/iterations')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@iteration_bp.route('', methods=['GET'])
def list_iterations():
    """列出所有迭代记录"""
    limit = request.args.get('limit', 20, type=int)
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM am_iterations 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return jsonify([dict(row) for row in rows])


@iteration_bp.route('', methods=['POST'])
def create_iteration():
    """创建新迭代记录"""
    data = request.get_json()
    
    required = ['content']
    if not all(k in data for k in required):
        return jsonify({"error": "缺少必填字段: content"}), 400
    
    from scripts.iteration_tracker.record_iteration import (
        generate_iteration_id, init_db
    )
    
    init_db()
    
    iteration_id = generate_iteration_id()
    now = datetime.now().isoformat()
    
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO am_iterations (
                iteration_id, content, 发现问题时间, 修复开始时间,
                修复完成时间, 修复结果, 涉及文件, 修复人, 操作日志
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            iteration_id,
            data.get('content', ''),
            data.get('problem_time', now),
            data.get('start_time', now),
            data.get('end_time', now),
            data.get('result', 'success'),
            data.get('files', ''),
            data.get('operator', 'system'),
            data.get('log', '')
        ))
        
        conn.commit()
        
        return jsonify({
            "status": "success",
            "iteration_id": iteration_id
        }), 201
        
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@iteration_bp.route('/<iteration_id>', methods=['GET'])
def get_iteration(iteration_id):
    """获取单个迭代记录"""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM am_iterations WHERE iteration_id = ?", (iteration_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return jsonify({"error": "记录不存在"}), 404
    
    return jsonify(dict(row))


@iteration_bp.route('/<iteration_id>', methods=['PUT'])
def update_iteration(iteration_id):
    """更新迭代记录"""
    data = request.get_json()
    
    conn = get_db()
    cursor = conn.cursor()
    
    fields = []
    values = []
    
    for field in ['content', 'result', 'files', 'operator', 'log']:
        if field in data:
            fields.append(f"{field} = ?")
            values.append(data[field])
    
    if not fields:
        return jsonify({"error": "没有要更新的字段"}), 400
    
    fields.append("updated_at = CURRENT_TIMESTAMP")
    values.append(iteration_id)
    
    try:
        cursor.execute(f"""
            UPDATE am_iterations 
            SET {', '.join(fields)}
            WHERE iteration_id = ?
        """, values)
        
        conn.commit()
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@iteration_bp.route('/<iteration_id>', methods=['DELETE'])
def delete_iteration(iteration_id):
    """删除迭代记录"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM am_iterations WHERE iteration_id = ?", (iteration_id,))
        conn.commit()
        
        return jsonify({"status": "success"})
        
    except Exception as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


# 注册蓝图时需要添加到主 API
# from api.iterations import iteration_bp
# app.register_blueprint(iteration_bp)
