# Follow-up Implementation Log: WRITE IMPLEMENTER

## Items Completed

### Item 1 (P2): Sentinel State Advancement

**Part A: CLI action in memory_write.py**
- Added `update-sentinel-state` to CLI action choices
- Added `--state` argument to argparse
- Implemented `update_sentinel_state()` function with:
  - Valid state transitions: `pending->saving`, `pending->failed`, `saving->saved`, `saving->failed`
  - O_NOFOLLOW for symlink safety on read; O_EXCL for hard link defense on write
  - Atomic write via tmp+rename pattern
  - Returns JSON result with `previous_state`, `new_state`, `session_id`
- CLI handler always exits 0 (fail-open) -- sentinel advancement is best-effort
- 12 tests added (TestUpdateSentinelState): all transitions, invalid transitions, missing files, malformed JSON, session_id preservation, timestamp update

**Part B: SKILL.md wiring**
- Phase 3 save subagent prompt updated with 3 sentinel state calls:
  1. Before save commands: `--state saving`
  2. After successful save+cleanup: `--state saved`
  3. After any failure: `--state failed`
- Error handler (Step 3) now includes `--state failed` call before pending sentinel write
- Result file fields documentation updated to include `session_id`
- Mandated single Bash call for entire save pipeline (prevents sentinel stuck in "saving")

### Item 4 (P3): session_id in Save-Result Schema

**Part A: memory_write.py schema update**
- Added `"session_id"` to `_SAVE_RESULT_ALLOWED_KEYS`
- Added validation: `session_id` must be string or null
- `write-save-result-direct` now reads session_id from sentinel file (`.triage-handled`) using O_NOFOLLOW
- Fails gracefully: session_id is None if sentinel read fails
- 2 tests added: `test_session_id_from_sentinel`, `test_session_id_none_without_sentinel`

**Part B: memory_triage.py guard update**
- `_check_save_result_guard()` now reads session_id directly from save-result JSON (primary path)
- Falls back to sentinel cross-reference for backwards compatibility with pre-session_id result files
- Uses O_NOFOLLOW for safe file reads
- Guard is now fully independent: works without sentinel file present
- Fixed premature loop termination: `return False` changed to `continue` so all candidate paths are checked

**Part C: Test updates**
- Updated 3 existing tests to use production-realistic payloads (saved_at, categories, titles, errors, session_id)
- Removed sentinel dependency from save-result guard tests (tests now match primary code path)
- Added `test_save_result_guard_works_without_sentinel`: verifies guard independence from sentinel
- Added `test_save_result_guard_fallback_to_sentinel`: verifies backwards compatibility

## Clink Review Fixes Applied

1. **Premature loop termination in `_check_save_result_guard()`** (Critical): Changed `return False` to `continue` in both the different-session and fallback-inconclusive paths so all candidate staging dirs are checked
2. **Hard link attack on tmp file** (High): Replaced `O_CREAT|O_TRUNC|O_NOFOLLOW` with `O_CREAT|O_EXCL` for tmp file creation in `update_sentinel_state()` -- O_EXCL guarantees exclusive creation
3. **Sentinel stuck in "saving" state** (Medium): Rewrote SKILL.md Phase 3 prompt to mandate a single Bash call for the entire pipeline (sentinel->saves->cleanup->result->sentinel)
4. **Missing malformed JSON test** (Low): Added `test_malformed_json_sentinel_fails_open`

## Files Modified
- `hooks/scripts/memory_write.py`: update_sentinel_state function + CLI, session_id in save-result, O_EXCL hardening
- `hooks/scripts/memory_triage.py`: _check_save_result_guard rewritten with loop continuation fix
- `skills/memory-management/SKILL.md`: Phase 3 sentinel state wiring, single-call mandate
- `tests/test_memory_write.py`: 14 new tests (12 sentinel state, 2 session_id)
- `tests/test_memory_triage.py`: 3 updated + 2 new save-result guard tests

## Test Results
- 1188 passed, 5 pre-existing failures (unrelated: TestRuntimeErrorDegradation, TestIssue1IndexRebuild)
- Compile checks pass for both modified scripts
- Zero new failures introduced
