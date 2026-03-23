"""Tests for memory_log_analyzer.py --metrics and --watch modes (Phase 3).

Covers:
- compute_metrics(): pure function, all 5 metric categories
- format_metrics_text(): human-readable formatting
- _format_watch_line(): single-line event formatting
- CLI integration: --metrics, --watch, --filter flags
- Edge cases: empty events, malformed data, missing fields
"""

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_log_analyzer import (
    compute_metrics,
    format_metrics_text,
    _format_watch_line,
    watch_logs,
    _load_events,
    format_json,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_save_complete(
    duration_ms=2500,
    status="success",
    phase_timing=None,
    timestamp="2026-03-20T14:30:00.123Z",
):
    """Create a save.complete event dict."""
    data = {"status": status}
    if phase_timing is not None:
        data["phase_timing"] = phase_timing
    return {
        "event_type": "save.complete",
        "level": "info",
        "timestamp": timestamp,
        "duration_ms": duration_ms,
        "data": data,
    }


def _make_triage_score(
    triggered=None,
    fire_count=1,
    timestamp="2026-03-20T12:00:00.000Z",
):
    """Create a triage.score event dict with fire_count."""
    if triggered is None:
        triggered = []
    return {
        "event_type": "triage.score",
        "level": "info",
        "timestamp": timestamp,
        "data": {
            "triggered": triggered,
            "fire_count": fire_count,
        },
    }


def _make_generic_event(event_type="retrieval.search", timestamp="2026-03-20T10:00:00.000Z"):
    """Create a generic event dict."""
    return {
        "event_type": event_type,
        "level": "info",
        "timestamp": timestamp,
        "data": {},
    }


# ===========================================================================
# compute_metrics tests
# ===========================================================================

class TestComputeMetrics:
    """Tests for compute_metrics() pure function."""

    def test_empty_events(self):
        """No events -> all metrics empty/zero."""
        m = compute_metrics([])
        assert m["total_events"] == 0
        assert m["save_duration"]["count"] == 0
        assert m["save_duration"]["avg_ms"] is None
        assert m["save_duration"]["p50_ms"] is None
        assert m["save_duration"]["p95_ms"] is None
        assert m["save_duration"]["max_ms"] is None
        assert m["refire_count"]["total_sessions"] == 0
        assert m["refire_count"]["avg_fire_count"] is None
        assert m["category_triggers"] == {}
        assert m["save_outcomes"]["success"] == 0
        assert m["save_outcomes"]["success_rate"] is None
        assert m["period"]["start"] == ""
        assert m["period"]["end"] == ""

    def test_total_events_count(self):
        """Total events count matches input length."""
        events = [_make_generic_event() for _ in range(17)]
        m = compute_metrics(events)
        assert m["total_events"] == 17

    def test_period_from_timestamps(self):
        """Period start/end derived from event timestamps."""
        events = [
            _make_generic_event(timestamp="2026-03-18T08:00:00Z"),
            _make_generic_event(timestamp="2026-03-20T16:00:00Z"),
            _make_generic_event(timestamp="2026-03-19T12:00:00Z"),
        ]
        m = compute_metrics(events)
        assert m["period"]["start"] == "2026-03-18"
        assert m["period"]["end"] == "2026-03-20"

    # -- Save Duration --------------------------------------------------

    def test_save_duration_single_event(self):
        """Single save.complete event -> metrics computed."""
        events = [_make_save_complete(duration_ms=3000)]
        m = compute_metrics(events)
        sd = m["save_duration"]
        assert sd["count"] == 1
        assert sd["avg_ms"] == 3000.0
        assert sd["p50_ms"] == 3000.0
        assert sd["p95_ms"] == 3000.0
        assert sd["max_ms"] == 3000.0

    def test_save_duration_multiple_events(self):
        """Multiple save.complete events -> avg, p50, p95, max computed."""
        events = [
            _make_save_complete(duration_ms=500),
            _make_save_complete(duration_ms=1500),
            _make_save_complete(duration_ms=3000),
            _make_save_complete(duration_ms=8000),
            _make_save_complete(duration_ms=25000),
        ]
        m = compute_metrics(events)
        sd = m["save_duration"]
        assert sd["count"] == 5
        assert sd["avg_ms"] == 7600.0  # (500+1500+3000+8000+25000)/5
        assert sd["p50_ms"] == 3000.0  # median of [500, 1500, 3000, 8000, 25000]
        assert sd["max_ms"] == 25000.0

    def test_save_duration_distribution_buckets(self):
        """Duration distribution buckets correctly assigned."""
        events = [
            _make_save_complete(duration_ms=200),     # under_1s
            _make_save_complete(duration_ms=999),     # under_1s
            _make_save_complete(duration_ms=1000),    # 1_5s
            _make_save_complete(duration_ms=4999),    # 1_5s
            _make_save_complete(duration_ms=5000),    # 5_30s
            _make_save_complete(duration_ms=29999),   # 5_30s
            _make_save_complete(duration_ms=30000),   # 30_60s
            _make_save_complete(duration_ms=59999),   # 30_60s
            _make_save_complete(duration_ms=60000),   # over_60s
            _make_save_complete(duration_ms=120000),  # over_60s
        ]
        m = compute_metrics(events)
        dist = m["save_duration"]["distribution"]
        assert dist["under_1s"] == 2
        assert dist["1_5s"] == 2
        assert dist["5_30s"] == 2
        assert dist["30_60s"] == 2
        assert dist["over_60s"] == 2

    def test_save_duration_from_data_field(self):
        """duration_ms read from data dict if not at top level."""
        events = [{
            "event_type": "save.complete",
            "level": "info",
            "timestamp": "2026-03-20T14:00:00Z",
            "data": {"status": "success", "duration_ms": 4200},
        }]
        m = compute_metrics(events)
        assert m["save_duration"]["count"] == 1
        assert m["save_duration"]["avg_ms"] == 4200.0

    def test_save_duration_negative_skipped(self):
        """Negative duration_ms values are skipped."""
        events = [
            _make_save_complete(duration_ms=-100),
            _make_save_complete(duration_ms=2000),
        ]
        m = compute_metrics(events)
        assert m["save_duration"]["count"] == 1
        assert m["save_duration"]["avg_ms"] == 2000.0

    def test_save_duration_none_skipped(self):
        """None duration_ms values are skipped."""
        events = [_make_save_complete(duration_ms=None)]
        # Event has no duration_ms anywhere useful
        events[0].pop("duration_ms")
        events[0]["data"].pop("status")
        events[0]["data"] = {}
        m = compute_metrics(events)
        assert m["save_duration"]["count"] == 0

    # -- Re-fire Count --------------------------------------------------

    def test_refire_distribution(self):
        """Fire count distribution correctly bucketed."""
        events = [
            _make_triage_score(fire_count=1),
            _make_triage_score(fire_count=1),
            _make_triage_score(fire_count=2),
            _make_triage_score(fire_count=3),
            _make_triage_score(fire_count=5),
        ]
        m = compute_metrics(events)
        rf = m["refire_count"]
        assert rf["total_sessions"] == 5
        assert rf["distribution"]["1"] == 2
        assert rf["distribution"]["2"] == 1
        assert rf["distribution"]["3_plus"] == 2
        assert rf["avg_fire_count"] == 2.4  # (1+1+2+3+5)/5

    def test_refire_no_fire_count(self):
        """Triage events without fire_count -> not counted."""
        events = [{
            "event_type": "triage.score",
            "level": "info",
            "timestamp": "2026-03-20T12:00:00Z",
            "data": {"triggered": []},
        }]
        m = compute_metrics(events)
        assert m["refire_count"]["total_sessions"] == 0
        assert m["refire_count"]["avg_fire_count"] is None

    def test_refire_non_numeric_skipped(self):
        """Non-numeric fire_count values are skipped."""
        events = [{
            "event_type": "triage.score",
            "level": "info",
            "timestamp": "2026-03-20T12:00:00Z",
            "data": {"fire_count": "invalid", "triggered": []},
        }]
        m = compute_metrics(events)
        assert m["refire_count"]["total_sessions"] == 0

    # -- Category Triggers ----------------------------------------------

    def test_category_trigger_frequency(self):
        """Category trigger counts and rates computed correctly."""
        events = [
            _make_triage_score(triggered=[
                {"category": "DECISION", "score": 8},
                {"category": "RUNBOOK", "score": 7},
            ]),
            _make_triage_score(triggered=[
                {"category": "DECISION", "score": 9},
            ]),
            _make_triage_score(triggered=[]),  # no triggers
        ]
        m = compute_metrics(events)
        ct = m["category_triggers"]
        assert ct["DECISION"]["count"] == 2
        assert ct["DECISION"]["rate"] == round(2 / 3, 4)
        assert ct["RUNBOOK"]["count"] == 1
        assert ct["RUNBOOK"]["rate"] == round(1 / 3, 4)

    def test_category_trigger_string_format(self):
        """Triggered items as plain strings (not dicts) are also counted."""
        events = [
            {
                "event_type": "triage.score",
                "level": "info",
                "timestamp": "2026-03-20T12:00:00Z",
                "data": {
                    "triggered": ["DECISION", "CONSTRAINT"],
                    "fire_count": 1,
                },
            },
        ]
        m = compute_metrics(events)
        ct = m["category_triggers"]
        assert ct["DECISION"]["count"] == 1
        assert ct["CONSTRAINT"]["count"] == 1

    def test_category_trigger_empty(self):
        """No triggers -> empty category_triggers dict."""
        events = [_make_triage_score(triggered=[])]
        m = compute_metrics(events)
        assert m["category_triggers"] == {}

    # -- Save Outcomes --------------------------------------------------

    def test_save_outcomes_counts(self):
        """Success/failure counts and rate computed correctly."""
        events = [
            _make_save_complete(status="success"),
            _make_save_complete(status="success"),
            _make_save_complete(status="success"),
            _make_save_complete(status="partial_failure"),
            _make_save_complete(status="total_failure"),
        ]
        m = compute_metrics(events)
        so = m["save_outcomes"]
        assert so["success"] == 3
        assert so["partial_failure"] == 1
        assert so["total_failure"] == 1
        assert so["success_rate"] == 0.6  # 3/5

    def test_save_outcomes_all_success(self):
        """All success -> 100% success rate."""
        events = [_make_save_complete(status="success") for _ in range(10)]
        m = compute_metrics(events)
        assert m["save_outcomes"]["success_rate"] == 1.0

    def test_save_outcomes_unknown_status(self):
        """Unknown status values are not counted in any bucket."""
        events = [_make_save_complete(status="unknown_status")]
        m = compute_metrics(events)
        so = m["save_outcomes"]
        assert so["success"] == 0
        assert so["partial_failure"] == 0
        assert so["total_failure"] == 0
        assert so["success_rate"] is None

    def test_save_outcomes_no_data(self):
        """No save.complete events -> all zeros, None rate."""
        events = [_make_generic_event()]
        m = compute_metrics(events)
        so = m["save_outcomes"]
        assert so["success"] == 0
        assert so["success_rate"] is None

    # -- Phase Timing ---------------------------------------------------

    def test_phase_timing_present(self):
        """Phase timing averages computed from save.complete events."""
        events = [
            _make_save_complete(
                phase_timing={"triage_ms": 100, "orchestrate_ms": 200, "write_ms": 300},
            ),
            _make_save_complete(
                phase_timing={"triage_ms": 200, "orchestrate_ms": 400, "write_ms": 600},
            ),
        ]
        m = compute_metrics(events)
        pt = m["phase_timing"]
        assert pt["avg_triage_ms"] == 150.0
        assert pt["avg_orchestrate_ms"] == 300.0
        assert pt["avg_write_ms"] == 450.0

    def test_phase_timing_missing(self):
        """No phase_timing in events -> all None."""
        events = [_make_save_complete()]
        m = compute_metrics(events)
        pt = m["phase_timing"]
        assert pt["avg_triage_ms"] is None
        assert pt["avg_orchestrate_ms"] is None
        assert pt["avg_write_ms"] is None

    def test_phase_timing_partial(self):
        """Partial phase_timing -> only present fields averaged."""
        events = [
            _make_save_complete(
                phase_timing={"triage_ms": 100},
            ),
        ]
        m = compute_metrics(events)
        pt = m["phase_timing"]
        assert pt["avg_triage_ms"] == 100.0
        assert pt["avg_orchestrate_ms"] is None
        assert pt["avg_write_ms"] is None

    def test_phase_timing_negative_skipped(self):
        """Negative phase timing values are skipped."""
        events = [
            _make_save_complete(
                phase_timing={"triage_ms": -50, "orchestrate_ms": 200, "write_ms": 300},
            ),
        ]
        m = compute_metrics(events)
        pt = m["phase_timing"]
        assert pt["avg_triage_ms"] is None  # -50 is skipped
        assert pt["avg_orchestrate_ms"] == 200.0
        assert pt["avg_write_ms"] == 300.0

    # -- Output structure -----------------------------------------------

    def test_output_keys_present(self):
        """All required top-level keys present in output."""
        m = compute_metrics([])
        expected_keys = {
            "period", "total_events", "save_duration",
            "refire_count", "category_triggers", "save_outcomes",
            "phase_timing",
        }
        assert set(m.keys()) >= expected_keys

    def test_output_json_serializable(self):
        """Metrics output is fully JSON-serializable."""
        events = [
            _make_save_complete(duration_ms=2000, status="success",
                                phase_timing={"triage_ms": 100}),
            _make_triage_score(triggered=[{"category": "DECISION", "score": 8}],
                               fire_count=2),
        ]
        m = compute_metrics(events)
        # Should not raise
        result = json.dumps(m)
        assert isinstance(result, str)

    # -- Malformed data resilience --------------------------------------

    def test_malformed_data_field(self):
        """Events with non-dict data field are handled gracefully."""
        events = [{
            "event_type": "save.complete",
            "level": "info",
            "timestamp": "2026-03-20T14:00:00Z",
            "duration_ms": 1000,
            "data": "not a dict",
        }]
        m = compute_metrics(events)
        # Should still count duration_ms from top level
        assert m["save_duration"]["count"] == 1
        # But status won't be extracted
        assert m["save_outcomes"]["success"] == 0

    def test_missing_timestamp(self):
        """Events with missing timestamp don't crash period calculation."""
        events = [
            {"event_type": "save.complete", "level": "info", "data": {"status": "success"},
             "duration_ms": 1000},
        ]
        m = compute_metrics(events)
        assert m["total_events"] == 1

    def test_mixed_event_types(self):
        """Mixed event types are correctly separated into metrics."""
        events = [
            _make_save_complete(duration_ms=1000, status="success"),
            _make_triage_score(triggered=[{"category": "DECISION", "score": 8}],
                               fire_count=1),
            _make_generic_event("retrieval.search"),
            _make_generic_event("retrieval.inject"),
        ]
        m = compute_metrics(events)
        assert m["total_events"] == 4
        assert m["save_duration"]["count"] == 1
        assert m["refire_count"]["total_sessions"] == 1
        assert m["category_triggers"]["DECISION"]["count"] == 1
        assert m["save_outcomes"]["success"] == 1


# ===========================================================================
# format_metrics_text tests
# ===========================================================================

class TestFormatMetricsText:
    """Tests for format_metrics_text() human-readable formatter."""

    def test_basic_output_structure(self):
        """Output contains expected section headers."""
        m = compute_metrics([])
        text = format_metrics_text(m)
        assert "Operational Metrics" in text
        assert "Save Flow Duration" in text
        assert "Re-fire Count" in text
        assert "Category Trigger Frequency" in text
        assert "Save Outcomes" in text
        assert "Phase Timing" in text

    def test_empty_metrics_no_crash(self):
        """Formatting empty metrics does not crash."""
        m = compute_metrics([])
        text = format_metrics_text(m)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_populated_metrics(self):
        """Formatting populated metrics includes actual values."""
        events = [
            _make_save_complete(duration_ms=2000, status="success",
                                phase_timing={"triage_ms": 100, "orchestrate_ms": 200, "write_ms": 300}),
            _make_triage_score(triggered=[{"category": "DECISION", "score": 8}],
                               fire_count=2),
        ]
        m = compute_metrics(events)
        text = format_metrics_text(m)
        assert "2000.0ms" in text
        assert "DECISION" in text
        assert "100.0ms" in text

    def test_no_data_messages(self):
        """Empty sections show 'no data found' messages."""
        m = compute_metrics([])
        text = format_metrics_text(m)
        assert "No save.complete events found." in text
        assert "No triage.score events with fire_count found." in text
        assert "No category triggers found." in text
        assert "No save outcome data found." in text
        assert "No phase timing data found." in text

    def test_json_format_metrics(self):
        """format_json works on metrics output."""
        m = compute_metrics([_make_save_complete()])
        json_str = format_json(m)
        parsed = json.loads(json_str)
        assert "save_duration" in parsed
        assert "refire_count" in parsed


# ===========================================================================
# _format_watch_line tests
# ===========================================================================

class TestFormatWatchLine:
    """Tests for _format_watch_line() single-line formatting."""

    def test_basic_format(self):
        """Standard event produces expected format."""
        entry = {
            "timestamp": "2026-03-20T14:30:45.123Z",
            "level": "info",
            "event_type": "retrieval.search",
            "data": {"match_count": 5},
        }
        line = _format_watch_line(entry)
        assert "[14:30:45]" in line
        assert "[INFO   ]" in line
        assert "retrieval.search" in line
        assert "match_count=5" in line

    def test_error_event_with_message(self):
        """Error events show truncated error message."""
        entry = {
            "timestamp": "2026-03-20T14:30:45.123Z",
            "level": "error",
            "event_type": "save.error",
            "data": {},
            "error": {"error_type": "IOError", "message": "Permission denied"},
        }
        line = _format_watch_line(entry)
        assert "[ERROR  ]" in line
        assert "Permission denied" in line

    def test_duration_shown(self):
        """duration_ms at top level is displayed."""
        entry = {
            "timestamp": "2026-03-20T14:30:45.123Z",
            "level": "info",
            "event_type": "save.complete",
            "duration_ms": 3456,
            "data": {"status": "success"},
        }
        line = _format_watch_line(entry)
        assert "duration=3456ms" in line
        assert "status=success" in line

    def test_missing_timestamp(self):
        """Missing timestamp uses placeholder."""
        entry = {
            "level": "info",
            "event_type": "test.event",
            "data": {},
        }
        line = _format_watch_line(entry)
        assert "[??:??:??]" in line

    def test_short_timestamp(self):
        """Short timestamp uses placeholder."""
        entry = {
            "timestamp": "2026",
            "level": "info",
            "event_type": "test.event",
            "data": {},
        }
        line = _format_watch_line(entry)
        assert "[??:??:??]" in line

    def test_no_data_fields(self):
        """Event with empty data produces clean line."""
        entry = {
            "timestamp": "2026-03-20T14:30:45.123Z",
            "level": "info",
            "event_type": "test.event",
            "data": {},
        }
        line = _format_watch_line(entry)
        assert "test.event" in line
        # No trailing data fields
        assert line.endswith("test.event")

    def test_non_dict_data(self):
        """Non-dict data field doesn't crash."""
        entry = {
            "timestamp": "2026-03-20T14:30:45.123Z",
            "level": "info",
            "event_type": "test.event",
            "data": "not a dict",
        }
        line = _format_watch_line(entry)
        assert "test.event" in line


# ===========================================================================
# watch_logs tests (short-running via mock)
# ===========================================================================

class TestWatchLogs:
    """Tests for watch_logs() -- uses mocked time.sleep and KeyboardInterrupt."""

    def test_watch_no_logs_dir(self, tmp_path, capsys):
        """watch_logs with no logs/ dir prints error and returns."""
        watch_logs(tmp_path, event_filter=None)
        captured = capsys.readouterr()
        assert "No logs directory" in captured.err

    def test_watch_reads_existing_events(self, tmp_path, capsys):
        """watch_logs reads existing events from today's log files."""
        logs_dir = tmp_path / "logs" / "save"
        logs_dir.mkdir(parents=True)

        today = time.strftime("%Y-%m-%d", time.gmtime())
        event = {
            "event_type": "save.complete",
            "level": "info",
            "timestamp": f"{today}T14:30:00.000Z",
            "data": {"status": "success"},
        }
        log_file = logs_dir / f"{today}.jsonl"
        log_file.write_text(json.dumps(event) + "\n")

        # Mock time.sleep to raise KeyboardInterrupt after first iteration
        call_count = [0]

        def mock_sleep(secs):
            call_count[0] += 1
            if call_count[0] >= 1:
                raise KeyboardInterrupt

        with patch("memory_log_analyzer.time.sleep", side_effect=mock_sleep):
            watch_logs(tmp_path, event_filter=None)

        captured = capsys.readouterr()
        assert "save.complete" in captured.out
        assert "status=success" in captured.out

    def test_watch_filter_events(self, tmp_path, capsys):
        """watch_logs with --filter only shows matching events."""
        logs_dir = tmp_path / "logs" / "save"
        logs_dir.mkdir(parents=True)
        triage_dir = tmp_path / "logs" / "triage"
        triage_dir.mkdir(parents=True)

        today = time.strftime("%Y-%m-%d", time.gmtime())

        save_event = {
            "event_type": "save.complete",
            "level": "info",
            "timestamp": f"{today}T14:30:00.000Z",
            "data": {"status": "success"},
        }
        triage_event = {
            "event_type": "triage.score",
            "level": "info",
            "timestamp": f"{today}T14:30:00.000Z",
            "data": {"fire_count": 1},
        }

        (logs_dir / f"{today}.jsonl").write_text(json.dumps(save_event) + "\n")
        (triage_dir / f"{today}.jsonl").write_text(json.dumps(triage_event) + "\n")

        call_count = [0]

        def mock_sleep(secs):
            call_count[0] += 1
            if call_count[0] >= 1:
                raise KeyboardInterrupt

        with patch("memory_log_analyzer.time.sleep", side_effect=mock_sleep):
            watch_logs(tmp_path, event_filter="save")

        captured = capsys.readouterr()
        assert "save.complete" in captured.out
        assert "triage.score" not in captured.out

    def test_watch_skips_malformed_lines(self, tmp_path, capsys):
        """watch_logs skips malformed JSONL lines without crashing."""
        logs_dir = tmp_path / "logs" / "save"
        logs_dir.mkdir(parents=True)

        today = time.strftime("%Y-%m-%d", time.gmtime())
        good_event = json.dumps({
            "event_type": "save.start",
            "level": "info",
            "timestamp": f"{today}T14:30:00.000Z",
            "data": {},
        })
        content = "this is not valid json\n" + good_event + "\n"
        (logs_dir / f"{today}.jsonl").write_text(content)

        call_count = [0]

        def mock_sleep(secs):
            call_count[0] += 1
            if call_count[0] >= 1:
                raise KeyboardInterrupt

        with patch("memory_log_analyzer.time.sleep", side_effect=mock_sleep):
            watch_logs(tmp_path, event_filter=None)

        captured = capsys.readouterr()
        assert "save.start" in captured.out

    def test_watch_skips_symlink_dirs(self, tmp_path, capsys):
        """watch_logs skips symlinked category directories."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)

        # Create a real dir and a symlink to it
        real_dir = tmp_path / "real_data"
        real_dir.mkdir()
        symlink_dir = logs_dir / "evil"
        symlink_dir.symlink_to(real_dir)

        call_count = [0]

        def mock_sleep(secs):
            call_count[0] += 1
            if call_count[0] >= 1:
                raise KeyboardInterrupt

        with patch("memory_log_analyzer.time.sleep", side_effect=mock_sleep):
            watch_logs(tmp_path, event_filter=None)

        # Should not crash
        captured = capsys.readouterr()
        assert "Watch stopped" in captured.err


# ===========================================================================
# CLI integration tests
# ===========================================================================

class TestCLIMetrics:
    """CLI --metrics integration tests."""

    def test_metrics_flag_accepted(self, tmp_path):
        """--metrics flag is accepted and produces output."""
        logs_dir = tmp_path / "logs" / "save"
        logs_dir.mkdir(parents=True)

        today = time.strftime("%Y-%m-%d", time.gmtime())
        event = {
            "event_type": "save.complete",
            "level": "info",
            "timestamp": f"{today}T14:00:00.000Z",
            "duration_ms": 2500,
            "data": {"status": "success"},
        }
        (logs_dir / f"{today}.jsonl").write_text(json.dumps(event) + "\n")

        import subprocess
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "hooks" / "scripts" / "memory_log_analyzer.py"),
                "--root", str(tmp_path),
                "--metrics",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Save Flow Duration" in result.stdout

    def test_metrics_json_output(self, tmp_path):
        """--metrics --format json produces valid JSON."""
        logs_dir = tmp_path / "logs" / "save"
        logs_dir.mkdir(parents=True)

        today = time.strftime("%Y-%m-%d", time.gmtime())
        event = {
            "event_type": "save.complete",
            "level": "info",
            "timestamp": f"{today}T14:00:00.000Z",
            "duration_ms": 2500,
            "data": {"status": "success"},
        }
        (logs_dir / f"{today}.jsonl").write_text(json.dumps(event) + "\n")

        import subprocess
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "hooks" / "scripts" / "memory_log_analyzer.py"),
                "--root", str(tmp_path),
                "--metrics",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert "save_duration" in parsed
        assert "refire_count" in parsed

    def test_metrics_empty_logs(self, tmp_path):
        """--metrics with no data returns empty metrics, not error."""
        (tmp_path / "logs").mkdir()

        import subprocess
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "hooks" / "scripts" / "memory_log_analyzer.py"),
                "--root", str(tmp_path),
                "--metrics",
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert parsed["total_events"] == 0

    def test_existing_analyze_mode_unchanged(self, tmp_path):
        """Default mode (no --metrics) still works as before."""
        (tmp_path / "logs").mkdir()

        import subprocess
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "hooks" / "scripts" / "memory_log_analyzer.py"),
                "--root", str(tmp_path),
                "--format", "json",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # NO_DATA finding => exit code 0 (warning, not critical)
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert "findings" in parsed
        assert parsed["findings"][0]["code"] == "NO_DATA"


# ===========================================================================
# Edge case / integration tests for compute_metrics
# ===========================================================================

class TestComputeMetricsEdgeCases:
    """Edge cases for compute_metrics."""

    def test_string_duration_skipped(self):
        """String duration_ms values are skipped."""
        events = [{
            "event_type": "save.complete",
            "level": "info",
            "timestamp": "2026-03-20T14:00:00Z",
            "duration_ms": "not_a_number",
            "data": {"status": "success"},
        }]
        m = compute_metrics(events)
        assert m["save_duration"]["count"] == 0

    def test_zero_duration_counted(self):
        """duration_ms=0 is valid and counted."""
        events = [_make_save_complete(duration_ms=0)]
        m = compute_metrics(events)
        assert m["save_duration"]["count"] == 1
        assert m["save_duration"]["avg_ms"] == 0.0

    def test_large_event_set(self):
        """Handles large event sets without error."""
        events = [
            _make_save_complete(duration_ms=i * 100, status="success")
            for i in range(1000)
        ]
        m = compute_metrics(events)
        assert m["save_duration"]["count"] == 1000
        assert m["save_outcomes"]["success"] == 1000

    def test_p95_with_two_events(self):
        """p95 computable with exactly 2 data points."""
        events = [
            _make_save_complete(duration_ms=100),
            _make_save_complete(duration_ms=200),
        ]
        m = compute_metrics(events)
        assert m["save_duration"]["p95_ms"] is not None

    def test_non_dict_triggered_items_skipped(self):
        """Non-dict, non-string triggered items are silently skipped."""
        events = [{
            "event_type": "triage.score",
            "level": "info",
            "timestamp": "2026-03-20T12:00:00Z",
            "data": {
                "triggered": [42, None, True],
                "fire_count": 1,
            },
        }]
        m = compute_metrics(events)
        assert m["category_triggers"] == {}

    def test_phase_timing_non_dict_skipped(self):
        """Non-dict phase_timing is skipped gracefully."""
        events = [_make_save_complete(phase_timing="bad")]
        m = compute_metrics(events)
        pt = m["phase_timing"]
        assert pt["avg_triage_ms"] is None

    def test_phase_timing_string_values_skipped(self):
        """String values in phase_timing are skipped."""
        events = [_make_save_complete(
            phase_timing={"triage_ms": "fast", "orchestrate_ms": 200, "write_ms": 300},
        )]
        m = compute_metrics(events)
        pt = m["phase_timing"]
        assert pt["avg_triage_ms"] is None
        assert pt["avg_orchestrate_ms"] == 200.0
