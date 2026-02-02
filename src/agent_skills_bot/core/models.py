"""Data models for agent-skills-bot."""

from dataclasses import dataclass, field
from typing import Dict, List, Union, Any


@dataclass(frozen=True)
class SkillQuery:
    skill: str
    query: str


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    path: str
    metadata: Dict[str, Union[str, List[str]]]


@dataclass(frozen=True)
class SkillResult:
    skill: str
    raw_output: str
    lines: List[str]


@dataclass(frozen=True)
class SkillStep:
    skill: str
    input: str
    notes: str | None = None
    requires: List[str] | None = None


@dataclass(frozen=True)
class SkillPlan:
    steps: List[SkillStep]


@dataclass
class StepResult:
    status: str
    summary: str
    raw_output: str
    artifacts: Dict[str, Any] = field(default_factory=dict)
