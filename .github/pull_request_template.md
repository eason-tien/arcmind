## 變更描述
<!-- 簡描這個 PR 做了什麼 -->

## 更新等級
<!-- 根據 CONTRIBUTING.md 選擇 -->
- [ ] Level 0 — 日誌/註釋/測試/記憶
- [ ] Level 1 — Bug 修復/參數調整/優化
- [ ] Level 2 — 新功能/新 Skill/新 API
- [ ] Level 3 — 架構變更（需 Human 審批 ⚠️）

## 變更類型
- [ ] `fix:` Bug 修復
- [ ] `feat:` 新功能
- [ ] `perf:` 性能優化
- [ ] `refactor:` 重構
- [ ] `docs:` 文檔
- [ ] `test:` 測試
- [ ] `ci:` CI/CD
- [ ] `feat!:` 破壞性變更

## Agent 資訊
| 項目 | 值 |
|------|-----|
| **Agent** | <!-- arcmind / antigravity / sub-agent --> |
| **版本** | <!-- 當前 VERSION --> |

## 提交前檢查清單
<!-- 根據 CONTRIBUTING.md 第十章 -->
- [ ] Commit message 符合 `type(scope): subject` 格式
- [ ] Commit footer 包含 `Agent-By: <name>`
- [ ] 修改等級不超過自身權限
- [ ] `pytest tests/ -v` 全部通過
- [ ] 無硬編碼密鑰或個人路徑 (`/Users/...`)
- [ ] 已更新 `TOOLS.md`（如涉及功能變更）
- [ ] 已更新 `CHANGELOG.md`（如涉及版本更新）
- [ ] 敏感文件未被觸及 (`.env`, `governor/`, `config/agents.json`)
- [ ] 共享記憶寫入標註了 agent 來源

## 關聯 Issue
<!-- Closes #123 -->
