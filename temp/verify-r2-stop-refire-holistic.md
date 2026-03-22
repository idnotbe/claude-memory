# V-R2 Holistic Review: Stop Hook Re-fire Fix

**Reviewer:** Opus 4.6 (Holistic, V-R2)
**Date:** 2026-03-22
**External Reviewers:** Codex (codereviewer), Gemini 3.1 Pro (codereviewer)

---

## 1. Completeness Check Against Action Plan

| Step | Description | Status | Notes |
|------|-------------|--------|-------|
| 1.1 | `.triage-handled` removed from cleanup patterns | PASS | `memory_write.py:506` -- comment explains intentional exclusion |
| 1.2 | FLAG_TTL_SECONDS = 1800 | PASS | `memory_triage.py:65` |
| 1.3 | Save-result guard with session_id comparison | PARTIAL | Implemented (`_check_save_result_guard`), but NOT independent -- see Finding F1 |
| 1.4 | Atomic lock with O_CREAT\|O_EXCL | PASS | Full acquire/release cycle with stale detection, HELD yields |
| 2.1 | RUNBOOK threshold >= 0.5 | PASS | `DEFAULT_THRESHOLDS["RUNBOOK"] = 0.5` |
| 2.2 | Negative filter for instructional text | PARTIAL | Anchored regexes work for headings, but SKILL.md text with boosters still triggers -- see Finding F2 |
| 3.1 | Session-scoped sentinel with get_session_id | PASS | `check_sentinel_session()` compares session_id |
| 3.2 | Sentinel as JSON with state machine | PASS | States: pending/saving/saved/failed with `_SENTINEL_BLOCK_STATES` frozenset |
| 3.3 | Sentinel survives cleanup | PASS | Verified by Step 1.1 |
| 3.4 | Retry-aware states + manual bypass | PARTIAL | State machine defined but never advances beyond "pending" -- see Finding F3 |
| 4 (tests) | All 5 required tests present | PASS | 16 tests in `TestStopHookRefireFix`, exceeds the 5 required |

**Summary:** 7/11 steps fully implemented, 4 partially implemented with known gaps.

---

## 2. Root Cause Verification

### RC-1: `.triage-handled` safe from cleanup
**VERIFIED.** Removed from `_STAGING_CLEANUP_PATTERNS` with clear comment. Test `test_sentinel_survives_cleanup` asserts this. The sentinel now persists until overwritten by a new session or expired via TTL.

### RC-2: 1800s TTL sufficient for save flow
**VERIFIED with caveat.** 1800s (30 min) covers the documented 10-28 min save flow. Separate `STOP_FLAG_TTL = 300` prevents cross-session bleed for the stop flag. If a save flow ever exceeds 30 min, the sentinel expires and re-fire becomes possible -- this is acceptable as a safety net against permanent suppression.

### RC-3: SESSION_SUMMARY cumulative re-trigger
**NOT ADDRESSED (by design, masked).** `score_session_summary()` at line 446 remains purely cumulative (tool_uses, distinct_tools, exchanges). The monotonic nature means any guard failure deterministically re-triggers SESSION_SUMMARY. The sentinel masks this but does not fix the root cause. This is acceptable debt IF the guard stack is robust; given the gaps identified below, it is a latent amplifier.

### RC-4: RUNBOOK false positive from SKILL.md contamination
**PARTIALLY FIXED.** The threshold increase (0.4 -> 0.5) and negative pattern filter reduce many false positives. However, testing confirms that SKILL.md-like text containing both primary keywords AND boosters (e.g., "error" + "fixed by", "failure" + "root cause") still scores above 0.5. Measured: 0.78 with boosted lines present. The negative filter only catches anchored markdown headings and conditional instructions, not prose containing error/failure + solution keywords.

---

## 3. Findings

### F1: Save-result guard is NOT independent (HIGH -- Codex finding, confirmed)

**Location:** `memory_triage.py:712-753`
**Issue:** `_check_save_result_guard()` depends on the sentinel to verify session_id. When the sentinel is missing/corrupt/clobbered, the guard returns False regardless of `last-save-result.json` freshness. Furthermore, `_SAVE_RESULT_ALLOWED_KEYS` in `memory_write.py:610` is `{"saved_at", "categories", "titles", "errors"}` -- no `session_id` field. The test at `test_memory_triage.py:2259` fabricates a `session_id` in the save-result JSON that production `write_save_result()` would reject as an unexpected key.

**Impact:** The defense stack is effectively 2 layers (sentinel + lock), not 3. The test overstates coverage.

**Recommendation:**
1. Either add `session_id` to `_SAVE_RESULT_ALLOWED_KEYS` and emit it from `write-save-result-direct`, or
2. Drop the claim that save-result is an independent guard and update the test to use production-realistic payloads, or
3. Have `_check_save_result_guard` read session_id from the result file itself (adding it to the schema) instead of cross-referencing the sentinel.

### F2: RUNBOOK negative filter too narrow for booster-rich text (MEDIUM -- Codex finding, confirmed)

**Location:** `memory_triage.py:150-157`
**Issue:** The negative filter only suppresses 3 anchored patterns (markdown headings, conditional bullet items). SKILL.md text containing unanchored error/failure keywords alongside booster keywords (fixed by, root cause, solution, workaround) still scores above threshold.
**Tested:** 7 representative SKILL.md-like lines with boosters -> RUNBOOK score 0.78 (threshold 0.5).

**Impact:** RC-4 can recur when SKILL.md instructional text is loaded into the transcript during the save flow.

**Recommendation:** Consider either:
1. Stripping known skill/doc payloads from the transcript text before scoring (content-based filtering), or
2. Adding broader negative patterns for imperative instructional prose (e.g., lines starting with "If ... fails"), or
3. Adding a transcript source filter that excludes system-injected content from scoring.

### F3: Sentinel state never advances beyond "pending" (MEDIUM -- known M2)

**Location:** `memory_triage.py:1430` (only `write_sentinel(..., "pending")` call)
**Issue:** The state machine defines 4 states (pending/saving/saved/failed) but only "pending" is ever written. Since "pending" is a blocking state, a failed save cannot transition to "failed" for retry. The sentinel remains in "pending" until TTL expiry (30 min).

**Impact:** If the save flow fails, automatic re-triage is blocked for up to 30 minutes. The retry-aware design from Step 3.4 is partially dead code.

**Recommendation:** This requires SKILL.md orchestration changes to advance sentinel state. Document as planned follow-up work.

### F4: Sentinel write position creates preemption window (MEDIUM -- Gemini finding)

**Location:** `memory_triage.py:1430` (write_sentinel) vs `memory_triage.py:1482` (print block decision)
**Issue:** The sentinel is written to "pending" at line 1430, but the actual block decision is not communicated to Claude Code until line 1482 (after context files, triage-data.json are all written). If the process is killed between these points (e.g., user hits Ctrl-C during context file generation), the sentinel blocks future triage attempts but no save actually started.

**Impact:** In rapid double-stop scenarios, the sentinel could suppress a legitimate triage without the save flow having started. TTL safety net (30 min) eventually recovers.

**Recommendation:** Move `write_sentinel("pending")` to immediately before `print(json.dumps({"decision": "block", ...}))`, or add rollback logic that deletes the sentinel if the script exits before emitting the block decision.

### F5: Lock path inconsistent with staging migration (LOW -- Gemini finding)

**Location:** `memory_triage.py:774` -- lock at `cwd/.claude/.stop_hook_lock`
**Issue:** The sentinel lives in `/tmp/.claude-memory-staging-<hash>/` but the lock lives in `cwd/.claude/`. This splits ephemeral coordination state across two directories, inconsistent with the `/tmp/` staging migration.

**Impact:** The lock file pollutes the user's `.claude/` directory. If `/tmp/` is wiped but `.claude/` persists (or vice versa), coordination state becomes inconsistent.

**Recommendation:** Move the lock to `get_staging_dir(cwd)` for consistency.

---

## 4. Integration Verification

### Sentinel path vs. write guard
**No conflict.** The sentinel is written by `memory_triage.py` via Python `open()`, which does not trigger the `PreToolUse:Write` hook. The write guard only intercepts the LLM's Write tool calls. This is correct behavior (Gemini confirmed: trusted host execution correctly bypasses the LLM sandbox).

### Staging guard compatibility
**No conflict.** `memory_staging_guard.py` blocks Bash writes (cat/echo/tee/cp/mv) to staging directories. The sentinel is written via Python `os.open()` + `os.replace()`, which is not a Bash command.

### SKILL.md references
**No issues.** SKILL.md references `.triage-pending.json` (the retry file) and `.triage-handled` (the sentinel) separately. The sentinel format change to JSON is compatible with SKILL.md's error handling instructions at line 316-321.

---

## 5. Test Coverage Assessment

### Present (16 tests in TestStopHookRefireFix)
1. `test_sentinel_survives_cleanup` -- RC-1
2. `test_flag_ttl_covers_save_flow` -- RC-2
3. `test_save_result_guard_blocks_same_session` -- Step 1.3 (but see F1)
4. `test_save_result_guard_allows_different_session` -- Step 1.3
5. `test_save_result_guard_allows_stale_result` -- Step 1.3
6. `test_runbook_threshold` -- Step 2.1
7. `test_session_scoped_sentinel_blocks_same_session` -- Step 3.1
8. `test_session_scoped_sentinel_allows_different_session` -- Step 3.1
9. `test_session_scoped_sentinel_allows_failed_state` -- Step 3.4
10. `test_session_scoped_sentinel_allows_expired` -- Step 3.4
11. `test_atomic_lock_acquire_release` -- Step 1.4
12. `test_atomic_lock_held_blocks_second_acquire` -- Step 1.4
13. `test_sentinel_read_write_roundtrip` -- Step 3.2
14. `test_read_sentinel_returns_none_when_missing` -- Step 3.2
15. `test_negative_patterns_suppress_doc_headings` -- Step 2.2
16. `test_negative_patterns_allow_real_troubleshooting` -- Step 2.2

### Missing/recommended tests
- **V-R1 fix coverage:** No tests for `STOP_FLAG_TTL` separation, FIFO rejection, CWD validation, or corrupted-timestamp fail-open.
- **Save-result guard with production schema:** Current test fabricates `session_id` in result JSON; need a test using `_SAVE_RESULT_ALLOWED_KEYS`-compliant data.
- **RUNBOOK scoring with boosted SKILL.md text:** Test that realistic SKILL.md transcript lines with boosters do/don't exceed threshold (documenting the known gap).
- **Sentinel preemption rollback:** Test that sentinel is cleaned up if script exits before block decision.

---

## 6. Follow-up Items (Priority Order)

| Priority | Item | Blocking? |
|----------|------|-----------|
| P1 | Fix save-result guard test to use production-realistic payloads (F1) | No -- cosmetic, but misleading |
| P1 | Decide: add session_id to save-result schema OR remove independence claim (F1) | No -- defense-in-depth, not critical path |
| P2 | Broaden RUNBOOK negative filter or add content source filtering (F2) | No -- masked by sentinel, but RC-4 latent |
| P2 | Defer sentinel write to minimize preemption window (F4) | No -- TTL recovers, but improves correctness |
| P3 | Wire sentinel state advancement into SKILL.md orchestration (F3/M2) | No -- TTL recovers |
| P3 | Move lock to staging dir (F5) | No -- cosmetic consistency |
| P3 | Add V-R1 fix tests | No -- fixes already in code |

---

## 7. Overall Assessment

The stop-hook re-fire fix substantially improves the situation. The core fix (removing sentinel from cleanup + TTL increase + session-scoped sentinel) addresses the primary re-fire loop (RC-1, RC-2). The defense-in-depth layers work but are not as independent as designed. The RUNBOOK contamination fix is partially effective. The state machine is architecturally sound but operationally incomplete (only "pending" is written).

**Verdict:** The fix is safe to ship. The remaining gaps (F1-F5) are documented, none are blocking, and all have TTL-based recovery. RC-3 (SESSION_SUMMARY cumulative scoring) remains a latent amplifier but is masked by the sentinel. Recommend addressing F1 (test accuracy) and F4 (sentinel write position) as quick follow-ups.

---

## 8. Clink Review Summary

### Codex Findings
- **Confirmed:** Save-result guard depends on sentinel (not independent)
- **Confirmed:** RUNBOOK filter too narrow for booster-rich text
- **Confirmed:** Sentinel state machine dead code beyond "pending"
- **Confirmed:** RC-3 is latent amplifier, not harmless

### Gemini Findings
- **Confirmed:** Sentinel write position creates preemption window
- **Confirmed:** Lock path inconsistent with staging migration
- **Confirmed:** Sentinel writes via Python open() correctly bypass write guard (as designed)
- **Accepted:** Save-result path coverage is correct (no need for non-staging paths)
