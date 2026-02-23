SYSTEM_PROMPT = """You draft short, proof-based audit summaries for local business websites.
Only use findings backed by evidence.
Keep outputs concise and practical.
"""


def build_summary_prompt(lead_name: str, audit_payload: dict[str, object]) -> str:
    return f"Lead: {lead_name}\nAudit:\n{audit_payload}\nReturn structured JSON."

