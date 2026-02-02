"""Bootstrap default user config and skills."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict

from agent_skills_bot.core.skills import DEFAULT_SKILLS_ROOT
from agent_skills_bot.utils.mcp_client import DEFAULT_CONFIG_PATH, reload_mcp_config


_BOOTSTRAPPED = False


def ensure_default_user_config() -> None:
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return
    _BOOTSTRAPPED = True
    logger = logging.getLogger("app.bootstrap")
    _ensure_mcp_config(logger)
    _ensure_shell_skill(logger)
    reload_mcp_config()


def _ensure_mcp_config(logger: logging.Logger) -> None:
    config_path = Path(os.environ.get("AGENT_SKILLS_MCP_CONFIG", DEFAULT_CONFIG_PATH))
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Failed to create config directory %s: %s", config_path.parent, exc)
        return

    data: Dict[str, Any] = {}
    if config_path.exists():
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("MCP config is invalid JSON; skipping defaults: %s", config_path)
            return
        if not isinstance(loaded, dict):
            logger.warning("MCP config is not a JSON object; skipping defaults: %s", config_path)
            return
        data = loaded

    servers = data.get("mcpServers")
    if servers is None:
        servers = {}
    if not isinstance(servers, dict):
        logger.warning("MCP config mcpServers is not an object; skipping defaults: %s", config_path)
        return

    changed = False
    if "shell_mcp" not in servers:
        servers["shell_mcp"] = {"command": "npx", "args": ["-y", "mcp-shell"]}
        changed = True

    if data.get("mcpServers") is not servers:
        data["mcpServers"] = servers
        changed = True

    if changed or not config_path.exists():
        payload = json.dumps(data, indent=2, ensure_ascii=True)
        try:
            config_path.write_text(f"{payload}\n", encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to write MCP config %s: %s", config_path, exc)


def _ensure_shell_skill(logger: logging.Logger) -> None:
    skills_root = Path(os.environ.get("AGENT_SKILLS_ROOT", DEFAULT_SKILLS_ROOT))
    skill_dir = skills_root / "shell-mcp"
    skill_md = skill_dir / "SKILL.md"
    if skill_md.exists():
        return
    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Failed to create skill directory %s: %s", skill_dir, exc)
        return
    content = "\n".join(
        [
            "---",
            "name: shell-mcp",
            'description: "Execute shell commands via the MCP shell server."',
            "allowed-tools:",
            "  - mcp__shell_mcp__run_command",
            "---",
            "",
            "Use mcp__shell_mcp__run_command for shell commands.",
            "Respect ~/.agent-skills-bot/command-allowlist.json when running commands.",
            "Prefer simple, safe commands and avoid destructive operations.",
            "",
        ]
    )
    try:
        skill_md.write_text(content, encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to write skill file %s: %s", skill_md, exc)
