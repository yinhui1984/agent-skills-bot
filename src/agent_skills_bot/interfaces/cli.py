"""CLI for agent-skills-bot."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shlex
from typing import Any
import threading
import time
from datetime import datetime, timezone

from rich.console import Console
from rich import box
from rich.panel import Panel
from prompt_toolkit import Application
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import HSplit, ConditionalContainer
from prompt_toolkit.filters import Condition
from prompt_toolkit.styles import Style as PTStyle
from prompt_toolkit.widgets import Frame, TextArea, Label
from rich.rule import Rule
from rich.text import Text

from agent_skills_bot.core.router import route_plan
from agent_skills_bot.core.models import SkillPlan, SkillStep, StepResult
from agent_skills_bot.core.skill_runner import (
    allowed_tools_for,
    build_command,
    execute_command,
    get_skill_meta,
    list_reference_files,
    read_reference_files,
)
from agent_skills_bot.core.skills import load_skills
from agent_skills_bot.utils.logger import setup_cli_logger
from agent_skills_bot.utils.mcp_client import (
    call_mcp_tool,
    drain_mcp_notifications,
    list_mcp_servers,
    list_mcp_tools_summary,
    list_mcp_tools,
)
from agent_skills_bot.utils.deepseek_client import chat_completion


console = Console()
NOTIFY_POLL_SECONDS = 1.0

COMMANDS = {
    "/list": "List all installed skills",
    "/help": "Show available commands",
    "/mcp": "List MCP servers and tools",
    "/mcp-notifications": "Show pending MCP notifications",
    "/quit": "Exit the CLI",
}


class _CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/"):
            return
        for cmd in COMMANDS:
            if cmd.startswith(text):
                yield Completion(cmd, start_position=-len(text))


def _prompt_query() -> str:
    text_area = TextArea(
        multiline=False,
        prompt="› ",
        completer=_CommandCompleter(),
        complete_while_typing=True,
    )
    hint_text = "Type a query or use / for commands"
    hint = Label(hint_text, style="class:hint")
    show_hint = Condition(lambda: not text_area.text.strip())
    frame = Frame(
        HSplit(
            [
                text_area,
                ConditionalContainer(hint, filter=show_hint),
            ]
        )
    )
    style = PTStyle.from_dict(
        {
            "frame": "bg:#2b2b2b",
            "frame.border": "#666666",
            "text-area": "bg:#2b2b2b",
            "text-area.prompt": "bold",
            "hint": "#888888 bg:#2b2b2b",
        }
    )
    bindings = KeyBindings()

    @bindings.add("enter")
    def _accept(event) -> None:
        event.app.exit(result=text_area.text.strip())


    @bindings.add("c-c")
    def _cancel(event) -> None:
        event.app.exit(result="")

    app = Application(
        layout=Layout(HSplit([frame])),
        key_bindings=bindings,
        style=style,
        full_screen=False,
    )
    return app.run()


def _render_output(lines: list[str]) -> None:
    if not lines:
        console.print(Rule("Result", style="green"))
        console.print("(no output)")
        return

    rendered = Text("", no_wrap=False)
    for line in lines:
        if line.startswith("└ "):
            rendered.append(line + "\n", style="dim")
        elif line.strip() == "":
            rendered.append("\n")
        else:
            rendered.append(line + "\n")

    console.print(Rule("Result", style="green"))
    console.print(rendered)


def _render_command_help() -> None:
    rendered = Text()
    for cmd, desc in COMMANDS.items():
        rendered.append(f"{cmd}\n", style="bold")
        rendered.append(f"  {desc}\n")
    console.print(Rule("Commands", style="blue"))
    console.print(rendered)


def _render_banner() -> None:
    banner = (
        " ____    _  __  ___   _       _           ____     ___    _____ \n"
        "/ ___|  | |/ / |_ _| | |     | |         | __ )   / _ \\  |_   _|\n"
        "\\___ \\  | ' /   | |  | |     | |         |  _ \\  | | | |   | |  \n"
        " ___) | | . \\   | |  | |___  | |___      | |_) | | |_| |   | |  \n"
        "|____/  |_|\\_\\ |___| |_____| |_____|     |____/   \\___/    |_|  \n"
    )
    console.print(banner, style="bold cyan")


def _render_plan(plan: SkillPlan) -> None:
    console.print(Rule("Plan", style="blue"))
    for idx, step in enumerate(plan.steps, 1):
        requires = ", ".join(step.requires or []) if step.requires else "(none)"
        notes = step.notes or ""
        console.print(f"{idx}. {step.skill}")
        console.print(f"   input: {step.input}")
        console.print(f"   requires: {requires}")
        if notes:
            console.print(f"   notes: {notes}")


def _handle_command(command: str) -> bool:
    if command == "/":
        _render_command_help()
        return True
    if command == "/help":
        _render_command_help()
        return True
    if command == "/list":
        skills = load_skills()
        if not skills:
            console.print(Rule("Skills", style="yellow"))
            console.print("(no skills found)")
            return True
        rendered = Text()
        for skill in skills:
            rendered.append(f"{skill.name}\n", style="bold")
            rendered.append(f"  {skill.description}\n")
            rendered.append(f"  {skill.path}\n\n", style="dim")
        console.print(Rule("Skills", style="green"))
        console.print(rendered)
        return True
    if command == "/mcp":
        servers = list_mcp_servers()
        console.print(Rule("MCP", style="blue"))
        if not servers:
            console.print("(no MCP servers configured)")
            return True
        console.print(
            "Note: first-time MCP startup may take time to install/load dependencies. Please wait..."
        )
        summary = list_mcp_tools_summary()
        rendered = Text()
        for server in servers:
            rendered.append(f"{server}\n", style="bold")
            tools = summary.get(server, [])
            if tools:
                rendered.append(f"  {', '.join(tools)}\n")
            else:
                rendered.append("  (no tools)\n", style="dim")
        console.print(rendered)
        return True
    if command == "/mcp-notifications":
        notes = drain_mcp_notifications()
        console.print(Rule("MCP Notifications", style="blue"))
        if not notes:
            console.print("(no notifications)")
            return True
        rendered = Text()
        for server, items in notes.items():
            rendered.append(f"{server}\n", style="bold")
            for item in items:
                rendered.append(f"  {json.dumps(item, ensure_ascii=False)}\n", style="dim")
        console.print(rendered)
        return True
    if command in {"/quit", "/exit"}:
        raise SystemExit(0)
    return False


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
            console.print(Rule(f"References ({step.skill})", style="cyan"))
            console.print("\n".join(references))
            load_refs = console.input("Load references into context? (Y/n): ").strip().lower()
            if not load_refs or load_refs in {"y", "yes"}:
                reference_texts_by_skill[step.skill] = read_reference_files(references)
    except Exception as exc:
        logger.error(str(exc))
        console.print(Rule("Error", style="red"))
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


def _infer_mcp_args(
    user_input: str,
    server: str,
    tool: str,
    schema: dict | None,
    context: list[dict[str, str]],
) -> dict:
    system = (
        "You must output JSON only. Infer MCP tool arguments from the user request. "
        "Use the provided input schema if available. Do not include extra keys."
    )
    schema_text = json.dumps(schema, ensure_ascii=False) if schema else "(none)"
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Tool: {server}.{tool}\nSchema: {schema_text}\nUser: {user_input}",
        },
        *context,
    ]
    response = chat_completion(messages, response_format={"type": "json_object"})
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        raw = response["choices"][0]["message"]["content"]
        return _repair_mcp_args(user_input, server, tool, raw, schema, context)


def _get_mcp_schema(server: str, tool: str) -> dict | None:
    tools = list_mcp_tools().get(server, [])
    for item in tools:
        if item.get("name") == tool:
            return item.get("inputSchema")
    return None


def _repair_mcp_args(
    user_input: str,
    server: str,
    tool: str,
    raw: str,
    schema: dict | None,
    context: list[dict[str, str]],
) -> dict:
    system = (
        "Return JSON only. Repair the MCP arguments into a valid JSON object. "
        "Do not execute or expand shell expressions; keep them as plain strings. "
        "Use the input schema if available and do not add extra keys."
    )
    schema_text = json.dumps(schema, ensure_ascii=False) if schema else "(none)"
    messages = [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": f"Tool: {server}.{tool}\nSchema: {schema_text}\nRaw: {raw}\nUser: {user_input}",
        },
        *context,
    ]
    response = chat_completion(messages, response_format={"type": "json_object"})
    try:
        content = response["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Failed to repair MCP arguments") from exc


def _normalize_mcp_args(args: dict) -> dict:
    if "arguments" in args and isinstance(args["arguments"], dict):
        return args["arguments"]
    if "args" in args and isinstance(args["args"], dict):
        return args["args"]
    if "command" in args and isinstance(args["command"], str) and args["command"].startswith("mcp__"):
        return {}
    return args


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
            console.print(Rule("Blocked", style="red"))
            console.print(f"Step {idx} blocked; missing requirements: {', '.join(missing)}")
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
            console.print(Rule("Error", style="red"))
            console.print(result.summary or "Step failed.")
            return
    console.print(Rule("Result", style="green"))
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
    while True:
        loop_step += 1
        if loop_step > max_loop_count:
            console.print(Rule("Warning", style="yellow"))
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
        allowed_tools = allowed_tools_for(get_skill_meta(step.skill))
        if allowed_tools:
            console.print(Rule("allowed-tools", style="cyan"))
            console.print(", ".join(allowed_tools))
            if command and command[0] not in allowed_tools:
                console.print(Rule("Blocked", style="red"))
                console.print(f"Command tool '{command[0]}' is not in allowed-tools.")
                return StepResult(
                    status="blocked",
                    summary=f"Command tool '{command[0]}' is not in allowed-tools.",
                    raw_output=last_output,
                )
        console.print(Rule("Command", style="magenta"))
        console.print(command_text)
        confirm = console.input("[bold yellow]Execute command?[/bold yellow] (Y/n): ").strip().lower()
        if confirm and confirm not in {"y", "yes"}:
            console.print("Cancelled.", style="dim")
            return StepResult(status="cancelled", summary="Cancelled by user.", raw_output=last_output)

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
                console.print(Rule("MCP Args", style="cyan"))
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
            console.print(Rule("Error", style="red"))
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
            summary = _summarize_tool_output(tool_output, user_input)
            return StepResult(status="ok", summary=summary or "Done.", raw_output=tool_output, artifacts=state.get("artifacts", {}))

        messages.append({"role": "assistant", "content": f"Command: {command_text}"})
        messages.append({"role": "user", "content": f"Tool output:\n{tool_output}"})
        summary = _summarize_tool_output(tool_output, user_input)
        if summary:
            messages.append({"role": "assistant", "content": f"Tool summary: {summary}"})
        messages.append({"role": "user", "content": _render_state_summary(state)})
        decision = _decide_next_step(messages, user_input)
        if decision.get("done"):
            console.print(Rule("Result", style="green"))
            console.print(decision.get("summary", "Done."))
            return StepResult(status="ok", summary=decision.get("summary", "Done."), raw_output=tool_output, artifacts=state.get("artifacts", {}))
        current_query = decision.get("next_input", "")
        if not current_query:
            console.print(Rule("Warning", style="yellow"))
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
    )
    try:
        return response["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        return ""


def _repair_decision(messages: list[dict[str, str]], user_input: str) -> dict:
    system = (
        "Return json only. Repair the decision into valid JSON. "
        "Schema: {\"done\": true|false, \"summary\": \"...\", \"next_input\": \"...\"}."
    )
    response = chat_completion(
        [{"role": "system", "content": system}, *messages, {"role": "user", "content": f"User: {user_input}"}],
        response_format={"type": "json_object"},
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


def _environment_context() -> str:
    shell = os.environ.get("SHELL", "(unknown)")
    now = datetime.now(timezone.utc).isoformat()
    os_info = platform.platform()
    return f"Environment: os={os_info}; shell={shell}; time_utc={now}"


def _render_state_summary(state: dict[str, object]) -> str:
    cwd = state.get("cwd") or "(unknown)"
    created = sorted(state.get("created", set()))
    modified = sorted(state.get("modified", set()))
    last_command = state.get("last_command") or "(none)"
    last_abs_path = state.get("last_abs_path") or "(none)"
    last_paths = state.get("last_paths", [])
    last_paths_text = ", ".join(last_paths) if last_paths else "(none)"
    artifacts = state.get("artifacts", {}) or {}
    artifact_keys = ", ".join(sorted(artifacts.keys())) if artifacts else "(none)"
    artifact_file = artifacts.get("file_path") if isinstance(artifacts, dict) else None
    artifact_urls = artifacts.get("url_list") if isinstance(artifacts, dict) else None
    artifact_text = artifacts.get("text") if isinstance(artifacts, dict) else None
    url_count = len(artifact_urls) if isinstance(artifact_urls, list) else 0
    text_len = len(artifact_text) if isinstance(artifact_text, str) else 0
    lines = [
        "State summary:",
        f"- cwd: {cwd}",
        f"- last_command: {last_command}",
        f"- last_abs_path: {last_abs_path}",
        f"- last_paths: {last_paths_text}",
        f"- created: {', '.join(created) if created else '(none)'}",
        f"- modified: {', '.join(modified) if modified else '(none)'}",
        f"- artifacts: {artifact_keys}",
        f"- artifacts.file_path: {artifact_file or '(none)'}",
        f"- artifacts.url_list.count: {url_count}",
        f"- artifacts.text.length: {text_len}",
    ]
    return "\n".join(lines)


def _render_state_json(state: dict[str, object]) -> str:
    payload: dict[str, Any] = {
        "cwd": state.get("cwd"),
        "last_command": state.get("last_command"),
        "last_abs_path": state.get("last_abs_path"),
        "last_paths": state.get("last_paths"),
        "created": sorted(state.get("created", set())),
        "modified": sorted(state.get("modified", set())),
        "artifacts": state.get("artifacts", {}),
    }
    return json.dumps(payload, ensure_ascii=False)


def _update_artifacts_from_output(state: dict[str, object], tool_output: str) -> None:
    artifacts = _extract_artifacts(tool_output)
    if not artifacts:
        return
    existing = state.get("artifacts")
    if not isinstance(existing, dict):
        existing = {}
        state["artifacts"] = existing
    _merge_artifacts(existing, artifacts)


def _extract_artifacts(tool_output: str) -> dict[str, object]:
    artifacts: dict[str, object] = {}
    text = ""
    try:
        payload = json.loads(tool_output)
        if isinstance(payload, dict):
            content = payload.get("content")
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                text = "\n".join(part for part in parts if part)
    except json.JSONDecodeError:
        pass

    if not text:
        text = tool_output.strip()

    if text:
        artifacts["text"] = text
        urls = re.findall(r"https?://[^\\s'\\\")]+", text)
        if urls:
            artifacts["url_list"] = list(dict.fromkeys(urls))

    paths = _extract_paths_from_output(tool_output)
    if paths:
        artifacts["paths"] = paths
        artifacts["file_path"] = paths[-1]
    return artifacts


def _merge_artifacts(target: dict[str, object], incoming: dict[str, object]) -> None:
    for key, value in incoming.items():
        if isinstance(value, list):
            existing = target.get(key)
            if isinstance(existing, list):
                for item in value:
                    if item not in existing:
                        existing.append(item)
            else:
                target[key] = list(value)
        else:
            target[key] = value


def _check_requires(requires: list[str] | None, state: dict[str, object]) -> list[str]:
    if not requires:
        return []
    artifacts = state.get("artifacts", {})
    missing = []
    for req in requires:
        if not _resolve_requirement(req, artifacts, state):
            missing.append(req)
    return missing


def _resolve_requirement(req: str, artifacts: dict[str, object], state: dict[str, object]) -> bool:
    req = req.strip()
    if not req:
        return True
    if "." not in req:
        value = artifacts.get(req)
        return bool(value)
    root, *parts = req.split(".")
    if root == "artifacts":
        data: object = artifacts
    elif root == "state":
        data = state
    else:
        return False
    for part in parts:
        if isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return False
    return bool(data)


def _update_state_from_command_and_output(
    state: dict[str, object],
    command_text: str,
    tool_output: str,
) -> None:
    state["last_command"] = command_text
    shell_cmd = _extract_shell_command(command_text)
    if not shell_cmd:
        return
    cwd = _extract_cwd(shell_cmd)
    if cwd:
        state["cwd"] = cwd
    created, modified = _extract_file_changes(shell_cmd)
    state.setdefault("created", set()).update(created)
    state.setdefault("modified", set()).update(modified)
    output_paths = _extract_paths_from_output(tool_output)
    if output_paths:
        state["last_paths"] = output_paths
        state["last_abs_path"] = output_paths[-1]
        state.setdefault("modified", set()).update(output_paths)


def _extract_shell_command(command_text: str) -> str:
    if command_text.startswith("bash -lc "):
        return command_text[len("bash -lc ") :].strip()
    return ""


def _extract_cwd(shell_cmd: str) -> str | None:
    match = re.search(r"(?:^|[;&|]\\s*)cd\\s+([^;&|]+)", shell_cmd)
    if not match:
        return None
    raw = match.group(1).strip()
    return _strip_quotes(raw)


def _extract_file_changes(shell_cmd: str) -> tuple[set[str], set[str]]:
    created: set[str] = set()
    modified: set[str] = set()
    # Redirections: > or >> target
    for target in re.findall(r">>\\s*([^;&|]+)|>\\s*([^;&|]+)", shell_cmd):
        path = _strip_quotes(next((t for t in target if t), ""))
        if path:
            modified.add(path)
    tokens = _safe_split(shell_cmd)
    if not tokens:
        return created, modified
    if tokens[0] in {"touch", "mkdir"}:
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            created.add(_strip_quotes(token))
    if tokens[0] in {"cp", "mv"} and len(tokens) >= 3:
        dest = _strip_quotes(tokens[-1])
        if dest:
            modified.add(dest)
    return created, modified


def _extract_paths_from_output(output: str) -> list[str]:
    paths: list[str] = []
    for line in output.splitlines():
        match = re.search(r"(/[^\\s'\\\"]+)", line)
        if match:
            path = match.group(1)
            if _looks_like_local_path(path) and path not in paths:
                paths.append(path)
    return paths


def _looks_like_local_path(path: str) -> bool:
    if path.startswith("http://") or path.startswith("https://"):
        return False
    allowed_prefixes = (
        "/Users/",
        "/home/",
        "/tmp/",
        "/var/",
        "/private/",
        "/Volumes/",
        "/opt/",
        "/etc/",
    )
    return path.startswith(allowed_prefixes)


def _strip_quotes(value: str) -> str:
    return value.strip().strip("\"'")


def _safe_split(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def run_cli_loop(
    initial_query: str | None,
    loop: bool = True,
    tool_loop: bool = True,
    max_loop_count: int = 10,
) -> None:
    setup_cli_logger()
    if initial_query is None:
        _render_banner()
    session_state: dict[str, object] = {
        "cwd": os.getcwd(),
        "created": set(),
        "modified": set(),
        "last_command": "",
        "last_paths": [],
        "last_abs_path": "",
        "artifacts": {},
    }
    stop_event = threading.Event()
    notify_thread = threading.Thread(
        target=_notification_loop,
        args=(stop_event,),
        daemon=True,
    )
    notify_thread.start()
    pending = initial_query
    try:
        while True:
            if not pending:
                pending = _prompt_query()
            if not pending:
                break
            if pending.startswith("/"):
                handled = _handle_command(pending)
                if not handled:
                    console.print(Rule("Command", style="yellow"))
                    console.print("Unknown command. Try /help")
                pending = None
                if not loop:
                    break
                continue
            run_cli(
                pending,
                tool_loop=tool_loop,
                max_loop_count=max_loop_count,
                session_state=session_state,
            )
            console.print()
            pending = None
            if not loop:
                break
    except KeyboardInterrupt:
        console.print("\nBye.", style="dim")
    finally:
        stop_event.set()


def _notification_loop(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        notes = drain_mcp_notifications()
        if notes:
            console.print(Rule("MCP Notifications", style="blue"))
            rendered = Text()
            for server, items in notes.items():
                rendered.append(f"{server}\n", style="bold")
                for item in items:
                    rendered.append(f"  {json.dumps(item, ensure_ascii=False)}\n", style="dim")
            console.print(rendered)
        time.sleep(NOTIFY_POLL_SECONDS)
