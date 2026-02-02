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

When a command is generated, the CLI will ask for confirmation before execution.
Routing uses two passes with `deepseek-chat`, and falls back to `deepseek-reasoner` only on failure.
If a skill declares `allowed-tools`, commands outside that list are blocked.

## Structure
- `doc/`: design notes and specs
- `src/agent_skills_bot/`: package source
- `tests/`: unit tests (unittest)
- `main_cli.py`: CLI entrypoint

## Notes
Runtime skills live outside the repo at `~/.agent-skills-bot/skills/`.
