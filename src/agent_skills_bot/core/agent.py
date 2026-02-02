"""Agent orchestration for the MVP."""

from __future__ import annotations

import logging

from agent_skills_bot.core.models import SkillResult
from agent_skills_bot.core.router import route_skill
from agent_skills_bot.core.skill_runner import run_skill


async def run(user_input: str) -> SkillResult:
    logging.getLogger("app.core").info("Routing skill for input")
    skill_query = route_skill(user_input)
    return await run_skill(skill_query.skill, skill_query.query)
