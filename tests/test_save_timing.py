"""Tests for Phase 2 save-flow timing features.

Covers:
- Group 1: triage_start_ts in build_triage_data
- Group 2: write_save_result accepts phase_timing
- Group 3: execute_saves phase_timing dict
- Group 4: save.start/save.complete log events
- Group 5: Integration (triage -> save timing flow)
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from memory_triage import build_triage_data
from memory_orchestrate import execute_saves
from memory_write import write_save_result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_triage_results(categories=None):
    """Build minimal triage result dicts."""
    cats = categories or ["decision"]
    return [{"category": cat, "score": 0.85} for cat in cats]


def _make_parallel_config():
    """Return a minimal parallel config."""
    return {
        "enabled": True,
        "category_models": {"decision": "sonnet"},
        "verification_model": "haiku",
        "default_model": "haiku",
    }


def _make_all_noop_manifest():
    """Build a manifest where all categories are NOOP."""
    return {"status": "all_noop", "categories": {}}


def _make_actionable_manifest(categories=None):
    """Build an actionable manifest with CREATE actions.

    Each category gets a CREATE action with a draft_path and target_path
    that point to tmp files. The caller is expected to create the draft
    files and mock subprocess.run.
    """
    cats = categories or ["decision"]
    resolved = {}
    for cat in cats:
        resolved[cat] = {
            "action": "CREATE",
            "draft_path": f"/tmp/test-draft-{cat}.json",
            "target_path": f"/tmp/test-target-{cat}.json",
        }
    return {"status": "actionable", "categories": resolved}


def _make_staging_dir(tmp_path, triage_start_ts=None):
    """Create a staging dir under /tmp/ with optional triage-data.json.

    Returns the staging dir path as a string.
    """
    staging = tmp_path / "staging"
    staging.mkdir(exist_ok=True)
    if triage_start_ts is not None:
        td = {"categories": [], "triage_start_ts": triage_start_ts}
        (staging / "triage-data.json").write_text(
            json.dumps(td), encoding="utf-8"
        )
    return str(staging)


def _make_tmp_staging_dir(triage_start_ts=None, suffix="test"):
    """Create a real /tmp/ staging dir that passes write_save_result path validation.

    Returns the staging dir path as a string.
    """
    import tempfile
    resolved_tmp = os.path.realpath("/tmp")
    staging = tempfile.mkdtemp(
        prefix=".claude-memory-staging-", dir=resolved_tmp
    )
    if triage_start_ts is not None:
        td = {"categories": [], "triage_start_ts": triage_start_ts}
        with open(os.path.join(staging, "triage-data.json"), "w") as f:
            json.dump(td, f)
    return staging


# ---------------------------------------------------------------------------
# Group 1: triage_start_ts in build_triage_data
# ---------------------------------------------------------------------------


class TestBuildTriageDataTimestamp:
    """Tests for triage_start_ts parameter in build_triage_data."""

    def test_build_triage_data_includes_triage_start_ts(self):
        """Verify ts is included in output when provided."""
        ts = time.time()
        data = build_triage_data(
            results=_make_triage_results(),
            context_paths={},
            parallel_config=_make_parallel_config(),
            triage_start_ts=ts,
        )
        assert "triage_start_ts" in data
        assert data["triage_start_ts"] == ts

    def test_build_triage_data_omits_triage_start_ts_when_none(self):
        """Verify no triage_start_ts key when None."""
        data = build_triage_data(
            results=_make_triage_results(),
            context_paths={},
            parallel_config=_make_parallel_config(),
            triage_start_ts=None,
        )
        assert "triage_start_ts" not in data

    def test_build_triage_data_handles_non_float_triage_start_ts(self):
        """String and int values are cast to float."""
        # Integer
        data_int = build_triage_data(
            results=_make_triage_results(),
            context_paths={},
            parallel_config=_make_parallel_config(),
            triage_start_ts=12345,
        )
        assert data_int["triage_start_ts"] == 12345.0
        assert isinstance(data_int["triage_start_ts"], float)

        # String that represents a number
        data_str = build_triage_data(
            results=_make_triage_results(),
            context_paths={},
            parallel_config=_make_parallel_config(),
            triage_start_ts="1711111111.5",
        )
        assert data_str["triage_start_ts"] == 1711111111.5
        assert isinstance(data_str["triage_start_ts"], float)

    def test_build_triage_data_handles_invalid_triage_start_ts(self):
        """Invalid value 'not_a_number' is silently skipped (fail-open)."""
        data = build_triage_data(
            results=_make_triage_results(),
            context_paths={},
            parallel_config=_make_parallel_config(),
            triage_start_ts="not_a_number",
        )
        assert "triage_start_ts" not in data


# ---------------------------------------------------------------------------
# Group 2: write_save_result accepts phase_timing
# ---------------------------------------------------------------------------


class TestWriteSaveResultPhaseTiming:
    """Tests for phase_timing validation in write_save_result."""

    def _make_result_json(self, phase_timing=None, include_key=True):
        """Build a valid save result JSON string."""
        data = {
            "saved_at": "2026-03-24T10:00:00Z",
            "categories": ["decision"],
            "titles": ["Test Decision"],
            "errors": [],
        }
        if include_key and phase_timing is not None:
            data["phase_timing"] = phase_timing
        elif include_key and phase_timing is None:
            # Explicitly include null
            data["phase_timing"] = None
        return json.dumps(data)

    def test_write_save_result_accepts_phase_timing_dict(self):
        """Valid dict passes validation."""
        staging = _make_tmp_staging_dir()
        try:
            result_json = self._make_result_json(phase_timing={
                "triage_ms": 100.5,
                "orchestrate_ms": 50.2,
                "write_ms": 30.1,
                "total_ms": 180.8,
                "draft_ms": None,
                "verify_ms": None,
            })
            result = write_save_result(staging, result_json)
            assert result["status"] == "ok"
            assert "path" in result
            # Verify file was written
            written = json.loads(Path(result["path"]).read_text())
            assert written["phase_timing"]["triage_ms"] == 100.5
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_write_save_result_accepts_phase_timing_none(self):
        """None (null) is accepted as a valid value."""
        staging = _make_tmp_staging_dir()
        try:
            result_json = self._make_result_json(phase_timing=None)
            result = write_save_result(staging, result_json)
            assert result["status"] == "ok"
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_write_save_result_rejects_phase_timing_string(self):
        """Non-dict type (string) is rejected."""
        staging = _make_tmp_staging_dir()
        try:
            result_json = self._make_result_json(
                phase_timing="not_a_dict"
            )
            result = write_save_result(staging, result_json)
            assert result["status"] == "error"
            assert "phase_timing must be a dict" in result["message"]
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_write_save_result_rejects_phase_timing_list(self):
        """List type is rejected."""
        staging = _make_tmp_staging_dir()
        try:
            result_json = self._make_result_json(
                phase_timing=[1, 2, 3]
            )
            result = write_save_result(staging, result_json)
            assert result["status"] == "error"
            assert "phase_timing must be a dict" in result["message"]
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)

    def test_write_save_result_accepts_phase_timing_empty_dict(self):
        """Empty dict {} is a valid dict."""
        staging = _make_tmp_staging_dir()
        try:
            result_json = self._make_result_json(phase_timing={})
            result = write_save_result(staging, result_json)
            assert result["status"] == "ok"
            written = json.loads(Path(result["path"]).read_text())
            assert written["phase_timing"] == {}
        finally:
            import shutil
            shutil.rmtree(staging, ignore_errors=True)


# ---------------------------------------------------------------------------
# Group 3: execute_saves phase_timing
# ---------------------------------------------------------------------------


class TestExecuteSavesPhaseTiming:
    """Tests for phase_timing dict returned by execute_saves."""

    def _run_execute_saves(self, tmp_path, manifest=None,
                           triage_start_ts=None, mock_subprocess=True):
        """Helper to run execute_saves with mocked subprocess calls."""
        staging = _make_staging_dir(tmp_path, triage_start_ts=triage_start_ts)
        memory_root = str(tmp_path / "memory")
        os.makedirs(memory_root, exist_ok=True)
        scripts_dir = str(SCRIPTS_DIR)
        python = sys.executable

        if manifest is None:
            manifest = _make_actionable_manifest()

        if mock_subprocess:
            # Mock subprocess.run to succeed for all write calls
            mock_result = mock.MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps({"title": "Test Title"})
            mock_result.stderr = ""
            with mock.patch("memory_orchestrate.subprocess.run",
                            return_value=mock_result):
                return execute_saves(
                    manifest, staging, memory_root, scripts_dir, python
                )
        else:
            return execute_saves(
                manifest, staging, memory_root, scripts_dir, python
            )

    def test_execute_saves_returns_phase_timing(self, tmp_path):
        """Verify phase_timing is present in result dict."""
        result = self._run_execute_saves(tmp_path,
                                         triage_start_ts=time.time() - 1)
        assert "phase_timing" in result
        assert isinstance(result["phase_timing"], dict)

    def test_execute_saves_phase_timing_keys(self, tmp_path):
        """Verify all expected keys: triage_ms, orchestrate_ms, write_ms,
        total_ms, draft_ms, verify_ms."""
        result = self._run_execute_saves(tmp_path,
                                         triage_start_ts=time.time() - 1)
        pt = result["phase_timing"]
        expected_keys = {
            "triage_ms", "orchestrate_ms", "write_ms",
            "total_ms", "draft_ms", "verify_ms",
        }
        assert set(pt.keys()) == expected_keys

    def test_execute_saves_phase_timing_draft_verify_none(self, tmp_path):
        """draft_ms and verify_ms are always None (populated by SKILL.md layer)."""
        result = self._run_execute_saves(tmp_path,
                                         triage_start_ts=time.time() - 1)
        pt = result["phase_timing"]
        assert pt["draft_ms"] is None
        assert pt["verify_ms"] is None

    def test_execute_saves_all_noop_returns_phase_timing_none(self, tmp_path):
        """All-noop manifest returns phase_timing: None."""
        result = self._run_execute_saves(
            tmp_path,
            manifest=_make_all_noop_manifest(),
            triage_start_ts=time.time() - 1,
        )
        assert result["phase_timing"] is None

    def test_execute_saves_phase_timing_without_triage_start_ts(self, tmp_path):
        """Without triage-data.json, triage_ms and total_ms are None."""
        result = self._run_execute_saves(tmp_path, triage_start_ts=None)
        pt = result["phase_timing"]
        assert pt["triage_ms"] is None
        assert pt["total_ms"] is None
        # orchestrate_ms and write_ms should still be populated
        assert isinstance(pt["orchestrate_ms"], (int, float))
        assert isinstance(pt["write_ms"], (int, float))

    def test_execute_saves_phase_timing_with_triage_start_ts(self, tmp_path):
        """With triage-data.json, triage_ms and total_ms are populated."""
        ts = time.time() - 2  # 2 seconds ago
        result = self._run_execute_saves(tmp_path, triage_start_ts=ts)
        pt = result["phase_timing"]
        assert pt["triage_ms"] is not None
        assert pt["total_ms"] is not None
        # Both should be positive (triage happened 2s ago)
        assert pt["triage_ms"] >= 0
        assert pt["total_ms"] >= 0

    def test_execute_saves_phase_timing_clamps_negative(self, tmp_path):
        """Negative cross-process duration is clamped to None.

        Simulates NTP step: triage_start_ts in the future.
        """
        future_ts = time.time() + 9999  # Far in the future
        result = self._run_execute_saves(tmp_path,
                                         triage_start_ts=future_ts)
        pt = result["phase_timing"]
        assert pt["triage_ms"] is None
        assert pt["total_ms"] is None

    def test_execute_saves_phase_timing_isfinite_guard(self, tmp_path):
        """NaN triage_start_ts produces None timing values."""
        staging = _make_staging_dir(tmp_path)
        # Write triage-data.json with NaN value
        td = {"categories": [], "triage_start_ts": float("nan")}
        # json.dumps converts NaN to "NaN" which is not valid JSON, but
        # we write it as a raw string to simulate corrupted data
        td_path = os.path.join(staging, "triage-data.json")
        # Use a workaround: write valid JSON but patch the read
        td_valid = {"categories": [], "triage_start_ts": "NaN"}
        with open(td_path, "w") as f:
            json.dump(td_valid, f)

        memory_root = str(tmp_path / "memory")
        os.makedirs(memory_root, exist_ok=True)

        manifest = _make_actionable_manifest()
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"title": "Test"})
        mock_result.stderr = ""

        with mock.patch("memory_orchestrate.subprocess.run",
                        return_value=mock_result):
            result = execute_saves(
                manifest, staging, memory_root,
                str(SCRIPTS_DIR), sys.executable,
            )

        pt = result["phase_timing"]
        # "NaN" string -> float("nan") -> isfinite returns False -> None
        assert pt["triage_ms"] is None
        assert pt["total_ms"] is None

    def test_execute_saves_phase_timing_infinity_guard(self, tmp_path):
        """Infinity triage_start_ts produces None timing values."""
        staging = _make_staging_dir(tmp_path)
        td_path = os.path.join(staging, "triage-data.json")
        td = {"categories": [], "triage_start_ts": "Infinity"}
        with open(td_path, "w") as f:
            json.dump(td, f)

        memory_root = str(tmp_path / "memory")
        os.makedirs(memory_root, exist_ok=True)

        manifest = _make_actionable_manifest()
        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"title": "Test"})
        mock_result.stderr = ""

        with mock.patch("memory_orchestrate.subprocess.run",
                        return_value=mock_result):
            result = execute_saves(
                manifest, staging, memory_root,
                str(SCRIPTS_DIR), sys.executable,
            )

        pt = result["phase_timing"]
        # "Infinity" -> float("inf") -> isfinite returns False -> None
        assert pt["triage_ms"] is None
        assert pt["total_ms"] is None


# ---------------------------------------------------------------------------
# Group 4: save.start / save.complete log events
# ---------------------------------------------------------------------------


class TestSaveLogEvents:
    """Tests for save.start and save.complete emit_event calls."""

    def _run_with_event_capture(self, tmp_path, triage_start_ts=None,
                                manifest=None):
        """Run execute_saves and capture emit_event calls."""
        staging = _make_staging_dir(tmp_path,
                                    triage_start_ts=triage_start_ts)
        memory_root = str(tmp_path / "memory")
        os.makedirs(memory_root, exist_ok=True)

        if manifest is None:
            manifest = _make_actionable_manifest()

        mock_subprocess_result = mock.MagicMock()
        mock_subprocess_result.returncode = 0
        mock_subprocess_result.stdout = json.dumps({"title": "Test"})
        mock_subprocess_result.stderr = ""

        with mock.patch("memory_orchestrate.subprocess.run",
                        return_value=mock_subprocess_result), \
             mock.patch("memory_orchestrate.emit_event") as mock_emit:
            result = execute_saves(
                manifest, staging, memory_root,
                str(SCRIPTS_DIR), sys.executable,
            )
        return result, mock_emit

    def test_execute_saves_emits_save_start(self, tmp_path):
        """Verify save.start event is emitted."""
        _, mock_emit = self._run_with_event_capture(tmp_path)
        event_types = [call.args[0] for call in mock_emit.call_args_list]
        assert "save.start" in event_types

    def test_execute_saves_emits_save_complete(self, tmp_path):
        """Verify save.complete event is emitted."""
        _, mock_emit = self._run_with_event_capture(tmp_path)
        event_types = [call.args[0] for call in mock_emit.call_args_list]
        assert "save.complete" in event_types

    def test_save_complete_has_duration_ms(self, tmp_path):
        """Verify save.complete has duration_ms when triage_start_ts provided."""
        ts = time.time() - 1
        _, mock_emit = self._run_with_event_capture(
            tmp_path, triage_start_ts=ts
        )
        # Find the save.complete call
        complete_calls = [
            call for call in mock_emit.call_args_list
            if call.args[0] == "save.complete"
        ]
        assert len(complete_calls) == 1
        kwargs = complete_calls[0].kwargs
        assert "duration_ms" in kwargs
        assert kwargs["duration_ms"] is not None
        assert kwargs["duration_ms"] >= 0

    def test_save_complete_duration_ms_none_without_triage_ts(self, tmp_path):
        """duration_ms is None when no triage_start_ts available."""
        _, mock_emit = self._run_with_event_capture(
            tmp_path, triage_start_ts=None
        )
        complete_calls = [
            call for call in mock_emit.call_args_list
            if call.args[0] == "save.complete"
        ]
        assert len(complete_calls) == 1
        kwargs = complete_calls[0].kwargs
        assert kwargs["duration_ms"] is None

    def test_save_complete_negative_duration_clamped(self, tmp_path):
        """Negative duration (future triage_start_ts) is clamped to None."""
        future_ts = time.time() + 9999
        _, mock_emit = self._run_with_event_capture(
            tmp_path, triage_start_ts=future_ts
        )
        complete_calls = [
            call for call in mock_emit.call_args_list
            if call.args[0] == "save.complete"
        ]
        assert len(complete_calls) == 1
        kwargs = complete_calls[0].kwargs
        assert kwargs["duration_ms"] is None


# ---------------------------------------------------------------------------
# Group 5: Integration
# ---------------------------------------------------------------------------


class TestTimingIntegration:
    """Integration tests for timing data flow."""

    def test_phase_timing_in_save_result_json(self, tmp_path):
        """Verify phase_timing flows into last-save-result.json.

        Uses execute_saves with mocked writes and checks the result
        file written to staging.
        """
        ts = time.time() - 1
        staging = _make_staging_dir(tmp_path, triage_start_ts=ts)
        memory_root = str(tmp_path / "memory")
        os.makedirs(memory_root, exist_ok=True)

        manifest = _make_actionable_manifest()

        call_count = {"n": 0}

        def mock_subprocess_run(cmd, **kwargs):
            """Mock subprocess: succeed for writes, track result payload."""
            call_count["n"] += 1
            result = mock.MagicMock()
            result.returncode = 0
            result.stdout = json.dumps({"title": "Test Title"})
            result.stderr = ""
            return result

        with mock.patch("memory_orchestrate.subprocess.run",
                        side_effect=mock_subprocess_run), \
             mock.patch("memory_orchestrate.emit_event"):
            result = execute_saves(
                manifest, staging, memory_root,
                str(SCRIPTS_DIR), sys.executable,
            )

        # The result dict itself should have phase_timing
        assert result["phase_timing"] is not None
        pt = result["phase_timing"]
        assert pt["triage_ms"] is not None
        assert pt["triage_ms"] >= 0
        assert pt["orchestrate_ms"] >= 0
        assert pt["write_ms"] >= 0

        # Also check the payload file written to staging
        payload_path = os.path.join(staging, ".save-result-payload.json")
        if os.path.isfile(payload_path):
            payload = json.loads(Path(payload_path).read_text())
            assert "phase_timing" in payload
            assert payload["phase_timing"]["triage_ms"] >= 0

    def test_triage_start_ts_in_triage_data_json(self, tmp_path):
        """Verify triage_start_ts appears in JSON output from build_triage_data."""
        ts = time.time()
        data = build_triage_data(
            results=_make_triage_results(["decision", "constraint"]),
            context_paths={"decision": "/tmp/ctx-decision.txt"},
            parallel_config=_make_parallel_config(),
            triage_start_ts=ts,
        )

        # Write to file (as the triage hook does)
        td_path = tmp_path / "triage-data.json"
        td_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Read back and verify
        loaded = json.loads(td_path.read_text())
        assert loaded["triage_start_ts"] == ts
        assert len(loaded["categories"]) == 2

    def test_full_timing_flow_triage_to_save(self, tmp_path):
        """End-to-end: write triage-data.json with ts, call execute_saves,
        verify phase_timing in result.
        """
        # 1. Simulate triage: build data with timestamp
        ts = time.time() - 0.5  # 500ms ago
        triage_data = build_triage_data(
            results=_make_triage_results(["decision"]),
            context_paths={},
            parallel_config=_make_parallel_config(),
            triage_start_ts=ts,
        )

        # 2. Write triage-data.json to staging (as triage hook does)
        staging = str(tmp_path / "staging")
        os.makedirs(staging, exist_ok=True)
        td_path = os.path.join(staging, "triage-data.json")
        with open(td_path, "w") as f:
            json.dump(triage_data, f)

        # 3. Run execute_saves with the staging dir
        memory_root = str(tmp_path / "memory")
        os.makedirs(memory_root, exist_ok=True)

        manifest = _make_actionable_manifest(["decision"])

        mock_result = mock.MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"title": "Use PostgreSQL"})
        mock_result.stderr = ""

        with mock.patch("memory_orchestrate.subprocess.run",
                        return_value=mock_result), \
             mock.patch("memory_orchestrate.emit_event"):
            result = execute_saves(
                manifest, staging, memory_root,
                str(SCRIPTS_DIR), sys.executable,
            )

        # 4. Verify timing
        assert result["status"] == "success"
        pt = result["phase_timing"]
        assert pt is not None

        # triage_ms should be roughly 500ms+ (wall clock since ts)
        assert pt["triage_ms"] is not None
        assert pt["triage_ms"] >= 400  # Allow some slack

        # total_ms should be >= triage_ms
        assert pt["total_ms"] is not None
        assert pt["total_ms"] >= pt["triage_ms"]

        # orchestrate_ms and write_ms should be non-negative
        assert pt["orchestrate_ms"] >= 0
        assert pt["write_ms"] >= 0

        # draft_ms and verify_ms always None from execute_saves
        assert pt["draft_ms"] is None
        assert pt["verify_ms"] is None
