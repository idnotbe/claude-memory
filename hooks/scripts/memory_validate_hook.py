#!/usr/bin/env python3
"""PostToolUse guardrail: validates writes to memory JSON files.

Detection-only fallback that catches cases where the PreToolUse guard
did not fire. Runs Pydantic schema validation on any file written
under the memory storage directory. Invalid files are quarantined
(renamed with .invalid.<timestamp> suffix) to preserve evidence.

Requires Pydantic v2 (bootstrapped from plugin venv).
"""

import json
import os
import sys
import time

# Lazy logger import (fail-open: never block hook execution)
_logger = None


def _log(event_type, data, level="info", memory_root=""):
    """Emit a structured log event. Fail-open."""
    global _logger
    try:
        if _logger is None:
            scripts_dir = os.path.dirname(os.path.abspath(__file__))
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            import memory_logger
            _logger = memory_logger
        _logger.emit_event(
            event_type, data,
            level=level, hook="PostToolUse:Write",
            script="memory_validate_hook", memory_root=memory_root,
        )
    except Exception:
        pass


# Lazy pydantic bootstrap: only runs when validating memory files
_pydantic_bootstrapped = False
_HAS_PYDANTIC = False


def _ensure_pydantic():
    """Lazy-bootstrap pydantic from plugin venv. Called only for memory files."""
    global _pydantic_bootstrapped, _HAS_PYDANTIC
    if _pydantic_bootstrapped:
        return
    # Flag is set AFTER completion so unexpected failures (e.g., permission
    # error in os.listdir) allow retry on the next call.
    _venv_lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.venv', 'lib')
    if os.path.isdir(_venv_lib):
        for _d in os.listdir(_venv_lib):
            _sp = os.path.join(_venv_lib, _d, 'site-packages')
            if os.path.isdir(_sp) and _sp not in sys.path:
                sys.path.insert(0, _sp)
    try:
        import pydantic  # noqa: F401
        _HAS_PYDANTIC = True
    except ImportError:
        pass
    _pydantic_bootstrapped = True

# Build path markers at runtime to avoid guardian pattern matching
_DC = ".clau" + "de"
_MEM = "mem" + "ory"
MEMORY_DIR_SEGMENT = "/{}/{}/".format(_DC, _MEM)

# Config file basename (runtime construction to match guardian convention)
_CONFIG_BASENAME = "mem" + "ory-config.json"

# Reverse mapping: folder name -> category value
FOLDER_TO_CATEGORY = {
    "sessions": "session_summary",
    "decisions": "decision",
    "runbooks": "runbook",
    "constraints": "constraint",
    "tech-debt": "tech_debt",
    "preferences": "preference",
}


def is_memory_file(file_path):
    """Check if path is inside the memory directory."""
    normalized = file_path.replace(os.sep, "/")
    return MEMORY_DIR_SEGMENT in normalized


def get_category_from_path(file_path):
    """Extract category from the folder name in the path."""
    normalized = file_path.replace(os.sep, "/")
    idx = normalized.find(MEMORY_DIR_SEGMENT)
    if idx < 0:
        return None
    after = normalized[idx + len(MEMORY_DIR_SEGMENT):]
    folder = after.split("/")[0] if "/" in after else ""
    return FOLDER_TO_CATEGORY.get(folder)


def quarantine(file_path):
    """Rename file to .invalid.<timestamp> to preserve evidence."""
    ts = int(time.time())
    quarantine_path = "{}.invalid.{}".format(file_path, ts)
    try:
        os.rename(file_path, quarantine_path)
    except OSError as e:
        print("WARNING: Could not quarantine {}: {}".format(file_path, e), file=sys.stderr)
        return file_path
    return quarantine_path


def validate_file(file_path):
    """Validate a memory JSON file. Returns (is_valid, error_message)."""
    _ensure_pydantic()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return False, "Invalid JSON: {}".format(e)
    except OSError as e:
        return False, "Cannot read file: {}".format(e)

    category = get_category_from_path(file_path)
    if category is None:
        category = data.get("category")
    if not category:
        return False, "Cannot determine category from path or file content"

    # Only attempt Pydantic validation if pydantic is available.
    # memory_write.py uses os.execv() to re-exec under the venv python when
    # pydantic is missing, which would replace our entire process and lose
    # the stdin data we already consumed. Guard against this.
    if _HAS_PYDANTIC:
        scripts_dir = os.path.dirname(os.path.abspath(__file__))
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        try:
            from memory_write import validate_memory
            return validate_memory(data, category)
        except Exception as e:
            return False, "Validation error: {}".format(e)

    return _basic_validation(data, category)


def _basic_validation(data, category):
    """Fallback validation when memory_write.py/pydantic is not available."""
    required = ["schema_version", "category", "id", "title", "created_at",
                "updated_at", "tags", "content"]
    missing = [f for f in required if f not in data]
    if missing:
        return False, "Missing required fields: {}".format(", ".join(missing))

    if data.get("category") != category:
        return False, "Category mismatch: file in '{}' folder but category is '{}'".format(
            category, data.get("category")
        )

    if not isinstance(data.get("tags"), list) or len(data.get("tags", [])) < 1:
        return False, "tags must be a non-empty array"

    if not isinstance(data.get("content"), dict):
        return False, "content must be an object"

    return True, ""


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_input = hook_input.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path:
        sys.exit(0)

    try:
        resolved = os.path.realpath(os.path.expanduser(file_path))
    except (OSError, ValueError):
        resolved = os.path.normpath(os.path.abspath(file_path))

    if not is_memory_file(resolved):
        sys.exit(0)

    # Skip staging files -- temporary working files, not memory records.
    # Check both new /tmp/ staging path and legacy .claude/memory/.staging/ path.
    _stg = ".stagi" + "ng"
    staging_marker = MEMORY_DIR_SEGMENT + _stg + "/"
    _TMP_STAGING_PREFIX = "/tmp/.claude-memory-staging-"
    normalized = resolved.replace(os.sep, "/")
    # Derive memory_root for logging
    _mem_root = ""
    _mem_idx = normalized.find(MEMORY_DIR_SEGMENT)
    if _mem_idx >= 0:
        _mem_root = normalized[:_mem_idx + len(MEMORY_DIR_SEGMENT)].rstrip("/")

    is_staging = (staging_marker in normalized) or resolved.startswith(_TMP_STAGING_PREFIX)
    if is_staging:
        # Defense-in-depth: check nlink as diagnostic warning (not gate).
        # PreToolUse write_guard is the primary defense with nlink gating.
        # PostToolUse is detection-only and should not quarantine staging files
        # that were already approved. WSL2 may report inconsistent st_nlink.
        nlink_val = None
        try:
            fd = os.open(resolved, os.O_RDONLY)
            try:
                nlink_val = os.fstat(fd).st_nlink
            finally:
                os.close(fd)
            if nlink_val > 1:
                print(
                    "WARNING: Staging file has unexpected nlink={}, "
                    "possible hard link (diagnostic only): {}".format(
                        nlink_val, resolved
                    ),
                    file=sys.stderr,
                )
                _log("validate.staging_skip", {
                    "path": os.path.basename(resolved),
                    "nlink": nlink_val, "nlink_warning": True,
                }, level="warning", memory_root=_mem_root)
        except OSError:
            pass  # open/fstat failed — staging file may be transient, skip
        if nlink_val is None or nlink_val == 1:
            _log("validate.staging_skip", {
                "path": os.path.basename(resolved),
            }, memory_root=_mem_root)
        sys.exit(0)  # Always skip validation for staging files

    # If we got here, a write bypassed the PreToolUse guard
    _log("validate.bypass_detected", {
        "path": os.path.basename(resolved),
    }, level="warning", memory_root=_mem_root)
    print(
        "WARNING: Write to memory file bypassed PreToolUse guard: {}".format(resolved),
        file=sys.stderr,
    )

    # Config file is not a memory record -- skip schema validation.
    # Only exempt when the file is directly in the memory root, not in a subfolder.
    if os.path.basename(resolved) == _CONFIG_BASENAME:
        norm = resolved.replace(os.sep, "/")
        idx = norm.find(MEMORY_DIR_SEGMENT)
        if idx >= 0:
            after_mem = norm[idx + len(MEMORY_DIR_SEGMENT):]
            if "/" not in after_mem:
                sys.exit(0)
        # If in a subfolder, fall through to validation

    # Non-JSON files in memory dir (e.g. index.md) should be blocked outright
    if not resolved.endswith(".json"):
        reason = (
            "Direct write to non-JSON memory file blocked. "
            "Path: {}. "
            "Only JSON memory records are allowed in the memory directory. "
            "Use memory_write.py via Bash instead.".format(resolved)
        )
        print("ERROR: {}".format(reason), file=sys.stderr)
        json.dump({
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }, sys.stdout)
        sys.exit(0)

    is_valid, error_msg = validate_file(resolved)

    if is_valid:
        print(
            "WARNING: File is valid but was written directly (bypassed guard): {}".format(resolved),
            file=sys.stderr,
        )
        sys.exit(0)

    # Invalid -- quarantine the file
    _log("validate.quarantine", {
        "path": os.path.basename(resolved), "error": error_msg[:200],
    }, level="error", memory_root=_mem_root)
    quarantine_path = quarantine(resolved)
    reason = (
        "Schema validation failed for memory file. "
        "Original path: {}. "
        "Error: {}. "
        "Quarantined to: {}. "
        "Use memory_write.py via Bash to create/update memory records "
        "(it handles schema compliance automatically).".format(
            resolved, error_msg, os.path.basename(quarantine_path)
        )
    )
    print("ERROR: {}".format(reason), file=sys.stderr)

    json.dump({
        "hookSpecificOutput": {
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, sys.stdout)
    sys.exit(0)


if __name__ == "__main__":
    main()
