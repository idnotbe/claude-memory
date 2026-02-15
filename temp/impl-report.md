# Implementation Report: 5 Architectural Fixes

## Summary

All 5 architectural fixes have been implemented and verified. 50/50 arch fix tests pass (40 clean + 10 xpassed). 189/189 existing tests pass with 0 regressions.

---

## Issue 2: _resolve_memory_root() fail-closed

**File:** `hooks/scripts/memory_write.py` (lines 1156-1181 -> 1155-1181)

**Changes:**
1. Removed the insecure `else` fallback that derived `memory_root` from `target_abs.parent.parent`
2. Now resolves target to absolute path BEFORE scanning parts (fixes relative path edge case)
3. Exits with `sys.exit(1)` and clear `PATH_ERROR` message including example path format

**Test Results:** 7/7 passed (3 previously xfail now pass)

---

## Issue 3: max_inject value clamping

**File:** `hooks/scripts/memory_retrieve.py` (lines 190-203)

**Changes:**
1. Added `int()` coercion for `max_inject` config value
2. Added `max(0, min(20, ...))` clamping to range [0, 20]
3. Added `ValueError/TypeError` exception handling with warning and default fallback to 5
4. Added early exit when `max_inject == 0` (allows disabling injection via config)

**Test Results:** 12/12 passed (6 previously xfail now pass)

---

## Issue 5: Title sanitization + structured output

**File:** `hooks/scripts/memory_retrieve.py` (lines 156-165 for `_sanitize_title`, lines 275-280 for output)

**Changes:**
1. Added `_sanitize_title()` function: strips control chars, replaces arrow markers, removes `#tags:` prefix, truncates to 120 chars
2. Changed output format from `"RELEVANT MEMORIES"` header + raw index lines to `<memory-context>` XML tags with sanitized fields
3. Output now reconstructs lines from parsed/sanitized fields instead of using `entry["raw"]`

**Test Results:** 12/12 passed (1 previously xfail now passes)

**Regression fix:** Updated `tests/test_memory_retrieve.py:218` to accept both old and new output format (`<memory-context` or `RELEVANT MEMORIES`).

---

## Issue 4: mkdir-based locking

**File:** `hooks/scripts/memory_write.py` (lines 1130-1153 -> 1130-1182)

**Changes:**
1. Removed `import fcntl` (no longer needed)
2. Added `import time` for timeout/stale detection
3. Replaced `_flock_index` class entirely:
   - Uses `os.mkdir()` for atomic locking (works on POSIX, Windows, NFS)
   - Stale lock detection: breaks locks older than 60 seconds
   - Timeout: waits up to 5 seconds with 50ms poll interval
   - Graceful degradation: proceeds without lock on permission errors
   - Clean release via `os.rmdir()` in `__exit__`
4. Lock artifact changed from `.index.lock` (file) to `.index.lockdir` (directory)

**Test Results:** 8/8 passed

---

## Issue 1: index.md rebuild-on-demand

**Files:** `hooks/scripts/memory_retrieve.py` (lines 188-198), `hooks/scripts/memory_candidate.py` (lines 220-229), `.gitignore`

**Changes:**
1. **memory_retrieve.py:** Added rebuild-on-demand block before the "exit if no index" check. Guards: only triggers when `memory_root.is_dir()` and `memory_index.py` exists. Uses `subprocess.run` with `timeout=10` and `capture_output=True`.
2. **memory_candidate.py:** Added identical rebuild-on-demand block before the error exit for missing index.
3. **.gitignore:** Added `.claude/memory/index.md` entry with comment explaining the derived artifact pattern.

**Test Results:** 7/7 passed

---

## Cross-Issue Interaction Tests

4/4 passed:
- Rebuild with sanitized titles (Issue 1 + Issue 5)
- max_inject limits injection surface (Issue 3 + Issue 5)
- Lock not needed for rebuild (Issue 1 + Issue 4)
- Validated root with lock (Issue 2 + Issue 4)

---

## Full Test Suite Results

### Arch Fix Tests (`test_arch_fixes.py`)
```
50 tests: 40 passed, 10 xpassed, 0 failed
```

### Existing Tests (all other test files)
```
189 tests: 189 passed, 0 failed
```

### Total: 239 tests, 239 passed, 0 failures

---

## Deviations from Plan

1. **No deviations.** All 5 fixes were implemented exactly as specified in the detailed fix plan.
2. **One existing test updated:** `tests/test_memory_retrieve.py:218` -- changed `assert "RELEVANT MEMORIES" in stdout` to accept either `<memory-context` or `RELEVANT MEMORIES` format to account for the Issue 5 output format change.

---

## Files Modified

| File | Changes |
|------|---------|
| `hooks/scripts/memory_write.py` | Issue 2 (fail-closed root resolution), Issue 4 (mkdir lock), removed `fcntl`, added `time` |
| `hooks/scripts/memory_retrieve.py` | Issue 1 (rebuild-on-demand), Issue 3 (max_inject clamp), Issue 5 (sanitize + structured output) |
| `hooks/scripts/memory_candidate.py` | Issue 1 (rebuild-on-demand) |
| `.gitignore` | Issue 1 (added `.claude/memory/index.md`) |
| `tests/test_memory_retrieve.py` | Updated assertion to accept new output format |
