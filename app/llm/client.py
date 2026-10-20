"""Ollama client: the only place the application talks to the LLM.

Based on the course OllamaProvider and parse_json_object. Settings come
from config.py (.env), so the model can be changed without touching code.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import requests

from config import OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, TEMPERATURE


@dataclass
class Generation:
    """One model response, with what is needed for logging and evaluation."""

    text: str
    model: str
    latency_s: float


def check_ollama() -> bool:
    """Check whether Ollama is available."""
    try:
        response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=10)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException:
        return False


def chat_with_llm(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
    temperature: float = TEMPERATURE,
    format: str | dict[str, Any] | None = None,
    timeout: int = 120,
) -> Generation:
    """Send system/user/assistant messages to Ollama /api/chat and return the reply.

    format="json" asks Ollama for a JSON object; a JSON schema (dict) asks
    for that exact shape. Errors (Ollama down, timeout, bad model name) are
    raised as requests exceptions for the caller to handle.
    """
    model = model or OLLAMA_CHAT_MODEL
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if format is not None:
        body["format"] = format

    started = time.perf_counter()
    response = requests.post(f"{OLLAMA_BASE_URL}/api/chat", json=body, timeout=timeout)
    response.raise_for_status()
    message = response.json().get("message") or {}
    text = (message.get("content") or "").strip()
    return Generation(text, model, time.perf_counter() - started)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the first JSON object from model text (fences and trailing prose allowed)."""
    if text is None:
        raise ValueError("Expected JSON text, got None")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise ValueError(f"No JSON object found in: {text[:200]!r}")
        value = json.loads(match.group())
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value
