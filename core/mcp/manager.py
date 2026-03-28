"""MCP server manager — lifecycle management for configured MCP servers.

Handles connecting, disconnecting, tool discovery, and tool execution
across all configured MCP servers. Acts as the single entry point
for the rest of the Empire to interact with MCP tools.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from core.mcp.client import MCPClient, MCPClientError, MCPToolSchema

logger = logging.getLogger(__name__)


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""
    name: str
    command: list[str] | None = None
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout: float = 30.0
    auto_connect: bool = True


@dataclass
class MCPServerStatus:
    """Runtime status of an MCP server."""
    name: str
    connected: bool = False
    server_version: str = ""
    tool_count: int = 0
    error: str = ""
    tools: list[str] = field(default_factory=list)


class MCPManager:
    """Manages all MCP server connections and tool routing.

    Thread-safe singleton pattern — one manager per empire.
    """

    _instances: dict[str, MCPManager] = {}
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls, empire_id: str = "") -> MCPManager:
        """Get or create the MCPManager for an empire."""
        with cls._instance_lock:
            if empire_id not in cls._instances:
                cls._instances[empire_id] = cls(empire_id)
            return cls._instances[empire_id]

    def __init__(self, empire_id: str = ""):
        self._empire_id = empire_id
        self._clients: dict[str, MCPClient] = {}
        self._configs: dict[str, MCPServerConfig] = {}
        self._tool_map: dict[str, str] = {}  # prefixed_tool_name -> server_name
        self._lock = threading.Lock()
        self._loaded = False

    def load_config(self) -> None:
        """Load MCP server configs from settings."""
        try:
            from config.settings import get_settings
            settings = get_settings()
            mcp_settings = getattr(settings, "mcp", None)
            if not mcp_settings:
                return

            servers = getattr(mcp_settings, "servers", {})
            for name, server_cfg in servers.items():
                if isinstance(server_cfg, dict):
                    config = MCPServerConfig(
                        name=name,
                        command=server_cfg.get("command"),
                        url=server_cfg.get("url"),
                        env=server_cfg.get("env", {}),
                        headers=server_cfg.get("headers", {}),
                        enabled=server_cfg.get("enabled", True),
                        timeout=server_cfg.get("timeout", 30.0),
                        auto_connect=server_cfg.get("auto_connect", True),
                    )
                else:
                    config = MCPServerConfig(
                        name=name,
                        command=getattr(server_cfg, "command", None),
                        url=getattr(server_cfg, "url", None),
                        env=getattr(server_cfg, "env", {}),
                        headers=getattr(server_cfg, "headers", {}),
                        enabled=getattr(server_cfg, "enabled", True),
                        timeout=getattr(server_cfg, "timeout", 30.0),
                        auto_connect=getattr(server_cfg, "auto_connect", True),
                    )
                self._configs[name] = config
            self._loaded = True
        except Exception as e:
            logger.debug("No MCP settings found: %s", e)

    def add_server(self, config: MCPServerConfig) -> None:
        """Add an MCP server configuration at runtime."""
        with self._lock:
            self._configs[config.name] = config

    def connect_server(self, name: str) -> MCPServerStatus:
        """Connect to a specific MCP server and discover its tools."""
        with self._lock:
            config = self._configs.get(name)
            if not config:
                return MCPServerStatus(name=name, error=f"Unknown server: {name}")

            if name in self._clients and self._clients[name].connected:
                client = self._clients[name]
                return MCPServerStatus(
                    name=name,
                    connected=True,
                    server_version=client.server_info.version if client.server_info else "",
                    tool_count=len(client.tools),
                    tools=[t.name for t in client.tools],
                )

        try:
            client = MCPClient(
                name=name,
                command=config.command,
                url=config.url,
                env=config.env,
                headers=config.headers,
                timeout=config.timeout,
            )
            server_info = client.connect()
            tools = client.list_tools()

            with self._lock:
                self._clients[name] = client
                # Map prefixed tool names to server
                for tool in tools:
                    td = tool.to_tool_definition()
                    self._tool_map[td.name] = name

            return MCPServerStatus(
                name=name,
                connected=True,
                server_version=server_info.version,
                tool_count=len(tools),
                tools=[t.name for t in tools],
            )
        except Exception as e:
            logger.error("Failed to connect MCP server %s: %s", name, e)
            return MCPServerStatus(name=name, error=str(e))

    def connect_all(self) -> list[MCPServerStatus]:
        """Connect to all enabled MCP servers."""
        if not self._loaded:
            self.load_config()

        statuses = []
        for name, config in self._configs.items():
            if config.enabled and config.auto_connect:
                status = self.connect_server(name)
                statuses.append(status)
        return statuses

    def disconnect_server(self, name: str) -> None:
        """Disconnect from an MCP server."""
        with self._lock:
            client = self._clients.pop(name, None)
            # Remove tool mappings
            self._tool_map = {k: v for k, v in self._tool_map.items() if v != name}
        if client:
            client.disconnect()

    def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        with self._lock:
            clients = list(self._clients.items())
            self._clients.clear()
            self._tool_map.clear()
        for name, client in clients:
            try:
                client.disconnect()
            except Exception:
                pass

    def get_all_tools(self) -> list[MCPToolSchema]:
        """Get all tools from all connected servers."""
        tools = []
        with self._lock:
            for client in self._clients.values():
                if client.connected:
                    tools.extend(client.tools)
        return tools

    def get_tool_definitions(self):
        """Get ToolDefinition objects for all MCP tools."""
        from llm.base import ToolDefinition
        tools = self.get_all_tools()
        return [t.to_tool_definition() for t in tools]

    def call_tool(self, prefixed_name: str, arguments: dict) -> dict:
        """Execute an MCP tool by its prefixed name.

        Args:
            prefixed_name: The full prefixed tool name (e.g. mcp_filesystem_read_file).
            arguments: Tool arguments.

        Returns:
            Tool result dict with 'content' and optional 'isError'.
        """
        with self._lock:
            server_name = self._tool_map.get(prefixed_name)
            if not server_name:
                raise MCPClientError(f"Unknown MCP tool: {prefixed_name}")
            client = self._clients.get(server_name)
            if not client or not client.connected:
                raise MCPClientError(f"MCP server {server_name} is not connected")

        # Strip the prefix to get the original tool name
        # Format: mcp_{server_name}_{tool_name}
        prefix = f"mcp_{server_name.replace('-', '_').replace('.', '_')}_"
        original_name = prefixed_name[len(prefix):] if prefixed_name.startswith(prefix) else prefixed_name

        return client.call_tool(original_name, arguments)

    def format_tool_result(self, result: dict) -> str:
        """Format an MCP tool result into a string for the LLM."""
        content_blocks = result.get("content", [])
        is_error = result.get("isError", False)

        parts = []
        for block in content_blocks:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "image":
                    parts.append(f"[Image: {block.get('mimeType', 'unknown')}]")
                elif block.get("type") == "resource":
                    uri = block.get("resource", {}).get("uri", "")
                    text = block.get("resource", {}).get("text", "")
                    parts.append(f"[Resource: {uri}]\n{text}")
            elif isinstance(block, str):
                parts.append(block)

        text = "\n".join(parts)
        if is_error:
            text = f"Error: {text}"
        return text

    def get_status(self) -> list[MCPServerStatus]:
        """Get status of all configured MCP servers."""
        if not self._loaded:
            self.load_config()

        statuses = []
        for name, config in self._configs.items():
            with self._lock:
                client = self._clients.get(name)
            if client and client.connected:
                statuses.append(MCPServerStatus(
                    name=name,
                    connected=True,
                    server_version=client.server_info.version if client.server_info else "",
                    tool_count=len(client.tools),
                    tools=[t.name for t in client.tools],
                ))
            else:
                statuses.append(MCPServerStatus(
                    name=name,
                    connected=False,
                ))
        return statuses

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Check if a tool name belongs to an MCP server."""
        with self._lock:
            return tool_name in self._tool_map
