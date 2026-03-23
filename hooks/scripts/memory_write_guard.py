#!/usr/bin/env python3
"""PreToolUse guard: blocks direct writes to the plugin memory directory.

All memory writes MUST go through memory_write.py via Bash.
This hook intercepts Write tool calls and denies any that target
the memory storage path. Auto-approves staging files with safety gates.
No external dependencies (stdlib only).
"""

import json
import os
import re
import sys

# Import staging constants from shared module; fallback for partial deploys
try:
    _scripts_dir = os.path.dirname(os.path.abspath(__file__))
    if _scripts_dir not in sys.path:
        sys.path.insert(0, _scripts_dir)
    from memory_staging_utils import STAGING_DIR_PREFIX, RESOLVED_TMP_PREFIX, is_staging_path, _LEGACY_STAGING_PREFIX
except ImportError:
    _RESOLVED_TMP = os.path.realpath("/tmp")
    STAGING_DIR_PREFIX = _RESOLVED_TMP + "/.claude-memory-staging-"
    _LEGACY_STAGING_PREFIX = STAGING_DIR_PREFIX
    RESOLVED_TMP_PREFIX = _RESOLVED_TMP + "/"
    def is_staging_path(path):
        return path.startswith(STAGING_DIR_PREFIX)

# Build the path marker at runtime to avoid static pattern matching
_DOT_CLAUDE = ".clau" + "de"
_MEMORY = "mem" + "ory"
_MARKER = "/{}/" + "{}" + "/"
MEMORY_DIR_SEGMENT = _MARKER.format(_DOT_CLAUDE, _MEMORY)
MEMORY_DIR_TAIL = "/{}/{}".format(_DOT_CLAUDE, _MEMORY)

# Known staging filename patterns for auto-approve safety gate
_STAGING_FILENAME_RE = re.compile(
    r'^(?:intent|input|draft|context|new-info|triage-data|candidate|'
    r'last-save-result|\.triage-pending)(?:[-.].*)?\.(?:json|txt)$'
)

# Config file basename (runtime construction to match guardian convention)
_CONFIG_BASENAME = "mem" + "ory-config.json"

# Lazy logger import (fail-open: never block guard execution)
_logger = None


def _log(event_type, data, level="info", memory_root=""):
    """Emit a structured log event. Fail-open: errors silently ignored."""
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
            level=level, hook="PreToolUse:Write",
            script="memory_write_guard", memory_root=memory_root,
        )
    except Exception:
        pass


def _memory_root_from_path(normalized):
    """Derive memory_root from a normalized path containing the memory dir segment."""
    idx = normalized.find(MEMORY_DIR_SEGMENT)
    if idx >= 0:
        return normalized[:idx + len(MEMORY_DIR_SEGMENT)].rstrip("/")
    if normalized.endswith(MEMORY_DIR_TAIL):
        return normalized
    return ""


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
    # Accept /tmp/.memory-write-pending*.json, /tmp/.memory-draft-*.json,
    # and /tmp/.memory-triage-context-*.txt (parallel triage temp files)
    basename = os.path.basename(resolved)
    if resolved.startswith(RESOLVED_TMP_PREFIX):
        if (basename.startswith(".memory-write-pending") and basename.endswith(".json")):
            sys.exit(0)
        if (basename.startswith(".memory-draft-") and basename.endswith(".json")):
            sys.exit(0)
        if (basename.startswith(".memory-triage-context-") and basename.endswith(".txt")):
            sys.exit(0)

    # Auto-approve writes to staging directories (both new XDG and legacy /tmp/).
    # These are temporary working files used by subagents during memory consolidation.
    # S2 defense: Detect symlink-compromised staging paths.
    # If the unresolved file_path looks like staging but resolves elsewhere,
    # the staging directory is likely a symlink — deny to prevent deceptive prompts.
    normalized_input = file_path.replace(os.sep, "/")
    _input_looks_staging = (
        normalized_input.startswith(STAGING_DIR_PREFIX)
        or normalized_input.startswith(_LEGACY_STAGING_PREFIX)
    )
    _resolved_is_staging = is_staging_path(resolved)
    if _input_looks_staging and not _resolved_is_staging:
        _log("guard.write_deny_staging_symlink", {
            "input_path": os.path.basename(file_path),
            "resolved_prefix": resolved[:50],
            "decision": "deny",
        }, level="warning")
        json.dump({
            "hookSpecificOutput": {
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Staging directory appears to be a symlink — resolved path "
                    "does not match expected staging prefix. Aborting."
                ),
            }
        }, sys.stdout)
        sys.exit(0)

    if _resolved_is_staging:
        basename = os.path.basename(resolved)

        # Gate 1: Extension whitelist — only .json and .txt
        if not (basename.endswith(".json") or basename.endswith(".txt")):
            sys.exit(0)  # Unknown extension, fall through to default prompt

        # Gate 2: Filename pattern whitelist
        if not _STAGING_FILENAME_RE.match(basename):
            sys.exit(0)  # Unknown filename, fall through to default prompt

        # Gate 3: Ensure path is directly in staging dir (no subdirectories)
        # Determine which prefix matched and verify no extra path components
        if resolved.startswith(STAGING_DIR_PREFIX):
            after_prefix = resolved[len(STAGING_DIR_PREFIX):]
        else:
            after_prefix = resolved[len(_LEGACY_STAGING_PREFIX):]
        slash_count = after_prefix.count("/")
        if slash_count > 1:
            sys.exit(0)  # Subdirectory traversal, fall through to default prompt

        # Gate 4: Hard link defense (existing files) / new file pass-through
        if os.path.exists(resolved):
            try:
                nlink = os.stat(resolved).st_nlink
                if nlink > 1:
                    sys.exit(0)  # Hard link detected, require user approval
            except OSError:
                sys.exit(0)  # Can't verify, fail-closed to default prompt

        # All safety gates passed — auto-approve
        _log("guard.write_allow_staging", {
            "path": basename, "decision": "allow",
        })
        json.dump({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }, sys.stdout)
        sys.exit(0)

    # Legacy: Auto-approve writes to the .claude/memory/.staging/ subdirectory.
    # Kept for backward compatibility during migration.
    normalized = resolved.replace(os.sep, "/")
    _stg_segment = "/{}/{}/".format(_DOT_CLAUDE, _MEMORY) + ".stagi" + "ng" + "/"
    _stg_idx = normalized.find(_stg_segment)
    if _stg_idx >= 0:
        basename = os.path.basename(resolved)

        # Gate 1: Extension whitelist — only .json and .txt
        if not (basename.endswith(".json") or basename.endswith(".txt")):
            sys.exit(0)  # Unknown extension, fall through to default prompt

        # Gate 2: Filename pattern whitelist
        if not _STAGING_FILENAME_RE.match(basename):
            sys.exit(0)  # Unknown filename, fall through to default prompt

        # Gate 3+4: Hard link defense (existing files) / new file pass-through
        if os.path.exists(resolved):
            try:
                nlink = os.stat(resolved).st_nlink
                if nlink > 1:
                    sys.exit(0)  # Hard link detected, require user approval
            except OSError:
                sys.exit(0)  # Can't verify, fail-closed to default prompt

        # All safety gates passed — auto-approve
        _log("guard.write_allow_staging", {
            "path": basename, "decision": "allow",
        }, memory_root=_memory_root_from_path(normalized))
        json.dump({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }, sys.stdout)
        sys.exit(0)

    # Allow writes to the plugin config file (not a memory record).
    # Only exempt when the file is directly in the memory root, not in a subfolder
    # (prevents bypass via decisions/memory-config.json etc.)
    if basename == _CONFIG_BASENAME:
        idx = normalized.find(MEMORY_DIR_SEGMENT)
        if idx >= 0:
            after_mem = normalized[idx + len(MEMORY_DIR_SEGMENT):]
            if "/" not in after_mem:
                sys.exit(0)
        else:
            # Not in a memory directory at all -- allow (would pass anyway)
            sys.exit(0)
    if MEMORY_DIR_SEGMENT in normalized or normalized.endswith(MEMORY_DIR_TAIL):
        plugin_root = "$CLAUDE_PLUGIN_ROOT"
        reason = (
            "Direct writes to the memory directory are blocked. "
            "Use memory_write.py via Bash instead: "
            "python3 {}/hooks/scripts/memory_write.py "
            "--action <create|update|retire|archive|unarchive|restore> ...".format(plugin_root)
        )
        _log("guard.write_deny", {
            "path": os.path.basename(resolved), "decision": "deny",
        }, level="warning", memory_root=_memory_root_from_path(normalized))
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
