"""FastMCP server definition and entry points for thoughtspot_mcp."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("thoughtspot_mcp")

# Register all tools (side-effect imports via decorators)
from thoughtspot_mcp.tools import register_all  # noqa: E402

register_all(mcp)


def main_stdio() -> None:
    """Entry point for local / Docker stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main_stdio()
