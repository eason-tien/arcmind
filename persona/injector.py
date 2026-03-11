# -*- coding: utf-8 -*-
"""
ArcMind Persona — Prompt Injector
===================================
將人格層級注入到 LLM prompt 中，整合會話歷史和記憶。

OpenClaw 風格的分層注入順序：
1. SOUL.md     → system prompt 最前面（身份基底）
2. AGENTS.md   → 行為指南
3. TOOLS.md    → 可用工具/環境描述
4. USER.md     → 使用者偏好
5. Context     → 會話歷史壓縮/記憶
"""
from __future__ import annotations

import logging
from typing import Any

from persona.loader import persona_loader

logger = logging.getLogger("arcmind.persona.injector")


class PersonaInjector:
    """
    Construct the full system prompt by layering persona files + context.
    """

    def __init__(self):
        self.loader = persona_loader

    def build_system_prompt(
        self,
        context_summary: str = "",
        extra_instructions: str = "",
        agent_type: str = "main",
        compact: bool = True,
    ) -> str:
        """
        Build the complete system prompt with layered injection.

        compact=True (default):
          - SOUL_COMPACT.md (~800 chars) instead of full SOUL.md (9KB)
          - NO TOOLS.md (19KB) — tools exposed via function calling schema
          - NO AGENTS.md (9KB) — delegation handled by Delegator system
          Total: ~2-4KB instead of 37KB+

        compact=False:
          - Legacy mode: full SOUL + AGENTS + TOOLS (37KB)
          - Only used when explicitly requested

        Returns:
            Full system prompt string.
        """
        sections = []

        # Layer 1: SOUL (identity foundation)
        soul = self.loader.get_soul(compact=compact)
        if soul:
            sections.append(soul)

        if not compact:
            # Layer 2: AGENTS (behavioral rules) — only in full mode
            agents = self.loader.get_agents()
            if agents:
                sections.append(agents)

            # Layer 3: TOOLS (environment/capabilities) — only in full mode
            tools = self.loader.get_tools()
            if tools:
                sections.append(tools)

        # Layer 4: USER (user preferences)
        user = self.loader.get_user()
        if user:
            sections.append(f"## User Profile\n{user}")

        # Layer 5: Context (session state)
        if context_summary:
            sections.append(f"## Current Context\n{context_summary}")

        # Layer 6: Extra instructions (per-request overrides)
        if extra_instructions:
            sections.append(f"## Additional Instructions\n{extra_instructions}")

        # Agent type hint
        if agent_type != "main":
            sections.append(
                f"## Agent Mode\nYou are operating as the `{agent_type}` agent."
            )

        prompt = "\n\n---\n\n".join(sections)

        logger.debug("[PersonaInjector] built system prompt: %d chars, %d layers, compact=%s",
                      len(prompt), len(sections), compact)
        return prompt

    def build_messages(
        self,
        user_text: str,
        history: list[dict] | None = None,
        context_summary: str = "",
        agent_type: str = "main",
        max_history: int = 20,
    ) -> list[dict]:
        """
        Build complete message list for LLM API call.

        Returns:
            List of {role, content} dicts ready for API call.
        """
        messages = []

        # System prompt
        system_prompt = self.build_system_prompt(
            context_summary=context_summary,
            agent_type=agent_type,
        )
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Conversation history (trimmed)
        if history:
            for turn in history[-max_history:]:
                role = turn.get("role", "user")
                content = turn.get("content", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # Current user message (if not already in history)
        if not history or history[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})

        return messages

    def status(self) -> dict:
        return {
            "loader": self.loader.status(),
            "sample_prompt_length": len(self.build_system_prompt()),
        }


# ── Singleton ──
persona_injector = PersonaInjector()
