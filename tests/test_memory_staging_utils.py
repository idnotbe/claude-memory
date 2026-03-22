"""Tests for memory_staging_utils.py -- shared staging path utilities.

Covers:
- get_staging_dir(): deterministic path generation, prefix, hash isolation
- ensure_staging_dir(): directory creation with permissions
- is_staging_path(): path identification for /tmp/ staging paths
"""

import hashlib
import os
import stat
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = str(Path(__file__).parent.parent / "hooks" / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from memory_staging_utils import (
    STAGING_DIR_PREFIX,
    get_staging_dir,
    ensure_staging_dir,
    is_staging_path,
)


# ===================================================================
# get_staging_dir()
# ===================================================================

class TestGetStagingDir:
    """Test deterministic staging directory path generation."""

    def test_returns_tmp_prefix(self, tmp_path):
        """Result must start with /tmp/.claude-memory-staging-"""
        result = get_staging_dir(str(tmp_path))
        assert result.startswith(STAGING_DIR_PREFIX), (
            f"Expected prefix {STAGING_DIR_PREFIX!r}, got {result!r}"
        )

    def test_deterministic_same_cwd(self, tmp_path):
        """Same cwd always produces the same path."""
        a = get_staging_dir(str(tmp_path))
        b = get_staging_dir(str(tmp_path))
        assert a == b

    def test_different_cwd_gives_different_path(self, tmp_path):
        """Different cwds produce different paths."""
        dir_a = tmp_path / "project_a"
        dir_b = tmp_path / "project_b"
        dir_a.mkdir()
        dir_b.mkdir()
        path_a = get_staging_dir(str(dir_a))
        path_b = get_staging_dir(str(dir_b))
        assert path_a != path_b, "Different project dirs should yield different staging dirs"

    def test_hash_is_12_chars(self, tmp_path):
        """The hash suffix should be exactly 12 hex characters."""
        result = get_staging_dir(str(tmp_path))
        suffix = result[len(STAGING_DIR_PREFIX):]
        assert len(suffix) == 12, f"Expected 12-char hash, got {len(suffix)}: {suffix!r}"
        # All hex chars
        assert all(c in "0123456789abcdef" for c in suffix), (
            f"Hash suffix contains non-hex chars: {suffix!r}"
        )

    def test_matches_manual_computation(self, tmp_path):
        """Verify the hash matches direct SHA-256 computation."""
        real_path = os.path.realpath(str(tmp_path))
        expected_hash = hashlib.sha256(real_path.encode()).hexdigest()[:12]
        expected = f"{STAGING_DIR_PREFIX}{expected_hash}"
        result = get_staging_dir(str(tmp_path))
        assert result == expected

    def test_empty_cwd_uses_getcwd(self):
        """Empty cwd string should fall back to os.getcwd()."""
        cwd = os.getcwd()
        expected = get_staging_dir(cwd)
        result = get_staging_dir("")
        assert result == expected

    def test_symlink_cwd_resolves_to_realpath(self, tmp_path):
        """Symlink cwd should resolve to the same path as the real target."""
        real_dir = tmp_path / "real_project"
        real_dir.mkdir()
        link_dir = tmp_path / "link_project"
        link_dir.symlink_to(real_dir)

        path_from_real = get_staging_dir(str(real_dir))
        path_from_link = get_staging_dir(str(link_dir))
        assert path_from_real == path_from_link, (
            "Symlink and real dir should resolve to the same staging path"
        )


# ===================================================================
# ensure_staging_dir()
# ===================================================================

class TestEnsureStagingDir:
    """Test staging directory creation."""

    def test_creates_directory(self, tmp_path):
        """ensure_staging_dir should create the directory."""
        result = ensure_staging_dir(str(tmp_path))
        assert os.path.isdir(result), f"Directory not created: {result}"

    def test_returns_same_as_get(self, tmp_path):
        """ensure_staging_dir and get_staging_dir should return the same path."""
        expected = get_staging_dir(str(tmp_path))
        result = ensure_staging_dir(str(tmp_path))
        assert result == expected

    def test_idempotent(self, tmp_path):
        """Calling ensure_staging_dir twice should work without error."""
        first = ensure_staging_dir(str(tmp_path))
        second = ensure_staging_dir(str(tmp_path))
        assert first == second
        assert os.path.isdir(first)

    def test_permissions_0o700(self, tmp_path):
        """Staging directory should have 0o700 permissions."""
        result = ensure_staging_dir(str(tmp_path))
        mode = os.stat(result).st_mode
        # Extract permission bits
        perms = stat.S_IMODE(mode)
        assert perms == 0o700, f"Expected 0o700, got {oct(perms)}"

    def test_cleanup(self, tmp_path):
        """Clean up the test staging dir after test."""
        result = ensure_staging_dir(str(tmp_path))
        # Cleanup
        if os.path.isdir(result):
            os.rmdir(result)


# ===================================================================
# is_staging_path()
# ===================================================================

class TestIsStagingPath:
    """Test staging path identification."""

    def test_valid_tmp_staging_path(self):
        """A path starting with the staging prefix should be identified."""
        assert is_staging_path("/tmp/.claude-memory-staging-abc123def456/intent-session.json")

    def test_valid_staging_dir_only(self):
        """Just the directory itself should be identified."""
        assert is_staging_path("/tmp/.claude-memory-staging-abc123def456")

    def test_non_staging_path(self):
        """Random /tmp/ paths should not match."""
        assert not is_staging_path("/tmp/some-other-dir/file.json")

    def test_claude_memory_path_not_staging(self):
        """Old .claude/memory paths should NOT be identified as staging."""
        assert not is_staging_path("/home/user/project/.claude/memory/.staging/file.json")

    def test_partial_prefix_no_match(self):
        """A partial prefix should not match."""
        assert not is_staging_path("/tmp/.claude-memory-stag")

    def test_empty_string(self):
        """Empty string should return False."""
        assert not is_staging_path("")

    def test_similar_prefix_but_different(self):
        """Paths similar to but not exactly the prefix should not match."""
        assert not is_staging_path("/tmp/.claude-memory-staging")  # no dash suffix
        # But with a hash it should match
        assert is_staging_path("/tmp/.claude-memory-staging-abc123")

    def test_nested_file_within_staging(self):
        """Nested files within staging should match."""
        assert is_staging_path("/tmp/.claude-memory-staging-abc123/subdir/deep/file.json")
