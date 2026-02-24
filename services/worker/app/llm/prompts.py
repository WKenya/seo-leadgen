SYSTEM_PROMPT = """You draft short, proof-based audit summaries for local business websites.
Rules:
- Only use findings backed by provided evidence.
- Do not invent facts.
- Keep email under 150 words.
- One CTA.
- Plain text email.
- Do not mention AI or automation.
Return valid JSON matching the requested schema.
"""


def build_summary_prompt(lead_name: str, audit_payload: dict[str, object]) -> str:
    return (
        f"Lead: {lead_name}\n"
        "Task: produce a short lead profile, three quick wins, and a short outreach email.\n"
        "Audit payload (proof-only):\n"
        f"{audit_payload}\n\n"
        "Return JSON with keys: lead_profile, quick_wins, email_subject, email_body_text, claims_used."
    )

