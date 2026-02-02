"""CLI execution loop and tool orchestration."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex

from agent_skills_bot.core.models import SkillPlan, SkillStep, StepResult
from agent_skills_bot.core.router import route_plan
from agent_skills_bot.core.skill_runner import (
    allowed_tools_for,
    build_command,
    execute_command,
    get_skill_meta,
    list_reference_files,
    read_reference_files,
)
from agent_skills_bot.interfaces.cli_mcp import (
    _coerce_mcp_args,
    _get_mcp_schema,
    _infer_mcp_args,
    _normalize_mcp_args,
    _repair_mcp_args,
)
from agent_skills_bot.interfaces.cli_state import (
    _check_requires,
    _environment_context,
    _missing_required_placeholders,
    _render_placeholders_in_args,
    _render_placeholders_in_command,
    _render_state_json,
    _render_state_summary,
    _update_artifacts_from_output,
    _update_state_from_command_and_output,
)
from agent_skills_bot.interfaces.cli_theme import (
    ERROR_RULE_STYLE,
    INFO_RULE_STYLE,
    RESULT_RULE_STYLE,
    WARNING_RULE_STYLE,
    console,
    _render_rule,
)
from agent_skills_bot.interfaces.cli_ui import _render_output, _render_plan
from agent_skills_bot.utils.command_allowlist import load_command_allowlist, is_command_allowed
from agent_skills_bot.utils.deepseek_client import chat_completion
from agent_skills_bot.utils.logger import setup_cli_logger
from agent_skills_bot.utils.mcp_client import call_mcp_tool, list_mcp_tools


SHELL_SEPARATORS = {"|", "&&", ";", "||"}


def _repair_unbalanced_quotes(command: str) -> tuple[str, str | None, bool]:
    single_odd = command.count("'") % 2 == 1
    double_odd = command.count('"') % 2 == 1
    if not single_odd and not double_odd:
        return command, None, False
    if single_odd and not double_odd:
        return command.replace("'", ""), "Removed unmatched single quotes in shell command.", True
    if double_odd and not single_odd:
        return command.replace('"', ""), "Removed unmatched double quotes in shell command.", True
    return command, "Shell command has unbalanced single and double quotes.", False



def run_cli(
    user_input: str,
    tool_loop: bool = True,
    max_loop_count: int = 10,
    session_state: dict[str, object] | None = None,
) -> None:
    setup_cli_logger()
    logger = logging.getLogger("app.core")
    if session_state is None:
        session_state = {
            "cwd": os.getcwd(),
            "created": set(),
            "modified": set(),
            "last_command": "",
            "last_paths": [],
            "last_abs_path": "",
            "artifacts": {},
        }

    console.print("Running...", style="yellow")

    try:
        plan = route_plan(user_input)
        _render_plan(plan)
        reference_texts_by_skill: dict[str, list[str]] = {}
        seen_skills: set[str] = set()
        for step in plan.steps:
            if step.skill in seen_skills:
                continue
            seen_skills.add(step.skill)
            references = list_reference_files(step.skill)
            if not references:
                continue
            _render_rule(f"References ({step.skill})", style=INFO_RULE_STYLE)
            console.print("\n".join(references))
            load_refs = console.input("Load references into context? (Y/n): ").strip().lower()
            if not load_refs or load_refs in {"y", "yes"}:
                reference_texts_by_skill[step.skill] = read_reference_files(references)
    except Exception as exc:
        logger.error(str(exc))
        _render_rule("Error", style=ERROR_RULE_STYLE)
        console.print(str(exc))
        return

    _run_plan(
        plan,
        user_input,
        reference_texts_by_skill,
        tool_loop=tool_loop,
        max_loop_count=max_loop_count,
        session_state=session_state,
    )


def _run_plan(
    plan: SkillPlan,
    user_input: str,
    reference_texts_by_skill: dict[str, list[str]],
    tool_loop: bool,
    max_loop_count: int,
    session_state: dict[str, object],
) -> None:
    effective_loop = tool_loop if len(plan.steps) == 1 else False
    if len(plan.steps) > 1 and tool_loop:
        console.print(
            "Multi-step plan detected; disabling per-step tool loop to honor the plan.",
            style="dim",
        )
    for idx, step in enumerate(plan.steps, 1):
        missing = _check_requires(step.requires, session_state)
        if missing:
            _render_rule("Blocked", style=ERROR_RULE_STYLE)
            console.print(f"Step {idx} blocked; missing requirements: {', '.join(missing)}")
            return
        missing_placeholders = _missing_required_placeholders(step)
        if missing_placeholders:
            _render_rule("Blocked", style=ERROR_RULE_STYLE)
            console.print(
                f"Step {idx} blocked; missing placeholders: {', '.join(missing_placeholders)}"
            )
            return
        reference_texts = reference_texts_by_skill.get(step.skill, [])
        result = _execute_step(
            step,
            user_input,
            reference_texts,
            tool_loop=effective_loop,
            max_loop_count=max_loop_count,
            session_state=session_state,
        )
        if result.status != "ok":
            _render_rule("Error", style=ERROR_RULE_STYLE)
            console.print(result.summary or "Step failed.")
            return
    _render_rule("Result", style=RESULT_RULE_STYLE)
    console.print("Plan complete.")


def _execute_step(
    step: SkillStep,
    user_input: str,
    reference_texts: list[str],
    tool_loop: bool,
    max_loop_count: int,
    session_state: dict[str, object],
) -> StepResult:
    logger = logging.getLogger("app.core")
    state = session_state
    messages = [
        {
            "role": "system",
            "content": (
                "You are executing a tool loop. Use the environment context and State summary provided. "
                "Prefer explicit absolute paths from State summary over heuristics like ls -t. "
                "When a State summary includes last_abs_path, use it directly."
            ),
        },
        {"role": "user", "content": _environment_context()},
        {"role": "user", "content": _render_state_summary(state)},
        {"role": "user", "content": f"User: {user_input}"},
        {"role": "user", "content": f"Step input: {step.input}"},
    ]
    loop_step = 0
    current_query = step.input
    last_pid: int | None = None
    last_output = ""
    allowlist = load_command_allowlist()
    while True:
        loop_step += 1
        if loop_step > max_loop_count:
            _render_rule("Warning", style=WARNING_RULE_STYLE)
            console.print("Max loop count reached.")
            return StepResult(status="max_loop", summary="Max loop count reached.", raw_output=last_output)
        state_summary = _render_state_summary(state)
        state_json = _render_state_json(state)
        command_query = current_query
        command = build_command(
            step.skill,
            command_query,
            reference_texts,
            state_summary=state_summary,
            state_json=state_json,
        )
        command_text = " ".join(command)
        if command and not command[0].startswith("mcp__"):
            try:
                command = _render_placeholders_in_command(command, session_state)
            except ValueError as exc:
                return StepResult(status="blocked", summary=str(exc), raw_output=last_output)
            command_text = " ".join(command)
        allowed_tools = allowed_tools_for(get_skill_meta(step.skill))
        if command and not command[0].startswith("mcp__"):
            if "mcp__shell_mcp__run_command" not in allowed_tools:
                _render_rule("Blocked", style=ERROR_RULE_STYLE)
                console.print("Direct shell commands are disabled; allow mcp__shell_mcp__run_command.")
                return StepResult(
                    status="blocked",
                    summary="Direct shell commands are disabled; allow mcp__shell_mcp__run_command.",
                    raw_output=last_output,
                )
            if not is_command_allowed(command, allowlist):
                _render_rule("Blocked", style=ERROR_RULE_STYLE)
                console.print(f"Shell command not in allowlist: {command[0]}")
                return StepResult(
                    status="blocked",
                    summary=f"Shell command not in allowlist: {command[0]}",
                    raw_output=last_output,
                )
            payload = json.dumps({"command": command_text}, ensure_ascii=False)
            command = ["mcp__shell_mcp__run_command", payload]
            command_text = " ".join(command)
        if allowed_tools:
            _render_rule("allowed-tools", style=INFO_RULE_STYLE)
            console.print(", ".join(allowed_tools))
            if command and command[0] not in allowed_tools:
                _render_rule("Blocked", style=ERROR_RULE_STYLE)
                console.print(f"Command tool '{command[0]}' is not in allowed-tools.")
                return StepResult(
                    status="blocked",
                    summary=f"Command tool '{command[0]}' is not in allowed-tools.",
                    raw_output=last_output,
                )
        _render_rule("Command", style=INFO_RULE_STYLE)
        console.print(command_text)
        confirm = console.input("[bold yellow]Execute command?[/bold yellow] (Y/n): ").strip().lower()
        if confirm and confirm not in {"y", "yes"}:
            console.print()
            console.print("Cancelled.", style="dim")
            return StepResult(status="cancelled", summary="Cancelled by user.", raw_output=last_output)
        console.print()

        try:
            if command and command[0].startswith("mcp__"):
                tool_spec = command[0].split("__", 2)
                if len(tool_spec) != 3:
                    raise RuntimeError("Invalid MCP tool format. Use mcp__server__tool.")
                server = tool_spec[1]
                tool = tool_spec[2]
                args = {}
                if len(command) > 1:
                    raw = " ".join(command[1:])
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        coerced = _coerce_mcp_args(raw, tool)
                        if coerced is not None:
                            args = coerced
                        else:
                            schema = _get_mcp_schema(server, tool)
                            args = _repair_mcp_args(user_input, server, tool, raw, schema, messages)
                else:
                    tools = list_mcp_tools().get(server, [])
                    schema = None
                    for item in tools:
                        if item.get("name") == tool:
                            schema = item.get("inputSchema")
                            break
                    args = _infer_mcp_args(user_input, server, tool, schema, messages)
                args = _normalize_mcp_args(args)
                if tool == "read_process_output":
                    pid = args.get("pid")
                    if not pid and last_pid:
                        args["pid"] = last_pid
                try:
                    args = _render_placeholders_in_args(args, session_state)
                except ValueError as exc:
                    return StepResult(status="blocked", summary=str(exc), raw_output=last_output)
                if tool == "run_command":
                    cmd_value = args.get("command")
                    if not isinstance(cmd_value, str) or not cmd_value.strip():
                        _render_rule("Blocked", style=ERROR_RULE_STYLE)
                        console.print("Shell command is missing or invalid.")
                        return StepResult(
                            status="blocked",
                            summary="Shell command is missing or invalid.",
                            raw_output=last_output,
                        )
                    repaired, note, repaired_ok = _repair_unbalanced_quotes(cmd_value)
                    if note:
                        if repaired_ok:
                            _render_rule("Warning", style=WARNING_RULE_STYLE)
                            console.print(note)
                        else:
                            _render_rule("Blocked", style=ERROR_RULE_STYLE)
                            console.print(note)
                            return StepResult(
                                status="blocked",
                                summary=note,
                                raw_output=last_output,
                            )
                    if repaired != cmd_value:
                        args["command"] = repaired
                        cmd_value = repaired
                    try:
                        tokens = shlex.split(cmd_value)
                    except ValueError:
                        _render_rule("Blocked", style=ERROR_RULE_STYLE)
                        console.print("Shell command has invalid quoting.")
                        return StepResult(
                            status="blocked",
                            summary="Shell command has invalid quoting.",
                            raw_output=last_output,
                        )
                    if not is_command_allowed(tokens, allowlist):
                        _render_rule("Blocked", style=ERROR_RULE_STYLE)
                        console.print(f"Shell command not in allowlist: {tokens[0]}")
                        return StepResult(
                            status="blocked",
                            summary=f"Shell command not in allowlist: {tokens[0]}",
                            raw_output=last_output,
                        )
                    safe_command = " ".join(
                        token if token in SHELL_SEPARATORS else shlex.quote(token)
                        for token in tokens
                    )
                    args["command"] = safe_command
                _render_rule("MCP Args", style=INFO_RULE_STYLE)
                console.print(json.dumps(args, indent=2, ensure_ascii=False))
                result = call_mcp_tool(server, tool, args)
                output = json.dumps(result, indent=2, ensure_ascii=False)
                _render_output(output.splitlines())
                tool_output = output
            else:
                result = asyncio.run(execute_command(step.skill, command))
                _render_output(result.lines)
                tool_output = result.raw_output
        except Exception as exc:
            logger.error(str(exc))
            _render_rule("Error", style=ERROR_RULE_STYLE)
            console.print(str(exc))
            return StepResult(status="error", summary=str(exc), raw_output=last_output)

        last_output = tool_output
        _update_state_from_command_and_output(state, command_text, tool_output)
        _update_artifacts_from_output(state, tool_output)

        if command and command[0].startswith("mcp__"):
            pid_match = re.search(r"PID\\s+(\\d+)", tool_output)
            if pid_match:
                last_pid = int(pid_match.group(1))

        if not tool_loop:
            summary = _short_tool_output_summary(tool_output)
            return StepResult(
                status="ok",
                summary=summary or "Done.",
                raw_output=tool_output,
                artifacts=state.get("artifacts", {}),
            )

        messages.append({"role": "assistant", "content": f"Command: {command_text}"})
        messages.append({"role": "user", "content": f"Tool output:\n{tool_output}"})
        summary = _summarize_tool_output(tool_output, user_input)
        if summary:
            messages.append({"role": "assistant", "content": f"Tool summary: {summary}"})
        messages.append({"role": "user", "content": _render_state_summary(state)})
        decision = _decide_next_step(messages, user_input)
        if decision.get("done"):
            _render_rule("Result", style=RESULT_RULE_STYLE)
            console.print(decision.get("summary", "Done."))
            return StepResult(
                status="ok",
                summary=decision.get("summary", "Done."),
                raw_output=tool_output,
                artifacts=state.get("artifacts", {}),
            )
        current_query = decision.get("next_input", "")
        if not current_query:
            _render_rule("Warning", style=WARNING_RULE_STYLE)
            console.print("No next step provided; stopping.")
            return StepResult(status="stopped", summary="No next step provided.", raw_output=tool_output)


def _decide_next_step(messages: list[dict[str, str]], user_input: str) -> dict:
    system = (
        "Return json only. Decide whether the task is complete. "
        "Schema: {\"done\": true|false, \"summary\": \"...\", \"next_input\": \"...\"}."
    )
    response = chat_completion(
        [{"role": "system", "content": system}, *messages],
        response_format={"type": "json_object"},
        purpose="decide_next_step",
    )
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return _repair_decision(messages, user_input)


def _summarize_tool_output(tool_output: str, user_input: str) -> str:
    if not tool_output.strip():
        return ""
    if len(tool_output) < 400:
        return tool_output.strip().splitlines()[0]
    system = (
        "Summarize the tool output in one short sentence focused on task completion. "
        "Do not include extra commentary."
    )
    response = chat_completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"User: {user_input}\nOutput:\n{tool_output}"},
        ],
        response_format={"type": "text"},
        purpose="summarize_tool_output",
    )
    try:
        return response["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return ""


def _short_tool_output_summary(tool_output: str) -> str:
    if not tool_output.strip():
        return ""
    first = tool_output.strip().splitlines()[0]
    return first[:200]


def _repair_decision(messages: list[dict[str, str]], user_input: str) -> dict:
    system = (
        "Return json only. Repair the decision into valid JSON. "
        "Schema: {\"done\": true|false, \"summary\": \"...\", \"next_input\": \"...\"}."
    )
    response = chat_completion(
        [{"role": "system", "content": system}, *messages, {"role": "user", "content": f"User: {user_input}"}],
        response_format={"type": "json_object"},
        purpose="repair_decision",
    )
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return {
            "done": True,
            "summary": "No further steps inferred; see tool output above.",
            "next_input": "",
        }
