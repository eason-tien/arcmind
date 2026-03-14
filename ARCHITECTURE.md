# ArcMind — Architecture Document
> Version: 0.9.3
> Author: Eason
> Status: 定義中（架構轉向）

---

## 一、定位重定義

**ArcMind** 是以 **MGIS 為骨幹**，向下補足 OpenClaw 執行能力缺口的**完整自主智能體系統**。

```
┌──────────────────────────────────────────────────────────────┐
│                        ArcMind                               │
│                                                              │
│  ┌──────────────── MGIS Foundation ──────────────────────┐  │
│  │  治理(Governor) · 記憶(LMF) · 因果(Causal) · 規劃     │  │
│  │  主動需求引擎(PDE) · SharedBrain · TaskGraph          │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
│  ┌──────────────── Runtime Extension ────────────────────┐  │
│  │  模型路由     │  Skill 管理  │  生命週期管理           │  │
│  │  瀏覽器/設備  │  Cron 排程  │  工具執行               │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                              │
└──────────────────────────┬───────────────────────────────────┘
                           │ 協議相容（可選接入）
                  ┌────────▼────────┐
                  │   OpenClaw      │  ← 外部 Skills / Gateway
                  │  Skills · UI    │     協議相容，可呼叫
                  └─────────────────┘
```

**核心信念：**
- MGIS 是「大腦」——治理、記憶、因果、規劃，ArcMind 直接繼承
- OpenClaw 是「工具箱」——ArcMind 在本地重現核心能力，可選接入 OpenClaw
- ArcMind = 完整閉環，不依賴 OpenClaw 也能獨立運行

---

## 二、MGIS Foundation（繼承層）

ArcMind 透過 API 直接使用 MGIS 所有能力，不重造輪子：

| MGIS 能力 | ArcMind 使用方式 |
|-----------|----------------|
| **Governor** | `POST /v1/governance/audit` — 所有行動的風險終審 |
| **LMF 記憶** | `GET/POST /v1/memory/*` — 查詢過去經驗、寫入學習結果 |
| **Planner** | `POST /v1/planner/plan` — 生成 TaskGraph |
| **Proactive Engine V2** | `GET /v1/proactive/status` — 取得主動需求建議 / Tomorrow Pack |
| **SharedBrain** | 背景排程觸發器（每日 21:30 / 每週日 18:00） |
| **Message Classifier** | `POST /v1/proactive/classify` — 訊息分類 |

---

## 三、Runtime Extension（補足層）

OpenClaw 具備但 MGIS 沒有的執行能力，ArcMind 自行實作：

### 3.1 模型路由（Model Router）

```
任務 → 路由規則 → 選擇模型 → 呼叫 → 結果
```

| 欄位 | 說明 |
|------|------|
| **路由維度** | 任務類型、成本預算、延遲要求、能力需求 |
| **支援模型** | Claude (Anthropic SDK)、本地 LLM、其他 provider |
| **抽象介面** | `ModelRouter.complete(prompt, task_type) → Response` |
| **fallback** | 主模型失敗 → 自動降級到次要模型 |

路由規則範例：
```yaml
rules:
  - task_type: code_review      → claude-opus-4
  - task_type: quick_classify   → claude-haiku-4
  - task_type: browser_vision   → claude-sonnet-4 + vision
  - cost_budget: low            → local_llm
```

### 3.2 Skill 管理（Skill Manager）

```
技能定義 → 技能登錄 → 技能發現 → 技能呼叫 → 結果回收
```

| 欄位 | 說明 |
|------|------|
| **Skill 格式** | 相容 OpenClaw Skill 協議（YAML manifest + Python/JS handler） |
| **本地技能** | ArcMind 內建技能（file_ops, web_search, code_exec 等） |
| **遠端技能** | 透過 OpenClaw Gateway 呼叫（協議相容，非必要） |
| **技能生命週期** | register → discover → invoke → audit → retire |

Skill Manifest 格式（相容 OpenClaw）：
```yaml
name: web_search
version: 1.0
description: 搜尋網路並返回結果摘要
inputs:
  - name: query
    type: string
    required: true
outputs:
  - name: results
    type: list
permissions: [network]
```

### 3.3 生命週期管理（Lifecycle Manager）

三層生命週期：

```
Session Lifecycle:  start → active → paused → resumed → ended
Task Lifecycle:     created → assigned → executing → verifying → closed
Agent Lifecycle:    spawned → running → idle → terminated
```

| 職責 | 說明 |
|------|------|
| **Session 持久化** | 跨次 session 保存上下文，自動續接未完成任務 |
| **Task 狀態機** | 任務從建立到關閉的完整狀態追蹤 |
| **Agent 池** | 管理並發 agent 數量與資源上限 |
| **恢復機制** | 系統重啟後自動恢復中斷的任務 |

### 3.4 瀏覽器/設備（Browser & Device）

```
指令 → 瀏覽器動作 → 截圖/DOM → 模型理解 → 下一步動作
```

| 功能 | 實作 |
|------|------|
| **瀏覽器自動化** | Playwright 驅動（headless / headed） |
| **視覺理解** | 截圖 → Claude Vision → 元素定位 |
| **表單填寫** | 結構化資料 → DOM 操作 |
| **設備整合** | （預留）MCP Browser Tool 協議相容 |

### 3.5 Cron 排程（Cron System）

```
排程定義 → 觸發器 → 任務生成 → Governor 審計 → 執行
```

| 功能 | 說明 |
|------|------|
| **Cron 語法** | 標準 cron expression（`0 21 * * *`） |
| **事件觸發** | webhook / 檔案變動 / API 回調 |
| **MGIS 整合** | 與 SharedBrain 排程協調（避免衝突） |
| **任務持久化** | 重啟後排程恢復，不遺漏 |
| **審計前置** | 所有排程任務在執行前必須通過 Governor |

---

## 四、OpenClaw 協議相容層

ArcMind 不依賴 OpenClaw，但**協議相容**，可在授權情況下接入：

```
ArcMind Skill Manager
       ↓
Skill Protocol Adapter
       ↓
本地 Skill Runner   OR   OpenClaw Gateway（可選）
```

相容點：
- Skill YAML manifest 格式相同
- 任務派單訊息格式相同（JSON schema）
- 結果回收格式相同

---

## 五、目錄結構（規劃）

```
arcmind/
├── foundation/
│   └── mgis_client.py          # MGIS API 客戶端（全部能力的入口）
│
├── runtime/
│   ├── model_router.py         # 模型路由引擎
│   ├── skill_manager.py        # Skill 登錄、發現、呼叫
│   ├── lifecycle.py            # Session/Task/Agent 生命週期
│   ├── browser.py              # Playwright 瀏覽器自動化
│   └── cron.py                 # Cron 排程系統
│
├── protocol/
│   ├── skill_schema.py         # Skill manifest 資料結構（OpenClaw 相容）
│   └── openclaw_adapter.py     # OpenClaw Gateway 客戶端（可選接入）
│
├── skills/                     # ArcMind 內建技能（本地）
│   ├── web_search.py
│   ├── file_ops.py
│   ├── code_exec.py
│   └── __manifest__.yaml       # 技能清單
│
├── loop/
│   ├── main_loop.py            # 主循環（Observe → Orient → Decide → Act）
│   ├── goal_tracker.py         # 長期目標追蹤
│   └── feedback.py             # 結果學習回寫 MGIS
│
├── api/
│   └── server.py               # ArcMind HTTP API（FastAPI）
│
└── config/
    ├── settings.py             # 連線設定、模型偏好
    └── routing_rules.yaml      # 模型路由規則
```

---

## 六、主循環設計

```
┌─────────────────── ArcMind Main Loop ───────────────────────┐
│                                                              │
│  Observe   ← 使用者輸入 / Cron 觸發 / MGIS Proactive Pack   │
│      ↓                                                       │
│  Orient    ← 查 MGIS 記憶 + 分類意圖 + 評估目標狀態         │
│      ↓                                                       │
│  Decide    ← 模型路由選擇 + TaskGraph 生成 + Governor 審計  │
│      ↓                                                       │
│  Act       ← Skill Manager 執行 + Browser 操作 + 工具呼叫   │
│      ↓                                                       │
│  [學習]    ← 結果回寫 MGIS LMF，更新 Lifecycle 狀態         │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## 七、設計原則

1. **MGIS 為根**：治理、記憶、規劃完全依賴 MGIS，不重複建造
2. **執行自主**：Runtime Extension 本地可運行，不強依賴 OpenClaw
3. **協議相容**：Skill 格式與 OpenClaw 相容，可雙向互操作
4. **審計前置**：所有排程、自動化動作必須通過 MGIS Governor
5. **最小侵入**：不修改 MGIS 與 OpenClaw 原始碼

---

## 八、待決策問題

- [ ] ArcMind 是否需要自己的 DB，或完全依賴 MGIS 的 SQLite？
- [ ] Playwright 瀏覽器模組是否使用 MCP Browser Tool 協議？
- [ ] 本地 Skill 執行沙盒：subprocess / Docker / WASM？
- [ ] 模型路由是否支援 OpenAI / Gemini，或僅 Claude？
- [ ] Cron 排程持久化儲存：APScheduler + SQLite？
- [ ] ArcMind API 是否需要 JWT 認證？

---

## 九、MVP 候選場景（重定義）

1. **本地 Skill 執行**：ArcMind 接受指令 → 路由模型 → 呼叫本地 Skill → Governor 審計 → 返回結果
2. **Cron + Proactive 整合**：排程觸發 → 取 MGIS Tomorrow Pack → 自動生成任務 → 執行
3. **瀏覽器智能體**：指令 → Browser Skill → Playwright 執行 → Vision 理解 → 多步操作

---

## 十、版本計畫

| 版本 | 目標 |
|------|------|
| **v0.1** | 架構文件（當前） |
| **v0.2** | foundation/ + MGIS 客戶端 + 基本 main_loop |
| **v0.3** | model_router + skill_manager + 3 個內建 Skill |
| **v0.4** | cron 系統 + lifecycle 管理 |
| **v0.5** | browser/device 模組 |
| **v1.0** | 完整 MVP，可與 OpenClaw 協議互操作 |

---

## 十一、核心演化心法 (Core System Evolution Philosophy)

1. **架構是法律**
   - 剛性分層與 Providers 模式
   - 透過嚴謹的架構設計（Architecture as Law），保證 Agent 不會在結構與實作上跑偏。

2. **Linter 是 Prompt**
   - 自定義 Linter 不僅僅用於報錯，還必須自帶修復指令（Fix Commands）。
   - 讓 Linter 成為 Agent 的 Prompt 來源，促使 Agent 形成自動修復與自我糾錯的完整閉環。

3. **規則是倍增器**
   - 全局生效的槓桿 (Rules as Multipliers)
   - 制定好的規則框架與自動化守則，能夠在全局系統中發揮倍增效應，大幅降低除錯與維護成本。
