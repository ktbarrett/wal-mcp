"""MCP server for RTL waveform analysis using WAL (Waveform Analysis Language).

This server provides a single tool that executes WAL expressions against a
persistent evaluator. Loaded waveforms, defined variables, aliases, and the
current INDEX of each trace all persist across tool calls. Waveform lifecycle
is managed from inside WAL via (load ...) and (unload ...).

Supported formats: VCD, FST (via WAL)
"""

import argparse
import asyncio
import logging
from collections.abc import Callable, Coroutine
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

_container: TraceContainer = TraceContainer()
_evaluator: SEval = SEval(_container)


def _reset_evaluator() -> None:
    """Reset the persistent WAL evaluator and trace container.

    Intended for tests; the running server keeps a single evaluator for its lifetime.
    """
    global _container, _evaluator
    _container = TraceContainer()
    _evaluator = SEval(_container)


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Return list of available waveform analysis tools."""
    return [
        Tool(
            name="execute_wal_expression",
            description="""Execute a WAL (Waveform Analysis Language) expression.

A single persistent WAL evaluator is shared across calls — loaded waveforms,
defined variables, aliases, and the current INDEX of each trace all persist
between calls.

Manage waveforms from inside WAL:
  (load "path/to/file.vcd")        — load with auto id (t0, t1, ...)
  (load "path/to/file.fst" 'b)     — load with explicit id
  (unload 't0)                     — unload by id

WAL is a functional, Lisp-like language. Key capabilities:
• Signal access: SIGNALS (list all), signal_name (value at INDEX)
• Time navigation: (step N), INDEX, signal@offset
• Search/filter: (find condition), (count condition), (whenever cond body)
• Logic: (&&), (||), (!), (=), (!=), (<), (>)
• Math: (+), (-), (*), (/)

Examples:
• (load "trace.vcd")               — load a waveform
• SIGNALS                           — list all signal names
• (length (find #t))                — total simulation length
• (count (= clk 1))                 — count clock high periods
• (find (&& (= clk 1) (= data 0))) — find clock high with data low""",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "WAL expression to execute",
                    },
                },
                "required": ["expression"],
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


async def _execute_wal_expression(args: dict[str, Any]) -> list[TextContent]:
    """Execute a WAL expression on the persistent evaluator.

    Args:
        args: Dictionary containing:
            - expression: WAL expression to execute

    Returns:
        List of TextContent with the result, or an error message with suggestions.
    """
    expression = args.get("expression")

    if not expression:
        return [TextContent(type="text", text="Error: WAL expression cannot be empty.")]

    try:
        parsed_expr = read_wal_sexpr(expression)
        result = _evaluator.eval(parsed_expr)

        result_lines = [
            f"WAL Expression: {expression}",
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

    except (Exception, SystemExit) as e:
        signals = list(_container.signals)
        message = str(e) or type(e).__name__
        suggestions = _get_wal_error_suggestions(message, signals)

        result_lines = [
            f"WAL Expression: {expression}",
            "",
            f"Execution Error: {message}",
            "",
            *suggestions,
        ]

    return [TextContent(type="text", text="\n".join(result_lines))]


def _get_wal_error_suggestions(error_msg: str, signals: list[str]) -> list[str]:
    """Generate helpful WAL suggestions based on error message and available signals."""
    if not signals:
        return [
            "No waveform is loaded. Load one with:",
            '  (load "path/to/file.vcd")',
        ]

    suggestions: list[str] = []

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
                f"• Use signal names directly: {signals[0]}",
            ]
        )

    if not suggestions:
        suggestions.extend(
            [
                "Common WAL patterns to try:",
                "• SIGNALS - List all signal names",
                "• (find (= signal_name value)) - Find when signal equals value",
                "• (count condition) - Count occurrences",
                "• (length (find #t)) - Total simulation length",
            ]
        )

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
