# UI and Logging Guide (Hexagonal Architecture)

## Goal
Keep core logic independent of any UI by using a hexagonal (ports and adapters) structure. This enables CLI, TUI, and future GUI/Web frontends with minimal refactoring.

## Suggested Layout
```
src/
  core/           # business logic, pure and testable
  interfaces/     # CLI/TUI adapters
  utils/          # logging configuration
```

## Golden Rules (Core Layer)
1. No direct IO: avoid `print()` and `input()` in core code.
2. Return structured data (dataclasses/dicts), not user-facing strings.
3. Async first: prefer `async def` to keep UI responsive.
4. Use `logging` for progress and errors; UI decides how to render.

## Core Example (pattern)
- Define dataclasses in `src/core/models.py`.
- Implement async generators in `src/core/business.py` that `yield` results.
- Log via `logging.getLogger("app.core")` without configuring handlers.

## Adapter Responsibilities
- CLI: configure log formatting and render results with a simple table.
- TUI: route logs to a UI widget and run core logic in a background worker.

## Logging Notes
- Configure handlers in adapters only (CLI/TUI).
- Keep log messages short and structured; include identifiers.

## Rationale
This separation keeps core logic deterministic, testable with `unittest`, and reusable across multiple interfaces.
