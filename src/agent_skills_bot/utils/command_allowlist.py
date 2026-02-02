"""Command allowlist enforcement for shell run_command."""

from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable


ALLOWLIST_PATH = Path.home() / ".agent-skills-bot" / "command-allowlist.json"

DEFAULT_ALLOWLIST = {
    "version": 1,
    "allow": [
        "cd",
        "which",
        "ls",
        "pwd",
        "whoami",
        "date",
        "uname",
        "id",
        "cat",
        "head",
        "tail",
        "wc",
        "stat",
        "file",
        "grep",
        "rg",
        "find",
        "tree",
        "du",
        "df",
        "sort",
        "uniq",
        "cut",
        "tr",
        "sed",
        "yt-dlp",
    ],
    "allow_globs": [
        "cd:*",
        "ls:*",
        "cat:*",
        "head:*",
        "tail:*",
        "wc:*",
        "stat:*",
        "file:*",
        "grep:*",
        "rg:*",
        "find:*",
        "tree:*",
        "du:*",
        "df:*",
        "sort:*",
        "uniq:*",
        "cut:*",
        "tr:*",
        "sed:*",
        "yt-dlp:*",
    ],
}


SHELL_SEPARATORS = {"|", "&&", ";", "||"}


@dataclass(frozen=True)
class CommandAllowlist:
    allow: frozenset[str]
    allow_globs: tuple[str, ...]


def _normalize_allowlist(payload: dict) -> CommandAllowlist:
    allow_raw = payload.get("allow", [])
    allow_globs_raw = payload.get("allow_globs", [])
    allow = frozenset(str(item).strip() for item in allow_raw if str(item).strip())
    allow_globs = tuple(
        str(item).strip() for item in allow_globs_raw if str(item).strip()
    )
    return CommandAllowlist(allow=allow, allow_globs=allow_globs)


def _ensure_allowlist_file() -> None:
    if ALLOWLIST_PATH.exists():
        return
    ALLOWLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALLOWLIST_PATH.write_text(
        json.dumps(DEFAULT_ALLOWLIST, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_command_allowlist() -> CommandAllowlist:
    _ensure_allowlist_file()
    try:
        payload = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = DEFAULT_ALLOWLIST
    return _normalize_allowlist(payload)


def _split_shell_commands(tokens: Iterable[str]) -> list[list[str]]:
    commands: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in SHELL_SEPARATORS:
            if not current:
                return []
            commands.append(current)
            current = []
            continue
        current.append(token)
    if current:
        commands.append(current)
    return commands


def _match_allowlist(cmd: str, args: list[str], allowlist: CommandAllowlist) -> bool:
    if not cmd:
        return False
    cmd_name = Path(cmd).name
    candidates = {cmd, cmd_name} if cmd_name else {cmd}
    signatures = set()
    for name in candidates:
        if not name:
            continue
        signatures.add(name if not args else f"{name}:{' '.join(args)}")
    if any(name in allowlist.allow for name in candidates):
        return True
    for pattern in allowlist.allow_globs:
        for signature in signatures:
            if fnmatch(signature, pattern):
                return True
        for name in candidates:
            if fnmatch(name, pattern):
                return True
    return False


def is_command_allowed(tokens: list[str], allowlist: CommandAllowlist) -> bool:
    return find_blocked_command(tokens, allowlist) is None


def find_blocked_command(
    tokens: list[str], allowlist: CommandAllowlist
) -> str | None:
    if not tokens:
        return None
    for segment in _split_shell_commands(tokens):
        if not segment:
            return ""
        cmd = segment[0]
        args = segment[1:]
        if not _match_allowlist(cmd, args, allowlist):
            return cmd
    return None
