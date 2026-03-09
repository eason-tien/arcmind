"""
ArcMind Agent Registry — Zero-Human Company Employee Directory
==============================================================
Loads agent definitions from config/agents.json, supports dynamic
registration, capability-based lookup, and role hierarchy.

Each agent is an "employee" with:
  - id / name / role
  - capabilities (what it can do)
  - allowed_tools (which tools it may call)
  - model (which LLM to use)
  - system_prompt (behavioral instructions)
  - status (active / idle / disabled)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("arcmind.agent_registry")

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "agents.json"


@dataclass
class AgentPersona:
    id: str
    name: str
    role: str
    description: str
    system_prompt: str
    allowed_tools: List[str]
    default_model: str
    capabilities: List[str] = field(default_factory=list)
    enabled: bool = True
    # For backward compat, expose 'role' as primary key too
    purpose: str = ""


class AgentRegistry:
    """
    Central registry for all Zero-Human Company agents.
    Loads from agents.json on init, supports runtime additions.
    """

    def __init__(self):
        self._agents: Dict[str, AgentPersona] = {}
        self._load_config()
        self._ensure_defaults()

    # ── Loading ──────────────────────────────────────────────────────────────

    def _load_config(self):
        """Load agents from config/agents.json."""
        if not _CONFIG_PATH.exists():
            logger.warning("agents.json not found at %s, using defaults only", _CONFIG_PATH)
            return

        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            for agent_def in data.get("agents", []):
                persona = AgentPersona(
                    id=agent_def["id"],
                    name=agent_def.get("name", agent_def["id"]),
                    role=agent_def["id"],  # role == id for config-loaded agents
                    description=agent_def.get("purpose", ""),
                    system_prompt=agent_def.get("system_prompt", ""),
                    allowed_tools=agent_def.get("allowed_tools", ["__all__"]),
                    default_model=agent_def.get("model", "claude"),
                    capabilities=agent_def.get("capabilities", []),
                    enabled=agent_def.get("enabled", True),
                    purpose=agent_def.get("purpose", ""),
                )
                self._agents[persona.id] = persona
            logger.info("Loaded %d agents from agents.json", len(self._agents))
        except Exception as e:
            logger.error("Failed to load agents.json: %s", e)

    def _ensure_defaults(self):
        """Ensure core roles exist even if agents.json is incomplete."""
        defaults = {
            "main": AgentPersona(
                id="main", name="Main (CEO)", role="ceo",
                description="The chief executive orchestrator. Delegates to sub-agents.",
                system_prompt=(
                    "You are the CEO of this autonomous system. Understand user requests, "
                    "break them into tasks, and delegate to specialized sub-agents."
                ),
                allowed_tools=["__all__"],
                default_model="claude",
                capabilities=["chat", "orchestration", "general"],
            ),
            "code": AgentPersona(
                id="code", name="Code Agent", role="engineer",
                description="Writes code, runs commands, modifies the file system.",
                system_prompt=(
                    "You are the Software Engineer agent. Safely execute commands, "
                    "read files, and write code to fulfill technical requirements."
                ),
                allowed_tools=["run_command", "view_file", "write_to_file",
                                "replace_file_content", "grep_search", "python_eval"],
                default_model="claude",
                capabilities=["coding", "debugging", "code_review", "refactor"],
            ),
            "search": AgentPersona(
                id="search", name="Search Agent", role="researcher",
                description="Gathers information from the web and internal memories.",
                system_prompt=(
                    "You are the Researcher agent. Use web search and memory retrieval. "
                    "Provide concise, accurate summaries."
                ),
                allowed_tools=["web_search", "memory_query", "read_url_content"],
                default_model="ollama",
                capabilities=["web_search", "research", "news"],
            ),
        }
        for agent_id, persona in defaults.items():
            if agent_id not in self._agents:
                self._agents[agent_id] = persona

    # ── Registration ─────────────────────────────────────────────────────────

    def register(self, persona: AgentPersona):
        """Register or update an agent at runtime."""
        self._agents[persona.id] = persona
        logger.info("Agent registered: %s (%s)", persona.id, persona.name)

    def unregister(self, agent_id: str) -> bool:
        """Remove an agent. Cannot remove 'main'."""
        if agent_id == "main":
            logger.warning("Cannot unregister the main (CEO) agent")
            return False
        removed = self._agents.pop(agent_id, None)
        return removed is not None

    # ── Lookup ───────────────────────────────────────────────────────────────

    def get(self, agent_id: str) -> Optional[AgentPersona]:
        """Get agent by id. Also checks role for backward compat."""
        if agent_id in self._agents:
            return self._agents[agent_id]
        # Fallback: search by role name (e.g., "ceo", "engineer", "researcher")
        for a in self._agents.values():
            if a.role == agent_id:
                return a
        return None

    def get_default(self) -> Optional[AgentPersona]:
        """Get the default (main/CEO) agent."""
        return self._agents.get("main")

    def find_by_capability(self, capability: str) -> List[AgentPersona]:
        """Find all enabled agents that have the given capability."""
        results = []
        for agent in self._agents.values():
            if not agent.enabled:
                continue
            if capability in agent.capabilities:
                results.append(agent)
        return results

    def list_roles(self) -> List[str]:
        """List all agent ids (for backward compat, named 'roles')."""
        return list(self._agents.keys())

    def list_agents(self) -> List[Dict]:
        """List all agents with their details."""
        return [
            {
                "id": a.id,
                "name": a.name,
                "role": a.role,
                "description": a.description,
                "default_model": a.default_model,
                "capabilities": a.capabilities,
                "allowed_tools": a.allowed_tools,
                "enabled": a.enabled,
            }
            for a in self._agents.values()
        ]

    def list_enabled(self) -> List[AgentPersona]:
        """List only enabled agents."""
        return [a for a in self._agents.values() if a.enabled]

    # ── Tool-facing methods (called by tool_loop.py) ────────────────────────

    def format_roster(self) -> str:
        """Format all agents as a human-readable roster string."""
        lines = ["## Zero-Human Company — Agent Roster", ""]
        for a in self._agents.values():
            status = "ON" if a.enabled else "OFF"
            lines.append(f"**{a.name}** (`{a.id}`) [{status}]")
            lines.append(f"  Model: {a.default_model}")
            lines.append(f"  Purpose: {a.description}")
            lines.append(f"  Capabilities: {', '.join(a.capabilities)}")
            lines.append("")
        lines.append(f"Total: {len(self._agents)} agents "
                      f"({len(self.list_enabled())} enabled)")
        return "\n".join(lines)

    def add_agent(
        self,
        agent_id: str,
        name: str,
        model: str,
        purpose: str,
        capabilities: list | None = None,
        system_prompt: str = "",
    ) -> str:
        """Add a new agent and persist to config."""
        if agent_id in self._agents:
            return f"Agent '{agent_id}' already exists. Use a different ID."

        persona = AgentPersona(
            id=agent_id,
            name=name,
            role=agent_id,
            description=purpose,
            system_prompt=system_prompt,
            allowed_tools=["__all__"],
            default_model=model,
            capabilities=capabilities or [],
            enabled=True,
            purpose=purpose,
        )
        self.register(persona)
        self.save_config()
        return f"Agent '{name}' ({agent_id}) added successfully with model {model}."

    def remove_agent(self, agent_id: str) -> str:
        """Remove an agent and persist to config."""
        if not self.unregister(agent_id):
            if agent_id == "main":
                return "Cannot remove the CEO (main) agent."
            return f"Agent '{agent_id}' not found."
        self.save_config()
        return f"Agent '{agent_id}' removed successfully."

    # ── Persistence ──────────────────────────────────────────────────────────

    def save_config(self):
        """Save current registry back to agents.json."""
        data = {
            "version": "2.0",
            "default_agent": "main",
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "model": a.default_model,
                    "purpose": a.description,
                    "capabilities": a.capabilities,
                    "system_prompt": a.system_prompt,
                    "allowed_tools": a.allowed_tools,
                    "enabled": a.enabled,
                }
                for a in self._agents.values()
            ]
        }
        _CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("Saved %d agents to agents.json", len(self._agents))


# ── Global singleton ──
agent_registry = AgentRegistry()
