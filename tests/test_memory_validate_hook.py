"""Tests for memory_validate_hook.py -- PostToolUse validation guardrail."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "hooks" / "scripts"
VALIDATE_SCRIPT = str(SCRIPTS_DIR / "memory_validate_hook.py")
PYTHON = sys.executable

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
