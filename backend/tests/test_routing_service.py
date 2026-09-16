"""Unit tests for the pure escalation-priority function - no DB needed."""

import pytest

from app.models.enums import IssuePriority
from app.services.routing_service import determine_final_priority


@pytest.mark.parametrize("keyword_text", ["System outage reported", "the server is down", "cannot access email"])
def test_escalation_keyword_bumps_low_priority_to_high(keyword_text):
    assert determine_final_priority(IssuePriority.LOW, keyword_text) == IssuePriority.HIGH


def test_escalation_never_downgrades_an_already_higher_priority():
    assert determine_final_priority(IssuePriority.CRITICAL, "total outage") == IssuePriority.CRITICAL


def test_no_keyword_leaves_ai_priority_unchanged():
    assert determine_final_priority(IssuePriority.LOW, "The label text has a typo.") == IssuePriority.LOW


@pytest.mark.parametrize(
    "text_containing_substring_but_not_the_word",
    ["A dropdown menu is misaligned", "the showdown between two dialogs", "downtown office directions are wrong"],
)
def test_keyword_matching_is_whole_word_not_substring(text_containing_substring_but_not_the_word):
    """Regression test: a naive `"down" in text` check would incorrectly
    match "dropdown", "showdown", "downtown", etc. and wrongly escalate
    unrelated issues to HIGH priority."""
    assert (
        determine_final_priority(IssuePriority.LOW, text_containing_substring_but_not_the_word)
        == IssuePriority.LOW
    )
