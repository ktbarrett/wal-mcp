# WAL MCP Server

MCP (Model Context Protocol) server for RTL waveform analysis using WAL (Waveform Analysis Language).

## Supported Waveform Formats

- VCD (Value Change Dump)
- FST (Fast Signal Trace)
- Any other formats supported by WAL

## Installation and Usage

```bash
pip install wal-mcp
```

Add to your MCP client configuration:

```json
{
  "mcpServers": {
    "wal-mcp": {
      "type": "stdio",
      "command": "wal-mcp-server",
      "args": []
    }
  }
}
```

For WAL expression syntax and advanced examples, see the [WAL documentation](https://wal-lang.org/documentation/usage).

This package also comes with script to install a skill and sufficient reference material to teach an AI agent how to write WAL.
This allows you to use natural language to analyze waveforms.

To install the skill into `.claude/skills/` your current directory run:

```sh
wal-mcp-install-skills
```

Or pass a filepath to the script to install elsewhere.

Alternatively, if you are using the Github CLI application you can install the skill using that.

```sh
gh install skill ktbarrett/wal-mcp
```

## Development

To set up a development environment, install the `dev` group and the current package.
This is easiest done with `uv`:

```bash
uv sync
```

## Testing

To run the test suite:

```bash
pytest
```

## Credits

Built on [WAL (Waveform Analysis Language)](https://github.com/ics-jku/wal),
a domain-specific language for hardware waveform analysis.
See the [WAL website](https://wal-lang.org/) for more information.

## License

BSD 3-Clause License. See [LICENSE](LICENSE) for details.
