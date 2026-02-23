from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class LeadRead(BaseModel):
    id: UUID
    name: str
    category: str | None = None
    source: str | None = None
    place_id: str | None = None
    website_url: str
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    status: str
    notion_page_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_model(cls, lead: object) -> "LeadRead":
        return cls.model_validate(lead, from_attributes=True)

