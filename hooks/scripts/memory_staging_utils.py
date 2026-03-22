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
    reading or writing staging files.

    Args:
        cwd: Project root directory. If empty, uses os.getcwd().

    Returns:
        Absolute path to the (now existing) staging directory.
    """
    staging_dir = get_staging_dir(cwd)
    os.makedirs(staging_dir, mode=0o700, exist_ok=True)
    return staging_dir


def is_staging_path(path: str) -> bool:
    """Check if a resolved path is within a claude-memory staging directory.

    Args:
        path: Resolved (realpath) file path to check.

    Returns:
        True if the path is within a /tmp/.claude-memory-staging-* directory.
    """
    return path.startswith(STAGING_DIR_PREFIX)
