#!/usr/bin/env python3
"""Shared staging path utilities for claude-memory plugin.

Provides a deterministic staging directory for each project, using the
most secure per-user directory available on the platform (XDG_RUNTIME_DIR,
/run/user/$UID, macOS per-user temp, or ~/.cache fallback).

The staging directory uses a SHA-256 hash of the project's real path
to ensure isolation between projects sharing the same system.

No external dependencies (stdlib only).
"""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
import sys
import time


# Resolve /tmp for legacy compatibility checks.
_RESOLVED_TMP = os.path.realpath("/tmp")
# Legacy prefix — kept for backward compatibility (guards, existing staging dirs)
_LEGACY_STAGING_PREFIX = _RESOLVED_TMP + "/.claude-memory-staging-"
RESOLVED_TMP_PREFIX = _RESOLVED_TMP + "/"


def _resolve_staging_base() -> str:
    """Determine the best staging base directory for this platform.

    Priority order (first valid candidate wins):
    1. XDG_RUNTIME_DIR — if set, 0700, owned by euid, is a directory
    2. /run/user/$UID — if exists, 0700, owned by euid (Linux systemd)
    3. macOS per-user temp — via os.confstr("CS_DARWIN_USER_TEMP_DIR")
    4. $XDG_CACHE_HOME/claude-memory/staging (or ~/.cache/claude-memory/staging)

    No /tmp/ fallback — the goal is to eliminate the /tmp/ attack class.

    Returns:
        Absolute path to the staging base directory.
    """
    euid = os.geteuid()

    # 1. XDG_RUNTIME_DIR (strict 0700 check — rejects WSL2's 0777)
    xrd = os.environ.get("XDG_RUNTIME_DIR", "").rstrip("/")
    if xrd and os.path.isabs(xrd) and os.path.isdir(xrd):
        try:
            st = os.lstat(xrd)
            if (st.st_uid == euid
                    and stat.S_ISDIR(st.st_mode)
                    and not stat.S_ISLNK(st.st_mode)
                    and stat.S_IMODE(st.st_mode) == 0o700):
                return xrd
        except OSError:
            pass

    # 2. /run/user/$UID (Linux systemd, even if XDG_RUNTIME_DIR not set)
    run_user = f"/run/user/{euid}"
    if os.path.isdir(run_user):
        try:
            st = os.lstat(run_user)
            if (st.st_uid == euid
                    and stat.S_ISDIR(st.st_mode)
                    and not stat.S_ISLNK(st.st_mode)
                    and stat.S_IMODE(st.st_mode) == 0o700):
                return run_user
        except OSError:
            pass

    # 3. macOS per-user temp (bypasses TMPDIR env var)
    if sys.platform == "darwin":
        try:
            darwin_tmp = os.confstr("CS_DARWIN_USER_TEMP_DIR")
            if darwin_tmp and os.path.isdir(darwin_tmp):
                st = os.lstat(darwin_tmp)
                if (st.st_uid == euid
                        and stat.S_ISDIR(st.st_mode)
                        and stat.S_IMODE(st.st_mode) & 0o077 == 0):
                    return darwin_tmp.rstrip("/")
        except (ValueError, AttributeError, OSError):
            pass

    # 4. Universal fallback: $XDG_CACHE_HOME/claude-memory/staging
    cache_home = os.environ.get("XDG_CACHE_HOME")
    if not cache_home or not os.path.isabs(cache_home):
        cache_home = os.path.join(os.path.expanduser("~"), ".cache")
    staging_base = os.path.join(cache_home, "claude-memory", "staging")
    # Ensure the directory exists with 0700
    os.makedirs(staging_base, mode=0o700, exist_ok=True)
    # Tighten permissions if pre-existing directory is too loose
    try:
        st = os.lstat(staging_base)
        if stat.S_ISDIR(st.st_mode) and stat.S_IMODE(st.st_mode) & 0o077:
            os.chmod(staging_base, 0o700)
    except OSError:
        pass
    return staging_base


# New staging base — determined at module load time
_STAGING_BASE = _resolve_staging_base()
STAGING_DIR_PREFIX = _STAGING_BASE + "/.claude-memory-staging-"


def get_staging_dir(cwd: str = "") -> str:
    """Get deterministic staging directory for the current project.

    Uses SHA-256 hash of the project's real path to avoid collisions
    between multiple projects on the same machine. The base directory
    is determined by _resolve_staging_base() (XDG_RUNTIME_DIR, /run/user,
    macOS per-user temp, or ~/.cache fallback).

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


def _cleanup_stale_staging(staging_dir: str) -> None:
    """Remove sibling staging dirs older than 7 days (for persistent storage only).

    Only runs for non-/tmp/ paths — /tmp/ paths are cleaned by the OS.
    Silently ignores any errors (best-effort cleanup).

    Args:
        staging_dir: The current (active) staging directory path.
    """
    parent = os.path.dirname(staging_dir)
    if not parent or parent.startswith(_RESOLVED_TMP):
        return  # /tmp/ paths are cleaned by OS
    try:
        cutoff = time.time() - 7 * 86400
        for entry in os.scandir(parent):
            if (entry.name.startswith(".claude-memory-staging-")
                    and entry.name != os.path.basename(staging_dir)
                    and entry.is_dir(follow_symlinks=False)):
                try:
                    if entry.stat(follow_symlinks=False).st_mtime < cutoff:
                        import shutil
                        shutil.rmtree(entry.path)
                except OSError:
                    pass
    except OSError:
        pass


def ensure_staging_dir(cwd: str = "") -> str:
    """Create staging directory if it doesn't exist. Returns the path.

    Sets restrictive permissions (0o700) to prevent other users from
    reading or writing staging files. If the directory already exists,
    validates it is not a symlink and is owned by the current user.

    For persistent storage paths (non-/tmp/), also sweeps sibling
    staging dirs older than 7 days.

    Args:
        cwd: Project root directory. If empty, uses os.getcwd().

    Returns:
        Absolute path to the (now existing) staging directory.

    Raises:
        RuntimeError: If the directory is a symlink or owned by another user.
    """
    staging_dir = get_staging_dir(cwd)
    validate_staging_dir(staging_dir)
    _cleanup_stale_staging(staging_dir)
    return staging_dir


def _validate_parent_chain(target_path: str) -> str:
    """Walk resolved path from root to target, validating ownership.

    Resolves the path first (via os.path.realpath) to handle legitimate OS
    symlinks (e.g., macOS /var -> /private/var, Fedora /home -> /var/home).
    Then walks the resolved path checking that each existing component:
    1. Is a real directory (not a file, FIFO, socket, etc.)
    2. Is owned by the current user or root (uid 0)

    Attacker-injected symlinks pointing to foreign-owned directories are
    caught by the ownership check on the resolved target — realpath()
    resolves through the attacker's symlink to the attacker's directory,
    whose foreign uid triggers rejection.

    Components that do not exist yet are acceptable -- they will be created
    by the subsequent os.makedirs() call.

    Args:
        target_path: Absolute path to the staging directory.

    Returns:
        The resolved (realpath) version of target_path. Callers should use
        this for subsequent mkdir/makedirs to ensure operations target the
        validated path, not the original (possibly symlinked) path.

    Raises:
        RuntimeError: If any ancestor is a non-directory or owned by a
            non-root, non-current user.
        ValueError: If target_path is not absolute.
    """
    if not os.path.isabs(target_path):
        raise ValueError(f"target_path must be absolute: {target_path}")

    # Resolve symlinks first to handle legitimate OS symlinks.
    # Attacker symlinks are caught by ownership check on resolved target.
    resolved = os.path.realpath(target_path)
    components = resolved.split(os.sep)
    # components[0] is '' for absolute paths on Unix
    euid = os.geteuid()

    current = os.sep  # Start at filesystem root
    for comp in components[1:]:  # Skip the empty first element
        current = os.path.join(current, comp)

        try:
            st = os.lstat(current)
        except FileNotFoundError:
            # This component and all subsequent ones don't exist yet.
            # They will be created by os.makedirs(). Safe to stop here.
            break
        except PermissionError:
            # Cannot lstat this component -- fail-closed.
            raise RuntimeError(
                f"Cannot lstat ancestor (permission denied): {current}"
            )

        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError(
                f"Ancestor exists but is not a directory: {current}"
            )

        # Ownership check: accept current user or root (uid 0).
        if st.st_uid != euid and st.st_uid != 0:
            raise RuntimeError(
                f"Ancestor owned by uid {st.st_uid}, expected "
                f"{euid} or 0 (root): {current}"
            )

    return resolved


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

    For new or legacy /tmp/ staging paths: uses mkdir + lstat validation
    (symlink/ownership). For truly legacy paths (e.g. .claude/memory/.staging):
    uses makedirs for parents + mkdir for the final component with lstat
    validation (symlink/ownership).

    Args:
        staging_dir: Absolute path to the staging directory.

    Raises:
        RuntimeError: If the directory is a symlink, not a directory,
            or foreign-owned.
    """
    if staging_dir.startswith(STAGING_DIR_PREFIX) or staging_dir.startswith(_LEGACY_STAGING_PREFIX):
        try:
            os.mkdir(staging_dir, 0o700)
        except FileExistsError:
            _validate_existing_staging(staging_dir)
    else:
        # Legacy path (e.g. <cwd>/.claude/memory/.staging)
        # Validate parent chain before creating any directories.
        # Use the resolved path for subsequent operations to ensure we
        # operate on the validated path, not the original (possibly symlinked).
        resolved = _validate_parent_chain(staging_dir)
        # Use makedirs for parents only, mkdir for the final component
        # to get atomic creation + symlink/ownership defense.
        parent = os.path.dirname(resolved)
        if parent:
            try:
                st = os.lstat(parent)
                if not stat.S_ISDIR(st.st_mode):
                    os.makedirs(parent, mode=0o700, exist_ok=True)
            except FileNotFoundError:
                os.makedirs(parent, mode=0o700, exist_ok=True)
        try:
            os.mkdir(resolved, 0o700)
        except FileExistsError:
            _validate_existing_staging(resolved)


def is_staging_path(path: str) -> bool:
    """Check if a resolved path is within a claude-memory staging directory.

    Accepts both the current staging base and the legacy /tmp/ prefix,
    ensuring backward compatibility during migration.

    Args:
        path: Resolved (realpath) file path to check.

    Returns:
        True if the path is within a staging directory (new or legacy).
    """
    return path.startswith(STAGING_DIR_PREFIX) or path.startswith(_LEGACY_STAGING_PREFIX)


# --- Portable O_DIRECTORY / O_NOFOLLOW flags ---
_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

# Maximum retries for unique temp file names (O_EXCL collision)
_TEMP_MAX_RETRIES = 5


class PinnedStagingDir:
    """TOCTOU-safe staging directory backed by fd-pinning.

    Opens the staging directory with O_DIRECTORY|O_NOFOLLOW, validates
    ownership via fstat(fd), and provides dir_fd for all file operations.
    This eliminates the TOCTOU window between path validation and use.

    Usage::

        with PinnedStagingDir(cwd="/path/to/project") as pin:
            pin.write_file("triage-data.json", data_bytes)
            content = pin.read_file("triage-data.json")
            pin.unlink("triage-data.json")

        # Or from an explicit path:
        with PinnedStagingDir(path="/tmp/.claude-memory-staging-abc123") as pin:
            ...

    The pinned fd ensures that even if the staging directory path is
    replaced with a symlink after validation, all operations continue
    on the original validated directory inode.
    """

    def __init__(self, cwd: str = "", path: str = ""):
        """Initialize PinnedStagingDir.

        Args:
            cwd: Project root. Used to compute staging dir via get_staging_dir().
                 Ignored if ``path`` is provided.
            path: Explicit staging directory path. If provided, used directly
                  instead of computing from cwd.
        """
        self._cwd = cwd
        self._explicit_path = path
        self._fd: int = -1
        self._path: str = ""

    def __enter__(self) -> PinnedStagingDir:
        if self._explicit_path:
            self._path = self._explicit_path
        else:
            self._path = get_staging_dir(self._cwd)

        # Step 1: Ensure directory exists (mkdir if needed).
        validate_staging_dir(self._path)

        # Step 2: Open with O_DIRECTORY|O_NOFOLLOW — rejects symlinks
        # atomically at open time.
        try:
            self._fd = os.open(
                self._path,
                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
            )
        except OSError as e:
            raise RuntimeError(
                f"Cannot open staging dir (symlink or not a directory?): "
                f"{self._path}: {e}"
            ) from e

        # Step 3: Validate via fstat (no TOCTOU — operates on fd).
        try:
            st = os.fstat(self._fd)
            if st.st_uid != os.geteuid():
                raise RuntimeError(
                    f"Staging dir owned by uid {st.st_uid}, "
                    f"expected {os.geteuid()}: {self._path}"
                )
            # Fix permissions if too loose — fchmod operates on fd, no TOCTOU.
            if stat.S_IMODE(st.st_mode) & 0o077:
                os.fchmod(self._fd, 0o700)
        except Exception:
            os.close(self._fd)
            self._fd = -1
            raise

        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    @property
    def fd(self) -> int:
        """The pinned directory file descriptor."""
        return self._fd

    @property
    def path(self) -> str:
        """The directory path (for logging/subprocess args — NOT for file ops)."""
        return self._path

    @staticmethod
    def _validate_name(name: str) -> None:
        """Reject filenames that could escape the pinned directory."""
        if not name or os.sep in name or name in (".", "..") or "\0" in name:
            raise ValueError(
                f"Invalid staging filename (must be a simple name, "
                f"no path separators or traversal): {name!r}"
            )

    def open_file(self, name: str, flags: int, mode: int = 0o600) -> int:
        """Open a file within the pinned directory via dir_fd.

        Args:
            name: Filename (not a path — must not contain os.sep or '..').
            flags: os.O_* flags. O_NOFOLLOW is added automatically.
            mode: File creation mode (default 0o600).

        Returns:
            File descriptor. Caller must close it.

        Raises:
            ValueError: If name contains path separators or traversal.
        """
        self._validate_name(name)
        return os.open(name, flags | _O_NOFOLLOW, mode, dir_fd=self._fd)

    def write_file(self, name: str, content: str | bytes) -> None:
        """Atomically write content to a file within the pinned directory.

        Uses a temporary file + rename pattern for atomicity. The temp file
        is created with O_EXCL (retry loop for collision resistance).
        Uses a write loop to handle short writes for large content.

        Args:
            name: Target filename.
            content: Content to write. Strings are UTF-8 encoded.
        """
        self._validate_name(name)
        if isinstance(content, str):
            content = content.encode("utf-8")

        # Create temp file with O_EXCL — retry with new random suffix on collision.
        tmp_name = ""
        fd = -1
        for _attempt in range(_TEMP_MAX_RETRIES):
            suffix = secrets.token_hex(4)
            tmp_name = f".{name}.{os.getpid()}.{suffix}.tmp"
            try:
                fd = os.open(
                    tmp_name,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW,
                    0o600,
                    dir_fd=self._fd,
                )
                break
            except FileExistsError:
                continue
        else:
            # Last resort: nanosecond timestamp
            tmp_name = f".{name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
            fd = os.open(
                tmp_name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_NOFOLLOW,
                0o600,
                dir_fd=self._fd,
            )

        # Write with loop for short writes, cleanup on failure.
        try:
            view = memoryview(content)
            written = 0
            while written < len(view):
                n = os.write(fd, view[written:])
                if n == 0:
                    raise OSError("os.write returned 0")
                written += n
        except Exception:
            os.close(fd)
            try:
                os.unlink(tmp_name, dir_fd=self._fd)
            except OSError:
                pass
            raise
        else:
            os.close(fd)

        # Atomic rename into place; cleanup temp on failure.
        try:
            os.rename(
                tmp_name, name,
                src_dir_fd=self._fd, dst_dir_fd=self._fd,
            )
        except Exception:
            try:
                os.unlink(tmp_name, dir_fd=self._fd)
            except OSError:
                pass
            raise

    def read_file(self, name: str, max_bytes: int = 1 << 20) -> bytes:
        """Read a file within the pinned directory.

        Args:
            name: Filename to read.
            max_bytes: Maximum bytes to read (default 1 MiB).

        Returns:
            File contents as bytes.
        """
        fd = self.open_file(name, os.O_RDONLY)
        try:
            chunks = []
            remaining = max_bytes
            while remaining > 0:
                chunk = os.read(fd, min(remaining, 65536))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    def unlink(self, name: str) -> None:
        """Delete a file within the pinned directory."""
        self._validate_name(name)
        os.unlink(name, dir_fd=self._fd)

    def listdir(self) -> list[str]:
        """List files in the pinned directory.

        Uses a duplicate fd because os.listdir() may consume the fd's
        directory stream position.
        """
        dup_fd = os.dup(self._fd)
        try:
            return os.listdir(dup_fd)
        finally:
            os.close(dup_fd)

    def exists(self, name: str) -> bool:
        """Check if a file exists within the pinned directory."""
        self._validate_name(name)
        try:
            os.stat(name, dir_fd=self._fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
