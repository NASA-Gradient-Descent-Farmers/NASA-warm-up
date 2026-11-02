"""The assistant's tools as an MCP server, for Claude Desktop or any MCP client.

    python -m src.assistant.mcp_server                       # stdio (Claude Desktop)
    python -m src.assistant.mcp_server --http --port 8001    # streamable HTTP at /mcp

Claude Desktop config (claude_desktop_config.json), with the repo root as working directory:

    {"mcpServers": {"field-shift": {"command": "python", "args": ["-m", "src.assistant.mcp_server"],
                                    "cwd": "/path/to/NASA-warm-up"}}}

Works with the MCP Python SDK 2.x (MCPServer) and 1.x (FastMCP).
"""

import argparse
import json

from . import prompts, tools

try:                                       # mcp >= 2
    from mcp.server.mcpserver import MCPServer as Server
except ImportError:                        # mcp 1.x
    from mcp.server.fastmcp import FastMCP as Server

server = Server("field-shift", instructions=prompts.SYSTEM)


@server.tool(description=tools.TOOLS[0]["description"])
def buscar_lugar(nombre: str, estado: str | None = None) -> str:
    return json.dumps(tools.buscar_lugar(nombre, estado), ensure_ascii=False)


@server.tool(description=tools.TOOLS[1]["description"] + " Formato de rotacion_actual: "
             + tools.TOOLS[1]["input_schema"]["properties"]["rotacion_actual"]["description"])
def comparar_rotaciones(lugar: str, rotacion_actual: str, estado: str | None = None, agua: str = "temporal",
                        prioridades: list[str] | None = None, residuo: str = "dejar", tiene_animales: bool = False,
                        mes_siembra: int | None = None, pendiente: str = "ligera", propuestas: list[str] | None = None,
                        costos: dict[str, float] | None = None,
                        rendimiento_propio: dict[str, float] | None = None) -> str:
    return tools.call("comparar_rotaciones", {k: v for k, v in locals().items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--http", action="store_true", help="serve streamable HTTP instead of stdio")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    if args.http:
        try:
            server.run("streamable-http", port=args.port)          # mcp >= 2
        except TypeError:                                           # mcp 1.x: port lives in settings
            server.settings.port = args.port
            server.run("streamable-http")
    else:
        server.run()


if __name__ == "__main__":
    main()
