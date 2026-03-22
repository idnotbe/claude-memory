"""Tests for memory_log_analyzer.py minimum sample size validity guards.

Covers all rate-based anomaly detectors to ensure they refuse to produce
findings when the sample size is below the configured minimum threshold.
This prevents false-positive CRITICAL/HIGH findings from tiny datasets.

Each detector function takes (events, event_counts) where:
- events: list of event dicts (raw JSONL entries)
- event_counts: Counter of event_type strings
"""

import sys
from collections import Counter
from pathlib import Path

import pytest

# Import directly from the scripts directory (conftest.py adds it to sys.path)
from memory_log_analyzer import (
    _detect_zero_length_prompt,
    _detect_skip_rate_high,
    _detect_category_never_triggers,
    _detect_booster_never_hits,
    _detect_error_spike,
    _MIN_SKIP_EVENTS_ZERO_PROMPT,
    _MIN_RETRIEVAL_EVENTS_SKIP_RATE,
    _MIN_TRIAGE_EVENTS_CATEGORY,
    _MIN_TRIAGE_EVENTS_BOOSTER,
    _MIN_ERROR_SPIKE_EVENTS,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_skip_event(prompt_length=0):
    """Create a retrieval.skip event dict with given prompt_length."""
    return {
        "event_type": "retrieval.skip",
        "level": "info",
        "timestamp": "2026-03-20T12:00:00Z",
        "data": {"prompt_length": prompt_length, "reason": "too_short"},
    }


def _make_triage_event(triggered=None, all_scores=None):
    """Create a triage.score event dict.

    Args:
        triggered: list of {"category": str, "score": float} dicts for
            categories that exceeded their threshold.
        all_scores: list of {"category": str, "score": float} dicts for
            all evaluated categories (including those below threshold).
    """
    if triggered is None:
        triggered = []
    if all_scores is None:
        all_scores = []
    return {
        "event_type": "triage.score",
        "level": "info",
        "timestamp": "2026-03-20T12:00:00Z",
        "data": {
            "triggered": triggered,
            "all_scores": all_scores,
        },
    }


def _make_retrieval_event(event_type="retrieval.skip"):
    """Create a generic retrieval event dict."""
    return {
        "event_type": event_type,
        "level": "info",
        "timestamp": "2026-03-20T12:00:00Z",
        "data": {},
    }


def _make_triage_event_with_booster(
    category,
    primary_hits=0,
    booster_hits=0,
    score=5,
    triggered=False,
):
    """Create a triage.score event with booster hit data for a category.

    This uses the extended triage format that includes primary_hits and
    booster_hits fields within each all_scores entry.
    """
    score_entry = {
        "category": category,
        "score": score,
        "primary_hits": primary_hits,
        "booster_hits": booster_hits,
    }
    triggered_list = (
        [{"category": category, "score": score}] if triggered else []
    )
    return {
        "event_type": "triage.score",
        "level": "info",
        "timestamp": "2026-03-20T12:00:00Z",
        "data": {
            "triggered": triggered_list,
            "all_scores": [score_entry],
        },
    }


def _counter_from_events(events):
    """Build event_counts Counter from a list of event dicts."""
    return Counter(e.get("event_type", "unknown") for e in events)


# ===========================================================================
# _detect_zero_length_prompt tests
# ===========================================================================

class TestDetectZeroLengthPrompt:
    """Tests for _detect_zero_length_prompt minimum sample guard."""

    def test_zero_prompt_no_events(self):
        """0 skip events -> None."""
        events = []
        ec = _counter_from_events(events)
        assert _detect_zero_length_prompt(events, ec) is None

    def test_zero_prompt_below_min(self):
        """9 skip events (all prompt_length=0) -> None (below _MIN_SKIP_EVENTS_ZERO_PROMPT=10)."""
        events = [_make_skip_event(prompt_length=0) for _ in range(9)]
        ec = _counter_from_events(events)
        result = _detect_zero_length_prompt(events, ec)
        assert result is None

    def test_zero_prompt_at_min_triggers(self):
        """10 skip events (all prompt_length=0) -> returns finding (100% > 50%)."""
        events = [_make_skip_event(prompt_length=0) for _ in range(10)]
        ec = _counter_from_events(events)
        result = _detect_zero_length_prompt(events, ec)
        assert result is not None
        assert result["code"] == "ZERO_LENGTH_PROMPT"
        assert result["severity"] == "critical"

    def test_zero_prompt_at_min_below_rate(self):
        """10 skip events (4 with prompt_length=0, 6 normal) -> None (40% < 50%)."""
        events = (
            [_make_skip_event(prompt_length=0) for _ in range(4)]
            + [_make_skip_event(prompt_length=42) for _ in range(6)]
        )
        ec = _counter_from_events(events)
        result = _detect_zero_length_prompt(events, ec)
        assert result is None

    def test_zero_prompt_sample_size_in_data(self):
        """Verify finding has sample_size key in data."""
        events = [_make_skip_event(prompt_length=0) for _ in range(15)]
        ec = _counter_from_events(events)
        result = _detect_zero_length_prompt(events, ec)
        assert result is not None
        assert "sample_size" in result["data"]
        assert result["data"]["sample_size"] == 15

    def test_zero_prompt_exactly_at_boundary(self):
        """Exactly _MIN_SKIP_EVENTS_ZERO_PROMPT events with exactly 50% rate -> None.

        The threshold is >50%, so exactly 50% should not trigger.
        """
        # 5 zero, 5 normal = exactly 50%
        events = (
            [_make_skip_event(prompt_length=0) for _ in range(5)]
            + [_make_skip_event(prompt_length=10) for _ in range(5)]
        )
        ec = _counter_from_events(events)
        result = _detect_zero_length_prompt(events, ec)
        assert result is None

    def test_zero_prompt_just_above_rate(self):
        """10 events, 6 zero prompt (60% > 50%) -> triggers."""
        events = (
            [_make_skip_event(prompt_length=0) for _ in range(6)]
            + [_make_skip_event(prompt_length=10) for _ in range(4)]
        )
        ec = _counter_from_events(events)
        result = _detect_zero_length_prompt(events, ec)
        assert result is not None
        assert result["code"] == "ZERO_LENGTH_PROMPT"


# ===========================================================================
# _detect_skip_rate_high tests
# ===========================================================================

class TestDetectSkipRateHigh:
    """Tests for _detect_skip_rate_high minimum sample guard."""

    def test_skip_rate_no_events(self):
        """0 retrieval events -> None."""
        events = []
        ec = _counter_from_events(events)
        assert _detect_skip_rate_high(events, ec) is None

    def test_skip_rate_below_min(self):
        """19 retrieval.skip events -> None (below _MIN_RETRIEVAL_EVENTS_SKIP_RATE=20)."""
        events = [_make_retrieval_event("retrieval.skip") for _ in range(19)]
        ec = _counter_from_events(events)
        result = _detect_skip_rate_high(events, ec)
        assert result is None

    def test_skip_rate_at_min_triggers(self):
        """20 retrieval.skip events -> returns finding (100% skip > 90%)."""
        events = [_make_retrieval_event("retrieval.skip") for _ in range(20)]
        ec = _counter_from_events(events)
        result = _detect_skip_rate_high(events, ec)
        assert result is not None
        assert result["code"] == "SKIP_RATE_HIGH"
        assert result["severity"] == "critical"
        assert result["data"]["sample_size"] == 20

    def test_skip_rate_at_min_below_rate(self):
        """20 events (10 skip, 10 search) -> None (50% < 90%)."""
        events = (
            [_make_retrieval_event("retrieval.skip") for _ in range(10)]
            + [_make_retrieval_event("retrieval.search") for _ in range(10)]
        )
        ec = _counter_from_events(events)
        result = _detect_skip_rate_high(events, ec)
        assert result is None

    def test_skip_rate_exactly_at_threshold(self):
        """90% skip rate exactly -> should NOT trigger (threshold is >90%, not >=)."""
        # 18 skip + 2 search = 90%
        events = (
            [_make_retrieval_event("retrieval.skip") for _ in range(18)]
            + [_make_retrieval_event("retrieval.search") for _ in range(2)]
        )
        ec = _counter_from_events(events)
        result = _detect_skip_rate_high(events, ec)
        assert result is None

    def test_skip_rate_just_above_threshold(self):
        """Just above 90% -> triggers."""
        # 19 skip + 1 search = 95%
        events = (
            [_make_retrieval_event("retrieval.skip") for _ in range(19)]
            + [_make_retrieval_event("retrieval.search") for _ in range(1)]
        )
        ec = _counter_from_events(events)
        result = _detect_skip_rate_high(events, ec)
        assert result is not None
        assert result["code"] == "SKIP_RATE_HIGH"

    def test_skip_rate_non_retrieval_events_ignored(self):
        """Non-retrieval events don't count toward retrieval total."""
        events = (
            [_make_retrieval_event("retrieval.skip") for _ in range(5)]
            + [{"event_type": "triage.score", "level": "info"} for _ in range(50)]
        )
        ec = _counter_from_events(events)
        # Only 5 retrieval events, below min of 20
        result = _detect_skip_rate_high(events, ec)
        assert result is None


# ===========================================================================
# _detect_category_never_triggers tests
# ===========================================================================

class TestDetectCategoryNeverTriggers:
    """Tests for _detect_category_never_triggers minimum sample guard."""

    def test_category_no_events(self):
        """0 triage events -> empty list."""
        events = []
        ec = _counter_from_events(events)
        assert _detect_category_never_triggers(events, ec) == []

    def test_category_below_min(self):
        """29 triage events with non-zero scores but no triggers -> [] (below min=30)."""
        events = [
            _make_triage_event(
                triggered=[],
                all_scores=[
                    {"category": "DECISION", "score": 3},
                    {"category": "RUNBOOK", "score": 2},
                ],
            )
            for _ in range(29)
        ]
        ec = _counter_from_events(events)
        result = _detect_category_never_triggers(events, ec)
        assert result == []

    def test_category_at_min_triggers(self):
        """30 triage events, DECISION has non-zero scores but never triggers -> finding."""
        events = [
            _make_triage_event(
                triggered=[],  # nothing triggers
                all_scores=[
                    {"category": "DECISION", "score": 3},
                    {"category": "RUNBOOK", "score": 0},
                ],
            )
            for _ in range(30)
        ]
        ec = _counter_from_events(events)
        result = _detect_category_never_triggers(events, ec)
        assert len(result) >= 1
        categories = [f["data"]["category"] for f in result]
        assert "DECISION" in categories
        # RUNBOOK should NOT be flagged (score=0 means no evidence of near-miss)
        assert "RUNBOOK" not in categories

    def test_category_at_min_no_issue(self):
        """30 triage events, all categories with scores also trigger -> no findings."""
        events = [
            _make_triage_event(
                triggered=[
                    {"category": "DECISION", "score": 8},
                    {"category": "RUNBOOK", "score": 7},
                ],
                all_scores=[
                    {"category": "DECISION", "score": 8},
                    {"category": "RUNBOOK", "score": 7},
                ],
            )
            for _ in range(30)
        ]
        ec = _counter_from_events(events)
        result = _detect_category_never_triggers(events, ec)
        assert result == []

    def test_category_finding_has_correct_code(self):
        """Verify finding code is CATEGORY_NEVER_TRIGGERS."""
        events = [
            _make_triage_event(
                triggered=[],
                all_scores=[{"category": "CONSTRAINT", "score": 2}],
            )
            for _ in range(30)
        ]
        ec = _counter_from_events(events)
        result = _detect_category_never_triggers(events, ec)
        assert len(result) >= 1
        assert all(f["code"] == "CATEGORY_NEVER_TRIGGERS" for f in result)
        assert all(f["severity"] == "high" for f in result)

    def test_category_multiple_never_trigger(self):
        """Multiple categories with non-zero scores but no triggers -> multiple findings."""
        events = [
            _make_triage_event(
                triggered=[],
                all_scores=[
                    {"category": "DECISION", "score": 4},
                    {"category": "TECH_DEBT", "score": 2},
                    {"category": "PREFERENCE", "score": 1},
                ],
            )
            for _ in range(30)
        ]
        ec = _counter_from_events(events)
        result = _detect_category_never_triggers(events, ec)
        categories = {f["data"]["category"] for f in result}
        assert "DECISION" in categories
        assert "TECH_DEBT" in categories
        assert "PREFERENCE" in categories


# ===========================================================================
# _detect_booster_never_hits tests
# ===========================================================================

class TestDetectBoosterNeverHits:
    """Tests for _detect_booster_never_hits minimum sample guard."""

    def test_booster_no_events(self):
        """0 triage events -> empty list."""
        events = []
        ec = _counter_from_events(events)
        assert _detect_booster_never_hits(events, ec) == []

    def test_booster_below_min(self):
        """49 events with booster data -> [] (below _MIN_TRIAGE_EVENTS_BOOSTER=50)."""
        events = [
            _make_triage_event_with_booster(
                "DECISION", primary_hits=3, booster_hits=0
            )
            for _ in range(49)
        ]
        ec = _counter_from_events(events)
        result = _detect_booster_never_hits(events, ec)
        assert result == []

    def test_booster_at_min_triggers(self):
        """50 events, DECISION has primary_hits>0 but booster_hits=0 -> finding."""
        events = [
            _make_triage_event_with_booster(
                "DECISION", primary_hits=3, booster_hits=0
            )
            for _ in range(50)
        ]
        ec = _counter_from_events(events)
        result = _detect_booster_never_hits(events, ec)
        assert len(result) >= 1
        categories = [f["data"]["category"] for f in result]
        assert "DECISION" in categories

    def test_booster_old_format(self):
        """50 events without primary_hits/booster_hits fields -> [] (no data to analyze)."""
        events = [
            _make_triage_event(
                triggered=[],
                all_scores=[{"category": "DECISION", "score": 3}],
            )
            for _ in range(50)
        ]
        ec = _counter_from_events(events)
        result = _detect_booster_never_hits(events, ec)
        assert result == []

    def test_booster_nonzero_booster(self):
        """50 events, primary>0 AND booster>0 -> no finding."""
        events = [
            _make_triage_event_with_booster(
                "DECISION", primary_hits=3, booster_hits=2
            )
            for _ in range(50)
        ]
        ec = _counter_from_events(events)
        result = _detect_booster_never_hits(events, ec)
        # DECISION should NOT appear since booster_hits > 0
        categories = [f["data"]["category"] for f in result]
        assert "DECISION" not in categories

    def test_booster_session_summary_excluded(self):
        """SESSION_SUMMARY never appears in booster findings.

        SESSION_SUMMARY is a special category that doesn't use keyword
        boosters, so it should never be flagged.
        """
        events = [
            _make_triage_event_with_booster(
                "SESSION_SUMMARY", primary_hits=5, booster_hits=0
            )
            for _ in range(50)
        ]
        ec = _counter_from_events(events)
        result = _detect_booster_never_hits(events, ec)
        categories = [f["data"]["category"] for f in result]
        assert "SESSION_SUMMARY" not in categories

    def test_booster_mixed_categories(self):
        """50 events with mixed categories: only the one with 0 booster_hits is flagged."""
        events = []
        for _ in range(50):
            events.append(
                _make_triage_event_with_booster(
                    "DECISION", primary_hits=3, booster_hits=0
                )
            )
            events.append(
                _make_triage_event_with_booster(
                    "RUNBOOK", primary_hits=4, booster_hits=2
                )
            )
        # Merge into single events (each triage event has multiple all_scores entries)
        merged = []
        for i in range(50):
            merged.append({
                "event_type": "triage.score",
                "level": "info",
                "timestamp": "2026-03-20T12:00:00Z",
                "data": {
                    "triggered": [],
                    "all_scores": [
                        {"category": "DECISION", "score": 5, "primary_hits": 3, "booster_hits": 0},
                        {"category": "RUNBOOK", "score": 6, "primary_hits": 4, "booster_hits": 2},
                    ],
                },
            })
        ec = _counter_from_events(merged)
        result = _detect_booster_never_hits(merged, ec)
        categories = [f["data"]["category"] for f in result]
        assert "DECISION" in categories
        assert "RUNBOOK" not in categories

    def test_booster_zero_primary_not_flagged(self):
        """If primary_hits=0 AND booster_hits=0, it should NOT be flagged.

        A category that never gets any hits at all is not a booster
        misconfiguration -- the keywords just don't match.
        """
        events = [
            _make_triage_event_with_booster(
                "CONSTRAINT", primary_hits=0, booster_hits=0
            )
            for _ in range(50)
        ]
        ec = _counter_from_events(events)
        result = _detect_booster_never_hits(events, ec)
        categories = [f["data"]["category"] for f in result]
        assert "CONSTRAINT" not in categories


# ===========================================================================
# _detect_error_spike tests
# ===========================================================================

class TestDetectErrorSpike:
    """Tests for _detect_error_spike minimum sample guard."""

    def _make_error_events(self, event_type, count, error_count):
        """Build a list of events with some errors and some info.

        Args:
            event_type: base event_type for all events.
            count: total events.
            error_count: how many should be level='error'.
        """
        events = []
        for i in range(count):
            events.append({
                "event_type": event_type,
                "level": "error" if i < error_count else "info",
                "timestamp": "2026-03-20T12:00:00Z",
            })
        return events

    def test_error_spike_below_min(self):
        """9 events in category (all errors) -> [] (below _MIN_ERROR_SPIKE_EVENTS=10)."""
        events = self._make_error_events("retrieval.skip", 9, 9)
        ec = _counter_from_events(events)
        result = _detect_error_spike(events, ec)
        assert result == []

    def test_error_spike_at_min(self):
        """10 events (5 errors) -> returns finding (50% > 10%)."""
        events = self._make_error_events("retrieval.skip", 10, 5)
        ec = _counter_from_events(events)
        result = _detect_error_spike(events, ec)
        assert len(result) >= 1
        cats = [f["data"]["category"] for f in result]
        assert "retrieval" in cats

    def test_error_spike_at_min_below_rate(self):
        """10 events (1 error) -> [] (10% == threshold, not exceeded)."""
        events = self._make_error_events("triage.score", 10, 1)
        ec = _counter_from_events(events)
        result = _detect_error_spike(events, ec)
        assert result == []

    def test_error_spike_no_events(self):
        """0 events -> []."""
        events = []
        ec = _counter_from_events(events)
        result = _detect_error_spike(events, ec)
        assert result == []

    def test_error_spike_just_above_rate(self):
        """10 events (2 errors = 20%) -> triggers (20% > 10%)."""
        events = self._make_error_events("retrieval.search", 10, 2)
        ec = _counter_from_events(events)
        result = _detect_error_spike(events, ec)
        assert len(result) >= 1

    def test_error_spike_multiple_categories(self):
        """Error spikes in two different categories -> two findings."""
        events = (
            self._make_error_events("retrieval.skip", 10, 5)
            + self._make_error_events("triage.score", 10, 5)
        )
        ec = _counter_from_events(events)
        result = _detect_error_spike(events, ec)
        cats = {f["data"]["category"] for f in result}
        assert "retrieval" in cats
        assert "triage" in cats

    def test_error_spike_finding_structure(self):
        """Verify the finding structure contains expected fields."""
        events = self._make_error_events("retrieval.skip", 20, 10)
        ec = _counter_from_events(events)
        result = _detect_error_spike(events, ec)
        assert len(result) >= 1
        finding = result[0]
        assert finding["code"] == "ERROR_SPIKE"
        assert finding["severity"] == "high"
        assert "error_count" in finding["data"]
        assert "total_count" in finding["data"]
        assert "error_rate" in finding["data"]


# ===========================================================================
# Constant value sanity tests
# ===========================================================================

class TestConstantValues:
    """Verify the minimum sample constants match expected values."""

    def test_min_skip_events_zero_prompt(self):
        assert _MIN_SKIP_EVENTS_ZERO_PROMPT == 10

    def test_min_retrieval_events_skip_rate(self):
        assert _MIN_RETRIEVAL_EVENTS_SKIP_RATE == 20

    def test_min_triage_events_category(self):
        assert _MIN_TRIAGE_EVENTS_CATEGORY == 30

    def test_min_triage_events_booster(self):
        assert _MIN_TRIAGE_EVENTS_BOOSTER == 50

    def test_min_error_spike_events(self):
        assert _MIN_ERROR_SPIKE_EVENTS == 10
