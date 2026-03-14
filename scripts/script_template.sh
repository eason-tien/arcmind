#!/bin/bash
# ArcMind Shell 脚本模板 (脚板)
# 用于快速创建新 Shell 脚本的基础模板

set -e  # 遇到错误立即退出
set -u  # 使用未定义的变量时报错

# 配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/logs/$(basename "$0" .sh).log"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log_error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2
}

# 主函数
main() {
    log "脚本开始执行"
    
    # TODO: 在这里添加你的业务逻辑
    
    log "脚本执行完成"
}

# 执行主函数
main "$@"
