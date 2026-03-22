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

# Prefix for all staging directories — matches guard pattern checks
STAGING_DIR_PREFIX = "/tmp/.claude-memory-staging-"


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
    project_hash = hashlib.sha256(os.path.realpath(cwd).encode()).hexdigest()[:12]
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
    try:
        os.mkdir(staging_dir, 0o700)
    except FileExistsError:
        # Validate existing directory: reject symlinks and foreign ownership
        st = os.lstat(staging_dir)
        if stat.S_ISLNK(st.st_mode):
            raise RuntimeError(
                f"Staging dir is a symlink (possible attack): {staging_dir}"
            )
        if st.st_uid != os.geteuid():
            raise RuntimeError(
                f"Staging dir owned by uid {st.st_uid}, "
                f"expected {os.geteuid()}: {staging_dir}"
            )
        # Tighten permissions if too open (other users have access)
        if stat.S_IMODE(st.st_mode) & 0o077:
            os.chmod(staging_dir, 0o700)
    return staging_dir


def is_staging_path(path: str) -> bool:
    """Check if a resolved path is within a claude-memory staging directory.

    Args:
        path: Resolved (realpath) file path to check.

    Returns:
        True if the path is within a /tmp/.claude-memory-staging-* directory.
    """
    return path.startswith(STAGING_DIR_PREFIX)
