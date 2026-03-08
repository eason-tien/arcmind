from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field


BASE_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    # ── ArcMind 自身 ──────────────────────────────────────────
    arcmind_host: str = "0.0.0.0"
    arcmind_port: int = 8100
    arcmind_api_key: str = Field(default="arcmind-dev-key", alias="ARCMIND_API_KEY")
    arcmind_env: str = Field(default="development", alias="ARCMIND_ENV")

    # ── MGIS 連線 ──────────────────────────────────────────────
    mgis_url: str = Field(default="http://localhost:8000", alias="MGIS_URL")
    mgis_api_key: str = Field(default="", alias="MGIS_API_KEY")
    mgis_admin_token: str = Field(default="", alias="MGIS_ADMIN_TOKEN")
    mgis_timeout: int = 30

    # ── OpenClaw 連線（可選）──────────────────────────────────
    openclaw_url: str = Field(default="", alias="OPENCLAW_URL")
    openclaw_enabled: bool = False

    # ═══════════════════════════════════════════════════════════
    #  AI Provider API Keys
    #  只要填入 key，對應 provider 就自動啟用
    # ═══════════════════════════════════════════════════════════

    # ── Anthropic (Claude) ────────────────────────────────────
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # ── OpenAI ────────────────────────────────────────────────
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="OPENAI_BASE_URL"
    )

    # ── OpenAI Codex CLI (OAuth 登入) ─────────────────────────
    # 設 CODEX_ENABLED=true 來讀取 ~/.codex/auth.json 的 OAuth token
    # 如果 OPENAI_API_KEY 已設定，優先用 API Key
    codex_enabled: bool = Field(default=False, alias="CODEX_ENABLED")

    # ── Google Gemini ─────────────────────────────────────────
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")

    # ── Groq（OpenAI-compatible，極速推理）────────────────────
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")

    # ── Mistral（OpenAI-compatible）───────────────────────────
    mistral_api_key: str = Field(default="", alias="MISTRAL_API_KEY")

    # ── OLLAMA 本地模型 ────────────────────────────────────────
    # 預設: http://localhost:11434/v1 （OLLAMA 預設端口）
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL"
    )
    # 設 OLLAMA_ENABLED=true 才啟動 ollama provider（避免無 OLLAMA 時報錯）
    ollama_enabled: bool = Field(default=False, alias="OLLAMA_ENABLED")
    ollama_default_model: str = Field(default="llama3.2", alias="OLLAMA_DEFAULT_MODEL")

    # ── Custom OpenAI-compatible Endpoint ─────────────────────
    # 可接入 LM Studio / Together AI / Perplexity / DeepSeek 等
    custom_model_base_url: str = Field(default="", alias="CUSTOM_MODEL_BASE_URL")
    custom_model_api_key: str = Field(default="", alias="CUSTOM_MODEL_API_KEY")
    custom_model_name: str = Field(default="custom", alias="CUSTOM_MODEL_NAME")

    # ═══════════════════════════════════════════════════════════
    #  路徑設定
    # ═══════════════════════════════════════════════════════════

    db_path: Path = BASE_DIR / "data" / "arcmind.db"
    routing_rules_path: Path = BASE_DIR / "config" / "routing_rules.yaml"
    skills_dir: Path = BASE_DIR / "skills"
    evidence_dir: Path = BASE_DIR / "evidence"

    # ── 瀏覽器 ────────────────────────────────────────────────
    browser_headless: bool = True
    browser_timeout: int = 30000  # ms

    # ── Cron ──────────────────────────────────────────────────
    cron_timezone: str = "Asia/Taipei"

    # ── Telegram Channel ──────────────────────────────────────
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # ── GitHub Integration ────────────────────────────────────
    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    github_webhook_secret: str = Field(default="", alias="GITHUB_WEBHOOK_SECRET")
    github_default_owner: str = Field(default="", alias="GITHUB_DEFAULT_OWNER")

    class Config:
        env_file = str(BASE_DIR / ".env")
        env_file_encoding = "utf-8"
        populate_by_name = True

    def model_post_init(self, __context):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        (self.evidence_dir / "logs").mkdir(exist_ok=True)

    # ── 快速查詢哪些 provider 有 key ─────────────────────────

    def available_providers(self) -> list[str]:
        providers = []
        if self.anthropic_api_key:
            providers.append("anthropic")
        if self.openai_api_key:
            providers.append("openai")
        if self.google_api_key:
            providers.append("google")
        if self.groq_api_key:
            providers.append("groq")
        if self.mistral_api_key:
            providers.append("mistral")
        if self.ollama_enabled:
            providers.append("ollama")
        if self.custom_model_base_url:
            providers.append("custom")
        return providers


settings = Settings()
