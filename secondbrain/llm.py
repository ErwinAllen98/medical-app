"""LLM access layer.

Three modes, all interchangeable:

* ``gemini``  — Google Generative AI (knowledge extraction / question writing)
* ``claude``  — Anthropic Messages API (learning diagnostics)
* ``manual``  — no API key needed: the prompt is handed to the doctor to paste
  into the NotebookLM / Claude web UI, and the reply is pasted back.

The manual bridge is a first-class citizen, because NotebookLM has no public
API and its source-grounding is exactly what we want to preserve.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import Settings


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str


# ---------------------------------------------------------------------------
# JSON extraction — LLMs love to wrap JSON in prose and code fences.
# ---------------------------------------------------------------------------

def extract_json(text: str):
    """Pull the first valid JSON object/array out of an LLM response."""
    if text is None:
        raise LLMError("empty response")
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        while start != -1:
            depth, in_str, esc = 0, False, False
            for i in range(start, len(cleaned)):
                ch = cleaned[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == opener:
                    depth += 1
                elif ch == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(cleaned[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = cleaned.find(opener, start + 1)
    raise LLMError("no valid JSON found in the response")


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def gemini_available(settings: Settings | None = None) -> bool:
    s = settings or Settings.load()
    if not s.gemini_api_key:
        return False
    try:  # new SDK
        from google import genai  # noqa: F401

        return True
    except ImportError:
        pass
    try:  # deprecated SDK, still works
        import google.generativeai  # noqa: F401

        return True
    except ImportError:
        return False


def claude_available(settings: Settings | None = None) -> bool:
    s = settings or Settings.load()
    return bool(s.anthropic_api_key)


def call_gemini(
    prompt: str,
    settings: Settings | None = None,
    json_mode: bool = True,
    timeout: int = 300,
) -> LLMResult:
    """Prefer the current `google-genai` SDK, fall back to the deprecated one."""
    s = settings or Settings.load()
    if not s.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not configured.")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        genai = None

    if genai is not None:
        config: dict = {"http_options": {"timeout": timeout * 1000}}
        if json_mode:
            config["response_mime_type"] = "application/json"
        try:
            client = genai.Client(api_key=s.gemini_api_key)
            response = client.models.generate_content(
                model=s.gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(**config),
            )
        except Exception as exc:
            raise LLMError(f"Gemini call failed: {exc}") from exc
        return LLMResult(text=response.text or "", provider="gemini", model=s.gemini_model)

    try:
        import google.generativeai as legacy
    except ImportError as exc:  # pragma: no cover
        raise LLMError("Install google-genai (pip install google-genai).") from exc

    legacy.configure(api_key=s.gemini_api_key)
    model = legacy.GenerativeModel(s.gemini_model)
    kwargs = {"request_options": {"timeout": timeout}}
    if json_mode:
        kwargs["generation_config"] = {"response_mime_type": "application/json"}
    try:
        response = model.generate_content(prompt, **kwargs)
    except Exception as exc:
        raise LLMError(f"Gemini call failed: {exc}") from exc
    return LLMResult(text=response.text or "", provider="gemini", model=s.gemini_model)


def call_claude(prompt: str, settings: Settings | None = None, max_tokens: int = 8000,
                timeout: int = 180) -> LLMResult:
    s = settings or Settings.load()
    if not s.anthropic_api_key:
        raise LLMError("ANTHROPIC_API_KEY is not configured.")
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise LLMError("requests is not installed.") from exc

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": s.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": s.claude_model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=timeout,
        )
    except Exception as exc:
        raise LLMError(f"Claude call failed: {exc}") from exc

    if resp.status_code >= 400:
        raise LLMError(f"Claude API error {resp.status_code}: {resp.text[:400]}")

    payload = resp.json()
    text = "".join(block.get("text", "") for block in payload.get("content", []))
    return LLMResult(text=text, provider="claude", model=s.claude_model)
