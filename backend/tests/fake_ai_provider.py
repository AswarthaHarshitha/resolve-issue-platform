"""A test-only AIProvider implementation - lets tests exercise the full
classification/validation/routing pipeline deterministically, with no
network calls, by returning a canned suggestion or raising the same
exceptions a real provider call can raise."""

from typing import Optional

from app.services.ai_provider import AIProvider, AIProviderError, AIResponseFormatError, AISuggestion


class FakeAIProvider(AIProvider):
    def __init__(
        self,
        suggestion: Optional[AISuggestion] = None,
        raise_provider_error: bool = False,
        raise_format_error: bool = False,
    ):
        self._suggestion = suggestion
        self._raise_provider_error = raise_provider_error
        self._raise_format_error = raise_format_error

    def classify(self, *, title: str, description: str) -> AISuggestion:
        if self._raise_provider_error:
            raise AIProviderError("simulated provider outage")
        if self._raise_format_error:
            raise AIResponseFormatError("simulated malformed response")
        assert self._suggestion is not None, "FakeAIProvider needs a suggestion or an error mode"
        return self._suggestion
