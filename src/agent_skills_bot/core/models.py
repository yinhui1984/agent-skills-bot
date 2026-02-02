"""Data models for agent-skills-bot."""

from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class SkillQuery:
    skill: str
    query: str


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    path: str
    metadata: Dict[str, str]


@dataclass(frozen=True)
class SkillResult:
    skill: str
    raw_output: str
    lines: List[str]
