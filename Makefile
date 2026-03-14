# ── ArcMind Makefile ───────────────────────────────────────
.PHONY: setup dev test lint docker clean help

PYTHON := python3
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## First-time setup: venv + deps + .env
	@echo "🧠 Setting up ArcMind..."
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@if [ ! -f .env ]; then cp .env.example .env && echo "📝 Created .env from .env.example — please edit it"; fi
	@echo "✅ Setup complete! Run 'make dev' to start."

dev: ## Start development server
	@echo "🚀 Starting ArcMind..."
	$(PY) main.py

test: ## Run tests
	$(PY) -m pytest tests/ -v --tb=short

lint: ## Run linter
	$(PY) -m py_compile main.py
	@find . -name "*.py" -not -path "./.venv/*" -not -path "./__pycache__/*" | \
		head -20 | xargs -I{} $(PY) -m py_compile {} && echo "✅ Lint OK"

docker: ## Build and start with Docker Compose
	docker compose up -d --build
	@echo "✅ ArcMind running at http://localhost:8100"

docker-stop: ## Stop Docker Compose
	docker compose down

logs: ## Tail logs
	@if [ -f logs/arcmind.log ]; then tail -f logs/arcmind.log; else $(PY) main.py; fi

health: ## Check health
	@curl -s http://localhost:8100/health | python3 -m json.tool 2>/dev/null || echo "❌ ArcMind not running"

clean: ## Clean generated files
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache htmlcov .coverage
	@echo "🧹 Cleaned"
