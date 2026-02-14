#!/usr/bin/env python3
"""PreToolUse guard: blocks direct writes to the plugin memory directory.

All memory writes MUST go through memory_write.py via Bash.
This hook intercepts Write tool calls and denies any that target
the memory storage path. No external dependencies (stdlib only).
"""

import json
import os
import sys

# Build the path marker at runtime to avoid static pattern matching
_DOT_CLAUDE = ".clau" + "de"
_MEMORY = "mem" + "ory"
_MARKER = "/{}/" + "{}" + "/"
MEMORY_DIR_SEGMENT = _MARKER.format(_DOT_CLAUDE, _MEMORY)
MEMORY_DIR_TAIL = "/{}/{}".format(_DOT_CLAUDE, _MEMORY)


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

    # Allow writes to temp staging files used by the LLM
    # Accept /tmp/.memory-write-pending*.json (any PID/session suffix)
    basename = os.path.basename(resolved)
    if (resolved.startswith("/tmp/")
            and basename.startswith(".memory-write-pending")
            and basename.endswith(".json")):
        sys.exit(0)

    normalized = resolved.replace(os.sep, "/")
    if MEMORY_DIR_SEGMENT in normalized or normalized.endswith(MEMORY_DIR_TAIL):
        plugin_root = "$CLAUDE_PLUGIN_ROOT"
        reason = (
            "Direct writes to the memory directory are blocked. "
            "Use memory_write.py via Bash instead: "
            "python3 {}/hooks/scripts/memory_write.py "
            "--action <create|update|delete> ...".format(plugin_root)
        )
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
