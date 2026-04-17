import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from mcp.types import TextContent

from wal_mcp import server

# Paths to the sample waveform files
TRACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "traces"))
VCD_FILE = os.path.join(TRACE_DIR, "counter.vcd")
FST_FILE = os.path.join(TRACE_DIR, "counter.fst")

WAVEFORM_FILES = [VCD_FILE, FST_FILE]


@pytest.fixture(autouse=True)
def clear_loaded_waveforms():
    """Clear loaded waveforms before each test."""
    server._loaded_waveforms.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_load_waveform(waveform_file):
    """Test loading a waveform file."""
    assert len(server._loaded_waveforms) == 0

    result = await server._load_waveform({"waveform_file": waveform_file})

    assert len(result) == 1
    assert f"Loaded waveform: {waveform_file}" in result[0].text
    assert waveform_file in server._loaded_waveforms


@pytest.mark.asyncio
async def test_load_waveform_invalid_path():
    """Test loading a nonexistent waveform file."""
    result = await server._load_waveform(
        {"waveform_file": "/nonexistent/path/file.vcd"}
    )

    assert "Error:" in result[0].text
    assert len(server._loaded_waveforms) == 0


@pytest.mark.asyncio
async def test_load_waveform_empty_path():
    """Test loading with an empty path."""
    result = await server._load_waveform({"waveform_file": ""})

    assert "Error:" in result[0].text
    assert "empty" in result[0].text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_load_waveform_reload(waveform_file):
    """Test that reloading replaces the entry."""
    await server._load_waveform({"waveform_file": waveform_file})
    first_container = server._loaded_waveforms[waveform_file]

    await server._load_waveform({"waveform_file": waveform_file})
    second_container = server._loaded_waveforms[waveform_file]

    assert first_container is not second_container
    assert len(server._loaded_waveforms) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_unload_waveform(waveform_file):
    """Test unloading a loaded waveform."""
    await server._load_waveform({"waveform_file": waveform_file})
    assert waveform_file in server._loaded_waveforms

    result = await server._unload_waveform({"waveform_file": waveform_file})

    assert f"Unloaded waveform: {waveform_file}" in result[0].text
    assert waveform_file not in server._loaded_waveforms


@pytest.mark.asyncio
async def test_unload_waveform_not_loaded():
    """Test unloading a waveform that isn't loaded."""
    result = await server._unload_waveform({"waveform_file": "/not/loaded.vcd"})

    assert "Error:" in result[0].text
    assert "not loaded" in result[0].text.lower()


@pytest.mark.asyncio
async def test_unload_waveform_empty_path():
    """Test unloading with an empty path."""
    result = await server._unload_waveform({"waveform_file": ""})

    assert "Error:" in result[0].text
    assert "empty" in result[0].text.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_valid(waveform_file):
    """Test execute_wal_expression with a valid expression."""
    await server._load_waveform({"waveform_file": waveform_file})

    result = await server._execute_wal_expression(
        {
            "waveform_file": waveform_file,
            "expression": "(length (find (= tb.clk 1)))",
        }
    )

    text = result[0].text
    assert "WAL Expression: (length (find (= tb.clk 1)))" in text
    assert "Result: 40" in text
    assert "Result type: int" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_invalid_syntax(waveform_file):
    """Test execute_wal_expression with invalid syntax."""
    await server._load_waveform({"waveform_file": waveform_file})

    result = await server._execute_wal_expression(
        {
            "waveform_file": waveform_file,
            "expression": "(count (= tb.clk 1)",
        }
    )

    text = result[0].text
    assert "Execution Error:" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_expression_undefined_signal(waveform_file):
    """Test execute_wal_expression with an undefined signal."""
    await server._load_waveform({"waveform_file": waveform_file})

    result = await server._execute_wal_expression(
        {
            "waveform_file": waveform_file,
            "expression": "(find (= non_existent_signal 1))",
        }
    )

    text = result[0].text
    assert "Execution Error:" in text


@pytest.mark.asyncio
@pytest.mark.parametrize("waveform_file", WAVEFORM_FILES)
async def test_execute_wal_not_loaded(waveform_file):
    """Test execute_wal_expression when waveform is not loaded."""
    result = await server._execute_wal_expression(
        {
            "waveform_file": waveform_file,
            "expression": "(length (find true))",
        }
    )

    text = result[0].text
    assert "not loaded" in text.lower()
    assert "load_waveform" in text


@pytest.mark.asyncio
async def test_execute_wal_expression_empty_expression():
    """Test execute_wal_expression with an empty expression."""
    result = await server._execute_wal_expression(
        {
            "waveform_file": VCD_FILE,
            "expression": "",
        }
    )

    assert "Error:" in result[0].text
    assert "empty" in result[0].text.lower()


@pytest.mark.asyncio
async def test_list_tools_return_format():
    """Test that list_tools returns proper List[Tool] format."""
    tools = await server.list_tools()

    assert isinstance(tools, list)
    assert len(tools) == 3

    for tool in tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert hasattr(tool, "inputSchema")
        assert isinstance(tool.name, str)
        assert isinstance(tool.description, str)
        assert isinstance(tool.inputSchema, dict)

    tool_names = [tool.name for tool in tools]
    expected_tools = ["load_waveform", "unload_waveform", "execute_wal_expression"]
    for expected_tool in expected_tools:
        assert expected_tool in tool_names


@pytest.mark.asyncio
async def test_call_tool_routing():
    """Test that call_tool routes to the correct function."""
    mock_handler = AsyncMock(return_value=[TextContent(type="text", text="mocked")])

    with patch.dict(server._TOOL_HANDLERS, {"load_waveform": mock_handler}):
        await server.call_tool("load_waveform", {})
        mock_handler.assert_called_once()

    result = await server.call_tool("unknown_tool", {})
    assert "Unknown tool: unknown_tool" in result[0].text


@pytest.mark.asyncio
async def test_call_tool_exception_handling():
    """Test that call_tool handles exceptions properly."""

    async def raise_error(_args):
        raise RuntimeError("test error")

    with patch.dict(server._TOOL_HANDLERS, {"load_waveform": raise_error}):
        result = await server.call_tool("load_waveform", {})
        assert isinstance(result, list)
        assert len(result) == 1
        assert "Error:" in result[0].text
