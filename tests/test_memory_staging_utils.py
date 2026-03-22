"""Tests for memory_staging_utils.py -- shared staging path utilities.

Covers:
- get_staging_dir(): deterministic path generation, prefix, hash isolation
- ensure_staging_dir(): directory creation with permissions
- validate_staging_dir(): adversarial symlink/ownership/permissions defense
- is_staging_path(): path identification for /tmp/ staging paths
"""

import hashlib
import importlib
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS_DIR = str(Path(__file__).parent.parent / "hooks" / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import memory_staging_utils
from memory_staging_utils import (
    RESOLVED_TMP_PREFIX,
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
        expected_hash = hashlib.sha256(f"{os.geteuid()}:{real_path}".encode()).hexdigest()[:12]
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

    def test_different_users_get_different_staging_dirs(self):
        """Different UIDs should produce different staging directories.

        The hash formula includes os.geteuid() to prevent cross-user
        collisions on shared /tmp/. This is critical for multi-user
        systems where two users might work on the same project path.
        """
        with mock.patch("memory_staging_utils.os.geteuid", return_value=1000):
            path_user_1000 = memory_staging_utils.get_staging_dir("/test")
        with mock.patch("memory_staging_utils.os.geteuid", return_value=1001):
            path_user_1001 = memory_staging_utils.get_staging_dir("/test")
        assert path_user_1000 != path_user_1001, (
            "Different UIDs with same cwd should produce different staging dirs"
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

    def test_created_dir_is_real_not_symlink(self, tmp_path):
        """ensure_staging_dir should create a real dir, not follow a symlink."""
        result = ensure_staging_dir(str(tmp_path))
        assert not os.path.islink(result), "Staging dir should not be a symlink"
        assert os.path.isdir(result)


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
        target = tmp_path / "attacker_dir"
        target.mkdir()

        # Use unique /tmp/ path to avoid CI parallel conflicts
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        os.rmdir(staging_path)  # Remove so we can place a symlink
        try:
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
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        try:
            os.chmod(staging_path, 0o777)

            validate_staging_dir(staging_path)

            actual_perms = stat.S_IMODE(os.lstat(staging_path).st_mode)
            assert actual_perms == 0o700, (
                f"Expected 0o700, got {oct(actual_perms)} -- "
                f"loose permissions were not tightened"
            )
        finally:
            shutil.rmtree(staging_path, ignore_errors=True)

    def test_regular_file_at_path_raises_not_directory(self, tmp_path):
        """Regular file (not dir) at staging path should raise RuntimeError with 'not a directory'.

        A pre-existing regular file at the staging path is rejected by the
        S_ISDIR check, preventing downstream failures from trying to write
        files into a non-directory.
        """
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        os.rmdir(staging_path)  # Remove dir so we can create a file
        try:
            with open(staging_path, "w") as f:
                f.write("not a directory")
            os.chmod(staging_path, 0o700)

            with pytest.raises(RuntimeError, match="not a directory"):
                validate_staging_dir(staging_path)
        finally:
            if os.path.exists(staging_path):
                os.unlink(staging_path)

    def test_fifo_at_staging_path_raises(self, tmp_path):
        """FIFO (named pipe) at staging path should raise RuntimeError.

        An attacker could create a FIFO at the staging path before the plugin
        runs. The S_ISDIR check must reject it.
        """
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        os.rmdir(staging_path)  # Remove dir so we can create a FIFO
        try:
            os.mkfifo(staging_path, 0o700)

            with pytest.raises(RuntimeError, match="not a directory"):
                validate_staging_dir(staging_path)
        finally:
            if os.path.exists(staging_path):
                os.unlink(staging_path)

    def test_socket_at_staging_path_raises(self, tmp_path):
        """Unix socket at staging path should raise RuntimeError.

        An attacker could create a Unix socket at the staging path before the
        plugin runs. The S_ISDIR check must reject it.
        """
        import socket as _socket
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        os.rmdir(staging_path)  # Remove dir so we can create a socket
        sock = None
        try:
            sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            sock.bind(staging_path)

            with pytest.raises(RuntimeError, match="not a directory"):
                validate_staging_dir(staging_path)
        finally:
            if sock:
                sock.close()
            if os.path.exists(staging_path):
                os.unlink(staging_path)

    def test_accepts_valid_own_directory(self, tmp_path):
        """A valid directory owned by current user should pass without error."""
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        try:
            # Should not raise
            validate_staging_dir(staging_path)
        finally:
            shutil.rmtree(staging_path, ignore_errors=True)

    def test_mkdir_creates_new_dir_without_validation(self, tmp_path):
        """When the directory does not exist, mkdir creates it (no lstat path)."""
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        os.rmdir(staging_path)  # Remove so validate_staging_dir can create it
        try:
            validate_staging_dir(staging_path)
            assert os.path.isdir(staging_path)
            assert stat.S_IMODE(os.lstat(staging_path).st_mode) == 0o700
        finally:
            shutil.rmtree(staging_path, ignore_errors=True)

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


# ===================================================================
# validate_staging_dir() -- legacy path security tests
# ===================================================================

class TestValidateStagingDirLegacyPath:
    """Security tests for the legacy path branch (.claude/memory/.staging).

    These mirror the /tmp/ path security tests but target the else-branch
    that handles paths not starting with STAGING_DIR_PREFIX.
    """

    def test_legacy_staging_rejects_symlink(self, tmp_path):
        """Symlink at legacy staging path should raise RuntimeError."""
        # Set up legacy-style path: <tmp>/.claude/memory/.staging
        parent = tmp_path / ".claude" / "memory"
        parent.mkdir(parents=True)
        staging_dir = str(parent / ".staging")

        # Create an attacker target and symlink
        attacker_dir = tmp_path / "attacker_controlled"
        attacker_dir.mkdir()
        os.symlink(str(attacker_dir), staging_dir)

        with pytest.raises(RuntimeError, match="symlink"):
            validate_staging_dir(staging_dir)

    def test_legacy_staging_fixes_permissions(self, tmp_path):
        """World-readable legacy staging dir should be tightened to 0o700."""
        parent = tmp_path / ".claude" / "memory"
        parent.mkdir(parents=True)
        staging_dir = str(parent / ".staging")

        # Create with overly permissive mode
        os.mkdir(staging_dir, 0o777)

        # validate_staging_dir should fix permissions
        validate_staging_dir(staging_dir)

        actual_perms = stat.S_IMODE(os.lstat(staging_dir).st_mode)
        assert actual_perms == 0o700, (
            f"Expected 0o700, got {oct(actual_perms)} -- "
            f"loose permissions were not tightened"
        )

    def test_legacy_staging_rejects_wrong_owner(self):
        """Legacy staging dir owned by different uid should raise RuntimeError.

        Uses mocking since we can't create dirs owned by another user
        without root.
        """
        staging_dir = "/home/user/.claude/memory/.staging"

        mock_stat = mock.MagicMock()
        mock_stat.st_mode = stat.S_IFDIR | 0o700  # Regular directory
        mock_stat.st_uid = 9999  # Foreign UID

        with mock.patch("memory_staging_utils.os.mkdir", side_effect=FileExistsError):
            with mock.patch("memory_staging_utils.os.lstat", return_value=mock_stat):
                with mock.patch("memory_staging_utils.os.geteuid", return_value=1000):
                    with mock.patch("memory_staging_utils.os.path.isdir", return_value=True):
                        with pytest.raises(RuntimeError, match="owned by uid 9999"):
                            validate_staging_dir(staging_dir)

    def test_legacy_staging_creates_parents(self, tmp_path):
        """Legacy path should create parent dirs (.claude/memory/) if missing."""
        staging_dir = str(tmp_path / ".claude" / "memory" / ".staging")

        # Parents don't exist yet
        assert not os.path.isdir(str(tmp_path / ".claude"))

        validate_staging_dir(staging_dir)

        assert os.path.isdir(staging_dir)
        assert stat.S_IMODE(os.lstat(staging_dir).st_mode) == 0o700

    def test_legacy_staging_idempotent(self, tmp_path):
        """Calling validate_staging_dir twice on legacy path should work."""
        parent = tmp_path / ".claude" / "memory"
        parent.mkdir(parents=True)
        staging_dir = str(parent / ".staging")

        validate_staging_dir(staging_dir)
        validate_staging_dir(staging_dir)  # second call should not raise

        assert os.path.isdir(staging_dir)

    def test_legacy_staging_rejects_regular_file(self, tmp_path):
        """Regular file (not dir) at legacy staging path should raise RuntimeError.

        Mirrors the /tmp/ path S_ISDIR test -- ensures the legacy branch also
        rejects non-directory entries via _validate_existing_staging().
        """
        parent = tmp_path / ".claude" / "memory"
        parent.mkdir(parents=True)
        staging_path = str(parent / ".staging")

        # Create a regular file where the staging dir should be
        with open(staging_path, "w") as f:
            f.write("not a directory")
        os.chmod(staging_path, 0o700)

        with pytest.raises(RuntimeError, match="not a directory"):
            validate_staging_dir(staging_path)


# ===================================================================
# Phase 2: Cross-platform resolved /tmp/ prefix tests
# ===================================================================

class TestResolvedTmpPrefix:
    """Tests for macOS /private/tmp cross-platform compatibility.

    STAGING_DIR_PREFIX and RESOLVED_TMP_PREFIX use os.path.realpath("/tmp")
    at module load time, which returns /tmp on Linux and /private/tmp on macOS.
    """

    def test_staging_prefix_is_resolved(self):
        """STAGING_DIR_PREFIX must start with os.path.realpath('/tmp')."""
        resolved_tmp = os.path.realpath("/tmp")
        assert STAGING_DIR_PREFIX.startswith(resolved_tmp), (
            f"STAGING_DIR_PREFIX {STAGING_DIR_PREFIX!r} does not start with "
            f"os.path.realpath('/tmp') = {resolved_tmp!r}"
        )

    def test_resolved_tmp_prefix_is_resolved(self):
        """RESOLVED_TMP_PREFIX must start with os.path.realpath('/tmp')."""
        resolved_tmp = os.path.realpath("/tmp")
        assert RESOLVED_TMP_PREFIX == resolved_tmp + "/", (
            f"RESOLVED_TMP_PREFIX {RESOLVED_TMP_PREFIX!r} != "
            f"os.path.realpath('/tmp') + '/' = {resolved_tmp + '/'!r}"
        )

    def test_resolved_path_matches_staging_prefix(self, tmp_path):
        """A path created inside the staging dir, after resolve(), still matches STAGING_DIR_PREFIX."""
        staging_dir = ensure_staging_dir(str(tmp_path))
        test_file = os.path.join(staging_dir, "test-file.json")
        # Simulate what Path.resolve() or os.path.realpath() does
        resolved = os.path.realpath(test_file)
        assert resolved.startswith(STAGING_DIR_PREFIX), (
            f"Resolved path {resolved!r} does not start with "
            f"STAGING_DIR_PREFIX {STAGING_DIR_PREFIX!r}"
        )

    def test_is_staging_path_after_resolve(self, tmp_path):
        """is_staging_path works with resolved paths (cross-platform)."""
        staging_dir = ensure_staging_dir(str(tmp_path))
        test_file = os.path.join(staging_dir, "intent-session.json")
        resolved = os.path.realpath(test_file)
        assert is_staging_path(resolved), (
            f"is_staging_path({resolved!r}) returned False after resolve"
        )

    def test_macos_private_tmp_simulation(self):
        """Simulate macOS /private/tmp via monkeypatch + importlib.reload.

        On macOS, os.path.realpath("/tmp") returns "/private/tmp".
        STAGING_DIR_PREFIX is evaluated at import time, so monkeypatching
        os.path.realpath and reloading the module should change the prefix.
        """
        original_realpath = os.path.realpath

        def mock_realpath(path, *args, **kwargs):
            if path == "/tmp":
                return "/private/tmp"
            return original_realpath(path, *args, **kwargs)

        try:
            with mock.patch("os.path.realpath", side_effect=mock_realpath):
                importlib.reload(memory_staging_utils)
                assert memory_staging_utils.STAGING_DIR_PREFIX == "/private/tmp/.claude-memory-staging-", (
                    f"After reload with macOS mock, STAGING_DIR_PREFIX should be "
                    f"'/private/tmp/.claude-memory-staging-', got "
                    f"{memory_staging_utils.STAGING_DIR_PREFIX!r}"
                )
                assert memory_staging_utils.RESOLVED_TMP_PREFIX == "/private/tmp/", (
                    f"After reload with macOS mock, RESOLVED_TMP_PREFIX should be "
                    f"'/private/tmp/', got "
                    f"{memory_staging_utils.RESOLVED_TMP_PREFIX!r}"
                )
        finally:
            # Restore original module state -- MUST be outside mock.patch context
            # so the reload sees the real os.path.realpath, not the mock.
            importlib.reload(memory_staging_utils)
