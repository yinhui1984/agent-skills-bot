# Repository Guidelines

## Project Structure & Module Organization
This repository is currently documentation-focused. Key paths:
- `doc/`: Design notes and specs (see `doc/design.md`).
- `.venv/`: Local Python environment (already created).
- `~/.agent-skills-bot/skills/`: Runtime skills root (outside repo).
 - `main_cli.py`: CLI entrypoint.

As implementation begins, place source code under a dedicated top-level directory (e.g., `src/` or `cmd/`) and tests under `tests/` to keep layout predictable.
Follow the UI/logging guidance in `doc/ui-logging-guide.md` to keep core logic UI-agnostic.

## Build, Test, and Development Commands
The project uses Python. No build or test commands are defined yet. When added, document them here with short explanations, for example:
- `python -m venv .venv`: Create the virtual environment.
- `source .venv/bin/activate`: Activate the environment (macOS/Linux).
- `python main_cli.py "..."`: Run the CLI with a query.

## Coding Style & Naming Conventions
- Keep files and docs in ASCII unless there is a clear reason to introduce Unicode.
- Prefer clear, descriptive names (e.g., `skill_loader`, `prompt_builder`).
- Use consistent casing: `snake_case` for functions and variables, `kebab-case` for CLI flags.
- If a formatter or linter is introduced, add it to this section with the exact command (e.g., `ruff format`, `black .`).

## Testing Guidelines
No testing framework is set yet. When tests are added:
- Keep unit tests close to their modules or under `tests/`.
- Use descriptive test names (e.g., `test_skill_loader_reads_skill_md`).
- Document how to run tests (single file and full suite).

## Commit & Pull Request Guidelines
There is no commit history yet, so no established commit message convention. When you start committing, keep messages short and action-oriented (e.g., `Add skill loader skeleton`).

For pull requests:
- Include a brief summary and rationale.
- Link relevant issues or notes in `doc/` when applicable.
- Note any new commands or configuration steps.

## Architecture Overview
The MVP is model-agnostic and centers on:
- Skill loading (`SKILL.md`) and keyword matching.
- Prompt assembly with tool definitions.
- An LLM client adapter (provider-specific details isolated).
- A tool executor (MVP: `bash_tool`).

Keep orchestration deterministic and reserve AI for task understanding and tool selection.
Default UI is CLI; DeepSeek V3 JSON mode is the default model configuration.
Skills follow the AgentSkills specification: https://agentskills.io/specification
