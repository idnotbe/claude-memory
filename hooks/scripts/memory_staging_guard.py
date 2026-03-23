#!/usr/bin/env python3
"""PreToolUse guard: blocks Bash writes to the .staging/ directory.

Subagents must use the Write tool (not Bash heredoc/cat/echo) for staging
file writes. This prevents Guardian bash_guardian.py false positives caused
by heredoc body content triggering write detection or protected path scans.
No external dependencies (stdlib only).
"""

import json
import os
import re
import sys

# Lazy logger import (fail-open: never block guard execution)
_logger = None


def _log(event_type, data, level="info"):
    """Emit a structured log event. Fail-open."""
    global _logger
    try:
        if _logger is None:
            scripts_dir = os.path.dirname(os.path.abspath(__file__))
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            import memory_logger
            _logger = memory_logger
        # Derive memory_root from CWD
        cwd = os.getcwd()
        memory_root = os.path.join(cwd, ".claude", "memory")
        _logger.emit_event(
            event_type, data,
            level=level, hook="PreToolUse:Bash",
            script="memory_staging_guard", memory_root=memory_root,
        )
    except Exception:
        pass


# Detect bash writes targeting staging directory.
# Matches the new XDG staging path, legacy /tmp/ staging path, and .claude/memory/.staging/
# Import prefixes from shared module; fallback for partial deploys.
try:
    _scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    from memory_staging_utils import STAGING_DIR_PREFIX as _STAGING_PREFIX, _LEGACY_STAGING_PREFIX
except ImportError:
    _RESOLVED_TMP = os.path.realpath("/tmp")
    _STAGING_PREFIX = _RESOLVED_TMP + "/.claude-memory-staging-"
    _LEGACY_STAGING_PREFIX = _STAGING_PREFIX

# Build regex from both new and legacy staging prefixes plus /tmp variants.
# Collect all unique directory prefixes that could appear in command strings.
_staging_dirs = set()
# Add the new staging prefix directory (everything before .claude-memory-staging-)
_staging_dirs.add(os.path.dirname(_STAGING_PREFIX))
# Add legacy /tmp variants
_RESOLVED_TMP = os.path.realpath("/tmp")
for _t in sorted({"/tmp", _RESOLVED_TMP}):
    _staging_dirs.add(_t)
_staging_alt = "|".join(re.escape(d) for d in sorted(_staging_dirs))
_STAGING_PATH_PATTERN = (
    r'(?:\.claude/memory/\.staging/|(?:' + _staging_alt + r')/\.claude-memory-staging-[a-f0-9]+/)'
)
_STAGING_WRITE_PATTERN = re.compile(
    r'(?:cat|echo|printf)\s+[^|&;\n>\s]*>\s*[^\s]*' + _STAGING_PATH_PATTERN
    + r'|'
    r'\btee\s+.*' + _STAGING_PATH_PATTERN
    + r'|'
    r'(?:cp|mv|install|dd)\s+.*' + _STAGING_PATH_PATTERN
    + r'|'
    r'\b(?:ln|link)\s+.*' + _STAGING_PATH_PATTERN
    + r'|'
    r'[&]?>{1,2}\s*[^\s]*' + _STAGING_PATH_PATTERN,
    re.DOTALL | re.IGNORECASE,
)


def main():
    try:
        hook_input = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if hook_input.get("tool_name") != "Bash":
        sys.exit(0)

    command = hook_input.get("tool_input", {}).get("command", "")

    if _STAGING_WRITE_PATTERN.search(command):
        reason = (
            "Bash writes to memory staging directories are blocked to prevent "
            "guardian false positives. Use the Write tool instead: "
            "Write(file_path='<staging_dir>/<filename>', content='<json>')"
        )
        _log("guard.staging_deny", {
            "command_preview": command[:100], "decision": "deny",
        }, level="warning")
        json.dump({
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }, sys.stdout)
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
