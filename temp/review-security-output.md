# Security Review: Staging Path Fix

**Reviewer**: reviewer-security
**Date**: 2026-02-20
**Scope**: Change in `commands/memory-save.md` lines 39-40, moving temp file path from `/tmp/.memory-write-pending.json` to `.claude/memory/.staging/.memory-write-pending.json`
**External inputs**: Gemini CLI code review (codex CLI unavailable due to rate limit)
**Vibe check**: Performed -- confirmed analysis is on-target and appropriately scoped

---

## Verdict: PASS -- Safe to Merge

The change introduces **no new security vulnerabilities** and is **strictly a security improvement**. Moving from a world-writable directory (`/tmp/`) to a project-local directory (`.claude/memory/.staging/`) eliminates an entire class of attacks (symlink races in shared directories, cross-user file manipulation).

---

## 1. Path Validation Trace

### Question: Will `_read_input()` accept `.claude/memory/.staging/.memory-write-pending.json`?

**Answer: Yes.** Exact trace through `memory_write.py:1165-1205`:

1. `args.input` = `.claude/memory/.staging/.memory-write-pending.json` (relative path from CLI `--input`)
2. Line 1172: `resolved = os.path.realpath(input_path)` resolves to absolute, e.g. `/home/user/project/.claude/memory/.staging/.memory-write-pending.json`
3. Line 1173: `".." in input_path` evaluates to `False` (no `..` in the relative path) -- passes
4. Line 1181: `"/.claude/memory/.staging/" in resolved` evaluates to `True` (substring present in resolved absolute path) -- passes
5. Line 1191: `open(resolved, "r")` reads the file successfully
6. Line 1192: `json.load(f)` returns parsed JSON dict

**Result**: The path is accepted. The fix is compatible with the existing validation logic.

### Write Guard Compatibility

The write guard (`memory_write_guard.py` lines 53-58) also allows staging writes via the same substring pattern:
```python
staging_segment = "/.claude/memory/.staging/"
if staging_segment in normalized:
    sys.exit(0)  # allow
```

The LLM's Write tool call to `.claude/memory/.staging/.memory-write-pending.json` will be allowed by the guard, and the subsequent `_read_input()` call will accept it. The full pipeline is consistent.

---

## 2. Path Traversal Analysis

### Can the new path be exploited for path traversal?

**No new path traversal vectors are introduced by this change.**

- The path `.claude/memory/.staging/.memory-write-pending.json` is a fixed template in the command doc -- the LLM fills in only the JSON content, not the path itself.
- The `..` check (line 1173) prevents literal traversal components in the input argument.
- `os.path.realpath()` resolves symlinks before the substring check, so `./a/../b` style tricks are neutralized.
- `_check_path_containment()` (line 1216-1226) separately validates the `--target` output path using `Path.relative_to()`, which is a strict containment check.

### Pre-existing concern (not introduced by this change)

The `_read_input()` substring check (`"/.claude/memory/.staging/" in resolved`) is theoretically bypassable: an attacker who creates a directory structure like `/tmp/evil/.claude/memory/.staging/payload.json` would have a resolved path that contains the substring and passes validation.

**Practical risk assessment: LOW**. Exploiting this requires:
1. The attacker to create that specific nested directory structure on the filesystem
2. The LLM agent to be tricked into passing that crafted path as `--input` instead of the fixed template path
3. The planted file to contain valid JSON that passes full Pydantic schema validation
4. The move from `/tmp/` to `.staging/` actually *reduces* exploitability because the staging directory is project-local (not world-writable)

**Recommended future improvement**: Replace the substring check with `Path(resolved).is_relative_to(memory_root / ".staging")` to match the strict containment check already used for `--target` paths in `_check_path_containment()`. This is not a blocker for the current change.

---

## 3. Race Conditions

### Can concurrent `/memory:save` calls race on `.memory-write-pending.json`?

**Risk: LOW (acceptable).**

The filename `.memory-write-pending.json` is deterministic (not PID-qualified like the auto-capture flow's `draft-<category>-<pid>.json` pattern in SKILL.md line 99). If two concurrent sessions both invoke `/memory:save` in the same project:

1. Both write to `.claude/memory/.staging/.memory-write-pending.json`
2. One write overwrites the other
3. `memory_write.py` reads whichever version exists at read time
4. `_cleanup_input()` deletes the file, and the second invocation gets `FileNotFoundError`

**Mitigating factors**:
- Claude Code runs tool calls sequentially within a single session
- `/memory:save` is a manual user-initiated command (low frequency, not auto-triggered)
- Cross-session concurrency on the same project is a known general limitation of the plugin (the `_flock_index` lock class exists precisely for index mutations; temp file naming is a separate concern)
- The auto-capture flow already handles this correctly with PID-qualified filenames

**If this becomes a concern**: Add PID or UUID qualification to the filename (e.g., `.memory-write-pending-<pid>.json`). Not a blocker for this change.

---

## 4. Symlink Attacks

### Could `.staging/` or the pending file be symlinked to write elsewhere?

**Pre-existing concern, not worsened by this change. Change is actually an improvement.**

Analysis of `_read_input()` symlink handling:

- `os.path.realpath()` resolves symlinks, so the substring check operates on the ultimate target path
- **Symlink on the file itself**: If `.memory-write-pending.json` is a symlink to `/etc/passwd`, `realpath()` resolves to `/etc/passwd`, which does NOT contain `/.claude/memory/.staging/` -- **correctly rejected**
- **Symlink on `.staging/` directory**: If `.staging/` is a symlink pointing to `/tmp/evil/.claude/memory/.staging/`, the resolved path would contain the substring and **pass** -- but creating such a symlink requires write access to the project's `.claude/memory/` directory, which is already a trusted boundary

**Contrast with triage script**: `memory_triage.py` (lines 768-772) uses `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW` flags to prevent symlink attacks when writing context files. `_read_input()` does not use `O_NOFOLLOW` for reads.

**Key improvement of this change**: The old `/tmp/` path was in a world-writable directory where any local user could create symlinks. The new `.staging/` path is in a project-local directory where only the project owner (and the LLM agent) can create files. This significantly reduces symlink attack surface.

**Recommended future improvement**: Add `os.path.islink()` check before `open()` in `_read_input()`, consistent with the triage script's defensive approach. Not a blocker.

---

## 5. Injection Surface

### Does the new path pattern introduce any new injection vectors?

**No.**

- The path is a fixed template string in `memory-save.md` -- not user-controlled
- The JSON content is validated by Pydantic schema (`validate_memory()` at line 638)
- Title sanitization (`auto_fix()` at line 623) strips control characters, delimiters (`" -> "`), and bracket sequences (`[SYSTEM]`)
- `record_status` is forced to `"active"` for creates (line 626), preventing status injection
- Immutable fields (`created_at`, `schema_version`, `category`, `id`) are preserved/overwritten as appropriate
- Category is validated against `CATEGORY_FOLDERS` allowlist (line 1336)

The only content that flows from user input into the system is the natural language description, which is structured into JSON by the LLM and then validated by Pydantic. This is unchanged by the path fix.

---

## 6. Additional Observations

### 6.1 Dead `/tmp/` allowlist in write guard

`memory_write_guard.py` lines 42-51 still allow `/tmp/.memory-write-pending*.json` writes. Since the `/memory:save` command no longer writes there, and the SKILL.md auto-capture flow already uses `.staging/`, this `/tmp/` allowlist is now dead code. It is harmless but could be cleaned up to reduce residual attack surface (a future attacker could potentially exploit the `/tmp/` allowlist to write files that pass the guard but fail `_read_input()` validation).

### 6.2 `_cleanup_input` uses original path, not resolved

`_cleanup_input(args.input)` (lines 1208-1213) calls `os.unlink(input_path)` on the original (potentially relative) path, not the resolved path. Analysis:
- If the input was a symlink, `unlink` removes the symlink itself (not the target) -- this is actually correct POSIX behavior
- If cwd changed between validation and cleanup, the wrong file could be deleted -- but cwd does not change during `memory_write.py` execution
- Since `_read_input()` validates the path before processing, and the script does not change directories, this is a minor pre-existing inconsistency, not a practical vulnerability

### 6.3 Docstring references `/tmp/`

Lines 10-15 of `memory_write.py` contain usage examples with `/tmp/.memory-write-pending.json`. These are documentation-only (module docstring) and do not affect runtime behavior, but should be updated for consistency with the actual validation logic.

### 6.4 TOCTOU between realpath and open

There is a time-of-check-to-time-of-use gap between `os.path.realpath()` (line 1172) and `open(resolved)` (line 1191). Between these calls, the filesystem could theoretically change (e.g., a symlink could be swapped). However:
- This requires an attacker with concurrent filesystem write access to the `.staging/` directory
- The window is microseconds (just the Python `if` checks between lines 1173-1189)
- Moving from `/tmp/` to `.staging/` actually *reduces* this risk because `/tmp/` is world-writable while `.staging/` is project-local

---

## 7. Summary Table

| Check | Result | Notes |
|-------|--------|-------|
| Path validation accepts new path | PASS | Substring check matches `/.claude/memory/.staging/` in resolved path |
| Write guard allows staging writes | PASS | Same substring pattern at guard line 57 |
| No new path traversal vectors | PASS | Fixed template path, not user-controlled |
| No new race conditions | PASS (LOW risk) | Deterministic filename; sequential single-session execution |
| No new symlink vectors | PASS (IMPROVED) | Project-local dir vs world-writable `/tmp/` |
| No new injection surface | PASS | Content validation chain unchanged |
| Pre-existing findings | NOTED | Substring check weakness, missing `O_NOFOLLOW`, dead `/tmp/` allowlist, docstring staleness |

---

## 8. Test Coverage for `_read_input()` Path Validation

Existing tests in `tests/test_memory_write.py` use the `write_input_file()` helper (lines 47-53) which correctly creates staging paths. Tests in `tests/test_arch_fixes.py` also set up `.claude/memory/.staging/` directories for integration tests.

**However**: There are no dedicated unit tests for `_read_input()` itself -- no tests that verify:
- Rejection of paths outside `.staging/` (e.g., `/tmp/evil.json`)
- Rejection of paths with `..` components
- Rejection of crafted paths like `/tmp/evil/.claude/memory/.staging/payload.json`
- Handling of symlinked input files

**Recommendation**: Add targeted `_read_input()` unit tests in a future PR to lock down the security properties.

---

## 9. Cross-Reference: External Review (Gemini CLI)

Gemini CLI flagged the substring check as "Critical" severity. I concur that the substring pattern (`"/.claude/memory/.staging/" in resolved`) is weaker than the `Path.relative_to()` approach used for target paths. However, the severity rating is overstated **for this specific change** because:

1. The vulnerability is pre-existing -- it exists in the current code regardless of this PR
2. This change does not worsen it -- moving from `/tmp/` to `.staging/` reduces exploitability
3. Exploitation requires multiple preconditions (directory creation + LLM manipulation + schema validation bypass)
4. The `Path.relative_to()` fix is a valid improvement but should be tracked separately

**Codex CLI**: Unavailable (rate limited). Analysis proceeded without it.

---

## 10. Final Verdict

**APPROVED -- No security concerns with the change itself.**

The fix is a strict security improvement. Pre-existing weaknesses in `_read_input()` are documented above for follow-up but are not blockers for merging this two-line documentation fix.
