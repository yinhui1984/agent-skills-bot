"""DeepSeek API client (model-agnostic wrapper interface uses DeepSeek V3 by default)."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class DeepSeekError(RuntimeError):
    pass


def _require_api_key() -> str:
    api_key = os.environ.get("APIKEY_DEEPSEEK")
    if not api_key:
        raise DeepSeekError("Missing APIKEY_DEEPSEEK environment variable")
    return api_key


def chat_completion(
    messages: List[Dict[str, str]],
    *,
    response_format: Dict[str, Any],
    model: str | None = None,
) -> Dict[str, Any]:
    api_key = _require_api_key()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)

    payload = {
        "model": model,
        "messages": messages,
        "response_format": response_format,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except Exception as exc:
        raise DeepSeekError(f"DeepSeek request failed: {exc}") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise DeepSeekError("DeepSeek response was not valid JSON") from exc
