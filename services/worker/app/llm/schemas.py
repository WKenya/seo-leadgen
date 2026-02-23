from typing import Any

from pydantic import BaseModel, Field


class QuickWin(BaseModel):
    title: str
    why_it_matters: str
    how_to_fix: str


class DraftOutput(BaseModel):
    lead_profile: str = Field(min_length=20)
    quick_wins: list[QuickWin] = Field(min_length=1, max_length=3)
    email_subject: str
    email_body_text: str
    claims_used: list[Any] = Field(default_factory=list)

