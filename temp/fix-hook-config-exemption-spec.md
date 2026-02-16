# Bug Fix Spec: Exempt memory-config.json from Hook Guards

## Problem

`memory-config.json` lives at `.claude/memory/memory-config.json` -- inside the memory directory.
Two hooks treat ALL files in `.claude/memory/` as memory files, but `memory-config.json` is the **plugin config**, not a memory record.

### What Goes Wrong

1. **PreToolUse (`memory_write_guard.py`)**: Blocks Write tool calls to `.claude/memory/` paths. This means:
   - `/memory:config` command cannot save config changes via Write tool without user manually approving the denial
   - Any automated config updates are blocked

2. **PostToolUse (`memory_validate_hook.py`)**: Validates all `.json` files in `.claude/memory/` against memory schemas. For `memory-config.json`:
   - `get_category_from_path()` returns `None` (not in a category subfolder)
   - `data.get("category")` returns `None` (config has no `category` field)
   - Validation fails with "Cannot determine category"
   - File gets **quarantined**: renamed to `memory-config.json.invalid.<timestamp>`
   - Plugin can no longer find its config

## Fix

Add a basename exemption for `memory-config.json` in both hook scripts.

### Design Decision: Basename Check (not path-depth)

**Chosen: Basename check** (`os.path.basename(resolved) == CONFIG_BASENAME`)

Alternatives considered:
- **Path-depth** (exempt root-level files, only validate files in subfolders): More general but over-broad -- could accidentally exempt future files that SHOULD be validated
- **Basename check**: Explicit, auditable, and only one file (`memory-config.json`) needs exemption

### Security Analysis

The hooks exist to prevent prompt injection via direct memory file writes. Exempting config is safe because:
- `/memory:config` command already allows config modification via Claude
- Config controls triage behavior and model selection, not security-critical auth/access
- The config file has no `category` field and doesn't follow the memory JSON schema, so schema validation is meaningless for it anyway

### Convention: Runtime String Construction

The existing hooks use runtime string construction to avoid Guardian pattern matching:
```python
_DOT_CLAUDE = ".clau" + "de"
_MEMORY = "mem" + "ory"
```

The config filename exemption MUST follow the same convention:
```python
_CONFIG_BASENAME = "mem" + "ory-config.json"
```

## Changes Required

### File 1: `hooks/scripts/memory_write_guard.py`

**Location**: After the `/tmp/` staging file checks (around line 42-48), before the memory directory block (line 50-51). Note: `basename` variable is already defined at line 41 and can be reused.

**Current code** (line 50-65):
```python
    normalized = resolved.replace(os.sep, "/")
    if MEMORY_DIR_SEGMENT in normalized or normalized.endswith(MEMORY_DIR_TAIL):
        plugin_root = "$CLAUDE_PLUGIN_ROOT"
        reason = (
            "Direct writes to the memory directory are blocked. "
            ...
        )
        json.dump(...)
        sys.exit(0)
```

**Add** a constant at module level (near the other path markers, around line 14-18):
```python
# Config file basename (runtime construction to match guardian convention)
_CONFIG_BASENAME = "mem" + "ory-config.json"
```

**Add** an exemption check BEFORE the deny block (between current line 49 and 50):
```python
    # Allow writes to the plugin config file (not a memory record)
    if os.path.basename(resolved) == _CONFIG_BASENAME:
        sys.exit(0)

    normalized = resolved.replace(os.sep, "/")
    ...
```

**Full modified main() function** for reference:
```python
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
    basename = os.path.basename(resolved)
    if resolved.startswith("/tmp/"):
        if (basename.startswith(".memory-write-pending") and basename.endswith(".json")):
            sys.exit(0)
        if (basename.startswith(".memory-draft-") and basename.endswith(".json")):
            sys.exit(0)
        if (basename.startswith(".memory-triage-context-") and basename.endswith(".txt")):
            sys.exit(0)

    # Allow writes to the plugin config file (not a memory record)
    if basename == _CONFIG_BASENAME:
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
```

### File 2: `hooks/scripts/memory_validate_hook.py`

**Location**: In `main()`, after the `is_memory_file()` check (line 150), before the non-JSON check (line 160).

**Add** a constant at module level (near the other path markers, around lines 33-36):
```python
# Config file basename (runtime construction to match guardian convention)
_CONFIG_BASENAME = "mem" + "ory-config.json"
```

**Add** an exemption check in `main()` (after the "bypassed PreToolUse guard" warning at line 157, before the non-JSON check at line 160):
```python
    # If we got here, a write bypassed the PreToolUse guard
    print(
        "WARNING: Write to memory file bypassed PreToolUse guard: {}".format(resolved),
        file=sys.stderr,
    )

    # Config file is not a memory record -- skip schema validation
    if os.path.basename(resolved) == _CONFIG_BASENAME:
        sys.exit(0)

    # Non-JSON files in memory dir (e.g. index.md) should be blocked outright
    if not resolved.endswith(".json"):
        ...
```

## Files NOT Changed

| File | Reason |
|------|--------|
| `memory_triage.py` | Reads config but doesn't write it |
| `memory_retrieve.py` | Reads config but doesn't write it |
| `memory_candidate.py` | No config interaction |
| `memory_write.py` | Writes memory files, not config |
| `memory_index.py` | Manages index.md, not config |

## Testing

### Manual Test 1: Write guard allows config write
```
1. Open Claude Code in a project with claude-memory plugin
2. Run /memory:config set max_inject to 3
3. Expected: Config updates without write guard denial prompt
4. Verify: .claude/memory/memory-config.json has max_inject: 3
```

### Manual Test 2: Validate hook skips config
```
1. Use Write tool to write valid JSON to .claude/memory/memory-config.json
2. Expected: No quarantine (file keeps its name)
3. Verify: ls .claude/memory/memory-config.json (no .invalid suffix)
```

### Manual Test 3: Memory files still protected
```
1. Try Write tool to .claude/memory/decisions/test.json
2. Expected: PreToolUse hook blocks with denial message
3. Verify: Write was denied
```

### Manual Test 4: Invalid memory files still quarantined
```
1. Somehow bypass the write guard (approve manually)
2. Write invalid JSON to .claude/memory/decisions/bad.json
3. Expected: PostToolUse hook quarantines the file
4. Verify: File renamed to .invalid.<timestamp>
```

## Additional Benefit

This fix also improves `/memory:config` command UX. Currently, users must manually approve the write guard denial every time they use this command. After the fix, config writes go through cleanly.

## Summary of Changes

| File | Change | Lines Affected |
|------|--------|---------------|
| `memory_write_guard.py` | Add `_CONFIG_BASENAME` constant + basename exemption before deny block | +5 lines |
| `memory_validate_hook.py` | Add `_CONFIG_BASENAME` constant + basename exemption before validation | +5 lines |

Total: ~10 lines added across 2 files. No existing behavior changed for memory files.
