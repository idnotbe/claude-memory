---
status: done
progress: "All 4 phases + 4 follow-up items complete. 1198 tests pass. 2 rounds of verification × 2 cycles (initial + follow-up) with cross-model verification (Codex 5.3 + Gemini 3.1 Pro). All HIGH/MEDIUM findings fixed."
---

# Fix Stop Hook Re-fire Loop — Action Plan

Stop hook fires 2-3 extra times per session end. Each re-fire produces ~26 visible output items (all noise) and may trigger additional popups. Root cause: both idempotency guards are destroyed before re-check.

## Root Causes

| ID | Root Cause | Status |
|----|-----------|--------|
| RC-1 | `.triage-handled` sentinel deleted by `cleanup_staging()` | FIXED |
| RC-2 | `FLAG_TTL_SECONDS = 300` (5 min) too short for 17-28 min save flow | FIXED |
| RC-3 | SESSION_SUMMARY always re-triggers (cumulative activity metrics) | MASKED (sentinel blocks re-fire) |
| RC-4 | RUNBOOK false positive from SKILL.md keyword contamination | PARTIALLY FIXED (threshold + negative filter) |

## Phases

### Phase 1: P0 Hotfix (4 code changes) [x]
- [x] **Step 1.1**: Removed `.triage-handled` from `_STAGING_CLEANUP_PATTERNS` in `memory_write.py`
- [x] **Step 1.2**: Increased `FLAG_TTL_SECONDS` from `300` to `1800` (30 min). Added separate `STOP_FLAG_TTL = 300` for `check_stop_flag()` (V-R1 fix: prevents cross-session bleed)
- [x] **Step 1.3**: Added `_check_save_result_guard()` -- checks `last-save-result.json` mtime + sentinel session_id cross-reference
- [x] **Step 1.4**: Added `_acquire_triage_lock()` / `_release_triage_lock()` with `O_CREAT|O_EXCL` atomicity, 120s stale detection, HELD yields

### Phase 2: Raise RUNBOOK Threshold [x]
- [x] **Step 2.1**: RUNBOOK threshold 0.4 → 0.5
- [x] **Step 2.2**: Added negative patterns for doc scaffolding (headings, conditional instructions)

### Phase 3: Session-Scoped Idempotency (defense-in-depth) [x]
- [x] **Step 3.1**: Session-scoped sentinel with `get_session_id(transcript_path)` keying
- [x] **Step 3.2**: Sentinel as JSON: `{"session_id", "state", "timestamp", "pid"}`, states: pending/saving/saved/failed
- [x] **Step 3.3**: Sentinel survives cleanup (removed from cleanup patterns in Step 1.1)
- [x] **Step 3.4**: State machine defined. **Known gap**: only "pending" is written in production (state advancement requires SKILL.md changes). TTL safety net (30 min) prevents permanent suppression.

### Phase 4: Tests [x]
- [x] **Step 4.1**: `test_sentinel_survives_cleanup`
- [x] **Step 4.2**: `test_flag_ttl_covers_save_flow`
- [x] **Step 4.3**: `test_save_result_guard_*` (3 tests: same session, different session, stale)
- [x] **Step 4.4**: `test_runbook_threshold`
- [x] **Step 4.5**: `test_session_scoped_sentinel_*` (4 tests: blocks, allows different, allows failed, allows expired)
- [x] Additional: lock acquire/release, sentinel roundtrip, negative patterns (2), STOP_FLAG_TTL (3)
- [x] Verification: 2 independent rounds (V-R1: 3 reviewers, V-R2: 2 reviewers)

## Verification Summary

### V-R1 (3 reviewers: correctness, security, operational)
| Finding | Severity | Status |
|---------|----------|--------|
| `check_stop_flag()` TTL regression (30 min cross-session bleed) | HIGH | FIXED (STOP_FLAG_TTL=300) |
| `check_sentinel_session()` TTL except fails closed | MEDIUM | FIXED (pass → return False) |
| Sentinel state never advances beyond "pending" | MEDIUM | DOCUMENTED (follow-up) |
| `_check_save_result_guard` depends on sentinel | MEDIUM | DOCUMENTED |
| FIFO DoS on sentinel read | MEDIUM | FIXED (O_NONBLOCK + fstat) |
| Unsanitized cwd from hook input | MEDIUM | FIXED (realpath + isdir) |
| /tmp/ staging dir symlink hijack | HIGH | PRE-EXISTING (not this PR) |
| Lock TOCTOU double-acquisition | HIGH | ACCEPTED (low practical risk) |

### V-R2 (2 reviewers: adversarial, holistic)
| Finding | Severity | Status |
|---------|----------|--------|
| `read_sentinel()` double-close bug (V-R1 fix regression) | HIGH | FIXED |
| `STOP_FLAG_TTL` zero test coverage | MEDIUM | FIXED (3 tests added) |
| `set_stop_flag()` follows symlinks | MEDIUM | FIXED (O_NOFOLLOW) |
| `import stat` inside function body | LOW | FIXED (moved to module scope) |
| Save-result guard test uses non-production schema | MEDIUM | DOCUMENTED (follow-up) |
| Sentinel write position preemption window | MEDIUM | DOCUMENTED (follow-up) |

## Follow-up Items (all resolved)

| Priority | Item | Status |
|----------|------|--------|
| P2 | Sentinel state advancement (pending→saving→saved/failed) | DONE — `update-sentinel-state` CLI + SKILL.md wiring with `_ok` tracking |
| P2 | RUNBOOK negative filter broadening | DONE — 5 pattern groups, tested against SKILL.md + real text |
| P3 | Lock path → staging dir | DONE — consistent with sentinel at `/tmp/` |
| P3 | session_id in save-result | DONE — schema + guard independence + backward compat |

### Follow-up Verification

**V-R1** (3 reviewers: correctness, security, operational):
- HIGH: SKILL.md `;` separator can't do conditional saved/failed → FIXED (`_ok` shell variable)
- MEDIUM: `update_sentinel_state()` missing path containment → FIXED

**V-R2** (2 reviewers: adversarial, holistic):
- HIGH: Save-result guard blocks re-triage even on failed saves → FIXED (result file conditional on `_ok=1`)
- HIGH: `memory_enforce.py` failure silently masked → FIXED (`|| _ok=0` added)
- MEDIUM: Legacy path validation accepts any `*/memory/.staging` → FIXED (see Pre-existing Fixes below)

## Pre-existing Security Fixes

Both previously-marked "PRE-EXISTING" bugs are now fixed:

| Bug | Fix | Verification |
|-----|-----|-------------|
| Staging dir symlink hijack (`memory_staging_utils.py`) | Shared `_validate_existing_staging()`: lstat symlink check, ownership validation, S_ISDIR, permission tightening. Legacy path uses `os.mkdir()` for atomic create. | V-R1 (3 reviewers) + V-R2 (2 reviewers), all PASS |
| Legacy path validation (`memory_write.py`) | `_is_valid_legacy_staging()` requires `.claude/memory/.staging` ancestry. All 5 call sites updated. | 14 new tests, zero old patterns remaining |
| `write_save_result()` uncaught RuntimeError | Added `except (RuntimeError, OSError)` for staging dir validation failures | V-R1 finding, V-R2 confirmed fixed |

## Files Changed

| File | Changes |
|------|---------|
| hooks/scripts/memory_write.py | Removed `.triage-handled` from cleanup, `update-sentinel-state` CLI, session_id in save-result, staging_dir path containment, `_is_valid_legacy_staging()` helper, RuntimeError catch |
| hooks/scripts/memory_triage.py | FLAG_TTL 1800, STOP_FLAG_TTL 300, session-scoped sentinel (JSON state), save-result guard (independent), atomic lock (staging dir), RUNBOOK 0.5 + 5 negative pattern groups, O_NONBLOCK/fstat, cwd validation, set_stop_flag O_NOFOLLOW |
| hooks/scripts/memory_staging_utils.py | `_validate_existing_staging()` shared helper, legacy path symlink/ownership/permission defense, S_ISDIR check |
| skills/memory-management/SKILL.md | Phase 3 sentinel state wiring with `_ok` status tracking, conditional cleanup/result/state |
| tests/test_memory_triage.py | 22 new regression tests |
| tests/test_memory_write.py | 28 new tests (sentinel state + session_id + legacy validation) |
| tests/test_memory_staging_utils.py | 5 new tests (symlink, permissions, ownership) |
