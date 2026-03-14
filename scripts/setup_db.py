import sqlite3

conn = sqlite3.connect('/Users/eason/Code/arcmind/data/arcmind.db')
cursor = conn.cursor()

# 创建错误记录表
cursor.execute('''
CREATE TABLE IF NOT EXISTS am_error_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    error_type TEXT NOT NULL,
    error_message TEXT,
    source_component TEXT,
    severity TEXT DEFAULT 'info',
    occurred_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    status TEXT DEFAULT 'pending'
)
''')

# 创建通知记录表
cursor.execute('''
CREATE TABLE IF NOT EXISTS am_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    notification_type TEXT NOT NULL,
    recipient TEXT,
    message TEXT,
    status TEXT DEFAULT 'sent',
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response TEXT
)
''')

# 创建系统健康检查记录表
cursor.execute('''
CREATE TABLE IF NOT EXISTS am_system_health (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_name TEXT NOT NULL,
    status TEXT,
    details TEXT,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()

# 验证表已创建
cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'am_%'")
tables = cursor.fetchall()
print("已创建/现有的表:")
for t in tables:
    print(f"  ✓ {t[0]}")

conn.close()
print("\n✅ 数据库结构更新完成")
