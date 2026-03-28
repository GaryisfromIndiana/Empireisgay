"""MCP server management routes."""

from __future__ import annotations

import logging
from flask import Blueprint, jsonify, request, current_app

logger = logging.getLogger(__name__)
mcp_bp = Blueprint("mcp", __name__)


@mcp_bp.route("/")
def mcp_status():
    """Get status of all configured MCP servers."""
    try:
        empire_id = current_app.config.get("EMPIRE_ID", "")
        from core.mcp.manager import MCPManager
        manager = MCPManager.get_instance(empire_id)
        manager.load_config()
        statuses = manager.get_status()
        return jsonify({
            "servers": [
                {
                    "name": s.name,
                    "connected": s.connected,
                    "version": s.server_version,
                    "tool_count": s.tool_count,
                    "tools": s.tools,
                    "error": s.error,
                }
                for s in statuses
            ],
            "total_tools": sum(s.tool_count for s in statuses),
        })
    except Exception as e:
        logger.error("MCP status error: %s", e)
        return jsonify({"error": str(e)}), 500


@mcp_bp.route("/connect", methods=["POST"])
def connect_server():
    """Connect to a specific MCP server or all servers."""
    try:
        empire_id = current_app.config.get("EMPIRE_ID", "")
        from core.mcp.manager import MCPManager
        manager = MCPManager.get_instance(empire_id)
        manager.load_config()

        data = request.get_json(silent=True) or {}
        server_name = data.get("server")

        if server_name:
            status = manager.connect_server(server_name)
            return jsonify({
                "name": status.name,
                "connected": status.connected,
                "version": status.server_version,
                "tool_count": status.tool_count,
                "tools": status.tools,
                "error": status.error,
            })
        else:
            statuses = manager.connect_all()
            return jsonify({
                "servers": [
                    {
                        "name": s.name,
                        "connected": s.connected,
                        "tool_count": s.tool_count,
                        "error": s.error,
                    }
                    for s in statuses
                ],
            })
    except Exception as e:
        logger.error("MCP connect error: %s", e)
        return jsonify({"error": str(e)}), 500


@mcp_bp.route("/disconnect", methods=["POST"])
def disconnect_server():
    """Disconnect from a specific MCP server or all servers."""
    try:
        empire_id = current_app.config.get("EMPIRE_ID", "")
        from core.mcp.manager import MCPManager
        manager = MCPManager.get_instance(empire_id)

        data = request.get_json(silent=True) or {}
        server_name = data.get("server")

        if server_name:
            manager.disconnect_server(server_name)
            return jsonify({"disconnected": server_name})
        else:
            manager.disconnect_all()
            return jsonify({"disconnected": "all"})
    except Exception as e:
        logger.error("MCP disconnect error: %s", e)
        return jsonify({"error": str(e)}), 500


@mcp_bp.route("/tools")
def list_tools():
    """List all available MCP tools across all connected servers."""
    try:
        empire_id = current_app.config.get("EMPIRE_ID", "")
        from core.mcp.manager import MCPManager
        manager = MCPManager.get_instance(empire_id)
        tools = manager.get_all_tools()
        return jsonify({
            "tools": [
                {
                    "name": t.name,
                    "server": t.server_name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in tools
            ],
            "total": len(tools),
        })
    except Exception as e:
        logger.error("MCP tools list error: %s", e)
        return jsonify({"error": str(e)}), 500


@mcp_bp.route("/call", methods=["POST"])
def call_tool():
    """Call an MCP tool directly (for testing/debugging)."""
    try:
        empire_id = current_app.config.get("EMPIRE_ID", "")
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "JSON body required with 'tool' and 'arguments'"}), 400

        tool_name = data.get("tool", "")
        arguments = data.get("arguments", {})

        if not tool_name:
            return jsonify({"error": "Missing 'tool' field"}), 400

        from core.mcp.manager import MCPManager
        manager = MCPManager.get_instance(empire_id)
        result = manager.call_tool(tool_name, arguments)
        formatted = manager.format_tool_result(result)

        return jsonify({
            "tool": tool_name,
            "result": formatted,
            "raw": result,
            "is_error": result.get("isError", False),
        })
    except Exception as e:
        logger.error("MCP tool call error: %s", e)
        return jsonify({"error": str(e)}), 500


@mcp_bp.route("/add", methods=["POST"])
def add_server():
    """Add a new MCP server configuration at runtime."""
    try:
        empire_id = current_app.config.get("EMPIRE_ID", "")
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "JSON body required"}), 400

        name = data.get("name", "")
        if not name:
            return jsonify({"error": "Missing 'name' field"}), 400

        from core.mcp.manager import MCPManager, MCPServerConfig
        manager = MCPManager.get_instance(empire_id)

        config = MCPServerConfig(
            name=name,
            command=data.get("command"),
            url=data.get("url"),
            env=data.get("env", {}),
            headers=data.get("headers", {}),
            enabled=data.get("enabled", True),
            timeout=data.get("timeout", 30.0),
        )
        manager.add_server(config)

        # Auto-connect if requested
        if data.get("connect", True):
            status = manager.connect_server(name)
            return jsonify({
                "added": name,
                "connected": status.connected,
                "tool_count": status.tool_count,
                "tools": status.tools,
                "error": status.error,
            })

        return jsonify({"added": name})
    except Exception as e:
        logger.error("MCP add server error: %s", e)
        return jsonify({"error": str(e)}), 500
