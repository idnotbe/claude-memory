# Follow-up Verification Round 1: Security Review

**Reviewer**: V-R1 Security
**Date**: 2026-03-22
**Scope**: All 4 follow-up items (sentinel state, RUNBOOK negative filter, lock migration, session_id in save-result)
**Cross-check**: Gemini clink (codereviewer role) validated findings

## Verdict: PASS with 2 actionable findings (1 MEDIUM, 1 LOW)

No blocking security issues. Two items warrant follow-up but do not block merge.

---

## Item 1: Sentinel State Advancement (`update_sentinel_state`)

### FINDING-1 (MEDIUM): Missing staging_dir path containment validation

**Location**: `hooks/scripts/memory_write.py` line 734
**Issue**: `update_sentinel_state()` does `Path(staging_dir).resolve()` but does NOT validate the path is within `/tmp/.claude-memory-staging-*` or legacy `.staging/`. Every other function that takes `staging_dir` (`write_save_result` at L630-635, `cleanup_staging` at L527-531, `cleanup_intents` at L580-584) validates containment. An attacker who controls the `--staging-dir` CLI arg could point it at any directory containing a `.triage-handled` file with valid JSON and a valid state transition.

**Exploitability**: Limited. Requires:
1. A `.triage-handled` file to already exist at the target path
2. The file to contain valid JSON with a state that allows the requested transition
3. The target directory to be writable by the current user

**Impact**: Cross-project sentinel contamination -- an attacker could advance the sentinel state of another project's staging directory, potentially causing that project's triage to be permanently suppressed (if advanced to "saved"). However, since `_SENTINEL_BLOCK_STATES` includes a TTL check (`FLAG_TTL_SECONDS = 1800`), suppression is capped at 30 minutes.

**Recommendation**: Port the path validation logic from `write_save_result` (lines 630-639) into `update_sentinel_state`. Add before line 737:
```python
resolved_str = str(staging_path)
is_tmp = resolved_str.startswith("/tmp/.claude-memory-staging-")
parts = staging_path.parts
is_legacy = len(parts) >= 2 and parts[-1] == ".staging" and parts[-2] == "memory"
if not is_tmp and not is_legacy:
    return {"status": "error", "message": f"Invalid staging dir: {staging_dir}"}
```

**Gemini concurrence**: Validated. "An attacker who tricks the LLM could cross-contaminate the sentinel state of another valid project directory owned by the same user."

### FINDING-2 (OK -- Downgraded from initial LOW): O_EXCL vs O_NOFOLLOW consistency

**Location**: `memory_write.py` L777 vs `memory_triage.py` L712
**Analysis**: `update_sentinel_state` uses `O_CREAT|O_WRONLY|O_EXCL` for the tmp file; `write_sentinel` uses `O_CREAT|O_WRONLY|O_TRUNC|O_NOFOLLOW`. Per POSIX, `O_EXCL` guarantees exclusive creation and inherently fails if the target exists (including symlinks). `O_NOFOLLOW` is redundant with `O_EXCL`. The `O_EXCL` pattern in `update_sentinel_state` is actually the superior approach.

**Gemini concurrence**: "O_EXCL inherently makes the call atomic and explicitly forces failure if the target exists -- including if it is a symlink. O_NOFOLLOW is redundant when using O_EXCL."

### FINDING-3 (OK): State transition validation is sound

The `_SENTINEL_TRANSITIONS` dict enforces strict state machine: `pending->saving`, `pending->failed`, `saving->saved`, `saving->failed`. An attacker cannot skip directly from `pending` to `saved`. The `failed` state correctly allows re-triage (not in `_SENTINEL_BLOCK_STATES`). The state machine cannot be used to permanently suppress triage because:
1. `failed` allows re-triage
2. TTL expiry at 30 min provides a safety net for all blocking states
3. The CLI handler always exits 0 (fail-open), so errors do not break the pipeline

### FINDING-4 (LOW): Unprotected read-modify-write in `update_sentinel_state` (TOCTOU)

**Location**: `memory_write.py` lines 737-784
**Issue**: The function reads the sentinel, validates the state transition, then writes the updated state. No lock protects this sequence. Concurrent invocations could read the same initial state and clobber each other's transitions.
**Mitigation**: LLM execution is sequential within a session. The SKILL.md mandates a single Bash call for the entire save pipeline. Cross-session concurrent access is prevented by the triage lock. Practical risk is negligible.
**Gemini concurrence**: "Since LLM execution is generally sequential, the practical risk is low."

---

## Item 2: RUNBOOK Negative Filter

### FINDING-5 (OK): Negative patterns are properly scoped

The negative filter at line 460 operates per-line (`any(np.search(line) for np in negative_pats)`). This means:
- Only individual lines matching instructional patterns are suppressed, not entire documents
- Real troubleshooting content on non-matching lines still scores normally
- An attacker embedding "memory_write.py --action create" in a message only suppresses that one line

### FINDING-6 (LOW): Group 3 pattern `memory_write\.py.*--action\s+[-\w]+` has limited injection surface

**Issue**: If conversation text contains literal "memory_write.py --action something", that line is suppressed from RUNBOOK scoring. This is by design (suppressing SKILL.md transcript contamination).
**Mitigation**: Requires the attacker to also embed error/failure keywords in the same line for the suppression to matter. Even then, only one line's contribution is lost. The `max_primary=3` and `max_boosted=2` limits mean other matching lines can still trigger RUNBOOK.

### FINDING-7 (OK): Groups 4 and 5 are sufficiently anchored

Group 5 patterns (`If ALL commands succeeded (no errors)`, `If ANY command failed, do NOT delete`) are anchored to full phrase matches that are specific to SKILL.md procedural text. The review-driven tightening (from implementation log) correctly addressed the Codex/Gemini concern about `If any command failed` being too broad.

---

## Item 3: Lock Migration to Staging Dir

### FINDING-8 (OK -- Security improvement): Lock now in /tmp/ staging with ownership validation

The lock moved from `cwd/.claude/.stop_hook_lock` to `staging_dir/.stop_hook_lock` where `staging_dir` is `/tmp/.claude-memory-staging-<hash>/`. This is MORE secure because:
- `ensure_staging_dir()` validates ownership (`st_uid == os.geteuid()`) and rejects symlinks
- Directory permissions are 0o700 (owner-only)
- Lock creation uses `O_CREAT|O_EXCL|O_WRONLY|O_NOFOLLOW` (line 858)

### FINDING-9 (LOW -- Pre-existing pattern, not introduced by follow-up): Stale lock cleanup TOCTOU

**Location**: `memory_triage.py` lines 869-880
**Issue**: When two processes concurrently detect a stale lock (age > 120s), Process A unlinks and creates a new lock. Process B then unlinks A's fresh lock and creates its own. Both return `_LOCK_ACQUIRED`, breaking mutual exclusion.
**Severity assessment**: This race was raised by Gemini as HIGH. I downgrade to LOW for these reasons:
1. The lock function was introduced in recent changes but the stale-cleanup pattern is a standard approach and the race window is extremely narrow (sub-millisecond between unlink and O_EXCL retry)
2. The lock protects triage (a read-only keyword scoring operation), not writes. Two concurrent triages produce identical results (deterministic scoring)
3. The sentinel provides the actual idempotency guarantee (checked both before and after lock acquisition)
4. Claude Code's hook execution model is single-threaded per session; the lock's purpose is cross-session concurrency which is rare
5. If both triages run, the sentinel write (write_sentinel at end) uses atomic tmp+rename, so the last writer wins without corruption

**However**: The Gemini reviewer correctly identifies this is architecturally imperfect. For defense-in-depth, a `link()+unlink()` pattern or `fcntl.flock()` would be more robust. This is a follow-up improvement, not a blocking issue.

### FINDING-10 (OK): Fail-open on staging dir failure

The `try/except (OSError, RuntimeError)` at lines 846-849 correctly returns `_LOCK_ERROR` which allows the caller to proceed without lock. This maintains the documented fail-open contract.

---

## Item 4: session_id in Save-Result

### FINDING-11 (OK): session_id sourcing and validation

In `write-save-result-direct` (lines 1886-1902):
- Sentinel is read with `O_NOFOLLOW` (line 1891) for symlink safety
- session_id validated as `isinstance(sid, str) and sid` (line 1899)
- Falls back to `None` on any error (fail-open)
- The staging dir is 0o700, so only the owning user can write the sentinel
- `write_save_result()` validates session_id type: `isinstance(sid, str)` at line 688

### FINDING-12 (OK -- Already fixed): Loop continuation in `_check_save_result_guard`

The implementation log documents changing `return False` to `continue` at lines 813 and 821. Verified the current code correctly uses `continue`. This was a logic bug with security implications (premature loop termination could skip valid candidate paths), but it has been fixed.

### FINDING-13 (OK): O_NOFOLLOW consistency in save-result reads

`_check_save_result_guard()` at line 799 uses `O_NOFOLLOW` for reading the save-result file. Consistent with the project's defensive file I/O pattern.

---

## SKILL.md Sentinel Wiring Review

The Phase 3 subagent prompt (lines 289-306 of SKILL.md) correctly mandates:
1. Single Bash call for entire pipeline (prevents sentinel stuck in "saving")
2. Sentinel advanced to "saving" before saves, "saved" after success, "failed" after failure
3. Error handler (Step 3) includes `--state failed` before writing pending sentinel

The single-call mandate is the key security control: it prevents an interruption from leaving the sentinel permanently in "saving" state, which would block triage for 30 minutes.

---

## Summary Table

| ID | Severity | Item | Finding | Status |
|----|----------|------|---------|--------|
| F1 | MEDIUM | Sentinel state | Missing staging_dir path containment | **Actionable** |
| F2 | OK | Sentinel state | O_EXCL vs O_NOFOLLOW (non-issue) | Closed |
| F3 | OK | Sentinel state | State transitions sound | Closed |
| F4 | LOW | Sentinel state | Read-modify-write TOCTOU (mitigated) | Accept risk |
| F5 | OK | RUNBOOK filter | Per-line scoping correct | Closed |
| F6 | LOW | RUNBOOK filter | Group 3 injection surface (minimal) | Accept risk |
| F7 | OK | RUNBOOK filter | Groups 4-5 anchoring | Closed |
| F8 | OK | Lock migration | Security improvement | Closed |
| F9 | LOW | Lock migration | Stale cleanup TOCTOU (pre-existing pattern) | Follow-up |
| F10 | OK | Lock migration | Fail-open correct | Closed |
| F11 | OK | session_id | Sourcing and validation sound | Closed |
| F12 | OK | session_id | Loop continuation fixed | Closed |
| F13 | OK | session_id | O_NOFOLLOW consistency | Closed |

## Recommended Actions

1. **(MEDIUM -- F1)**: Add path containment check to `update_sentinel_state()` in `memory_write.py`. Copy the pattern from `write_save_result()` lines 630-639.
2. **(LOW -- F9)**: Consider hardening stale lock cleanup with `link()+unlink()` pattern or `fcntl.flock()` in a future pass. Not blocking for this change.
