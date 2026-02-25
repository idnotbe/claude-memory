"""Tests for memory_logger.py -- shared structured JSONL logging module.

Covers: emit_event, parse_logging_config, get_session_id, cleanup_old_logs,
level filtering, results truncation, path traversal prevention, symlink
protection, concurrent safety, non-serializable data, and p95 benchmark.
"""

import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from memory_logger import (
    emit_event,
    parse_logging_config,
    get_session_id,
    cleanup_old_logs,
    _sanitize_category,
    _LEVELS,
    _MAX_RESULTS,
    _CLEANUP_INTERVAL_S,
)


# ---------------------------------------------------------------------------
# Helper: enabled config
# ---------------------------------------------------------------------------

def _enabled_config(level="info", retention_days=14):
    """Return a logging config dict with logging enabled."""
    return {"logging": {"enabled": True, "level": level, "retention_days": retention_days}}


def _read_log_lines(memory_root):
    """Read all JSONL lines from all log files under memory_root/logs/."""
    log_dir = Path(memory_root) / "logs"
    lines = []
    if not log_dir.exists():
        return lines
    for cat_dir in log_dir.iterdir():
        if cat_dir.is_dir() and not cat_dir.name.startswith("."):
            for f in cat_dir.iterdir():
                if f.suffix == ".jsonl":
                    lines.extend(f.read_text("utf-8").strip().splitlines())
    return lines


# ===================================================================
# 1-3: Normal append + JSONL validity + schema verification
# ===================================================================

class TestNormalAppend:
    def test_emit_creates_file_and_writes_valid_jsonl(self, tmp_path):
        """emit_event creates the log file and writes a parseable JSONL line."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"query_tokens": ["auth"]},
            level="info",
            hook="UserPromptSubmit",
            script="memory_retrieve.py",
            session_id="transcript-abc",
            duration_ms=42.5,
            memory_root=str(root),
            config=_enabled_config(),
        )
        lines = _read_log_lines(root)
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert isinstance(entry, dict)

    def test_jsonl_line_parseable_by_json_loads(self, tmp_path):
        """Every line written by emit_event must be parseable by json.loads."""
        root = tmp_path / "memory"
        root.mkdir()
        for i in range(5):
            emit_event(
                "retrieval.search",
                {"i": i},
                memory_root=str(root),
                config=_enabled_config(),
            )
        lines = _read_log_lines(root)
        assert len(lines) == 5
        for line in lines:
            parsed = json.loads(line)
            assert "schema_version" in parsed

    def test_schema_required_fields(self, tmp_path):
        """Log entry must contain all required top-level fields with correct types."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "judge.evaluate",
            {"accepted": [0, 1]},
            level="warning",
            hook="UserPromptSubmit",
            script="memory_judge.py",
            session_id="session-xyz",
            duration_ms=100.0,
            error={"type": "TimeoutError", "message": "timed out"},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])

        # schema_version
        assert entry["schema_version"] == 1

        # timestamp format: YYYY-MM-DDThh:mm:ss.mmmZ
        ts = entry["timestamp"]
        assert ts.endswith("Z")
        # Parse to verify format
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ")

        # Required string fields
        assert entry["event_type"] == "judge.evaluate"
        assert entry["level"] == "warning"
        assert entry["hook"] == "UserPromptSubmit"
        assert entry["script"] == "memory_judge.py"
        assert entry["session_id"] == "session-xyz"

        # duration_ms
        assert entry["duration_ms"] == 100.0

        # data dict
        assert isinstance(entry["data"], dict)
        assert entry["data"]["accepted"] == [0, 1]

        # error dict
        assert entry["error"]["type"] == "TimeoutError"


# ===================================================================
# 4-5: Directory auto-creation and permission errors
# ===================================================================

class TestDirectoryHandling:
    def test_auto_creates_log_directory(self, tmp_path):
        """emit_event creates logs/{category}/ if it does not exist."""
        root = tmp_path / "memory"
        # root itself does not exist yet
        emit_event(
            "triage.score",
            {"scores": {}},
            memory_root=str(root),
            config=_enabled_config(),
        )
        log_dir = root / "logs" / "triage"
        assert log_dir.is_dir()
        lines = _read_log_lines(root)
        assert len(lines) == 1

    def test_directory_permission_error_fail_open(self, tmp_path):
        """If log directory cannot be created, emit_event returns without crash."""
        # Create a non-writable parent so mkdir fails
        blocked = tmp_path / "blocked"
        blocked.mkdir()
        blocked.chmod(0o444)
        try:
            root = blocked / "memory"
            # Should NOT raise -- fail-open
            emit_event(
                "retrieval.search",
                {"test": True},
                memory_root=str(root),
                config=_enabled_config(),
            )
            # Verify no crash occurred (the function returned normally).
            # We avoid calling .exists() on the blocked subtree because
            # that itself would raise PermissionError on some platforms.
        finally:
            blocked.chmod(0o755)


# ===================================================================
# 6-8: Disabled logging, empty root, invalid config
# ===================================================================

class TestDisabledAndInvalidConfig:
    def test_logging_disabled_no_files(self, tmp_path):
        """When logging.enabled=false, no files are created."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"x": 1},
            memory_root=str(root),
            config={"logging": {"enabled": False}},
        )
        assert not (root / "logs").exists()

    def test_empty_memory_root_returns_immediately(self, tmp_path):
        """Empty memory_root means immediate return, no files."""
        emit_event(
            "retrieval.search",
            {"x": 1},
            memory_root="",
            config=_enabled_config(),
        )
        # Nothing to assert on filesystem -- just verify no crash

    def test_config_none_safe_default(self, tmp_path):
        """config=None should use safe defaults (disabled)."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"x": 1},
            memory_root=str(root),
            config=None,
        )
        assert not (root / "logs").exists()

    def test_config_string_safe_default(self, tmp_path):
        """config as a string should use safe defaults, no crash."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"x": 1},
            memory_root=str(root),
            config="invalid",
        )
        assert not (root / "logs").exists()

    def test_config_list_safe_default(self, tmp_path):
        """config as a list should use safe defaults, no crash."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"x": 1},
            memory_root=str(root),
            config=[1, 2, 3],
        )
        assert not (root / "logs").exists()


# ===================================================================
# 9-11: Level filtering
# ===================================================================

class TestLevelFiltering:
    def test_debug_not_logged_when_level_info(self, tmp_path):
        """Debug events are dropped when config level is info."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"debug_data": True},
            level="debug",
            memory_root=str(root),
            config=_enabled_config(level="info"),
        )
        assert len(_read_log_lines(root)) == 0

    def test_warning_logged_when_level_info(self, tmp_path):
        """Warning events are logged when config level is info."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "judge.error",
            {"err": "timeout"},
            level="warning",
            memory_root=str(root),
            config=_enabled_config(level="info"),
        )
        lines = _read_log_lines(root)
        assert len(lines) == 1
        assert json.loads(lines[0])["level"] == "warning"

    def test_info_logged_when_level_info(self, tmp_path):
        """Info events are logged when config level is info."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"results": []},
            level="info",
            memory_root=str(root),
            config=_enabled_config(level="info"),
        )
        lines = _read_log_lines(root)
        assert len(lines) == 1
        assert json.loads(lines[0])["level"] == "info"


# ===================================================================
# 12-15: Cleanup
# ===================================================================

class TestCleanup:
    def test_cleanup_deletes_old_files(self, tmp_path):
        """Files older than retention_days are removed."""
        log_root = tmp_path / "logs"
        cat_dir = log_root / "retrieval"
        cat_dir.mkdir(parents=True)

        old_file = cat_dir / "2020-01-01.jsonl"
        old_file.write_text('{"old":true}\n')
        # Set mtime to 30 days ago
        old_mtime = time.time() - (30 * 86400)
        os.utime(str(old_file), (old_mtime, old_mtime))

        recent_file = cat_dir / "2026-02-24.jsonl"
        recent_file.write_text('{"recent":true}\n')

        cleanup_old_logs(log_root, retention_days=14)
        assert not old_file.exists(), "Old file should have been deleted"
        assert recent_file.exists(), "Recent file should be preserved"

    def test_cleanup_time_gate_skip(self, tmp_path):
        """.last_cleanup less than 24h ago means cleanup is skipped."""
        log_root = tmp_path / "logs"
        cat_dir = log_root / "retrieval"
        cat_dir.mkdir(parents=True)

        # Create .last_cleanup with recent timestamp
        last_cleanup = log_root / ".last_cleanup"
        last_cleanup.write_text(str(time.time()))

        old_file = cat_dir / "2020-01-01.jsonl"
        old_file.write_text('{"old":true}\n')
        old_mtime = time.time() - (30 * 86400)
        os.utime(str(old_file), (old_mtime, old_mtime))

        cleanup_old_logs(log_root, retention_days=14)
        assert old_file.exists(), "Old file should NOT be deleted (time gate active)"

    def test_cleanup_proceeds_when_last_cleanup_missing(self, tmp_path):
        """.last_cleanup missing means cleanup proceeds."""
        log_root = tmp_path / "logs"
        cat_dir = log_root / "retrieval"
        cat_dir.mkdir(parents=True)

        old_file = cat_dir / "2020-01-01.jsonl"
        old_file.write_text('{"old":true}\n')
        old_mtime = time.time() - (30 * 86400)
        os.utime(str(old_file), (old_mtime, old_mtime))

        # No .last_cleanup file
        assert not (log_root / ".last_cleanup").exists()
        cleanup_old_logs(log_root, retention_days=14)
        assert not old_file.exists(), "Old file should be deleted"

    def test_cleanup_disabled_when_retention_zero(self, tmp_path):
        """retention_days=0 disables cleanup entirely."""
        log_root = tmp_path / "logs"
        cat_dir = log_root / "retrieval"
        cat_dir.mkdir(parents=True)

        old_file = cat_dir / "2020-01-01.jsonl"
        old_file.write_text('{"old":true}\n')
        old_mtime = time.time() - (365 * 86400)
        os.utime(str(old_file), (old_mtime, old_mtime))

        cleanup_old_logs(log_root, retention_days=0)
        assert old_file.exists(), "File should NOT be deleted when retention_days=0"


# ===================================================================
# 16-17: Session ID extraction
# ===================================================================

class TestGetSessionId:
    def test_normal_path(self):
        """Normal transcript path returns stem."""
        assert get_session_id("/tmp/transcript-abc123.json") == "transcript-abc123"

    def test_empty_returns_empty(self):
        assert get_session_id("") == ""

    def test_none_returns_empty(self):
        assert get_session_id(None) == ""


# ===================================================================
# 18-19: Results truncation
# ===================================================================

class TestResultsTruncation:
    def test_results_truncated_to_max(self, tmp_path):
        """data.results with >20 entries is truncated to 20."""
        root = tmp_path / "memory"
        root.mkdir()
        results = [{"path": f"entry-{i}.json", "score": -i} for i in range(50)]
        emit_event(
            "retrieval.search",
            {"results": results},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert len(entry["data"]["results"]) == _MAX_RESULTS

    def test_original_dict_not_mutated(self, tmp_path):
        """The caller's data dict must not be modified by truncation."""
        root = tmp_path / "memory"
        root.mkdir()
        results = [{"path": f"entry-{i}.json"} for i in range(50)]
        original_data = {"results": results}
        original_len = len(original_data["results"])

        emit_event(
            "retrieval.search",
            original_data,
            memory_root=str(root),
            config=_enabled_config(),
        )
        assert len(original_data["results"]) == original_len, \
            "emit_event should not mutate the caller's data dict"


# ===================================================================
# 20: Path traversal prevention
# ===================================================================

class TestPathTraversalPrevention:
    def test_dotdot_in_event_type_sanitized(self, tmp_path):
        """event_type '../../etc' must be sanitized to a safe category."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "../../etc",
            {"test": True},
            memory_root=str(root),
            config=_enabled_config(),
        )
        log_dir = root / "logs"
        if log_dir.exists():
            # Verify no ".." path component was created
            for d in log_dir.iterdir():
                assert ".." not in str(d.name)
        # Verify no file was created outside logs/
        assert not (root.parent / "etc").exists()

    def test_sanitize_category_function(self):
        """_sanitize_category handles various malicious inputs."""
        assert _sanitize_category("retrieval.search") == "retrieval"
        assert _sanitize_category("../../etc") == "unknown"
        assert _sanitize_category("normal") == "normal"
        # "a/b" splits on "." -> "a/b", "/" stripped -> "ab"
        assert _sanitize_category("a/b") == "ab"
        assert _sanitize_category("") == "unknown"
        # "with spaces" fails the safe regex, spaces stripped -> "withspaces"
        assert _sanitize_category("with spaces.foo") == "withspaces"


# ===================================================================
# 21: Symlink protection in cleanup
# ===================================================================

class TestSymlinkProtection:
    def test_cleanup_skips_symlinked_dirs(self, tmp_path):
        """Symlinked category directories are skipped during cleanup."""
        log_root = tmp_path / "logs"
        real_dir = tmp_path / "real_target"
        real_dir.mkdir(parents=True)
        old_file = real_dir / "2020-01-01.jsonl"
        old_file.write_text('{"old":true}\n')
        old_mtime = time.time() - (30 * 86400)
        os.utime(str(old_file), (old_mtime, old_mtime))

        log_root.mkdir(parents=True)
        symlink_dir = log_root / "evil"
        symlink_dir.symlink_to(real_dir)

        cleanup_old_logs(log_root, retention_days=14)
        # File in the symlinked target must NOT be deleted
        assert old_file.exists(), "Cleanup should skip symlinked directories"

    def test_cleanup_skips_symlinked_files(self, tmp_path):
        """Symlinked log files inside a real category dir are skipped."""
        log_root = tmp_path / "logs"
        cat_dir = log_root / "retrieval"
        cat_dir.mkdir(parents=True)

        # Real old file outside logs
        target_file = tmp_path / "important.jsonl"
        target_file.write_text('{"important":true}\n')
        old_mtime = time.time() - (30 * 86400)
        os.utime(str(target_file), (old_mtime, old_mtime))

        # Symlink inside the log directory
        symlink_file = cat_dir / "2020-01-01.jsonl"
        symlink_file.symlink_to(target_file)

        cleanup_old_logs(log_root, retention_days=14)
        assert target_file.exists(), "Symlinked files should be skipped by cleanup"


# ===================================================================
# 22: Non-serializable data
# ===================================================================

class TestNonSerializableData:
    def test_datetime_in_data_converted_via_str(self, tmp_path):
        """datetime objects in data are serialized via default=str."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"timestamp": datetime(2026, 2, 25, 12, 0, 0, tzinfo=timezone.utc)},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert "2026-02-25" in entry["data"]["timestamp"]

    def test_set_in_data_converted_to_sorted_list(self, tmp_path):
        """set objects in data are serialized as deterministic sorted lists."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"tags": {"b", "a", "c"}},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["data"]["tags"] == ["a", "b", "c"], \
            "set should be serialized as a sorted list"


# ===================================================================
# 23: Concurrent append safety
# ===================================================================

class TestConcurrentAppend:
    def test_concurrent_emit_no_corruption(self, tmp_path):
        """Multiple concurrent emit_event calls produce valid non-corrupt JSONL."""
        root = tmp_path / "memory"
        root.mkdir()
        cfg = _enabled_config()

        def worker(i):
            emit_event(
                "retrieval.search",
                {"worker": i, "payload": "x" * 100},
                memory_root=str(root),
                config=cfg,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(worker, range(50)))

        lines = _read_log_lines(root)
        # Every line must be valid JSON
        assert len(lines) == 50
        for idx, line in enumerate(lines):
            parsed = json.loads(line)
            assert parsed["schema_version"] == 1, f"Line {idx} invalid"


# ===================================================================
# 24: Performance benchmark
# ===================================================================

class TestPerformanceBenchmark:
    def test_emit_event_p95_under_5ms(self, tmp_path):
        """p95 latency of emit_event must be < 5ms over 100 calls."""
        root = tmp_path / "memory"
        root.mkdir()
        cfg = _enabled_config()
        durations = []

        for i in range(100):
            start = time.perf_counter()
            emit_event(
                "retrieval.search",
                {"i": i, "tokens": ["auth", "jwt"]},
                level="info",
                memory_root=str(root),
                config=cfg,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            durations.append(elapsed_ms)

        durations.sort()
        p95 = durations[94]  # 95th percentile (0-indexed)
        assert p95 < 5.0, f"p95={p95:.2f}ms exceeds 5ms budget"


# ===================================================================
# 25-27: parse_logging_config
# ===================================================================

class TestParseLoggingConfig:
    def test_full_plugin_config_extracted(self):
        """Full plugin config with 'logging' key is correctly extracted."""
        cfg = parse_logging_config({
            "retrieval": {"enabled": True},
            "logging": {"enabled": True, "level": "debug", "retention_days": 7},
        })
        assert cfg["enabled"] is True
        assert cfg["level"] == "debug"
        assert cfg["retention_days"] == 7

    def test_logging_sub_dict_directly(self):
        """Passing just the logging sub-dict (no parent 'logging' key) works."""
        cfg = parse_logging_config({"enabled": True, "level": "warning", "retention_days": 30})
        assert cfg["enabled"] is True
        assert cfg["level"] == "warning"
        assert cfg["retention_days"] == 30

    def test_negative_retention_days_defaults_to_14(self):
        """Negative retention_days is clamped to default 14."""
        cfg = parse_logging_config({"enabled": True, "retention_days": -5})
        assert cfg["retention_days"] == 14

    def test_unknown_level_defaults_to_info(self):
        """Unknown level string falls back to 'info'."""
        cfg = parse_logging_config({"enabled": True, "level": "verbose"})
        assert cfg["level"] == "info"

    def test_none_config_returns_defaults(self):
        """None config returns safe defaults."""
        cfg = parse_logging_config(None)
        assert cfg["enabled"] is False
        assert cfg["level"] == "info"
        assert cfg["retention_days"] == 14

    def test_string_config_returns_defaults(self):
        """String config returns safe defaults."""
        cfg = parse_logging_config("not a dict")
        assert cfg["enabled"] is False

    def test_list_config_returns_defaults(self):
        """List config returns safe defaults."""
        cfg = parse_logging_config([1, 2])
        assert cfg["enabled"] is False

    def test_empty_dict_returns_defaults(self):
        """Empty dict returns safe defaults."""
        cfg = parse_logging_config({})
        assert cfg["enabled"] is False
        assert cfg["level"] == "info"
        assert cfg["retention_days"] == 14


# ===================================================================
# 28: Bool-string config parsing
# ===================================================================

class TestBoolStringConfig:
    """parse_logging_config should handle string-typed booleans correctly."""

    def test_string_false_disables(self):
        """'false' string should be parsed as enabled=False."""
        cfg = parse_logging_config({"enabled": "false"})
        assert cfg["enabled"] is False

    def test_string_true_enables(self):
        """'true' string should be parsed as enabled=True."""
        cfg = parse_logging_config({"enabled": "true"})
        assert cfg["enabled"] is True

    def test_string_1_enables(self):
        """'1' string should be parsed as enabled=True."""
        cfg = parse_logging_config({"enabled": "1"})
        assert cfg["enabled"] is True

    def test_string_yes_enables(self):
        """'yes' string should be parsed as enabled=True."""
        cfg = parse_logging_config({"enabled": "yes"})
        assert cfg["enabled"] is True

    def test_string_0_disables(self):
        """'0' string should be parsed as enabled=False."""
        cfg = parse_logging_config({"enabled": "0"})
        assert cfg["enabled"] is False

    def test_string_no_disables(self):
        """'no' string should be parsed as enabled=False."""
        cfg = parse_logging_config({"enabled": "no"})
        assert cfg["enabled"] is False


# ===================================================================
# 29: NaN / Infinity handling in duration_ms
# ===================================================================

class TestNaNInfinityHandling:
    """NaN and Infinity duration_ms values must be written as null, not literals."""

    def test_nan_duration_written_as_null(self, tmp_path):
        """emit_event with duration_ms=NaN writes duration_ms: null."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"test": True},
            duration_ms=float("nan"),
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["duration_ms"] is None

    def test_inf_duration_written_as_null(self, tmp_path):
        """emit_event with duration_ms=Infinity writes duration_ms: null."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"test": True},
            duration_ms=float("inf"),
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["duration_ms"] is None

    def test_neg_inf_duration_written_as_null(self, tmp_path):
        """emit_event with duration_ms=-Infinity writes duration_ms: null."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"test": True},
            duration_ms=float("-inf"),
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["duration_ms"] is None


# ===================================================================
# 30: Symlink containment in emit_event
# ===================================================================

class TestSymlinkContainment:
    """Symlink in category directory must not escape the logs/ root."""

    def test_symlink_category_dir_no_escape(self, tmp_path):
        """A symlink at logs/evil -> /tmp/target/ must not receive log data."""
        target_dir = tmp_path / "target"
        target_dir.mkdir()

        root = tmp_path / "memory"
        root.mkdir()
        logs_dir = root / "logs"
        logs_dir.mkdir()

        # Create symlink: logs/evil -> target_dir (outside logs/)
        evil_link = logs_dir / "evil"
        evil_link.symlink_to(target_dir)

        emit_event(
            "evil.test",
            {"payload": "should not appear"},
            memory_root=str(root),
            config=_enabled_config(),
        )

        # Verify no file written to symlink target
        target_files = list(target_dir.iterdir())
        assert len(target_files) == 0, \
            f"Files written to symlink target: {target_files}"


# ===================================================================
# 31: .last_cleanup symlink bypass prevention
# ===================================================================

class TestLastCleanupSymlinkBypass:
    """If .last_cleanup is a symlink, cleanup should remove it and proceed."""

    def test_symlink_last_cleanup_removed_and_cleanup_proceeds(self, tmp_path):
        """Symlink .last_cleanup is removed; old files are still cleaned up."""
        log_root = tmp_path / "logs"
        cat_dir = log_root / "retrieval"
        cat_dir.mkdir(parents=True)

        # Create an old log file that should be cleaned up
        old_file = cat_dir / "2020-01-01.jsonl"
        old_file.write_text('{"old":true}\n')
        old_mtime = time.time() - (30 * 86400)
        os.utime(str(old_file), (old_mtime, old_mtime))

        # Create a decoy file and point .last_cleanup symlink at it
        decoy = tmp_path / "decoy_timestamp"
        decoy.write_text(str(time.time()))

        last_cleanup = log_root / ".last_cleanup"
        last_cleanup.symlink_to(decoy)
        assert last_cleanup.is_symlink()

        cleanup_old_logs(log_root, retention_days=14)

        # The symlink should have been removed
        assert not last_cleanup.is_symlink(), \
            ".last_cleanup symlink should be removed by cleanup"
        # Old file should have been deleted (cleanup proceeded)
        assert not old_file.exists(), \
            "Old file should be deleted after symlink .last_cleanup is removed"


# ===================================================================
# 32: Category name length limit
# ===================================================================

class TestCategoryLengthLimit:
    """_sanitize_category must cap output length to prevent filesystem issues."""

    def test_long_category_truncated_to_64(self):
        """A 1000-character input must produce output of length <= 64."""
        result = _sanitize_category("a" * 1000)
        assert len(result) <= 64, \
            f"Category length {len(result)} exceeds 64-char limit"

    def test_long_category_preserves_prefix(self):
        """Truncated category retains the beginning of the string."""
        long_name = "abcdefgh" * 125  # 1000 chars
        result = _sanitize_category(long_name)
        assert result.startswith("abcdefgh")


# ===================================================================
# 33: Midnight date consistency (timestamp vs filename)
# ===================================================================

class TestMidnightDateConsistency:
    """The date in the timestamp field must match the date in the filename."""

    def test_timestamp_date_matches_filename_date(self, tmp_path):
        """Verify that a logged event has the same date in timestamp and filename."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"consistency_test": True},
            memory_root=str(root),
            config=_enabled_config(),
        )
        # Find the JSONL file
        log_dir = root / "logs" / "retrieval"
        assert log_dir.is_dir()
        jsonl_files = list(log_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 1

        filename_date = jsonl_files[0].stem  # e.g. "2026-02-25"
        entry = json.loads(jsonl_files[0].read_text("utf-8").strip())
        timestamp_date = entry["timestamp"][:10]  # "2026-02-25" from ISO timestamp

        assert filename_date == timestamp_date, \
            f"Filename date {filename_date} != timestamp date {timestamp_date}"


# ===================================================================
# 34-39: Lazy import fallback in consumer scripts (A-05 audit)
# ===================================================================

class TestLazyImportFallback:
    """Verify the lazy import fallback pattern works in actual consumer scripts.

    Each consumer script duplicates the pattern:
        try:
            from memory_logger import emit_event, get_session_id, parse_logging_config
        except (ImportError, SyntaxError) as e:
            if isinstance(e, ImportError) and getattr(e, 'name', None) != 'memory_logger':
                raise
            def emit_event(*args, **kwargs): pass
            ...

    These tests verify the pattern IN the consumer scripts (not just
    in memory_logger.py itself) to catch copy-paste typos or drift.

    Strategy: use subprocess with controlled sys.path to isolate each
    scenario in a fresh Python process.  The isolated_dir is prepended
    to sys.path and the real hooks/scripts directory is filtered out,
    so the subprocess finds the consumer script copy but NOT the real
    memory_logger.py.  Stdlib paths are preserved.
    """

    import subprocess
    import shutil
    import textwrap

    # Consumer scripts to test (no non-stdlib sibling dependencies)
    # B-06 fix: added memory_judge.py (stdlib-only deps, same lazy import pattern)
    CONSUMER_SCRIPTS = [
        ("memory_search_engine.py", "memory_search_engine"),
        ("memory_triage.py", "memory_triage"),
        ("memory_judge.py", "memory_judge"),
    ]

    # Real hooks/scripts directory to exclude from subprocess sys.path
    _REAL_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "hooks" / "scripts")

    @pytest.fixture
    def isolated_dir(self, tmp_path):
        """Create a temp directory with copies of consumer scripts."""
        scripts_dir = Path(__file__).parent.parent / "hooks" / "scripts"
        for filename, _ in self.CONSUMER_SCRIPTS:
            src = scripts_dir / filename
            dst = tmp_path / filename
            self.shutil.copy2(str(src), str(dst))
        return tmp_path

    def _build_path_setup(self, isolated_dir):
        """Return a Python code snippet that sets up sys.path for isolation.

        Prepends isolated_dir, removes the real hooks/scripts directory
        (and its resolved form) so memory_logger.py is not found there,
        while keeping stdlib and site-packages accessible.
        """
        return self.textwrap.dedent(f"""\
            import sys, os
            _real = {self._REAL_SCRIPTS_DIR!r}
            _real_resolved = os.path.realpath(_real)
            sys.path = [{str(isolated_dir)!r}] + [
                p for p in sys.path
                if os.path.realpath(p) != _real_resolved and p != _real
            ]
        """)

    def _run_snippet(self, workdir, snippet, expect_success=True):
        """Run a Python snippet in a subprocess with isolation.

        Returns (returncode, stdout, stderr).
        """
        result = self.subprocess.run(
            [sys.executable, "-c", snippet],
            capture_output=True,
            text=True,
            cwd=str(workdir),
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            timeout=15,
        )
        if expect_success:
            assert result.returncode == 0, (
                f"Expected success but got rc={result.returncode}\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        return result.returncode, result.stdout, result.stderr

    # ------------------------------------------------------------------
    # Scenario A: memory_logger.py missing entirely
    # ------------------------------------------------------------------

    def test_missing_logger_search_engine_imports_ok(self, isolated_dir):
        """memory_search_engine imports without error when memory_logger.py is absent."""
        # Ensure no memory_logger.py exists in isolated dir
        logger_path = isolated_dir / "memory_logger.py"
        if logger_path.exists():
            logger_path.unlink()

        snippet = self._build_path_setup(isolated_dir) + self.textwrap.dedent(f"""\
            from memory_search_engine import emit_event, get_session_id, parse_logging_config
            # Verify noop behavior
            emit_event("test", {{}})
            assert get_session_id("/tmp/x.json") == ""
            cfg = parse_logging_config({{}})
            assert cfg["enabled"] is False
            print("OK")
        """)
        rc, stdout, _ = self._run_snippet(isolated_dir, snippet)
        assert "OK" in stdout

    def test_missing_logger_triage_imports_ok(self, isolated_dir):
        """memory_triage imports without error when memory_logger.py is absent."""
        logger_path = isolated_dir / "memory_logger.py"
        if logger_path.exists():
            logger_path.unlink()

        snippet = self._build_path_setup(isolated_dir) + self.textwrap.dedent(f"""\
            from memory_triage import emit_event, get_session_id, parse_logging_config
            emit_event("test", {{}})
            assert get_session_id("/tmp/x.json") == ""
            cfg = parse_logging_config({{}})
            assert cfg["enabled"] is False
            print("OK")
        """)
        rc, stdout, _ = self._run_snippet(isolated_dir, snippet)
        assert "OK" in stdout

    def test_missing_logger_judge_imports_ok(self, isolated_dir):
        """memory_judge imports without error when memory_logger.py is absent."""
        logger_path = isolated_dir / "memory_logger.py"
        if logger_path.exists():
            logger_path.unlink()

        snippet = self._build_path_setup(isolated_dir) + self.textwrap.dedent(f"""\
            from memory_judge import emit_event, get_session_id, parse_logging_config
            emit_event("test", {{}})
            assert get_session_id("") == ""
            cfg = parse_logging_config({{}})
            assert cfg["enabled"] is False
            print("OK")
        """)
        rc, stdout, _ = self._run_snippet(isolated_dir, snippet)
        assert "OK" in stdout

    # ------------------------------------------------------------------
    # Scenario B: memory_logger.py has a SyntaxError
    # ------------------------------------------------------------------

    def test_syntax_error_logger_search_engine_imports_ok(self, isolated_dir):
        """memory_search_engine imports without error when memory_logger.py has SyntaxError."""
        bad_logger = isolated_dir / "memory_logger.py"
        bad_logger.write_text("def broken(\n", encoding="utf-8")

        snippet = self._build_path_setup(isolated_dir) + self.textwrap.dedent(f"""\
            from memory_search_engine import emit_event, get_session_id, parse_logging_config
            emit_event("test", {{}})
            assert get_session_id("") == ""
            print("OK")
        """)
        rc, stdout, _ = self._run_snippet(isolated_dir, snippet)
        assert "OK" in stdout

    def test_syntax_error_logger_triage_imports_ok(self, isolated_dir):
        """memory_triage imports without error when memory_logger.py has SyntaxError."""
        bad_logger = isolated_dir / "memory_logger.py"
        bad_logger.write_text("def broken(\n", encoding="utf-8")

        snippet = self._build_path_setup(isolated_dir) + self.textwrap.dedent(f"""\
            from memory_triage import emit_event, get_session_id, parse_logging_config
            emit_event("test", {{}})
            assert get_session_id("") == ""
            print("OK")
        """)
        rc, stdout, _ = self._run_snippet(isolated_dir, snippet)
        assert "OK" in stdout

    def test_syntax_error_logger_judge_imports_ok(self, isolated_dir):
        """memory_judge imports without error when memory_logger.py has SyntaxError."""
        bad_logger = isolated_dir / "memory_logger.py"
        bad_logger.write_text("def broken(\n", encoding="utf-8")

        snippet = self._build_path_setup(isolated_dir) + self.textwrap.dedent(f"""\
            from memory_judge import emit_event, get_session_id, parse_logging_config
            emit_event("test", {{}})
            assert get_session_id("") == ""
            print("OK")
        """)
        rc, stdout, _ = self._run_snippet(isolated_dir, snippet)
        assert "OK" in stdout

    # ------------------------------------------------------------------
    # Scenario C: memory_logger.py imports a nonexistent transitive dep
    # ------------------------------------------------------------------

    def test_transitive_dep_failure_search_engine_propagates(self, isolated_dir):
        """ImportError from a transitive dependency inside memory_logger must propagate."""
        bad_logger = isolated_dir / "memory_logger.py"
        bad_logger.write_text(
            "import nonexistent_transitive_dependency_xyzzy\n"
            "def emit_event(*a, **kw): pass\n"
            "def get_session_id(*a, **kw): return ''\n"
            "def parse_logging_config(*a, **kw): return {}\n",
            encoding="utf-8",
        )

        snippet = self._build_path_setup(isolated_dir) + self.textwrap.dedent(f"""\
            try:
                import memory_search_engine
                print("UNEXPECTED_SUCCESS")
            except ImportError as e:
                # The error should mention the transitive dep, not memory_logger
                print(f"IMPORT_ERROR:{{e.name}}")
            except Exception as e:
                print(f"OTHER_ERROR:{{type(e).__name__}}:{{e}}")
        """)
        rc, stdout, stderr = self._run_snippet(isolated_dir, snippet)
        assert "IMPORT_ERROR:nonexistent_transitive_dependency_xyzzy" in stdout, (
            f"Expected transitive ImportError to propagate.\n"
            f"stdout: {stdout}\nstderr: {stderr}"
        )

    def test_transitive_dep_failure_triage_propagates(self, isolated_dir):
        """ImportError from a transitive dependency inside memory_logger must propagate."""
        bad_logger = isolated_dir / "memory_logger.py"
        bad_logger.write_text(
            "import nonexistent_transitive_dependency_xyzzy\n"
            "def emit_event(*a, **kw): pass\n"
            "def get_session_id(*a, **kw): return ''\n"
            "def parse_logging_config(*a, **kw): return {}\n",
            encoding="utf-8",
        )

        snippet = self._build_path_setup(isolated_dir) + self.textwrap.dedent(f"""\
            try:
                import memory_triage
                print("UNEXPECTED_SUCCESS")
            except ImportError as e:
                print(f"IMPORT_ERROR:{{e.name}}")
            except Exception as e:
                print(f"OTHER_ERROR:{{type(e).__name__}}:{{e}}")
        """)
        rc, stdout, stderr = self._run_snippet(isolated_dir, snippet)
        assert "IMPORT_ERROR:nonexistent_transitive_dependency_xyzzy" in stdout, (
            f"Expected transitive ImportError to propagate.\n"
            f"stdout: {stdout}\nstderr: {stderr}"
        )

    def test_transitive_dep_failure_judge_propagates(self, isolated_dir):
        """ImportError from a transitive dependency inside memory_logger must propagate (judge)."""
        bad_logger = isolated_dir / "memory_logger.py"
        bad_logger.write_text(
            "import nonexistent_transitive_dependency_xyzzy\n"
            "def emit_event(*a, **kw): pass\n"
            "def get_session_id(*a, **kw): return ''\n"
            "def parse_logging_config(*a, **kw): return {}\n",
            encoding="utf-8",
        )

        snippet = self._build_path_setup(isolated_dir) + self.textwrap.dedent(f"""\
            try:
                import memory_judge
                print("UNEXPECTED_SUCCESS")
            except ImportError as e:
                print(f"IMPORT_ERROR:{{e.name}}")
            except Exception as e:
                print(f"OTHER_ERROR:{{type(e).__name__}}:{{e}}")
        """)
        rc, stdout, stderr = self._run_snippet(isolated_dir, snippet)
        assert "IMPORT_ERROR:nonexistent_transitive_dependency_xyzzy" in stdout, (
            f"Expected transitive ImportError to propagate.\n"
            f"stdout: {stdout}\nstderr: {stderr}"
        )


# ===================================================================
# A-06: Cleanup latency under accumulated logs
# ===================================================================

class TestCleanupLatencyUnderLoad:
    """Verify emit_event p95 stays under 50ms even when cleanup must scan
    many accumulated log files across multiple category directories.

    Production scenario: after 14+ days of logging, cleanup_old_logs() inside
    emit_event() will scan 7 category dirs x 14 files each = 98 files.
    Some files are beyond retention and should be deleted; recent ones kept.
    """

    def _build_accumulated_log_tree(self, root):
        """Create a realistic accumulated log tree under root/logs/.

        Layout: 7 category dirs, each with 14 .jsonl files.
        - 4 files per category are >30 days old (should be deleted)
        - 10 files per category are recent (should be preserved)
        Sets .last_cleanup mtime to >24h ago so cleanup actually fires.
        """
        log_root = Path(root) / "logs"
        categories = [
            "retrieval", "triage", "judge", "write",
            "validate", "enforce", "search",
        ]
        now = time.time()
        old_mtime = now - (30 * 86400)    # 30 days ago
        recent_mtime = now - (2 * 86400)  # 2 days ago

        old_files = []
        recent_files = []

        for cat in categories:
            cat_dir = log_root / cat
            cat_dir.mkdir(parents=True, exist_ok=True)
            for i in range(14):
                fname = f"2025-{(i + 1):02d}-15.jsonl"
                fpath = cat_dir / fname
                # Write a realistic-size log line
                line = json.dumps({
                    "schema_version": 1,
                    "timestamp": "2025-01-15T12:00:00.000Z",
                    "event_type": f"{cat}.test",
                    "level": "info",
                    "hook": "UserPromptSubmit",
                    "script": "memory_retrieve.py",
                    "session_id": f"session-{i}",
                    "duration_ms": 3.5,
                    "data": {
                        "query_tokens": ["test"],
                        "results": [
                            {"path": f"entry-{j}.json", "score": -j}
                            for j in range(5)
                        ],
                    },
                    "error": None,
                }) + "\n"
                fpath.write_text(line * 10)  # ~10 lines per file

                if i < 4:
                    # Old files: beyond retention
                    os.utime(str(fpath), (old_mtime, old_mtime))
                    old_files.append(fpath)
                else:
                    # Recent files: within retention
                    os.utime(str(fpath), (recent_mtime, recent_mtime))
                    recent_files.append(fpath)

        # Set .last_cleanup mtime to >24h ago so cleanup will actually run
        last_cleanup = log_root / ".last_cleanup"
        stale_ts = now - (_CLEANUP_INTERVAL_S + 100)
        last_cleanup.write_text(str(stale_ts))
        os.utime(str(last_cleanup), (stale_ts, stale_ts))

        return old_files, recent_files

    def test_emit_with_cleanup_under_50ms(self, tmp_path):
        """emit_event latency including cleanup of 98 accumulated files stays under 50ms."""
        root = tmp_path / "memory"
        root.mkdir()
        cfg = _enabled_config(retention_days=14)

        old_files, recent_files = self._build_accumulated_log_tree(root)

        # Verify setup: 7 categories x 4 old = 28 old files
        assert len(old_files) == 28
        # Verify setup: 7 categories x 10 recent = 70 recent files
        assert len(recent_files) == 70

        # Measure a single emit_event call that triggers cleanup
        start = time.perf_counter()
        emit_event(
            "retrieval.search",
            {"query_tokens": ["auth", "jwt"], "results": []},
            level="info",
            memory_root=str(root),
            config=cfg,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 50.0, \
            f"emit_event + cleanup took {elapsed_ms:.2f}ms, exceeding 50ms budget"

    def test_old_files_deleted_recent_preserved(self, tmp_path):
        """After emit_event triggers cleanup, old files are gone and recent files remain."""
        root = tmp_path / "memory"
        root.mkdir()
        cfg = _enabled_config(retention_days=14)

        old_files, recent_files = self._build_accumulated_log_tree(root)

        emit_event(
            "retrieval.search",
            {"query_tokens": ["test"]},
            level="info",
            memory_root=str(root),
            config=cfg,
        )

        # All old files (>30 days) should be deleted
        for f in old_files:
            assert not f.exists(), f"Old file should have been deleted: {f.name}"

        # All recent files (2 days old) should be preserved
        for f in recent_files:
            assert f.exists(), f"Recent file should be preserved: {f.name}"


# ===================================================================
# A-07: Large payload concurrent append (PIPE_BUF boundary)
# ===================================================================

class TestLargePayloadConcurrentAppend:
    """Verify that concurrent writes of realistic ~3-4KB payloads produce
    valid, non-interleaved JSONL lines.

    POSIX O_APPEND guarantees atomic seek-to-end+write for regular files.
    On Linux, the VFS inode lock (i_rwsem) makes writes atomic for any size.
    Real retrieval.search events with 20 results can reach 2-4KB.
    """

    def test_large_payload_no_corruption(self, tmp_path):
        """8 threads x 20 writes of ~3.5KB payloads produce 160 valid JSONL lines."""
        root = tmp_path / "memory"
        root.mkdir()
        cfg = _enabled_config()

        # Build a payload that produces a JSONL line near 3.5-4KB.
        # Each result entry is ~150 bytes; 20 results ~ 3KB + envelope ~ 3.5KB.
        large_results = [
            {
                "path": f"memories/decisions/entry-{i:04d}.json",
                "score": -(i * 0.1),
                "title": f"Decision about component {i}",
                "snippet": f"Architecture note for result {i} with context",
            }
            for i in range(20)
        ]

        num_threads = 8
        writes_per_thread = 20
        expected_total = num_threads * writes_per_thread  # 160

        def worker(thread_id):
            for seq in range(writes_per_thread):
                emit_event(
                    "retrieval.search",
                    {
                        "query_tokens": ["auth", "jwt", "token", "session"],
                        "results": large_results,
                        "thread_id": thread_id,
                        "seq": seq,
                    },
                    level="info",
                    hook="UserPromptSubmit",
                    script="memory_retrieve.py",
                    session_id=f"session-thread-{thread_id}",
                    duration_ms=42.5,
                    memory_root=str(root),
                    config=cfg,
                )

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            list(executor.map(worker, range(num_threads)))

        lines = _read_log_lines(root)

        # Verify total line count
        assert len(lines) == expected_total, \
            f"Expected {expected_total} lines, got {len(lines)}"

        # Verify every line is valid JSON with correct schema
        for idx, line in enumerate(lines):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as e:
                # Show a useful snippet on failure
                snippet = line[:200] + "..." if len(line) > 200 else line
                pytest.fail(
                    f"Line {idx} is not valid JSON (interleaving/corruption): "
                    f"{e}\nSnippet: {snippet}"
                )
            assert parsed["schema_version"] == 1, \
                f"Line {idx} missing schema_version"
            assert parsed["event_type"] == "retrieval.search", \
                f"Line {idx} wrong event_type: {parsed.get('event_type')}"

    def test_payload_size_near_pipe_buf(self, tmp_path):
        """Verify the test payload is a realistic production size (2-4KB)."""
        root = tmp_path / "memory"
        root.mkdir()
        cfg = _enabled_config()

        large_results = [
            {
                "path": f"memories/decisions/entry-{i:04d}.json",
                "score": -(i * 0.1),
                "title": f"Decision about component {i}",
                "snippet": f"Architecture note for result {i} with context",
            }
            for i in range(20)
        ]

        emit_event(
            "retrieval.search",
            {
                "query_tokens": ["auth", "jwt", "token", "session"],
                "results": large_results,
                "thread_id": 0,
                "seq": 0,
            },
            level="info",
            hook="UserPromptSubmit",
            script="memory_retrieve.py",
            session_id="session-size-check",
            duration_ms=42.5,
            memory_root=str(root),
            config=cfg,
        )

        lines = _read_log_lines(root)
        assert len(lines) == 1
        line_bytes = len(lines[0].encode("utf-8"))
        # Should be between 2KB and 4KB (realistic production payload size)
        assert line_bytes >= 2048, \
            f"Payload too small ({line_bytes} bytes), not testing realistic size"
        assert line_bytes <= 4096, \
            f"Payload ({line_bytes} bytes) exceeds 4KB realistic ceiling"


# ===================================================================
# A-04: End-to-end integration (retrieval pipeline -> JSONL on disk)
# ===================================================================

import subprocess as _subprocess_mod

_E2E_SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
_E2E_RETRIEVE_SCRIPT = str(_E2E_SCRIPTS_DIR / "memory_retrieve.py")
_E2E_PYTHON = sys.executable


def _make_e2e_decision(id_val="use-jwt", title="Use JWT for authentication",
                       tags=None):
    """Minimal valid decision memory for e2e tests."""
    return {
        "schema_version": "1.0",
        "category": "decision",
        "id": id_val,
        "title": title,
        "record_status": "active",
        "created_at": "2026-01-15T10:00:00Z",
        "updated_at": "2026-02-10T10:00:00Z",
        "tags": tags or ["auth", "jwt", "security"],
        "confidence": 0.9,
        "content": {
            "status": "accepted",
            "context": "Need stateless auth for API",
            "decision": "Use JWT tokens with 1h expiry",
            "rationale": ["Stateless", "Industry standard"],
            "alternatives": [{"option": "Session cookies",
                              "rejected_reason": "Not stateless"}],
            "consequences": ["Must handle token refresh"],
        },
        "changes": [],
        "times_updated": 0,
    }


def _make_e2e_preference(id_val="prefer-typescript",
                         title="Prefer TypeScript over JavaScript",
                         tags=None):
    """Minimal valid preference memory for e2e tests."""
    return {
        "schema_version": "1.0",
        "category": "preference",
        "id": id_val,
        "title": title,
        "record_status": "active",
        "created_at": "2026-01-10T08:00:00Z",
        "updated_at": "2026-02-01T08:00:00Z",
        "tags": tags or ["typescript", "language"],
        "confidence": 0.95,
        "content": {
            "topic": "Programming language choice",
            "value": "TypeScript",
            "reason": "Better type safety and tooling",
            "strength": "strong",
            "examples": {
                "prefer": ["TypeScript for new projects"],
                "avoid": ["Plain JavaScript for anything beyond scripts"],
            },
        },
        "changes": [],
        "times_updated": 0,
    }


def _make_e2e_runbook(id_val="fix-db-connection",
                      title="Fix database connection timeout",
                      tags=None):
    """Minimal valid runbook memory for e2e tests."""
    return {
        "schema_version": "1.0",
        "category": "runbook",
        "id": id_val,
        "title": title,
        "record_status": "active",
        "created_at": "2026-01-25T14:00:00Z",
        "updated_at": "2026-02-01T14:00:00Z",
        "tags": tags or ["database", "connection", "timeout"],
        "confidence": 0.8,
        "content": {
            "trigger": "Database connection timeout errors in logs",
            "symptoms": ["Slow queries", "Connection pool exhaustion"],
            "steps": ["Check connection pool size", "Restart pool", "Monitor"],
            "verification": "Query response time < 100ms",
            "root_cause": "Connection leak in ORM",
            "environment": "Production PostgreSQL cluster",
        },
        "changes": [],
        "times_updated": 0,
    }


_E2E_FOLDER_MAP = {
    "session_summary": "sessions",
    "decision": "decisions",
    "runbook": "runbooks",
    "constraint": "constraints",
    "tech_debt": "tech-debt",
    "preference": "preferences",
}

_E2E_CATEGORY_DISPLAY = {
    "decision": "DECISION",
    "preference": "PREFERENCE",
    "runbook": "RUNBOOK",
    "constraint": "CONSTRAINT",
    "tech_debt": "TECH_DEBT",
    "session_summary": "SESSION_SUMMARY",
}


def _build_e2e_index(*memories, path_prefix=".claude/memory"):
    """Build enriched index.md from memory dicts (self-contained)."""
    lines = [
        "# Memory Index",
        "",
        "<!-- Auto-generated by memory_index.py. Do not edit manually. -->",
        "",
    ]
    for m in memories:
        cat = m["category"]
        display = _E2E_CATEGORY_DISPLAY.get(cat, cat.upper())
        folder = _E2E_FOLDER_MAP[cat]
        path = f"{path_prefix}/{folder}/{m['id']}.json"
        tags = m.get("tags", [])
        line = f"- [{display}] {m['title']} -> {path}"
        if tags:
            line += f" #tags:{','.join(tags)}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def _setup_e2e_project(tmp_path, memories, logging_config=None):
    """Create a full project directory with memories, index, and config.

    Returns (project_dir, memory_root).
    """
    proj = tmp_path / "project"
    proj.mkdir()
    dc = proj / ".claude"
    dc.mkdir()
    mem_root = dc / "memory"
    mem_root.mkdir()
    for folder in ["sessions", "decisions", "runbooks", "constraints",
                    "tech-debt", "preferences"]:
        (mem_root / folder).mkdir()

    # Write memory JSON files
    for m in memories:
        cat = m["category"]
        folder = _E2E_FOLDER_MAP[cat]
        fp = mem_root / folder / f"{m['id']}.json"
        fp.write_text(json.dumps(m, indent=2), encoding="utf-8")

    # Build and write index.md
    index_content = _build_e2e_index(*memories)
    (mem_root / "index.md").write_text(index_content, encoding="utf-8")

    # Write memory-config.json
    cfg = logging_config or {
        "retrieval": {"enabled": True, "max_inject": 3},
        "logging": {"enabled": True, "level": "debug", "retention_days": 14},
    }
    (mem_root / "memory-config.json").write_text(
        json.dumps(cfg, indent=2), encoding="utf-8"
    )

    return proj, mem_root


def _run_e2e_retrieve(hook_input):
    """Run memory_retrieve.py as subprocess, returning (stdout, stderr, rc)."""
    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    result = _subprocess_mod.run(
        [_E2E_PYTHON, _E2E_RETRIEVE_SCRIPT],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=15,
        env=env,
    )
    return result.stdout, result.stderr, result.returncode


def _collect_e2e_log_entries(memory_root):
    """Read all JSONL log entries from {memory_root}/logs/.

    Returns list of (filename_date, entry_dict) tuples, ordered by
    file path then line position (preserving write order within a file).
    """
    log_dir = Path(memory_root) / "logs"
    entries = []
    if not log_dir.exists():
        return entries
    for cat_dir in sorted(log_dir.iterdir()):
        if cat_dir.is_dir() and not cat_dir.name.startswith("."):
            for f in sorted(cat_dir.iterdir()):
                if f.suffix == ".jsonl":
                    filename_date = f.stem
                    for line in f.read_text("utf-8").strip().splitlines():
                        if line.strip():
                            entries.append((filename_date, json.loads(line)))
    return entries


# Known event types produced by retrieval pipeline
# Note: retrieval.judge_result (debug, requires judge enabled) and
# retrieval.fallback (warning, requires FTS5 unavailable) are included
# for completeness but not triggered by standard E2E tests since
# the judge is disabled (no API key) and FTS5 is always available.
_E2E_KNOWN_EVENT_TYPES = frozenset({
    "retrieval.skip",
    "retrieval.search",
    "retrieval.inject",
    "retrieval.judge_result",  # debug-only, judge must be enabled
    "retrieval.fallback",      # warning-only, FTS5 must be unavailable
})

# Required keys for each event type's data dict
# V2-02 fix: added candidates_post_threshold to retrieval.search
_E2E_EVENT_DATA_KEYS = {
    "retrieval.skip": {"reason"},
    "retrieval.search": {"query_tokens", "engine", "candidates_found", "candidates_post_threshold"},
    "retrieval.inject": {"injected_count", "results"},
    "retrieval.judge_result": {"candidates_post_judge", "judge_active"},
    "retrieval.fallback": {"engine", "reason"},
}


class TestEndToEndLogging:
    """A-04: End-to-end integration tests verifying actual JSONL output
    produced by the retrieval pipeline running as a subprocess.

    These tests validate that real pipeline execution (not synthetic
    emit_event calls) produces correct, schema-valid JSONL log entries.
    """

    def test_full_pipeline_produces_valid_jsonl(self, tmp_path):
        """Run retrieval with a matching prompt and verify all JSONL entries.

        Checks: schema_version, timestamp/filename match, known event_type,
        data dict keys, duration_ms validity, session_id, hook, script, level.
        """
        decision = _make_e2e_decision()
        preference = _make_e2e_preference()
        runbook = _make_e2e_runbook()
        proj, mem_root = _setup_e2e_project(
            tmp_path, [decision, preference, runbook]
        )

        hook_input = {
            "user_prompt": "How does JWT authentication work in this project?",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-e2e-test-abc.json",
        }

        stdout, stderr, rc = _run_e2e_retrieve(hook_input)
        assert rc == 0, f"retrieve exited with rc={rc}, stderr={stderr}"

        # The prompt should match the JWT decision memory
        assert "<memory-context" in stdout or "use-jwt" in stdout, \
            f"Expected matching output but got: {stdout[:200]}"

        # Collect all log entries
        log_entries = _collect_e2e_log_entries(mem_root)
        assert len(log_entries) >= 2, \
            f"Expected >= 2 log events (search + inject), got {len(log_entries)}"

        seen_types = set()

        for filename_date, entry in log_entries:
            # schema_version
            assert entry["schema_version"] == 1, \
                f"schema_version should be 1, got {entry.get('schema_version')}"

            # timestamp matches filename date
            ts = entry["timestamp"]
            assert ts.endswith("Z"), f"timestamp should end with Z: {ts}"
            timestamp_date = ts[:10]
            assert filename_date == timestamp_date, \
                f"Filename date {filename_date} != timestamp date {timestamp_date}"

            # event_type is known
            event_type = entry["event_type"]
            assert event_type in _E2E_KNOWN_EVENT_TYPES, \
                f"Unknown event_type: {event_type}"
            seen_types.add(event_type)

            # data dict contains expected keys
            data = entry["data"]
            assert isinstance(data, dict), \
                f"data should be dict, got {type(data)}"
            expected_keys = _E2E_EVENT_DATA_KEYS.get(event_type, set())
            missing = expected_keys - set(data.keys())
            assert not missing, \
                f"Event {event_type} missing data keys: {missing}"

            # duration_ms is positive finite (where present)
            dur = entry.get("duration_ms")
            if dur is not None:
                assert isinstance(dur, (int, float)), \
                    f"duration_ms should be numeric, got {type(dur)}"
                assert dur >= 0, f"duration_ms should be >= 0, got {dur}"
                assert dur < 1e9, f"duration_ms should be finite, got {dur}"

            # session_id is non-empty (derived from transcript_path)
            session_id = entry.get("session_id", "")
            assert session_id != "", \
                f"session_id should be non-empty for event {event_type}"
            assert "e2e-test" in session_id, \
                f"session_id should contain transcript stem, got: {session_id}"

            # hook and script
            assert entry["hook"] == "UserPromptSubmit", \
                f"hook should be UserPromptSubmit, got {entry.get('hook')}"
            assert entry["script"] == "memory_retrieve.py", \
                f"script should be memory_retrieve.py, got {entry.get('script')}"

            # level is valid
            assert entry["level"] in ("debug", "info", "warning", "error"), \
                f"Invalid level: {entry.get('level')}"

        # Verify we saw the key pipeline events
        assert "retrieval.search" in seen_types, \
            f"Missing retrieval.search event. Seen: {seen_types}"
        assert "retrieval.inject" in seen_types, \
            f"Missing retrieval.inject event. Seen: {seen_types}"

    def test_search_event_results_structure(self, tmp_path):
        """Verify the retrieval.search event results array has expected fields."""
        decision = _make_e2e_decision()
        proj, mem_root = _setup_e2e_project(tmp_path, [decision])

        hook_input = {
            "user_prompt": "How does JWT authentication work in this project?",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-results-check.json",
        }

        _run_e2e_retrieve(hook_input)

        log_entries = _collect_e2e_log_entries(mem_root)
        search_events = [
            e for _, e in log_entries if e["event_type"] == "retrieval.search"
        ]
        assert len(search_events) >= 1, \
            "Expected at least one retrieval.search event"

        search_data = search_events[0]["data"]
        assert "results" in search_data
        assert isinstance(search_data["results"], list)

        if search_data["results"]:
            result = search_data["results"][0]
            assert "path" in result, "result should have 'path'"
            assert "score" in result, "result should have 'score'"
            assert "confidence" in result, "result should have 'confidence'"
            # V2-05 fix: validate raw_bm25 and body_bonus per schema contract
            assert "raw_bm25" in result, "result should have 'raw_bm25'"
            assert "body_bonus" in result, "result should have 'body_bonus'"
            assert result["confidence"] in ("high", "medium", "low"), \
                f"confidence should be high/medium/low, got {result['confidence']}"

    def test_inject_event_results_structure(self, tmp_path):
        """Verify the retrieval.inject event has injected_count and results."""
        decision = _make_e2e_decision()
        proj, mem_root = _setup_e2e_project(tmp_path, [decision])

        hook_input = {
            "user_prompt": "How does JWT authentication work in this project?",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-inject-check.json",
        }

        _run_e2e_retrieve(hook_input)

        log_entries = _collect_e2e_log_entries(mem_root)
        inject_events = [
            e for _, e in log_entries if e["event_type"] == "retrieval.inject"
        ]
        assert len(inject_events) >= 1, \
            "Expected at least one retrieval.inject event"

        inject_data = inject_events[0]["data"]
        assert "injected_count" in inject_data
        assert isinstance(inject_data["injected_count"], int)
        assert inject_data["injected_count"] >= 1, \
            "Should inject at least 1 result"

        assert "results" in inject_data
        assert isinstance(inject_data["results"], list)
        assert len(inject_data["results"]) == inject_data["injected_count"]

        for r in inject_data["results"]:
            assert "path" in r
            assert "confidence" in r

    def test_short_prompt_skip_event(self, tmp_path):
        """Short prompt (< 10 chars) produces retrieval.skip with short_prompt.

        Validates A-01 fix: config is loaded before skip events, so
        short_prompt events are actually logged when logging is enabled.
        """
        decision = _make_e2e_decision()
        proj, mem_root = _setup_e2e_project(tmp_path, [decision])

        hook_input = {
            "user_prompt": "hi",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-skip-test.json",
        }

        stdout, stderr, rc = _run_e2e_retrieve(hook_input)
        assert rc == 0
        assert stdout.strip() == "", "Short prompt should produce no stdout"

        log_entries = _collect_e2e_log_entries(mem_root)
        assert len(log_entries) >= 1, \
            "Expected at least 1 log event for short prompt skip"

        skip_events = [
            e for _, e in log_entries if e["event_type"] == "retrieval.skip"
        ]
        assert len(skip_events) >= 1, (
            f"Expected retrieval.skip event. Got types: "
            f"{[e['event_type'] for _, e in log_entries]}"
        )

        skip_data = skip_events[0]["data"]
        assert skip_data["reason"] == "short_prompt", \
            f"Expected reason='short_prompt', got {skip_data.get('reason')}"
        assert "prompt_length" in skip_data, \
            "skip event should include prompt_length"
        assert skip_data["prompt_length"] == 2, \
            f"Expected prompt_length=2 for 'hi', got {skip_data['prompt_length']}"

        # Verify schema on the skip event too
        skip_entry = skip_events[0]
        assert skip_entry["schema_version"] == 1
        assert skip_entry["session_id"] != ""
        assert "skip-test" in skip_entry["session_id"]

    def test_empty_prompt_skip_event(self, tmp_path):
        """Very short trimmed prompt also triggers short_prompt skip."""
        decision = _make_e2e_decision()
        proj, mem_root = _setup_e2e_project(tmp_path, [decision])

        hook_input = {
            "user_prompt": "  ok  ",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-empty-skip.json",
        }

        _run_e2e_retrieve(hook_input)

        log_entries = _collect_e2e_log_entries(mem_root)
        skip_events = [
            e for _, e in log_entries if e["event_type"] == "retrieval.skip"
        ]
        assert len(skip_events) >= 1, \
            "Expected retrieval.skip for short prompt"
        assert skip_events[0]["data"]["reason"] == "short_prompt"

    def test_no_match_produces_skip_or_no_inject(self, tmp_path):
        """Prompt with no matching memories logs search but no inject."""
        decision = _make_e2e_decision()
        proj, mem_root = _setup_e2e_project(tmp_path, [decision])

        hook_input = {
            "user_prompt": "What is the weather forecast for tomorrow morning?",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-no-match.json",
        }

        stdout, stderr, rc = _run_e2e_retrieve(hook_input)
        assert rc == 0

        log_entries = _collect_e2e_log_entries(mem_root)
        # B-01 fix: assert pipeline produced log output (prevents vacuous pass on crash)
        assert len(log_entries) >= 1, \
            "Pipeline should produce at least one log event even for non-matching queries"

        inject_events = [
            e for _, e in log_entries
            if e["event_type"] == "retrieval.inject"
        ]
        skip_events = [
            e for _, e in log_entries
            if e["event_type"] == "retrieval.skip"
        ]

        # At least one of: skip logged, or no inject
        assert len(skip_events) >= 1 or len(inject_events) == 0, \
            "With no matches, expect either skip event or no inject event"

    def test_logging_disabled_no_log_files(self, tmp_path):
        """When logging is disabled in config, no log files are created."""
        decision = _make_e2e_decision()
        cfg = {
            "retrieval": {"enabled": True, "max_inject": 3},
            "logging": {"enabled": False},
        }
        proj, mem_root = _setup_e2e_project(
            tmp_path, [decision], logging_config=cfg
        )

        hook_input = {
            "user_prompt": "How does JWT authentication work in this project?",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-disabled.json",
        }

        _run_e2e_retrieve(hook_input)

        log_dir = mem_root / "logs"
        assert not log_dir.exists(), \
            "No log directory should be created when logging is disabled"

    def test_multiple_memories_pipeline(self, tmp_path):
        """Pipeline with multiple matching memories produces correct events.

        Uses two decision memories with very similar content so FTS5 BM25
        scores are close enough that both survive the 25% noise floor.
        """
        decision1 = _make_e2e_decision(
            id_val="auth-jwt-tokens",
            title="Use JWT tokens for authentication",
            tags=["auth", "jwt", "tokens"],
        )
        decision2 = _make_e2e_decision(
            id_val="auth-jwt-refresh",
            title="JWT token refresh authentication flow",
            tags=["auth", "jwt", "tokens"],
        )

        proj, mem_root = _setup_e2e_project(
            tmp_path, [decision1, decision2]
        )

        hook_input = {
            "user_prompt": "How does JWT token authentication work in this project?",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-multi-match.json",
        }

        stdout, stderr, rc = _run_e2e_retrieve(hook_input)
        assert rc == 0

        log_entries = _collect_e2e_log_entries(mem_root)

        event_types = [e["event_type"] for _, e in log_entries]
        assert "retrieval.search" in event_types
        assert "retrieval.inject" in event_types

        inject_events = [
            e for _, e in log_entries
            if e["event_type"] == "retrieval.inject"
        ]
        assert inject_events[0]["data"]["injected_count"] >= 2, \
            "Two similar memories should produce >= 2 injected results"

    def test_log_entries_ordered_by_pipeline_stage(self, tmp_path):
        """Log entries follow pipeline order: search before inject."""
        decision = _make_e2e_decision()
        proj, mem_root = _setup_e2e_project(tmp_path, [decision])

        hook_input = {
            "user_prompt": "How does JWT authentication work in this project?",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-order-test.json",
        }

        _run_e2e_retrieve(hook_input)

        # B-02 fix: hard-assert log directory and event presence (no vacuous pass)
        log_dir = mem_root / "logs" / "retrieval"
        assert log_dir.exists(), \
            "Log directory should exist after pipeline execution"

        ordered_entries = []
        for f in sorted(log_dir.iterdir()):
            if f.suffix == ".jsonl":
                for line in f.read_text("utf-8").strip().splitlines():
                    if line.strip():
                        ordered_entries.append(json.loads(line))

        event_types = [e["event_type"] for e in ordered_entries]
        assert "retrieval.search" in event_types, \
            f"Expected retrieval.search event. Seen: {event_types}"
        assert "retrieval.inject" in event_types, \
            f"Expected retrieval.inject event. Seen: {event_types}"

        search_idx = event_types.index("retrieval.search")
        inject_idx = event_types.index("retrieval.inject")
        assert search_idx < inject_idx, \
            f"search (idx={search_idx}) should precede " \
            f"inject (idx={inject_idx})"

    def test_inject_duration_covers_full_pipeline(self, tmp_path):
        """retrieval.inject duration_ms >= retrieval.search duration_ms."""
        decision = _make_e2e_decision()
        proj, mem_root = _setup_e2e_project(tmp_path, [decision])

        hook_input = {
            "user_prompt": "How does JWT authentication work in this project?",
            "cwd": str(proj),
            "transcript_path": "/tmp/transcript-duration-test.json",
        }

        _run_e2e_retrieve(hook_input)

        # B-03 fix: hard-assert event presence and duration (no vacuous pass)
        log_entries = _collect_e2e_log_entries(mem_root)
        search_events = [
            e for _, e in log_entries if e["event_type"] == "retrieval.search"
        ]
        inject_events = [
            e for _, e in log_entries if e["event_type"] == "retrieval.inject"
        ]

        assert len(search_events) >= 1, \
            f"Expected retrieval.search event. Types: {[e['event_type'] for _, e in log_entries]}"
        assert len(inject_events) >= 1, \
            f"Expected retrieval.inject event. Types: {[e['event_type'] for _, e in log_entries]}"

        search_dur = search_events[0].get("duration_ms")
        inject_dur = inject_events[0].get("duration_ms")
        assert search_dur is not None, \
            "retrieval.search should have duration_ms"
        assert inject_dur is not None, \
            "retrieval.inject should have duration_ms"
        assert inject_dur >= search_dur, \
            f"inject duration ({inject_dur}ms) should >= " \
            f"search duration ({search_dur}ms)"


# ===================================================================
# A-08: Operational Workflow Smoke Tests
# ===================================================================

class TestOperationalWorkflowSmoke:
    """A-08: Config-driven operational behavior.

    Tests the user-facing config workflows:
    enabled/disabled toggling, level filtering interactions,
    retention_days=0 disabling cleanup, and missing config fallback.
    """

    def test_enabled_true_starts_logging(self, tmp_path):
        """logging.enabled: true -> logging produces output files."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"query_tokens": ["test"]},
            memory_root=str(root),
            config={"logging": {"enabled": True, "level": "info"}},
        )
        lines = _read_log_lines(root)
        assert len(lines) == 1, "Enabled logging should produce exactly one log line"
        entry = json.loads(lines[0])
        assert entry["event_type"] == "retrieval.search"

    def test_level_debug_shows_debug_events(self, tmp_path):
        """logging.level: 'debug' -> debug-level events appear in logs."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.judge_result",
            {"candidates_post_judge": 3, "judge_active": True},
            level="debug",
            memory_root=str(root),
            config=_enabled_config(level="debug"),
        )
        lines = _read_log_lines(root)
        assert len(lines) == 1, "Debug level config should allow debug events"
        entry = json.loads(lines[0])
        assert entry["level"] == "debug"

    def test_level_error_filters_out_info(self, tmp_path):
        """logging.level: 'error' -> info events are filtered out."""
        root = tmp_path / "memory"
        root.mkdir()
        # Emit info-level event
        emit_event(
            "retrieval.search",
            {"query_tokens": ["auth"]},
            level="info",
            memory_root=str(root),
            config=_enabled_config(level="error"),
        )
        # Emit warning-level event
        emit_event(
            "judge.error",
            {"error_type": "timeout"},
            level="warning",
            memory_root=str(root),
            config=_enabled_config(level="error"),
        )
        # Emit error-level event
        emit_event(
            "judge.error",
            {"error_type": "api_failure"},
            level="error",
            memory_root=str(root),
            config=_enabled_config(level="error"),
        )
        lines = _read_log_lines(root)
        assert len(lines) == 1, \
            f"Only error events should pass; got {len(lines)} lines"
        entry = json.loads(lines[0])
        assert entry["level"] == "error"
        assert entry["data"]["error_type"] == "api_failure"

    def test_level_error_filters_debug_and_info_but_keeps_error(self, tmp_path):
        """logging.level: 'error' -> debug and info filtered, error retained."""
        root = tmp_path / "memory"
        root.mkdir()
        for lvl in ("debug", "info", "warning", "error"):
            emit_event(
                "test.event",
                {"level_test": lvl},
                level=lvl,
                memory_root=str(root),
                config=_enabled_config(level="error"),
            )
        lines = _read_log_lines(root)
        assert len(lines) == 1
        assert json.loads(lines[0])["level"] == "error"

    def test_disabled_false_stops_logging_preserves_existing(self, tmp_path):
        """logging.enabled: false -> no new logs, but existing files preserved."""
        root = tmp_path / "memory"
        root.mkdir()
        # First, emit with enabled=true
        emit_event(
            "retrieval.search",
            {"query_tokens": ["first"]},
            memory_root=str(root),
            config=_enabled_config(),
        )
        lines_before = _read_log_lines(root)
        assert len(lines_before) == 1, "Pre-condition: one log line exists"

        # Capture existing log files
        log_dir = root / "logs"
        existing_files = list(log_dir.rglob("*.jsonl"))
        assert len(existing_files) > 0

        # Now emit with enabled=false
        emit_event(
            "retrieval.search",
            {"query_tokens": ["second"]},
            memory_root=str(root),
            config={"logging": {"enabled": False}},
        )

        # Existing files should still be there
        for f in existing_files:
            assert f.exists(), f"Existing log file {f.name} should be preserved"

        # No new lines should have been added
        lines_after = _read_log_lines(root)
        assert len(lines_after) == 1, \
            "Disabled logging should not add new log lines"

    def test_retention_days_zero_disables_cleanup(self, tmp_path):
        """logging.retention_days: 0 -> cleanup_old_logs returns immediately."""
        log_root = tmp_path / "logs"
        cat_dir = log_root / "retrieval"
        cat_dir.mkdir(parents=True)

        # Create an "old" file (set mtime to 30 days ago)
        old_file = cat_dir / "2020-01-01.jsonl"
        old_file.write_text('{"old":true}\n')
        old_mtime = time.time() - (30 * 86400)
        os.utime(str(old_file), (old_mtime, old_mtime))

        # Call cleanup with retention_days=0
        cleanup_old_logs(log_root, retention_days=0)

        # Old file should still exist (cleanup disabled)
        assert old_file.exists(), \
            "retention_days=0 should disable cleanup entirely"

    def test_retention_days_zero_via_emit_event(self, tmp_path):
        """Full emit_event with retention_days=0 does not delete old logs."""
        root = tmp_path / "memory"
        root.mkdir()
        log_root = root / "logs" / "retrieval"
        log_root.mkdir(parents=True)

        # Create an old file
        old_file = log_root / "2020-01-01.jsonl"
        old_file.write_text('{"old":true}\n')
        old_mtime = time.time() - (30 * 86400)
        os.utime(str(old_file), (old_mtime, old_mtime))

        # Emit event with retention_days=0
        emit_event(
            "retrieval.search",
            {"query_tokens": ["test"]},
            memory_root=str(root),
            config=_enabled_config(retention_days=0),
        )

        # Verify emit_event actually ran to completion (not a vacuous pass
        # due to fail-open swallowing an early exception)
        lines = _read_log_lines(root)
        assert len(lines) >= 1, \
            "emit_event should have written a new log line (proves it ran to completion)"

        assert old_file.exists(), \
            "retention_days=0 via emit_event should not trigger cleanup"

    def test_missing_config_falls_back_to_disabled(self, tmp_path):
        """Missing config (None) -> falls back to disabled (no I/O)."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"query_tokens": ["test"]},
            memory_root=str(root),
            config=None,
        )
        assert not (root / "logs").exists(), \
            "config=None should default to disabled, creating no log directory"

    def test_empty_dict_config_falls_back_to_disabled(self, tmp_path):
        """Empty config dict {} -> falls back to disabled."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"query_tokens": ["test"]},
            memory_root=str(root),
            config={},
        )
        assert not (root / "logs").exists(), \
            "Empty config should default to disabled"

    def test_workflow_enable_emit_disable_emit(self, tmp_path):
        """Full workflow: enable -> emit -> disable -> emit -> verify."""
        root = tmp_path / "memory"
        root.mkdir()

        # Step 1: Enable and emit
        emit_event(
            "retrieval.search",
            {"step": 1},
            memory_root=str(root),
            config=_enabled_config(),
        )
        assert len(_read_log_lines(root)) == 1

        # Step 2: Disable and emit
        emit_event(
            "retrieval.search",
            {"step": 2},
            memory_root=str(root),
            config={"logging": {"enabled": False}},
        )
        # Still only 1 line
        assert len(_read_log_lines(root)) == 1

        # Step 3: Re-enable and emit
        emit_event(
            "retrieval.search",
            {"step": 3},
            memory_root=str(root),
            config=_enabled_config(),
        )
        lines = _read_log_lines(root)
        assert len(lines) == 2
        entries = [json.loads(l) for l in lines]
        steps = [e["data"]["step"] for e in entries]
        assert steps == [1, 3], "Only steps 1 and 3 should be logged"

    def test_level_change_between_emits(self, tmp_path):
        """Changing level between emits correctly filters."""
        root = tmp_path / "memory"
        root.mkdir()

        # Emit debug event with debug level -> should appear
        emit_event(
            "retrieval.judge_result",
            {"phase": "debug-phase"},
            level="debug",
            memory_root=str(root),
            config=_enabled_config(level="debug"),
        )
        # Emit debug event with info level -> should NOT appear
        emit_event(
            "retrieval.judge_result",
            {"phase": "info-phase"},
            level="debug",
            memory_root=str(root),
            config=_enabled_config(level="info"),
        )
        lines = _read_log_lines(root)
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["data"]["phase"] == "debug-phase"


# ===================================================================
# A-09: Truncation Metadata Enhancement
# ===================================================================

class TestTruncationMetadata:
    """A-09: When results[] is truncated, preserve original count metadata.

    When data.results has > 20 entries, the logged data dict should include:
    - _truncated: True
    - _original_results_count: <original length>

    When data.results has <= 20 entries, these keys should NOT be present.
    """

    def test_no_truncation_metadata_when_within_limit(self, tmp_path):
        """results with <= 20 entries: no _truncated or _original_results_count."""
        root = tmp_path / "memory"
        root.mkdir()
        results = [{"path": f"entry-{i}.json", "score": -i} for i in range(15)]
        emit_event(
            "retrieval.search",
            {"results": results, "engine": "fts5_bm25"},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert "_truncated" not in entry["data"], \
            "No _truncated key when results within limit"
        assert "_original_results_count" not in entry["data"], \
            "No _original_results_count key when results within limit"
        assert len(entry["data"]["results"]) == 15

    def test_no_truncation_metadata_at_exact_limit(self, tmp_path):
        """results with exactly 20 entries: no truncation metadata."""
        root = tmp_path / "memory"
        root.mkdir()
        results = [{"path": f"entry-{i}.json"} for i in range(_MAX_RESULTS)]
        emit_event(
            "retrieval.search",
            {"results": results},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert "_truncated" not in entry["data"]
        assert "_original_results_count" not in entry["data"]
        assert len(entry["data"]["results"]) == _MAX_RESULTS

    def test_truncation_metadata_added_when_over_limit(self, tmp_path):
        """results with > 20 entries: _truncated=True and _original_results_count set."""
        root = tmp_path / "memory"
        root.mkdir()
        original_count = 50
        results = [{"path": f"entry-{i}.json", "score": -i} for i in range(original_count)]
        emit_event(
            "retrieval.search",
            {"results": results},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["data"]["_truncated"] is True
        assert entry["data"]["_original_results_count"] == original_count
        assert len(entry["data"]["results"]) == _MAX_RESULTS

    def test_truncation_metadata_at_21_entries(self, tmp_path):
        """Boundary: 21 entries (one over limit) triggers truncation metadata."""
        root = tmp_path / "memory"
        root.mkdir()
        results = [{"path": f"entry-{i}.json"} for i in range(21)]
        emit_event(
            "retrieval.search",
            {"results": results},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["data"]["_truncated"] is True
        assert entry["data"]["_original_results_count"] == 21
        assert len(entry["data"]["results"]) == _MAX_RESULTS

    def test_truncation_metadata_large_count(self, tmp_path):
        """Large results list (200 entries) preserves correct original count."""
        root = tmp_path / "memory"
        root.mkdir()
        original_count = 200
        results = [{"path": f"e-{i}.json"} for i in range(original_count)]
        emit_event(
            "retrieval.search",
            {"results": results},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["data"]["_truncated"] is True
        assert entry["data"]["_original_results_count"] == original_count
        assert len(entry["data"]["results"]) == _MAX_RESULTS

    def test_truncation_does_not_mutate_caller_data(self, tmp_path):
        """Truncation metadata does not leak into the caller's original dict."""
        root = tmp_path / "memory"
        root.mkdir()
        results = [{"path": f"entry-{i}.json"} for i in range(50)]
        original_data = {"results": results, "engine": "fts5_bm25"}
        emit_event(
            "retrieval.search",
            original_data,
            memory_root=str(root),
            config=_enabled_config(),
        )
        # Caller's dict must not have truncation metadata
        assert "_truncated" not in original_data, \
            "Caller's data dict must not be mutated with _truncated"
        assert "_original_results_count" not in original_data, \
            "Caller's data dict must not be mutated with _original_results_count"
        assert len(original_data["results"]) == 50, \
            "Caller's results list must not be modified"

    def test_no_metadata_when_results_is_empty_list(self, tmp_path):
        """Empty results list: no truncation metadata."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.search",
            {"results": []},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert "_truncated" not in entry["data"]
        assert "_original_results_count" not in entry["data"]
        assert entry["data"]["results"] == []

    def test_no_metadata_when_no_results_key(self, tmp_path):
        """data dict without 'results' key: no truncation metadata."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "retrieval.skip",
            {"reason": "short_prompt", "prompt_length": 5},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert "_truncated" not in entry["data"]
        assert "_original_results_count" not in entry["data"]


# ===================================================================
# A-11: Deterministic set serialization (_json_default)
# ===================================================================

from memory_logger import _json_default


class TestJsonDefaultSerializer:
    """A-11: _json_default converts sets to sorted lists for deterministic output."""

    def test_set_serialized_as_sorted_list(self):
        """Python set is converted to a sorted list."""
        result = _json_default({"c", "a", "b"})
        assert result == ["a", "b", "c"]

    def test_frozenset_serialized_as_sorted_list(self):
        """Python frozenset is converted to a sorted list."""
        result = _json_default(frozenset({"z", "m", "a"}))
        assert result == ["a", "m", "z"]

    def test_empty_set_serialized_as_empty_list(self):
        """Empty set becomes empty list."""
        result = _json_default(set())
        assert result == []

    def test_empty_frozenset_serialized_as_empty_list(self):
        """Empty frozenset becomes empty list."""
        result = _json_default(frozenset())
        assert result == []

    def test_datetime_uses_str_fallback(self):
        """Non-set types like datetime fall back to str()."""
        dt = datetime(2026, 2, 25, 10, 30, 0, tzinfo=timezone.utc)
        result = _json_default(dt)
        assert isinstance(result, str)
        assert "2026-02-25" in result

    def test_set_with_mixed_types_sorted_by_str(self):
        """Sets with mixed types are sorted by str() representation."""
        result = _json_default({3, 1, 2})
        assert result == [1, 2, 3]

    def test_set_determinism_across_calls(self):
        """Multiple calls with the same set produce identical output."""
        s = {"x", "a", "m", "z", "b"}
        results = [_json_default(s) for _ in range(10)]
        assert all(r == ["a", "b", "m", "x", "z"] for r in results), \
            "All iterations must produce identical sorted output"


class TestSetSerializationInEmitEvent:
    """A-11: End-to-end tests for set serialization through emit_event."""

    def test_set_in_data_produces_sorted_list_in_jsonl(self, tmp_path):
        """set in data dict -> sorted JSON array in output."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "test.event",
            {"tags": {"beta", "alpha", "gamma"}},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["data"]["tags"] == ["alpha", "beta", "gamma"]

    def test_frozenset_in_data_produces_sorted_list_in_jsonl(self, tmp_path):
        """frozenset in data dict -> sorted JSON array in output."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "test.event",
            {"ids": frozenset({3, 1, 2})},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["data"]["ids"] == [1, 2, 3]

    def test_normal_types_unaffected(self, tmp_path):
        """Normal serializable types (dict, list, str, int) are unchanged."""
        root = tmp_path / "memory"
        root.mkdir()
        data = {
            "string": "hello",
            "number": 42,
            "float": 3.14,
            "list": [1, 2, 3],
            "nested": {"key": "value"},
            "null": None,
            "bool": True,
        }
        emit_event(
            "test.event",
            data,
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["data"]["string"] == "hello"
        assert entry["data"]["number"] == 42
        assert entry["data"]["float"] == 3.14
        assert entry["data"]["list"] == [1, 2, 3]
        assert entry["data"]["nested"] == {"key": "value"}
        assert entry["data"]["null"] is None
        assert entry["data"]["bool"] is True

    def test_nested_set_in_data(self, tmp_path):
        """set nested inside a list within data is also serialized correctly."""
        root = tmp_path / "memory"
        root.mkdir()
        emit_event(
            "test.event",
            {"items": [{"tags": {"b", "a"}}]},
            memory_root=str(root),
            config=_enabled_config(),
        )
        entry = json.loads(_read_log_lines(root)[0])
        assert entry["data"]["items"][0]["tags"] == ["a", "b"]


# ===================================================================
# A-10: score_all_categories returns all 6 category scores
# ===================================================================

from memory_triage import (
    score_all_categories,
    CATEGORY_PATTERNS,
    run_triage,
    DEFAULT_THRESHOLDS,
)


class TestScoreAllCategories:
    """A-10: score_all_categories always returns all 6 categories."""

    def test_returns_all_six_categories(self):
        """Always returns exactly 6 entries (5 text + SESSION_SUMMARY)."""
        result = score_all_categories(
            "some text",
            {"tool_uses": 0, "distinct_tools": 0, "exchanges": 0},
        )
        assert len(result) == 6, f"Expected 6 categories, got {len(result)}"

    def test_returns_all_categories_even_with_empty_text(self):
        """Empty text still returns all 6 categories with zero scores."""
        result = score_all_categories(
            "", {"tool_uses": 0, "distinct_tools": 0, "exchanges": 0},
        )
        assert len(result) == 6
        for entry in result:
            assert entry["score"] == 0.0

    def test_category_names_match_expected(self):
        """Returned categories match CATEGORY_PATTERNS + SESSION_SUMMARY."""
        result = score_all_categories(
            "test", {"tool_uses": 0, "distinct_tools": 0, "exchanges": 0},
        )
        expected_cats = set(CATEGORY_PATTERNS.keys()) | {"SESSION_SUMMARY"}
        actual_cats = {r["category"] for r in result}
        assert actual_cats == expected_cats, \
            f"Expected {expected_cats}, got {actual_cats}"

    def test_no_snippets_in_output(self):
        """Output dicts must NOT contain snippets (privacy/size concern)."""
        text = "We decided to use OAuth because it is more secure"
        result = score_all_categories(
            text, {"tool_uses": 5, "distinct_tools": 2, "exchanges": 10},
        )
        for entry in result:
            assert "snippets" not in entry, \
                f"Category {entry['category']} should not have snippets"

    def test_only_category_and_score_keys(self):
        """Each entry has exactly 'category' and 'score' keys."""
        text = "We decided to use OAuth because it is secure"
        result = score_all_categories(
            text, {"tool_uses": 5, "distinct_tools": 2, "exchanges": 10},
        )
        for entry in result:
            assert set(entry.keys()) == {"category", "score"}, \
                f"Expected only category+score keys, got {set(entry.keys())}"

    def test_scores_are_rounded_to_4_decimals(self):
        """Scores should be rounded to 4 decimal places."""
        text = "We decided to use OAuth because it is secure"
        result = score_all_categories(
            text, {"tool_uses": 5, "distinct_tools": 2, "exchanges": 10},
        )
        for entry in result:
            score_str = str(entry["score"])
            if "." in score_str:
                decimals = len(score_str.split(".")[1])
                assert decimals <= 4, \
                    f"{entry['category']} score {entry['score']} has {decimals} decimals"

    def test_triggered_category_has_nonzero_score(self):
        """A category with clear keyword matches should have a non-zero score."""
        text = "We decided to use OAuth because it provides better security"
        result = score_all_categories(
            text, {"tool_uses": 0, "distinct_tools": 0, "exchanges": 0},
        )
        decision_score = next(r for r in result if r["category"] == "DECISION")
        assert decision_score["score"] > 0, \
            "DECISION category should have non-zero score with clear keyword match"

    def test_session_summary_nonzero_with_activity(self):
        """SESSION_SUMMARY should have non-zero score with sufficient activity."""
        metrics = {"tool_uses": 20, "distinct_tools": 5, "exchanges": 15}
        result = score_all_categories("", metrics)
        session_score = next(r for r in result if r["category"] == "SESSION_SUMMARY")
        assert session_score["score"] > 0, \
            "SESSION_SUMMARY should score non-zero with activity metrics"

    def test_consistency_with_run_triage(self):
        """Triggered scores from score_all_categories match run_triage results."""
        text = (
            "We decided to use OAuth because it is more secure. "
            "We also prefer to always use TypeScript going forward consistently."
        )
        metrics = {"tool_uses": 20, "distinct_tools": 5, "exchanges": 15}
        thresholds = DEFAULT_THRESHOLDS

        all_scores = score_all_categories(text, metrics)
        triggered = run_triage(text, metrics, thresholds)

        # Build lookup from all_scores
        all_map = {r["category"]: r["score"] for r in all_scores}

        # Every triggered category should have a matching score in all_scores
        for t in triggered:
            assert t["category"] in all_map, \
                f"Triggered category {t['category']} not in all_scores"
            assert round(t["score"], 4) == all_map[t["category"]], \
                f"Score mismatch for {t['category']}: " \
                f"triggered={round(t['score'], 4)} vs all={all_map[t['category']]}"


class TestTriageScoreEmitAllScores:
    """A-10: Verify that the triage.score emit_event includes all_scores field."""

    def test_all_scores_in_triage_score_data(self, tmp_path):
        """The triage.score event data should contain all_scores with 6 entries."""
        text = "We decided to use OAuth"
        metrics = {"tool_uses": 5, "distinct_tools": 2, "exchanges": 10}
        all_scores = score_all_categories(text, metrics)

        root = tmp_path / "memory"
        root.mkdir()

        # Simulate what _run_triage does for the emit_event call
        results = run_triage(text, metrics, DEFAULT_THRESHOLDS)
        data = {
            "text_len": len(text),
            "exchanges": metrics["exchanges"],
            "tool_uses": metrics["tool_uses"],
            "triggered": [
                {"category": r["category"], "score": round(r["score"], 4)}
                for r in results
            ],
            "all_scores": all_scores,
        }

        emit_event(
            "triage.score",
            data,
            hook="Stop",
            script="memory_triage.py",
            memory_root=str(root),
            config=_enabled_config(),
        )

        lines = _read_log_lines(root)
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert "all_scores" in entry["data"], \
            "triage.score event must contain all_scores field"
        assert len(entry["data"]["all_scores"]) == 6, \
            f"Expected 6 entries in all_scores, got {len(entry['data']['all_scores'])}"

    def test_all_scores_backwards_compatible_with_triggered(self, tmp_path):
        """triggered field still present alongside all_scores."""
        text = "We decided to use OAuth because it is secure"
        metrics = {"tool_uses": 5, "distinct_tools": 2, "exchanges": 10}
        all_scores = score_all_categories(text, metrics)
        results = run_triage(text, metrics, DEFAULT_THRESHOLDS)

        root = tmp_path / "memory"
        root.mkdir()

        data = {
            "text_len": len(text),
            "exchanges": metrics["exchanges"],
            "tool_uses": metrics["tool_uses"],
            "triggered": [
                {"category": r["category"], "score": round(r["score"], 4)}
                for r in results
            ],
            "all_scores": all_scores,
        }

        emit_event(
            "triage.score",
            data,
            hook="Stop",
            script="memory_triage.py",
            memory_root=str(root),
            config=_enabled_config(),
        )

        entry = json.loads(_read_log_lines(root)[0])
        # Both fields present
        assert "triggered" in entry["data"]
        assert "all_scores" in entry["data"]
        # triggered is a subset (by category) of all_scores
        triggered_cats = {t["category"] for t in entry["data"]["triggered"]}
        all_cats = {s["category"] for s in entry["data"]["all_scores"]}
        assert triggered_cats.issubset(all_cats), \
            f"triggered categories {triggered_cats} should be subset of all_scores {all_cats}"
