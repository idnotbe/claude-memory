"""Tests for memory_index.py -- index management utility."""

import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
INDEX_SCRIPT = str(SCRIPTS_DIR / "memory_index.py")
PYTHON = sys.executable

sys.path.insert(0, str(SCRIPTS_DIR))
from memory_index import (
    scan_memories,
    CATEGORY_FOLDERS,
    CATEGORY_DISPLAY,
)
from conftest import (
    make_decision_memory,
    make_preference_memory,
    make_tech_debt_memory,
    make_session_memory,
    make_runbook_memory,
    make_constraint_memory,
    write_memory_file,
    write_index,
)


def run_index_cmd(root, *args):
    """Run memory_index.py with given args. Returns (stdout, stderr, returncode)."""
    cmd = [PYTHON, INDEX_SCRIPT, "--root", str(root)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    return result.stdout, result.stderr, result.returncode


def setup_memory_root(tmp_path):
    """Create a project-like .claude/memory structure and return (project_root, memory_root)."""
    proj = tmp_path / "project"
    proj.mkdir()
    dc = proj / ".claude"
    dc.mkdir()
    mem = dc / "memory"
    mem.mkdir()
    for folder in CATEGORY_FOLDERS.values():
        (mem / folder).mkdir()
    return proj, mem


class TestScanMemories:
    def test_scans_active_only_by_default(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        active = make_decision_memory()
        retired = make_tech_debt_memory(record_status="retired", retired_at="2026-01-01T00:00:00Z")
        write_memory_file(mem_root, active)
        write_memory_file(mem_root, retired)
        results = scan_memories(mem_root, include_inactive=False)
        ids = [m["data"]["id"] for m in results]
        assert "use-jwt" in ids
        assert "legacy-api-v1" not in ids

    def test_scans_all_with_include_inactive(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        active = make_decision_memory()
        retired = make_tech_debt_memory(record_status="retired", retired_at="2026-01-01T00:00:00Z")
        write_memory_file(mem_root, active)
        write_memory_file(mem_root, retired)
        results = scan_memories(mem_root, include_inactive=True)
        ids = [m["data"]["id"] for m in results]
        assert "use-jwt" in ids
        assert "legacy-api-v1" in ids

    def test_skips_corrupt_json(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        bad_file = mem_root / "decisions" / "bad.json"
        bad_file.write_text("{invalid json")
        results = scan_memories(mem_root, include_inactive=True)
        assert len(results) == 0


class TestRebuild:
    def test_rebuild_generates_enriched_format(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        mem = make_decision_memory()
        write_memory_file(mem_root, mem)
        stdout, stderr, rc = run_index_cmd(mem_root, "--rebuild")
        assert rc == 0
        assert "Rebuilt index.md" in stdout
        index_content = (mem_root / "index.md").read_text()
        assert "[DECISION]" in index_content
        assert "#tags:" in index_content
        assert "auth" in index_content

    def test_rebuild_skips_retired(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        active = make_decision_memory()
        retired = make_tech_debt_memory(record_status="retired", retired_at="2026-01-01T00:00:00Z")
        write_memory_file(mem_root, active)
        write_memory_file(mem_root, retired)
        run_index_cmd(mem_root, "--rebuild")
        index_content = (mem_root / "index.md").read_text()
        assert "use-jwt" in index_content
        assert "legacy-api-v1" not in index_content

    def test_rebuild_skips_archived(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        active = make_decision_memory()
        archived = make_preference_memory(record_status="archived")
        write_memory_file(mem_root, active)
        write_memory_file(mem_root, archived)
        run_index_cmd(mem_root, "--rebuild")
        index_content = (mem_root / "index.md").read_text()
        assert "use-jwt" in index_content
        assert "prefer-typescript" not in index_content

    def test_rebuild_multiple_categories(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        write_memory_file(mem_root, make_decision_memory())
        write_memory_file(mem_root, make_preference_memory())
        write_memory_file(mem_root, make_tech_debt_memory())
        run_index_cmd(mem_root, "--rebuild")
        index_content = (mem_root / "index.md").read_text()
        assert "[DECISION]" in index_content
        assert "[PREFERENCE]" in index_content
        assert "[TECH_DEBT]" in index_content

    def test_rebuild_empty_store(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        stdout, stderr, rc = run_index_cmd(mem_root, "--rebuild")
        assert rc == 0
        assert "No active memory files" in stdout


class TestValidate:
    def test_validate_in_sync(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        mem = make_decision_memory()
        write_memory_file(mem_root, mem)
        run_index_cmd(mem_root, "--rebuild")
        stdout, stderr, rc = run_index_cmd(mem_root, "--validate")
        assert rc == 0
        assert "valid" in stdout.lower()

    def test_validate_detects_missing_from_index(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        mem1 = make_decision_memory()
        mem2 = make_preference_memory()
        write_memory_file(mem_root, mem1)
        write_memory_file(mem_root, mem2)
        # Only index mem1
        write_index(mem_root, mem1)
        stdout, stderr, rc = run_index_cmd(mem_root, "--validate")
        assert rc == 1
        assert "NOT in index" in stdout

    def test_validate_detects_stale_entries(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        mem = make_decision_memory()
        write_memory_file(mem_root, mem)
        run_index_cmd(mem_root, "--rebuild")
        # Delete the file but keep index
        (mem_root / "decisions" / "use-jwt.json").unlink()
        stdout, stderr, rc = run_index_cmd(mem_root, "--validate")
        assert rc == 1
        assert "NO matching file" in stdout


class TestGC:
    def test_gc_removes_past_grace_period(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        old_retired = make_tech_debt_memory(
            record_status="retired",
            retired_at=(datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        write_memory_file(mem_root, old_retired)
        stdout, stderr, rc = run_index_cmd(mem_root, "--gc")
        assert rc == 0
        assert "DELETED" in stdout
        assert not (mem_root / "tech-debt" / "legacy-api-v1.json").exists()

    def test_gc_respects_grace_period(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        recent_retired = make_tech_debt_memory(
            record_status="retired",
            retired_at=(datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        write_memory_file(mem_root, recent_retired)
        stdout, stderr, rc = run_index_cmd(mem_root, "--gc")
        assert rc == 0
        assert "No retired memories past grace period" in stdout
        assert (mem_root / "tech-debt" / "legacy-api-v1.json").exists()

    def test_gc_custom_grace_period(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        retired = make_tech_debt_memory(
            record_status="retired",
            retired_at=(datetime.now(timezone.utc) - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        write_memory_file(mem_root, retired)
        # Write config with 7-day grace period
        config = {"delete": {"grace_period_days": 7}}
        (mem_root / "memory-config.json").write_text(json.dumps(config))
        stdout, stderr, rc = run_index_cmd(mem_root, "--gc")
        assert rc == 0
        assert "DELETED" in stdout

    def test_gc_skips_missing_retired_at(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        retired = make_tech_debt_memory(record_status="retired")
        # make_tech_debt_memory with record_status="retired" may or may not
        # have retired_at depending on the retired_at parameter; ensure it's missing
        retired.pop("retired_at", None)
        retired.pop("retired_reason", None)
        write_memory_file(mem_root, retired)
        stdout, stderr, rc = run_index_cmd(mem_root, "--gc")
        assert rc == 0
        assert "SKIP" in stdout
        assert (mem_root / "tech-debt" / "legacy-api-v1.json").exists()


class TestHealth:
    def test_health_report_good(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        write_memory_file(mem_root, make_decision_memory())
        write_memory_file(mem_root, make_preference_memory())
        run_index_cmd(mem_root, "--rebuild")
        stdout, stderr, rc = run_index_cmd(mem_root, "--health")
        assert rc == 0
        assert "Memory Health Report" in stdout
        assert "DECISION: 1" in stdout
        assert "PREFERENCE: 1" in stdout
        assert "TOTAL (active): 2" in stdout
        assert "Health: GOOD" in stdout

    def test_health_detects_heavily_updated(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        heavy = make_decision_memory(times_updated=10)
        write_memory_file(mem_root, heavy)
        run_index_cmd(mem_root, "--rebuild")
        stdout, stderr, rc = run_index_cmd(mem_root, "--health")
        assert rc == 0
        assert "updated 10 times" in stdout
        assert "NEEDS ATTENTION" in stdout

    def test_health_reports_retired_count(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        write_memory_file(mem_root, make_decision_memory())
        retired = make_tech_debt_memory(
            record_status="retired",
            retired_at="2026-02-10T00:00:00Z",
        )
        write_memory_file(mem_root, retired)
        run_index_cmd(mem_root, "--rebuild")
        stdout, stderr, rc = run_index_cmd(mem_root, "--health")
        assert rc == 0
        assert "Retired: 1" in stdout

    def test_health_detects_index_desync(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        write_memory_file(mem_root, make_decision_memory())
        write_memory_file(mem_root, make_preference_memory())
        # Only index one
        write_index(mem_root, make_decision_memory())
        stdout, stderr, rc = run_index_cmd(mem_root, "--health")
        assert rc == 0
        assert "NEEDS ATTENTION" in stdout or "FILES MISSING FROM INDEX" in stdout

    def test_health_empty_store(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        # Create an empty index
        (mem_root / "index.md").write_text("# Memory Index\n")
        stdout, stderr, rc = run_index_cmd(mem_root, "--health")
        assert rc == 0
        assert "No active memories" in stdout


class TestQuery:
    def test_query_finds_match(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        write_memory_file(mem_root, make_decision_memory())
        run_index_cmd(mem_root, "--rebuild")
        stdout, stderr, rc = run_index_cmd(mem_root, "--query", "JWT")
        assert rc == 0
        assert "1 match" in stdout

    def test_query_no_match(self, tmp_path):
        proj, mem_root = setup_memory_root(tmp_path)
        write_memory_file(mem_root, make_decision_memory())
        run_index_cmd(mem_root, "--rebuild")
        stdout, stderr, rc = run_index_cmd(mem_root, "--query", "zzzznonexistent")
        assert rc == 0
        assert "No matches" in stdout
