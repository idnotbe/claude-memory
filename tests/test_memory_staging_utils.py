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
    _LEGACY_STAGING_PREFIX,
    PinnedStagingDir,
    _validate_parent_chain,
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

    def test_legacy_staging_accepts_symlink_to_own_dir(self, tmp_path):
        """Symlink to user-owned dir at legacy staging path should be accepted.

        With the realpath approach, same-user symlinks in legacy paths are
        not an attack — they are resolved transparently. This avoids false
        positives for OS symlinks (macOS /var -> /private/var, etc.).
        """
        parent = tmp_path / ".claude" / "memory"
        parent.mkdir(parents=True)
        staging_dir = str(parent / ".staging")

        # Create a user-owned target and symlink to it
        real_target = tmp_path / "real_staging"
        real_target.mkdir()
        os.symlink(str(real_target), staging_dir)

        # Should NOT raise — symlink resolves to user-owned dir
        validate_staging_dir(staging_dir)
        # Verify the resolved directory is intact
        assert os.path.isdir(os.path.realpath(staging_dir))

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
# Phase 2: Cross-platform prefix and staging base tests
# ===================================================================

class TestResolvedTmpPrefix:
    """Tests for staging base resolution and legacy /tmp/ compatibility.

    STAGING_DIR_PREFIX now uses _resolve_staging_base() (XDG_RUNTIME_DIR,
    /run/user, macOS per-user temp, or ~/.cache fallback).
    _LEGACY_STAGING_PREFIX and RESOLVED_TMP_PREFIX still use
    os.path.realpath("/tmp") for backward compatibility.
    """

    def test_staging_prefix_uses_staging_base(self):
        """STAGING_DIR_PREFIX must use _STAGING_BASE, not /tmp/."""
        staging_base = memory_staging_utils._STAGING_BASE
        assert STAGING_DIR_PREFIX == staging_base + "/.claude-memory-staging-", (
            f"STAGING_DIR_PREFIX {STAGING_DIR_PREFIX!r} does not match "
            f"_STAGING_BASE + '/.claude-memory-staging-' = "
            f"{staging_base + '/.claude-memory-staging-'!r}"
        )

    def test_legacy_prefix_uses_resolved_tmp(self):
        """_LEGACY_STAGING_PREFIX must start with os.path.realpath('/tmp')."""
        resolved_tmp = os.path.realpath("/tmp")
        assert memory_staging_utils._LEGACY_STAGING_PREFIX == resolved_tmp + "/.claude-memory-staging-", (
            f"_LEGACY_STAGING_PREFIX {memory_staging_utils._LEGACY_STAGING_PREFIX!r} "
            f"does not match os.path.realpath('/tmp') + '/.claude-memory-staging-'"
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
        _LEGACY_STAGING_PREFIX is evaluated at import time, so monkeypatching
        os.path.realpath and reloading the module should change the legacy prefix.
        STAGING_DIR_PREFIX now depends on _resolve_staging_base(), not /tmp/.
        """
        original_realpath = os.path.realpath

        def mock_realpath(path, *args, **kwargs):
            if path == "/tmp":
                return "/private/tmp"
            return original_realpath(path, *args, **kwargs)

        try:
            with mock.patch("os.path.realpath", side_effect=mock_realpath):
                importlib.reload(memory_staging_utils)
                # Legacy prefix should use /private/tmp
                assert memory_staging_utils._LEGACY_STAGING_PREFIX == "/private/tmp/.claude-memory-staging-", (
                    f"After reload with macOS mock, _LEGACY_STAGING_PREFIX should be "
                    f"'/private/tmp/.claude-memory-staging-', got "
                    f"{memory_staging_utils._LEGACY_STAGING_PREFIX!r}"
                )
                assert memory_staging_utils.RESOLVED_TMP_PREFIX == "/private/tmp/", (
                    f"After reload with macOS mock, RESOLVED_TMP_PREFIX should be "
                    f"'/private/tmp/', got "
                    f"{memory_staging_utils.RESOLVED_TMP_PREFIX!r}"
                )
                # STAGING_DIR_PREFIX should still use _STAGING_BASE (not /tmp/)
                assert memory_staging_utils.STAGING_DIR_PREFIX == (
                    memory_staging_utils._STAGING_BASE + "/.claude-memory-staging-"
                )
        finally:
            # Restore original module state -- MUST be outside mock.patch context
            # so the reload sees the real os.path.realpath, not the mock.
            importlib.reload(memory_staging_utils)


# ===================================================================
# _resolve_staging_base() -- XDG / fallback resolution tests (P5)
# ===================================================================

class TestResolveStagingBase:
    """Tests for _resolve_staging_base() resolution chain.

    Validates the priority order: XDG_RUNTIME_DIR (0700) > /run/user/$UID >
    macOS confstr > ~/.cache/claude-memory/staging/. Each test reloads the
    module to re-trigger module-level resolution.
    """

    def test_xdg_runtime_dir_valid(self, tmp_path, monkeypatch):
        """Valid XDG_RUNTIME_DIR (0700, owned by euid) should be used."""
        xrd = tmp_path / "runtime"
        xrd.mkdir(mode=0o700)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(xrd))
        importlib.reload(memory_staging_utils)
        try:
            assert memory_staging_utils.STAGING_DIR_PREFIX.startswith(str(xrd)), (
                f"STAGING_DIR_PREFIX {memory_staging_utils.STAGING_DIR_PREFIX!r} "
                f"should start with XDG_RUNTIME_DIR {str(xrd)!r}"
            )
        finally:
            monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
            importlib.reload(memory_staging_utils)

    def test_xdg_runtime_dir_0777_rejected(self, tmp_path, monkeypatch):
        """XDG_RUNTIME_DIR with 0777 (WSL2) should be rejected."""
        xrd = tmp_path / "runtime"
        xrd.mkdir(mode=0o777)
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(xrd))
        importlib.reload(memory_staging_utils)
        try:
            assert not memory_staging_utils.STAGING_DIR_PREFIX.startswith(str(xrd)), (
                f"STAGING_DIR_PREFIX should NOT start with 0777 XDG_RUNTIME_DIR "
                f"{str(xrd)!r}, got {memory_staging_utils.STAGING_DIR_PREFIX!r}"
            )
        finally:
            monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
            importlib.reload(memory_staging_utils)

    def test_xdg_cache_home_respected(self, tmp_path, monkeypatch):
        """$XDG_CACHE_HOME should be used for the fallback path."""
        cache = tmp_path / "custom-cache"
        cache.mkdir(mode=0o700)
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        importlib.reload(memory_staging_utils)
        try:
            prefix = memory_staging_utils.STAGING_DIR_PREFIX
            # The prefix should include our custom cache path
            assert str(cache) in prefix, (
                f"STAGING_DIR_PREFIX {prefix!r} should contain "
                f"XDG_CACHE_HOME {str(cache)!r}"
            )
            assert "claude-memory" in prefix
        finally:
            monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
            importlib.reload(memory_staging_utils)

    def test_fallback_to_home_cache(self, tmp_path, monkeypatch):
        """When no runtime dir available, should fall back to ~/.cache."""
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        importlib.reload(memory_staging_utils)
        try:
            prefix = memory_staging_utils.STAGING_DIR_PREFIX
            # Should be an absolute path with the staging marker
            assert os.path.isabs(prefix), f"Prefix must be absolute: {prefix!r}"
            assert ".claude-memory-staging-" in prefix, (
                f"Prefix must contain staging marker: {prefix!r}"
            )
        finally:
            importlib.reload(memory_staging_utils)

    def test_staging_base_is_not_tmp(self, monkeypatch):
        """STAGING_DIR_PREFIX should NOT fall back to /tmp/ (P5 goal)."""
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        importlib.reload(memory_staging_utils)
        try:
            resolved_tmp = os.path.realpath("/tmp")
            assert not memory_staging_utils.STAGING_DIR_PREFIX.startswith(resolved_tmp), (
                f"STAGING_DIR_PREFIX should NOT use /tmp/: "
                f"{memory_staging_utils.STAGING_DIR_PREFIX!r}"
            )
        finally:
            importlib.reload(memory_staging_utils)

    def test_legacy_prefix_still_in_tmp(self, monkeypatch):
        """_LEGACY_STAGING_PREFIX must remain in /tmp/ for backward compat."""
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        importlib.reload(memory_staging_utils)
        try:
            resolved_tmp = os.path.realpath("/tmp")
            assert memory_staging_utils._LEGACY_STAGING_PREFIX.startswith(resolved_tmp), (
                f"_LEGACY_STAGING_PREFIX must be in /tmp/: "
                f"{memory_staging_utils._LEGACY_STAGING_PREFIX!r}"
            )
        finally:
            importlib.reload(memory_staging_utils)

    def test_xdg_runtime_dir_nonexistent_skipped(self, tmp_path, monkeypatch):
        """Non-existent XDG_RUNTIME_DIR should be skipped (no crash)."""
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "does-not-exist"))
        importlib.reload(memory_staging_utils)
        try:
            # Should have fallen back to something valid
            assert os.path.isabs(memory_staging_utils.STAGING_DIR_PREFIX)
            assert ".claude-memory-staging-" in memory_staging_utils.STAGING_DIR_PREFIX
        finally:
            monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
            importlib.reload(memory_staging_utils)

    def test_staging_base_dir_created_with_0700(self, tmp_path, monkeypatch):
        """The ~/.cache fallback should create the staging base with 0700."""
        cache = tmp_path / "fresh-cache"
        monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        importlib.reload(memory_staging_utils)
        try:
            staging_base_dir = os.path.join(str(cache), "claude-memory", "staging")
            assert os.path.isdir(staging_base_dir), (
                f"Staging base dir should be created: {staging_base_dir}"
            )
            perms = stat.S_IMODE(os.lstat(staging_base_dir).st_mode)
            assert perms == 0o700, (
                f"Staging base should have 0700, got {oct(perms)}"
            )
        finally:
            monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
            importlib.reload(memory_staging_utils)


# ===================================================================
# _validate_parent_chain() -- parent chain validation tests (P3)
# ===================================================================

class TestValidateParentChain:
    """Tests for _validate_parent_chain() function."""

    def test_valid_chain_all_owned_by_user(self, tmp_path):
        """Valid chain with all directories owned by current user."""
        chain = tmp_path / "a" / "b" / "c"
        chain.mkdir(parents=True)
        # Should not raise
        _validate_parent_chain(str(chain))

    def test_valid_chain_with_root_owned_ancestors(self):
        """Real path with root-owned system dirs (/, /tmp) should pass."""
        # /tmp is root-owned, should be accepted
        _validate_parent_chain("/tmp/test-nonexistent-dir")

    def test_accepts_symlink_to_user_owned_dir(self, tmp_path):
        """Symlink to a user-owned directory should pass (realpath resolves it)."""
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        sym = tmp_path / "sym"
        sym.symlink_to(real_dir)
        target = sym / "child"
        # After realpath, this becomes tmp_path/real/child — all user-owned
        _validate_parent_chain(str(target))

    def test_resolves_system_symlinks_transparently(self, tmp_path):
        """Symlinks in parent chain are resolved before walking — no false positives."""
        # Simulates macOS /var -> /private/var or Fedora /home -> /var/home
        real_target = tmp_path / "real_home" / "user" / "project"
        real_target.mkdir(parents=True)
        sym_home = tmp_path / "home"
        sym_home.symlink_to(tmp_path / "real_home")
        # Path goes through symlink: tmp_path/home/user/project
        # realpath resolves to: tmp_path/real_home/user/project (all user-owned)
        _validate_parent_chain(str(sym_home / "user" / "project"))

    def test_rejects_symlink_to_foreign_owned_dir(self, tmp_path, monkeypatch):
        """Symlink pointing to foreign-owned dir should be rejected via ownership check."""
        attacker_dir = tmp_path / "attacker_controlled"
        attacker_dir.mkdir()
        sym = tmp_path / ".claude"
        sym.symlink_to(attacker_dir)
        target = sym / "memory" / ".staging"
        # realpath resolves symlink: tmp_path/attacker_controlled/memory/.staging
        # We mock lstat to return foreign uid for attacker_controlled
        original_lstat = os.lstat
        resolved_attacker = str(attacker_dir)

        def mock_lstat(path, *args, **kwargs):
            result = original_lstat(path, *args, **kwargs)
            if str(path) == resolved_attacker:
                class FakeStat:
                    def __init__(self, real):
                        for attr in dir(real):
                            if attr.startswith('st_'):
                                setattr(self, attr, getattr(real, attr))
                        self.st_uid = 9999
                        self.st_mode = real.st_mode
                return FakeStat(result)
            return result

        monkeypatch.setattr(os, "lstat", mock_lstat)
        with pytest.raises(RuntimeError, match="owned by uid 9999"):
            _validate_parent_chain(str(target))

    def test_rejects_foreign_owned_ancestor(self, tmp_path, monkeypatch):
        """Foreign-owned ancestor should be rejected."""
        chain = tmp_path / "a" / "b"
        chain.mkdir(parents=True)

        original_lstat = os.lstat
        target_dir = str(tmp_path / "a")

        def mock_lstat(path, *args, **kwargs):
            result = original_lstat(path, *args, **kwargs)
            if str(path) == target_dir:
                # Return a modified stat with foreign uid
                class FakeStat:
                    def __init__(self, real):
                        for attr in dir(real):
                            if attr.startswith('st_'):
                                setattr(self, attr, getattr(real, attr))
                        self.st_uid = 9999
                        self.st_mode = real.st_mode
                return FakeStat(result)
            return result

        monkeypatch.setattr(os, "lstat", mock_lstat)
        with pytest.raises(RuntimeError, match="owned by uid 9999"):
            _validate_parent_chain(str(chain))

    def test_accepts_nonexistent_components(self, tmp_path):
        """Non-existent components should be accepted (makedirs will create)."""
        target = tmp_path / "does" / "not" / "exist" / "staging"
        # Only tmp_path exists; rest don't. Should not raise.
        _validate_parent_chain(str(target))

    def test_rejects_non_directory_ancestor(self, tmp_path):
        """Regular file where directory expected should be rejected."""
        regular_file = tmp_path / "not_a_dir"
        regular_file.write_text("I am a file")
        target = regular_file / "child"  # This path makes no sense, but tests the check
        with pytest.raises(RuntimeError, match="not a directory"):
            _validate_parent_chain(str(target))

    def test_rejects_relative_path(self):
        """Relative paths should raise ValueError."""
        with pytest.raises(ValueError, match="must be absolute"):
            _validate_parent_chain("relative/path/here")

    def test_handles_dot_dot_in_path(self, tmp_path):
        """Paths with .. should be normalized correctly."""
        chain = tmp_path / "a" / "b"
        chain.mkdir(parents=True)
        # Path with .. that normalizes to valid path
        path_with_dots = str(tmp_path / "a" / "b" / ".." / "b" / "child")
        _validate_parent_chain(path_with_dots)

    def test_permission_denied_fails_closed(self, tmp_path, monkeypatch):
        """PermissionError on lstat should fail-closed."""
        chain = tmp_path / "restricted" / "child"
        (tmp_path / "restricted").mkdir()

        original_lstat = os.lstat
        restricted_path = str(tmp_path / "restricted")

        def mock_lstat(path, *args, **kwargs):
            if str(path) == restricted_path:
                raise PermissionError("Permission denied")
            return original_lstat(path, *args, **kwargs)

        monkeypatch.setattr(os, "lstat", mock_lstat)
        with pytest.raises(RuntimeError, match="permission denied"):
            _validate_parent_chain(str(chain))

    def test_root_path_only(self):
        """Root path should pass (root is always valid)."""
        _validate_parent_chain("/")

    def test_single_level_path(self):
        """Single-level path like /staging should validate root only."""
        _validate_parent_chain("/staging-nonexistent")


# ===================================================================
# Legacy parent chain integration tests (P3)
# ===================================================================

class TestLegacyParentChainIntegration:
    """Integration tests for validate_staging_dir() legacy branch with parent chain validation."""

    def test_legacy_staging_accepts_symlink_to_user_owned_parent(self, tmp_path):
        """Legacy staging with symlink to user-owned dir should pass (realpath resolves)."""
        real_dir = tmp_path / "real_claude"
        real_dir.mkdir()
        (real_dir / "memory").mkdir()

        sym_claude = tmp_path / ".claude"
        sym_claude.symlink_to(real_dir)

        staging_path = str(tmp_path / ".claude" / "memory" / ".staging")
        # After realpath: tmp_path/real_claude/memory/.staging — all user-owned
        validate_staging_dir(staging_path)
        # Verify staging dir was created at the resolved location
        resolved = os.path.realpath(staging_path)
        assert os.path.isdir(resolved)

    def test_legacy_staging_rejects_symlink_to_foreign_parent(self, tmp_path, monkeypatch):
        """Legacy staging with symlink to foreign-owned dir should be rejected."""
        attacker_dir = tmp_path / "attacker"
        attacker_dir.mkdir()
        (attacker_dir / "memory").mkdir()

        sym_claude = tmp_path / ".claude"
        sym_claude.symlink_to(attacker_dir)

        staging_path = str(tmp_path / ".claude" / "memory" / ".staging")

        original_lstat = os.lstat
        resolved_attacker = str(attacker_dir)

        def mock_lstat(path, *args, **kwargs):
            result = original_lstat(path, *args, **kwargs)
            if str(path) == resolved_attacker:
                class FakeStat:
                    def __init__(self, real):
                        for attr in dir(real):
                            if attr.startswith('st_'):
                                setattr(self, attr, getattr(real, attr))
                        self.st_uid = 9999
                        self.st_mode = real.st_mode
                return FakeStat(result)
            return result

        monkeypatch.setattr(os, "lstat", mock_lstat)
        with pytest.raises(RuntimeError, match="owned by uid 9999"):
            validate_staging_dir(staging_path)

    def test_legacy_staging_rejects_foreign_parent(self, tmp_path, monkeypatch):
        """Legacy staging with foreign-owned parent should be rejected."""
        claude_dir = tmp_path / ".claude" / "memory"
        claude_dir.mkdir(parents=True)
        staging_path = str(claude_dir / ".staging")

        original_lstat = os.lstat
        target_dir = str(tmp_path / ".claude")

        def mock_lstat(path, *args, **kwargs):
            result = original_lstat(path, *args, **kwargs)
            if str(path) == target_dir:
                class FakeStat:
                    def __init__(self, real):
                        for attr in dir(real):
                            if attr.startswith('st_'):
                                setattr(self, attr, getattr(real, attr))
                        self.st_uid = 9999
                        self.st_mode = real.st_mode
                return FakeStat(result)
            return result

        monkeypatch.setattr(os, "lstat", mock_lstat)
        with pytest.raises(RuntimeError, match="owned by uid 9999"):
            validate_staging_dir(staging_path)

    def test_legacy_staging_creates_dirs_after_validation(self, tmp_path):
        """Valid legacy path should create all parents and staging dir."""
        staging_path = str(tmp_path / "project" / ".claude" / "memory" / ".staging")
        # Only tmp_path exists. validate_staging_dir should create everything.
        validate_staging_dir(staging_path)
        assert os.path.isdir(staging_path)

    def test_new_staging_path_works(self, tmp_path, monkeypatch):
        """Verify new staging base paths work."""
        staging_path = STAGING_DIR_PREFIX + "test123abc"
        try:
            validate_staging_dir(staging_path)
            assert os.path.isdir(staging_path)
        finally:
            if os.path.isdir(staging_path):
                os.rmdir(staging_path)

    def test_legacy_tmp_staging_path_unchanged(self, tmp_path, monkeypatch):
        """Verify legacy /tmp/ staging paths still work (no regression)."""
        staging_path = _LEGACY_STAGING_PREFIX + "test123abc"
        try:
            validate_staging_dir(staging_path)
            assert os.path.isdir(staging_path)
        finally:
            if os.path.isdir(staging_path):
                os.rmdir(staging_path)


# ===================================================================
# PinnedStagingDir -- fd-pinned TOCTOU-safe context manager
# ===================================================================

class TestPinnedStagingDir:
    """Tests for PinnedStagingDir: fd-pinned, TOCTOU-safe staging directory."""

    def test_pinned_opens_creates_directory(self, tmp_path):
        """PinnedStagingDir(cwd=tmp) creates and opens the staging dir."""
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            assert pin.fd >= 0, "fd should be a valid descriptor"
            expected = get_staging_dir(str(tmp_path))
            assert pin.path == expected
            assert os.path.isdir(pin.path)

    def test_pinned_from_explicit_path(self, tmp_path):
        """PinnedStagingDir(path=explicit) works."""
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        try:
            # Remove and let PinnedStagingDir recreate it
            os.rmdir(staging_path)
            with PinnedStagingDir(path=staging_path) as pin:
                assert pin.path == staging_path
                assert pin.fd >= 0
                assert os.path.isdir(staging_path)
        finally:
            shutil.rmtree(staging_path, ignore_errors=True)

    def test_pinned_rejects_symlink_at_staging_path(self, tmp_path):
        """Staging path is a symlink -> RuntimeError."""
        target = tmp_path / "attacker_dir"
        target.mkdir()
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        os.rmdir(staging_path)
        try:
            os.symlink(str(target), staging_path)
            with pytest.raises(RuntimeError, match="symlink"):
                with PinnedStagingDir(path=staging_path):
                    pass
        finally:
            if os.path.islink(staging_path):
                os.unlink(staging_path)

    def test_pinned_rejects_foreign_owned_directory(self):
        """Mock fstat to return foreign uid -> RuntimeError."""
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        try:
            original_fstat = os.fstat

            def mock_fstat(fd):
                result = original_fstat(fd)
                # Return a mock with foreign uid
                m = mock.MagicMock()
                m.st_uid = 9999
                m.st_mode = result.st_mode
                return m

            with mock.patch("os.fstat", side_effect=mock_fstat):
                with pytest.raises(RuntimeError, match="owned by uid 9999"):
                    with PinnedStagingDir(path=staging_path):
                        pass
        finally:
            shutil.rmtree(staging_path, ignore_errors=True)

    def test_pinned_tightens_loose_permissions_via_fchmod(self, tmp_path):
        """Dir with 0o777 -> fchmod to 0o700."""
        staging_path = tempfile.mkdtemp(prefix=".claude-memory-staging-", dir="/tmp")
        try:
            # Set overly permissive mode
            os.chmod(staging_path, 0o777)
            with PinnedStagingDir(path=staging_path) as pin:
                # After entering context, permissions should be tightened
                st = os.fstat(pin.fd)
                actual_perms = stat.S_IMODE(st.st_mode)
                assert actual_perms == 0o700, (
                    f"Expected 0o700, got {oct(actual_perms)}"
                )
        finally:
            shutil.rmtree(staging_path, ignore_errors=True)

    def test_pinned_fd_closes_on_exit(self, tmp_path):
        """fd is closed after context exit."""
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            fd = pin.fd
            assert fd >= 0
        # After exit, fd should be closed. Verify by attempting fstat.
        with pytest.raises(OSError):
            os.fstat(fd)

    def test_pinned_fd_closes_on_exception(self, tmp_path):
        """fd is closed even when exception occurs inside context."""
        fd_captured = None
        with pytest.raises(ValueError, match="deliberate"):
            with PinnedStagingDir(cwd=str(tmp_path)) as pin:
                fd_captured = pin.fd
                assert fd_captured >= 0
                raise ValueError("deliberate error")
        # fd should still be closed
        assert fd_captured is not None
        with pytest.raises(OSError):
            os.fstat(fd_captured)

    def test_pinned_write_file_atomic(self, tmp_path):
        """write_file creates file with correct content."""
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            pin.write_file("test.json", b'{"key": "value"}')
            # Verify via path-based read
            full_path = os.path.join(pin.path, "test.json")
            assert os.path.isfile(full_path)
            with open(full_path, "rb") as f:
                assert f.read() == b'{"key": "value"}'

    def test_pinned_read_file(self, tmp_path):
        """read_file returns correct bytes."""
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            pin.write_file("data.txt", b"hello world")
            content = pin.read_file("data.txt")
            assert content == b"hello world"

    def test_pinned_unlink_file(self, tmp_path):
        """unlink removes the file."""
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            pin.write_file("to_delete.txt", b"delete me")
            assert pin.exists("to_delete.txt")
            pin.unlink("to_delete.txt")
            assert not pin.exists("to_delete.txt")

    def test_pinned_listdir(self, tmp_path):
        """listdir returns file names."""
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            pin.write_file("alpha.txt", b"a")
            pin.write_file("beta.txt", b"b")
            entries = pin.listdir()
            assert "alpha.txt" in entries
            assert "beta.txt" in entries

    def test_pinned_exists(self, tmp_path):
        """exists() returns True/False correctly."""
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            assert not pin.exists("nonexistent.txt")
            pin.write_file("present.txt", b"here")
            assert pin.exists("present.txt")

    def test_pinned_write_file_overwrites(self, tmp_path):
        """write_file atomically replaces existing file."""
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            pin.write_file("overwrite.txt", b"version1")
            assert pin.read_file("overwrite.txt") == b"version1"
            pin.write_file("overwrite.txt", b"version2")
            assert pin.read_file("overwrite.txt") == b"version2"

    def test_pinned_rejects_symlink_file_within_dir(self, tmp_path):
        """open_file with O_NOFOLLOW rejects symlinks inside the dir."""
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            # Create a real file outside the staging dir
            external = tmp_path / "external_secret.txt"
            external.write_text("secret data")
            # Create a symlink inside the staging dir pointing outside
            symlink_path = os.path.join(pin.path, "evil_link")
            os.symlink(str(external), symlink_path)
            # open_file should reject the symlink due to O_NOFOLLOW
            with pytest.raises(OSError):
                pin.open_file("evil_link", os.O_RDONLY)

    # --- TOCTOU elimination tests ---

    def test_fd_pinned_immune_to_path_replacement(self, tmp_path):
        """Open PinnedStagingDir, replace path with symlink, verify write_file
        still operates on original dir (fd-pinned, not path-based).

        Renames the original directory (keeping the inode alive via fd) and
        places a symlink at the original path pointing to an attacker dir.
        The fd-based operations must still target the original inode, not
        the attacker's directory.
        """
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            staging_path = pin.path
            stashed_path = staging_path + ".stashed"
            pin.write_file("before_attack.txt", b"safe")

            # Attacker replaces the staging path with a symlink.
            # Rename (not delete) so the inode stays alive via the fd.
            attacker_dir = tmp_path / "attacker"
            attacker_dir.mkdir()
            os.rename(staging_path, stashed_path)
            os.symlink(str(attacker_dir), staging_path)

            # Write should still go to the original inode via dir_fd,
            # NOT follow the new symlink
            pin.write_file("after_attack.txt", b"still safe")

            # The file should NOT appear in the attacker directory
            assert not os.path.exists(
                os.path.join(str(attacker_dir), "after_attack.txt")
            ), "write_file followed the symlink -- TOCTOU vulnerability!"

            # The file SHOULD appear in the stashed (original inode) directory
            assert os.path.exists(
                os.path.join(stashed_path, "after_attack.txt")
            ), "write_file did not operate on the original directory inode"

            # Clean up: remove symlink, restore original name for cleanup
            os.unlink(staging_path)
            os.rename(stashed_path, staging_path)

    def test_fd_validates_via_fstat_not_lstat(self, tmp_path):
        """Verify fstat-based validation: fstat operates on the fd, not the path.

        After opening, even if lstat would return different info (e.g., due to
        path replacement), fstat still returns the original inode's metadata.
        """
        with PinnedStagingDir(cwd=str(tmp_path)) as pin:
            # fstat on the pinned fd should match the original directory
            st_fd = os.fstat(pin.fd)
            st_path = os.stat(pin.path)
            # Same inode
            assert st_fd.st_ino == st_path.st_ino, (
                "fstat(fd) and stat(path) should reference the same inode"
            )
            assert st_fd.st_uid == os.geteuid()

    # --- Regression ---

    def test_ensure_staging_dir_still_returns_path(self, tmp_path):
        """Existing API (ensure_staging_dir) still works after PinnedStagingDir addition."""
        result = ensure_staging_dir(str(tmp_path))
        assert isinstance(result, str)
        assert os.path.isdir(result)
        # Should match get_staging_dir
        assert result == get_staging_dir(str(tmp_path))
