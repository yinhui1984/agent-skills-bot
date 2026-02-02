"""Skill discovery and execution."""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import subprocess
from typing import List

from agent_skills_bot.core.models import SkillMeta, SkillResult
from agent_skills_bot.core.skills import load_skills


DEFAULT_SKILLS_ROOT = os.path.expanduser("~/.agent-skills-bot/skills")
logger = logging.getLogger("app.core")


def _skill_dir(skill: str) -> pathlib.Path:
    root = pathlib.Path(os.environ.get("AGENT_SKILLS_ROOT", DEFAULT_SKILLS_ROOT))
    return root / skill


def _select_skill_command(skill: SkillMeta, query: str) -> List[str]:
    skill_path = pathlib.Path(skill.path)
    entrypoint = skill.metadata.get("metadata.entrypoint") or skill.metadata.get("entrypoint", "")
    if entrypoint:
        entry_path = skill_path / entrypoint
        return _command_for_entry(entry_path, query)

    scripts_dir = skill_path / "scripts"
    candidates = [
        scripts_dir / "run.py",
        scripts_dir / "run.js",
        scripts_dir / "enrich_find.py",
        scripts_dir / "enrich_find.js",
    ]
    for candidate in candidates:
        if candidate.exists():
            return _command_for_entry(candidate, query)

    scripts = list(scripts_dir.glob("*")) if scripts_dir.exists() else []
    if len(scripts) == 1:
        return _command_for_entry(scripts[0], query)

    raise FileNotFoundError(
        "No supported script found for skill. Provide scripts/run.py, scripts/run.js, "
        "or set metadata.entrypoint in SKILL.md frontmatter."
    )


def _command_for_entry(entry_path: pathlib.Path, query: str) -> List[str]:
    suffix = entry_path.suffix.lower()
    if suffix == ".py":
        return ["python", str(entry_path), query]
    if suffix == ".js":
        return ["node", str(entry_path), query]
    if suffix in {".sh", ".bash"}:
        return ["bash", str(entry_path), query]
    return ["python", str(entry_path), query]


def _run_command(command: List[str]) -> str:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise RuntimeError(f"Skill command failed with code {result.returncode}\n{output}")
    return output.strip()


def _find_skill_meta(skill_name: str) -> SkillMeta:
    for skill in load_skills():
        if skill.name == skill_name or pathlib.Path(skill.path).name == skill_name:
            return skill
    raise FileNotFoundError(f"Skill not found: {skill_name}")


async def run_skill(skill_name: str, query: str) -> SkillResult:
    skill = _find_skill_meta(skill_name)
    logger.info("Running skill: %s", skill.name)
    command = _select_skill_command(skill, query)
    output = await asyncio.to_thread(_run_command, command)
    lines = [line for line in output.splitlines() if line.strip()]
    return SkillResult(skill=skill.name, raw_output=output, lines=lines)
