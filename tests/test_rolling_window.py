"""Tests for rolling window enforcement (memory_enforce.py) and
related memory_write.py changes (FlockIndex, retire_record).

24 test cases covering:
  - Tests 1-15: memory_enforce.py behavior
  - Tests 16-24: memory_write.py (FlockIndex, retire_record)
"""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from conftest import (
    make_session_memory,
    write_memory_file,
    build_enriched_index,
    write_index,
)

from memory_write import FlockIndex, retire_record, CATEGORY_FOLDERS, atomic_write_json


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_enforce_project(tmp_path, session_count, max_retained=5,
                           config_max_retained=None, extra_files=None):
    """Create a project structure with N active session files.

    Returns (proj, mem_root, session_files) where session_files is a list
    of Path objects sorted by created_at (oldest first).
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

    sessions = []
    memories = []
    for i in range(session_count):
        ts = f"2026-01-{10 + i:02d}T09:00:00Z"
        mem = make_session_memory(
            id_val=f"session-{i:03d}",
            title=f"Session {i}",
        )
        mem["created_at"] = ts
        mem["updated_at"] = ts
        fp = write_memory_file(mem_root, mem)
        sessions.append(fp)
        memories.append(mem)

    if extra_files:
        for ef in extra_files:
            fp = mem_root / "sessions" / ef["filename"]
            fp.write_text(ef["content"])

    # Write index for all memories
    if memories:
        write_index(mem_root, *memories, path_prefix=".claude/memory")

    # Write config if requested
    if config_max_retained is not None:
        config = {
            "categories": {
                "session_summary": {
                    "max_retained": config_max_retained,
                }
            }
        }
        (mem_root / "memory-config.json").write_text(json.dumps(config))

    return proj, mem_root, sessions


# ===========================================================================
# Tests 1-15: memory_enforce.py
# ===========================================================================

class TestEnforceRollingWindow:
    """Tests for enforce_rolling_window() and supporting functions."""

    def test_01_rolling_window_triggers_one_retirement(self, tmp_path):
        """6 active sessions, max_retained=5 -> retires 1 oldest."""
        from memory_enforce import enforce_rolling_window

        proj, mem_root, sessions = _setup_enforce_project(tmp_path, 6)
        result = enforce_rolling_window(mem_root, "session_summary",
                                        max_retained=5)
        assert len(result["retired"]) == 1
        assert result["retired"][0] == "session-000"
        assert result["active_count"] == 5
        assert result["max_retained"] == 5

        # Verify the file is actually retired
        retired_file = sessions[0]
        data = json.loads(retired_file.read_text())
        assert data["record_status"] == "retired"

    def test_02_no_trigger_at_limit(self, tmp_path):
        """5 active sessions, max_retained=5 -> 0 retirements."""
        from memory_enforce import enforce_rolling_window

        proj, mem_root, sessions = _setup_enforce_project(tmp_path, 5)
        result = enforce_rolling_window(mem_root, "session_summary",
                                        max_retained=5)
        assert len(result["retired"]) == 0
        assert result["active_count"] == 5

    def test_03_multiple_retirements(self, tmp_path):
        """8 active sessions, max_retained=5 -> retires 3 oldest."""
        from memory_enforce import enforce_rolling_window

        proj, mem_root, sessions = _setup_enforce_project(tmp_path, 8)
        result = enforce_rolling_window(mem_root, "session_summary",
                                        max_retained=5)
        assert len(result["retired"]) == 3
        assert result["active_count"] == 5
        # Oldest 3 should be retired
        assert result["retired"] == ["session-000", "session-001",
                                     "session-002"]

    def test_04_correct_ordering_by_created_at_and_filename(self, tmp_path):
        """Retires by created_at (oldest first), filename as tiebreaker."""
        from memory_enforce import enforce_rolling_window

        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem_root = dc / "memory"
        mem_root.mkdir()
        (mem_root / "sessions").mkdir()

        # Create 4 sessions: 2 with same timestamp, different filenames
        sessions_data = [
            ("aaa-session.json", "2026-01-10T09:00:00Z"),
            ("zzz-session.json", "2026-01-10T09:00:00Z"),  # same ts, later filename
            ("bbb-session.json", "2026-01-11T09:00:00Z"),
            ("ccc-session.json", "2026-01-12T09:00:00Z"),
        ]
        memories = []
        for fname, ts in sessions_data:
            stem = fname.replace(".json", "")
            mem = make_session_memory(id_val=stem, title=f"Session {stem}")
            mem["created_at"] = ts
            mem["updated_at"] = ts
            fp = mem_root / "sessions" / fname
            fp.write_text(json.dumps(mem, indent=2))
            memories.append(mem)

        write_index(mem_root, *memories, path_prefix=".claude/memory")

        result = enforce_rolling_window(mem_root, "session_summary",
                                        max_retained=2)
        # Should retire 2: aaa-session (oldest ts, earlier filename),
        # then zzz-session (same ts, later filename)
        assert len(result["retired"]) == 2
        assert result["retired"][0] == "aaa-session"
        assert result["retired"][1] == "zzz-session"

    def test_05_cli_max_retained_override(self, tmp_path):
        """--max-retained 3 overrides config default of 5."""
        from memory_enforce import enforce_rolling_window

        proj, mem_root, sessions = _setup_enforce_project(
            tmp_path, 6, config_max_retained=5)
        # CLI override = 3
        result = enforce_rolling_window(mem_root, "session_summary",
                                        max_retained=3)
        assert len(result["retired"]) == 3
        assert result["active_count"] == 3

    def test_06_config_max_retained(self, tmp_path):
        """Config says max_retained=3, no CLI flag -> uses config value."""
        from memory_enforce import _read_max_retained

        proj, mem_root, sessions = _setup_enforce_project(
            tmp_path, 6, config_max_retained=3)
        value = _read_max_retained(mem_root, "session_summary",
                                   cli_override=None)
        assert value == 3

    def test_07_corrupted_json_skipped(self, tmp_path):
        """One file with invalid JSON -> skipped, others processed normally."""
        from memory_enforce import enforce_rolling_window

        proj, mem_root, sessions = _setup_enforce_project(
            tmp_path, 5,
            extra_files=[{
                "filename": "bad-file.json",
                "content": "{invalid json!!!",
            }],
        )
        # 5 valid + 1 corrupted = 5 active (corrupted skipped)
        # max_retained=4 -> retire 1
        result = enforce_rolling_window(mem_root, "session_summary",
                                        max_retained=4)
        assert len(result["retired"]) == 1
        # Corrupted file should NOT appear in retired list
        assert "bad-file" not in result["retired"]

    def test_08_retire_record_failure_breaks_loop(self, tmp_path):
        """Mock structural error in retire_record -> loop breaks, partial results."""
        from memory_enforce import enforce_rolling_window

        # 6 active, max_retained=3 -> needs to retire 3
        proj, mem_root, sessions = _setup_enforce_project(tmp_path, 6)
        call_count = 0

        def mock_retire(target_abs, reason, memory_root, index_path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call succeeds (return a valid result dict)
                return {"status": "retired", "target": str(target_abs),
                        "reason": reason}
            # Second call: structural error -> breaks the loop
            raise RuntimeError("Simulated structural error")

        with patch("memory_enforce.retire_record", side_effect=mock_retire):
            result = enforce_rolling_window(mem_root, "session_summary",
                                            max_retained=3)

        # First call succeeded, second raised -> break -> only 1 retired
        assert len(result["retired"]) == 1
        assert result["retired"][0] == "session-000"

    def test_09_file_disappears_between_scan_and_retire(self, tmp_path):
        """File deleted after scan -> FileNotFoundError caught, continue."""
        from memory_enforce import enforce_rolling_window

        proj, mem_root, sessions = _setup_enforce_project(tmp_path, 7)
        call_count = 0
        original_retire = retire_record

        def mock_retire(target_abs, reason, memory_root, index_path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise FileNotFoundError(f"File gone: {target_abs}")
            return original_retire(target_abs, reason, memory_root,
                                   index_path)

        with patch("memory_enforce.retire_record", side_effect=mock_retire):
            result = enforce_rolling_window(mem_root, "session_summary",
                                            max_retained=5)

        # 7 active, max_retained=5 -> need to retire 2
        # First call: FileNotFoundError -> continue
        # Second call: succeeds
        # So 1 should be in retired list (the second one)
        assert len(result["retired"]) == 1
        assert result["retired"][0] == "session-001"

    def test_10_dry_run_no_modification(self, tmp_path):
        """--dry-run: reports what would retire, includes dry_run key, no changes."""
        from memory_enforce import enforce_rolling_window

        proj, mem_root, sessions = _setup_enforce_project(tmp_path, 7)

        # Save file contents before dry run
        before = {}
        for s in sessions:
            before[s] = s.read_text()

        result = enforce_rolling_window(mem_root, "session_summary",
                                        max_retained=5, dry_run=True)
        assert result["dry_run"] is True
        assert len(result["retired"]) == 2
        assert result["active_count"] == 5

        # Verify no files were modified
        for s in sessions:
            assert s.read_text() == before[s], f"File {s} was modified during dry-run"

    def test_11_empty_directory(self, tmp_path):
        """Sessions folder doesn't exist -> 0 retirements."""
        from memory_enforce import enforce_rolling_window

        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem_root = dc / "memory"
        mem_root.mkdir()
        # Do NOT create sessions/ subfolder

        result = enforce_rolling_window(mem_root, "session_summary",
                                        max_retained=5)
        assert result["retired"] == []
        assert result["active_count"] == 0

    def test_12_memory_root_discovery(self, tmp_path, monkeypatch):
        """Test CLAUDE_PROJECT_ROOT env var -> CWD fallback -> error."""
        from memory_enforce import _resolve_memory_root

        # Setup project structure
        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem = dc / "memory"
        mem.mkdir()

        # Test 1: CLAUDE_PROJECT_ROOT env var
        monkeypatch.setenv("CLAUDE_PROJECT_ROOT", str(proj))
        result = _resolve_memory_root()
        assert result == mem

        # Test 2: CWD fallback (clear env var)
        monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
        monkeypatch.chdir(proj)
        result = _resolve_memory_root()
        assert result == mem

        # Test 3: error when neither works
        monkeypatch.delenv("CLAUDE_PROJECT_ROOT", raising=False)
        nowhere = tmp_path / "nowhere"
        nowhere.mkdir(exist_ok=True)
        monkeypatch.chdir(nowhere)
        with pytest.raises(SystemExit) as exc_info:
            _resolve_memory_root()
        assert exc_info.value.code == 1

    def test_13_lock_not_acquired_raises(self, tmp_path):
        """Mock FlockIndex with acquired=False -> TimeoutError raised."""
        from memory_enforce import enforce_rolling_window

        proj, mem_root, sessions = _setup_enforce_project(tmp_path, 6)

        mock_lock = MagicMock()
        mock_lock.acquired = False
        mock_lock.__enter__ = MagicMock(return_value=mock_lock)
        mock_lock.__exit__ = MagicMock(return_value=False)
        mock_lock.require_acquired.side_effect = TimeoutError(
            "LOCK_TIMEOUT_ERROR: Index lock not acquired."
        )

        with patch("memory_enforce.FlockIndex", return_value=mock_lock):
            with pytest.raises(TimeoutError, match="LOCK_TIMEOUT_ERROR"):
                enforce_rolling_window(mem_root, "session_summary",
                                       max_retained=5)

    def test_14_max_retained_zero_rejected(self, tmp_path):
        """--max-retained 0 should be rejected by CLI validation."""
        import subprocess
        enforce_script = str(SCRIPTS_DIR / "memory_enforce.py")

        proj, mem_root, _ = _setup_enforce_project(tmp_path, 3)

        result = subprocess.run(
            [sys.executable, enforce_script,
             "--category", "session_summary",
             "--max-retained", "0"],
            capture_output=True, text=True, timeout=10,
            cwd=str(proj),
            env={**os.environ, "CLAUDE_PROJECT_ROOT": str(proj)},
        )
        assert result.returncode != 0
        assert "must be >= 1" in result.stderr

    def test_15_max_retained_negative_rejected(self, tmp_path):
        """--max-retained -1 should be rejected by CLI validation."""
        import subprocess
        enforce_script = str(SCRIPTS_DIR / "memory_enforce.py")

        proj, mem_root, _ = _setup_enforce_project(tmp_path, 3)

        result = subprocess.run(
            [sys.executable, enforce_script,
             "--category", "session_summary",
             "--max-retained", "-1"],
            capture_output=True, text=True, timeout=10,
            cwd=str(proj),
            env={**os.environ, "CLAUDE_PROJECT_ROOT": str(proj)},
        )
        assert result.returncode != 0
        assert "must be >= 1" in result.stderr


# ===========================================================================
# Tests 16-24: memory_write.py (FlockIndex, retire_record)
# ===========================================================================

class TestFlockIndexAndRetireRecord:
    """Tests for FlockIndex.require_acquired() and retire_record()."""

    def test_16_require_acquired_raises_when_not_acquired(self, tmp_path):
        """FlockIndex with acquired=False -> require_acquired() raises TimeoutError."""
        index_path = tmp_path / "index.md"
        index_path.write_text("# Index\n")
        lock_dir = index_path.parent / ".index.lockdir"

        # Create a fresh (non-stale) lock to force timeout
        lock_dir.mkdir()
        os.utime(lock_dir, None)

        lock = FlockIndex(index_path)
        # Reduce timeout for test speed
        lock._LOCK_TIMEOUT = 0.2
        with lock:
            assert lock.acquired is False
            with pytest.raises(TimeoutError, match="LOCK_TIMEOUT_ERROR"):
                lock.require_acquired()

        # Cleanup
        if lock_dir.exists():
            lock_dir.rmdir()

    def test_17_require_acquired_passes_when_acquired(self, tmp_path):
        """FlockIndex with acquired=True -> require_acquired() does not raise."""
        index_path = tmp_path / "index.md"
        index_path.write_text("# Index\n")

        lock = FlockIndex(index_path)
        with lock:
            assert lock.acquired is True
            # Should not raise
            lock.require_acquired()

    def test_18_existing_lock_timeout_still_passes(self, tmp_path):
        """FlockIndex timeout returns self with acquired=False (backward compat)."""
        index_path = tmp_path / "index.md"
        index_path.write_text("# Index\n")
        lock_dir = index_path.parent / ".index.lockdir"

        # Create a fresh lock to simulate contention
        lock_dir.mkdir()
        os.utime(lock_dir, None)

        lock = FlockIndex(index_path)
        lock._LOCK_TIMEOUT = 0.2
        with lock as ctx:
            # Should return self (not raise), with acquired=False
            assert ctx is lock
            assert lock.acquired is False

        if lock_dir.exists():
            lock_dir.rmdir()

    def test_19_existing_permission_denied_still_passes(self, tmp_path):
        """OSError on mkdir returns self with acquired=False (backward compat)."""
        ro_dir = tmp_path / "readonly"
        ro_dir.mkdir()
        index_path = ro_dir / "index.md"
        index_path.write_text("# Index\n")

        os.chmod(ro_dir, 0o444)
        try:
            lock = FlockIndex(index_path)
            with lock as ctx:
                assert ctx is lock
                assert lock.acquired is False
        finally:
            os.chmod(ro_dir, 0o755)

    def test_20_retire_record_matches_do_retire_behavior(self, tmp_path):
        """retire_record() sets the same fields as the old do_retire()."""
        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem_root = dc / "memory"
        mem_root.mkdir()
        (mem_root / "sessions").mkdir()

        mem = make_session_memory(id_val="test-session")
        fp = mem_root / "sessions" / "test-session.json"
        fp.write_text(json.dumps(mem, indent=2))

        index_path = mem_root / "index.md"
        write_index(mem_root, mem, path_prefix=".claude/memory")

        with FlockIndex(index_path) as lock:
            lock.require_acquired()
            result = retire_record(fp, "Test reason", mem_root, index_path)

        assert result["status"] == "retired"
        assert result["reason"] == "Test reason"

        # Verify the file on disk
        data = json.loads(fp.read_text())
        assert data["record_status"] == "retired"
        assert data["retired_at"] is not None
        assert data["retired_reason"] == "Test reason"
        assert data["updated_at"] is not None
        # Should have a change entry
        assert len(data["changes"]) >= 1
        last_change = data["changes"][-1]
        assert last_change["field"] == "record_status"
        assert last_change["old_value"] == "active"
        assert last_change["new_value"] == "retired"
        # archived fields should be absent
        assert "archived_at" not in data
        assert "archived_reason" not in data

    def test_21_retire_record_relative_path(self, tmp_path):
        """rel_path computed via memory_root.parent.parent (project root)."""
        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem_root = dc / "memory"
        mem_root.mkdir()
        (mem_root / "sessions").mkdir()

        mem = make_session_memory(id_val="rel-path-test")
        fp = mem_root / "sessions" / "rel-path-test.json"
        fp.write_text(json.dumps(mem, indent=2))

        index_path = mem_root / "index.md"
        write_index(mem_root, mem, path_prefix=".claude/memory")

        # Verify the index contains the entry before retirement
        index_before = index_path.read_text()
        assert "rel-path-test" in index_before

        with FlockIndex(index_path) as lock:
            lock.require_acquired()
            result = retire_record(fp, "Test", mem_root, index_path)

        # The entry should be removed from the index using the correct
        # relative path: .claude/memory/sessions/rel-path-test.json
        index_after = index_path.read_text()
        assert "rel-path-test" not in index_after

        # Verify the relative path was computed correctly by checking
        # that memory_root.parent.parent gives us the project root
        project_root = mem_root.parent.parent
        expected_rel = str(fp.relative_to(project_root))
        assert expected_rel == ".claude/memory/sessions/rel-path-test.json"

    def test_22_retire_record_already_retired(self, tmp_path):
        """retire_record() on already-retired file returns already_retired."""
        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem_root = dc / "memory"
        mem_root.mkdir()
        (mem_root / "sessions").mkdir()

        mem = make_session_memory(id_val="already-retired")
        mem["record_status"] = "retired"
        mem["retired_at"] = "2026-02-01T00:00:00Z"
        mem["retired_reason"] = "Previously retired"
        fp = mem_root / "sessions" / "already-retired.json"
        fp.write_text(json.dumps(mem, indent=2))

        index_path = mem_root / "index.md"
        index_path.write_text("# Memory Index\n")

        with FlockIndex(index_path) as lock:
            lock.require_acquired()
            result = retire_record(fp, "Retire again", mem_root, index_path)

        assert result["status"] == "already_retired"
        assert str(fp) in result["target"]

    def test_23_retire_record_archived_raises(self, tmp_path):
        """retire_record() on archived file raises RuntimeError."""
        proj = tmp_path / "project"
        proj.mkdir()
        dc = proj / ".claude"
        dc.mkdir()
        mem_root = dc / "memory"
        mem_root.mkdir()
        (mem_root / "sessions").mkdir()

        mem = make_session_memory(id_val="archived-session")
        mem["record_status"] = "archived"
        mem["archived_at"] = "2026-02-01T00:00:00Z"
        mem["archived_reason"] = "Long-term storage"
        fp = mem_root / "sessions" / "archived-session.json"
        fp.write_text(json.dumps(mem, indent=2))

        index_path = mem_root / "index.md"
        index_path.write_text("# Memory Index\n")

        with FlockIndex(index_path) as lock:
            lock.require_acquired()
            with pytest.raises(RuntimeError, match="unarchived"):
                retire_record(fp, "Try to retire", mem_root, index_path)

    def test_24_flock_index_rename_no_remaining_references(self):
        """Verify no remaining _flock_index references in memory_write.py."""
        write_script = SCRIPTS_DIR / "memory_write.py"
        source = write_script.read_text()

        # Should NOT contain the old private name as a class def or usage
        assert "class _flock_index" not in source
        assert "_flock_index(" not in source

        # Should contain the new public name
        assert "class FlockIndex" in source

        # All 6 action handlers should use FlockIndex
        for handler in ["do_create", "do_update", "do_retire",
                         "do_archive", "do_unarchive", "do_restore"]:
            # Find the handler function body
            start = source.find(f"def {handler}(")
            assert start != -1, f"Handler {handler} not found"
            # Find the next def (end of this handler)
            next_def = source.find("\ndef ", start + 1)
            if next_def == -1:
                next_def = len(source)
            body = source[start:next_def]
            assert "FlockIndex(" in body, \
                f"{handler} does not use FlockIndex"
