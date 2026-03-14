# -*- coding: utf-8 -*-
"""
ArcMind — Agent Template Library
==================================
CEO 按需從模板庫聘用 Agent（不預裝）。

用法：
  from runtime.agent_templates import template_manager

  # 查看可用模板
  templates = template_manager.list_templates()

  # 聘用 Agent
  result = template_manager.hire("security")

  # 解僱 Agent
  result = template_manager.fire("security")
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from runtime.agent_registry import agent_registry, AgentPersona

logger = logging.getLogger("arcmind.agent_templates")

_TEMPLATES_PATH = Path(__file__).parent.parent / "config" / "agent_templates.json"


@dataclass
class AgentTemplate:
    """A template for hiring an agent on demand."""
    template_id: str
    name: str
    model: str
    purpose: str
    capabilities: List[str]
    allowed_tools: List[str]
    system_prompt: str
    category: str


class TemplateManager:
    """
    Manages the agent template library.
    CEO can hire (instantiate) or fire (remove) agents from templates.
    """

    def __init__(self):
        self._templates: Dict[str, AgentTemplate] = {}
        self._load_templates()

    def _load_templates(self) -> None:
        if not _TEMPLATES_PATH.exists():
            logger.warning("agent_templates.json not found at %s", _TEMPLATES_PATH)
            return
        try:
            data = json.loads(_TEMPLATES_PATH.read_text(encoding="utf-8"))
            for t in data.get("templates", []):
                tmpl = AgentTemplate(
                    template_id=t["template_id"],
                    name=t.get("name", t["template_id"]),
                    model=t.get("model", "claude"),
                    purpose=t.get("purpose", ""),
                    capabilities=t.get("capabilities", []),
                    allowed_tools=t.get("allowed_tools", ["__all__"]),
                    system_prompt=t.get("system_prompt", ""),
                    category=t.get("category", "general"),
                )
                self._templates[tmpl.template_id] = tmpl
            logger.info("Loaded %d agent templates", len(self._templates))
        except Exception as e:
            logger.error("Failed to load agent_templates.json: %s", e)

    # ── Query ─────────────────────────────────────────────────────────────────

    def list_templates(self) -> List[dict]:
        """List all available templates with hire status."""
        hired_ids = set(agent_registry.list_roles())
        result = []
        for t in self._templates.values():
            result.append({
                "template_id": t.template_id,
                "name": t.name,
                "model": t.model,
                "purpose": t.purpose,
                "capabilities": t.capabilities,
                "category": t.category,
                "hired": t.template_id in hired_ids,
            })
        return result

    def list_by_category(self, category: str) -> List[dict]:
        """List templates filtered by category."""
        return [t for t in self.list_templates() if t["category"] == category]

    def get_template(self, template_id: str) -> Optional[AgentTemplate]:
        return self._templates.get(template_id)

    def find_by_capability(self, capability: str) -> List[AgentTemplate]:
        """Find templates that match a capability (for CEO auto-hire)."""
        return [
            t for t in self._templates.values()
            if capability in t.capabilities
        ]

    # ── Hire / Fire ───────────────────────────────────────────────────────────

    def hire(self, template_id: str, custom_model: Optional[str] = None) -> dict:
        """
        Hire an agent from template → register in agent_registry + persist.
        Returns status dict.
        """
        tmpl = self._templates.get(template_id)
        if not tmpl:
            return {"success": False, "error": f"Template '{template_id}' not found"}

        # Check if already hired
        existing = agent_registry.get(template_id)
        if existing:
            return {"success": False, "error": f"Agent '{template_id}' already hired"}

        model = custom_model or tmpl.model
        result_msg = agent_registry.add_agent(
            agent_id=tmpl.template_id,
            name=tmpl.name,
            model=model,
            purpose=tmpl.purpose,
            capabilities=tmpl.capabilities,
            system_prompt=tmpl.system_prompt,
        )

        # Update allowed_tools (add_agent sets __all__, override with template)
        persona = agent_registry.get(template_id)
        if persona:
            persona.allowed_tools = tmpl.allowed_tools
            agent_registry.save_config()

        logger.info("[TemplateManager] HIRED: %s (%s) model=%s",
                    tmpl.name, template_id, model)

        return {
            "success": True,
            "agent_id": template_id,
            "name": tmpl.name,
            "model": model,
            "message": result_msg,
        }

    def fire(self, agent_id: str) -> dict:
        """
        Fire (remove) a hired agent. Cannot fire core agents or CEO.
        """
        # Protect core agents that were in the original agents.json
        core_agents = {"main", "search", "analysis", "code", "qa", "devops", "pm", "windows"}
        if agent_id in core_agents:
            return {"success": False, "error": f"Cannot fire core agent '{agent_id}'"}

        result_msg = agent_registry.remove_agent(agent_id)
        success = "removed" in result_msg.lower() or "success" in result_msg.lower()

        if success:
            logger.info("[TemplateManager] FIRED: %s", agent_id)
        return {"success": success, "agent_id": agent_id, "message": result_msg}

    def suggest_hire(self, command: str) -> Optional[AgentTemplate]:
        """
        CEO auto-suggest: given a command, find an unhired template
        that could handle it. Used by Delegator when no active agent matches.
        """
        from runtime.delegator import _CAPABILITY_KEYWORDS
        cmd_lower = command.lower()

        # Score capabilities against command
        matched_caps = []
        for capability, keywords in _CAPABILITY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in cmd_lower)
            if score > 0:
                matched_caps.append((capability, score))
        matched_caps.sort(key=lambda x: x[1], reverse=True)

        hired_ids = set(agent_registry.list_roles())

        for cap, _score in matched_caps:
            candidates = self.find_by_capability(cap)
            for tmpl in candidates:
                if tmpl.template_id not in hired_ids:
                    return tmpl
        return None


# ── Global singleton ──
template_manager = TemplateManager()
