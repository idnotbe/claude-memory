# Stop Hook Re-fire Fix -- Test Results

## Test Summary
- **Class**: `TestStopHookRefireFix` in `tests/test_memory_triage.py`
- **Tests written**: 16 (5 required + 11 additional/sub-cases)
- **All pass**: 113/113 total file tests pass (97 existing + 16 new)

## Test Mapping to Requirements

| # | Required Test | Method(s) | Status |
|---|--------------|-----------|--------|
| 1 | sentinel_survives_cleanup | `test_sentinel_survives_cleanup` | PASS |
| 2 | flag_ttl_covers_save_flow | `test_flag_ttl_covers_save_flow` | PASS |
| 3 | save_result_guard | `test_save_result_guard_blocks_same_session`, `test_save_result_guard_allows_different_session`, `test_save_result_guard_allows_stale_result` | PASS (3) |
| 4 | runbook_threshold | `test_runbook_threshold` | PASS |
| 5 | session_scoped_sentinel | `test_session_scoped_sentinel_blocks_same_session`, `test_session_scoped_sentinel_allows_different_session`, `test_session_scoped_sentinel_allows_failed_state`, `test_session_scoped_sentinel_allows_expired` | PASS (4) |
| + | atomic_lock_acquire_release | `test_atomic_lock_acquire_release`, `test_atomic_lock_held_blocks_second_acquire` | PASS (2) |
| + | sentinel_read_write_roundtrip | `test_sentinel_read_write_roundtrip`, `test_read_sentinel_returns_none_when_missing` | PASS (2) |
| + | negative_patterns_suppress_doc | `test_negative_patterns_suppress_doc_headings`, `test_negative_patterns_allow_real_troubleshooting` | PASS (2) |

## Vibe Check
**Assessment**: On track. Well-structured, thorough regression suite directly covering all root causes (RC-1 through RC-4) from the implementation log. The sentinel state machine matrix (same session, different session, failed, expired) is particularly strong.

## Clink Reviews

### Codex (codex-5.2-high)
**Positives**:
- Session-sentinel matrix covers the core state machine well
- RUNBOOK negative-pattern pair is the right kind of regression guard
- Not flaky; main risk is brittleness from coupling to private helpers

**Gaps identified (Medium)**:
- No end-to-end `_run_triage()` tests for save-result guard and lock branches
- Several tests pin constants rather than behavior (cleanup patterns, TTL, threshold)
- No coverage for stale-lock cleanup (120s), `_LOCK_ERROR` fail-open, or cwd-local save-result path

**Note**: The E2E coverage gap is partially mitigated by the existing `TestSentinelIdempotency` class which already exercises `_run_triage()` for sentinel-based suppression.

### Gemini (gemini-3.1-pro-preview)
**Positives**:
- Robust time-shifting via `os.utime()` avoids flaky `time.sleep()`
- Excellent `tmp_path` isolation prevents host pollution
- Real-world test data in negative-pattern tests

**Gaps identified (Medium)**:
- Missing stale lock retry (120s) and fail-open (malformed JSON) edge cases
- Static constant assertions could be replaced with behavioral tests (e.g., invoke `cleanup_staging()` directly)
- No combined flow test verifying guard interaction inside `_run_triage()`

## Known Gaps (deferred)
Both reviewers consistently flagged these as future improvements:
1. Stale lock reclamation test (backdated lock > 120s, verify overwrite)
2. Fail-open on malformed sentinel JSON (corrupted file -> returns False)
3. Behavioral test for `cleanup_staging()` preserving `.triage-handled`
4. `_LOCK_ERROR` path coverage (OS error -> proceed without lock)
5. `_run_triage()` integration test for save-result guard and lock-HELD paths

These are valid but out of scope for this regression test batch. The existing `TestSentinelIdempotency` class already provides E2E coverage for the core sentinel flow through `_run_triage()`.
