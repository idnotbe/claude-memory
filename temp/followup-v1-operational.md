# Verification Round 1: Operational Review

**Reviewer**: V-R1 Operational
**Scope**: All 4 follow-up items (sentinel state, RUNBOOK filter, lock migration, session_id in save-result)
**Status**: PASS with 1 advisory

---

## Item 1: Sentinel State Advancement

### State Machine Correctness

The transition map is minimal and correct:
- `pending -> saving` (save pipeline starting)
- `pending -> failed` (early failure before save attempt)
- `saving -> saved` (success)
- `saving -> failed` (pipeline error)

Terminal states (`saved`, `failed`) have no outgoing transitions. The `_SENTINEL_TRANSITIONS` dict enforces this -- any attempt to transition from `saved` or `failed` returns an error (but exits 0, fail-open). **Correct.**

### Stuck-State Recovery

If the process is killed while sentinel is in "saving":
1. **Same session re-stop**: `check_sentinel_session()` returns True (state "saving" is in `_SENTINEL_BLOCK_STATES`), so triage is skipped and stop proceeds. The user is never trapped -- they can always stop.
2. **Same session re-triage**: Blocked until FLAG_TTL_SECONDS (30 min) expires, at which point `age >= FLAG_TTL_SECONDS` allows re-triage. This is the designed recovery window.
3. **New session**: Different session_id bypasses the sentinel entirely (line 747-748).
4. **Single Bash call mandate**: SKILL.md mandates all pipeline commands in one `cmd1 ; cmd2 ; ...` Bash call. If the LLM agent crashes, the spawned shell process continues executing, which should reach the final `--state saved` or `--state failed` command. This is a strong mitigation against stuck "saving" states.

The timestamp is updated on each state transition (`current["timestamp"] = time.time()` at line 764 of memory_write.py), so the 30-min TTL starts from the "saving" transition, not from the original "pending" write. **Correct behavior.**

### Observability

State transitions produce JSON output with `previous_state`, `new_state`, `session_id`. The CLI handler logs these to stdout. The save subagent runs in a Task, so output is visible in the conversation. **Adequate for debugging.**

### Fail-Open Guarantees

- CLI always exits 0 regardless of error
- Invalid transitions return `{"status": "error"}` but exit 0
- Missing sentinel file returns error but exit 0
- Missing `--staging-dir` or `--state` returns error but exit 0
- Unexpected exceptions caught by broad `except Exception` handler

All fail-open paths verified. **PASS.**

---

## Item 2: RUNBOOK Negative Filter Expansion

### False Positive Reduction

The 5 regex groups are well-targeted at SKILL.md procedural text:
1. **Markdown headings**: `^#+` anchored -- cannot match mid-line real text
2. **Subagent failure instructions**: `^[-*]\s*If` anchored -- only matches list items
3. **Save command templates**: `memory_write.py.*--action` / `memory_enforce.py` -- highly specific to plugin commands
4. **Boilerplate**: `CRITICAL:\s*Using\s+heredoc` -- specific multi-word phrases
5. **Instructional patterns**: Extended to full context ("If ALL commands succeeded (no errors)") to avoid suppressing similar real text

### Adversarial Regression

Test `test_negative_patterns_dont_suppress_similar_real_text` verifies that "If any command failed, we checked the logs" is NOT suppressed (because it lacks "do NOT delete" suffix). This is the critical regression test. **Verified passing.**

### Performance Impact

5 compiled regex groups checked per line via `any(np.search(line) for np in negative_pats)`. With ~500 lines, that's ~2500 regex evaluations maximum. Python's compiled regex operates in C -- this adds <5ms to the triage run, well within the <100ms budget. The `any()` short-circuit means most lines will exit after 1-2 checks. **Negligible impact.**

### Coverage

8 tests (7 new, 1 existing) cover:
- All 5 groups individually (suppression tests)
- Real troubleshooting NOT suppressed (2 tests)
- Mixed content (only real lines score)
- Adversarial regression (similar phrasing not suppressed)

**PASS.**

---

## Item 3: Lock Migration to Staging Dir

### /tmp/ Cleanup by OS

Linux systemd-tmpfiles typically cleans `/tmp/` files older than 10 days. The lock file has a 2-minute stale timeout (line 869: `if age > 120`), so OS cleanup of the entire staging directory would only matter if a triage run spans >10 days -- impossible. If the directory is missing, `ensure_staging_dir()` recreates it. If `ensure_staging_dir()` fails (OSError or RuntimeError from symlink detection), the fail-open handler returns `("", _LOCK_ERROR)`. **No operational risk.**

### Determinism

`get_staging_dir(cwd)` derives the path from `sha256(os.path.realpath(cwd))[:12]`. This is deterministic across processes for the same project directory. Multiple concurrent triage hooks from the same project will resolve to the same lock path. **Correct.**

### Cleanup Safety

`_STAGING_CLEANUP_PATTERNS` does NOT include `.stop_hook_lock` (verified: patterns are `triage-data.json`, `context-*.txt`, `draft-*.json`, `input-*.json`, `intent-*.json`, `new-info-*.txt`, `.triage-pending.json`). The lock file survives cleanup. It's cleaned up explicitly by `_release_triage_lock()` at the end of triage. **Safe.**

### /tmp/ Full

If `/tmp/` is full, `os.mkdir()` in `ensure_staging_dir()` raises `OSError`. The try/except in `_acquire_triage_lock()` catches this and returns `("", _LOCK_ERROR)`. The triage proceeds without a lock (fail-open), relying on the sentinel for idempotency. **Correct degradation.**

### Backward Compatibility

Old lock files at `cwd/.claude/.stop_hook_lock` will become orphaned after this change. They are inert files (no active code reads from the old path). Over time they become stale (>2min) and would be cleaned by the old stale-lock logic, but since no code targets them, they simply sit harmlessly. **No backward compatibility issue.**

**PASS.**

---

## Item 4: session_id in Save-Result

### Guard Independence from Sentinel

`_check_save_result_guard()` primary path reads `session_id` directly from `last-save-result.json`. If present and matches current session: blocks re-triage. If present but different session: `continue` to next candidate. This works without any sentinel file. Verified by test `test_save_result_guard_works_without_sentinel`. **PASS.**

### Backward Compatibility (Old Results Without session_id)

When `session_id` is absent in the result file, the code falls through to the fallback path (line 816-819):
```python
sentinel = read_sentinel(cwd)
if sentinel and sentinel.get("session_id") == current_session_id:
    if sentinel.get("state", "") in _SENTINEL_BLOCK_STATES:
        return True
```

This correctly cross-references the sentinel. The check against `_SENTINEL_BLOCK_STATES` (which includes "pending", "saving", "saved") is appropriate here: if the sentinel shows the current session already reached a blocking state, the save-result file (even without session_id) is from this session's pipeline. **Backward compatible.**

### Rolling Deployment (Mixed Old/New Code)

- **Old triage + new write**: Old triage does not call `_check_save_result_guard` with session_id awareness. The old guard would ignore the `session_id` field in the save-result (it's just an extra key). **No breakage.**
- **New triage + old write**: Old write produces save-results without `session_id`. New guard's fallback path handles this via sentinel cross-reference. **No breakage.**

### Loop Termination Fix

The `return False` -> `continue` fix is critical. Previously, if the first candidate path had a different session_id, the guard immediately returned False (allow triage) without checking the second candidate path (the `/tmp/` staging dir). Now it correctly iterates through all candidates. **Important correctness fix, well-tested.**

### Fail-Open on Missing Save-Result

If no `last-save-result.json` exists in any candidate path, all `os.stat()` calls raise `OSError`, which is caught and `continue`d. The loop exhausts all candidates and returns `False` (allow triage). **Correct fail-open.**

**PASS.**

---

## General Assessment

### Test Coverage

All 4 items have dedicated tests:
- Item 1: 12 tests in `TestUpdateSentinelState` + SKILL.md prompt changes (not unit-testable)
- Item 2: 8 tests (7 new + 1 existing)
- Item 3: 3 tests (2 updated + 1 new)
- Item 4: 5 tests (3 updated + 2 new)

Total: 28 tests covering the follow-up changes. All pass (verified: 26/26 ran + 2 in existing suites).

### Backward Compatibility

All changes are backward compatible:
- Sentinel state advancement: new CLI action, does not affect existing actions
- RUNBOOK filter: additive negative patterns, only affects scoring (no schema change)
- Lock migration: old lock path abandoned (inert), new path works immediately
- session_id in save-result: additive field, old results handled via fallback

### Fail-Open Guarantees

Every new code path maintains fail-open:
- Sentinel state: always exit 0
- Lock acquisition: returns `_LOCK_ERROR` on failure
- Save-result guard: returns `False` (allow triage) on any error
- Negative patterns: `cfg.get("negative", [])` gracefully handles missing patterns

### Advisory: TOCTOU in update_sentinel_state

**[Low/Advisory]** There is a TOCTOU window between reading the sentinel JSON and writing the updated version via `os.replace()`. In theory, two concurrent processes could read the same state and both write transitions. In practice, this is heavily mitigated:
1. The triage lock serializes triage entry (only one process triggers saves)
2. The save pipeline runs in a single Task subagent (one writer)
3. `_SENTINEL_TRANSITIONS` prevents invalid jumps (e.g., `pending -> saved`)
4. The sentinel has a 30-min TTL safety net

Adding `fcntl.flock()` would close this gap at minimal cost, but the existing mitigations make exploitation effectively impossible. **No action required; advisory only.**

---

## Verdict

**PASS** -- All 4 follow-up items are operationally sound. The state machine is correct with proper recovery mechanisms. All fail-open guarantees hold. Backward compatibility is maintained. Test coverage is comprehensive.

1 advisory (TOCTOU in sentinel update) noted for future hardening but does not affect current operational reliability.
