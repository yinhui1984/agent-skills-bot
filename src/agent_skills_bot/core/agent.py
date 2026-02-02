"""Agent orchestration for the MVP."""

from __future__ import annotations

import logging

from agent_skills_bot.core.models import SkillResult
from agent_skills_bot.core.router import route_skill
from agent_skills_bot.core.skill_runner import build_command, execute_command


async def run(user_input: str) -> SkillResult:
    logging.getLogger("app.core").info("Routing skill for input")
    skill_query = route_skill(user_input)
    command = build_command(
        skill_query.skill,
        skill_query.query,
        state_summary=None,
        state_json=None,
    )
    return await execute_command(skill_query.skill, command)
