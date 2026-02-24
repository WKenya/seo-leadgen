from __future__ import annotations

import json
from typing import Any

import httpx

from app.llm.prompts import SYSTEM_PROMPT, build_summary_prompt
from app.llm.schemas import DraftOutput


def generate_draft_with_openai(
    *,
    api_key: str,
    model: str,
    base_url: str,
    lead_name: str,
    audit_payload: dict[str, Any],
) -> DraftOutput:
    if not api_key:
        raise RuntimeError("missing OPENAI_API_KEY")
    if not model:
        raise RuntimeError("missing OPENAI_MODEL")

    body = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_summary_prompt(lead_name, audit_payload)},
        ],
        "temperature": 0.2,
    }
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        )
        response.raise_for_status()
        payload = response.json()

    choice = ((payload.get("choices") or [{}])[0]).get("message") or {}
    content = choice.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("openai_empty_content")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"openai_invalid_json: {exc}") from exc

    return DraftOutput.model_validate(parsed)

