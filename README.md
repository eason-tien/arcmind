<p align="center">
  <h1 align="center">🧠 ArcMind</h1>
  <p align="center">
    <strong>OODA-based Autonomous AI Agent</strong><br>
    Multi-provider routing · 63 skills · 4-layer memory · Self-healing
  </p>
  <p align="center">
    <a href="#-quick-start">Quick Start</a> ·
    <a href="#-features">Features</a> ·
    <a href="#-architecture">Architecture</a> ·
    <a href="CONTRIBUTING.md">Contributing</a>
  </p>
</p>

---

## What is ArcMind?

ArcMind is an **autonomous AI agent** that thinks in [OODA loops](https://en.wikipedia.org/wiki/OODA_loop) (Observe → Orient → Decide → Act). It can browse the web, manage files, write code, schedule tasks, send Telegram messages, and learn from every interaction — all with built-in governance and self-healing.

```
User / Cron / Webhook
       ↓
┌─── OODA Loop ───────────────────────┐
│  Observe  ← input + memory recall   │
│  Orient   ← classify + plan         │
│  Decide   ← model route + governor  │
│  Act      ← skills + tools          │
│  [Learn]  ← memory write-back       │
└──────────────────────────────────────┘
```

## ✨ Features

| Category | Highlights |
|----------|-----------|
| **🧠 Reasoning** | OODA loop, multi-step planning, goal tracking |
| **🔀 Model Routing** | Auto-selects best LLM per task (OpenAI, Anthropic, Ollama, NVIDIA NIM, custom) |
| **🛠️ 63 Skills** | Web search, browser automation, code execution, file ops, email KB, cron scheduling, and more |
| **💾 4-Layer Memory** | Working → Short-term → Long-term → Vector (ChromaDB) |
| **🤖 Multi-Agent** | CEO delegates to specialist agents (search, code, QA, DevOps, PM) |
| **📱 Channels** | Telegram bot, REST API, WebSocket, voice input |
| **🔒 Governance** | Governor审计, risk assessment, action approval |
| **🩺 Self-Healing** | Watchdog + repair agent + auto-restart |
| **📊 Observability** | Prometheus + Grafana + Loki stack |
| **📅 Scheduler** | Cron-based task scheduling with timezone support |

## 🚀 Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone
git clone https://github.com/eason-tien/arcmind.git
cd arcmind

# Configure (only 3 required vars)
cp .env.example .env
# Edit .env: set ARCMIND_API_KEY and at least one LLM provider key

# Start
docker compose up -d

# Check health
curl http://localhost:8100/health
```

### Option 2: Local Development

```bash
# Clone
git clone https://github.com/eason-tien/arcmind.git
cd arcmind

# Setup
make setup    # Creates venv, installs deps, copies .env

# Configure
# Edit .env: set ARCMIND_API_KEY and at least one LLM provider key

# Run
make dev      # Starts ArcMind on port 8100
```

### Option 3: Makefile Commands

```bash
make setup     # First-time setup
make dev       # Start development server
make test      # Run tests
make lint      # Run linter
make docker    # Build & start with Docker
make clean     # Clean generated files
```

## ⚙️ Configuration

ArcMind uses a `.env` file for configuration. Copy `.env.example` to get started:

```bash
cp .env.example .env
```

### Required Variables (minimum to run)

| Variable | Description |
|----------|------------|
| `ARCMIND_API_KEY` | API key for authenticating requests to ArcMind |
| At least one LLM provider | See below |

### LLM Providers (pick one or more)

| Provider | Variable | Notes |
|----------|----------|-------|
| **Ollama** (local) | `OLLAMA_ENABLED=true` | Free, runs locally |
| **OpenAI** | `OPENAI_API_KEY` | GPT-4o, GPT-4 |
| **Anthropic** | `ANTHROPIC_API_KEY` | Claude Sonnet/Opus |
| **NVIDIA NIM** | `NVIDIA_API_KEY` | Llama, Mistral |
| **Custom** | `CUSTOM_MODEL_BASE_URL` | Any OpenAI-compatible API |

> See `.env.example` for the full list of optional configuration.

## 🏗️ Architecture

```
arcmind/
├── api/           # FastAPI HTTP server
├── channels/      # Telegram, WebSocket
├── config/        # Settings, tool registry
├── db/            # Database models
├── foundation/    # MGIS client (governance, memory)
├── governor/      # Risk assessment & action approval
├── loop/          # OODA main loop, goal tracker
├── memory/        # 4-layer memory system
├── runtime/       # Model router, skill manager, lifecycle
├── skills/        # 63 built-in skills
├── tools/         # Tool definitions
├── watchdog.py    # Self-healing watchdog
└── main.py        # Entry point
```

### Key Components

- **Model Router** (`runtime/model_router.py`) — Routes tasks to the optimal LLM based on task type, cost budget, and capability requirements. Auto-fallback on failure.
- **Skill Manager** (`runtime/skill_manager.py`) — Discovers, loads, and executes skills with YAML manifests.
- **OODA Loop** (`loop/main_loop.py`) — Core reasoning loop: Observe → Orient → Decide → Act → Learn.
- **Governor** (`governor/`) — Pre-execution risk assessment. Blocks dangerous actions.
- **Memory** (`memory/`) — Working memory → short-term → long-term → vector embeddings (ChromaDB).

## 📡 API

ArcMind exposes a REST API on port `8100` (default):

```bash
# Health check
curl http://localhost:8100/health

# Send a message
curl -X POST http://localhost:8100/v1/chat \
  -H "Authorization: Bearer YOUR_ARCMIND_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"message": "Search for the latest AI news"}'
```

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## 📄 License

[MIT](LICENSE) © ArcMind Contributors
