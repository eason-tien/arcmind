# 迭代追踪系统

## 概述
记录每次修复的内容、时间和结果，用于追踪系统自愈过程。

## 数据库表

### am_iterations
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 主键 |
| iteration_id | TEXT | 迭代唯一ID (如 iter_20260313_001) |
| content | TEXT | 修复内容描述 |
| 发现问题时间 | TEXT | 发现问题的ISO时间 |
| 修复开始时间 | TEXT | 开始修复的ISO时间 |
| 修复完成时间 | TEXT | 修复完成的ISO时间 |
| 修复结果 | TEXT | success/failure/partial_success |
| 涉及文件 | TEXT | 修复涉及的文件路径 |
| 修复人 | TEXT | 修复人 (默认 system) |
| 操作日志 | TEXT | 详细操作日志 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

## API 接口

### 基础 URL
`/api/iterations`

### 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/iterations | 列出所有迭代记录 |
| POST | /api/iterations | 创建新迭代记录 |
| GET | /api/iterations/{id} | 获取单个迭代记录 |
| PUT | /api/iterations/{id} | 更新迭代记录 |
| DELETE | /api/iterations/{id} | 删除迭代记录 |

### 创建示例
```bash
curl -X POST http://localhost:5000/api/iterations \
  -H "Content-Type: application/json" \
  -d '{
    "content": "修复审批门清理问题",
    "result": "success",
    "files": "scripts/approval_gate_cleanup.py",
    "operator": "pm"
  }'
```

## 脚本

### record_iteration.py
记录迭代的脚本模板，支持自动生成迭代ID和时间戳。

```python
from scripts.iteration_tracker.record_iteration import record_fix

# 记录一次修复
record_fix(
    content="修复了Cron服务未启动的问题",
    result="success",
    files=["scripts/check_system.py"],
    operator="pm"
)
```

## 使用场景

1. **系统自愈记录** - 自动记录系统修复过程
2. **审计追踪** - 追踪谁在什么时候做了什么修改
3. **问题分析** - 分析修复成功率、优化方向
