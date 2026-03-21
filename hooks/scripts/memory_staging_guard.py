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


# Detect bash writes targeting .staging/ directory
_STAGING_WRITE_PATTERN = re.compile(
    r'(?:cat|echo|printf)\s+[^|&;\n>\s]*>\s*[^\s]*\.claude/memory/\.staging/'
    r'|'
    r'\btee\s+.*\.claude/memory/\.staging/'
    r'|'
    r'(?:cp|mv|install|dd)\s+.*\.claude/memory/\.staging/'
    r'|'
    r'\b(?:ln|link)\s+.*\.claude/memory/\.staging/'
    r'|'
    r'[&]?>{1,2}\s*[^\s]*\.claude/memory/\.staging/',
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
            "Bash writes to .claude/memory/.staging/ are blocked to prevent "
            "guardian false positives. Use the Write tool instead: "
            "Write(file_path='.claude/memory/.staging/<filename>', content='<json>')"
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
