"""Tests for memory_staging_utils.py -- shared staging path utilities.

Covers:
- get_staging_dir(): deterministic path generation, prefix, hash isolation
- ensure_staging_dir(): directory creation with permissions
- validate_staging_dir(): adversarial symlink/ownership/permissions defense
- is_staging_path(): path identification for /tmp/ staging paths
"""

import hashlib
import os
import stat
import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = str(Path(__file__).parent.parent / "hooks" / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from memory_staging_utils import (
    STAGING_DIR_PREFIX,
    get_staging_dir,
    ensure_staging_dir,
    validate_staging_dir,
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


# ===================================================================
# validate_staging_dir() -- adversarial security tests (V-R2 GAP 1)
# ===================================================================

class TestValidateStagingDirSecurity:
    """Adversarial tests for symlink/ownership/permissions defense.

    These tests ensure the S1 security fix (mkdir + lstat validation)
    correctly rejects symlinks and foreign-owned directories. Without
    these tests, the core defense could be accidentally removed and
    the test suite would still pass.
    """

    def test_rejects_symlink_at_staging_path(self, tmp_path):
        """Pre-existing symlink at staging path should raise RuntimeError."""
        # Create a target directory for the symlink to point to
        target = tmp_path / "attacker_dir"
        target.mkdir()

        # Create a symlink at a /tmp/ staging path
        staging_path = f"{STAGING_DIR_PREFIX}test_symlink_reject"
        try:
            # Remove if it exists from a previous failed test
            if os.path.islink(staging_path) or os.path.exists(staging_path):
                if os.path.islink(staging_path):
                    os.unlink(staging_path)
                elif os.path.isdir(staging_path):
                    os.rmdir(staging_path)

            os.symlink(str(target), staging_path)

            with pytest.raises(RuntimeError, match="symlink"):
                validate_staging_dir(staging_path)
        finally:
            if os.path.islink(staging_path):
                os.unlink(staging_path)

    def test_rejects_foreign_ownership_via_mock(self):
        """Directory owned by different UID should raise RuntimeError.

        Uses mocking since we can't create files owned by another user
        without root. Patches os.lstat to return a foreign UID and
        os.geteuid to return our UID.
        """
        staging_path = f"{STAGING_DIR_PREFIX}test_foreign_uid"

        # Mock the scenario: mkdir raises FileExistsError (dir exists),
        # lstat returns a stat result with a foreign UID
        mock_stat = mock.MagicMock()
        mock_stat.st_mode = stat.S_IFDIR | 0o700  # Regular directory
        mock_stat.st_uid = 9999  # Foreign UID

        with mock.patch("memory_staging_utils.os.mkdir", side_effect=FileExistsError):
            with mock.patch("memory_staging_utils.os.lstat", return_value=mock_stat):
                with mock.patch("memory_staging_utils.os.geteuid", return_value=1000):
                    with pytest.raises(RuntimeError, match="owned by uid 9999"):
                        validate_staging_dir(staging_path)

    def test_tightens_loose_permissions(self, tmp_path):
        """Directory with 0o777 should be tightened to 0o700.

        Verifies the permission-tightening branch (S_IMODE & 0o077).
        """
        staging_path = f"{STAGING_DIR_PREFIX}test_loose_perms"
        try:
            # Create directory with loose permissions
            os.mkdir(staging_path, 0o777)

            # validate_staging_dir should tighten permissions
            validate_staging_dir(staging_path)

            actual_perms = stat.S_IMODE(os.lstat(staging_path).st_mode)
            assert actual_perms == 0o700, (
                f"Expected 0o700, got {oct(actual_perms)} -- "
                f"loose permissions were not tightened"
            )
        finally:
            if os.path.isdir(staging_path):
                os.rmdir(staging_path)

    def test_regular_file_at_path_does_not_pass_silently(self, tmp_path):
        """Regular file (not dir) at staging path should cause downstream failure.

        validate_staging_dir() does not currently check S_ISDIR, so a regular
        file at the path would pass validation but cause FileNotFoundError
        downstream when trying to write files into it. This test documents
        that behavior -- the file passes the symlink/ownership checks but
        is not a directory.
        """
        staging_path = f"{STAGING_DIR_PREFIX}test_regular_file"
        try:
            # Create a regular file at the staging path
            with open(staging_path, "w") as f:
                f.write("not a directory")
            os.chmod(staging_path, 0o700)

            # validate_staging_dir does NOT raise -- it passes symlink/uid checks
            # (this documents the behavior; a future S_ISDIR check would change it)
            validate_staging_dir(staging_path)

            # But it's not a directory, so downstream operations would fail
            assert os.path.isfile(staging_path)
            assert not os.path.isdir(staging_path)
        finally:
            if os.path.exists(staging_path):
                os.unlink(staging_path)

    def test_accepts_valid_own_directory(self, tmp_path):
        """A valid directory owned by current user should pass without error."""
        staging_path = f"{STAGING_DIR_PREFIX}test_valid_own"
        try:
            os.mkdir(staging_path, 0o700)

            # Should not raise
            validate_staging_dir(staging_path)
        finally:
            if os.path.isdir(staging_path):
                os.rmdir(staging_path)

    def test_mkdir_creates_new_dir_without_validation(self, tmp_path):
        """When the directory does not exist, mkdir creates it (no lstat path)."""
        staging_path = f"{STAGING_DIR_PREFIX}test_new_create"
        try:
            # Ensure it does not exist
            if os.path.exists(staging_path):
                os.rmdir(staging_path)

            validate_staging_dir(staging_path)
            assert os.path.isdir(staging_path)
            assert stat.S_IMODE(os.lstat(staging_path).st_mode) == 0o700
        finally:
            if os.path.isdir(staging_path):
                os.rmdir(staging_path)

    def test_ensure_staging_dir_propagates_runtime_error(self, tmp_path):
        """ensure_staging_dir should propagate RuntimeError from validate_staging_dir.

        This ensures callers can catch RuntimeError for graceful degradation.
        """
        with mock.patch(
            "memory_staging_utils.validate_staging_dir",
            side_effect=RuntimeError("Staging dir is a symlink (possible attack): /tmp/x"),
        ):
            with pytest.raises(RuntimeError, match="symlink"):
                ensure_staging_dir(str(tmp_path))
