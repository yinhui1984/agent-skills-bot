"""Prompting and routing logic for skill selection."""

from __future__ import annotations

import json
from typing import Dict, List

from agent_skills_bot.utils.deepseek_client import chat_completion
from agent_skills_bot.core.models import SkillMeta, SkillQuery
from agent_skills_bot.core.skills import filter_skills, load_skills


SYSTEM_PROMPT = (
    "You are an agent that selects which skill to run. "
    "Return a JSON object only. The word json must appear in this prompt.\n\n"
    "Output JSON schema:\n"
    "{\n"
    "  \"action\": \"run_skill\",\n"
    "  \"skill\": \"<skill name from the list>\",\n"
    "  \"query\": \"...user query...\"\n"
    "}\n"
    "If you are unsure, pick the best matching skill from the list."
)


def _format_skills(skills: List[SkillMeta]) -> str:
    lines = []
    for skill in skills:
        desc = skill.description or "(no description)"
        lines.append(f"- {skill.name}: {desc}")
    return "\n".join(lines)


def build_messages(user_input: str, skills: List[SkillMeta]) -> List[Dict[str, str]]:
    skills_block = _format_skills(skills)
    prompt = f"{SYSTEM_PROMPT}\n\nAvailable skills:\n{skills_block}"
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": user_input},
    ]


def parse_skill_query(response: Dict[str, object]) -> SkillQuery:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Unexpected DeepSeek response format") from exc

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("DeepSeek did not return valid JSON output") from exc

    if payload.get("action") != "run_skill":
        raise ValueError("DeepSeek returned an unsupported action")

    skill = str(payload.get("skill", "")).strip()
    query = str(payload.get("query", "")).strip()
    if not skill or not query:
        raise ValueError("DeepSeek response missing skill or query")

    return SkillQuery(skill=skill, query=query)


def route_skill(user_input: str) -> SkillQuery:
    skills = load_skills()
    if not skills:
        raise ValueError("No skills found under ~/.agent-skills-bot/skills")
    candidates = filter_skills(skills, user_input)
    messages = build_messages(user_input, candidates)
    response = chat_completion(messages, response_format={"type": "json_object"})
    return parse_skill_query(response)
