# agent-skills-bot

Model-agnostic agent that loads Claude-style skills (SKILL.md + optional scripts) and executes tasks via a minimal tool interface.

## Quick Start
```
python -m venv .venv
source .venv/bin/activate
pip install -e .
export APIKEY_DEEPSEEK=your_key
python main_cli.py "find some skills which can convert pdf to markdown"
```

Interactive mode (prompts when no query is provided):
```
python main_cli.py
```
Single-run mode (no loop):
```
python main_cli.py --once "find some skills which can convert pdf to markdown"
```

Disable multi-step tool loop:
```
python main_cli.py --no-loop "how many file types in /Users/z/Downloads"
```

Max tool iterations:
```
python main_cli.py --max-loop-count 5 "how many file types in /Users/z/Downloads"
```

When a command is generated, the CLI will ask for confirmation before execution.
Routing uses two passes with `deepseek-chat`, and falls back to `deepseek-reasoner` only on failure.
If a skill declares `allowed-tools`, commands outside that list are blocked.

Built-in skill:
- No built-in shell tool is enabled; use MCP servers (e.g., filesystem) for controlled file operations.

### Commands
- `/list` list installed skills
- `/help` show command help
- `/mcp` list MCP servers and tools
- `/mcp-notifications` show pending MCP notifications
- `/quit` exit the CLI

### MCP
Create `~/.agent-skills-bot/mcp.json` with:
```
{
  "mcpServers": {
    "desktop-commander": {
      "command": "npx",
      "args": ["-y", "@wonderwhy-er/desktop-commander"]
    }
  }
}
```
MCP tools can be invoked as `mcp__server__tool` with JSON arguments.

## Structure
- `doc/`: design notes and specs
- `src/agent_skills_bot/`: package source
- `tests/`: unit tests (unittest)
- `main_cli.py`: CLI entrypoint

## Notes
Runtime skills live outside the repo at `~/.agent-skills-bot/skills/`.
