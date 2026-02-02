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
    "  \"input\": \"...executable parameters only...\",\n"
    "  \"notes\": \"...optional constraints...\"\n"
    "}\n"
    "The input must be the task parameters only, not the user's full sentence. "
    "Remove command verbs like 'search', 'find', 'run', 'execute', tool names, or platforms, "
    "and keep only the content needed to perform the task.\n"
    "Examples:\n"
    "- User: \"search github voice to text\" -> input: \"voice to text\"\n"
    "- User: \"github search rust wasm\" -> input: \"rust wasm\"\n"
    "- User: \"convert report.pdf to markdown\" -> input: \"report.pdf to markdown\"\n"
    "If you are unsure, pick the best matching skill from the list."
)


def _format_skills(skills: List[SkillMeta]) -> str:
    lines = []
    for skill in skills:
        desc = skill.description or "(no description)"
        lines.append(f"- {skill.name}: {desc} (path: {skill.path})")
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
    query = str(payload.get("input", "")).strip()
    if not skill or not query:
        raise ValueError("DeepSeek response missing skill or input")
    return SkillQuery(skill=skill, query=query)


def _is_valid_skill_query(skill_query: SkillQuery, skills: List[SkillMeta]) -> bool:
    available = {skill.name for skill in skills}
    return skill_query.skill in available and bool(skill_query.query.strip())


def _confirm_messages(user_input: str, draft: SkillQuery, skills: List[SkillMeta]) -> List[Dict[str, str]]:
    skills_block = _format_skills(skills)
    system = (
        "You are validating a draft skill routing result. "
        "Return json only with the same schema as before. "
        "Keep the input as-is unless it is empty or not executable parameters. "
        "Do not add new fields.\n\n"
        "Available skills:\n"
        f"{skills_block}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_input},
        {
            "role": "assistant",
            "content": json.dumps(
                {
                    "action": "run_skill",
                    "skill": draft.skill,
                    "input": draft.query,
                    "notes": "",
                }
            ),
        },
        {"role": "user", "content": "Confirm or correct the draft JSON only."},
    ]


def route_skill(user_input: str) -> SkillQuery:
    skills = load_skills()
    if not skills:
        raise ValueError("No skills found under ~/.agent-skills-bot/skills")
    candidates = filter_skills(skills, user_input)
    messages = build_messages(user_input, candidates)

    response = chat_completion(
        messages,
        response_format={"type": "json_object"},
        model="deepseek-chat",
    )
    draft = parse_skill_query(response)
    if _is_valid_skill_query(draft, skills):
        confirm = chat_completion(
            _confirm_messages(user_input, draft, candidates),
            response_format={"type": "json_object"},
            model="deepseek-chat",
        )
        confirmed = parse_skill_query(confirm)
        if _is_valid_skill_query(confirmed, skills):
            return confirmed

    fallback = chat_completion(
        messages,
        response_format={"type": "json_object"},
        model="deepseek-reasoner",
    )
    result = parse_skill_query(fallback)
    if not _is_valid_skill_query(result, skills):
        raise ValueError("Routing failed: no valid skill match")
    return result
