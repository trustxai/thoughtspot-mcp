"""Tool registration for thoughtspot_mcp.

``register_all`` imports every tool module so that the ``@mcp.tool`` decorators
run and self-register. All Wave A + B modules are listed here from day one (even
while some are still empty stubs) so that parallel worktrees implementing
individual modules never need to touch this file — eliminating merge conflicts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_all(mcp: FastMCP) -> None:
    """Import every tool module so their @mcp.tool decorators execute."""
    from thoughtspot_mcp.tools import (  # noqa: F401
        connections,
        data,
        health,
        metadata,
        reports,
        spotter,
        system_logs,
        tags,
        tml,
        users_groups,
    )
