"""Tests for memory_validate_hook.py -- PostToolUse validation guardrail."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
VALIDATE_SCRIPT = str(SCRIPTS_DIR / "memory_validate_hook.py")
GUARD_SCRIPT = str(SCRIPTS_DIR / "memory_write_guard.py")
PYTHON = sys.executable


# ---------------------------------------------------------------------------
# Helpers (modeled after test_memory_staging_guard.py)
# ---------------------------------------------------------------------------

def run_validate_hook(file_path):
    """Run validate hook with a file_path, return (stdout, stderr, returncode)."""
    hook_input = {"tool_input": {"file_path": file_path}}
    result = subprocess.run(
        [PYTHON, VALIDATE_SCRIPT],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def run_write_guard(file_path):
    """Run write guard (PreToolUse) with a file_path, return (stdout, stderr, returncode)."""
    hook_input = {"tool_input": {"file_path": file_path}}
    result = subprocess.run(
        [PYTHON, GUARD_SCRIPT],
        input=json.dumps(hook_input),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def assert_allow(stdout, msg=""):
    """Assert the hook allowed the operation (empty stdout = allow)."""
    assert stdout == "", f"Expected empty stdout (allow), got: {stdout!r}. {msg}"


def assert_deny(stdout, msg=""):
    """Assert stdout contains a deny decision."""
    assert stdout, f"Expected deny output, got empty. {msg}"
    output = json.loads(stdout)
    decision = output.get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "deny", f"Expected deny, got '{decision}'. {msg}"

sys.path.insert(0, str(SCRIPTS_DIR))
from memory_validate_hook import (
    is_memory_file,
    get_category_from_path,
    FOLDER_TO_CATEGORY,
)


class TestIsMemoryFile:
    def test_memory_json_path(self):
        assert is_memory_file("/home/user/project/.claude/memory/decisions/test.json") is True

    def test_non_memory_path(self):
        assert is_memory_file("/home/user/project/src/main.py") is False

    def test_memory_non_json_path_now_matched(self):
        """After F9 fix, non-JSON files in memory dir ARE matched."""
        assert is_memory_file("/home/user/project/.claude/memory/decisions/test.md") is True

    def test_memory_index_matched(self):
        """index.md inside memory dir should now be matched."""
        assert is_memory_file("/home/user/project/.claude/memory/index.md") is True

    def test_empty_path(self):
        assert is_memory_file("") is False


class TestGetCategoryFromPath:
    def test_decisions_folder(self):
        assert get_category_from_path(
            "/home/user/.claude/memory/decisions/use-jwt.json"
        ) == "decision"

    def test_preferences_folder(self):
        assert get_category_from_path(
            "/home/user/.claude/memory/preferences/dark-mode.json"
        ) == "preference"

    def test_sessions_folder(self):
        assert get_category_from_path(
            "/home/user/.claude/memory/sessions/2026-02-14.json"
        ) == "session_summary"

    def test_tech_debt_folder(self):
        assert get_category_from_path(
            "/home/user/.claude/memory/tech-debt/legacy.json"
        ) == "tech_debt"

    def test_unknown_folder(self):
        assert get_category_from_path(
            "/home/user/.claude/memory/unknown/test.json"
        ) is None

    def test_all_folders_mapped(self):
        for folder, cat in FOLDER_TO_CATEGORY.items():
            path = f"/home/user/.claude/memory/{folder}/test.json"
            assert get_category_from_path(path) == cat


class TestValidateHookIntegration:
    """Integration tests running the hook as a subprocess."""

    def _run_validate_hook(self, hook_input):
        result = subprocess.run(
            [PYTHON, VALIDATE_SCRIPT],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout, result.stderr, result.returncode

    def test_non_memory_file_passes_through(self):
        hook_input = {
            "tool_input": {
                "file_path": "/home/user/project/src/main.py",
            }
        }
        stdout, stderr, rc = self._run_validate_hook(hook_input)
        assert rc == 0
        # No blocking output for non-memory files
        if stdout.strip():
            output = json.loads(stdout)
            assert output.get("decision") != "block"

    def test_valid_memory_file(self, tmp_path):
        """Valid memory file should pass validation (with warning about guard bypass)."""
        from conftest import make_decision_memory
        mem = make_decision_memory()
        # Create a memory-like path
        mem_dir = tmp_path / ".claude" / "memory" / "decisions"
        mem_dir.mkdir(parents=True)
        mem_file = mem_dir / "use-jwt.json"
        mem_file.write_text(json.dumps(mem, indent=2))

        hook_input = {
            "tool_input": {
                "file_path": str(mem_file),
            }
        }
        stdout, stderr, rc = self._run_validate_hook(hook_input)
        assert rc == 0
        # Valid file should not be blocked
        if stdout.strip():
            output = json.loads(stdout)
            assert output.get("decision") != "block"

    def test_invalid_memory_file_quarantined(self, tmp_path):
        """Invalid memory file should be quarantined."""
        # Create an invalid memory file (missing required fields)
        mem_dir = tmp_path / ".claude" / "memory" / "decisions"
        mem_dir.mkdir(parents=True)
        mem_file = mem_dir / "bad-mem.json"
        mem_file.write_text(json.dumps({"title": "bad", "category": "decision"}))

        hook_input = {
            "tool_input": {
                "file_path": str(mem_file),
            }
        }
        stdout, stderr, rc = self._run_validate_hook(hook_input)
        assert rc == 0
        # Check quarantine happened
        quarantined = list(mem_dir.glob("bad-mem.json.invalid.*"))
        assert len(quarantined) >= 1 or "block" in stdout

    def test_empty_input(self):
        result = subprocess.run(
            [PYTHON, VALIDATE_SCRIPT],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0

    def test_missing_file_path(self):
        hook_input = {"tool_input": {}}
        stdout, stderr, rc = self._run_validate_hook(hook_input)
        assert rc == 0

    # --- Config file exemption tests ---

    def test_config_file_skips_validation(self):
        """memory-config.json should NOT be validated or quarantined."""
        hook_input = {
            "tool_input": {
                "file_path": "/home/user/project/.claude/memory/memory-config.json",
            }
        }
        stdout, stderr, rc = self._run_validate_hook(hook_input)
        assert rc == 0
        # Should NOT produce a deny decision
        if stdout.strip():
            output = json.loads(stdout)
            hook_output = output.get("hookSpecificOutput", {})
            assert hook_output.get("permissionDecision") != "deny"

    def test_config_file_not_quarantined(self, tmp_path):
        """Write a real config file and verify it is not renamed/quarantined."""
        # Create a .claude/memory/ directory structure
        mem_dir = tmp_path / ".claude" / "memory"
        mem_dir.mkdir(parents=True)
        config_file = mem_dir / "memory-config.json"
        config_data = {
            "retrieval": {"enabled": True, "max_inject": 5},
            "triage": {"enabled": True},
        }
        config_file.write_text(json.dumps(config_data, indent=2))

        hook_input = {
            "tool_input": {
                "file_path": str(config_file),
            }
        }
        stdout, stderr, rc = self._run_validate_hook(hook_input)
        assert rc == 0

        # Config file should still exist with its original name (not quarantined)
        assert config_file.exists(), "Config file was quarantined (renamed)"
        # No .invalid files should exist
        quarantined = list(mem_dir.glob("memory-config.json.invalid.*"))
        assert len(quarantined) == 0, (
            f"Config file was quarantined: {quarantined}"
        )

    def test_config_file_in_subdirectory_still_validated(self, tmp_path):
        """memory-config.json inside a category subfolder should NOT be exempted."""
        mem_dir = tmp_path / ".claude" / "memory" / "decisions"
        mem_dir.mkdir(parents=True)
        fake_config = mem_dir / "memory-config.json"
        # Write a file that looks like config but is in a subfolder
        fake_config.write_text(json.dumps({"retrieval": {"enabled": True}}))

        hook_input = {
            "tool_input": {
                "file_path": str(fake_config),
            }
        }
        stdout, stderr, rc = self._run_validate_hook(hook_input)
        assert rc == 0
        # Should be quarantined (not exempted) since it's in a subfolder
        quarantined = list(mem_dir.glob("memory-config.json.invalid.*"))
        assert len(quarantined) >= 1 or "deny" in stdout, (
            "memory-config.json in subdirectory was incorrectly exempted"
        )

    def test_memory_files_still_validated(self, tmp_path):
        """Regular memory files should still go through validation and quarantine."""
        mem_dir = tmp_path / ".claude" / "memory" / "decisions"
        mem_dir.mkdir(parents=True)
        bad_file = mem_dir / "bad-decision.json"
        # Write an invalid memory file (missing required fields)
        bad_file.write_text(json.dumps({"title": "bad", "category": "decision"}))

        hook_input = {
            "tool_input": {
                "file_path": str(bad_file),
            }
        }
        stdout, stderr, rc = self._run_validate_hook(hook_input)
        assert rc == 0

        # The invalid memory file should be quarantined
        quarantined = list(mem_dir.glob("bad-decision.json.invalid.*"))
        assert len(quarantined) >= 1 or "deny" in stdout, (
            "Invalid memory file was not quarantined"
        )


# ============================================================
# Phase 2: Staging Exemption Tests (TrueNegatives)
# ============================================================

class TestStagingExemption:
    """Staging files must pass through without quarantine or deny."""

    def test_staging_json_file_allowed(self, tmp_path):
        """intent-*.json in .staging/ should exit(0) with no deny."""
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "intent-decision.json"
        f.write_text('{"intent": "create"}')

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        assert_allow(stdout, "staging JSON file should be allowed")
        assert f.exists(), "Staging file should not be quarantined (renamed)"
        assert not list(staging_dir.glob("*.invalid.*")), "No quarantine artifacts"

    def test_staging_txt_file_allowed(self, tmp_path):
        """new-info-*.txt in .staging/ should exit(0) with no deny."""
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "new-info-session.txt"
        f.write_text("session notes here")

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        assert_allow(stdout, "staging txt file should be allowed")
        assert f.exists(), "Staging file should not be quarantined (renamed)"

    def test_staging_nested_path_allowed(self, tmp_path):
        """Files in .staging/sub/dir/ should also be allowed."""
        nested_dir = tmp_path / ".claude" / "memory" / ".staging" / "sub" / "dir"
        nested_dir.mkdir(parents=True)
        f = nested_dir / "file.json"
        f.write_text('{}')

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        assert_allow(stdout, "nested staging file should be allowed")
        assert f.exists(), "Nested staging file should not be quarantined"

    def test_staging_no_bypass_warning(self, tmp_path):
        """Staging path should NOT produce 'bypassed PreToolUse guard' warning."""
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "intent-decision.json"
        f.write_text('{"intent": "create"}')

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        assert "bypassed PreToolUse guard" not in stderr, (
            "Staging file should not trigger bypass warning"
        )

    def test_staging_triage_data_allowed(self, tmp_path):
        """triage-data.json (most critical staging file) should exit(0)."""
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "triage-data.json"
        f.write_text('{"categories": []}')

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        assert_allow(stdout, "triage-data.json should be allowed")
        assert f.exists(), "triage-data.json should not be quarantined"

    def test_non_staging_shows_bypass_warning(self, tmp_path):
        """Non-staging memory file should show 'bypassed PreToolUse guard' warning."""
        from conftest import make_decision_memory
        mem_dir = tmp_path / ".claude" / "memory" / "decisions"
        mem_dir.mkdir(parents=True)
        f = mem_dir / "test-decision.json"
        f.write_text(json.dumps(make_decision_memory()))

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        assert "bypassed PreToolUse guard" in stderr, (
            "Non-staging memory file should trigger bypass warning"
        )


# ============================================================
# Phase 2: Security Tests (TruePositives)
# ============================================================

# ============================================================
# Phase 2+: Near-miss regression tests (advisory fix)
# ============================================================

class TestStagingNearMiss:
    """Near-miss paths that should NOT be exempted by staging exclusion."""

    def test_staging_as_file_not_exempted(self, tmp_path):
        """.staging as a FILE (not directory) should not be exempted."""
        mem_dir = tmp_path / ".claude" / "memory"
        mem_dir.mkdir(parents=True)
        # Create .staging as a regular file, not a directory
        f = mem_dir / ".staging"
        f.write_text("this is a file named .staging")

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        # .staging has no trailing slash in resolved path → marker doesn't match
        # Also not .json → non-JSON deny fires
        assert_deny(stdout, ".staging as file should be denied (non-JSON)")

    def test_stagingfoo_not_exempted(self, tmp_path):
        """.stagingfoo/ should not be exempted (prefix collision guard)."""
        bad_dir = tmp_path / ".claude" / "memory" / ".stagingfoo"
        bad_dir.mkdir(parents=True)
        f = bad_dir / "evil.json"
        f.write_text(json.dumps({"title": "evil", "category": "decision"}))

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        # .stagingfoo/ does NOT match /.claude/memory/.staging/ marker
        quarantined = list(bad_dir.glob("evil.json.invalid.*"))
        has_deny = stdout and "deny" in stdout
        assert len(quarantined) >= 1 or has_deny, (
            ".stagingfoo/ should not be exempted by staging exclusion"
        )

    def test_staging_at_wrong_level_not_exempted(self, tmp_path):
        """decisions/.staging/file.json should not be exempted."""
        wrong_dir = tmp_path / ".claude" / "memory" / "decisions" / ".staging"
        wrong_dir.mkdir(parents=True)
        f = wrong_dir / "file.json"
        f.write_text(json.dumps({"title": "wrong", "category": "decision"}))

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        # Path is /.claude/memory/decisions/.staging/file.json
        # Marker is /.claude/memory/.staging/ — different position
        quarantined = list(wrong_dir.glob("file.json.invalid.*"))
        has_deny = stdout and "deny" in stdout
        assert len(quarantined) >= 1 or has_deny, (
            ".staging/ at wrong nesting level should not be exempted"
        )


class TestStagingHardLink:
    """Hard-link detection in staging exclusion."""

    def test_hardlinked_staging_file_warns_but_skips(self, tmp_path):
        """A hard-linked file in .staging/ should warn but still skip validation.

        nlink is now diagnostic-only in PostToolUse (warning, not gate).
        PreToolUse write_guard is the primary defense with nlink gating.
        """
        decisions_dir = tmp_path / ".claude" / "memory" / "decisions"
        decisions_dir.mkdir(parents=True)
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)

        # Create a real memory file (invalid, will be quarantined)
        real_file = decisions_dir / "real.json"
        real_file.write_text(json.dumps({"title": "real", "category": "decision"}))

        # Hard-link it into .staging/
        hardlink = staging_dir / "real.json"
        os.link(str(real_file), str(hardlink))

        # Verify hard link was created (nlink == 2)
        assert os.stat(str(hardlink)).st_nlink == 2

        stdout, stderr, rc = run_validate_hook(str(hardlink))
        assert rc == 0
        # Should warn about nlink but still skip validation (warning-only)
        assert "unexpected nlink" in stderr, (
            "Hard-linked staging file should trigger nlink warning"
        )
        # Should NOT quarantine — staging skip is unconditional
        assert_allow(stdout, "Hard-linked staging file should still be skipped")
        assert hardlink.exists(), "Hard-linked staging file should not be quarantined"

    def test_normal_staging_file_exempted(self, tmp_path):
        """A normal staging file (nlink == 1) should be exempted."""
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "intent.json"
        f.write_text('{"intent": "create"}')

        # Verify normal file (nlink == 1)
        assert os.stat(str(f)).st_nlink == 1

        stdout, stderr, rc = run_validate_hook(str(f))
        assert rc == 0
        assert_allow(stdout, "normal staging file (nlink=1) should be exempted")
        assert "unexpected nlink" not in stderr


class TestStagingSecurity:
    """Security: staging exclusion must not bypass real validation."""

    def test_staging_traversal_blocked(self, tmp_path):
        """Path .staging/../decisions/evil.json should resolve and be validated."""
        # Create the actual target directory that traversal resolves to
        decisions_dir = tmp_path / ".claude" / "memory" / "decisions"
        decisions_dir.mkdir(parents=True)
        evil_file = decisions_dir / "evil.json"
        evil_file.write_text(json.dumps({"title": "evil", "category": "decision"}))

        # Also create .staging/ so the path is plausible
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)

        # Path traversal: .staging/../decisions/evil.json -> decisions/evil.json
        traversal_path = str(staging_dir / ".." / "decisions" / "evil.json")
        stdout, stderr, rc = run_validate_hook(traversal_path)
        assert rc == 0
        # Should be quarantined or denied (not exempted via staging)
        quarantined = list(decisions_dir.glob("evil.json.invalid.*"))
        has_deny = stdout and "deny" in stdout
        assert len(quarantined) >= 1 or has_deny, (
            "Traversal path should NOT be exempted by staging exclusion"
        )

    def test_non_staging_memory_still_validated(self, tmp_path):
        """Invalid memory file outside .staging/ should still be quarantined."""
        mem_dir = tmp_path / ".claude" / "memory" / "decisions"
        mem_dir.mkdir(parents=True)
        bad_file = mem_dir / "bad.json"
        bad_file.write_text(json.dumps({"title": "bad", "category": "decision"}))

        stdout, stderr, rc = run_validate_hook(str(bad_file))
        assert rc == 0
        quarantined = list(mem_dir.glob("bad.json.invalid.*"))
        has_deny = stdout and "deny" in stdout
        assert len(quarantined) >= 1 or has_deny, (
            "Non-staging invalid file should be quarantined"
        )


# ============================================================
# Phase 2: Cross-Hook Parity Tests
# ============================================================

class TestCrossHookParity:
    """Pre/PostToolUse hooks must agree on staging and config exemptions."""

    def test_parity_staging_both_hooks_allow(self, tmp_path):
        """Both PreToolUse and PostToolUse must allow .staging/ files."""
        staging_dir = tmp_path / ".claude" / "memory" / ".staging"
        staging_dir.mkdir(parents=True)
        f = staging_dir / "intent-decision.json"
        f.write_text('{"intent": "create"}')
        path = str(f)

        # PostToolUse (validate hook)
        post_stdout, _, post_rc = run_validate_hook(path)
        assert post_rc == 0
        assert_allow(post_stdout, "PostToolUse should allow staging")

        # PreToolUse (write guard) — explicit allow for staging
        pre_stdout, _, pre_rc = run_write_guard(path)
        assert pre_rc == 0
        if pre_stdout:
            output = json.loads(pre_stdout)
            decision = output.get("hookSpecificOutput", {}).get("permissionDecision")
            assert decision == "allow", (
                f"PreToolUse should allow staging, got '{decision}'"
            )
        # Empty stdout is also acceptable (abstain = no deny)

    def test_parity_config_both_hooks_allow(self, tmp_path):
        """Both PreToolUse and PostToolUse must allow memory-config.json."""
        mem_dir = tmp_path / ".claude" / "memory"
        mem_dir.mkdir(parents=True)
        config_file = mem_dir / "memory-config.json"
        config_file.write_text(json.dumps({"retrieval": {"enabled": True}}))
        path = str(config_file)

        # PostToolUse (validate hook)
        post_stdout, _, post_rc = run_validate_hook(path)
        assert post_rc == 0
        assert_allow(post_stdout, "PostToolUse should allow config")

        # PreToolUse (write guard)
        pre_stdout, _, pre_rc = run_write_guard(path)
        assert pre_rc == 0
        assert_allow(pre_stdout, "PreToolUse should allow config")
