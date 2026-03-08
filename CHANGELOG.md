# Changelog

All notable changes to ArcMind will be documented in this file.

## [0.3.0] - 2026-03-08

### Added
- OODA-based main loop with 5-stage processing
- 16 tools (run_command, read_file, write_file, web_search, python_eval, memory_query, list/add/remove_agents, invoke/list_skills, harness create/status/control)
- 10 skills (web_search, file_ops, code_exec, trading, self_iteration, daily_report, github, document, env_discovery, gitnexus)
- Multi-provider model routing (MiniMax, Ollama, OpenAI, Anthropic, Google, Groq, Mistral)
- 4-layer memory system (episodic/semantic/procedural/causal) with SQLite + Vector
- Governor safety system with risk assessment + circuit breaker
- Self-healing watchdog + repair agent + incident logging
- Harness system for resumable multi-step tasks
- Gemini Bridge for Antigravity CLI integration
- Telegram, REST API, WebSocket, Voice channels
- Android hybrid app (Chaquopy + AccessibilityService)
- GitHub Actions CI/CD pipeline
- Auto-update mechanism
- Error reporting to GitHub Issues

### Fixed
- memory_compressor.py: ChromaDB API migration to SQLite
- test_gateway.py: Python 3.14 asyncio compatibility
- test_harness.py: UNIQUE constraint test isolation
