# Stop Hook Re-fire Fix — Implementation Log

## Summary
All 3 phases implemented. 1095/1095 tests pass. Both files compile cleanly.

## Phase 1: P0 Hotfix

### Step 1.1: Remove `.triage-handled` from cleanup patterns
- File: `hooks/scripts/memory_write.py` line 506
- Removed `.triage-handled` from `_STAGING_CLEANUP_PATTERNS`
- Added comment explaining the intentional exclusion
- Root cause RC-1 fixed: sentinel now survives `cleanup_staging()`

### Step 1.2: Increase FLAG_TTL_SECONDS
- File: `hooks/scripts/memory_triage.py` line 49
- Changed from `300` (5 min) to `1800` (30 min)
- Root cause RC-2 fixed: TTL now covers the 10-28 min save flow

### Step 1.3: Save-result guard (defense-in-depth)
- Added `_check_save_result_guard()` function
- Checks both cwd-local and /tmp/ staging paths for `last-save-result.json`
- Cross-references sentinel session_id for independent verification
- Fail-open on all error paths

### Step 1.4: Atomic lock for TOCTOU prevention
- Added `_acquire_triage_lock()` and `_release_triage_lock()`
- Uses `O_CREAT | O_EXCL | O_NOFOLLOW` for atomic creation
- Returns `(lock_path, status)` tuple with 3 states: ACQUIRED, HELD, ERROR
- **HELD = return 0** (yield to lock holder) — critical fix from clink review
- ERROR = proceed without lock (fail-open)
- 120s stale lock detection with retry-once
- Lock released in `finally` block

## Phase 2: RUNBOOK Threshold

### Step 2.1: RUNBOOK threshold 0.4 -> 0.5
- Reduces false positives from 1-primary + 1-booster SKILL.md contamination
- Root cause RC-4 partially fixed

### Step 2.2: Negative pattern filter
- Added `"negative"` key to RUNBOOK category patterns
- Patterns anchored to doc scaffolding only:
  - `^#+ Error Handling` (markdown headings)
  - `^[-*] If (a )?subagent fails` (list-item instructions)
  - `^#+ Retry/Fallback Logic/Strategy` (markdown headings)
- Verified: does NOT suppress real troubleshooting text like "On error, restart the worker"
- `score_text_category()` updated to skip lines matching negative patterns

## Phase 3: Session-Scoped Idempotency

### Step 3.1: Session-scoped sentinel
- `_sentinel_path()` returns `cwd/.claude/memory/.staging/.triage-handled`
- `read_sentinel()` reads JSON with O_NOFOLLOW, fail-open on any error
- `write_sentinel()` writes atomically via tmp+replace
- `check_sentinel_session()` compares session_id + state + TTL

### Step 3.2: Sentinel as JSON state file
- Format: `{"session_id": "...", "state": "pending|saving|saved|failed", "timestamp": ..., "pid": ...}`
- Blocking states: `{pending, saving, saved}` — `frozenset` for O(1) lookup
- Failed state allows re-triage

### Step 3.3: Sentinel survives cleanup
- Already done by Step 1.1 (removed from `_STAGING_CLEANUP_PATTERNS`)

### Step 3.4: TTL safety net
- `check_sentinel_session()` checks sentinel timestamp against `FLAG_TTL_SECONDS`
- Even same-session sentinels expire after 30 min (prevents indefinite suppression)
- Critical fix from clink review (Codex finding)

### _run_triage() flow (final)
1. Read stdin JSON
2. Extract fields (transcript_path, cwd)
3. Load config
4. Derive session_id from transcript_path
5. Check stop_hook_active flag (user re-stopping, backward compat)
6. Check session-scoped sentinel (same session + blocking state + within TTL = skip)
7. Check save-result guard (defense-in-depth)
8. Acquire atomic lock
   - HELD: return 0 (yield to lock holder)
   - ERROR: proceed without lock (fail-open)
   - ACQUIRED: continue
9. Double-check sentinel under lock (check-lock-check pattern)
10. Read/parse transcript
11. Score all categories
12. If results: write sentinel("pending"), write context files, output block
13. finally: release lock if acquired

## Clink Review Fixes
1. Lock HELD -> return 0 (was: proceed anyway, both codex+gemini flagged)
2. TTL safety net in check_sentinel_session (codex: indefinite suppression)
3. Tightened RUNBOOK negative patterns (codex: too aggressive)
4. Updated memory_write.py comment (gemini: inaccurate TTL reference)

## Test Results
- All 1095 tests pass
- Updated 4 existing tests to match new behavior:
  - `test_sentinel_allows_stop_when_fresh`: now writes JSON sentinel
  - `test_sentinel_created_when_blocking`: checks JSON content
  - `test_sentinel_uses_flag_ttl_constant`: asserts 1800, uses JSON sentinel
  - `test_other_categories_unaffected`: expects RUNBOOK=0.5

## Files Modified
| File | Changes |
|------|---------|
| `hooks/scripts/memory_write.py` | Remove `.triage-handled` from cleanup patterns, update comment |
| `hooks/scripts/memory_triage.py` | FLAG_TTL, RUNBOOK threshold, negative patterns, session sentinel, atomic lock, save-result guard, _run_triage rewrite |
| `tests/test_memory_triage.py` | Update 4 existing tests for new behavior |
