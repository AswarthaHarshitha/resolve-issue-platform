"""The AI provider abstraction (DECISIONS.md D4, D10). Deliberately small: a
single method that takes an issue's text and returns a *structural* guess at
its shape - no framework, no agent, no RAG. It has no database access and no
idea what a "valid" category actually is in this deployment; that semantic
validation happens one layer up, in ai_validation.py, which is exactly the
AI-is-an-advisor boundary this project's architecture insists on.

`AISuggestion` is structural validation only (right fields, right types) -
it says nothing about whether `category`/`priority` are values this
deployment actually recognizes.
"""

import json
from abc import ABC, abstractmethod
from typing import Optional

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import get_settings

settings = get_settings()


class AISuggestion(BaseModel):
    category: str
    sub_category: Optional[str] = None
    priority: str
    summary: str
    reasoning: str


class AIProviderError(Exception):
    """The provider call itself failed - network error, timeout, non-2xx
    response. Distinct from getting a response that doesn't parse."""


class AIResponseFormatError(Exception):
    """The provider responded, but not with something that structurally
    matches AISuggestion (malformed JSON, missing fields, wrong types)."""


class AIProvider(ABC):
    @abstractmethod
    def classify(self, *, title: str, description: str) -> AISuggestion:
        """Raises AIProviderError or AIResponseFormatError on failure -
        never returns a fabricated/default suggestion (DECISIONS.md D5)."""


_SYSTEM_PROMPT = (
    "You are a triage assistant for an internal issue-tracking system. Given "
    "an issue's title and description, respond with ONLY a JSON object with "
    "exactly these keys: category (string - a broad department, e.g. 'IT' or "
    "'Facilities', NOT a specific topic), sub_category (string or null - a "
    "more specific area within that department, e.g. 'Network' or "
    "'Hardware'), priority (one of LOW, MEDIUM, HIGH, CRITICAL), summary (a "
    "one-sentence summary), reasoning (a brief explanation of the "
    "classification). Do not include any text outside the JSON object."
)


class OpenAICompatibleProvider(AIProvider):
    """Works with any OpenAI-compatible chat completions endpoint - the real
    OpenAI API, or another provider's compatibility layer (e.g. Google
    Gemini's, at https://generativelanguage.googleapis.com/v1beta/openai/)
    configured via OPENAI_BASE_URL. Swapping providers is a config change,
    not a code change."""

    def __init__(self, api_key: str, model: str, base_url: Optional[str] = None):
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def classify(self, *, title: str, description: str) -> AISuggestion:
        user_prompt = f"Title: {title}\n\nDescription: {description}"

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0,
            )
        except (APIError, APITimeoutError) as exc:
            raise AIProviderError(str(exc)) from exc

        try:
            content = response.choices[0].message.content
        except (IndexError, AttributeError) as exc:
            raise AIResponseFormatError("Provider response had no message content") from exc

        if content is None:
            raise AIResponseFormatError("Provider response content was empty")

        content = _strip_code_fences(content)

        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AIResponseFormatError(f"Provider response was not valid JSON: {exc}") from exc

        try:
            return AISuggestion.model_validate(payload)
        except ValidationError as exc:
            raise AIResponseFormatError(f"Provider response did not match the expected shape: {exc}") from exc


def _strip_code_fences(text: str) -> str:
    """Some providers wrap JSON in ```json ... ``` despite instructions not
    to - strip that before parsing rather than failing on cosmetic formatting."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def get_default_provider() -> AIProvider:
    return OpenAICompatibleProvider(
        api_key=settings.openai_api_key,
        model=settings.openai_model,
        base_url=settings.openai_base_url,
    )
