# agent-skills-bot

Model-agnostic agent that loads Claude-style skills (SKILL.md + optional scripts) and executes tasks via a minimal tool interface.

## Quick Start
```
python -m venv .venv
source .venv/bin/activate
pip install -e .
export APIKEY_DEEPSEEK=your_key
python main_tui.py
```

## Structure
- `doc/`: design notes and specs
- `src/agent_skills_bot/`: package source
- `tests/`: unit tests (unittest)
 - `main_tui.py`: default Textual UI entrypoint

## Notes
Runtime skills live outside the repo at `~/.agent-skills-bot/skills/`.
