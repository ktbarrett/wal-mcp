import os
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from mcp.server.fastmcp.exceptions import ToolError

from wal_mcp import server

TRACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "traces"))
VCD_FILE = os.path.join(TRACE_DIR, "counter.vcd")
FST_FILE = os.path.join(TRACE_DIR, "counter.fst")

WAVEFORM_FILES = [VCD_FILE, FST_FILE]


@pytest.fixture(autouse=True)
def reset_session() -> None:
    """Give each test a fresh evaluator and trace container."""
    server._reset_session()


# Business-logic tests call the decorated tool functions directly (the
# decorator returns the function unchanged). Tests that need to exercise
# the schema, validation, or dispatch surface go through `server.app.call_tool`.


# ---------------------------------------------------------------------------
# execute_wal_expression: end-to-end persistence + error reporting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_load_via_wal_exposes_signals(waveform_file: str) -> None:
    """Loading a waveform via WAL exposes its signals."""
    await server.execute_wal_expression(f'(load "{waveform_file}")')
    text = await server.execute_wal_expression("SIGNALS")
    assert "tb.clk" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_valid(waveform_file: str) -> None:
    await server.execute_wal_expression(f'(load "{waveform_file}")')

    text = await server.execute_wal_expression("(length (find (= tb.clk 1)))")

    assert "WAL Expression: (length (find (= tb.clk 1)))" in text
    assert "Result: 40" in text
    assert "Result type: int" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_invalid_syntax(waveform_file: str) -> None:
    await server.execute_wal_expression(f'(load "{waveform_file}")')
    text = await server.execute_wal_expression("(count (= tb.clk 1)")
    assert "ParseError:" in text
    assert "Hint:" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_undefined_signal(waveform_file: str) -> None:
    await server.execute_wal_expression(f'(load "{waveform_file}")')
    text = await server.execute_wal_expression("(find (= non_existent_signal 1))")
    assert "WalEvalError:" in text
    assert "search_signals" in text


@pytest.mark.asyncio
async def test_execute_wal_no_waveform_loaded() -> None:
    """Errors with no waveform loaded suggest using load_trace."""
    text = await server.execute_wal_expression("tb.clk")
    assert "load_trace" in text


@pytest.mark.asyncio
async def test_wal_error_hint_dispatch() -> None:
    """Directly exercise each branch of _wal_error_hint."""
    from wal.ast_defs import WalEvalError
    from wal.reader import ParseError

    # No traces: load_trace prompt regardless of exception type.
    assert "load_trace" in server._wal_error_hint(RuntimeError("anything"))

    await server.load_trace(VCD_FILE)
    assert "parentheses" in server._wal_error_hint(ParseError("ctx", "bad parse"))
    assert "search_signals" in server._wal_error_hint(WalEvalError())
    # RuntimeError / AssertionError fall through to the trace-state hint. WAL's
    # SEval rewraps these into WalEvalError before they leave the evaluator, so
    # the only paths that hit this branch are direct WalSession calls.
    assert "loaded_traces" in server._wal_error_hint(RuntimeError("No traces loaded"))
    assert "loaded_traces" in server._wal_error_hint(AssertionError("trace id in use"))


@pytest.mark.asyncio
async def test_execute_wal_expression_empty_expression_rejected_by_schema() -> None:
    """Empty expressions are rejected by the Pydantic min_length=1 constraint."""
    with pytest.raises(ToolError):
        await server.app.call_tool("execute_wal_expression", {"expression": ""})


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_state_persists_across_calls(waveform_file: str) -> None:
    await server.execute_wal_expression(f'(load "{waveform_file}")')
    await server.execute_wal_expression("(define foo 42)")
    assert "Result: 42" in await server.execute_wal_expression("foo")

    await server.execute_wal_expression("(step 5)")
    assert "Result: 5" in await server.execute_wal_expression("INDEX")


@pytest.mark.asyncio
async def test_reset_session_clears_state() -> None:
    await server.execute_wal_expression(f'(load "{VCD_FILE}")')
    await server.execute_wal_expression("(define foo 99)")

    server._reset_session()

    assert list(server._session.container.signals) == []
    text = await server.execute_wal_expression("foo")
    assert "load_trace" in text  # session was reset, no traces remain


# ---------------------------------------------------------------------------
# load_trace / unload_trace / loaded_traces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_load_trace_returns_metadata(waveform_file: str) -> None:
    payload = await server.load_trace(waveform_file)
    assert payload["trace_id"] == "t0"
    assert payload["filename"] == waveform_file
    assert payload["n_signals"] > 0
    assert payload["max_index"] is not None


@pytest.mark.asyncio
async def test_load_trace_explicit_id() -> None:
    payload = await server.load_trace(VCD_FILE, trace_id="main")
    assert payload["trace_id"] == "main"


@pytest.mark.asyncio
async def test_load_trace_missing_path_rejected_by_schema() -> None:
    with pytest.raises(ToolError):
        await server.app.call_tool("load_trace", {})


@pytest.mark.asyncio
async def test_load_trace_missing_file_rejected_before_wal() -> None:
    """Missing files are caught before WAL is invoked (WAL would sys.exit)."""
    with pytest.raises(ToolError, match="No such file"):
        await server.load_trace("/nonexistent/file.vcd")
    assert await server.loaded_traces() == []


@pytest.mark.asyncio
async def test_unload_trace_removes_it() -> None:
    await server.load_trace(VCD_FILE)
    payload = await server.unload_trace("t0")
    assert payload == {"unloaded": "t0"}
    assert await server.loaded_traces() == []


@pytest.mark.asyncio
async def test_unload_unknown_trace_id() -> None:
    with pytest.raises(ToolError):
        await server.unload_trace("nope")


@pytest.mark.asyncio
async def test_loaded_traces_lists_all() -> None:
    await server.load_trace(VCD_FILE)
    await server.load_trace(FST_FILE, trace_id="fst")
    payload = await server.loaded_traces()
    ids = {t["trace_id"] for t in payload}
    assert ids == {"t0", "fst"}


# ---------------------------------------------------------------------------
# list_scopes / search_signals / get_signal_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_scopes_returns_hierarchy() -> None:
    await server.load_trace(VCD_FILE)
    payload = await server.list_scopes()
    assert "scopes" in payload
    assert any("tb" in s for s in payload["scopes"])


@pytest.mark.asyncio
async def test_list_scopes_unknown_trace_id() -> None:
    await server.load_trace(VCD_FILE)
    with pytest.raises(ToolError):
        await server.list_scopes(trace_id="nope")


@pytest.mark.asyncio
async def test_search_signals_glob_match() -> None:
    await server.load_trace(VCD_FILE)
    payload = await server.search_signals("tb.clk*")
    assert payload["total_matches"] >= 1
    names = [m["name"] for m in payload["matches"]]
    assert "tb.clk" in names


@pytest.mark.asyncio
async def test_search_signals_no_match() -> None:
    await server.load_trace(VCD_FILE)
    payload = await server.search_signals("definitely_not_a_signal_*")
    assert payload["total_matches"] == 0
    assert payload["matches"] == []


@pytest.mark.asyncio
async def test_search_signals_limit_truncates() -> None:
    await server.load_trace(VCD_FILE)
    payload = await server.search_signals("*", limit=1)
    assert payload["limit"] == 1
    assert payload["returned"] == 1
    assert payload["truncated"] is True
    assert payload["total_matches"] >= 1


@pytest.mark.asyncio
async def test_search_signals_limit_above_cap_rejected_by_schema() -> None:
    """The Pydantic Field(le=500) constraint rejects out-of-range limits."""
    await server.load_trace(VCD_FILE)
    with pytest.raises(ToolError):
        await server.app.call_tool("search_signals", {"pattern": "*", "limit": 9999})


@pytest.mark.asyncio
async def test_search_signals_missing_pattern_rejected_by_schema() -> None:
    await server.load_trace(VCD_FILE)
    with pytest.raises(ToolError):
        await server.app.call_tool("search_signals", {})


@pytest.mark.asyncio
async def test_get_signal_info_known_signal() -> None:
    await server.load_trace(VCD_FILE)
    payload = await server.get_signal_info("tb.clk")
    assert payload["name"] == "tb.clk"
    assert payload["leaf"] == "clk"
    assert payload["scope"] == "tb"
    assert payload["width"] is not None


@pytest.mark.asyncio
async def test_get_signal_info_unknown_signal() -> None:
    await server.load_trace(VCD_FILE)
    with pytest.raises(ToolError):
        await server.get_signal_info("tb.nope")


# ---------------------------------------------------------------------------
# Tool surface
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_exposes_all_tools() -> None:
    tools = await server.app.list_tools()
    names = {t.name for t in tools}
    assert names == {
        "load_trace",
        "unload_trace",
        "loaded_traces",
        "list_scopes",
        "search_signals",
        "get_signal_info",
        "execute_wal_expression",
    }
    for tool in tools:
        assert isinstance(tool.description, str)
        assert isinstance(tool.inputSchema, dict)


@pytest.mark.asyncio
async def test_search_signals_schema_advertises_limit_bounds() -> None:
    """Pydantic Field(ge=, le=) must surface in the JSON schema sent to clients."""
    tools = await server.app.list_tools()
    by_name = {t.name: t for t in tools}
    limit: dict[str, Any] = by_name["search_signals"].inputSchema["properties"]["limit"]
    assert limit["minimum"] == 1
    assert limit["maximum"] == 500
    assert limit["default"] == 50


@pytest.mark.asyncio
async def test_call_unknown_tool() -> None:
    with pytest.raises(ToolError):
        await server.app.call_tool("unknown_tool", {})
