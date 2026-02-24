from __future__ import annotations

import json
import time
from typing import Any

import httpx

from app.llm.prompts import SYSTEM_PROMPT, build_summary_prompt
from app.llm.schemas import DraftOutput


def extract_chat_message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    chunks.append(item["text"])
                elif isinstance(item.get("content"), str):
                    chunks.append(item["content"])
        return "".join(chunks)
    return ""


def _post_chat_completion(client: httpx.Client, *, base_url: str, api_key: str, body: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
    )
    response.raise_for_status()
    return response.json()


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
    last_error: Exception | None = None
    with httpx.Client(timeout=60.0) as client:
        for attempt in range(3):
            try:
                payload = _post_chat_completion(client, base_url=base_url, api_key=api_key, body=body)
                break
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in {408, 409, 429, 500, 502, 503, 504} or attempt == 2:
                    raise
                time.sleep(1.0 + attempt)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(1.0 + attempt)
        else:
            raise RuntimeError(f"openai_request_failed: {last_error}")

    choice = ((payload.get("choices") or [{}])[0]).get("message") or {}
    content = extract_chat_message_text(choice.get("content"))
    if not content.strip():
        raise RuntimeError("openai_empty_content")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"openai_invalid_json: {exc}") from exc

    return DraftOutput.model_validate(parsed)
