"""Prompting and routing logic for skill selection."""

from __future__ import annotations

import json
import os
import platform
from datetime import datetime, timezone
from typing import Dict, List

from agent_skills_bot.utils.deepseek_client import chat_completion
from agent_skills_bot.core.models import SkillMeta, SkillQuery, SkillPlan, SkillStep
from agent_skills_bot.core.skills import filter_skills, load_skills


SYSTEM_PROMPT = (
    "You are an agent that selects which tool(s) to run. "
    "Return JSON only. The word json must appear in this prompt.\n\n"
    "You must choose from the Available skills list. Treat all options as peers.\n\n"
    "Decision criteria:\n"
    "- Choose the simplest, most reliable, and most direct way to satisfy the user request.\n"
    "- If multiple skills are required, return a multi-step plan.\n"
    "- Use the environment context (OS, shell, time) to judge whether a skill is appropriate.\n"
    "- Do not prefer any skill by default.\n\n"
    "Output JSON schema (single step):\n"
    "{\n"
    "  \"action\": \"run_skill\",\n"
    "  \"skill\": \"<skill name from the list>\",\n"
    "  \"input\": \"...executable parameters only...\",\n"
    "  \"notes\": \"...optional constraints or multi-step hints...\"\n"
    "}\n\n"
    "Output JSON schema (multi-step plan):\n"
    "{\n"
    "  \"action\": \"run_plan\",\n"
    "  \"steps\": [\n"
    "    {\"skill\":\"<skill>\", \"input\":\"...\", \"notes\":\"...\", \"requires\":[\"artifacts.text\"]}\n"
    "  ]\n"
    "}\n\n"
    "If a step depends on earlier outputs, set requires using artifacts.* keys "
    "(e.g., artifacts.text, artifacts.file_path, artifacts.url_list).\n"
    "When the user asks to save/write/upload, include a separate step that performs the file operation "
    "using a skill capable of filesystem or shell operations.\n"
    "The input must be the task parameters only, not the user's full sentence.\n"
    "Examples:\n"
    "- User: \"search github voice to text\" -> input: \"voice to text\"\n"
    "- User: \"github search rust wasm\" -> input: \"rust wasm\"\n"
    "- User: \"convert report.pdf to markdown\" -> input: \"report.pdf to markdown\"\n"
    "If you are unsure, pick the best matching single skill."
)


def _format_skills(skills: List[SkillMeta]) -> str:
    lines = []
    for skill in skills:
        desc = skill.description or "(no description)"
        allowed = skill.metadata.get("allowed-tools") or skill.metadata.get("metadata.allowed-tools")
        if isinstance(allowed, list):
            allowed_text = ", ".join(str(item) for item in allowed if str(item).strip())
        elif isinstance(allowed, str):
            allowed_text = allowed.strip()
        else:
            allowed_text = ""
        suffix = f" (path: {skill.path})"
        if allowed_text:
            suffix = f" (allowed-tools: {allowed_text}; path: {skill.path})"
        lines.append(f"- {skill.name}: {desc}{suffix}")
    return "\n".join(lines)


def _environment_context() -> str:
    shell = os.environ.get("SHELL", "(unknown)")
    now = datetime.now(timezone.utc).isoformat()
    os_info = platform.platform()
    return f"Environment: os={os_info}; shell={shell}; time_utc={now}"


def build_messages(user_input: str, skills: List[SkillMeta]) -> List[Dict[str, str]]:
    skills_block = _format_skills(skills)
    prompt = f"{SYSTEM_PROMPT}\n\nAvailable skills:\n{skills_block}"
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": _environment_context()},
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


def parse_skill_plan(response: Dict[str, object]) -> SkillPlan:
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Unexpected DeepSeek response format") from exc

    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("DeepSeek did not return valid JSON output") from exc

    action = payload.get("action")
    if action == "run_skill":
        skill = str(payload.get("skill", "")).strip()
        query = str(payload.get("input", "")).strip()
        if not skill or not query:
            raise ValueError("DeepSeek response missing skill or input")
        return SkillPlan(steps=[SkillStep(skill=skill, input=query)])
    if action != "run_plan":
        raise ValueError("DeepSeek returned an unsupported action")

    raw_steps = payload.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("DeepSeek returned an empty plan")

    steps: list[SkillStep] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            continue
        skill = str(item.get("skill", "")).strip()
        step_input = str(item.get("input", "")).strip()
        if not skill or not step_input:
            continue
        notes = str(item.get("notes", "")).strip() or None
        requires_raw = item.get("requires")
        requires = None
        if isinstance(requires_raw, list):
            requires = [str(req).strip() for req in requires_raw if str(req).strip()]
        steps.append(SkillStep(skill=skill, input=step_input, notes=notes, requires=requires))

    if not steps:
        raise ValueError("DeepSeek returned an invalid plan")
    return SkillPlan(steps=steps)


def _is_valid_skill_query(skill_query: SkillQuery, skills: List[SkillMeta]) -> bool:
    available = {skill.name for skill in skills}
    return skill_query.skill in available and bool(skill_query.query.strip())


def _is_valid_plan(plan: SkillPlan, skills: List[SkillMeta]) -> bool:
    available = {skill.name for skill in skills}
    if not plan.steps:
        return False
    for step in plan.steps:
        if step.skill not in available:
            return False
        if not step.input.strip():
            return False
    return True


def _capabilities_for_skill(skill: SkillMeta) -> List[str]:
    allowed = skill.metadata.get("allowed-tools") or skill.metadata.get("metadata.allowed-tools")
    if isinstance(allowed, list):
        tools = [str(item) for item in allowed if str(item).strip()]
    elif isinstance(allowed, str):
        tools = [item.strip() for item in allowed.split(",") if item.strip()]
    else:
        tools = []

    capabilities: list[str] = []
    if any(tool.endswith("__write_file") or tool.endswith("__edit_file") for tool in tools):
        capabilities.append("file_write")
    if any(
        tool.endswith("__read_file")
        or tool.endswith("__read_text_file")
        or tool.endswith("__list_directory")
        or tool.endswith("__list_directory_with_sizes")
        for tool in tools
    ):
        capabilities.append("file_read")
    if any(tool.endswith("__run_command") for tool in tools):
        capabilities.append("shell")
    if tools:
        capabilities.append("mcp")
    return capabilities


def _skills_capabilities_summary(skills: List[SkillMeta]) -> str:
    lines = []
    for skill in skills:
        capabilities = _capabilities_for_skill(skill)
        caps_text = ", ".join(capabilities) if capabilities else "(none)"
        lines.append(f"- {skill.name}: {caps_text}")
    return "\n".join(lines)


def _plan_to_payload(plan: SkillPlan) -> Dict[str, object]:
    if len(plan.steps) == 1:
        step = plan.steps[0]
        return {
            "action": "run_skill",
            "skill": step.skill,
            "input": step.input,
            "notes": step.notes or "",
        }
    return {
        "action": "run_plan",
        "steps": [
            {
                "skill": step.skill,
                "input": step.input,
                "notes": step.notes or "",
                "requires": step.requires or [],
            }
            for step in plan.steps
        ],
    }


def _refine_plan(user_input: str, plan: SkillPlan, skills: List[SkillMeta]) -> SkillPlan:
    skills_block = _format_skills(skills)
    capabilities_block = _skills_capabilities_summary(skills)
    system = (
        "You are refining a draft execution plan. Return json only with the same schema as before. "
        "Ensure each step uses a skill capable of the action based on the capabilities list and tool hints. "
        "If the user asks to save/write/upload to disk, the responsible step must use a skill with file_write "
        "or shell capability. Do not assign file operations to skills without those capabilities. "
        "If the plan is already correct, return it unchanged."
    )
    payload = _plan_to_payload(plan)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"User request: {user_input}"},
        {"role": "user", "content": f"Available skills:\n{skills_block}"},
        {"role": "user", "content": f"Skill capabilities:\n{capabilities_block}"},
        {"role": "user", "content": f"Draft plan JSON:\n{json.dumps(payload)}"},
        {"role": "user", "content": "Return corrected plan JSON only."},
    ]
    response = chat_completion(
        messages,
        response_format={"type": "json_object"},
        model="deepseek-chat",
    )
    refined = parse_skill_plan(response)
    if _is_valid_plan(refined, skills):
        return refined
    return plan


def _confirm_messages(user_input: str, draft: SkillPlan, skills: List[SkillMeta]) -> List[Dict[str, str]]:
    skills_block = _format_skills(skills)
    capabilities_block = _skills_capabilities_summary(skills)
    system = (
        "You are validating a draft skill routing result. "
        "Return json only with the same schema as before. "
        "Ensure the plan satisfies the user request and each step uses a skill "
        "capable of the intended action based on the capabilities list. "
        "If the plan is missing required actions, correct it. "
        "Keep the input as-is unless it is empty or not executable parameters. "
        "Do not add new fields.\n\n"
        "Available skills:\n"
        f"{skills_block}\n\n"
        "Skill capabilities:\n"
        f"{capabilities_block}"
    )
    payload = _plan_to_payload(draft)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_input},
        {
            "role": "assistant",
            "content": json.dumps(payload),
        },
        {"role": "user", "content": "Confirm or correct the draft JSON only."},
    ]


def route_plan(user_input: str) -> SkillPlan:
    skills = load_skills(include_builtin=True)
    if not skills:
        raise ValueError("No skills found under ~/.agent-skills-bot/skills")
    candidates = filter_skills(skills, user_input)
    messages = build_messages(user_input, candidates)

    response = chat_completion(
        messages,
        response_format={"type": "json_object"},
        model="deepseek-chat",
    )
    draft = parse_skill_plan(response)
    if _is_valid_plan(draft, skills):
        confirm = chat_completion(
            _confirm_messages(user_input, draft, candidates),
            response_format={"type": "json_object"},
            model="deepseek-chat",
        )
        confirmed = parse_skill_plan(confirm)
        if _is_valid_plan(confirmed, skills):
            return _refine_plan(user_input, confirmed, skills)

    fallback = chat_completion(
        messages,
        response_format={"type": "json_object"},
        model="deepseek-reasoner",
    )
    result = parse_skill_plan(fallback)
    if not _is_valid_plan(result, skills):
        raise ValueError("Routing failed: no valid skill match")
    return _refine_plan(user_input, result, skills)


def _skills_with_allowed_tools(skills: List[SkillMeta]) -> Dict[str, List[str]]:
    mapping: Dict[str, List[str]] = {}
    for skill in skills:
        allowed = skill.metadata.get("allowed-tools") or skill.metadata.get("metadata.allowed-tools")
        if isinstance(allowed, list):
            tools = [str(item) for item in allowed if str(item).strip()]
        elif isinstance(allowed, str):
            tools = [item.strip() for item in allowed.split(",") if item.strip()]
        else:
            tools = []
        if tools:
            mapping[skill.name] = tools
    return mapping


def route_skill(user_input: str) -> SkillQuery:
    plan = route_plan(user_input)
    if not plan.steps:
        raise ValueError("Routing failed: empty plan")
    step = plan.steps[0]
    return SkillQuery(skill=step.skill, query=step.input)
