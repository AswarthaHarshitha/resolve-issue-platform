from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import AIAnalysisResultStatus, IssuePriority


class AIAnalysisResultPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    attempt_number: int
    status: AIAnalysisResultStatus
    raw_category: Optional[str] = None
    raw_sub_category: Optional[str] = None
    raw_priority: Optional[str] = None
    summary: Optional[str] = None
    reasoning: Optional[str] = None
    matched_priority: Optional[IssuePriority] = None
    error_message: Optional[str] = None
    created_at: datetime
