"""Expose the four read-only SECOP tools through the official MCP SDK."""

from __future__ import annotations

import logging
import sys

from mcp.server.fastmcp import FastMCP

from secop_mcp.procurement import (
    compute_financial_indicators,
    get_company_profile,
    get_process,
    search_processes,
)

mcp = FastMCP("secop")
mcp.tool()(search_processes)
mcp.tool()(get_process)
mcp.tool()(get_company_profile)
mcp.tool()(compute_financial_indicators)


def main() -> None:
    """Run stdio with diagnostic logging directed to stderr, never stdout."""
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
