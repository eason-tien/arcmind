# Antigravity Self-Memory System

純檔案系統的跨對話記憶機制，讓 Antigravity 在不同對話間保持知識延續。

## 目錄結構

```
.agents/memory/
├── README.md           ← 你正在讀的這個
├── long_term.jsonl      ← 永久長期記憶（JSONL append-only）
├── index.json           ← 關鍵字索引（加速檢索）
└── short_term/          ← 短期記憶（按日期分檔，7天過期）
    └── 2026-03-08.jsonl
```

## JSONL 記錄格式

```json
{"ts": "ISO-8601", "cat": "preference|fact|decision|project|observation", "content": "...", "importance": 0.0-1.0, "tags": ["..."]}
```

## 使用方式

| 指令 | 功能 |
|------|------|
| `/memory-save` | 寫入記憶（手動觸發或任務結束時） |
| `/memory-recall` | 載入記憶（新對話開始時） |

## 類別說明

| cat | 用途 | 範例 |
|-----|------|------|
| `preference` | 用戶偏好 | 「偏好繁體中文」 |
| `fact` | 技術事實 | 「ArcMind 用 SQLite 向量記憶」 |
| `decision` | 設計決策 | 「trading_enhanced.py 未註冊到 manifest」 |
| `project` | 專案上下文 | 「arcmind 專案根目錄 /Users/eason/Code/arcmind」 |
| `observation` | 臨時觀察 | 「測試通過率 95.5%」 |
