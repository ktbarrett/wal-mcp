"""MCP server for RTL waveform analysis using WAL (Waveform Analysis Language).

This server provides tools for analyzing waveform files from RTL simulations,
allowing LLMs to inspect signals, detect transitions, and debug hardware designs.

Supported formats: VCD, FST (via WAL)
"""

import argparse
import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool
from wal.core import TraceContainer, read_wal_sexpr
from wal.eval import SEval

from wal_mcp import __version__

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = Server("wal-mcp")

_loaded_waveforms: dict[str, TraceContainer] = {}


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Return list of available waveform analysis tools."""
    return [
        Tool(
            name="load_waveform",
            description="Load a waveform file for analysis. Must be called before execute_wal_expression.",
            inputSchema={
                "type": "object",
                "properties": {
                    "waveform_file": {
                        "type": "string",
                        "description": "Path to waveform file (.vcd, .fst, etc.)",
                    },
                },
                "required": ["waveform_file"],
            },
        ),
        Tool(
            name="unload_waveform",
            description="Unload a previously loaded waveform file, freeing its resources.",
            inputSchema={
                "type": "object",
                "properties": {
                    "waveform_file": {
                        "type": "string",
                        "description": "Path to waveform file to unload",
                    },
                },
                "required": ["waveform_file"],
            },
        ),
        Tool(
            name="execute_wal_expression",
            description="""Execute WAL (Waveform Analysis Language) expressions for signal analysis.

The waveform must be loaded first via load_waveform.

WAL is a functional language with Lisp-like syntax. Key capabilities:
• Signal access: SIGNALS (list all), signal_name (get value)
• Time navigation: (step N), INDEX, (find condition)
• Search/filter: (find condition), (count condition)
• Logic: (and), (or), (not), (=), (!=), (<), (>)
• Math: (+), (-), (*), (/)

Examples:
• SIGNALS - List all signal names
• (length (find true)) - Total simulation length
• (count (= clk 1)) - Count clock high periods
• (find (and (= clk 1) (= data 0))) - Find clock high with data low
• (length (find (> counter 10))) - Time steps where counter > 10""",
            inputSchema={
                "type": "object",
                "properties": {
                    "waveform_file": {
                        "type": "string",
                        "description": "Path to a loaded waveform file",
                    },
                    "expression": {
                        "type": "string",
                        "description": "WAL expression to execute",
                    },
                },
                "required": ["waveform_file", "expression"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(tool_name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Route tool calls to appropriate handlers."""
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {tool_name}")]
    try:
        return await handler(arguments)
    except Exception as e:
        logger.error("Error in %s: %s", tool_name, e)
        return [TextContent(type="text", text=f"Error: {e}")]


async def _load_waveform(args: dict[str, Any]) -> list[TextContent]:
    """Load a waveform file for analysis.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file (.vcd, .fst, etc.)

    Returns:
        List of TextContent with confirmation message
    """
    waveform_file = args.get("waveform_file")

    if not waveform_file:
        return [
            TextContent(type="text", text="Error: Waveform file path cannot be empty.")
        ]

    path = Path(waveform_file)
    if not path.exists():
        return [
            TextContent(
                type="text", text=f"Error: Waveform file not found: {waveform_file}"
            )
        ]

    try:
        container = TraceContainer()
        container.load(waveform_file)
        _loaded_waveforms[waveform_file] = container
        logger.info("Loaded waveform: %s", waveform_file)
        return [TextContent(type="text", text=f"Loaded waveform: {waveform_file}")]
    except Exception as e:
        logger.error("Failed to load waveform file %s: %s", waveform_file, e)
        return [
            TextContent(
                type="text", text=f"Error loading waveform file '{waveform_file}': {e}"
            )
        ]


async def _unload_waveform(args: dict[str, Any]) -> list[TextContent]:
    """Unload a previously loaded waveform file.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file to unload

    Returns:
        List of TextContent with confirmation or error
    """
    waveform_file = args.get("waveform_file")

    if not waveform_file:
        return [
            TextContent(type="text", text="Error: Waveform file path cannot be empty.")
        ]

    if waveform_file not in _loaded_waveforms:
        return [
            TextContent(
                type="text", text=f"Error: Waveform not loaded: {waveform_file}"
            )
        ]

    del _loaded_waveforms[waveform_file]
    logger.info("Unloaded waveform: %s", waveform_file)
    return [TextContent(type="text", text=f"Unloaded waveform: {waveform_file}")]


async def _execute_wal_expression(args: dict[str, Any]) -> list[TextContent]:
    """Execute WAL expression on a loaded waveform.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to a loaded waveform file
            - expression: WAL expression to execute

    Returns:
        List of TextContent with expression execution results
    """
    waveform_file = args.get("waveform_file")
    expression = args.get("expression")

    if not waveform_file:
        return [
            TextContent(type="text", text="Error: Waveform file path cannot be empty.")
        ]

    if not expression:
        return [TextContent(type="text", text="Error: WAL expression cannot be empty.")]

    container = _loaded_waveforms.get(waveform_file)
    if container is None:
        return [
            TextContent(
                type="text",
                text=f"Error: Waveform not loaded: {waveform_file}\n"
                "Call load_waveform first.",
            )
        ]

    try:
        evaluator = SEval(container)
        parsed_expr = read_wal_sexpr(expression)
        result = evaluator.eval(parsed_expr)

        result_lines = [
            f"WAL Expression: {expression}",
            f"Waveform file: {waveform_file}",
            "",
            f"Result: {result}",
            f"Result type: {type(result).__name__}",
        ]

        if isinstance(result, list) and len(result) > 5:
            result_lines.append(f"Result length: {len(result)}")
            result_lines.append("First few elements:")
            for i, item in enumerate(result[:5]):
                result_lines.append(f"  [{i}]: {item}")
            if len(result) > 5:
                result_lines.append(f"  ... and {len(result) - 5} more")

    except Exception as e:
        all_signals = list(container.signals) if container is not None else []
        suggestions = _get_wal_error_suggestions(str(e), all_signals)

        result_lines = [
            f"WAL Expression: {expression}",
            f"Waveform file: {waveform_file}",
            "",
            f"Execution Error: {e!s}",
            "",
            *suggestions,
        ]

    return [TextContent(type="text", text="\n".join(result_lines))]


def _get_wal_error_suggestions(error_msg: str, signals: list[str]) -> list[str]:
    """Generate helpful WAL suggestions based on error message and available signals."""
    suggestions = []

    if "undefined" in error_msg.lower():
        suggestions.extend(
            [
                "Variable/function not found. Try:",
                "• Check signal names with SIGNALS",
                "• Use exact signal names from your waveform",
                f"• Available signals: {', '.join(signals[:5])}{'...' if len(signals) > 5 else ''}",
            ]
        )

    if "argument must be a list" in error_msg.lower():
        suggestions.extend(
            [
                "Function expects a list. Try:",
                "• (find condition) returns a list of time indices",
                "• (length (find condition)) to count matches",
                f"• Use signal names directly: {signals[0] if signals else 'signal_name'}",
            ]
        )

    if not suggestions:
        suggestions.extend(
            [
                "Common WAL patterns to try:",
                "• SIGNALS - List all signal names",
                "• (find (= signal_name value)) - Find when signal equals value",
                "• (count condition) - Count occurrences",
                "• (length (find true)) - Total simulation length",
            ]
        )

    if signals:
        first_signal = signals[0]
        suggestions.extend(
            [
                "",
                f"Examples with your signals (using '{first_signal}'):",
                f"• (find (= {first_signal} 1)) - Find when {first_signal} is high",
                f"• (count (= {first_signal} 0)) - Count when {first_signal} is low",
                f"• (length (find (!= {first_signal} 0))) - Time steps when {first_signal} != 0",
            ]
        )

    return suggestions


_ToolHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, list[TextContent]]]

_TOOL_HANDLERS: dict[str, _ToolHandler] = {
    "load_waveform": _load_waveform,
    "unload_waveform": _unload_waveform,
    "execute_wal_expression": _execute_wal_expression,
}


async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="wal-mcp",
                server_version=__version__,
                capabilities=app.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def main():
    """Main entry point for the MCP server.

    Starts the server using stdio transport for communication with MCP clients.
    """
    argparser = argparse.ArgumentParser(
        description="MCP server for RTL waveform analysis using WAL"
    )
    argparser.add_argument(
        "--version", action="store_true", help="Show server version and exit"
    )

    args = argparser.parse_args()
    if args.version:
        print(f"wal-mcp version {__version__}")
        return

    asyncio.run(_main())


if __name__ == "__main__":
    main()
