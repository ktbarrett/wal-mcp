"""MCP server for RTL waveform analysis using WAL (Waveform Analysis Language).

The server exposes a small set of structured tools for waveform lifecycle and
signal discovery, plus an `execute_wal_expression` escape hatch for arbitrary
WAL queries. A single persistent WAL evaluator is shared across calls -- loaded
waveforms, defined variables, aliases, and the current INDEX of each trace
persist between calls.

Supported formats: VCD, FST (via WAL).
"""

import argparse
import asyncio
import fnmatch
import logging
import re
from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field
from wal.ast_defs import WalEvalError
from wal.core import TraceContainer, read_wal_sexpr
from wal.eval import SEval
from wal.reader import ParseError

from wal_mcp import __version__

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

_WAL_ERRORS: tuple[type[BaseException], ...] = (
    ParseError,
    WalEvalError,
    AssertionError,
    RuntimeError,
    SystemExit,
)

_SCOPE_SEP = "^"  # WAL multi-trace separator (TraceContainer uses tid^name)


def _glob_matcher(pattern: str) -> Callable[[str], bool]:
    """Return a fast predicate for a glob pattern.

    Common patterns -- '*foo*', 'foo*', '*foo', 'foo' -- compile to a string
    op (substring/startswith/endswith/equality), which is C-optimized in CPython
    and roughly an order of magnitude faster than re.match for large lists.
    Anything with '?' / '[…]' / interior '*' falls back to a compiled regex.
    """
    has_special = any(c in pattern for c in "?[")
    star_count = pattern.count("*")

    if not has_special:
        if star_count == 0:
            return pattern.__eq__
        body = pattern.strip("*")
        if "*" not in body:  # all '*' are at the ends
            starts = pattern.startswith("*")
            ends = pattern.endswith("*")
            if starts and ends:
                return lambda s: body in s
            if ends:
                return lambda s: s.startswith(body)
            if starts:
                return lambda s: s.endswith(body)

    regex = re.compile(fnmatch.translate(pattern))
    return lambda s: regex.match(s) is not None


class WalSession:
    """Holds a persistent WAL evaluator and its trace container.

    Tool handlers go through this object so test/global state is encapsulated
    and the WAL <-> Python boundary lives in one place.
    """

    def __init__(self) -> None:
        self.container: TraceContainer = TraceContainer()
        self.evaluator: SEval = SEval(self.container)

    def reset(self) -> None:
        self.container = TraceContainer()
        self.evaluator = SEval(self.container)

    def execute(self, expression: str) -> Any:
        return self.evaluator.eval(read_wal_sexpr(expression))

    def load(self, path: str, trace_id: str | None = None) -> str:
        """Load a waveform; returns the assigned trace id."""
        before: set[str] = set(self.container.traces)
        self.container.load(path, tid=trace_id)
        new_ids: set[str] = set(self.container.traces) - before
        if not new_ids:
            raise RuntimeError(f"Failed to load trace from {path!r}")
        assigned: str = next(iter(new_ids))
        return assigned

    def unload(self, trace_id: str) -> None:
        if trace_id not in self.container.traces:
            raise KeyError(trace_id)
        self.container.unload(trace_id)

    def loaded_traces(self) -> list[dict[str, Any]]:
        return [
            {
                "trace_id": tid,
                "filename": getattr(trace, "filename", None),
                "n_signals": len(getattr(trace, "rawsignals", [])),
                "max_index": getattr(trace, "max_index", None),
            }
            for tid, trace in self.container.traces.items()
        ]

    def list_scopes(self, trace_id: str | None = None) -> list[str]:
        if trace_id is None:
            return self.container.scopes  # type: ignore[no-any-return]
        if trace_id not in self.container.traces:
            raise KeyError(trace_id)
        return self.container.traces[trace_id].scopes  # type: ignore[no-any-return]

    def search_signals(
        self,
        pattern: str,
        limit: int,
        trace_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """Glob-match signals; returns (matches[:limit], total_match_count)."""
        all_signals: list[str] = self.container.signals
        if trace_id is not None:
            if trace_id not in self.container.traces:
                raise KeyError(trace_id)
            # In multi-trace mode signals are tagged "tid^name". Filter to this tid.
            if len(self.container.traces) > 1:
                prefix = f"{trace_id}{_SCOPE_SEP}"
                all_signals = [s for s in all_signals if s.startswith(prefix)]

        match = _glob_matcher(pattern)
        matched = [s for s in all_signals if match(s)]
        results = [self._signal_record(name) for name in matched[:limit]]
        return results, len(matched)

    def get_signal_info(self, name: str) -> dict[str, Any]:
        if not self.container.contains(name):
            raise KeyError(name)
        return self._signal_record(name)

    def _signal_record(self, name: str) -> dict[str, Any]:
        if _SCOPE_SEP in name:
            tid, bare = name.split(_SCOPE_SEP, 1)
        else:
            tid, bare = (
                next(iter(self.container.traces), None) or "",
                name,
            )
        scope, _, leaf = bare.rpartition(".")
        try:
            width = self.container.signal_width(name)
        except Exception:
            width = None
        return {
            "name": name,
            "leaf": leaf,
            "scope": scope,
            "width": width,
            "trace_id": tid,
        }


_session: WalSession = WalSession()


def _reset_session() -> None:
    """Reset the persistent WAL session. Intended for tests."""
    _session.reset()


app = FastMCP("wal-mcp")


@app.tool(
    description=(
        "Load a VCD or FST waveform file into the persistent session. "
        "Returns the assigned trace id and basic stats. Use list_scopes/"
        "search_signals to explore; do not enumerate all signals -- real "
        "designs have 10k-100k."
    ),
)
async def load_trace(
    path: Annotated[str, Field(description="Path to .vcd or .fst file")],
    trace_id: Annotated[
        str | None,
        Field(description="Optional explicit trace id (default auto: t0, t1, ...)"),
    ] = None,
) -> dict[str, Any]:
    try:
        assigned = _session.load(path, trace_id=trace_id)
    except _WAL_ERRORS as e:
        raise ToolError(f"Error loading {path!r}: {e or type(e).__name__}") from e
    trace = _session.container.traces[assigned]
    return {
        "trace_id": assigned,
        "filename": getattr(trace, "filename", path),
        "n_signals": len(getattr(trace, "rawsignals", [])),
        "n_scopes": len(getattr(trace, "scopes", [])),
        "max_index": getattr(trace, "max_index", None),
    }


@app.tool(description="Unload a previously loaded trace by id.")
async def unload_trace(
    trace_id: Annotated[str, Field(description="Id returned by load_trace")],
) -> dict[str, Any]:
    try:
        _session.unload(trace_id)
    except KeyError as e:
        raise ToolError(f"No loaded trace with id {trace_id!r}.") from e
    return {"unloaded": trace_id}


@app.tool(
    description="List currently loaded traces with id, filename, n_signals, max_index.",
)
async def loaded_traces() -> list[dict[str, Any]]:
    return _session.loaded_traces()


@app.tool(
    description=(
        "List scope (module/hierarchy) names. Optionally filter to one trace. "
        "Use this before search_signals to narrow your pattern."
    ),
)
async def list_scopes(
    trace_id: Annotated[
        str | None, Field(description="Optional trace id filter")
    ] = None,
) -> dict[str, Any]:
    try:
        scopes = _session.list_scopes(trace_id)
    except KeyError as e:
        raise ToolError(f"No loaded trace with id {trace_id!r}.") from e
    return {"trace_id": trace_id, "scopes": scopes}


@app.tool(
    description=(
        "Find signals by glob pattern (e.g. 'tb.dut.*', '*clk*'). Returns at most "
        "`limit` matches plus the total match count. Designs may have 100k+ signals -- "
        "always supply a narrow pattern; raising the limit instead of narrowing the "
        "pattern is a mistake."
    ),
)
async def search_signals(
    pattern: Annotated[
        str,
        Field(description="fnmatch glob: * (any), ? (one char), [abc] (set)"),
    ],
    limit: Annotated[
        int,
        Field(ge=1, le=500, description="Max matches to return (hard cap 500)"),
    ] = 50,
    trace_id: Annotated[
        str | None, Field(description="Optional trace id filter")
    ] = None,
) -> dict[str, Any]:
    try:
        matches, total = _session.search_signals(
            pattern, limit=limit, trace_id=trace_id
        )
    except KeyError as e:
        raise ToolError(f"No loaded trace with id {trace_id!r}.") from e
    return {
        "pattern": pattern,
        "total_matches": total,
        "returned": len(matches),
        "limit": limit,
        "truncated": total > len(matches),
        "matches": matches,
    }


@app.tool(description="Get width, scope, and trace id for a known signal name.")
async def get_signal_info(
    name: Annotated[str, Field(description="Fully-qualified signal name")],
) -> dict[str, Any]:
    try:
        return _session.get_signal_info(name)
    except KeyError as e:
        raise ToolError(f"No signal named {name!r} in any loaded trace.") from e


@app.tool(
    description=(
        "Escape hatch: evaluate an arbitrary WAL expression on the persistent "
        "evaluator. Use the structured tools (load_trace, search_signals, etc.) "
        "for routine ops; reach for this only for real WAL queries (find/count/"
        "whenever/timeframe/define). Loaded waveforms, defines, and INDEX persist "
        "across calls."
    ),
)
async def execute_wal_expression(
    expression: Annotated[
        str, Field(min_length=1, description="WAL expression to execute")
    ],
) -> str:
    try:
        result = _session.execute(expression)

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
            result_lines.append(f"  ... and {len(result) - 5} more")

    except _WAL_ERRORS as e:
        signals = list(_session.container.signals)
        message = str(e) or type(e).__name__
        suggestions = _get_wal_error_suggestions(message, signals)

        result_lines = [
            f"WAL Expression: {expression}",
            "",
            f"Execution Error: {message}",
            "",
            *suggestions,
        ]

    return "\n".join(result_lines)


def _get_wal_error_suggestions(error_msg: str, signals: list[str]) -> list[str]:
    """Generate helpful WAL suggestions based on error message and available signals."""
    if not signals:
        return [
            "No waveform is loaded. Load one with the load_trace tool.",
        ]

    suggestions: list[str] = []

    if "undefined" in error_msg.lower():
        suggestions.extend(
            [
                "Variable/function not found. Try:",
                "- Use search_signals to find a valid signal name",
                f"- A loaded signal: {signals[0]}",
            ]
        )

    if "argument must be a list" in error_msg.lower():
        suggestions.extend(
            [
                "Function expects a list. Try:",
                "- (find condition) returns a list of time indices",
                "- (length (find condition)) to count matches",
                f"- Use signal names directly: {signals[0]}",
            ]
        )

    if not suggestions:
        suggestions.extend(
            [
                "Common WAL patterns:",
                "- (find (= signal_name value)) - Find when signal equals value",
                "- (count condition) - Count occurrences",
                "- (length (find #t)) - Total simulation length",
            ]
        )

    first_signal = signals[0]
    suggestions.extend(
        [
            "",
            f"Examples with your signals (using '{first_signal}'):",
            f"- (find (= {first_signal} 1))",
            f"- (count (= {first_signal} 0))",
        ]
    )

    return suggestions


def main() -> None:
    """Main entry point for the MCP server.

    Starts the server using stdio transport for communication with MCP clients.
    """
    argparser = argparse.ArgumentParser(
        prog="wal-mcp-server",
        description="MCP server for RTL waveform analysis using WAL",
    )
    argparser.add_argument(
        "--version", action="store_true", help="Show server version and exit"
    )

    args = argparser.parse_args()
    if args.version:
        print(f"wal-mcp-server version {__version__}")
        return

    asyncio.run(app.run_stdio_async())


if __name__ == "__main__":
    main()
