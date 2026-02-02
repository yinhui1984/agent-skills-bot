"""State and placeholder helpers for the CLI tool loop."""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
from datetime import datetime, timezone
from typing import Any

from agent_skills_bot.core.models import SkillStep


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


def _missing_required_placeholders(step: SkillStep) -> list[str]:
    if not step.requires:
        return []
    missing = []
    for req in step.requires:
        placeholder = f"{{{{{req}}}}}"
        if placeholder not in step.input:
            missing.append(placeholder)
    return missing


def _render_step_input(step_input: str, state: dict[str, object]) -> str:
    pattern = re.compile(r"\\{\\{([^}]+)\\}\\}")
    artifacts = state.get("artifacts", {})

    def _replace(match: re.Match) -> str:
        key = match.group(1).strip()
        if not key:
            raise ValueError("Empty placeholder in step input.")
        if not _resolve_requirement(key, artifacts, state):
            raise ValueError(f"Missing required value for placeholder: {key}")
        value = _resolve_requirement_value(key, artifacts, state)
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    return pattern.sub(_replace, step_input)


def _resolve_requirement_value(req: str, artifacts: dict[str, object], state: dict[str, object]) -> object:
    req = req.strip()
    if "." not in req:
        return artifacts.get(req)
    root, *parts = req.split(".")
    if root == "artifacts":
        data: object = artifacts
    elif root == "state":
        data = state
    else:
        return None
    for part in parts:
        if isinstance(data, dict) and part in data:
            data = data[part]
        else:
            return None
    return data


def _render_placeholders_in_command(command: list[str], state: dict[str, object]) -> list[str]:
    rendered: list[str] = []
    for item in command:
        if "{{" in item and "}}" in item:
            rendered.append(_render_step_input(item, state))
        else:
            rendered.append(item)
    return rendered


def _render_placeholders_in_args(args: object, state: dict[str, object]) -> object:
    if isinstance(args, dict):
        return {key: _render_placeholders_in_args(value, state) for key, value in args.items()}
    if isinstance(args, list):
        return [_render_placeholders_in_args(item, state) for item in args]
    if isinstance(args, str) and "{{" in args and "}}" in args:
        return _render_step_input(args, state)
    return args


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
