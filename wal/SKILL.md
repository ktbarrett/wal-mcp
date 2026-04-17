---
name: wal
description: "Load and query RTL simulation waveforms (VCD/FST) using WAL via the wal MCP server. Capabilities: list signals, find transitions/edges, count events, correlate signals, timing analysis, debug state machines. TRIGGER: user asks to analyze a waveform/VCD/FST, debug a simulation/verification, investigate signal transitions/timing, debug FPGA/ASIC verification. SKIP: general HDL/RTL code questions without waveform files."
---

# WAL Waveform Analysis Skill

You are an expert in RTL waveform analysis using WAL (Waveform Analysis Language).

## Setup Check

Before doing anything, verify the `wal-mcp` MCP server is available:

1. Call `mcp__gateway__get_server_details` with `server_names: ["wal-mcp"]` to confirm the server exists.
2. If the server is not available, inform the user that the `wal-mcp` MCP server must be configured and stop.

## Workflow

1. **Identify the waveform file.** Ask the user for the path if not provided. Waveform files have `.vcd` or `.fst` extensions.
2. **Load the waveform** using the `load_waveform` tool.
3. **Discover signals** by executing the WAL expression `SIGNALS`.
4. **Analyze** using `execute_wal_expression` to answer the user's question.
5. **Unload** the waveform with `unload_waveform` when analysis is complete. Ask the user if they want to keep it loaded for further queries.

## WAL Language Reference

```wal-reference
${{file:references/wal-lang.md}}
```

## WAL Examples

```wal-examples
${{dir:references/examples}}
```

## Analysis Strategies

### Signal Discovery
```
SIGNALS                          — List all signal names
(length (find true))             — Total simulation length in time steps
```

### Finding Events
```
(find (= signal 1))             — All times where signal is high
(find (&& (= valid 1) (= ready 0)))  — Handshake stalls
(count (= error 1))             — Count error assertions
```

### Timing Analysis
```
(step 0) signal                  — Value at time 0
(step N) signal                  — Value at time N
signal@1                         — Value at next time step (relative)
signal@-1                        — Value at previous time step
```

### Transition Detection
```
(find (!= signal signal@-1))    — All transition times for a signal
(find (&& (= signal 0) (= signal@1 1)))  — Rising edges
(find (&& (= signal 1) (= signal@1 0)))  — Falling edges
```

### Multi-Signal Correlation
```
(find (&& (= clk 1) (= enable 1)))           — Clock-gated events
(whenever (= trigger 1) (print INDEX data))   — Print data at trigger points
```

### Debugging Patterns
```
(find (> counter max_expected))               — Out-of-range values
(length (find (&& (= valid 1) (= ready 0)))) — Backpressure duration
(find (= state error_state))                  — FSM error states
```

## Tips

- Signal names are hierarchical (e.g., `tb.dut.cpu.pc`). Use `SIGNALS` to discover exact names.
- WAL uses `&&` and `||` for logical AND/OR, not `and`/`or`.
- `(find condition)` returns a list of time indices; wrap in `(length ...)` to count.
- `(count condition)` is shorthand for `(length (find condition))`.
- Use `(whenever condition body)` to evaluate an expression at every matching time step.
- Use `(timeframe ...)` to perform local time navigation without losing your position.
- Use `#t` and `#f` (or `1` and `0`) for boolean literals.
