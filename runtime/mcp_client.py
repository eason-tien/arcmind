# -*- coding: utf-8 -*-
"""
MCP Client Adapter — 連接外部 MCP Server，自動發現工具並註冊到 ToolRegistry。

P2-1: 支援 stdio 和 streamable_http 兩種 transport。
工具名自動加前綴 `mcp_{server}_{tool}` 避免與內建工具衝突。

無硬依賴：未安裝 `mcp` 時自動跳過，不影響現有系統。
"""
from __future__ import annotations

import asyncio
import json
import logging
import pathlib
from typing import Any, Optional

logger = logging.getLogger("arcmind.mcp_client")

_CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config" / "mcp_servers.json"


class MCPClientManager:
    """
    Manages connections to multiple MCP Servers.

    Usage:
        manager = MCPClientManager()
        await manager.connect_all()       # reads config/mcp_servers.json
        await manager.call_tool("github", "list_repos", {"org": "foo"})
    """

    def __init__(self):
        self._sessions: dict[str, Any] = {}  # server_name → ClientSession
        self._transports: dict[str, Any] = {}  # server_name → (read, write) context
        self._available = self._check_mcp_available()

    @staticmethod
    def _check_mcp_available() -> bool:
        try:
            import mcp  # noqa: F401
            return True
        except ImportError:
            logger.info("[MCPClient] mcp package not installed — MCP integration disabled")
            return False

    def load_config(self) -> list[dict]:
        """Load MCP server configurations from config/mcp_servers.json."""
        if not _CONFIG_PATH.exists():
            return []
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
            servers = data.get("servers", [])
            if servers:
                logger.info("[MCPClient] Loaded %d server configs", len(servers))
            return servers
        except Exception as e:
            logger.warning("[MCPClient] Failed to load config: %s", e)
            return []

    async def connect(self, server_config: dict) -> bool:
        """
        Connect to a single MCP Server and discover its tools.

        server_config format:
        {
            "name": "github",
            "transport": "stdio",          // "stdio" or "streamable_http"
            "command": "npx",              // for stdio
            "args": ["-y", "@modelcontextprotocol/server-github"],
            "env": {"GITHUB_TOKEN": "..."},
            "url": "http://localhost:8080/mcp"   // for streamable_http
        }
        """
        if not self._available:
            return False

        name = server_config.get("name", "unknown")
        transport = server_config.get("transport", "stdio")

        try:
            from mcp import ClientSession

            if transport == "stdio":
                return await self._connect_stdio(name, server_config)
            elif transport == "streamable_http":
                return await self._connect_http(name, server_config)
            else:
                logger.warning("[MCPClient] Unknown transport '%s' for server '%s'", transport, name)
                return False
        except Exception as e:
            logger.error("[MCPClient] Failed to connect to '%s': %s", name, e)
            return False

    async def _connect_stdio(self, name: str, config: dict) -> bool:
        """Connect via stdio transport."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=config.get("command", ""),
            args=config.get("args", []),
            env=config.get("env"),
        )

        try:
            # Note: stdio_client is an async context manager.
            # We need to keep it alive, so we enter the context manually.
            ctx = stdio_client(params)
            read, write = await ctx.__aenter__()

            session_ctx = ClientSession(read, write)
            session = await session_ctx.__aenter__()
            await session.initialize()

            self._transports[name] = (ctx, session_ctx)
            self._sessions[name] = session

            # Discover tools
            tools_result = await session.list_tools()
            tool_count = len(tools_result.tools) if tools_result.tools else 0
            logger.info("[MCPClient] Connected to '%s' via stdio — %d tools discovered", name, tool_count)

            # Register tools to ToolRegistry
            self._register_tools(name, tools_result.tools or [])
            return True

        except Exception as e:
            logger.error("[MCPClient] stdio connection to '%s' failed: %s", name, e)
            return False

    async def _connect_http(self, name: str, config: dict) -> bool:
        """Connect via streamable HTTP transport."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        url = config.get("url", "")
        if not url:
            logger.error("[MCPClient] No URL provided for HTTP server '%s'", name)
            return False

        try:
            ctx = streamable_http_client(url)
            read, write, _ = await ctx.__aenter__()

            session_ctx = ClientSession(read, write)
            session = await session_ctx.__aenter__()
            await session.initialize()

            self._transports[name] = (ctx, session_ctx)
            self._sessions[name] = session

            tools_result = await session.list_tools()
            tool_count = len(tools_result.tools) if tools_result.tools else 0
            logger.info("[MCPClient] Connected to '%s' via HTTP — %d tools discovered", name, tool_count)

            self._register_tools(name, tools_result.tools or [])
            return True

        except Exception as e:
            logger.error("[MCPClient] HTTP connection to '%s' failed: %s", name, e)
            return False

    def _register_tools(self, server_name: str, tools: list) -> None:
        """Register discovered MCP tools into ArcMind's ToolRegistry."""
        try:
            from runtime.tool_loop import tool_registry
        except ImportError:
            logger.warning("[MCPClient] Cannot import tool_registry — tools not registered")
            return

        for tool in tools:
            # Prefix tool name to avoid conflicts
            prefixed_name = f"mcp_{server_name}_{tool.name}"

            # Build input_schema from MCP tool definition
            input_schema = {}
            if hasattr(tool, 'inputSchema') and tool.inputSchema:
                input_schema = tool.inputSchema
            elif hasattr(tool, 'input_schema') and tool.input_schema:
                input_schema = tool.input_schema

            # Create a closure for the handler
            _server = server_name
            _tool_name = tool.name

            def make_handler(srv: str, tn: str):
                def handler(**kwargs) -> str:
                    """MCP tool handler — delegates to MCP server."""
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Already in async context — use thread
                            import concurrent.futures
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                                future = pool.submit(
                                    asyncio.run,
                                    self._call_tool_async(srv, tn, kwargs)
                                )
                                return future.result(timeout=60)
                        else:
                            return loop.run_until_complete(
                                self._call_tool_async(srv, tn, kwargs)
                            )
                    except RuntimeError:
                        return asyncio.run(self._call_tool_async(srv, tn, kwargs))
                return handler

            tool_registry.register(
                name=prefixed_name,
                description=f"[MCP:{server_name}] {tool.description or tool.name}",
                input_schema=input_schema if isinstance(input_schema, dict) else {"type": "object", "properties": {}},
                handler=make_handler(_server, _tool_name),
            )
            logger.debug("[MCPClient] Registered tool: %s", prefixed_name)

    async def _call_tool_async(self, server_name: str, tool_name: str,
                                arguments: dict) -> str:
        """Call a tool on an MCP server."""
        session = self._sessions.get(server_name)
        if not session:
            return f"Error: MCP server '{server_name}' not connected"

        try:
            from mcp import types
            result = await session.call_tool(tool_name, arguments=arguments)

            # Extract text from result content blocks
            parts = []
            for block in (result.content or []):
                if isinstance(block, types.TextContent):
                    parts.append(block.text)
                elif hasattr(block, 'text'):
                    parts.append(str(block.text))
                else:
                    parts.append(str(block))

            return "\n".join(parts) if parts else "(empty result)"
        except Exception as e:
            logger.error("[MCPClient] call_tool '%s.%s' failed: %s", server_name, tool_name, e)
            return f"Error calling MCP tool: {e}"

    async def connect_all(self) -> int:
        """Connect to all configured MCP servers. Returns number of successful connections."""
        configs = self.load_config()
        if not configs:
            return 0

        connected = 0
        for cfg in configs:
            if await self.connect(cfg):
                connected += 1

        logger.info("[MCPClient] Connected to %d/%d servers", connected, len(configs))
        return connected

    async def disconnect_all(self) -> None:
        """Gracefully disconnect from all MCP servers."""
        for name in list(self._sessions.keys()):
            try:
                ctx, session_ctx = self._transports.get(name, (None, None))
                if session_ctx:
                    await session_ctx.__aexit__(None, None, None)
                if ctx:
                    await ctx.__aexit__(None, None, None)
                logger.info("[MCPClient] Disconnected from '%s'", name)
            except Exception as e:
                logger.debug("[MCPClient] Disconnect error for '%s': %s", name, e)
        self._sessions.clear()
        self._transports.clear()

    def get_connected_servers(self) -> list[str]:
        """Return list of connected server names."""
        return list(self._sessions.keys())

    def get_tool_count(self) -> int:
        """Return total number of MCP tools registered."""
        try:
            from runtime.tool_loop import tool_registry
            return sum(1 for name in tool_registry.list_tools() if name.startswith("mcp_"))
        except Exception:
            return 0


# Singleton
mcp_client_manager = MCPClientManager()
