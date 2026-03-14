#!/usr/bin/env python3
import sys
sys.path.insert(0, '/Users/eason/Code/arcmind')

from db.v3_schema import init_v3_schema

init_v3_schema()
print('✅ am_iteration_records 表已创建')
