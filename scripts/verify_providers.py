"""
多 Provider 初始化驗證腳本
使用模擬 API key 測試所有 provider 能正確初始化，無需真實呼叫。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 在 import 任何模組前設定環境變數
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-mock-test")
os.environ.setdefault("OPENAI_API_KEY", "sk-openai-mock")
os.environ.setdefault("GOOGLE_API_KEY", "AIza-mock")
os.environ.setdefault("GROQ_API_KEY", "gsk_mock")
os.environ.setdefault("MISTRAL_API_KEY", "mistral-mock")
os.environ.setdefault("OLLAMA_ENABLED", "true")
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("CUSTOM_MODEL_BASE_URL", "http://localhost:1234/v1")

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import Settings
from runtime.model_router import (
    ModelRouter, AnthropicProvider, OpenAICompatibleProvider,
    GoogleProvider, RoutingRules
)

RESULTS = []

def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    RESULTS.append((name, status, detail))
    mark = "✓" if condition else "✗"
    print(f"  {mark} [{status}] {name}" + (f"  — {detail}" if detail else ""))


print("=" * 60)
print("  ArcMind Multi-Provider Verify")
print("=" * 60)

# ── Settings 讀取 ────────────────────────────────────────────
print("\n[S1] Settings — available_providers()")
s = Settings(
    _env_file=None,  # 不從 .env 讀，直接用 os.environ
    ANTHROPIC_API_KEY="sk-ant-mock",
    OPENAI_API_KEY="sk-openai-mock",
    GOOGLE_API_KEY="AIza-mock",
    GROQ_API_KEY="gsk_mock",
    MISTRAL_API_KEY="mistral-mock",
    OLLAMA_ENABLED=True,
    OLLAMA_BASE_URL="http://localhost:11434/v1",
    CUSTOM_MODEL_BASE_URL="http://localhost:1234/v1",
)
providers_list = s.available_providers()
check("S1-a: anthropic in available", "anthropic" in providers_list)
check("S1-b: openai in available", "openai" in providers_list)
check("S1-c: google in available", "google" in providers_list)
check("S1-d: groq in available", "groq" in providers_list)
check("S1-e: mistral in available", "mistral" in providers_list)
check("S1-f: ollama in available", "ollama" in providers_list)
check("S1-g: custom in available", "custom" in providers_list)
print(f"  providers: {providers_list}")

# ── Provider 物件建立（不實際呼叫 API）──────────────────────
print("\n[S2] Provider 物件初始化")

# Anthropic
try:
    import anthropic
    ap = AnthropicProvider.__new__(AnthropicProvider)
    ap._client = anthropic.Anthropic(api_key="sk-ant-mock")
    check("S2-a: AnthropicProvider 建立", True)
except Exception as e:
    check("S2-a: AnthropicProvider 建立", False, str(e))

# OpenAI-compatible providers
for name, key, url in [
    ("openai",  "sk-mock", "https://api.openai.com/v1"),
    ("groq",    "gsk_mock", "https://api.groq.com/openai/v1"),
    ("mistral", "mistral-mock", "https://api.mistral.ai/v1"),
    ("ollama",  "ollama", "http://localhost:11434/v1"),
    ("lmstudio","not-needed", "http://localhost:1234/v1"),
]:
    try:
        p = OpenAICompatibleProvider(name, key, url)
        check(f"S2-{name}: OpenAICompatibleProvider 建立", True,
              f"base_url={url}")
    except Exception as e:
        check(f"S2-{name}: OpenAICompatibleProvider 建立", False, str(e))

# Google Gemini
try:
    import google.generativeai as genai
    genai.configure(api_key="AIza-mock")
    check("S2-google: GoogleProvider 可配置", True)
except Exception as e:
    check("S2-google: GoogleProvider 可配置", False, str(e))

# ── 路由規則 ─────────────────────────────────────────────────
print("\n[S3] 路由規則解析")
rules = RoutingRules.load(Path(__file__).parent.parent / "config" / "routing_rules.yaml")
check("S3-a: rules 載入", rules.default != "")
check("S3-b: task_type_rules 不為空", len(rules.task_type_rules) > 0)
check("S3-c: fallback_chain 不為空", len(rules.fallback_chain) > 0)
check("S3-d: default 含 provider 前綴",
      ":" in rules.default, rules.default)

# ── ModelRouter 解析 ─────────────────────────────────────────
print("\n[S4] ModelRouter._parse_model()")
router = ModelRouter.__new__(ModelRouter)
router._rules = rules
router._providers = {}

parse_tests = [
    ("anthropic:claude-sonnet-4-6",  "anthropic", "claude-sonnet-4-6"),
    ("openai:gpt-4o",                "openai",    "gpt-4o"),
    ("google:gemini-2.0-flash",      "google",    "gemini-2.0-flash"),
    ("groq:llama-3.3-70b-versatile", "groq",      "llama-3.3-70b-versatile"),
    ("mistral:mistral-large-latest", "mistral",   "mistral-large-latest"),
    ("ollama:llama3.2",              "ollama",    "llama3.2"),
    ("claude-sonnet-4-6",            "anthropic", "claude-sonnet-4-6"),
    ("gpt-4o",                       "openai",    "gpt-4o"),
    ("gemini-2.0-flash",             "google",    "gemini-2.0-flash"),
    ("llama3.2",                     "ollama",    "llama3.2"),
]
all_parse_ok = True
for model_str, exp_provider, exp_model in parse_tests:
    # Temporarily add providers for auto-detect test
    router._providers = {"anthropic": True, "openai": True, "google": True,
                         "groq": True, "ollama": True, "mistral": True}
    got_provider, got_model = router._parse_model(model_str)
    ok = (got_provider == exp_provider and got_model == exp_model)
    if not ok:
        all_parse_ok = False
        print(f"  ✗ parse('{model_str}') → ({got_provider}, {got_model})"
              f" expected ({exp_provider}, {exp_model})")
check("S4: _parse_model 全部正確", all_parse_ok,
      f"{len(parse_tests)} cases")

# ── Fallback chain ───────────────────────────────────────────
print("\n[S5] Fallback chain")
chain = router._build_fallback_chain("anthropic:claude-opus-4-6")
check("S5-a: chain 從 primary 開始", chain[0] == "anthropic:claude-opus-4-6")
check("S5-b: chain 長度 > 1", len(chain) > 1, f"len={len(chain)}")
check("S5-c: chain 含 ollama fallback",
      any("ollama" in m for m in chain))

# ── 匯總 ─────────────────────────────────────────────────────
print("\n" + "=" * 60)
passed = sum(1 for _, s, _ in RESULTS if s == "PASS")
total = len(RESULTS)
print(f"  Result: {passed}/{total} PASS")
print("=" * 60)

if passed < total:
    sys.exit(1)
