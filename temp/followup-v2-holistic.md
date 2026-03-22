# Follow-up V-R2 Holistic Review

**Reviewer**: Opus 4.6 (1M) + Codex 5.3 cross-model
**Date**: 2026-03-22
**Scope**: Completeness against 4 follow-up items, system-wide integration, end-to-end flow

---

## 1. Completeness Against Follow-up Items

### P2: Sentinel State Advancement — PASS

**Implementation verified:**
- `update_sentinel_state()` in `memory_write.py` (line 716): reads current sentinel, validates transition via `_SENTINEL_TRANSITIONS` map, atomically writes updated state.
- Valid transitions: `pending->{saving, failed}`, `saving->{saved, failed}`. Terminal states (`saved`, `failed`) have no outbound transitions.
- Path containment: validates `/tmp/.claude-memory-staging-*` or legacy `.staging` paths (same pattern as `write_save_result`).
- CLI wiring: `--action update-sentinel-state --staging-dir <dir> --state <state>` (line 1838). Always exits 0 (fail-open).
- SKILL.md Phase 3 (line 296): fully wired into the combined single-Bash-call template with `_ok` tracking.
- **10 tests** in `TestUpdateSentinelState`: all 4 valid transitions, 2 invalid transitions, missing sentinel, missing staging-dir, missing state, session_id preservation, timestamp update, malformed JSON.

### P2: RUNBOOK Negative Filter — PASS (with advisory)

**Implementation verified:**
- Groups 3-5 added to `CATEGORY_PATTERNS["RUNBOOK"]["negative"]` (lines 176-199):
  - Group 3: Phase 3 save command templates (`memory_write.py.*--action`, `memory_enforce.py`)
  - Group 4: Phase 3 subagent prompt boilerplate (`CRITICAL: Using heredoc`, `Minimal Console Output`, etc.)
  - Group 5: SKILL.md-specific instructional patterns (anchored with extended context)
- **8 negative-pattern tests**: suppress doc headings, Phase 3 save commands, Phase 3 boilerplate, Phase 3 headings, allow real troubleshooting (3 tests), and mixed SKILL.md+real content.

**Advisory (LOW):** The `memory_write\.py.*--action\s+[-\w]+` pattern (Group 3) is broad enough to suppress real troubleshooting lines that include `memory_write.py --action` references. Verified empirically: a line like "I ran memory_write.py --action create and it crashed" scores 0.0 for RUNBOOK. However, practical impact is very low because: (a) this scenario only occurs when debugging the memory plugin itself, (b) the surrounding lines without `memory_write.py` still contribute score (Case 2 tested at 0.33), and (c) the pattern exists to prevent a known high-frequency false positive (SKILL.md Phase 3 contamination, the original RC-4). **Acceptable tradeoff; no fix needed.**

### P3: Lock Path Migration — PASS

**Implementation verified:**
- `_acquire_triage_lock()` (line 838): uses `ensure_staging_dir(cwd)` and places lock at `os.path.join(staging_dir, ".stop_hook_lock")`.
- No reference to old `cwd/.claude/.stop_hook_lock` path remains in production code.
- **3 tests**: lock acquire/release roundtrip verifies staging dir location, held-blocks-second-acquire, and explicit `test_lock_path_in_staging_dir` verifies NOT in `cwd/.claude/` and IS in staging dir.

### P3: session_id in Save-Result — PASS

**Implementation verified:**
- `_SAVE_RESULT_ALLOWED_KEYS` (line 614): includes `"session_id"`.
- `write_save_result()` (line 687): validates `session_id` as string or None.
- `write-save-result-direct` (line 1897-1921): reads `session_id` from sentinel file (best-effort, None on failure), embeds it in result JSON.
- `_check_save_result_guard()` (line 808-825): primary path reads `session_id` from result file directly. Fallback: sentinel cross-reference for backward compatibility with pre-session_id result files.
- **5 tests**: blocks same session (with session_id in result), allows different session, allows stale result, works WITHOUT sentinel (independence test), fallback TO sentinel (backwards compat test).

---

## 2. System-wide Integration Check

### Compile check: PASS
All `hooks/scripts/memory_*.py` compile cleanly.

### Test suite: PASS
**1198 tests passed** in 54.83s. Zero failures.

### CLAUDE.md: UP TO DATE
Key Files table includes `memory_write.py` and `memory_triage.py` with accurate descriptions. Write Actions section documents all 6 actions. Architecture section accurately describes the 5-phase flow.

### Action plan consistency: MINOR GAP
The follow-up items table in `fix-stop-hook-refire.md` (lines 72-77) lists the 4 items but doesn't mark them as resolved. The Files Changed table (lines 82-85) only lists original changes, not the follow-up additions (e.g., new `update-sentinel-state` action in `memory_write.py`, new SKILL.md Phase 3 template changes, new RUNBOOK negative patterns Groups 3-5). The frontmatter `status: done` and `progress` do mention follow-up completion generically.

---

## 3. End-to-End Flow Verification

### Step 1: User stops -> triage fires -> sentinel check -> lock -> score -> block
- `_run_triage()` calls `check_sentinel_session(cwd, session_id)` early (fail-open: returns False = proceed).
- If not blocked, acquires lock via `_acquire_triage_lock(cwd, session_id)` (staging dir path).
- Runs scoring. If categories trigger, writes sentinel via `write_sentinel(cwd, session_id, "pending")`.
- Returns block decision with triage data. **CORRECT.**

### Step 2: Save pipeline starts -> sentinel "saving" -> save commands -> sentinel "saved"/"failed"
- SKILL.md Phase 3 spawns haiku Task subagent with single-Bash-call template.
- Sequence: `_ok=1` -> `update-sentinel-state --state saving` -> `cmd1 || _ok=0` -> ... -> `memory_enforce || _ok=0` -> conditional cleanup (if _ok) -> conditional result write (if _ok) -> conditional sentinel saved/failed.
- **V-R1 fix applied**: `_ok` tracking with `|| _ok=0` after each save command AND enforce command.
- **Conditional result file**: only written when `_ok=1`. On failure, no result file = save-result guard won't block re-triage. **CORRECT.**

### Step 3: User stops again (re-fire) -> sentinel check blocks
- `check_sentinel_session()`: same session_id + state in `{pending, saving, saved}` + within TTL -> returns True (skip triage).
- `_check_save_result_guard()`: reads `session_id` from `last-save-result.json` directly. Match -> returns True (skip triage). **CORRECT.**

### Step 4: New session -> sentinel check allows
- `check_sentinel_session()`: different `session_id` -> returns False (proceed). **CORRECT.**

### Step 5: Failed save -> sentinel "failed" -> re-triage allowed
- On save failure: `_ok=0` -> cleanup skipped, result file skipped, sentinel advanced to "failed".
- `check_sentinel_session()`: state "failed" is NOT in `_SENTINEL_BLOCK_STATES` -> returns False (proceed with re-triage). **CORRECT.**

### Edge case: Initial sentinel advancement fails
- If `update-sentinel-state --state saving` fails (no sentinel file): exits 0 (fail-open), `_ok` stays 1.
- Save commands still execute normally.
- If saves succeed: `write-save-result-direct` tries to read sentinel for session_id, gets None. Result file has `session_id: null`.
- On re-fire: `_check_save_result_guard()` finds `session_id: null` in result -> doesn't match current session -> proceeds to sentinel check.
- `check_sentinel_session()`: sentinel is still in "pending" state (never advanced) -> blocks re-triage because "pending" is in `_SENTINEL_BLOCK_STATES`. **STILL PROTECTED.**
- If sentinel was never written at all (write_sentinel failed in step 1): `check_sentinel_session()` returns False (no sentinel = proceed). But `_check_save_result_guard` also has `session_id: null` -> no match -> allows. In this scenario, re-triage IS allowed. But this is actually correct behavior: if the sentinel system completely failed, the fallback is to allow re-triage rather than silently lose memories. **FAIL-OPEN BY DESIGN.**

---

## 4. Cross-Model Findings (Codex 5.3)

### Finding 1 (HIGH): Sentinel advancement not tracked in _ok — INVALID

Codex claimed the initial `update-sentinel-state --state saving` failure would lead to `last-save-result.json` with `session_id: null` defeating re-fire prevention. Analysis:

1. The SKILL.md template (line 296) makes the result file write CONDITIONAL on `_ok=1`, not unconditional. Codex's description of the template was inaccurate.
2. Even if sentinel advancement fails, the sentinel from `write_sentinel()` in step 1 is still at "pending" state. `check_sentinel_session()` blocks on "pending" (it's in `_SENTINEL_BLOCK_STATES`). Re-fire is still prevented.
3. If sentinel was never created (total system failure), then yes, re-fire prevention degrades. But this is correct fail-open behavior: allowing re-triage is better than permanently blocking saves.

**Verdict: Not a bug. The system correctly degrades gracefully.**

### Finding 2 (MEDIUM): memory_enforce.py not in _ok — INVALID

Codex claimed `memory_enforce.py` was not tracked by `_ok`. The actual template on line 296 shows `<memory_enforce.py command> || _ok=0` and step 4 in the description (line 304) explicitly states "Run memory_enforce.py if session_summary was created, also with `|| _ok=0`". Line 298 states "The `|| _ok=0` after EVERY command (save commands AND memory_enforce.py) captures individual failures."

**Verdict: Codex was incorrect. Enforce IS tracked.**

### Finding 3 (MEDIUM): RUNBOOK negative regex too broad — VALID (LOW severity)

Codex correctly identified that `memory_write\.py.*--action\s+[-\w]+` suppresses real troubleshooting lines that include `memory_write.py --action`. Empirically confirmed (see advisory in P2 section above). However, the practical impact is very low (plugin-internal debugging only, surrounding lines still contribute), and the pattern prevents a known high-frequency false positive.

**Verdict: Valid observation, acceptable tradeoff, no fix needed.**

---

## 5. Follow-up Items Resolution Summary

| Priority | Item | Status | Evidence |
|----------|------|--------|----------|
| P2 | Sentinel state advancement | RESOLVED | `update_sentinel_state()` + CLI action + SKILL.md Phase 3 wiring + 10 tests |
| P2 | RUNBOOK negative filter | RESOLVED | Groups 3-5 patterns + 8 tests (advisory: minor over-suppression) |
| P3 | Lock path migration | RESOLVED | `_acquire_triage_lock()` uses staging dir + 3 tests |
| P3 | session_id in save-result | RESOLVED | Schema + write-save-result-direct + guard primary path + 5 tests |

**All 4 follow-up items are fully resolved.**

---

## 6. Overall Assessment

**PASS** -- All follow-up items implemented correctly with comprehensive test coverage. The end-to-end stop-hook lifecycle is sound with proper fail-open degradation. One low-severity advisory (RUNBOOK negative pattern breadth) noted but acceptable given the tradeoff. 1198 tests pass, all scripts compile. The system maintains correct behavior across all lifecycle steps including edge cases (sentinel failure, total system failure).
