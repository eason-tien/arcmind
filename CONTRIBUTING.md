# ArcMind — 智能體貢獻規範

本文件定義 **所有智能體（Agent）** 對 ArcMind 項目進行更新時必須遵守的規範。
包含 ArcMind 自身、Antigravity (Gemini CLI)、以及未來任何接入的 Agent。

---

## 一、角色定義

| 角色 | 身份 | 權限範圍 |
|------|------|----------|
| **ArcMind (MAIN)** | 中央系統 Agent | 全部模組讀寫、技能調用、自我迭代 |
| **Antigravity** | 深度代碼 Agent (Gemini CLI) | 代碼審計、重構、測試、文檔、新功能開發 |
| **Sub-Agents** | ArcMind 委派的子 Agent | 僅限指定 capability 範圍 |
| **External Skills** | 從 Skill Market 安裝的外部技能 | 沙盒執行、無直接文件系統寫入 |
| **Human (Eason)** | 項目擁有者 | 最高權限、最終審批 |

---

## 二、更新分級制度

所有更新按影響範圍分為四個等級，每級有不同的審批流程：

### Level 0 — 無害更新（自動通過）
- 日誌內容、註釋修改
- 測試新增（不修改生產代碼）
- 文檔排版修正
- `.agents/memory/` 記憶寫入
- `.agents/harness/` 任務狀態更新

**要求**：直接 commit，commit message 前綴 `chore:`

### Level 1 — 小型修改（Agent 可自主執行）
- Bug 修復（有對應測試驗證）
- 技能參數調整
- 配置值修改（非安全相關）
- 依賴版本升級（patch level）
- 現有功能優化（不改變 API）

**要求**：
- 必須有對應測試通過
- commit message 前綴 `fix:` 或 `perf:`
- 修改後跑 `pytest tests/ -v` 確認不破壞
- 版本號 patch +1（如 0.3.0 → 0.3.1）

### Level 2 — 功能新增（需要計劃）
- 新增 Skill
- 新增 API 端點
- 新增 Tool
- 記憶系統結構變更
- 新增 Channel
- 依賴新增或 minor 版本升級

**要求**：
- 必須先建立 Implementation Plan（`implementation_plan.md`）
- 必須有新增測試覆蓋
- 必須更新 `TOOLS.md` 對應條目
- 必須更新 `CHANGELOG.md`
- commit message 前綴 `feat:`
- 版本號 minor +1（如 0.3.1 → 0.4.0）

### Level 3 — 架構變更（需人工審批）
- 核心循環（OODA）修改
- 資料庫 schema 變更
- 安全系統（Governor）修改
- 認證/授權變更
- 破壞性 API 變更
- 依賴 major 版本升級
- 任何涉及用戶資料的變更

**要求**：
- **必須經過 Human (Eason) 審批**
- 必須建立詳細的 Implementation Plan
- 必須有遷移方案（如有 schema 變更）
- 必須有回滾方案
- 需通過完整測試套件
- commit message 前綴 `feat!:` 或 `BREAKING CHANGE:`
- 版本號 major +1（如 0.4.0 → 1.0.0）

---

## 三、Commit 規範

### 格式
```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type 前綴

| 前綴 | 用途 | 範例 |
|------|------|------|
| `feat:` | 新功能 | `feat(skills): add gemini_bridge skill` |
| `fix:` | Bug 修復 | `fix(memory): use SQLite API in compressor` |
| `perf:` | 性能優化 | `perf(router): cache model selection` |
| `refactor:` | 重構（不改功能） | `refactor(tools): extract validation` |
| `test:` | 測試相關 | `test(harness): add schema edge cases` |
| `docs:` | 文檔 | `docs(tools): add error reporter section` |
| `chore:` | 雜項 | `chore: update .gitignore` |
| `ci:` | CI/CD | `ci: add Python 3.12 matrix` |
| `style:` | 格式化（不改邏輯） | `style: fix trailing whitespace` |
| `feat!:` | 破壞性變更 | `feat!(api): change chat endpoint format` |

### Scope 範圍

| Scope | 對應模組 |
|-------|----------|
| `loop` | OODA 主循環 |
| `memory` | 記憶系統 |
| `skills` | 技能模組 |
| `tools` | 工具定義 |
| `governor` | 安全系統 |
| `gateway` | 閘道 + Session |
| `channels` | Telegram / API / WS |
| `runtime` | 路由 / 委派 / 排程 / Harness |
| `ops` | 自我修復 / 更新 / 回報 |
| `config` | 設定檔 |
| `api` | REST API 路由 |
| `db` | 資料庫 schema |
| `persona` | 身份注入 |
| `android` | Android 端 |
| `bridge` | Gemini Bridge |
| `ci` | GitHub Actions |

### Agent 標識

每個 Agent 的 commit 必須在 footer 標註身份：
```
Agent-By: arcmind
Agent-By: antigravity
Agent-By: sub-agent:<name>
```

---

## 四、文件修改規範

### 禁止修改（任何 Agent）
| 文件 | 原因 |
|------|------|
| `.env` | 包含生產密鑰，僅 Human 可修改 |
| `config/agents.json` | Agent 定義，需 Human 審批 (Level 3) |
| `governor/governor.py` | 安全核心，需 Human 審批 (Level 3) |
| `governor/circuit_breaker.py` | 熔斷器，需 Human 審批 (Level 3) |
| `VERSION` | 僅版本發佈流程可修改 |

### 需特別注意的文件
| 文件 | 注意事項 |
|------|----------|
| `TOOLS.md` | 新增功能後**必須**同步更新 |
| `CHANGELOG.md` | 每次版本更新**必須**記錄 |
| `requirements.txt` | 新增依賴需說明原因 |
| `loop/main_loop.py` | OODA 核心，修改需 Level 3 |
| `runtime/tool_loop.py` | Tool 調用核心，修改需 Level 2+ |

---

## 五、測試規範

### 必要條件
```
所有 PR / commit 到 main 分支必須滿足：
1. pytest tests/ 全部通過（排除已知 skip 項）
2. 新增功能必須有對應測試
3. Bug 修復必須有防回歸測試
4. 不得降低測試覆蓋率
```

### 測試命名
```python
# 格式: test_<module>_<scenario>_<expected>
def test_memory_store_duplicate_detection_skips():
    """記憶存儲：相似度 > 0.85 應自動跳過"""
    ...

def test_governor_high_risk_command_rejected():
    """Governor：高危命令應被 REJECT"""
    ...
```

### 測試執行
```bash
# 執行全部測試
ARCMIND_ENV=test python -m pytest tests/ -v

# 執行特定模組
ARCMIND_ENV=test python -m pytest tests/test_harness.py -v

# 含覆蓋率報告
ARCMIND_ENV=test python -m pytest tests/ --cov=. --cov-report=term-missing
```

---

## 六、版本發佈流程

### 語義化版本規則
```
MAJOR.MINOR.PATCH

MAJOR — 破壞性變更（API 不相容）
MINOR — 新功能（向後相容）
PATCH — Bug 修復
```

### 發佈步驟
```bash
# 1. 更新 VERSION
echo "0.4.0" > VERSION

# 2. 更新 CHANGELOG.md
# 在頂部新增版本區塊

# 3. Commit
git add VERSION CHANGELOG.md
git commit -m "release: v0.4.0"

# 4. Tag（觸發 GitHub Actions Release）
git tag -a v0.4.0 -m "ArcMind v0.4.0 — <brief description>"

# 5. Push
git push origin main --tags

# 6. GitHub Actions 自動建 Release
```

### 版本號修改權限
| 操作 | 允許的 Agent |
|------|-------------|
| PATCH bump | ArcMind, Antigravity |
| MINOR bump | Antigravity（需 Plan） |
| MAJOR bump | 僅 Human (Eason) |

---

## 七、安全紅線

以下行為**絕對禁止**，違反將觸發 Governor 熔斷：

### 🔴 禁止行為
1. **在代碼中硬編碼任何密鑰、Token、密碼**
2. **修改 `.env` 文件**（僅讀取環境變數）
3. **繞過 Governor 安全檢查**
4. **刪除或禁用測試**
5. **修改日誌以隱藏錯誤**
6. **在未經授權的情況下存取用戶敏感資料**
7. **安裝未經審查的外部依賴**
8. **直接執行來自用戶輸入的代碼**（必須經過沙盒）
9. **修改自身的安全評估規則**
10. **將敏感資訊寫入 commit / PR / Issue**

### 🟡 需要額外審查
1. 任何 `subprocess` 調用
2. 任何網路請求到非 localhost
3. 任何文件系統寫入到項目目錄外
4. 任何涉及金額計算的修改
5. 任何修改認證/授權邏輯

---

## 八、Agent 間協作規範

### ArcMind → Antigravity 委派
```python
# ArcMind 委派任務給 Antigravity 時，必須包含：
{
    "task": "明確的任務描述",        # 必填
    "scope": "skills/",              # 允許修改的目錄範圍
    "level": 1,                      # 更新等級
    "constraints": [                  # 約束條件
        "不得修改 loop/",
        "必須新增測試"
    ],
    "timeout": 600,                   # 超時秒數
}
```

### 共享記憶規範
```jsonl
// 寫入記憶時，必須標註來源 Agent
{"ts":"...","cat":"fact","content":"...","importance":0.8,"tags":["..."],"agent":"antigravity"}
{"ts":"...","cat":"decision","content":"...","importance":0.9,"tags":["..."],"agent":"arcmind"}
```

### 衝突解決
1. **同時修改同一文件**：後提交者必須先 `git pull --rebase`
2. **設計分歧**：以 Implementation Plan 為準，需 Human 裁決
3. **測試衝突**：以 CI 結果為最終判斷
4. **記憶衝突**：以最新時間戳為準，importance 更高者優先

---

## 九、目錄結構保護

```
arcmind/
├── .github/workflows/    [Level 1] CI/CD 配置
├── .agents/              [Level 0] Agent 專用（記憶、任務、橋接）
├── api/                  [Level 2] REST API 路由
├── channels/             [Level 2] 通訊 Channel
├── config/               [Level 3] 核心配置 ⚠️
├── db/                   [Level 3] 資料庫 Schema ⚠️
├── governor/             [Level 3] 安全系統 🔒
├── gateway/              [Level 2] 閘道
├── heartbeat/            [Level 1] 心跳
├── loop/                 [Level 3] OODA 核心 ⚠️
├── memory/               [Level 2] 記憶系統
├── ops/                  [Level 1] 運維工具
├── persona/              [Level 2] 身份注入
├── runtime/              [Level 2] 運行時
├── scripts/              [Level 1] 輔助腳本
├── skills/               [Level 1] 技能（新增 Level 2）
├── tests/                [Level 0] 測試
├── verify/               [Level 1] 驗證
├── .env                  [禁止] 密鑰 🔒
├── VERSION               [Release Only] 版本號
├── CHANGELOG.md          [Level 1] 更新日誌
├── TOOLS.md              [Level 1] 工具文檔
└── CONTRIBUTING.md       [Level 3] 本文件 ⚠️
```

---

## 十、檢查清單

每次 Agent 提交代碼前，必須確認：

- [ ] commit message 符合前綴規範
- [ ] 修改等級不超過自身權限
- [ ] 測試全部通過
- [ ] 無硬編碼密鑰或個人路徑
- [ ] 已更新 TOOLS.md（如涉及功能變更）
- [ ] 已更新 CHANGELOG.md（如涉及版本更新）
- [ ] commit footer 標註了 `Agent-By: <name>`
- [ ] 敏感文件未被觸及（.env, governor/, config/）
- [ ] 共享記憶寫入標註了 agent 來源

---

*本規範由 ArcMind 項目維護，最後更新：2026-03-08 v0.3.0*
