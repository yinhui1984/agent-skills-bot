"""DeepSeek API client (model-agnostic wrapper interface uses DeepSeek V3 by default)."""

from __future__ import annotations

import json
import os
import time
import urllib.request
import logging
from typing import Any, Dict, List


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
logger = logging.getLogger("app.core")


class DeepSeekError(RuntimeError):
    pass


def _require_api_key() -> str:
    api_key = os.environ.get("APIKEY_DEEPSEEK")
    if not api_key:
        raise DeepSeekError("Missing APIKEY_DEEPSEEK environment variable")
    return api_key


SHORT_RESPONSE_THRESHOLD = 20


def chat_completion(
    messages: List[Dict[str, str]],
    *,
    response_format: Dict[str, Any],
    model: str | None = None,
    purpose: str | None = None,
) -> Dict[str, Any]:
    api_key = _require_api_key()
    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    model = model or os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL)

    request_purpose = purpose or "unspecified"
    start = time.monotonic()

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

    body = ""
    error: Exception | None = None
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
    except Exception as exc:
        error = exc
        raise DeepSeekError(f"DeepSeek request failed: {exc}") from exc
    finally:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        if error is not None or len(body) <= SHORT_RESPONSE_THRESHOLD:
            logger.warning(
                "AI response issue purpose=%s bytes=%s elapsed_ms=%s error=%s",
                request_purpose,
                len(body or ""),
                elapsed_ms,
                error or "",
            )

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise DeepSeekError("DeepSeek response was not valid JSON") from exc


def _messages_length(messages: List[Dict[str, str]]) -> int:
    total = 0
    for item in messages:
        content = item.get("content")
        if isinstance(content, str):
            total += len(content)
        else:
            total += len(str(content))
    return total
