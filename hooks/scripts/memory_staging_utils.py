#!/usr/bin/env python3
"""Shared staging path utilities for claude-memory plugin.

Provides a deterministic /tmp/-based staging directory for each project,
avoiding Claude Code's hardcoded .claude/ protected directory prompts.

The staging directory uses a SHA-256 hash of the project's real path
to ensure isolation between projects sharing the same system.

No external dependencies (stdlib only).
"""

from __future__ import annotations

import hashlib
import os
import stat

# Prefix for all staging directories — matches guard pattern checks.
# Use os.path.realpath("/tmp") to handle macOS where /tmp -> /private/tmp.
# After Path.resolve() or os.path.realpath(), paths become /private/tmp/...
# which would fail a startswith("/tmp/...") check.
_RESOLVED_TMP = os.path.realpath("/tmp")
STAGING_DIR_PREFIX = _RESOLVED_TMP + "/.claude-memory-staging-"
RESOLVED_TMP_PREFIX = _RESOLVED_TMP + "/"


def get_staging_dir(cwd: str = "") -> str:
    """Get deterministic /tmp/ staging directory for the current project.

    Uses SHA-256 hash of the project's real path to avoid collisions
    between multiple projects on the same machine.

    Args:
        cwd: Project root directory. If empty, uses os.getcwd().

    Returns:
        Absolute path to the staging directory (may not exist yet).
    """
    if not cwd:
        cwd = os.getcwd()
    # Hash formula: UID:realpath(cwd) for per-user isolation.
    # Changed from realpath(cwd)-only in v5.1.0.
    # Orphaned dirs from old formula are harmless (cleaned by OS on reboot).
    project_hash = hashlib.sha256(f"{os.geteuid()}:{os.path.realpath(cwd)}".encode()).hexdigest()[:12]
    return f"{STAGING_DIR_PREFIX}{project_hash}"


def ensure_staging_dir(cwd: str = "") -> str:
    """Create staging directory if it doesn't exist. Returns the path.

    Sets restrictive permissions (0o700) to prevent other users from
    reading or writing staging files. If the directory already exists,
    validates it is not a symlink and is owned by the current user
    (defense against symlink squatting in /tmp/).

    Args:
        cwd: Project root directory. If empty, uses os.getcwd().

    Returns:
        Absolute path to the (now existing) staging directory.

    Raises:
        RuntimeError: If the directory is a symlink or owned by another user.
    """
    staging_dir = get_staging_dir(cwd)
    validate_staging_dir(staging_dir)
    return staging_dir


def _validate_existing_staging(staging_dir: str) -> None:
    """Validate an existing staging directory (symlink, type, ownership, perms).

    Called when os.mkdir raises FileExistsError -- the path already exists,
    so we must verify it hasn't been tampered with.

    Args:
        staging_dir: Absolute path to the staging directory.

    Raises:
        RuntimeError: If the path is a symlink, not a directory, or foreign-owned.
    """
    st = os.lstat(staging_dir)
    if stat.S_ISLNK(st.st_mode):
        raise RuntimeError(
            f"Staging dir is a symlink (possible attack): {staging_dir}"
        )
    if not stat.S_ISDIR(st.st_mode):
        raise RuntimeError(
            f"Staging path exists but is not a directory: {staging_dir}"
        )
    if st.st_uid != os.geteuid():
        raise RuntimeError(
            f"Staging dir owned by uid {st.st_uid}, "
            f"expected {os.geteuid()}: {staging_dir}"
        )
    if stat.S_IMODE(st.st_mode) & 0o077:
        # TOCTOU note: the window between lstat and chmod is practically
        # unexploitable -- /tmp/ has sticky bit, legacy paths are in
        # the user's workspace. An attacker cannot delete+replace the
        # directory in this window without already having write access.
        try:
            os.chmod(staging_dir, 0o700, follow_symlinks=False)
        except (NotImplementedError, OSError):
            os.chmod(staging_dir, 0o700)


def validate_staging_dir(staging_dir: str) -> None:
    """Ensure a staging directory exists with safe ownership/permissions.

    For /tmp/ staging paths: uses mkdir + lstat validation (symlink/ownership).
    For legacy paths (not in /tmp/): uses makedirs for parents + mkdir for
    the final .staging component with lstat validation (symlink/ownership).

    Args:
        staging_dir: Absolute path to the staging directory.

    Raises:
        RuntimeError: If the directory is a symlink, not a directory,
            or foreign-owned.
    """
    if staging_dir.startswith(STAGING_DIR_PREFIX):
        try:
            os.mkdir(staging_dir, 0o700)
        except FileExistsError:
            _validate_existing_staging(staging_dir)
    else:
        # Legacy path (e.g. <cwd>/.claude/memory/.staging)
        # Use makedirs for parents only, mkdir for the final component
        # to get atomic creation + symlink/ownership defense.
        parent = os.path.dirname(staging_dir)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent, mode=0o700, exist_ok=True)
        try:
            os.mkdir(staging_dir, 0o700)
        except FileExistsError:
            _validate_existing_staging(staging_dir)


def is_staging_path(path: str) -> bool:
    """Check if a resolved path is within a claude-memory staging directory.

    Args:
        path: Resolved (realpath) file path to check.

    Returns:
        True if the path is within a /tmp/.claude-memory-staging-* directory.
    """
    return path.startswith(STAGING_DIR_PREFIX)
