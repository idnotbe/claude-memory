# Verification Round 1: Operational Review — Stop Hook Re-fire Fix

**Reviewer:** Opus (operational lens)
**External reviewers:** Codex (codereviewer), Gemini (codereviewer)
**Files reviewed:** `hooks/scripts/memory_triage.py`, `hooks/scripts/memory_write.py`, `hooks/scripts/memory_write_guard.py`, `hooks/scripts/memory_staging_guard.py`, `hooks/scripts/memory_staging_utils.py`, `tests/test_memory_triage.py`

---

## Verdict: PASS with 1 HIGH, 2 MEDIUM, 1 LOW findings

The implementation is operationally sound with consistent fail-open discipline, correct atomicity primitives, and negligible performance overhead (~0.4ms combined for all new guard paths). One high-severity finding requires attention before merge.

---

## HIGH: Cross-Session Stop Flag TTL Regression

**Location:** `memory_triage.py:65,555-569`
**Source:** Gemini (confirmed by Opus)

`check_stop_flag()` uses `FLAG_TTL_SECONDS` (1800s / 30 min) to decide if the legacy `.stop_hook_active` flag is "fresh." This flag is **per-project, not per-session** — it has no `session_id`. The TTL was raised from 300s to 1800s for the sentinel's needs, but the stop flag inherited this change.

**Scenario:**
1. Session A blocks stop → `set_stop_flag()` creates `.stop_hook_active`
2. User abandons Session A (doesn't re-stop)
3. User starts Session B on same project, stops after 15 minutes
4. `check_stop_flag()` sees a 15-min-old flag (< 1800s), consumes it, returns `True`
5. Session B's triage is silently skipped — **memories lost**

The flag is consumed (unlinked) on read, so this is a one-shot skip, not permanent. But it widens the cross-session bleed window from 5 minutes to 30 minutes.

**Fix:** Decouple the stop flag TTL from `FLAG_TTL_SECONDS`. Either:
- Hardcode `check_stop_flag()` to use a separate constant (e.g., `STOP_FLAG_TTL = 300`)
- Or embed `session_id` in the stop flag content and validate it

---

## MEDIUM: `_check_save_result_guard` Not Actually Independent of Sentinel

**Location:** `memory_triage.py:702-743`
**Source:** Codex + Gemini (both flagged)

The docstring claims this is a "defense-in-depth" guard that works "semi-independently" from the sentinel. In reality, lines 733-736 require `read_sentinel()` to succeed AND return a matching `session_id`. If the sentinel is corrupt, missing, or is an old plain-text format, `read_sentinel()` returns `None`, and the guard returns `False` — providing no additional protection.

**Impact:** During rolling deployment where old `memory_write.py` deletes `.triage-handled` from cleanup, this guard is completely defeated. The defense-in-depth claim is misleading.

**Fix:** Either:
- Update the docstring to document the sentinel dependency honestly
- Or embed `session_id` directly in `last-save-result.json` so the guard can self-validate

---

## MEDIUM: SIGKILL Lock Orphan — 120s Triage Blackout

**Location:** `memory_triage.py:756-801`
**Source:** Codex + Opus vibe-check

If the process is SIGKILL'd after acquiring the lock but before the `finally` block runs, the lock file `.claude/.stop_hook_lock` persists until the 120s stale detection clears it. During this window, all subsequent stop hook invocations see `_LOCK_HELD` and return 0.

**Impact:** Triage is silently skipped for up to 2 minutes. However, `_LOCK_HELD → return 0` means the user can stop freely (not trapped), so this is a **missed triage**, not a blocked user. Acceptable for a CLI plugin.

**Mitigation:** Already handled correctly by the stale lock detection. Suggest adding a comment documenting this as an accepted tradeoff.

---

## LOW: Sentinel Files Have No Garbage Collection

**Location:** `memory_write.py:506-508`, `memory_triage.py:596-603`
**Source:** Codex + Opus vibe-check

`.triage-handled` is intentionally excluded from `_STAGING_CLEANUP_PATTERNS`. This means sentinel files persist in `/tmp/.claude-memory-staging-<hash>/` indefinitely. However:
- Bounded to **one file per project** (overwritten by new sessions)
- Located in `/tmp/` (OS tmpwatch/systemd-tmpfiles handles eventual cleanup)
- File size is ~150 bytes

**Impact:** Negligible in practice. Could become a concern if staging dir is ever moved out of `/tmp/`.

**Fix (optional):** Opportunistically unlink expired sentinels in `check_sentinel_session()` when `age >= FLAG_TTL_SECONDS`.

---

## Checklist Results

### Fail-open guarantees ✅
- All new functions (`read_sentinel`, `write_sentinel`, `check_sentinel_session`, `_check_save_result_guard`, `_acquire_triage_lock`, `_release_triage_lock`) return safe fallback values on any exception.
- `_run_triage()` is wrapped by `main()`'s catch-all `except Exception` that returns 0.
- `_LOCK_HELD → return 0` ensures lock contention never blocks the user.
- No code path found that could trap the user in a stop-blocked state from exceptions.

### Performance impact ✅
- Codex micro-benchmarked: `check_sentinel_session` ~0.05ms, `_check_save_result_guard` ~0.09ms, lock acquire+release ~0.25ms. Total ~0.4ms per invocation.
- No blocking I/O operations. All file operations use non-blocking open/read/write.
- JSON parsing of ~150-byte sentinel is negligible.

### Observability ⚠️ (adequate but not ideal)
- `emit_event("triage.score", ...)` logs all category scores with timing.
- `emit_error("triage.error", ...)` logs the catch-all exception.
- Sentinel state transitions (write) are NOT explicitly logged via `emit_event()`.
- Lock acquisitions/releases are NOT logged.
- **Debugging capability:** Sentinel file is human-readable JSON with `session_id`, `state`, `timestamp`, `pid`. Lock file similarly contains JSON. An operator can examine these files to diagnose stuck triage.

### Deployment / migration ✅
- Old plain-text sentinels: `read_sentinel()` hits `json.JSONDecodeError`, returns `None`. `check_sentinel_session()` returns `False` (proceed with triage). This is correct fail-open behavior — old sentinels are silently ignored and overwritten on next block.
- Old `memory_write.py` versions still include `.triage-handled` in cleanup patterns. If old code runs after new triage writes a sentinel, the sentinel gets deleted. **Impact:** One extra re-triage/re-block, which is the same problem this fix was solving. However, once the new `memory_write.py` is deployed, the sentinel survives.
- No explicit migration needed.

### Resource cleanup ✅
- Lock files: Always cleaned up in `finally` block (except SIGKILL — 120s stale detection handles).
- Sentinel files: One per project, bounded, in `/tmp/`.
- No risk of filling `/tmp/` or `.staging/`.

### Backward compatibility ✅
- `check_stop_flag()` / `set_stop_flag()` unchanged in interface (TTL change is the HIGH finding above).
- `memory_write_guard.py` references `.staging/` paths — still valid (sentinel is in staging dir).
- `memory_staging_guard.py` blocks Bash writes to staging — unaffected by sentinel changes (sentinel is written via Python `open()`, not Bash).

---

## External Reviewer Agreement Matrix

| Finding | Codex | Gemini | Opus |
|---------|-------|--------|------|
| Cross-session stop flag TTL | — | HIGH ✓ | Confirmed |
| Save-result guard not independent | MEDIUM ✓ | MEDIUM ✓ | Confirmed |
| SIGKILL lock orphan window | LOW ✓ | — | MEDIUM |
| Sentinel no GC | LOW ✓ | — | LOW |
| Implicit vs explicit fail-open | — | LOW ✓ | Noted |
| Lock TOCTOU race after stale unlink | Correct ✓ | Correct ✓ | Correct ✓ |

All three reviewers agree: fail-open discipline is consistent, atomicity primitives are correct, and performance is negligible.
