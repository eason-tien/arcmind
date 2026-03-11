"""
ArcMind 多 Provider 模型路由引擎
支援所有主流雲端 API 與 OLLAMA 本地模型。

Provider 格式：  "provider:model_id"
  anthropic:claude-sonnet-4-6
  openai:gpt-4o
  openai:gpt-4o-mini
  codex:o3                             ← Codex CLI OAuth (訂閱制)
  google:gemini-2.0-flash
  groq:llama-3.1-70b-versatile        ← OpenAI-compatible
  mistral:mistral-large-latest         ← OpenAI-compatible
  ollama:llama3.2                      ← 本地，OpenAI-compatible
  ollama:qwen2.5:7b                    ← 本地，OpenAI-compatible
  custom:my-model                      ← 自訂 base_url，OpenAI-compatible
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from config.settings import settings

logger = logging.getLogger("arcmind.model_router")


# ── Codex CLI OAuth Token Reader ──────────────────────────────────────────────

def _read_codex_token() -> str:
    """
    Read OAuth token from Codex CLI auth store (~/.codex/auth.json).
    Returns the access token string, or empty string if not found.
    """
    auth_path = Path.home() / ".codex" / "auth.json"
    if not auth_path.exists():
        return ""
    try:
        data = json.loads(auth_path.read_text())
        # Codex auth.json schema:
        #   {tokens: {access_token, id_token, refresh_token}, OPENAI_API_KEY, auth_mode}
        tokens = data.get("tokens", {})
        token = ""
        if isinstance(tokens, dict):
            token = tokens.get("access_token", "") or tokens.get("id_token", "")
        if not token:
            # Fallback: maybe a flat layout or explicit API key
            token = (
                data.get("OPENAI_API_KEY")
                or data.get("token")
                or data.get("access_token")
                or ""
            )
        if token and token != "None":
            logger.info("[Codex] OAuth token loaded from %s", auth_path)
            return token
        return ""
    except Exception as e:
        logger.warning("[Codex] Failed to read auth.json: %s", e)
        return ""


# ── 回傳格式 ─────────────────────────────────────────────────────────────────

@dataclass
class ModelResponse:
    model: str
    provider: str
    content: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    stop_reason: str


# ── Provider 抽象基底 ─────────────────────────────────────────────────────────

class BaseProvider:
    name: str = "base"

    def complete(self, model: str, messages: list[dict],
                 system: str | None, max_tokens: int) -> ModelResponse:
        raise NotImplementedError


# ── Anthropic Provider ────────────────────────────────────────────────────────

class AnthropicProvider(BaseProvider):
    name = "anthropic"

    def __init__(self):
        import anthropic as _anthropic
        self._client = _anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=90.0,  # 90s — 比默認 600s 合理得多
        )

    def complete(self, model: str, messages: list[dict],
                 system: str | None, max_tokens: int) -> ModelResponse:
        import anthropic as _anthropic
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        resp = self._client.messages.create(**kwargs)
        content = "".join(b.text for b in resp.content if hasattr(b, "text"))
        return ModelResponse(
            model=model,
            provider=self.name,
            content=content,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            total_tokens=resp.usage.input_tokens + resp.usage.output_tokens,
            stop_reason=resp.stop_reason or "end_turn",
        )


# ── OpenAI-compatible Provider (OpenAI / Groq / Mistral / OLLAMA / custom) ───

class OpenAICompatibleProvider(BaseProvider):
    """
    使用 openai 套件呼叫任何 OpenAI-compatible API。
    透過 base_url 切換到 Groq / Mistral / OLLAMA 等服務。
    """

    def __init__(self, provider_name: str, api_key: str,
                 base_url: str | None = None):
        from openai import OpenAI
        import httpx as _httpx
        self.name = provider_name
        # 分離 connect / read timeout：
        #   connect: 連線建立不應超過 10s（網路問題就快速失敗）
        #   read: LLM 推理時間，雲端 API 90s，本地 120s
        _is_local = provider_name in ("ollama", "ollama_remote")
        _read_timeout = 120.0 if _is_local else 90.0
        self._client = OpenAI(
            api_key=api_key or "not-needed",
            base_url=base_url,
            timeout=_httpx.Timeout(
                connect=10.0,       # 快速偵測連線失敗
                read=_read_timeout,  # LLM 推理等待
                write=10.0,         # 上傳 prompt 不應太慢
                pool=10.0,          # 連線池等待
            ),
        )

    def complete(self, model: str, messages: list[dict],
                 system: str | None, max_tokens: int) -> ModelResponse:
        # 把 system 插入 messages 最前面
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        resp = self._client.chat.completions.create(
            model=model,
            messages=full_messages,
            max_tokens=max_tokens,
        )
        choice = resp.choices[0]
        content = choice.message.content or ""
        usage = resp.usage
        in_tok = usage.prompt_tokens if usage else 0
        out_tok = usage.completion_tokens if usage else 0

        return ModelResponse(
            model=model,
            provider=self.name,
            content=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=in_tok + out_tok,
            stop_reason=choice.finish_reason or "stop",
        )


# ── Google Gemini Provider ────────────────────────────────────────────────────

class GoogleProvider(BaseProvider):
    name = "google"

    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=settings.google_api_key)
        self._genai = genai

    def complete(self, model: str, messages: list[dict],
                 system: str | None, max_tokens: int) -> ModelResponse:
        # 轉換 messages → Gemini 格式
        history = []
        last_user = ""
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            text = m["content"] if isinstance(m["content"], str) else str(m["content"])
            if role == "user":
                last_user = text
                if len(messages) > 1:
                    history.append({"role": "user", "parts": [text]})
            else:
                history.append({"role": "model", "parts": [text]})

        # 最後一條 user 訊息不加入 history，直接當 prompt
        if history and history[-1]["role"] == "user":
            last_user = history.pop()["parts"][0]

        gen_model = self._genai.GenerativeModel(
            model_name=model,
            system_instruction=system or "",
        )
        if history:
            chat = gen_model.start_chat(history=history)
            resp = chat.send_message(last_user)
        else:
            resp = gen_model.generate_content(last_user)

        content = resp.text or ""
        # Gemini 不一定提供 token count
        try:
            in_tok = resp.usage_metadata.prompt_token_count
            out_tok = resp.usage_metadata.candidates_token_count
        except Exception:
            in_tok = out_tok = 0

        return ModelResponse(
            model=model,
            provider=self.name,
            content=content,
            input_tokens=in_tok,
            output_tokens=out_tok,
            total_tokens=in_tok + out_tok,
            stop_reason="stop",
        )


# ── 路由規則 ──────────────────────────────────────────────────────────────────

@dataclass
class RoutingRules:
    default: str = "anthropic:claude-sonnet-4-6"
    task_type_rules: list[dict] = field(default_factory=list)
    budget_rules: list[dict] = field(default_factory=list)
    fallback_chain: list[str] = field(default_factory=list)
    providers: dict = field(default_factory=dict)  # provider config

    @classmethod
    def load(cls, path) -> "RoutingRules":
        try:
            with open(path, "r") as f:
                data = yaml.safe_load(f)
            return cls(
                default=data.get("default", "anthropic:claude-sonnet-4-6"),
                task_type_rules=data.get("task_type_rules", []),
                budget_rules=data.get("budget_rules", []),
                fallback_chain=data.get("fallback_chain", []),
                providers=data.get("providers", {}),
            )
        except Exception as e:
            logger.warning("Failed to load routing rules: %s. Using defaults.", e)
            return cls()


# ── ModelRouter ───────────────────────────────────────────────────────────────

class ModelRouter:
    """
    多 Provider 模型路由器。
    model 格式：  "provider:model_id"
    支援：anthropic / openai / codex / google / groq / mistral / ollama / custom
    """

    # 預設 max_tokens（若規則未指定）
    _DEFAULT_MAX: dict[str, int] = {
        "anthropic:claude-opus-4-6": 8192,
        "anthropic:claude-sonnet-4-6": 4096,
        "anthropic:claude-haiku-4-5-20251001": 2048,
        "openai:gpt-4o": 4096,
        "openai:gpt-4o-mini": 4096,
        "openai:gpt-4.5-preview": 8192,
        "openai:gpt-5.4": 16384,
        "openai:o1": 8192,
        "openai:o3": 8192,
        "openai:o3-mini": 4096,
        "openai:o4-mini": 4096,
        "google:gemini-2.0-flash": 4096,
        "google:gemini-2.0-flash-lite": 2048,
        "google:gemini-1.5-pro": 8192,
        "groq:llama-3.3-70b-versatile": 4096,
        "groq:llama-3.1-8b-instant": 2048,
        "mistral:mistral-large-latest": 4096,
        "mistral:mistral-small-latest": 2048,
        # ollama 本地模型沒有強制上限，預設 4096
    }

    def __init__(self):
        self._rules = RoutingRules.load(settings.routing_rules_path)
        self._providers: dict[str, BaseProvider] = {}
        self._init_providers()

    def _init_providers(self) -> None:
        """依據 settings 初始化已有 API key 的 provider"""

        # Anthropic
        if settings.anthropic_api_key:
            try:
                self._providers["anthropic"] = AnthropicProvider()
                logger.info("Provider ready: anthropic")
            except Exception as e:
                logger.warning("Anthropic init failed: %s", e)

        # OpenAI (API Key)
        if settings.openai_api_key:
            try:
                self._providers["openai"] = OpenAICompatibleProvider(
                    "openai", settings.openai_api_key,
                    base_url="https://api.openai.com/v1",
                )
                logger.info("Provider ready: openai (API Key)")
            except Exception as e:
                logger.warning("OpenAI init failed: %s", e)

        # OpenAI Codex CLI (OAuth — 當 OPENAI_API_KEY 未設時的備選)
        if settings.codex_enabled and "openai" not in self._providers:
            codex_token = _read_codex_token()
            if codex_token:
                try:
                    provider = OpenAICompatibleProvider(
                        "codex", codex_token,
                        base_url="https://api.openai.com/v1",
                    )
                    self._providers["codex"] = provider
                    # 同時註冊為 openai，讓 openai:gpt-4o 路由也能走 Codex token
                    self._providers["openai"] = provider
                    logger.info("Provider ready: codex (OAuth via ~/.codex/auth.json)")
                except Exception as e:
                    logger.warning("Codex OAuth init failed: %s", e)

        # Google Gemini
        if settings.google_api_key:
            try:
                self._providers["google"] = GoogleProvider()
                logger.info("Provider ready: google")
            except Exception as e:
                logger.warning("Google init failed: %s", e)

        # Groq
        if settings.groq_api_key:
            try:
                self._providers["groq"] = OpenAICompatibleProvider(
                    "groq", settings.groq_api_key,
                    base_url="https://api.groq.com/openai/v1",
                )
                logger.info("Provider ready: groq")
            except Exception as e:
                logger.warning("Groq init failed: %s", e)

        # Mistral
        if settings.mistral_api_key:
            try:
                self._providers["mistral"] = OpenAICompatibleProvider(
                    "mistral", settings.mistral_api_key,
                    base_url="https://api.mistral.ai/v1",
                )
                logger.info("Provider ready: mistral")
            except Exception as e:
                logger.warning("Mistral init failed: %s", e)

        # OLLAMA（本地，需 OLLAMA_ENABLED=true）
        if settings.ollama_enabled:
            try:
                self._providers["ollama"] = OpenAICompatibleProvider(
                    "ollama", "ollama",  # api_key 任意值，OLLAMA 不驗證
                    base_url=settings.ollama_base_url,
                )
                logger.info("Provider ready: ollama (%s)", settings.ollama_base_url)
            except Exception as e:
                logger.warning("OLLAMA init failed: %s", e)

        # Custom（自訂 endpoint，OpenAI-compatible）
        if settings.custom_model_base_url:
            try:
                self._providers["custom"] = OpenAICompatibleProvider(
                    "custom",
                    settings.custom_model_api_key or "not-needed",
                    base_url=settings.custom_model_base_url,
                )
                logger.info("Provider ready: custom (%s)", settings.custom_model_base_url)
            except Exception as e:
                logger.warning("Custom provider init failed: %s", e)

        # ── 動態載入所有 OpenAI-compatible 新 Providers (DeepSeek, xAI, Kimi, 等 16 家) ──
        for pname, key_attr in settings._OPENAI_COMPATIBLE:
            api_key = getattr(settings, key_attr, "")
            if api_key:
                try:
                    cfg = settings.get_provider_config(pname)
                    base_url = cfg.get("base_url")
                    self._providers[pname] = OpenAICompatibleProvider(
                        pname, api_key, base_url=base_url
                    )
                    logger.info("Provider ready: %s (%s)", pname, base_url)
                except Exception as e:
                    logger.warning("Provider init failed for %s: %s", pname, e)

        # 自訂 provider（來自 routing_rules.yaml 的 providers 區塊）
        for pname, pconf in self._rules.providers.items():
            if pname in self._providers:
                continue
            try:
                self._providers[pname] = OpenAICompatibleProvider(
                    pname,
                    pconf.get("api_key", ""),
                    base_url=pconf.get("base_url"),
                )
                logger.info("Provider ready: %s (from routing_rules)", pname)
            except Exception as e:
                logger.warning("Custom provider %s init failed: %s", pname, e)

        if not self._providers:
            logger.warning("No providers initialized. Check API keys in .env")

    # ── 解析 model string ─────────────────────────────────────────────────────

    def _parse_model(self, model_str: str) -> tuple[str, str]:
        """
        解析 "provider:model_id" → (provider, model_id)
        沒有 : 前綴時，根據 model_str 自動判斷 provider。
        """
        if ":" in model_str:
            provider, model_id = model_str.split(":", 1)
            return provider.lower(), model_id

        # 自動推斷
        m = model_str.lower()
        if m.startswith("claude"):
            return "anthropic", model_str
        if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4"):
            return "openai", model_str
        if m.startswith("gemini"):
            return "google", model_str
        if m.startswith("llama") or m.startswith("mixtral") or m.startswith("gemma"):
            # 若 ollama 可用則用 ollama，否則嘗試 groq
            if "ollama" in self._providers:
                return "ollama", model_str
            return "groq", model_str
        if m.startswith("mistral") or m.startswith("codestral"):
            return "mistral", model_str

        # 最後 fallback：用 default provider
        # 為避免無窮迴圈（若 self._rules.default 也無法解析），傳遞防護標記
        if model_str == self._rules.default:
            # 已經是 default 本身，直接給一個安全的回退值
            return "anthropic", model_str
            
        default_provider, _ = self._parse_model(self._rules.default)
        return default_provider, model_str
    # ── 選擇模型 ──────────────────────────────────────────────────────────────

    def select_model(self, task_type: str = "general",
                     budget: str = "medium") -> tuple[str, int]:
        """
        回傳 (full_model_str, max_tokens)。
        full_model_str 格式：  "provider:model_id"
        """
        # Task type rules
        for rule in self._rules.task_type_rules:
            if task_type in rule.get("match", []):
                m = rule.get("model") or self._rules.default
                max_tok = rule.get("max_tokens", self._DEFAULT_MAX.get(m, 4096))
                # 確認 provider 可用，否則跳過
                provider, _ = self._parse_model(m)
                if provider in self._providers:
                    return m, max_tok

        # Budget rules
        for rule in self._rules.budget_rules:
            if rule.get("budget") == budget:
                m = rule.get("model") or self._rules.default
                provider, _ = self._parse_model(m)
                if provider in self._providers:
                    return m, self._DEFAULT_MAX.get(m, 4096)

        # Default
        m = self._rules.default
        provider, _ = self._parse_model(m)
        if provider in self._providers:
            return m, self._DEFAULT_MAX.get(m, 4096)

        # Last resort: first available provider's first known model
        if self._providers:
            first_pname = next(iter(self._providers))
            fallback = {
                "anthropic": "anthropic:claude-sonnet-4-6",
                "openai": "openai:gpt-4o-mini",
                "google": "google:gemini-2.0-flash",
                "groq": "groq:llama-3.3-70b-versatile",
                "mistral": "mistral:mistral-small-latest",
                "ollama": f"ollama:{settings.ollama_default_model}",
                "custom": f"custom:{settings.custom_model_name}",
            }.get(first_pname, f"{first_pname}:default")
            return fallback, 4096

        raise RuntimeError("No AI providers available. Please set at least one API key.")

    # ── 呼叫模型 ──────────────────────────────────────────────────────────────

    def complete(self, prompt: str, system: str | None = None,
                 task_type: str = "general", budget: str = "medium",
                 messages: list[dict] | None = None,
                 model: str | None = None,
                 max_tokens: int | None = None) -> ModelResponse:
        """
        呼叫模型，自動選 provider 並在失敗時走 fallback 鏈。

        model 參數：可指定 "provider:model_id"，否則自動按 task_type/budget 選擇。
        """
        chosen = model or self.select_model(task_type, budget)[0]
        final_max = max_tokens or self._DEFAULT_MAX.get(chosen, 4096)

        msg_list = messages if messages else [{"role": "user", "content": prompt}]

        # 建立 fallback 鏈
        chain = self._build_fallback_chain(chosen)

        last_error = None
        for m_str in chain:
            provider_name, model_id = self._parse_model(m_str)
            provider = self._providers.get(provider_name)
            if not provider:
                continue
            try:
                logger.info("Calling %s model=%s payload=msg_list=%s system=%s", provider_name, model_id, msg_list, system)
                return provider.complete(model_id, msg_list, system, final_max)

            except Exception as e:
                logger.warning("%s/%s failed: %s. Trying next.", provider_name, model_id, e)
                last_error = e
                continue

        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    def _build_fallback_chain(self, primary: str) -> list[str]:
        chain = [primary]
        for m in self._rules.fallback_chain:
            if m != primary:
                chain.append(m)
        return chain

    # ── 快速分類 ──────────────────────────────────────────────────────────────

    def quick_classify(self, text: str, categories: list[str]) -> str:
        cats = ", ".join(categories)
        prompt = (
            f"Classify the following text into ONE of these categories: {cats}\n\n"
            f"Text: {text}\n\n"
            f"Reply with ONLY the category name, nothing else."
        )
        resp = self.complete(prompt, task_type="classify", budget="low")
        result = resp.content.strip()
        for c in categories:
            if c.lower() in result.lower():
                return c
        return categories[0]

    # ── 查詢可用 providers ────────────────────────────────────────────────────

    def list_providers(self) -> list[dict]:
        return [
            {"provider": name, "type": type(p).__name__}
            for name, p in self._providers.items()
        ]

    def is_provider_available(self, provider: str) -> bool:
        return provider in self._providers


# 全域單例
model_router = ModelRouter()
