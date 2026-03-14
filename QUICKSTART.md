# ⚡ ArcMind Quick Start Guide

Get ArcMind running in 5 minutes.

## Prerequisites

- **Python 3.12+** (for local) or **Docker** (for containers)
- At least one LLM provider API key (see below)

## Step 1: Clone

```bash
git clone https://github.com/eason-tien/arcmind.git
cd arcmind
```

## Step 2: Configure

```bash
cp .env.example .env
```

Open `.env` and set **two things**:

```bash
# 1. Your ArcMind API key (any strong string)
ARCMIND_API_KEY=my-secret-key-here

# 2. At least one LLM provider:
OPENAI_API_KEY=sk-...           # Option A: OpenAI
# ANTHROPIC_API_KEY=sk-ant-...  # Option B: Anthropic
# OLLAMA_ENABLED=true           # Option C: Free local (needs Ollama installed)
```

## Step 3: Start

### Docker (Recommended)

```bash
docker compose up -d
# Wait ~30s for startup, then:
curl http://localhost:8100/health
```

### Local Development

```bash
make setup    # Creates venv, installs deps
make dev      # Starts on port 8100
```

### Manual

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Step 4: Test

```bash
# Health check
curl http://localhost:8100/health

# Send a message
curl -X POST http://localhost:8100/v1/chat \
  -H "Authorization: Bearer my-secret-key-here" \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, what can you do?"}'
```

## Step 5: Connect Telegram (Optional)

1. Create a bot via [@BotFather](https://t.me/BotFather)
2. Add to `.env`:
   ```bash
   TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
   TELEGRAM_CHAT_ID=your-chat-id
   ```
3. Restart ArcMind

## What's Next?

- **Browse the API**: `http://localhost:8100/docs` (FastAPI auto-docs)
- **View skills**: Check `skills/` directory for 63 built-in capabilities
- **Cron tasks**: Schedule automated tasks via `/v1/cron/`
- **Web UI**: Access at `http://localhost:8100/ui` (if enabled)

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `Connection refused` on port 8100 | Wait 15-30s after startup for initialization |
| `ARCMIND_API_KEY not set` | Edit `.env` and set the key |
| `No LLM provider configured` | Add at least one API key in `.env` |
| Docker OOM killed | Increase Docker memory to 4GB+ |

## Available Make Commands

```
make setup       # First-time setup
make dev         # Start development server
make test        # Run tests
make lint        # Check syntax
make docker      # Build & start Docker
make docker-stop # Stop Docker
make logs        # Tail log files
make health      # Check service health
make clean       # Clean temp files
```
