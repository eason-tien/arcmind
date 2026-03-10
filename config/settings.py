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
    #  AI Provider API Keys — 市面上所有主流 Provider
    #  只要填入 key，對應 provider 就自動啟用
    # ═══════════════════════════════════════════════════════════

    # ── Anthropic (Claude 4 / Sonnet / Haiku) ────────────────
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com", alias="ANTHROPIC_BASE_URL"
    )

    # ── OpenAI (GPT-4o / o3 / o4-mini) ──────────────────────
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", alias="OPENAI_BASE_URL"
    )

    # ── OpenAI Codex CLI (OAuth 登入) ─────────────────────────
    codex_enabled: bool = Field(default=False, alias="CODEX_ENABLED")

    # ── Google Gemini (2.5 Pro / Flash) ──────────────────────
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    google_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta", alias="GOOGLE_BASE_URL"
    )

    # ── DeepSeek (V3 / R1 / Coder) ──────────────────────────
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com/v1", alias="DEEPSEEK_BASE_URL"
    )

    # ── xAI (Grok-3 / Grok-3-mini) ──────────────────────────
    xai_api_key: str = Field(default="", alias="XAI_API_KEY")
    xai_base_url: str = Field(
        default="https://api.x.ai/v1", alias="XAI_BASE_URL"
    )

    # ── Groq（極速推理 — LLaMA / Mixtral / Gemma）────────────
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1", alias="GROQ_BASE_URL"
    )

    # ── Mistral (Large / Medium / Codestral) ────────────────
    mistral_api_key: str = Field(default="", alias="MISTRAL_API_KEY")
    mistral_base_url: str = Field(
        default="https://api.mistral.ai/v1", alias="MISTRAL_BASE_URL"
    )

    # ── Cohere (Command R+ / Embed) ──────────────────────────
    cohere_api_key: str = Field(default="", alias="COHERE_API_KEY")
    cohere_base_url: str = Field(
        default="https://api.cohere.ai/v1", alias="COHERE_BASE_URL"
    )

    # ── Together AI (開源模型託管) ────────────────────────────
    together_api_key: str = Field(default="", alias="TOGETHER_API_KEY")
    together_base_url: str = Field(
        default="https://api.together.xyz/v1", alias="TOGETHER_BASE_URL"
    )

    # ── Fireworks AI (極速開源模型) ──────────────────────────
    fireworks_api_key: str = Field(default="", alias="FIREWORKS_API_KEY")
    fireworks_base_url: str = Field(
        default="https://api.fireworks.ai/inference/v1", alias="FIREWORKS_BASE_URL"
    )

    # ── Perplexity (搜尋增強 AI) ─────────────────────────────
    perplexity_api_key: str = Field(default="", alias="PERPLEXITY_API_KEY")
    perplexity_base_url: str = Field(
        default="https://api.perplexity.ai", alias="PERPLEXITY_BASE_URL"
    )

    # ── OpenRouter (統一入口 — 接入所有模型) ──────────────────
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL"
    )

    # ── Cerebras (極速 Wafer-Scale 推理) ─────────────────────
    cerebras_api_key: str = Field(default="", alias="CEREBRAS_API_KEY")
    cerebras_base_url: str = Field(
        default="https://api.cerebras.ai/v1", alias="CEREBRAS_BASE_URL"
    )

    # ── Hyperbolic (GPU 雲端推理) ────────────────────────────
    hyperbolic_api_key: str = Field(default="", alias="HYPERBOLIC_API_KEY")
    hyperbolic_base_url: str = Field(
        default="https://api.hyperbolic.xyz/v1", alias="HYPERBOLIC_BASE_URL"
    )

    # ── SiliconFlow (矽基流動 — 中國開源模型平台) ────────────
    siliconflow_api_key: str = Field(default="", alias="SILICONFLOW_API_KEY")
    siliconflow_base_url: str = Field(
        default="https://api.siliconflow.cn/v1", alias="SILICONFLOW_BASE_URL"
    )

    # ── MiniMax (海螺 AI) ────────────────────────────────────
    minimax_api_key: str = Field(default="", alias="MINIMAX_API_KEY")
    minimax_base_url: str = Field(
        default="https://api.minimax.chat/v1", alias="MINIMAX_BASE_URL"
    )
    minimax_group_id: str = Field(default="", alias="MINIMAX_GROUP_ID")

    # ── Moonshot (月之暗面 — Kimi) ──────────────────────────
    moonshot_api_key: str = Field(default="", alias="MOONSHOT_API_KEY")
    moonshot_base_url: str = Field(
        default="https://api.moonshot.cn/v1", alias="MOONSHOT_BASE_URL"
    )

    # ── Zhipu AI (智譜 — GLM-4) ─────────────────────────────
    zhipu_api_key: str = Field(default="", alias="ZHIPU_API_KEY")
    zhipu_base_url: str = Field(
        default="https://open.bigmodel.cn/api/paas/v4", alias="ZHIPU_BASE_URL"
    )

    # ── Yi (零一萬物 — Yi-Lightning) ─────────────────────────
    yi_api_key: str = Field(default="", alias="YI_API_KEY")
    yi_base_url: str = Field(
        default="https://api.lingyiwanwu.com/v1", alias="YI_BASE_URL"
    )

    # ── Baichuan (百川智能) ──────────────────────────────────
    baichuan_api_key: str = Field(default="", alias="BAICHUAN_API_KEY")
    baichuan_base_url: str = Field(
        default="https://api.baichuan-ai.com/v1", alias="BAICHUAN_BASE_URL"
    )

    # ── Stepfun (階躍星辰 — Step-2) ─────────────────────────
    stepfun_api_key: str = Field(default="", alias="STEPFUN_API_KEY")
    stepfun_base_url: str = Field(
        default="https://api.stepfun.com/v1", alias="STEPFUN_BASE_URL"
    )

    # ── NVIDIA (GLM-5) ───────────────────────────────────────
    nvidia_api_key: str = Field(default="", alias="NVIDIA_API_KEY")
    nvidia_base_url: str = Field(
        default="https://integrate.api.nvidia.com/v1", alias="NVIDIA_BASE_URL"
    )
    nvidia_model_name: str = Field(default="glm-5", alias="NVIDIA_MODEL_NAME")

    # ── OLLAMA 本地模型 ────────────────────────────────────────
    ollama_base_url: str = Field(
        default="http://localhost:11434/v1", alias="OLLAMA_BASE_URL"
    )
    ollama_enabled: bool = Field(default=False, alias="OLLAMA_ENABLED")
    ollama_default_model: str = Field(default="llama3.2", alias="OLLAMA_DEFAULT_MODEL")

    # ── OLLAMA 遠端模型（LAN PC）────────────────────────────────
    ollama_remote_enabled: bool = Field(default=False, alias="OLLAMA_REMOTE_ENABLED")
    ollama_remote_base_url: str = Field(
        default="http://192.168.1.151:11434/v1", alias="OLLAMA_REMOTE_BASE_URL"
    )
    ollama_remote_default_model: str = Field(default="qwen3:14b", alias="OLLAMA_REMOTE_DEFAULT_MODEL")

    # ── Custom OpenAI-compatible Endpoint ─────────────────────
    # 可接入 LM Studio / vLLM / 其他自架服務
    custom_model_base_url: str = Field(default="", alias="CUSTOM_MODEL_BASE_URL")
    custom_model_api_key: str = Field(default="", alias="CUSTOM_MODEL_API_KEY")
    custom_model_name: str = Field(default="custom", alias="CUSTOM_MODEL_NAME")

    # ── Federation (ArcMind ↔ ArcMind 跨實例協作) ──────────
    federation_enabled: bool = Field(default=False, alias="FEDERATION_ENABLED")
    federation_instance_id: str = Field(default="arcmind-main", alias="FEDERATION_INSTANCE_ID")
    federation_api_key: str = Field(default="", alias="FEDERATION_API_KEY")
    federation_peers: str = Field(default="", alias="FEDERATION_PEERS")  # 逗號分隔 URLs
    federation_timeout: int = Field(default=120, alias="FEDERATION_TIMEOUT")  # 秒

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
        extra = "ignore"  # 忽略 .env 中未定義的欄位（避免 ValidationError）

    def model_post_init(self, __context):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        (self.evidence_dir / "logs").mkdir(exist_ok=True)

    # ── 快速查詢哪些 provider 有 key ─────────────────────────

    # 所有 OpenAI-compatible providers（有 key + base_url 就能接入）
    _OPENAI_COMPATIBLE = [
        ("deepseek",    "deepseek_api_key"),
        ("xai",         "xai_api_key"),
        ("groq",        "groq_api_key"),
        ("mistral",     "mistral_api_key"),
        ("cohere",      "cohere_api_key"),
        ("together",    "together_api_key"),
        ("fireworks",   "fireworks_api_key"),
        ("perplexity",  "perplexity_api_key"),
        ("openrouter",  "openrouter_api_key"),
        ("cerebras",    "cerebras_api_key"),
        ("hyperbolic",  "hyperbolic_api_key"),
        ("siliconflow", "siliconflow_api_key"),
        ("minimax",     "minimax_api_key"),
        ("moonshot",    "moonshot_api_key"),
        ("zhipu",       "zhipu_api_key"),
        ("yi",          "yi_api_key"),
        ("baichuan",    "baichuan_api_key"),
        ("stepfun",     "stepfun_api_key"),
        ("nvidia",      "nvidia_api_key"),
    ]

    def available_providers(self) -> list[str]:
        providers = []
        # 原生 SDK providers
        if self.anthropic_api_key:
            providers.append("anthropic")
        if self.openai_api_key:
            providers.append("openai")
        if self.google_api_key:
            providers.append("google")
        # OpenAI-compatible providers
        for name, key_attr in self._OPENAI_COMPATIBLE:
            if getattr(self, key_attr, ""):
                providers.append(name)
        # Local models
        if self.ollama_enabled:
            providers.append("ollama")
        if self.ollama_remote_enabled:
            providers.append("ollama_remote")
        if self.custom_model_base_url:
            providers.append("custom")
        return providers

    def get_provider_config(self, provider: str) -> dict:
        """取得指定 provider 的完整配置（key + base_url）"""
        configs = {
            "anthropic":   {"api_key": self.anthropic_api_key,   "base_url": self.anthropic_base_url},
            "openai":      {"api_key": self.openai_api_key,      "base_url": self.openai_base_url},
            "google":      {"api_key": self.google_api_key,      "base_url": self.google_base_url},
            "deepseek":    {"api_key": self.deepseek_api_key,    "base_url": self.deepseek_base_url},
            "xai":         {"api_key": self.xai_api_key,         "base_url": self.xai_base_url},
            "groq":        {"api_key": self.groq_api_key,        "base_url": self.groq_base_url},
            "mistral":     {"api_key": self.mistral_api_key,     "base_url": self.mistral_base_url},
            "cohere":      {"api_key": self.cohere_api_key,      "base_url": self.cohere_base_url},
            "together":    {"api_key": self.together_api_key,    "base_url": self.together_base_url},
            "fireworks":   {"api_key": self.fireworks_api_key,   "base_url": self.fireworks_base_url},
            "perplexity":  {"api_key": self.perplexity_api_key,  "base_url": self.perplexity_base_url},
            "openrouter":  {"api_key": self.openrouter_api_key,  "base_url": self.openrouter_base_url},
            "cerebras":    {"api_key": self.cerebras_api_key,    "base_url": self.cerebras_base_url},
            "hyperbolic":  {"api_key": self.hyperbolic_api_key,  "base_url": self.hyperbolic_base_url},
            "siliconflow": {"api_key": self.siliconflow_api_key, "base_url": self.siliconflow_base_url},
            "minimax":     {"api_key": self.minimax_api_key,     "base_url": self.minimax_base_url,
                           "group_id": self.minimax_group_id},
            "moonshot":    {"api_key": self.moonshot_api_key,    "base_url": self.moonshot_base_url},
            "zhipu":       {"api_key": self.zhipu_api_key,       "base_url": self.zhipu_base_url},
            "yi":          {"api_key": self.yi_api_key,          "base_url": self.yi_base_url},
            "baichuan":    {"api_key": self.baichuan_api_key,    "base_url": self.baichuan_base_url},
            "stepfun":     {"api_key": self.stepfun_api_key,     "base_url": self.stepfun_base_url},
            "nvidia":      {"api_key": self.nvidia_api_key,       "base_url": self.nvidia_base_url,
                           "model": self.nvidia_model_name},
            "ollama":      {"base_url": self.ollama_base_url,    "model": self.ollama_default_model},
            "ollama_remote": {"base_url": self.ollama_remote_base_url, "model": self.ollama_remote_default_model},
            "custom":      {"api_key": self.custom_model_api_key, "base_url": self.custom_model_base_url,
                           "model": self.custom_model_name},
        }
        return configs.get(provider, {})


settings = Settings()
