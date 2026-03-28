"""MCP client — connects to MCP servers over stdio or SSE.

Implements the JSON-RPC 2.0 protocol subset needed for:
  - initialize handshake
  - tools/list discovery
  - tools/call execution
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# JSON-RPC 2.0 constants
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass
class MCPToolSchema:
    """Schema for a tool discovered from an MCP server."""
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    server_name: str = ""

    def to_tool_definition(self):
        """Convert to Empire's ToolDefinition format."""
        from llm.base import ToolDefinition
        # Prefix tool name with server name to avoid collisions
        prefixed_name = f"mcp_{self.server_name}_{self.name}" if self.server_name else f"mcp_{self.name}"
        # Sanitize name (LLM APIs only allow alphanumeric + underscore)
        prefixed_name = prefixed_name.replace("-", "_").replace(".", "_")
        return ToolDefinition(
            name=prefixed_name,
            description=f"[MCP:{self.server_name}] {self.description}",
            parameters=self.input_schema or {"type": "object", "properties": {}},
        )


@dataclass
class MCPServerInfo:
    """Info returned from an MCP server after initialization."""
    name: str = ""
    version: str = ""
    protocol_version: str = ""
    capabilities: dict = field(default_factory=dict)


class MCPClientError(Exception):
    """Error communicating with an MCP server."""
    pass


class StdioTransport:
    """Transport layer for MCP over stdio (subprocess).

    Spawns the MCP server as a subprocess and communicates
    via stdin/stdout using newline-delimited JSON-RPC messages.
    """

    def __init__(self, command: list[str], env: dict[str, str] | None = None):
        self._command = command
        self._env = env
        self._process: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._response_events: dict[str, threading.Event] = {}
        self._responses: dict[str, dict] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False

    def start(self) -> None:
        """Start the MCP server subprocess."""
        import os
        env = dict(os.environ)
        if self._env:
            env.update(self._env)

        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            bufsize=0,
        )
        self._running = True
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

    def stop(self) -> None:
        """Stop the MCP server subprocess."""
        self._running = False
        if self._process:
            try:
                self._process.stdin.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                if self._process.poll() is None:
                    self._process.kill()
            self._process = None

    def send(self, message: dict, timeout: float = 30.0) -> dict:
        """Send a JSON-RPC message and wait for the response."""
        msg_id = message.get("id")
        if msg_id is None:
            raise MCPClientError("Message must have an 'id' field")

        event = threading.Event()
        with self._lock:
            self._response_events[msg_id] = event

        raw = json.dumps(message) + "\n"
        try:
            self._process.stdin.write(raw.encode("utf-8"))
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise MCPClientError(f"Failed to send to MCP server: {e}")

        if not event.wait(timeout=timeout):
            with self._lock:
                self._response_events.pop(msg_id, None)
            raise MCPClientError(f"Timeout waiting for response to {message.get('method', msg_id)}")

        with self._lock:
            self._response_events.pop(msg_id, None)
            return self._responses.pop(msg_id, {})

    def _read_loop(self) -> None:
        """Background thread that reads responses from stdout."""
        while self._running and self._process and self._process.poll() is None:
            try:
                line = self._process.stdout.readline()
                if not line:
                    break
                line = line.decode("utf-8").strip()
                if not line:
                    continue
                data = json.loads(line)
                msg_id = data.get("id")
                if msg_id is not None:
                    with self._lock:
                        self._responses[msg_id] = data
                        event = self._response_events.get(msg_id)
                        if event:
                            event.set()
            except json.JSONDecodeError:
                continue
            except Exception as e:
                if self._running:
                    logger.debug("MCP reader error: %s", e)
                break

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None


class SSETransport:
    """Transport layer for MCP over HTTP/SSE.

    Connects to an MCP server via Server-Sent Events for receiving
    and HTTP POST for sending.
    """

    def __init__(self, url: str, headers: dict[str, str] | None = None):
        self._url = url
        self._headers = headers or {}
        self._session_url: Optional[str] = None
        self._responses: dict[str, dict] = {}
        self._response_events: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._running = False
        self._sse_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Connect to the SSE endpoint."""
        self._running = True
        self._sse_thread = threading.Thread(target=self._sse_loop, daemon=True)
        self._sse_thread.start()
        # Wait briefly for the SSE connection to establish
        time.sleep(1.0)

    def stop(self) -> None:
        """Disconnect from SSE."""
        self._running = False

    def send(self, message: dict, timeout: float = 30.0) -> dict:
        """Send a JSON-RPC message via HTTP POST."""
        import urllib.request
        import urllib.error

        msg_id = message.get("id")
        if msg_id is None:
            raise MCPClientError("Message must have an 'id' field")

        event = threading.Event()
        with self._lock:
            self._response_events[msg_id] = event

        post_url = self._session_url or self._url
        body = json.dumps(message).encode("utf-8")
        headers = {**self._headers, "Content-Type": "application/json"}

        try:
            req = urllib.request.Request(post_url, data=body, headers=headers, method="POST")
            urllib.request.urlopen(req, timeout=timeout)
        except Exception as e:
            with self._lock:
                self._response_events.pop(msg_id, None)
            raise MCPClientError(f"HTTP POST failed: {e}")

        if not event.wait(timeout=timeout):
            with self._lock:
                self._response_events.pop(msg_id, None)
            raise MCPClientError(f"Timeout waiting for SSE response to {msg_id}")

        with self._lock:
            self._response_events.pop(msg_id, None)
            return self._responses.pop(msg_id, {})

    def _sse_loop(self) -> None:
        """Background thread reading SSE events."""
        import urllib.request

        try:
            req = urllib.request.Request(self._url, headers={**self._headers, "Accept": "text/event-stream"})
            resp = urllib.request.urlopen(req)

            buffer = ""
            while self._running:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8")
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    self._handle_sse_event(event_str)
        except Exception as e:
            if self._running:
                logger.debug("SSE connection error: %s", e)

    def _handle_sse_event(self, event_str: str) -> None:
        """Parse an SSE event and dispatch it."""
        data_lines = []
        for line in event_str.split("\n"):
            if line.startswith("data: "):
                data_lines.append(line[6:])
            elif line.startswith("event: endpoint"):
                # Server is telling us the POST endpoint
                pass

        if data_lines:
            try:
                data = json.loads("".join(data_lines))
                msg_id = data.get("id")
                if msg_id is not None:
                    with self._lock:
                        self._responses[msg_id] = data
                        event = self._response_events.get(msg_id)
                        if event:
                            event.set()
            except json.JSONDecodeError:
                pass

    @property
    def is_alive(self) -> bool:
        return self._running


class MCPClient:
    """High-level MCP client that manages server connections.

    Usage:
        client = MCPClient(name="filesystem", command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"])
        client.connect()
        tools = client.list_tools()
        result = client.call_tool("read_file", {"path": "/tmp/hello.txt"})
        client.disconnect()
    """

    def __init__(
        self,
        name: str,
        command: list[str] | None = None,
        url: str | None = None,
        env: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self.name = name
        self._timeout = timeout
        self._server_info: Optional[MCPServerInfo] = None
        self._tools: list[MCPToolSchema] = []
        self._connected = False

        if command:
            self._transport = StdioTransport(command, env=env)
        elif url:
            self._transport = SSETransport(url, headers=headers)
        else:
            raise MCPClientError("Must provide either 'command' (stdio) or 'url' (SSE)")

    def connect(self) -> MCPServerInfo:
        """Connect to the MCP server and perform the initialize handshake."""
        self._transport.start()

        # Send initialize request
        init_response = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "empire-ai",
                "version": "1.0.0",
            },
        })

        result = init_response.get("result", {})
        self._server_info = MCPServerInfo(
            name=result.get("serverInfo", {}).get("name", self.name),
            version=result.get("serverInfo", {}).get("version", "unknown"),
            protocol_version=result.get("protocolVersion", ""),
            capabilities=result.get("capabilities", {}),
        )

        # Send initialized notification (no response expected)
        self._notify("notifications/initialized", {})

        self._connected = True
        logger.info("Connected to MCP server: %s v%s", self._server_info.name, self._server_info.version)
        return self._server_info

    def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        self._connected = False
        self._transport.stop()
        logger.info("Disconnected from MCP server: %s", self.name)

    def list_tools(self) -> list[MCPToolSchema]:
        """Discover tools available on this MCP server."""
        if not self._connected:
            raise MCPClientError("Not connected. Call connect() first.")

        response = self._request("tools/list", {})
        result = response.get("result", {})
        tools_raw = result.get("tools", [])

        self._tools = []
        for t in tools_raw:
            schema = MCPToolSchema(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=self.name,
            )
            self._tools.append(schema)

        logger.info("MCP server %s exposes %d tools", self.name, len(self._tools))
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Execute a tool on the MCP server.

        Args:
            tool_name: The tool name (without the mcp_ prefix).
            arguments: Tool arguments.

        Returns:
            Dict with 'content' (list of content blocks) and 'isError' flag.
        """
        if not self._connected:
            raise MCPClientError("Not connected. Call connect() first.")

        response = self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        if "error" in response:
            error = response["error"]
            raise MCPClientError(f"Tool call failed: {error.get('message', str(error))}")

        result = response.get("result", {})
        return result

    @property
    def connected(self) -> bool:
        return self._connected and self._transport.is_alive

    @property
    def server_info(self) -> Optional[MCPServerInfo]:
        return self._server_info

    @property
    def tools(self) -> list[MCPToolSchema]:
        return list(self._tools)

    def _request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and return the response."""
        msg_id = str(uuid.uuid4())[:8]
        message = {
            "jsonrpc": JSONRPC_VERSION,
            "id": msg_id,
            "method": method,
            "params": params,
        }
        return self._transport.send(message, timeout=self._timeout)

    def _notify(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        message = {
            "jsonrpc": JSONRPC_VERSION,
            "method": method,
            "params": params,
        }
        raw = json.dumps(message) + "\n"
        if isinstance(self._transport, StdioTransport) and self._transport._process:
            try:
                self._transport._process.stdin.write(raw.encode("utf-8"))
                self._transport._process.stdin.flush()
            except Exception:
                pass
