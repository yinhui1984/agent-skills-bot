"""Skill discovery and execution."""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import json
import shlex
import subprocess
from dataclasses import dataclass
from typing import List

from agent_skills_bot.core.models import SkillMeta, SkillResult
from agent_skills_bot.core.skills import load_skills
from agent_skills_bot.utils.deepseek_client import chat_completion


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


def _read_skill_body(skill_path: pathlib.Path) -> str:
    skill_md = skill_path / "SKILL.md"
    if not skill_md.exists():
        return ""
    lines = skill_md.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                return "\n".join(lines[idx + 1 :]).strip()
    return "\n".join(lines).strip()


def _list_reference_files(skill_path: pathlib.Path) -> List[str]:
    refs_dir = skill_path / "references"
    if not refs_dir.exists():
        return []
    return [str(path) for path in refs_dir.rglob("*") if path.is_file()]


def _build_llm_command(
    skill: SkillMeta,
    query: str,
    reference_texts: List[str] | None = None,
) -> List[str]:
    skill_body = _read_skill_body(pathlib.Path(skill.path))
    references = _list_reference_files(pathlib.Path(skill.path))
    system_prompt = (
        "You are an execution planner. Return json only. "
        "Output schema: {\"command\": \"...\", \"description\": \"...\"}. "
        "Use the provided skill instructions to craft a command for the user query."
    )

    references_block = "\n".join(f"- {path}" for path in references) or "(none)"
    references_content = "\n\n".join(reference_texts or [])

    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": f"Skill instructions:\n{skill_body}\n\nReference files:\n{references_block}",
        },
        {
            "role": "user",
            "content": f"Reference contents:\n{references_content}" if references_content else "Reference contents: (not loaded)",
        },
        {"role": "user", "content": f"User request: {query}"},
    ]
    response = chat_completion(messages, response_format={"type": "json_object"})
    try:
        content = response["choices"][0]["message"]["content"]
        payload = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("LLM did not return valid JSON command") from exc

    command = str(payload.get("command", "")).strip()
    if not command:
        raise RuntimeError("LLM command was empty")

    return shlex.split(command)


def allowed_tools_for(skill: SkillMeta) -> List[str]:
    tools = skill.metadata.get("allowed-tools") or skill.metadata.get("metadata.allowed-tools")
    if isinstance(tools, list):
        return [str(tool) for tool in tools if str(tool).strip()]
    if isinstance(tools, str):
        return [tool.strip() for tool in tools.split(",") if tool.strip()]
    return []


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


def get_skill_meta(skill_name: str) -> SkillMeta:
    return _find_skill_meta(skill_name)


def build_command(
    skill_name: str,
    query: str,
    reference_texts: List[str] | None = None,
) -> List[str]:
    skill = _find_skill_meta(skill_name)
    try:
        return _select_skill_command(skill, query)
    except FileNotFoundError:
        return _build_llm_command(skill, query, reference_texts)


def list_reference_files(skill_name: str) -> List[str]:
    skill = _find_skill_meta(skill_name)
    return _list_reference_files(pathlib.Path(skill.path))


def read_reference_files(paths: List[str]) -> List[str]:
    contents = []
    for path in paths:
        try:
            contents.append(pathlib.Path(path).read_text(encoding="utf-8"))
        except FileNotFoundError:
            continue
    return contents


async def execute_command(skill_name: str, command: List[str]) -> SkillResult:
    logger.info("Running skill: %s", skill_name)
    output = await asyncio.to_thread(_run_command, command)
    lines = [line for line in output.splitlines() if line.strip()]
    return SkillResult(skill=skill_name, raw_output=output, lines=lines)
