#!/usr/bin/env python3
"""Shared structured logging for claude-memory plugin.

Lightweight JSONL logger with fail-open semantics.
All errors are silently swallowed to never block hook execution.

Directory structure: {memory_root}/logs/{event_category}/{YYYY-MM-DD}.jsonl
where event_category = event_type.split('.')[0]

No external dependencies (stdlib only).
"""

import json
import math
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Level constants
# ---------------------------------------------------------------------------
_LEVELS = {"debug": 0, "info": 1, "warning": 2, "error": 3}

# Maximum number of entries in data.results to prevent oversized log lines
_MAX_RESULTS = 20

# Cleanup interval in seconds (24 hours)
_CLEANUP_INTERVAL_S = 86400

# Safe characters for event_category (path traversal prevention)
_SAFE_CATEGORY_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Portable O_NOFOLLOW -- not available on all platforms
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

def parse_logging_config(config):
    # type: (dict) -> dict
    """Parse logging config with safe defaults.

    Accepts the full plugin config dict or just the ``logging`` sub-dict.
    Returns a normalised dict with keys: enabled, level, retention_days.
    """
    try:
        if not isinstance(config, dict):
            return {"enabled": False, "level": "info", "retention_days": 14}
        log_cfg = config.get("logging", config) if "logging" in config else config
        if not isinstance(log_cfg, dict):
            log_cfg = {}
        raw_enabled = log_cfg.get("enabled", False)
        if isinstance(raw_enabled, bool):
            enabled = raw_enabled
        elif isinstance(raw_enabled, str):
            enabled = raw_enabled.lower() in ("true", "1", "yes")
        else:
            enabled = bool(raw_enabled)
        level = str(log_cfg.get("level", "info")).lower()
        if level not in _LEVELS:
            level = "info"
        try:
            retention_days = int(log_cfg.get("retention_days", 14))
            if retention_days < 0:
                retention_days = 14
        except (ValueError, TypeError, OverflowError):
            retention_days = 14
        return {"enabled": enabled, "level": level, "retention_days": retention_days}
    except Exception:
        return {"enabled": False, "level": "info", "retention_days": 14}


# ---------------------------------------------------------------------------
# Session ID extraction
# ---------------------------------------------------------------------------

def get_session_id(transcript_path):
    # type: (str) -> str
    """Extract session identifier from transcript path filename.

    Examples:
        "/tmp/transcript-abc123.json" -> "transcript-abc123"
        ""                            -> ""
        None                          -> ""
    """
    try:
        if not transcript_path:
            return ""
        # Use the stem (filename without extension)
        return Path(str(transcript_path)).stem
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Log cleanup
# ---------------------------------------------------------------------------

def cleanup_old_logs(log_root, retention_days):
    # type: (Path, int) -> None
    """Delete log files older than *retention_days*.

    Guarded by a ``{log_root}/.last_cleanup`` timestamp file so that the
    scan runs at most once per 24 hours.  All errors are silently ignored.

    A *retention_days* value of 0 disables cleanup entirely.
    Symlinks are explicitly skipped to prevent traversal attacks.
    """
    try:
        if retention_days <= 0:
            return

        log_root = Path(log_root)
        last_cleanup_file = log_root / ".last_cleanup"

        # Check time gate (use lstat to avoid symlink bypass)
        try:
            if last_cleanup_file.is_symlink():
                try:
                    last_cleanup_file.unlink()
                except OSError:
                    pass
            elif last_cleanup_file.exists():
                mtime = os.lstat(str(last_cleanup_file)).st_mtime
                if (time.time() - mtime) < _CLEANUP_INTERVAL_S:
                    return  # Too recent, skip
        except OSError:
            pass  # Cannot stat -- proceed with cleanup anyway

        # Walk log directories and remove old .jsonl files
        now = time.time()
        cutoff = now - (retention_days * 86400)

        for category_dir in log_root.iterdir():
            try:
                # Skip symlinks to prevent traversal attacks
                if category_dir.is_symlink():
                    continue
                if not category_dir.is_dir() or category_dir.name.startswith("."):
                    continue
                for log_file in category_dir.iterdir():
                    try:
                        # Skip symlinks
                        if log_file.is_symlink():
                            continue
                        if (
                            log_file.is_file()
                            and log_file.suffix == ".jsonl"
                            and log_file.stat().st_mtime < cutoff
                        ):
                            log_file.unlink()
                    except OSError:
                        pass
            except OSError:
                pass

        # Update .last_cleanup timestamp
        try:
            os.makedirs(str(log_root), mode=0o700, exist_ok=True)
            fd = os.open(
                str(last_cleanup_file),
                os.O_CREAT | os.O_WRONLY | os.O_TRUNC | _O_NOFOLLOW,
                0o600,
            )
            try:
                os.write(fd, str(now).encode("utf-8"))
            finally:
                os.close(fd)
        except OSError:
            pass

    except Exception:
        pass  # Fail-open: cleanup failure must never block


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sanitize_category(event_type):
    # type: (str) -> str
    """Extract and sanitize the event category from an event_type string.

    Returns only alphanumeric, hyphen, and underscore characters.
    Falls back to ``"unknown"`` if the result is empty or unsafe.
    """
    parts = str(event_type).split(".", 1)
    candidate = parts[0] if parts else ""
    if candidate and _SAFE_CATEGORY_RE.match(candidate):
        return candidate[:64]
    # Strip unsafe characters as last resort
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", candidate)
    result = cleaned if cleaned else "unknown"
    return result[:64]  # Limit length to avoid exceeding NAME_MAX


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------

def _json_default(obj):
    """Custom JSON serializer for emit_event.

    Converts set/frozenset to sorted lists for deterministic output,
    falls back to str() for other non-serializable types (e.g., datetime).
    """
    if isinstance(obj, (set, frozenset)):
        return sorted(obj, key=str)
    return str(obj)


# ---------------------------------------------------------------------------
# Core emit
# ---------------------------------------------------------------------------

def emit_event(
    event_type,    # type: str
    data,          # type: dict
    *,
    level="info",          # type: str
    hook="",               # type: str
    script="",             # type: str
    session_id="",         # type: str
    duration_ms=None,      # type: float
    error=None,            # type: dict
    memory_root="",        # type: str
    config=None,           # type: dict
):
    # type: (...) -> None
    """Append a single JSONL event to the appropriate log file.

    File path: ``{memory_root}/logs/{event_category}/{YYYY-MM-DD}.jsonl``
    where ``event_category = event_type.split('.')[0]``.

    **Fail-open**: any exception is silently caught so hook execution is
    never blocked.  If logging is disabled (``config.logging.enabled`` is
    ``false`` or *memory_root* is empty), the function returns immediately
    with zero file I/O.
    """
    try:
        # -- Parse config (lazy: no I/O if disabled) -----------------------
        log_cfg = parse_logging_config(config if config is not None else {})
        if not log_cfg["enabled"]:
            return
        if not memory_root:
            return

        # -- Level filtering ------------------------------------------------
        normalized_level = str(level).lower()
        event_level = _LEVELS.get(normalized_level, 1)
        min_level = _LEVELS.get(log_cfg["level"], 1)
        if event_level < min_level:
            return
        # Clamp to known levels for schema consistency
        if normalized_level not in _LEVELS:
            normalized_level = "info"

        # -- Sanitize duration_ms (prevent NaN/Infinity in JSONL) -------------
        if duration_ms is not None:
            try:
                if not math.isfinite(duration_ms):
                    duration_ms = None
            except (TypeError, ValueError):
                duration_ms = None

        # -- Truncate results[] if present ----------------------------------
        if isinstance(data, dict) and "results" in data:
            results = data.get("results")
            if isinstance(results, list) and len(results) > _MAX_RESULTS:
                data = dict(data)  # shallow copy to avoid mutating caller
                data["_original_results_count"] = len(results)
                data["_truncated"] = True
                data["results"] = results[:_MAX_RESULTS]

        # -- Capture time once (avoid midnight race between timestamp/filename)
        now = datetime.now(timezone.utc)

        # -- Build log entry ------------------------------------------------
        entry = {
            "schema_version": 1,
            "timestamp": now.strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )[:-3] + "Z",  # millisecond precision, UTC
            "event_type": str(event_type),
            "level": normalized_level,
            "hook": str(hook),
            "script": str(script),
            "session_id": str(session_id),
            "duration_ms": duration_ms,
            "data": data if isinstance(data, dict) else {},
            "error": error,
        }

        line_bytes = (
            json.dumps(
                entry, ensure_ascii=False, separators=(",", ":"),
                default=_json_default, allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

        # -- Resolve log file path (sanitized category) ---------------------
        event_category = _sanitize_category(event_type)
        date_str = now.strftime("%Y-%m-%d")

        logs_root = Path(str(memory_root)) / "logs"
        log_dir = logs_root / event_category
        os.makedirs(str(log_dir), mode=0o700, exist_ok=True)

        # -- Containment check (prevent symlink traversal via makedirs) -----
        try:
            log_dir.resolve().relative_to(logs_root.resolve())
        except ValueError:
            return  # Symlink escape detected

        log_path = str(log_dir / (date_str + ".jsonl"))

        # -- Atomic append (single write syscall) ---------------------------
        fd = os.open(
            log_path,
            os.O_CREAT | os.O_WRONLY | os.O_APPEND | _O_NOFOLLOW,
            0o600,
        )
        try:
            os.write(fd, line_bytes)
        finally:
            os.close(fd)

        # -- Periodic cleanup (non-blocking) --------------------------------
        cleanup_old_logs(
            Path(str(memory_root)) / "logs",
            log_cfg["retention_days"],
        )

    except Exception:
        pass  # Fail-open: never block hook execution
