# V1 Security Review: Config Exemption Fix

**Reviewer:** v1-security
**Date:** 2026-02-16
**Rating:** PASS_WITH_NOTES

## Summary

The config exemption implementation is fundamentally sound and follows existing conventions correctly. One medium-severity finding (basename collision in subdirectories) warrants a targeted fix. All other checklist items pass cleanly.

---

## Checklist Findings

### 1. Injection Vector Analysis: PASS

**Finding:** Exempting `memory-config.json` does NOT create new prompt injection paths.

- The config file is NOT injected into LLM context by `memory_retrieve.py` (retrieval reads memory JSON files from the index, not config).
- Config `categories.*.description` values ARE used in triage context files and retrieval output, but this attack surface existed prior to this change -- config was already editable via `/memory:config` command.
- The exemption removes a UX friction point (the write guard approval prompt) but does not create any new injection vector.
- `max_inject` is clamped to `[0, 20]` by `memory_retrieve.py` regardless of config values.

**Verdict:** No new attack surface introduced.

### 2. Path Traversal: PASS

**Finding:** Path traversal is mitigated by `os.path.realpath()`.

- Both hooks resolve the input path with `os.path.realpath(os.path.expanduser(file_path))` before any checks.
- `realpath()` resolves `..` components, so `../memory-config.json` would resolve to its canonical absolute path.
- The basename check operates on the resolved path, not the raw input.
- A path like `.claude/memory/decisions/../memory-config.json` resolves to `.claude/memory/memory-config.json`, and basename would correctly be `memory-config.json`.

**Verdict:** Path traversal attacks are neutralized by `realpath()`.

### 3. Basename Collision: FAIL (Medium Severity)

**Finding:** A file named `memory-config.json` in any subdirectory bypasses both guards.

**Attack path:**
1. Write to `.claude/memory/decisions/memory-config.json`
2. `memory_write_guard.py` flow:
   - `resolved = realpath(file_path)` -> `/home/user/project/.claude/memory/decisions/memory-config.json`
   - `basename = os.path.basename(resolved)` -> `memory-config.json`
   - `if basename == _CONFIG_BASENAME: sys.exit(0)` -> **ALLOWED** (line 54)
   - Memory directory deny check at line 58 **never reached**
3. `memory_validate_hook.py` flow:
   - Same basename check at line 163 -> `sys.exit(0)` -> **validation skipped**
4. Net effect: File written to a category subfolder without write guard or schema validation.

**Impact assessment:**
- The file would bypass both PreToolUse guard and PostToolUse validation.
- `memory_index.py` `scan_memories()` scans `*.json` in category subfolders via `folder_path.glob("*.json")` (line 58). A `memory-config.json` in `decisions/` would be picked up during `--rebuild`.
- If indexed, the file's `title` field (if present) would be injected into context by `memory_retrieve.py`, enabling prompt injection.
- **Practical exploitability:** Low-medium. Requires an agent to specifically craft a Write tool call to this path, and the hook must not catch it. In practice, the LLM would need to be manipulated into writing to this specific filename in a subdirectory.

**Recommended fix:** Add a directory-depth check alongside the basename check. The config file should only be exempted when it is in the memory root directory, not in a category subfolder. For example:

```python
# In memory_write_guard.py (before line 57's normalized check):
if basename == _CONFIG_BASENAME:
    normalized_for_check = resolved.replace(os.sep, "/")
    # Only allow if the file is directly in a .claude/memory/ root, not a subfolder
    # i.e., the segment before the basename should end with /.claude/memory/
    parent_dir = normalized_for_check.rsplit("/", 1)[0] + "/"
    if parent_dir.endswith(MEMORY_DIR_SEGMENT) or parent_dir.endswith(MEMORY_DIR_TAIL + "/"):
        sys.exit(0)
```

Or more simply, verify the resolved path does NOT contain a category subfolder between the memory dir segment and the filename:

```python
# Simpler approach: only exempt if basename matches AND file is not deeper than memory root
if basename == _CONFIG_BASENAME:
    normalized_pre = resolved.replace(os.sep, "/")
    idx = normalized_pre.find("/.claude/memory/")
    if idx >= 0:
        after_mem = normalized_pre[idx + len("/.claude/memory/"):]
        # Config should be directly in memory root (no further '/' in remainder except the basename itself)
        if "/" not in after_mem:
            sys.exit(0)
    else:
        # Not even in a memory directory -- allow (would be allowed anyway)
        sys.exit(0)
```

Same fix needed in `memory_validate_hook.py`.

### 4. Guardian Convention: PASS

**Finding:** Runtime string construction correctly follows the convention.

- `_CONFIG_BASENAME = "mem" + "ory-config.json"` matches the pattern of `_DOT_CLAUDE = ".clau" + "de"` and `_MEMORY = "mem" + "ory"`.
- The string is split at the same boundary (`mem` + `ory`) as the existing `_MEMORY` constant.
- This prevents static pattern matching from detecting the literal string `memory-config.json` in the source.

**Verdict:** Convention correctly followed.

### 5. Symlink Attacks: PASS

**Finding:** Symlink attacks are mitigated by `os.path.realpath()`.

Analysis of symlink scenarios:

| Scenario | Result | Safe? |
|----------|--------|-------|
| Symlink FROM `memory-config.json` TO a memory file | `realpath()` resolves to target; basename becomes the target's filename (not `memory-config.json`); exemption does NOT fire | Yes |
| Symlink FROM a memory file TO `memory-config.json` | `realpath()` resolves to actual config file; writes to the real config file; equivalent to direct config write | Yes |
| Symlink FROM outside memory dir TO inside | `realpath()` resolves to inside; normal deny check applies | Yes |

**Verdict:** `os.path.realpath()` resolves symlinks before any path checks, neutralizing symlink-based attacks.

### 6. Race Conditions (TOCTOU): PASS (pre-existing)

**Finding:** No new TOCTOU issues introduced by this change.

- A standard TOCTOU gap exists between PreToolUse check and actual write (pre-existing architectural limitation in all Claude Code hooks).
- The config exemption does not widen this gap or create new race conditions.
- An attacker exploiting TOCTOU would need code execution on the machine already, making the hook bypass moot.

**Verdict:** Pre-existing limitation, not introduced or worsened by this change.

### 7. Exit Code Semantics: PASS

**Finding:** `sys.exit(0)` correctly signals "allow" in both hook contexts.

- **PreToolUse (write_guard):** `sys.exit(0)` with no JSON output = "hook ran successfully, no opinion" = allow. This is the same pattern used for `/tmp/` staging files (lines 47, 49, 51) and non-memory paths (line 74).
- **PostToolUse (validate_hook):** `sys.exit(0)` with no JSON output = "no action needed." Since PostToolUse cannot prevent writes (already happened), this correctly means "don't quarantine, don't warn."
- Both are consistent with existing exit patterns in the same files.

**Verdict:** Exit code semantics are correct and consistent.

---

## Test Coverage Assessment

The 7 new tests provide good coverage:

| Test | Covers |
|------|--------|
| `test_allows_config_file_write` | Happy path: config allowed through write guard |
| `test_blocks_memory_file_but_allows_config` | Selectivity: config allowed, memory files still blocked |
| `test_config_file_in_different_project_paths` | Path variation across OS patterns |
| `test_similar_config_filenames_still_blocked` | Exact-match only (6 similar names) |
| `test_config_file_skips_validation` | Config skips PostToolUse validation |
| `test_config_file_not_quarantined` | Real filesystem: config not renamed |
| `test_memory_files_still_validated` | Non-config files still quarantined |

**Missing test:** No test for `memory-config.json` in a subdirectory (the basename collision finding). A test like the following would expose the vulnerability:

```python
def test_config_file_in_subdirectory_still_blocked(self):
    """memory-config.json inside a category subfolder should still be blocked."""
    hook_input = {
        "tool_input": {
            "file_path": "/home/user/project/.claude/memory/decisions/memory-config.json",
        }
    }
    stdout, rc = run_guard(hook_input)
    assert rc == 0
    if stdout.strip():
        output = json.loads(stdout)
        hook_output = output.get("hookSpecificOutput", {})
        assert hook_output.get("permissionDecision") == "deny", (
            "memory-config.json in subdirectory should be blocked"
        )
```

---

## Overall Assessment

### Rating: PASS_WITH_NOTES

The implementation is well-designed, follows conventions correctly, and the test suite is thorough for the intended behavior. The one actionable finding is the **basename collision in subdirectories** (checklist item 3), which allows a file named `memory-config.json` in any category subfolder to bypass both guards entirely. While practical exploitability is limited (requires LLM manipulation to write to that specific filename), the fix is straightforward: add a check that the config file is directly in the memory root, not in a subfolder.

### Recommended Changes

1. **[Medium]** Add directory-depth validation to the basename exemption in both `memory_write_guard.py` and `memory_validate_hook.py`. The config file should only be exempted when it resides directly in the `.claude/memory/` root, not in `decisions/`, `sessions/`, or any other subfolder.

2. **[Low]** Add a test case for `memory-config.json` in a subdirectory to prevent regression if the depth check is implemented.
