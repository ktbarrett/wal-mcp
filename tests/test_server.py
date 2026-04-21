import os
import sys
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from mcp.types import TextContent

from wal_mcp import server

TRACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "traces"))
VCD_FILE = os.path.join(TRACE_DIR, "counter.vcd")
FST_FILE = os.path.join(TRACE_DIR, "counter.fst")

WAVEFORM_FILES = [VCD_FILE, FST_FILE]


@pytest.fixture(autouse=True)
def reset_evaluator() -> None:
    """Give each test a fresh evaluator and trace container."""
    server._reset_evaluator()


async def _exec(expr: str) -> str:
    result = await server._execute_wal_expression({"expression": expr})
    return result[0].text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_load_via_wal_exposes_signals(waveform_file: str) -> None:
    """Loading a waveform via WAL exposes its signals."""
    await _exec(f'(load "{waveform_file}")')
    text = await _exec("SIGNALS")
    assert "tb.clk" in text


@pytest.mark.asyncio
async def test_load_invalid_path_surfaces_wal_error() -> None:
    """Loading a nonexistent file surfaces a WAL error."""
    text = await _exec('(load "/nonexistent/path/file.vcd")')
    assert "Execution Error:" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_valid(waveform_file: str) -> None:
    """Test execute_wal_expression with a valid expression after load."""
    await _exec(f'(load "{waveform_file}")')

    text = await _exec("(length (find (= tb.clk 1)))")

    assert "WAL Expression: (length (find (= tb.clk 1)))" in text
    assert "Result: 40" in text
    assert "Result type: int" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_invalid_syntax(waveform_file: str) -> None:
    """Test execute_wal_expression with invalid syntax."""
    await _exec(f'(load "{waveform_file}")')
    text = await _exec("(count (= tb.clk 1)")
    assert "Execution Error:" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_undefined_signal(waveform_file: str) -> None:
    """Test execute_wal_expression with an undefined signal."""
    await _exec(f'(load "{waveform_file}")')
    text = await _exec("(find (= non_existent_signal 1))")
    assert "Execution Error:" in text


@pytest.mark.asyncio
async def test_execute_wal_no_waveform_loaded() -> None:
    """Errors with no waveform loaded suggest using (load ...)."""
    text = await _exec("tb.clk")
    assert "Execution Error:" in text
    assert "(load " in text


@pytest.mark.asyncio
async def test_execute_wal_expression_empty_expression() -> None:
    """Test execute_wal_expression with an empty expression."""
    result = await server._execute_wal_expression({"expression": ""})
    assert "Error:" in result[0].text
    assert "empty" in result[0].text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_state_persists_across_calls(waveform_file: str) -> None:
    """Defines and INDEX persist across multiple execute calls."""
    await _exec(f'(load "{waveform_file}")')
    await _exec("(define foo 42)")
    assert "Result: 42" in await _exec("foo")

    await _exec("(step 5)")
    assert "Result: 5" in await _exec("INDEX")


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_unload_via_wal(waveform_file: str) -> None:
    """(unload ...) removes the trace from the container."""
    await _exec(f'(load "{waveform_file}")')
    assert len(list(server._container.signals)) > 0

    await _exec("(unload 't0)")
    assert list(server._container.signals) == []


@pytest.mark.asyncio
async def test_reset_evaluator_clears_state() -> None:
    """_reset_evaluator() drops loaded waveforms and bindings."""
    await _exec(f'(load "{VCD_FILE}")')
    await _exec("(define foo 99)")

    server._reset_evaluator()

    assert list(server._container.signals) == []
    assert "Execution Error:" in await _exec("foo")


@pytest.mark.asyncio
async def test_list_tools_return_format() -> None:
    """list_tools returns the single execute tool."""
    tools = await server.list_tools()

    assert isinstance(tools, list)
    assert len(tools) == 1

    tool = tools[0]
    assert tool.name == "execute_wal_expression"
    assert isinstance(tool.description, str)
    assert isinstance(tool.inputSchema, dict)


@pytest.mark.asyncio
async def test_call_tool_routing() -> None:
    """Test that call_tool routes to the correct function."""
    mock_handler = AsyncMock(return_value=[TextContent(type="text", text="mocked")])

    with patch.dict(server._TOOL_HANDLERS, {"execute_wal_expression": mock_handler}):
        await server.call_tool("execute_wal_expression", {})
        mock_handler.assert_called_once()

    result = await server.call_tool("unknown_tool", {})
    assert "Unknown tool: unknown_tool" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_exception_handling() -> None:
    """Test that call_tool handles exceptions properly."""

    async def raise_error(_args: dict[str, Any]) -> list[TextContent]:
        raise RuntimeError("test error")

    with patch.dict(server._TOOL_HANDLERS, {"execute_wal_expression": raise_error}):
        result = await server.call_tool("execute_wal_expression", {})
        assert isinstance(result, list)
        assert len(result) == 1
        assert "Error:" in result[0].text
