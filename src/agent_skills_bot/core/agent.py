"""Agent orchestration for the MVP."""

from __future__ import annotations

import logging

from agent_skills_bot.core.models import SkillResult
from agent_skills_bot.core.router import route_plan
from agent_skills_bot.core.skill_runner import build_command, execute_command


async def run(user_input: str) -> SkillResult:
    logging.getLogger("app.core").info("Routing skill for input")
    plan = route_plan(user_input)
    if not plan.steps:
        raise ValueError("Routing failed: empty plan")
    skill_query = plan.steps[0]
    command = build_command(
        skill_query.skill,
        skill_query.input,
        state_summary=None,
        state_json=None,
    )
    return await execute_command(skill_query.skill, command)
