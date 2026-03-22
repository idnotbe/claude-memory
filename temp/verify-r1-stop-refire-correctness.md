# Verification Round 1 -- Stop Hook Re-fire Fix: Correctness Review

**Reviewer:** V-R1 (Correctness)
**Date:** 2026-03-22
**Files reviewed:**
- `hooks/scripts/memory_triage.py` (sentinel, lock, save-result guard, `_run_triage()` rewrite)
- `hooks/scripts/memory_write.py` (`_STAGING_CLEANUP_PATTERNS` change)
- `tests/test_memory_triage.py` (updated + new sentinel/lock tests)
- `skills/memory-management/SKILL.md` (save pipeline orchestration)
- `hooks/scripts/memory_logger.py` (`get_session_id()`)

**External opinions:** Codex (codereviewer), Gemini 3.1 Pro (codereviewer)

---

## Verdict: 2 MEDIUM bugs, 3 LOW observations, no blockers

The core sentinel logic is correct. The fix successfully addresses all 4 root causes (RC-1 through RC-4). The remaining issues are edge-case hardening items, not fundamental design flaws.

---

## MEDIUM Issues

### M1: TTL timestamp `except` fails closed (line 691-692)

**Location:** `check_sentinel_session()`, lines 687-692

```python
try:
    age = time.time() - float(sentinel_ts)
    if age >= FLAG_TTL_SECONDS:
        return False  # Expired, allow re-triage
except (TypeError, ValueError):
    pass  # Invalid timestamp, treat as no TTL constraint
```

**Problem:** If `sentinel_ts` is corrupted (e.g., `"NaN"`, `null`, or a string), `float()` raises `ValueError`/`TypeError`. The `except` block does `pass`, which falls through to the blocking check at line 695. This means a same-session sentinel with a corrupted timestamp will suppress triage **indefinitely** -- the TTL safety net is completely disabled.

**Expected behavior (per docstring):** "Fail-open: returns False on any error."

**Fix:** Change `pass` to `return False`.

**Severity:** MEDIUM. This is a correctness violation of the function's own fail-open contract. If the save pipeline writes a malformed timestamp and then crashes, triage is permanently suppressed for that session until the process exits.

**Consensus:** Both Codex and Gemini independently flagged this.

---

### M2: Sentinel state never advances beyond "pending" in production (line 1418)

**Location:** `_run_triage()` line 1418; SKILL.md Phase 3

**Problem:** The only production call to `write_sentinel()` is at line 1418, which always writes `state="pending"`. No code path in the save pipeline (SKILL.md orchestration, memory_write.py, or any other script) advances the sentinel to `"saving"`, `"saved"`, or `"failed"`.

**Impact:** The state machine is effectively binary: `pending` (blocks) vs. no sentinel (allows). The intended retry-aware behavior from Phase 3 Step 3.4 ("Only set state='saved' AFTER successful commit; set state='failed' if save fails; allow re-triage on failed") is **not implemented**. If the save pipeline fails, the sentinel stays `"pending"` until the TTL expires (30 min), and there is no way to re-trigger triage on failure within that window.

**Fix:** Add sentinel state advancement to the save pipeline:
- SKILL.md Phase 3 Step 2 (cleanup-staging): advance sentinel to `"saved"` after successful save
- SKILL.md Phase 3 Step 3 (error handling): advance sentinel to `"failed"` on pipeline failure
- Either add a CLI action to memory_write.py (e.g., `--action update-sentinel`) or instruct the orchestrating agent to call `write_sentinel()` via a small Python one-liner

**Severity:** MEDIUM. The re-fire prevention still works (pending blocks re-fires within TTL), but the fail-recovery design is incomplete. A failed save permanently suppresses retry for up to 30 minutes.

**Consensus:** Codex independently identified this ("I did not find a production writer advancing .triage-handled to saving, saved, or failed").

---

## LOW Observations

### L1: TOCTOU race in stale lock recovery (lines 784-795)

**Location:** `_acquire_triage_lock()`, stale lock detection branch

**Scenario:**
1. Process A and Process B both `stat()` the lock file, both see `age > 120s`
2. Process A calls `os.unlink()` (succeeds)
3. Process C creates a fresh lock (succeeds)
4. Process B calls `os.unlink()` -- **deletes Process C's fresh lock**
5. Process B creates its own lock
6. Both B and C now believe they hold the lock

**Impact:** LOW in practice. The sentinel double-check pattern at line 1362-1364 catches this: even if two processes pass the lock, only the first writer's sentinel takes effect, and the second process will see the sentinel and exit. Additionally, both processes running triage concurrently produces duplicate output but no data corruption (triage is read-only scoring).

**Mitigation already in place:** Sentinel re-check under lock (line 1362-1364).

**Potential fix (if desired):** Replace file-based lock with `fcntl.flock()` which eliminates stale-lock concepts entirely. Or check lock file inode before releasing (only unlink if inode matches what was created).

**Consensus:** Both Codex and Gemini flagged this. Gemini recommended `fcntl.flock`; Codex recommended lock-instance identity.

---

### L2: Empty `session_id` bypasses all session-scoped guards (lines 1343, 1347)

**Location:** `_run_triage()` lines 1343-1348

```python
if session_id and check_sentinel_session(cwd, session_id):
    return 0
if session_id and _check_save_result_guard(cwd, session_id):
    return 0
```

**Scenario:** If `get_session_id()` returns `""` (empty transcript path, or unexpected failure), all three session-scoped guards (sentinel, save-result, lock session matching) are bypassed. The only remaining guard is `check_stop_flag()` which is consumed-on-read.

**Impact:** LOW. In practice, `transcript_path` is always provided by Claude Code's hook infrastructure. An empty transcript_path causes `_run_triage()` to exit at line 1367-1368 (`not transcript_path or not os.path.isfile(transcript_path)`), so the empty-session-id path never reaches scoring. The guards are bypassed, but the function exits before they would matter.

**Gemini's concern** (inescapable blocking loop) is theoretically valid but practically unreachable: if transcript_path is empty, triage never fires, so no blocking occurs.

**Potential fix (defense-in-depth):** Generate a fallback session_id from `hash(cwd + str(os.getpid()))` when transcript_path is missing.

---

### L3: `_check_save_result_guard()` is not truly independent (lines 733-739)

**Location:** `_check_save_result_guard()`, lines 732-739

**Problem:** The guard requires BOTH a fresh `last-save-result.json` AND a matching sentinel to return True (skip). If the sentinel is corrupted/missing but the save-result file proves a save happened, the guard returns False (proceed). This makes it a reinforcing guard (confirms sentinel) rather than an independent fallback.

**Impact:** LOW. The sentinel is the primary guard and is robust (atomic writes, O_NOFOLLOW). The save-result guard provides additional confidence but cannot substitute for a missing sentinel.

**Potential fix:** Add `session_id` to `last-save-result.json` schema (via `write-save-result-direct` action) so the guard can validate independently.

---

### L4: FLAG_TTL_SECONDS=1800 has thin margin (2 min worst case)

**Location:** Line 65

**Analysis:** Save flow documented at 10-28 minutes. TTL of 30 minutes leaves 2-minute margin in worst case. If API latency, retries, or agent stalls push the flow beyond 30 minutes, the sentinel expires and a concurrent stop could trigger duplicate triage.

**Impact:** LOW. The sentinel expiring is a safety-net activation, not a bug. The worst outcome is a duplicate triage (which produces duplicate output noise but no data corruption, since `memory_write.py` has its own OCC flock protections).

**Trade-off:** Increasing TTL (e.g., to 3600) reduces duplicate risk but increases the stuck-triage window if the save pipeline truly hangs. Current 1800 is a reasonable balance.

---

## Correct Items (Confirmed)

| Item | Status | Notes |
|------|--------|-------|
| Sentinel blocks same-session re-fires | CORRECT | `check_sentinel_session()` returns True for same session + blocking state + within TTL |
| New session bypasses sentinel | CORRECT | Line 682: `sentinel_session != current_session_id` returns False |
| Failed state allows re-triage | CORRECT | Line 698-699: state not in `_SENTINEL_BLOCK_STATES` returns False |
| TTL safety net (when timestamp is valid) | CORRECT | Line 689: `age >= FLAG_TTL_SECONDS` returns False |
| `check_stop_flag()` backward compat | CORRECT | Still called at line 1339, still consumes flag on check |
| `set_stop_flag()` called when blocking | CORRECT | Line 1415 |
| Lock HELD yields (return 0) | CORRECT | Line 1355-1356 |
| Double-check sentinel under lock | CORRECT | Line 1362-1364 |
| `finally` releases lock | CORRECT | Python guarantees `finally` on `return` inside `try` |
| `.triage-handled` removed from cleanup | CORRECT | `_STAGING_CLEANUP_PATTERNS` no longer includes it |
| RUNBOOK threshold raised to 0.5 | CORRECT | Reduces SKILL.md contamination false positives |
| Negative patterns for RUNBOOK | CORRECT | Anchored to doc scaffolding, does not suppress real troubleshooting |
| Atomic sentinel writes (tmp+replace+O_NOFOLLOW) | CORRECT | `write_sentinel()` uses proper atomic pattern |

---

## Recommended Priority for Fixes

1. **M1** (TTL except fails closed): One-line fix, high confidence, should be done before merge
2. **M2** (state never advances): Design gap, requires SKILL.md + possible script changes. Can be a follow-up if sentinel + TTL is considered sufficient for now
3. **L1-L4**: Hardening items for a future pass

---

## Test Coverage Assessment

- Sentinel same-session blocking: COVERED (test_sentinel_allows_stop_when_fresh)
- Sentinel different-session bypass: COVERED (test_sentinel_ignored_when_different_session)
- Sentinel created on block: COVERED (test_sentinel_created_when_blocking)
- Sentinel not created on allow: COVERED (test_sentinel_not_created_when_allowing)
- Sequential idempotency: COVERED (test_sentinel_idempotency_sequential_calls)
- FLAG_TTL constant value: COVERED (test_sentinel_uses_flag_ttl_constant)
- Sentinel survives cleanup: COVERED (test_sentinel_survives_cleanup)
- Save-result guard: COVERED (test_save_result_guard_*)
- Lock basic tests: COVERED (test_atomic_lock_*)
- **NOT COVERED:** Corrupted sentinel timestamp (M1 scenario)
- **NOT COVERED:** Concurrent lock acquisition race (L1 scenario)
- **NOT COVERED:** Empty session_id path (L2 scenario)
- **NOT COVERED:** State advancement beyond "pending" (M2 -- no production code to test)
