#!/bin/bash
# ArcMind 系统健康检查脚本
# 每12小时执行

LOG_FILE="/Users/eason/Code/arcmind/logs/arcmind.log"
ERROR_LOG="/Users/eason/Code/arcmind/logs/error.log"
ALERT_LOG="/Users/eason/Code/arcmind/logs/health_alert.log"
API_URL="http://localhost:8100/health"

TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
echo "=== 健康检查 $TIMESTAMP ===" >> $ALERT_LOG

# 1. 检查 API 服务是否正常
HEALTH_STATUS=$(curl -s -o /dev/null -w "%{http_code}" $API_URL 2>/dev/null)
if [ "$HEALTH_STATUS" != "200" ]; then
    echo "[$TIMESTAMP] ❌ API 服务异常 HTTP: $HEALTH_STATUS" >> $ALERT_LOG
    # 尝试重启服务
    cd /Users/eason/Code/arcmind && nohup python -m arcmind.server > /dev/null 2>&1 &
    echo "[$TIMESTAMP] 🔄 已尝试重启 API 服务" >> $ALERT_LOG
else
    echo "[$TIMESTAMP] ✅ API 服务正常" >> $ALERT_LOG
fi

# 2. 检查最近错误日志
if [ -f "$LOG_FILE" ]; then
    ERROR_COUNT=$(grep -c "ERROR" "$LOG_FILE" 2>/dev/null || echo "0")
    if [ "$ERROR_COUNT" -gt 0 ]; then
        echo "[$TIMESTAMP] ⚠️ 发现 $ERROR_COUNT 个错误记录" >> $ALERT_LOG
        # 提取最近5条错误
        grep "ERROR" "$LOG_FILE" | tail -5 >> $ALERT_LOG
    else
        echo "[$TIMESTAMP] ✅ 无错误记录" >> $ALERT_LOG
    fi
fi

# 3. 检查 Telegram Bot
TG_STATUS=$(curl -s "https://api.telegram.org/bot8226645969:AAEtV4IUVvWpQzsLsdNLYhtuhXKeU7OSFF8/getMe" | grep -c "ok" || echo "0")
if [ "$TG_STATUS" -gt 0 ]; then
    echo "[$TIMESTAMP] ✅ Telegram Bot 正常" >> $ALERT_LOG
else
    echo "[$TIMESTAMP] ❌ Telegram Bot 异常" >> $ALERT_LOG
fi

# 4. 检查磁盘空间
DISK_USAGE=$(df -h / | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 90 ]; then
    echo "[$TIMESTAMP] ⚠️ 磁盘使用率: ${DISK_USAGE}%" >> $ALERT_LOG
else
    echo "[$TIMESTAMP] ✅ 磁盘使用率: ${DISK_USAGE}%" >> $ALERT_LOG
fi

# 5. 检查内存
MEM_USAGE=$(vm_stat | grep "Pages active" | awk '{print $3}' | sed 's/\.//')
if [ "$MEM_USAGE" -gt 18000 ]; then
    echo "[$TIMESTAMP] ⚠️ 内存使用较高" >> $ALERT_LOG
else
    echo "[$TIMESTAMP] ✅ 内存正常" >> $ALERT_LOG
fi

echo "=== 检查完成 ===" >> $ALERT_LOG
echo "" >> $ALERT_LOG

# 发送 Telegram 通知
curl -s -X POST "https://api.telegram.org/bot8226645969:AAEtV4IUVvWpQzsLsdNLYhtuhXKeU7OSFF8/sendMessage" \
    -d "chat_id=8541856901" \
    -d "text=🔔 ArcMind 健康检查完成 - $TIMESTAMP" > /dev/null 2>&1

exit 0
