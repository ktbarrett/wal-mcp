"""MCP server for RTL waveform analysis using WAL (Waveform Analysis Language).

This server provides tools for analyzing waveform files from RTL simulations,
allowing LLMs to inspect signals, detect transitions, and debug hardware designs.

Supported formats: VCD, FST (via WAL)
"""

import argparse
import asyncio
import logging
import os
import re
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

# Cache: {file_path: (modification_time, TraceContainer)}
_waveform_cache: dict[str, tuple[float, TraceContainer]] = {}


@app.list_tools()
async def list_tools() -> list[Tool]:
    """Return list of available waveform analysis tools."""
    return [
        Tool(
            name="get_signal_list",
            description="Get hierarchical list of signals from waveform file",
            inputSchema={
                "type": "object",
                "properties": {
                    "waveform_file": {
                        "type": "string",
                        "description": "Path to waveform file (.vcd, .fst, etc.)",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Optional regex pattern to filter signals (e.g., 'cpu.*', 'top\\.m1\\.*')",
                        "default": "",
                    },
                },
                "required": ["waveform_file"],
            },
        ),
        Tool(
            name="get_signal_transitions",
            description="Get signal transitions within a time range",
            inputSchema={
                "type": "object",
                "properties": {
                    "waveform_file": {
                        "type": "string",
                        "description": "Path to waveform file",
                    },
                    "signal_name": {
                        "type": "string",
                        "description": "Full signal name (e.g., 'cpu.pc')",
                    },
                    "start_time": {
                        "type": "integer",
                        "description": "Start time in simulation time units",
                        "default": 0,
                    },
                    "end_time": {
                        "type": "integer",
                        "description": "End time in simulation time units (0 = end of simulation)",
                        "default": 0,
                    },
                },
                "required": ["waveform_file", "signal_name"],
            },
        ),
        Tool(
            name="get_waveform_length",
            description="Get the length of the waveform file",
            inputSchema={
                "type": "object",
                "properties": {
                    "waveform_file": {
                        "type": "string",
                        "description": "Path to waveform file",
                    },
                },
                "required": ["waveform_file"],
            },
        ),
        Tool(
            name="execute_wal_expression",
            description="""Execute WAL (Waveform Analysis Language) expressions for advanced signal analysis.

WAL is a functional language with Lisp-like syntax. Key capabilities:
• Signal access: SIGNALS (list all), signal_name (get value)
• Time navigation: (step N), INDEX, (find condition)
• Search/filter: (find condition), (count condition)
• Logic: (and), (or), (not), (=), (!=), (<), (>)
• Math: (+), (-), (*), (/)

Examples:
• (count (= clk 1)) - Count clock high periods
• (find (and (= clk 1) (= data 0))) - Find clock high with data low
• (length (find (> counter 10))) - Time steps where counter > 10
• (find (= overflow 1)) - Find overflow events

Use get_wal_help for detailed documentation and examples.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "waveform_file": {
                        "type": "string",
                        "description": "Path to waveform file",
                    },
                    "expression": {
                        "type": "string",
                        "description": "WAL expression to execute",
                    },
                },
                "required": ["waveform_file", "expression"],
            },
        ),
        Tool(
            name="get_wal_examples",
            description="Get WAL examples customized for specific waveform signals",
            inputSchema={
                "type": "object",
                "properties": {
                    "waveform_file": {
                        "type": "string",
                        "description": "Path to waveform file",
                    },
                },
                "required": ["waveform_file"],
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


async def _load_waveform(waveform_file: str) -> TraceContainer:
    """Load waveform file using WAL, with caching that checks file modification time.

    Args:
        waveform_file: Path to waveform file (.vcd, .fst, etc.)

    Returns:
        TraceContainer: WAL container with loaded waveform data

    Raises:
        FileNotFoundError: If the waveform file does not exist.
        ValueError: If the waveform_file path is empty.
        Exception: For other errors during loading.
    """
    if not waveform_file:
        raise ValueError("Waveform file path cannot be empty.")

    try:
        current_mtime = os.path.getmtime(waveform_file)
    except FileNotFoundError:
        logger.error("Waveform file not found: %s", waveform_file)
        raise
    except OSError as e:
        logger.error("Error accessing waveform file %s: %s", waveform_file, e)
        raise

    # Check if file is cached and still current
    if waveform_file in _waveform_cache:
        cached_mtime, container = _waveform_cache[waveform_file]
        if cached_mtime == current_mtime:
            logger.debug("Using cached waveform: %s", waveform_file)
            return container
        else:
            logger.info(
                "Waveform file %s changed (mtime: %s -> %s), reloading...",
                waveform_file,
                cached_mtime,
                current_mtime,
            )

    # Load fresh copy
    logger.info("Loading waveform file: %s", waveform_file)
    try:
        container = TraceContainer()
        container.load(waveform_file)
        _waveform_cache[waveform_file] = (current_mtime, container)
        logger.debug("Cached waveform %s with mtime: %s", waveform_file, current_mtime)
    except Exception as e:
        logger.error("Failed to load waveform file %s: %s", waveform_file, e)
        raise

    return container


async def _get_signal_list(args: dict[str, Any]) -> list[TextContent]:
    """Get hierarchical list of signals from waveform file.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file
            - pattern: Optional regex pattern to filter signal names

    Returns:
        List of TextContent with formatted signal list
    """
    waveform_file = args.get("waveform_file")
    pattern = args.get("pattern", "")

    try:
        container = await _load_waveform(waveform_file)
        all_signals = container.signals

        if pattern:
            regex = re.compile(pattern)
            filtered_signals = [s for s in all_signals if regex.search(s)]
        else:
            filtered_signals = all_signals

        result_lines = [f"Signals in {waveform_file}:"]
        if pattern:
            result_lines.append(f"Filter pattern: {pattern}")

        for signal in filtered_signals:
            width = container.signal_width(signal)
            bit_word = "bit" if width == 1 else "bits"
            result_lines.append(f"  {signal} [{width} {bit_word}]")

        if not filtered_signals:
            if pattern:
                result_lines.append("  No signals found matching regex pattern.")
            else:
                result_lines.append("  No signals found in waveform file.")

    except (FileNotFoundError, ValueError) as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except re.error as e:
        result_lines = [
            f"Signals in {waveform_file}:",
            f"Invalid regex pattern '{pattern}': {e}",
            "Please provide a valid regex pattern.",
        ]
    except Exception as e:
        return [
            TextContent(
                type="text",
                text=f"Error processing waveform file '{waveform_file}': {e}",
            )
        ]

    return [TextContent(type="text", text="\n".join(result_lines))]


async def _get_signal_transitions(args: dict[str, Any]) -> list[TextContent]:
    """Get signal transitions within specified time range.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file
            - signal_name: Full signal name (e.g., 'cpu.pc')
            - start_time: Start time in simulation units (optional, default: 0)
            - end_time: End time in simulation units (optional, default: end)

    Returns:
        List of TextContent with signal transition information
    """
    waveform_file = args.get("waveform_file")
    signal_name = args.get("signal_name")
    start_time = args.get("start_time", 0)
    end_time = args.get("end_time", 0)

    try:
        if not signal_name:
            raise ValueError("Signal name cannot be empty.")

        container = await _load_waveform(waveform_file)

        if signal_name not in container.signals:
            return [
                TextContent(
                    type="text",
                    text=f"Error: Signal '{signal_name}' not found in {waveform_file}",
                )
            ]

        result_lines = [f"Signal analysis for '{signal_name}':"]
        width = container.signal_width(signal_name)
        bit_word = "bit" if width == 1 else "bits"
        result_lines.append(f"  Width: {width} {bit_word}")

        evaluator = SEval(container)
        actual_end_time = end_time

        if end_time == 0:
            waveform_length = evaluator.eval(read_wal_sexpr("(length (find true))"))
            actual_end_time = waveform_length - 1
        container.step(start_time)
        prev_value = container.signal_value(signal_name)
        result_lines.append(f"  Initial value at time {start_time}: {prev_value}")

        transitions = []
        current_time = start_time

        while current_time < actual_end_time:
            try:
                container.step(1)  # Advance by 1 step
                current_time += 1
                curr_value = container.signal_value(signal_name)

                if prev_value != curr_value:
                    transitions.append(
                        f"  Time {current_time}: {prev_value} -> {curr_value}"
                    )
                prev_value = curr_value

            except Exception:
                logger.debug(
                    "Stopped iterating signal '%s' at time %s",
                    signal_name,
                    current_time,
                    exc_info=True,
                )
                break
        if transitions:
            result_lines.append("")
            result_lines.append("Transitions detected:")
            result_lines.extend(transitions)
        else:
            result_lines.append("")
            result_lines.append("No transitions detected in time range.")

        time_range = f"{start_time} to {actual_end_time if end_time == 0 else end_time}"
        result_lines.append("")
        result_lines.append(f"Time range analyzed: {time_range}")
        result_lines.append(f"Total time steps checked: {current_time - start_time}")

    except (FileNotFoundError, ValueError) as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        result_lines = [f"Error during transition detection for '{signal_name}': {e}"]

    return [TextContent(type="text", text="\n".join(result_lines))]


async def _get_waveform_length(args: dict[str, Any]) -> list[TextContent]:
    """Get the length of the waveform file.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file

    Returns:
        List of TextContent with waveform length information
    """
    waveform_file = args.get("waveform_file")

    try:
        container = await _load_waveform(waveform_file)
        evaluator = SEval(container)
        waveform_length = evaluator.eval(read_wal_sexpr("(length (find true))"))

        result_lines = [
            f"Waveform file: {waveform_file}",
            f"Length: {waveform_length} time steps",
            f"Time range: 0 to {waveform_length - 1}",
            "Method: WAL (length (find true))",
        ]

    except (FileNotFoundError, ValueError) as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        result_lines = [
            f"Waveform file: {waveform_file}",
            f"Error getting waveform length: {str(e)}",
        ]

    return [TextContent(type="text", text="\n".join(result_lines))]


async def _execute_wal_expression(args: dict[str, Any]) -> list[TextContent]:
    """Execute WAL expression on waveform file.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file
            - expression: WAL expression to execute

    Returns:
        List of TextContent with expression execution results
    """
    waveform_file = args.get("waveform_file")
    expression = args.get("expression")

    try:
        if not expression:
            raise ValueError("WAL expression cannot be empty.")

        container = await _load_waveform(waveform_file)
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

    except (FileNotFoundError, ValueError) as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        # Get signal-specific suggestions
        all_signals = (
            list(_waveform_cache[waveform_file][1].signals)
            if waveform_file in _waveform_cache
            else []
        )
        suggestions = _get_wal_error_suggestions(str(e), all_signals)

        result_lines = [
            f"WAL Expression: {expression}",
            f"Waveform file: {waveform_file}",
            "",
            f"Execution Error: {str(e)}",
            "",
            *suggestions,
            "",
            "For more help: use get_wal_help with topics 'examples', 'functions', or 'debugging'",
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
        # Generic suggestions
        suggestions.extend(
            [
                "Common WAL patterns to try:",
                "• SIGNALS - List all signal names",
                "• (find (= signal_name value)) - Find when signal equals value",
                "• (count condition) - Count occurrences",
                "• (length (find true)) - Total simulation length",
            ]
        )

    # Add signal-specific examples
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


async def _get_wal_examples(args: dict[str, Any]) -> list[TextContent]:
    """Get WAL examples customized for the specific waveform signals.

    Args:
        args: Dictionary containing:
            - waveform_file: Path to waveform file

    Returns:
        List of TextContent with signal-specific WAL examples
    """
    waveform_file = args["waveform_file"]

    try:
        container = await _load_waveform(waveform_file)
        all_signals = list(container.signals)

        if not all_signals:
            return [TextContent(type="text", text="No signals found in waveform file")]

        # Categorize signals by type for better examples
        clock_signals = [s for s in all_signals if "clk" in s.lower()]
        reset_signals = [
            s for s in all_signals if "reset" in s.lower() or "rst" in s.lower()
        ]
        counter_signals = [
            s for s in all_signals if "counter" in s.lower() or "count" in s.lower()
        ]

        result_lines = [
            f"WAL Examples for {waveform_file}",
            "=" * 60,
            f"Available signals: {len(all_signals)} total",
            "",
        ]

        # Basic signal access examples
        result_lines.extend(
            [
                "BASIC SIGNAL ACCESS:",
                "• SIGNALS - List all signals in waveform",
                f"• {all_signals[0]} - Get current value of {all_signals[0]}",
                "• INDEX - Current time index",
                "• (length (find true)) - Total simulation length",
                "",
            ]
        )

        # Clock-specific examples
        if clock_signals:
            clk = clock_signals[0]
            result_lines.extend(
                [
                    f"CLOCK ANALYSIS (using {clk}):",
                    f"• (find (= {clk} 1)) - Find all clock high times",
                    f"• (length (find (= {clk} 1))) - Count clock high periods",
                    f"• (step 0) (find (= {clk} 1)) - Go to start, find clock highs",
                    "",
                ]
            )

        # Reset-specific examples
        if reset_signals:
            rst = reset_signals[0]
            result_lines.extend(
                [
                    f"RESET ANALYSIS (using {rst}):",
                    f"• (find (= {rst} 1)) - Find reset assertion times",
                    f"• (find (= {rst} 0)) - Find reset deassertion times",
                    f"• (length (find (= {rst} 1))) - Total reset duration",
                    "",
                ]
            )

        # Counter-specific examples
        if counter_signals:
            cnt = counter_signals[0]
            result_lines.extend(
                [
                    f"COUNTER ANALYSIS (using {cnt}):",
                    f"• (find (= {cnt} 0)) - Find when counter is zero",
                    f"• (find (> {cnt} 10)) - Find when counter > 10",
                    f"• (length (find (>= {cnt} 1))) - Non-zero periods",
                    "",
                ]
            )

        # Multi-signal analysis examples
        if len(all_signals) >= 2:
            sig1, sig2 = all_signals[0], all_signals[1]
            result_lines.extend(
                [
                    "MULTI-SIGNAL PATTERNS:",
                    f"• (find (&& (= {sig1} 1) (= {sig2} 0))) - {sig1} high AND {sig2} low",
                    f"• (find (|| (= {sig1} 1) (= {sig2} 1))) - Either signal high",
                    f"• (find (&& (>= {sig1} 1) (>= {sig2} 1))) - Both signals non-zero",
                    "",
                ]
            )

        # Debugging patterns
        result_lines.extend(
            [
                "DEBUGGING PATTERNS:",
                "• (find (= overflow 1)) - Find overflow events (if overflow signal exists)",
                "• (find (&& (= valid 1) (= ready 0))) - Handshake stalls (if protocol signals exist)",
                f"• (length (find (> {all_signals[-1]} 15))) - Values out of range (example: >15)",
                "",
                "TIMING ANALYSIS:",
                "• (step 0) INDEX - Go to start and show time",
                f"• (step 10) {all_signals[0]} - Advance 10 steps and show signal value",
                f"• (find (= {all_signals[0]} target)) - Find specific signal values",
                "",
                "For more help: use get_wal_help with topics 'functions', 'debugging', or 'syntax'",
            ]
        )

    except Exception as e:
        result_lines = [
            f"Error loading waveform {waveform_file}: {str(e)}",
            "",
            "Use get_wal_help for general WAL documentation",
        ]

    return [TextContent(type="text", text="\n".join(result_lines))]


_ToolHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, list[TextContent]]]

_TOOL_HANDLERS: dict[str, _ToolHandler] = {
    "get_signal_list": _get_signal_list,
    "get_signal_transitions": _get_signal_transitions,
    "get_waveform_length": _get_waveform_length,
    "execute_wal_expression": _execute_wal_expression,
    "get_wal_examples": _get_wal_examples,
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
