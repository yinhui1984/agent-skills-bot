"""Skill discovery and metadata parsing."""

from __future__ import annotations

import os
import pathlib
import re
from typing import Dict, Iterable, List, Tuple, Union

from agent_skills_bot.core.models import SkillMeta


DEFAULT_SKILLS_ROOT = os.path.expanduser("~/.agent-skills-bot/skills")
NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _skills_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("AGENT_SKILLS_ROOT", DEFAULT_SKILLS_ROOT))


def _read_skill_md(path: pathlib.Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _parse_frontmatter(lines: List[str]) -> Dict[str, Union[str, List[str]]]:
    if not lines or lines[0].strip() != "---":
        return {}

    data: Dict[str, Union[str, List[str]]] = {}
    metadata: Dict[str, Union[str, List[str]]] = {}
    in_metadata = False
    list_key: Tuple[str, bool] | None = None

    for line in lines[1:]:
        stripped = line.rstrip("\n")
        if stripped.strip() == "---":
            break

        if not stripped.strip():
            continue

        if stripped.startswith("metadata:"):
            in_metadata = True
            list_key = None
            continue

        if in_metadata:
            if not stripped.startswith("  "):
                in_metadata = False
                list_key = None
            else:
                inner = stripped.strip()
                if inner.startswith("- ") and list_key and list_key[1]:
                    metadata[list_key[0]].append(inner[2:].strip())
                    continue
                key, value = _split_kv(inner)
                if key:
                    if value == "":
                        metadata[key] = []
                        list_key = (key, True)
                    else:
                        metadata[key] = value
                        list_key = (key, False)
                continue

        if stripped.startswith("- ") and list_key and list_key[1]:
            data[list_key[0]].append(stripped[2:].strip())
            continue
        key, value = _split_kv(stripped)
        if key:
            if value == "":
                data[key] = []
                list_key = (key, True)
            else:
                data[key] = value
                list_key = (key, False)

    if metadata:
        data.update({f"metadata.{k}": v for k, v in metadata.items()})
    return data


def _split_kv(line: str) -> tuple[str, str]:
    if ":" not in line:
        return "", ""
    key, value = line.split(":", 1)
    return key.strip(), value.strip().strip("\"'")


def _iter_skill_dirs(root: pathlib.Path) -> Iterable[pathlib.Path]:
    if not root.exists():
        return []
    skill_dirs = []
    for dirpath, _, filenames in os.walk(root, followlinks=True):
        if "SKILL.md" in filenames:
            skill_dirs.append(pathlib.Path(dirpath))
    return skill_dirs


def load_skills() -> List[SkillMeta]:
    skills: List[SkillMeta] = []
    root = _skills_root()

    for skill_dir in _iter_skill_dirs(root):
        skill_md = _read_skill_md(skill_dir / "SKILL.md")
        lines = skill_md.splitlines()
        frontmatter = _parse_frontmatter(lines)

        declared_name = str(frontmatter.get("name", "")).strip()
        description = str(frontmatter.get("description", "")).strip()
        if not declared_name or not description:
            continue
        dir_name = skill_dir.name
        if declared_name != dir_name:
            continue
        if len(declared_name) > 64 or not NAME_PATTERN.match(declared_name):
            continue
        if len(description) > 1024:
            continue
        name = declared_name
        skills.append(
            SkillMeta(
                name=name,
                description=description,
                path=str(skill_dir),
                metadata=frontmatter,
            )
        )

    return skills


def filter_skills(skills: List[SkillMeta], query: str, limit: int = 20) -> List[SkillMeta]:
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return skills[:limit]

    scored = []
    for skill in skills:
        hay = f"{skill.name} {skill.description}".lower()
        score = sum(1 for t in terms if t in hay)
        if score:
            scored.append((score, skill))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [skill for _, skill in scored[:limit]]
