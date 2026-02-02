# agent-skills-bot

Model-agnostic CLI agent that loads Claude-style skills (SKILL.md + optional scripts) and executes tasks via MCP tools or a guarded shell command entrypoint.

## Features
- Skill-based routing from SKILL.md (AgentSkills spec)
- CLI planning flow with optional tool loop
- Safe tool execution with explicit confirmation prompts
- MCP integration (stdio servers) with notifications
- Command allowlist for shell execution (run_command)
- Interactive CLI with input history
- Optional reference loading for each skill

## Requirements
- Python 3.11+
- DeepSeek API key in `APIKEY_DEEPSEEK`

## Quick Start
```
make venv
make install
export APIKEY_DEEPSEEK=your_key
make run
```

Run with a single query:
```
.venv/bin/python main_cli.py "find some skills which can convert pdf to markdown"
```

Interactive mode (prompts when no query is provided):
```
.venv/bin/python main_cli.py
```

Single-run mode (no loop):
```
.venv/bin/python main_cli.py --once "find some skills which can convert pdf to markdown"
```

Disable multi-step tool loop:
```
.venv/bin/python main_cli.py --no-loop "how many file types in /Users/z/Downloads"
```

Max tool iterations:
```
.venv/bin/python main_cli.py --max-loop-count 5 "how many file types in /Users/z/Downloads"
```

## CLI Commands
- `/list` list installed skills
- `/help` show command help
- `/mcp` list MCP servers and tools
- `/mcp-notifications` show pending MCP notifications
- `/quit` exit the CLI

## Config Directory
Default config directory:
```
~/.agent-skills-bot
```

Contents:
- `skills/` installed skills (each directory contains SKILL.md)
- `command-allowlist.json` allowlisted shell commands for `run_command`
- `mcp.json` MCP server configuration

### command-allowlist.json
Used to gate shell execution when `mcp__shell_mcp__run_command` is allowed by a skill.
The command is only allowed if the tool entrypoint is permitted by `allowed-tools` and the command matches this allowlist.

Example:
```
{
  "version": 1,
  "allow": ["which", "ls", "find", "yt-dlp"],
  "allow_globs": ["ls:*", "find:*", "yt-dlp:*"]
}
```

## MCP Setup
Create `~/.agent-skills-bot/mcp.json`:
```
{
  "mcpServers": {
    "shell_mcp": {
      "command": "npx",
      "args": ["-y", "mcp-shell"]
    },
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/Users/yourname/Downloads",
        "/Users/yourname/Desktop"
      ]
    }
  }
}
```
Adjust the paths for your machine.
On first run, if `mcp.json` is missing or does not include `shell_mcp`, the CLI writes a
default `shell_mcp` entry (`npx -y mcp-shell`). It also creates a default
`~/.agent-skills-bot/skills/shell-mcp/SKILL.md` if the skill is missing.

MCP tools can be invoked as `mcp__server__tool` with JSON arguments.

## Skills
Runtime skills live outside the repo at `~/.agent-skills-bot/skills/`.
A skill is a folder containing `SKILL.md` (and optional scripts or references).

Example layout:
```
~/.agent-skills-bot/skills/youtube-transcribe-skill/
  SKILL.md
  references/
```

## Safety Model
- If a skill declares `allowed-tools`, commands outside that list are blocked.
- `run_command` is only allowed when both:
  - `mcp__shell_mcp__run_command` is in `allowed-tools`
  - the command matches `command-allowlist.json`
- The CLI always asks for confirmation before executing a tool command.

## Structure
- `doc/` design notes and specs
- `src/agent_skills_bot/` package source
- `tests/` unit tests (unittest)
- `main_cli.py` CLI entrypoint

## Development
```
make venv
make install
make run
make test
```

## Notes
Routing uses two passes with `deepseek-chat` and falls back to `deepseek-reasoner` only on failure.
References for a skill can be listed and optionally loaded into the context.
