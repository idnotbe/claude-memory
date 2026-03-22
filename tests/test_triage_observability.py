"""Tests for triage observability features (Phase 1).

Covers:
- Step 1.1: fire_count in triage.score log event
- Step 1.2: session_id propagation in all events
- Step 1.3: triage.idempotency_skip events for guard short-circuits
- _increment_fire_count edge cases
"""

import io
import json
import os
import stat
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from memory_triage import (
    _increment_fire_count,
    _run_triage,
    check_stop_flag,
    set_stop_flag,
)
from memory_staging_utils import get_staging_dir, ensure_staging_dir


# ---------------------------------------------------------------------------
# Helpers (mirrors patterns from test_memory_triage.py)
# ---------------------------------------------------------------------------

def _user_msg(content, nested=True):
    if nested:
        return {"type": "user", "message": {"role": "user", "content": content}}
    return {"type": "human", "content": content}


def _assistant_msg(content, nested=True):
    if nested:
        return {"type": "assistant", "message": {"role": "assistant", "content": content}}
    return {"type": "assistant", "content": content}


def _write_transcript(tmp_path, messages, filename="transcript.jsonl"):
    path = tmp_path / filename
    lines = [json.dumps(m) for m in messages]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def _write_config(tmp_path, config_data=None):
    """Write memory-config.json and return project root path."""
    proj = tmp_path / "proj"
    mem_dir = proj / ".claude" / "memory"
    mem_dir.mkdir(parents=True, exist_ok=True)
    cfg = config_data or {"triage": {"enabled": True}}
    (mem_dir / "memory-config.json").write_text(
        json.dumps(cfg), encoding="utf-8"
    )
    return str(proj)


def _build_decision_transcript(tmp_path):
    """Build a transcript that triggers DECISION category."""
    messages = [
        _user_msg("We need to pick a database for the new service."),
        _assistant_msg([
            {"type": "text", "text": (
                "I decided to go with PostgreSQL because it has "
                "better JSONB support. We chose PostgreSQL over MySQL "
                "due to the advanced indexing capabilities."
            )},
        ]),
    ]
    # Add enough exchanges to also trigger SESSION_SUMMARY
    for i in range(10):
        messages.append(_user_msg(f"Continue step {i}"))
        messages.append(_assistant_msg([
            {"type": "text", "text": f"Working on step {i}..."},
            {"type": "tool_use", "name": "Edit", "input": {}},
        ]))
    return _write_transcript(tmp_path, messages)


def _hook_input(transcript_path, cwd):
    return json.dumps({
        "transcript_path": transcript_path,
        "cwd": cwd,
    })


# ---------------------------------------------------------------------------
# _increment_fire_count unit tests
# ---------------------------------------------------------------------------


class TestIncrementFireCount:
    """Tests for _increment_fire_count()."""

    def test_first_invocation_returns_one(self, tmp_path):
        """First call on a fresh staging dir returns 1."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        result = _increment_fire_count(cwd)
        assert result == 1

    def test_increments_on_successive_calls(self, tmp_path):
        """Successive calls should return incrementing values."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        r1 = _increment_fire_count(cwd)
        r2 = _increment_fire_count(cwd)
        r3 = _increment_fire_count(cwd)
        assert r1 == 1
        assert r2 == 2
        assert r3 == 3

    def test_corrupted_counter_resets_to_one(self, tmp_path):
        """Corrupted (non-numeric) counter file should reset to 1."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        staging = ensure_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        with open(counter_path, "w") as f:
            f.write("not_a_number")
        result = _increment_fire_count(cwd)
        assert result == 1

    def test_negative_counter_clamps_to_one(self, tmp_path):
        """Negative counter value should be clamped to 0, then increment to 1."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        staging = ensure_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        with open(counter_path, "w") as f:
            f.write("-10")
        result = _increment_fire_count(cwd)
        assert result == 1

    def test_empty_counter_file_returns_one(self, tmp_path):
        """Empty counter file should reset to 1."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        staging = ensure_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        with open(counter_path, "w") as f:
            f.write("")
        result = _increment_fire_count(cwd)
        assert result == 1

    def test_fail_open_on_exception(self, tmp_path):
        """If ensure_staging_dir raises, should return 0 (fail-open)."""
        with mock.patch("memory_triage.ensure_staging_dir", side_effect=RuntimeError("boom")), \
             mock.patch("memory_triage.get_staging_dir", side_effect=RuntimeError("boom")):
            result = _increment_fire_count(str(tmp_path))
        assert result == 0

    def test_counter_file_symlink_rejected(self, tmp_path):
        """Symlink counter file should be rejected by O_NOFOLLOW."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        staging = ensure_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        target = os.path.join(staging, ".counter-target")
        with open(target, "w") as f:
            f.write("5")
        os.symlink(target, counter_path)
        # O_NOFOLLOW causes OSError on both read and write, outer except returns 0
        result = _increment_fire_count(cwd)
        assert result == 0
        # Verify symlink target was not modified (symlink not followed)
        with open(target, "r") as f:
            assert f.read() == "5"

    def test_fifo_rejected_by_fstat(self, tmp_path):
        """FIFO at counter path should be rejected by fstat check."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        staging = ensure_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        os.mkfifo(counter_path)
        # fstat should detect non-regular file and return 0
        result = _increment_fire_count(cwd)
        assert result == 0


# ---------------------------------------------------------------------------
# triage.idempotency_skip logging tests
# ---------------------------------------------------------------------------


class TestIdempotencySkipLogging:
    """Tests for triage.idempotency_skip emit_event calls."""

    def test_stop_flag_guard_emits_skip(self, tmp_path):
        """When stop_flag guard triggers, should emit idempotency_skip with guard='stop_flag'."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=True), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            exit_code = _run_triage()

        assert exit_code == 0
        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        assert len(skip_calls) == 1
        data = skip_calls[0][0][1]
        assert data["guard"] == "stop_flag"
        assert data["fire_count"] == 1
        kwargs = skip_calls[0][1]
        assert kwargs["session_id"] != ""
        assert kwargs["hook"] == "Stop"
        assert kwargs["script"] == "memory_triage.py"

    def test_sentinel_guard_emits_skip(self, tmp_path):
        """When sentinel guard triggers, should emit idempotency_skip with guard='sentinel'."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.check_sentinel_session", return_value=True), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            exit_code = _run_triage()

        assert exit_code == 0
        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        assert len(skip_calls) == 1
        data = skip_calls[0][0][1]
        assert data["guard"] == "sentinel"

    def test_save_result_guard_emits_skip(self, tmp_path):
        """When save_result guard triggers, should emit idempotency_skip with guard='save_result'."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.check_sentinel_session", return_value=False), \
             mock.patch("memory_triage._check_save_result_guard", return_value=True), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            exit_code = _run_triage()

        assert exit_code == 0
        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        assert len(skip_calls) == 1
        data = skip_calls[0][0][1]
        assert data["guard"] == "save_result"

    def test_lock_held_guard_emits_skip(self, tmp_path):
        """When lock is held by another process, should emit idempotency_skip with guard='lock_held'."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.check_sentinel_session", return_value=False), \
             mock.patch("memory_triage._check_save_result_guard", return_value=False), \
             mock.patch("memory_triage._acquire_triage_lock", return_value=("", "held")), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            exit_code = _run_triage()

        assert exit_code == 0
        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        assert len(skip_calls) == 1
        data = skip_calls[0][0][1]
        assert data["guard"] == "lock_held"

    def test_sentinel_recheck_guard_emits_skip(self, tmp_path):
        """When sentinel re-check under lock triggers, should emit with guard='sentinel_recheck'."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        # First sentinel check returns False, but re-check under lock returns True
        sentinel_calls = iter([False, True])

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.check_sentinel_session", side_effect=lambda *a: next(sentinel_calls)), \
             mock.patch("memory_triage._check_save_result_guard", return_value=False), \
             mock.patch("memory_triage._acquire_triage_lock", return_value=("/tmp/lock", "acquired")), \
             mock.patch("memory_triage._release_triage_lock"), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            exit_code = _run_triage()

        assert exit_code == 0
        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        assert len(skip_calls) == 1
        data = skip_calls[0][0][1]
        assert data["guard"] == "sentinel_recheck"

    def test_no_skip_event_on_normal_triage(self, tmp_path):
        """Normal triage (no guards triggered) should NOT emit idempotency_skip."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        assert len(skip_calls) == 0
        # Verify scoring path was reached (not an early exit)
        score_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.score"
        ]
        assert len(score_calls) == 1

    def test_skip_event_includes_session_id(self, tmp_path):
        """All idempotency_skip events must include session_id kwarg."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=True), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        assert len(skip_calls) == 1
        kwargs = skip_calls[0][1]
        assert "session_id" in kwargs
        # session_id should be derived from transcript filename
        assert kwargs["session_id"] == "transcript"


# ---------------------------------------------------------------------------
# fire_count in triage.score tests
# ---------------------------------------------------------------------------


class TestFireCountInTriageScore:
    """Tests for fire_count field in triage.score emit_event."""

    def test_triage_score_includes_fire_count(self, tmp_path):
        """triage.score event data should include fire_count == 1 on fresh workspace."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        score_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.score"
        ]
        assert len(score_calls) == 1
        data = score_calls[0][0][1]
        assert "fire_count" in data
        assert isinstance(data["fire_count"], int)
        assert data["fire_count"] == 1

    def test_fire_count_in_skip_event_matches(self, tmp_path):
        """fire_count in idempotency_skip should match the counter value."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=True), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        assert len(skip_calls) == 1
        data = skip_calls[0][0][1]
        assert data["fire_count"] == 1

    def test_triage_score_session_id(self, tmp_path):
        """triage.score event should include session_id kwarg."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        score_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.score"
        ]
        assert len(score_calls) == 1
        kwargs = score_calls[0][1]
        assert kwargs["session_id"] == "transcript"


# ---------------------------------------------------------------------------
# Logging disabled / fail-open tests
# ---------------------------------------------------------------------------


class TestObservabilityFailOpen:
    """Ensure observability code doesn't break triage when logging is disabled or errors."""

    def test_runs_with_logging_disabled(self, tmp_path):
        """Triage should work normally even when logging is explicitly disabled."""
        cwd = _write_config(tmp_path, {
            "triage": {"enabled": True},
            "logging": {"enabled": False},
        })
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        captured_out = io.StringIO()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("memory_triage.check_stop_flag", return_value=False):
            exit_code = _run_triage()

        assert exit_code == 0
        # Should still produce blocking output (triage logic unaffected)
        stdout_text = captured_out.getvalue().strip()
        assert stdout_text, "Expected block output but got empty stdout"
        response = json.loads(stdout_text)
        assert response["decision"] == "block"

    def test_emit_event_failure_doesnt_break_main(self, tmp_path):
        """If emit_event raises inside main(), the outer handler catches it."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        def raising_emit(*args, **kwargs):
            raise RuntimeError("logging broken")

        captured_out = io.StringIO()
        # main() has its own try/except around _run_triage()
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", captured_out), \
             mock.patch("sys.stderr", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.emit_event", side_effect=raising_emit):
            from memory_triage import main
            exit_code = main()

        # main() catches all exceptions and returns 0 (fail-open)
        assert exit_code == 0

    def test_increment_fire_count_failure_doesnt_block(self, tmp_path):
        """If _increment_fire_count fails, triage should proceed with fire_count=0."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage._increment_fire_count", return_value=0), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            exit_code = _run_triage()

        assert exit_code == 0
        score_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.score"
        ]
        assert len(score_calls) == 1
        assert score_calls[0][0][1]["fire_count"] == 0


# ---------------------------------------------------------------------------
# Gap 1, 8, 9, 11, 12: fire_count edge cases
# ---------------------------------------------------------------------------


class TestFireCountEdgeCases:
    """Tests for _increment_fire_count edge cases not covered by TestIncrementFireCount."""

    def test_different_cwds_have_independent_counters(self, tmp_path):
        """Different cwd values produce independent counters via staging dir hash (Gap 1)."""
        cwd_a = str(tmp_path / "workspace_a")
        cwd_b = str(tmp_path / "workspace_b")
        os.makedirs(cwd_a, exist_ok=True)
        os.makedirs(cwd_b, exist_ok=True)

        # Increment workspace A three times
        a1 = _increment_fire_count(cwd_a)
        a2 = _increment_fire_count(cwd_a)
        a3 = _increment_fire_count(cwd_a)

        # Increment workspace B once
        b1 = _increment_fire_count(cwd_b)

        # A should be at 3, B should be at 1 (independent)
        assert a1 == 1
        assert a2 == 2
        assert a3 == 3
        assert b1 == 1

    def test_counter_file_large_content_truncated(self, tmp_path):
        """Counter file >64 bytes is safely truncated by os.read(fd, 64) (Gap 8).

        Uses digit padding so truncation changes the parsed value — a space-padded
        payload would strip identically whether or not truncation occurs.
        """
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        staging = ensure_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        # Write "42" followed by 100 zeroes (102 bytes total).
        # With 64-byte truncation: reads "42" + "0"*62 -> int("42"+"0"*62) + 1
        # Without truncation: would read "42" + "0"*100 -> much larger number
        with open(counter_path, "w") as f:
            f.write("42" + "0" * 100)
        result = _increment_fire_count(cwd)
        truncated_value = int("42" + "0" * 62)
        assert result == truncated_value + 1

    def test_counter_file_permissions_0600(self, tmp_path):
        """Counter file should be created with mode 0o600 (Gap 9)."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        _increment_fire_count(cwd)
        staging = get_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        file_mode = os.stat(counter_path).st_mode
        # Extract permission bits only (mask out file type)
        perms = stat.S_IMODE(file_mode)
        assert perms == 0o600

    def test_large_counter_value_increments(self, tmp_path):
        """Large counter value (999999) should increment correctly (Gap 11)."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        staging = ensure_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        with open(counter_path, "w") as f:
            f.write("999999")
        result = _increment_fire_count(cwd)
        assert result == 1000000

    def test_non_utf8_counter_content_resets(self, tmp_path):
        """Binary content in counter file handled gracefully, resets to 1 (Gap 12)."""
        cwd = str(tmp_path / "proj")
        os.makedirs(cwd, exist_ok=True)
        staging = ensure_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        # Write raw binary bytes (not valid UTF-8 number)
        with open(counter_path, "wb") as f:
            f.write(b"\x80\x81\x82\xff\xfe")
        result = _increment_fire_count(cwd)
        # decode(errors="replace") produces replacement chars -> int() fails -> count=0 -> +1 = 1
        assert result == 1


# ---------------------------------------------------------------------------
# Gap 2: Empty session_id bypasses sentinel and save_result guards
# ---------------------------------------------------------------------------


class TestSessionIdGuardBehavior:
    """Tests for empty session_id guard bypass behavior (Gap 2)."""

    def test_empty_session_id_skips_sentinel_guard(self, tmp_path):
        """Empty session_id causes sentinel guard to be skipped entirely (Gap 2a).

        Lines 1500: 'if session_id and check_sentinel_session(...)' -- when
        session_id is empty, check_sentinel_session is never called.
        Also verifies triage continues to the scoring path (not an unrelated early exit).
        """
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.get_session_id", return_value=""), \
             mock.patch("memory_triage.check_sentinel_session", return_value=True) as mock_sentinel, \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        # check_sentinel_session should never be called when session_id is empty
        mock_sentinel.assert_not_called()

        # No sentinel skip event should be emitted
        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip" and c[0][1].get("guard") == "sentinel"
        ]
        assert len(skip_calls) == 0

        # Positive assertion: triage continued to the scoring path
        score_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.score"
        ]
        assert len(score_calls) == 1

    def test_empty_session_id_skips_save_result_guard(self, tmp_path):
        """Empty session_id causes save_result guard to be skipped entirely (Gap 2b).

        Lines 1509: 'if session_id and _check_save_result_guard(...)' -- when
        session_id is empty, _check_save_result_guard is never called.
        Also verifies triage continues to the scoring path (not an unrelated early exit).
        """
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.get_session_id", return_value=""), \
             mock.patch("memory_triage.check_sentinel_session") as mock_sentinel, \
             mock.patch("memory_triage._check_save_result_guard", return_value=True) as mock_save, \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        # Neither guard should be called when session_id is empty
        mock_sentinel.assert_not_called()
        mock_save.assert_not_called()

        # No save_result skip event should be emitted
        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip" and c[0][1].get("guard") == "save_result"
        ]
        assert len(skip_calls) == 0

        # Positive assertion: triage continued to the scoring path
        score_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.score"
        ]
        assert len(score_calls) == 1


# ---------------------------------------------------------------------------
# Gap 3, 7: triage.score event data completeness
# ---------------------------------------------------------------------------


class TestTriageScoreCompleteness:
    """Tests for triage.score event field completeness (Gaps 3, 7)."""

    def test_triage_score_event_data_completeness(self, tmp_path):
        """triage.score event should include all required fields (Gap 3)."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        score_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.score"
        ]
        assert len(score_calls) == 1

        data = score_calls[0][0][1]
        kwargs = score_calls[0][1]

        # All required data fields present with correct types and semantic values
        assert "all_scores" in data
        assert isinstance(data["all_scores"], list)
        assert len(data["all_scores"]) == 6  # one per category
        for entry in data["all_scores"]:
            assert "category" in entry
            assert "score" in entry
        assert "triggered" in data
        assert isinstance(data["triggered"], list)
        assert len(data["triggered"]) > 0  # decision transcript should trigger
        for item in data["triggered"]:
            assert "category" in item
            assert "score" in item
        assert "text_len" in data
        assert isinstance(data["text_len"], int)
        assert data["text_len"] > 0
        assert "exchanges" in data
        assert isinstance(data["exchanges"], int)
        assert "tool_uses" in data
        assert isinstance(data["tool_uses"], int)
        assert "fire_count" in data
        assert isinstance(data["fire_count"], int)
        assert data["fire_count"] == 1

        # Required kwargs
        assert "session_id" in kwargs
        assert "duration_ms" in kwargs
        assert "hook" in kwargs
        assert kwargs["hook"] == "Stop"
        assert "script" in kwargs
        assert kwargs["script"] == "memory_triage.py"
        assert "memory_root" in kwargs
        assert "config" in kwargs

    def test_triage_score_has_positive_duration_ms(self, tmp_path):
        """triage.score duration_ms should be a positive number (Gap 7)."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=False), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        score_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.score"
        ]
        assert len(score_calls) == 1
        kwargs = score_calls[0][1]
        assert kwargs["duration_ms"] is not None
        assert isinstance(kwargs["duration_ms"], float)
        assert kwargs["duration_ms"] > 0


# ---------------------------------------------------------------------------
# Gap 4: Skip events include memory_root and config kwargs
# ---------------------------------------------------------------------------


class TestSkipEventKwargs:
    """Tests for skip event kwargs completeness (Gap 4)."""

    def test_skip_event_includes_memory_root_and_config(self, tmp_path):
        """All idempotency_skip events must include memory_root and config kwargs (Gap 4)."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=True), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            _run_triage()

        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        assert len(skip_calls) == 1
        kwargs = skip_calls[0][1]

        # memory_root should be exactly {cwd}/.claude/memory
        expected_root = os.path.join(cwd, ".claude", "memory")
        assert "memory_root" in kwargs
        assert kwargs["memory_root"] == expected_root

        # config should be the raw config dict (matching what was written)
        assert "config" in kwargs
        assert isinstance(kwargs["config"], dict)


# ---------------------------------------------------------------------------
# Gap 5, 6: Integration-level fire_count tests
# ---------------------------------------------------------------------------


class TestFireCountControlFlow:
    """Control-flow tests for fire_count across _run_triage calls (Gaps 5, 6)."""

    def test_fire_count_increments_across_triage_runs(self, tmp_path):
        """Multiple _run_triage invocations with same cwd show incrementing fire_count (Gap 5)."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        fire_counts = []

        for _ in range(3):
            with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
                 mock.patch("sys.stdout", io.StringIO()), \
                 mock.patch("memory_triage.check_stop_flag", return_value=False), \
                 mock.patch("memory_triage.check_sentinel_session", return_value=False), \
                 mock.patch("memory_triage._check_save_result_guard", return_value=False), \
                 mock.patch("memory_triage._acquire_triage_lock", return_value=("", "acquired")), \
                 mock.patch("memory_triage._release_triage_lock"), \
                 mock.patch("memory_triage.emit_event") as mock_emit:
                _run_triage()

            score_calls = [
                c for c in mock_emit.call_args_list
                if c[0][0] == "triage.score"
            ]
            assert len(score_calls) == 1
            fire_counts.append(score_calls[0][0][1]["fire_count"])

        assert fire_counts == [1, 2, 3]

    def test_first_guard_wins_no_double_skip(self, tmp_path):
        """When multiple guards would trigger, only the first produces a skip event (Gap 6)."""
        cwd = _write_config(tmp_path)
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        # Both stop_flag and sentinel would trigger, but stop_flag is checked first
        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.check_stop_flag", return_value=True), \
             mock.patch("memory_triage.check_sentinel_session", return_value=True) as mock_sentinel, \
             mock.patch("memory_triage.emit_event") as mock_emit:
            exit_code = _run_triage()

        assert exit_code == 0

        skip_calls = [
            c for c in mock_emit.call_args_list
            if c[0][0] == "triage.idempotency_skip"
        ]
        # Only one skip event emitted (not two)
        assert len(skip_calls) == 1
        # The first guard (stop_flag) should be the one reported
        assert skip_calls[0][0][1]["guard"] == "stop_flag"
        # Sentinel guard should never have been reached (short-circuit)
        mock_sentinel.assert_not_called()


# ---------------------------------------------------------------------------
# Gap 10: Disabled triage has no side effects
# ---------------------------------------------------------------------------


class TestDisabledTriageNoSideEffects:
    """Tests that disabled triage produces no side effects (Gap 10)."""

    def test_disabled_triage_does_not_increment_fire_count(self, tmp_path):
        """When triage.enabled=false, no counter file should be created (Gap 10)."""
        cwd = _write_config(tmp_path, {"triage": {"enabled": False}})
        transcript_path = _build_decision_transcript(tmp_path)
        hook_input = _hook_input(transcript_path, cwd)

        with mock.patch("memory_triage.read_stdin", return_value=hook_input), \
             mock.patch("sys.stdout", io.StringIO()), \
             mock.patch("memory_triage.emit_event") as mock_emit:
            exit_code = _run_triage()

        assert exit_code == 0

        # No events should be emitted at all
        assert mock_emit.call_count == 0

        # No counter file should exist in the staging directory
        staging = get_staging_dir(cwd)
        counter_path = os.path.join(staging, ".triage-fire-count")
        assert not os.path.exists(counter_path)
