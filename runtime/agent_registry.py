# -*- coding: utf-8 -*-
"""
ArcMind — Agent Registry
==========================
JSON-based Agent Registry for multi-agent delegation.

每個 Agent 綁定：model、capabilities、system_prompt。
MAIN Agent 作為調度主管，sub-agents 處理專業任務。

用法：
  from runtime.agent_registry import agent_registry

  agents = agent_registry.list_agents()
  code_agent = agent_registry.get("code")
  matched = agent_registry.find_by_capability("coding")
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("arcmind.agent_registry")

# Default path to agents.json
_AGENTS_FILE = Path(__file__).parent.parent / "config" / "agents.json"


class AgentConfig:
    """Deserialized agent configuration (read-only view)."""

    def __init__(self, data: dict):
        self.id: str = data.get("id", "")
        self.name: str = data.get("name", "")
        self.model: str = data.get("model", "")
        self.purpose: str = data.get("purpose", "")
        self.capabilities: list[str] = data.get("capabilities", [])
        self.system_prompt: str = data.get("system_prompt", "")
        self.enabled: bool = data.get("enabled", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "model": self.model,
            "purpose": self.purpose,
            "capabilities": self.capabilities,
            "enabled": self.enabled,
        }

    def __repr__(self):
        return f"<Agent '{self.id}' model={self.model} caps={self.capabilities}>"


class AgentRegistry:
    """
    JSON-based Agent Registry.
    Loads agents from config/agents.json with hot-reload support.
    """

    def __init__(self, path: Path | str | None = None):
        self._path = Path(path) if path else _AGENTS_FILE
        self._agents: dict[str, AgentConfig] = {}
        self._mtime: float = 0
        self._default_agent: str = "main"
        self._load()

    def _load(self) -> None:
        """Load or reload agents.json."""
        if not self._path.exists():
            logger.warning("[AgentRegistry] %s not found", self._path)
            return

        try:
            mtime = self._path.stat().st_mtime
            if mtime == self._mtime and self._agents:
                return  # No change

            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self._default_agent = data.get("default_agent", "main")
            self._agents = {}
            for agent_data in data.get("agents", []):
                agent = AgentConfig(agent_data)
                if agent.enabled:
                    self._agents[agent.id] = agent

            self._mtime = mtime
            logger.info("[AgentRegistry] loaded %d agents from %s",
                        len(self._agents), self._path.name)
        except Exception as e:
            logger.error("[AgentRegistry] failed to load: %s", e)

    def _ensure_fresh(self) -> None:
        """Hot-reload if file changed."""
        try:
            if self._path.exists():
                mtime = self._path.stat().st_mtime
                if mtime != self._mtime:
                    self._load()
        except Exception:
            pass

    def get(self, agent_id: str) -> Optional[AgentConfig]:
        """Get agent by ID."""
        self._ensure_fresh()
        return self._agents.get(agent_id)

    def get_default(self) -> Optional[AgentConfig]:
        """Get the default (MAIN) agent."""
        self._ensure_fresh()
        return self._agents.get(self._default_agent)

    def list_agents(self) -> list[AgentConfig]:
        """List all enabled agents."""
        self._ensure_fresh()
        return list(self._agents.values())

    def find_by_capability(self, capability: str) -> list[AgentConfig]:
        """Find agents that have a given capability."""
        self._ensure_fresh()
        return [a for a in self._agents.values() if capability in a.capabilities]

    def get_sub_agents(self) -> list[AgentConfig]:
        """Get all agents except MAIN."""
        self._ensure_fresh()
        return [a for a in self._agents.values() if a.id != self._default_agent]

    def format_roster(self) -> str:
        """Format agent roster for display."""
        self._ensure_fresh()
        lines = []
        for a in self._agents.values():
            role = "👑 MAIN" if a.id == self._default_agent else "  └─"
            lines.append(f"{role} **{a.name}** (`{a.id}`) — {a.model}")
            lines.append(f"     用途: {a.purpose}")
            lines.append(f"     能力: {', '.join(a.capabilities)}")
        return "\n".join(lines)

    def status(self) -> dict:
        self._ensure_fresh()
        return {
            "total_agents": len(self._agents),
            "default": self._default_agent,
            "agents": [a.to_dict() for a in self._agents.values()],
        }

    # ── CRUD Operations ──────────────────────────────────────────────────

    def _save(self) -> None:
        """Atomic write agents.json."""
        data = {
            "version": "1.0",
            "default_agent": self._default_agent,
            "agents": [],
        }
        for a in self._agents.values():
            data["agents"].append({
                "id": a.id,
                "name": a.name,
                "model": a.model,
                "purpose": a.purpose,
                "capabilities": a.capabilities,
                "system_prompt": a.system_prompt,
                "enabled": a.enabled,
            })

        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        tmp.replace(self._path)
        self._mtime = self._path.stat().st_mtime
        logger.info("[AgentRegistry] saved %d agents", len(self._agents))

    def add_agent(
        self,
        agent_id: str,
        name: str,
        model: str,
        purpose: str,
        capabilities: list[str] | None = None,
        system_prompt: str = "",
    ) -> str:
        """Add a new agent. Returns confirmation message."""
        self._ensure_fresh()

        if agent_id in self._agents:
            return f"❌ Agent '{agent_id}' 已存在。請用 update_agent 更新。"

        agent = AgentConfig({
            "id": agent_id,
            "name": name,
            "model": model,
            "purpose": purpose,
            "capabilities": capabilities or [],
            "system_prompt": system_prompt,
            "enabled": True,
        })
        self._agents[agent_id] = agent
        self._save()

        return (
            f"✅ Agent 已添加！\n"
            f"  ID: {agent_id}\n"
            f"  名稱: {name}\n"
            f"  模型: {model}\n"
            f"  用途: {purpose}\n"
            f"  能力: {', '.join(capabilities or [])}"
        )

    def remove_agent(self, agent_id: str) -> str:
        """Remove an agent. Cannot remove MAIN."""
        self._ensure_fresh()

        if agent_id == self._default_agent:
            return "❌ 不能移除 MAIN Agent。"

        if agent_id not in self._agents:
            return f"❌ Agent '{agent_id}' 不存在。"

        name = self._agents[agent_id].name
        del self._agents[agent_id]
        self._save()
        return f"✅ Agent '{name}' ({agent_id}) 已移除。"

    def update_agent(
        self,
        agent_id: str,
        name: str | None = None,
        model: str | None = None,
        purpose: str | None = None,
        capabilities: list[str] | None = None,
        system_prompt: str | None = None,
    ) -> str:
        """Update an existing agent's configuration."""
        self._ensure_fresh()

        if agent_id not in self._agents:
            return f"❌ Agent '{agent_id}' 不存在。"

        old = self._agents[agent_id]
        updated = AgentConfig({
            "id": agent_id,
            "name": name or old.name,
            "model": model or old.model,
            "purpose": purpose or old.purpose,
            "capabilities": capabilities if capabilities is not None else old.capabilities,
            "system_prompt": system_prompt if system_prompt is not None else old.system_prompt,
            "enabled": True,
        })
        self._agents[agent_id] = updated
        self._save()
        return f"✅ Agent '{agent_id}' 已更新。"


# ── Singleton ──
agent_registry = AgentRegistry()

