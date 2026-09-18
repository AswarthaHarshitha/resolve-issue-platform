from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.issue import UserSummary

_BODY_MAX_LENGTH = 5000


class CommentCreateRequest(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("body must not be empty")
        if len(value) > _BODY_MAX_LENGTH:
            raise ValueError(f"body must be at most {_BODY_MAX_LENGTH} characters")
        return value


class CommentPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    author: UserSummary
    body: str
    created_at: datetime
