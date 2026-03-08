# ArcMind AI Provider 設定指南

## 支援的 Provider 一覽

| Provider | 類型 | 啟用方式 | 備註 |
|----------|------|----------|------|
| **Anthropic** | 雲端 | `ANTHROPIC_API_KEY=sk-ant-...` | 主力推薦，Claude 系列 |
| **OpenAI** | 雲端 | `OPENAI_API_KEY=sk-...` | GPT-4o, o1 系列 |
| **Google Gemini** | 雲端 | `GOOGLE_API_KEY=AIza...` | Gemini 2.0 Flash/Pro |
| **Groq** | 雲端 | `GROQ_API_KEY=gsk_...` | 速度最快，有免費額度 |
| **Mistral** | 雲端 | `MISTRAL_API_KEY=...` | 歐洲開源模型 |
| **OLLAMA** | 本地 | `OLLAMA_ENABLED=true` | 完全免費，隱私安全 |
| **LM Studio** | 本地 | `CUSTOM_MODEL_BASE_URL=http://localhost:1234/v1` | GUI 管理本地模型 |
| **DeepSeek** | 雲端 | providers 區塊設定 | 低成本推理模型 |
| **Together AI** | 雲端 | providers 區塊設定 | 開源模型雲端版 |

---

## 快速設定

### 1. 複製 .env 範本
```bash
cp .env.example .env
```

### 2. 填入要使用的 provider key（只需填你有的）

```bash
# .env 範例（只填 Anthropic + OLLAMA）
ANTHROPIC_API_KEY=sk-ant-api03-xxxxxxxx
OLLAMA_ENABLED=true
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_DEFAULT_MODEL=llama3.2
```

### 3. 確認啟用（呼叫 API）
```bash
curl http://localhost:8100/v1/models
# 回傳已啟用的 provider 清單
```

---

## OLLAMA 本地模型設定

```bash
# 1. 安裝 OLLAMA
brew install ollama           # macOS
# 或到 https://ollama.com 下載

# 2. 啟動服務
ollama serve

# 3. 下載模型（選一個）
ollama pull llama3.2          # 2GB，通用
ollama pull qwen2.5:7b        # 4GB，中文優化
ollama pull deepseek-r1:7b   # 4GB，推理優化
ollama pull phi4              # 8GB，Microsoft 輕量
ollama pull mistral           # 4GB，歐洲開源

# 4. 在 .env 設定
OLLAMA_ENABLED=true
OLLAMA_DEFAULT_MODEL=llama3.2
```

---

## 自訂 OpenAI-compatible 端點

任何支援 OpenAI API 格式的服務都可以接入：

```yaml
# config/routing_rules.yaml 的 providers 區塊取消註解
providers:
  deepseek:
    base_url: https://api.deepseek.com/v1
    api_key: sk-deepseek-xxxx
  together:
    base_url: https://api.together.xyz/v1
    api_key: your-together-key
  perplexity:
    base_url: https://api.perplexity.ai
    api_key: pplx-xxxx
```

使用時：
```json
{ "model": "deepseek:deepseek-chat" }
```

---

## 路由規則自訂

編輯 `config/routing_rules.yaml`：

```yaml
# 把某個任務類型指向本地 OLLAMA
task_type_rules:
  - match: [private, local_only]
    model: ollama:llama3.2

# 讓隱私任務完全不離開本地
  - match: [sensitive_data]
    model: ollama:qwen2.5:7b
```

---

## Fallback 邏輯

當主 provider 失敗（網路、quota、API 錯誤），自動按 `fallback_chain` 順序降級：

```
anthropic:claude-sonnet → anthropic:claude-haiku → openai:gpt-4o-mini
→ groq:llama-3.3-70b → google:gemini-2.0-flash → ollama:llama3.2
```

最後一級（`ollama`）在本地，**確保系統不因雲端故障完全中斷**。
