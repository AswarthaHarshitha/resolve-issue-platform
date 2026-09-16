"""Semantic validation of an AI suggestion against this deployment's actual
configuration (DECISIONS.md D5). The AIProvider only checks structural
shape; this is where "is 'Networking' a real category we have?" gets
answered - the AI is never trusted to know its own vocabulary is correct.

Explicitly supported normalization (case-insensitive matching) is applied;
anything beyond that fails rather than being coerced into a guess."""

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.category import Category
from app.models.enums import IssuePriority
from app.models.sub_category import SubCategory
from app.services.ai_provider import AISuggestion


@dataclass
class ValidatedSuggestion:
    category_id: UUID
    sub_category_id: Optional[UUID]
    priority: IssuePriority
    summary: str
    reasoning: str


class AIValidationError(Exception):
    """The AI's suggestion could not be matched to real configuration -
    category unknown, or priority not one of the allowed values. Carries a
    human-readable reason for storage in ai_analysis_results.error_message."""


def validate_ai_suggestion(db: Session, raw: AISuggestion) -> ValidatedSuggestion:
    category = (
        db.query(Category)
        .filter(func.lower(Category.name) == raw.category.strip().lower(), Category.is_active.is_(True))
        .first()
    )
    if category is None:
        raise AIValidationError(f"AI suggested an unknown category: {raw.category!r}")

    sub_category_id = None
    if raw.sub_category:
        sub_category = (
            db.query(SubCategory)
            .filter(
                SubCategory.category_id == category.id,
                func.lower(SubCategory.name) == raw.sub_category.strip().lower(),
                SubCategory.is_active.is_(True),
            )
            .first()
        )
        # A sub_category that doesn't match under the matched category is
        # dropped (explicit, documented normalization), not treated as a
        # hard failure - the category alone is still useful information.
        if sub_category is not None:
            sub_category_id = sub_category.id

    try:
        priority = IssuePriority(raw.priority.strip().upper())
    except ValueError:
        raise AIValidationError(f"AI suggested an unsupported priority: {raw.priority!r}")

    summary = raw.summary.strip()
    reasoning = raw.reasoning.strip()
    if not summary or not reasoning:
        raise AIValidationError("AI response was missing a summary or reasoning")

    return ValidatedSuggestion(
        category_id=category.id,
        sub_category_id=sub_category_id,
        priority=priority,
        summary=summary,
        reasoning=reasoning,
    )
