"""
ArcMind Agent Registry
Defines the "Employees" of the Zero-Human Company.
Each role has specific tool access, budget models, and system prompts.
"""
from typing import Dict, List, Optional
from dataclasses import dataclass

@dataclass
class AgentPersona:
    role: str
    description: str
    system_prompt: str
    allowed_tools: List[str]
    default_model: str

class AgentRegistry:
    def __init__(self):
        self._personas: Dict[str, AgentPersona] = {}
        self._register_defaults()

    def _register_defaults(self):
        # 1. The CEO (Main ArcMind Agent)
        self.register(AgentPersona(
            role="ceo",
            description="The chief executive orchestrator. Handles high-level goals and delegates to others.",
            system_prompt=(
                "You are the CEO of this autonomous system. Your job is to understand user requests, "
                "break them down into tasks, and delegate them to your specialized sub-agents "
                "(like researcher or engineer) when appropriate. You focus on the big picture."
            ),
            allowed_tools=["__all__"], # CEO has access to all tools
            default_model="claude"
        ))

        # 2. The Researcher
        self.register(AgentPersona(
            role="researcher",
            description="Specializes in gathering information from the web or internal memories.",
            system_prompt=(
                "You are the Researcher agent. Your sole purpose is to gather information required by your manager. "
                "Use web search and memory retrieval. Provide concise, accurate summaries."
            ),
            allowed_tools=["web_search", "memory_query", "read_url_content"],
            default_model="ollama" # Low budget model
        ))

        # 3. The Engineer
        self.register(AgentPersona(
            role="engineer",
            description="Specializes in writing code, running commands, and modifying the file system.",
            system_prompt=(
                "You are the Software Engineer agent. Your job is to safely execute commands, read files, "
                "and write code to fulfill the technical requirements of your manager."
            ),
            allowed_tools=["run_command", "view_file", "write_to_file", "replace_file_content", "grep_search"],
            default_model="claude" # High capability model
        ))

        # 4. The Windows Engineer (Remote Worker)
        self.register(AgentPersona(
            role="windows_engineer",
            description="Specializes in executing tasks on the remote Windows PC at 192.168.1.151.",
            system_prompt=(
                "You are the Windows Engineer agent residing on a remote Windows PC. "
                "Your job is to safely execute powershell commands and python scripts sent from the macOS CEO."
            ),
            allowed_tools=["windows_delegation"], # Special tool routing
            default_model="claude"
        ))

    def register(self, persona: AgentPersona):
        self._personas[persona.role] = persona

    def get(self, role: str) -> Optional[AgentPersona]:
        return self._personas.get(role)

    def list_roles(self) -> List[str]:
        return list(self._personas.keys())

    def list_agents(self) -> List[Dict]:
        """List all agents with their details"""
        return [
            {
                "role": p.role,
                "description": p.description,
                "default_model": p.default_model,
                "allowed_tools": p.allowed_tools
            }
            for p in self._personas.values()
        ]

agent_registry = AgentRegistry()
