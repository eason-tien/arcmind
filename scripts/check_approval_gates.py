import sqlite3
import os

db_path = "data/arcmind.db"

# Check if db exists
if os.path.exists(db_path):
    print(f"Database exists: {db_path}")
    print(f"Size: {os.path.getsize(db_path)} bytes")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    print(f"\nTables ({len(tables)}):")
    for t in tables:
        print(f"  - {t[0]}")
    
    # Check for approval_gates table
    approval_tables = [t[0] for t in tables if 'approval' in t[0].lower()]
    print(f"\nApproval-related tables: {approval_tables}")
    
    if 'approval_gates' in [t[0] for t in tables]:
        # Query pending records older than 30 days
        cursor.execute("""
            SELECT COUNT(*) 
            FROM approval_gates 
            WHERE status='pending' 
            AND created_at < datetime('now', '-30 days')
        """)
        count = cursor.fetchone()[0]
        print(f"\nPending approval_gates older than 30 days: {count}")
        
        # Get schema
        cursor.execute("PRAGMA table_info(approval_gates)")
        columns = cursor.fetchall()
        print(f"\napproval_gates columns:")
        for col in columns:
            print(f"  {col[1]} ({col[2]})")
    
    conn.close()
else:
    print(f"Database not found: {db_path}")
