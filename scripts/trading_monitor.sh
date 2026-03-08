#!/bin/bash
# 台股交易监控脚本
# 执行时间：工作日 9:00-13:30 每30分钟检查一次

cd /Users/eason/Code/arcmind

# 记录日志
LOG_FILE="/Users/eason/Code/arcmind/logs/trading_$(date +%Y%m%d).log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] ====== 交易检查开始 ======" >> $LOG_FILE

# 检查是否在交易时段
HOUR=$(date +%H)
MINUTE=$(date +%M)
TIME_VALUE=$((10#$HOUR*60 + 10#$MINUTE))

# 台股交易时段 9:00-13:30 (540-810分钟)
if [ $TIME_VALUE -lt 540 ] || [ $TIME_VALUE -gt 810 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 非交易时段，跳过" >> $LOG_FILE
    exit 0
fi

# 执行交易引擎
python3 scripts/trading_engine.py >> $LOG_FILE 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ====== 交易检查完成 ======" >> $LOG_FILE
