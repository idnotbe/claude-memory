# Follow-up V1: Correctness Review

**Reviewer**: Opus 4.6 (1M context)
**Cross-model**: Gemini 3.1 Pro, Codex (o4-mini)
**Date**: 2026-03-22
**Verdict**: 3 of 4 items PASS; Item 1 has a HIGH-severity SKILL.md prompt logic bug

---

## Item 1: Sentinel State Advancement

### Code (`memory_write.py::update_sentinel_state`) -- PASS

- **State transitions**: Correctly validated. `_SENTINEL_TRANSITIONS` maps `pending -> {saving, failed}` and `saving -> {saved, failed}`. Terminal states (`saved`, `failed`) have no entry, so `.get(state, set())` returns empty set, correctly rejecting any transition from terminal states. All 4 valid transitions and 2 invalid transitions tested.
- **Invalid transition handling**: Returns `{"status": "error", ...}` with exit code 0 (fail-open). Correct.
- **Missing sentinel file**: Returns error, exit 0. Correct.
- **Malformed JSON**: Caught by `json.JSONDecodeError`, returns error, exit 0. Correct.
- **Atomic write**: Uses O_CREAT|O_EXCL for tmp file (hard link defense). Preceding `os.unlink()` of stale tmp creates a micro-TOCTOU window, but O_EXCL guarantees the open fails if anything exists at that path (including symlinks). At worst, a DoS (write fails), never arbitrary file write. Acceptable.
- **Session ID preservation**: `current.get("session_id", "")` correctly preserves it. Tested.
- **CLI wiring**: `--action update-sentinel-state` requires `--staging-dir` and `--state`; missing either returns error JSON at exit 0. Correct.

### SKILL.md Phase 3 Wiring -- FAIL (HIGH)

**Bug: Contradictory single-Bash-call + conditional logic**

The prompt mandates combining ALL commands into a single Bash call with `;` separators (line 277, 289-293). The command template on line 296 unconditionally ends with `--state saved`. But the prose instructions (lines 302-304) say:
- "If ALL commands succeeded: run cleanup-staging (if ANY failed: skip cleanup)"
- "Advance sentinel to final state: 'saved' if all succeeded, 'failed' if any failed"

This is impossible with `;` separators. `;` does not propagate exit codes -- every command runs regardless. The haiku subagent cannot branch on failure within a single `;`-separated Bash call without explicit shell error tracking (e.g., `ok=1; cmd1 || ok=0; ...`).

**Impact**: Failed saves will always be marked `"saved"`, which is a blocking state in `_SENTINEL_BLOCK_STATES`. This suppresses re-triage for the rest of the session, defeating the purpose of the "failed" state that was meant to allow retry.

**Mitigation**: The Step 3 error handler (lines 317-332) catches total subagent failure/timeout and writes `--state failed`. So catastrophic failures (subagent crash, timeout) are covered. But partial failures within the Bash call (e.g., one create fails but others succeed) will always end up as `saved`.

**Recommended fix**: Use shell status tracking in the single Bash call:
```bash
ok=1; cmd1 || ok=1; cmd2 || ok=0; ...; \
if [ "$ok" -eq 1 ]; then cleanup-staging; fi; \
write-save-result-direct ...; \
if [ "$ok" -eq 1 ]; then --state saved; else --state failed; fi
```
Or allow the subagent to use 2 Bash calls: one for saves, one for finalization based on results.

### Minor: Terminal states not explicit in `_SENTINEL_TRANSITIONS`

The dict omits `"saved": set(), "failed": set()`. The `.get()` fallback handles it correctly, but adding explicit empty sets would improve readability and self-documentation.

---

## Item 2: RUNBOOK Negative Filter -- PASS

### Patterns Correct

All 5 negative pattern groups reviewed:

1. **Group 1** (headings): `^#+\s*Error\s+Handling\b`, `^#+\s*Step\s+\d+:` etc. Properly anchored to line start with `^`. Will not match "error handling" mid-line.
2. **Group 2** (conditional instructions): `^[-*]\s*If\s+(?:a\s+)?(?:subagent|Task\s+subagent)\s+fails`. Anchored to list item start.
3. **Group 3** (save commands): `memory_write\.py.*--action\s+[-\w]+` requires `--action` after `memory_write.py`. The adversarial test "The save failed when memory_write.py crashed unexpectedly." correctly does NOT match (no `--action`). `memory_enforce\.py\b` requires exact script name.
4. **Group 4** (boilerplate): `CRITICAL:\s*Using\s+heredoc` etc. Very specific phrases unlikely in natural text.
5. **Group 5** (instructional): Extended patterns require full SKILL.md context -- `If\s+ALL\s+commands\s+succeeded\s*\(no\s+errors\)` and `If\s+ANY\s+command\s+failed,\s+do\s+NOT\s+delete`. The `(no errors)` parenthetical and `do NOT delete` suffix are strong anchors that prevent false suppression of natural text like "If any command failed, we checked the logs."

### Performance

5 compiled regex groups checked per line (via `any(np.search(line) for np in negative_pats)`) is negligible. Regex compilation happens once at module load. Short-circuit evaluation on `any()` means most lines exit after 1-2 checks. No concern.

### Tests Adequate

7 new tests cover: suppression of Phase 3 commands, boilerplate, headings; non-suppression of real error fixes, mixed content, and adversarial similar phrasing. Good regression coverage.

---

## Item 3: Lock Path Migration -- PASS

### Implementation Correct

- `_acquire_triage_lock()` now calls `ensure_staging_dir(cwd)` and places lock at `os.path.join(staging_dir, ".stop_hook_lock")`.
- Fail-open hardening: `ensure_staging_dir()` wrapped in `try/except (OSError, RuntimeError)` returning `("", _LOCK_ERROR)`. This handles both OS failures and symlink attack detection from `ensure_staging_dir()`.
- Cleanup safety: Verified that `cleanup_staging()` patterns do not match `.stop_hook_lock`.
- `_release_triage_lock()` unchanged (simple `os.unlink`), still correct.

### Staging Dir Availability

`ensure_staging_dir(cwd)` creates the `/tmp/.claude-memory-staging-<hash>/` directory with `0o700` permissions and ownership validation. If creation fails, the lock function returns `_LOCK_ERROR` (fail-open). Correct behavior.

### Tests Updated

- `test_atomic_lock_acquire_release`: Updated to verify lock is in staging dir, not `cwd/.claude/`.
- `test_atomic_lock_held_blocks_second_acquire`: No `.claude` dir creation needed.
- `test_lock_path_in_staging_dir`: New test explicitly verifies old path is NOT used and new path IS in staging dir.

---

## Item 4: session_id in Save-Result -- PASS (with advisory)

### Schema Update Correct

- `"session_id"` added to `_SAVE_RESULT_ALLOWED_KEYS`. Validated as string or null.
- `write-save-result-direct` reads sentinel with `O_NOFOLLOW`, extracts `session_id`, includes in result JSON. Falls back to `None` on any failure. Correct.

### Guard Independence Correct

`_check_save_result_guard()` has two paths:
1. **Primary**: Reads `session_id` from result file directly. If matches current session, returns True (block). If different, `continue` to next candidate.
2. **Fallback**: Cross-references sentinel for legacy results without `session_id`. Checks sentinel state is in `_SENTINEL_BLOCK_STATES` (pending/saving/saved). `failed` state correctly NOT in block states, so failed sentinel + legacy result = allows re-triage.

### Loop Continuation Fix Correct

Previous `return False` on different-session and fallback-inconclusive was a premature termination bug. Changed to `continue` so all candidate paths are checked. Critical fix confirmed correct.

### Candidate Ordering

The function checks legacy path (`cwd/.claude/memory/.staging/`) first, then `/tmp/` path. Order does not affect correctness -- the loop is a logical OR, first match wins. If legacy has non-matching session_id, it continues to /tmp/ candidate.

### Advisory: Guard blocks on all fresh results, even with errors

`_check_save_result_guard()` blocks re-triage whenever a fresh result file has a matching `session_id`, regardless of whether `errors` is non-empty. Combined with the SKILL.md bug (Item 1) where `write-save-result-direct` hard-codes `errors: []` and requires non-empty `categories`/`titles`, this means:

- Currently: The guard effectively blocks on any result, which is correct because `write-save-result-direct` only writes on success.
- Future risk: If the save pipeline is fixed to write results on failure too (with `errors` populated), the guard would suppress retry even for failed saves.

This is not a current bug, but a latent design tension to address when fixing Item 1's SKILL.md issue.

---

## Cross-Model Consensus

| Finding | Gemini 3.1 Pro | Codex (o4-mini) | This review |
|---------|---------------|-----------------|-------------|
| SKILL.md single-Bash conditional logic bug | HIGH | HIGH | HIGH |
| Guard blocks regardless of save success | not flagged | MEDIUM | ADVISORY (latent) |
| validate_staging_dir not called in update_sentinel_state | not flagged | LOW | LOW (mitigated by flow) |
| Terminal states not explicit in transitions dict | LOW (readability) | not flagged | LOW (readability) |
| All other items correct | PASS | PASS | PASS |

---

## Summary

| Item | Verdict | Issues |
|------|---------|--------|
| 1: Sentinel state advancement (code) | PASS | Minor: explicit terminal states |
| 1: Sentinel state advancement (SKILL.md) | **FAIL** | HIGH: single-Bash-call cannot implement conditional saved/failed logic |
| 2: RUNBOOK negative filter | PASS | None |
| 3: Lock path migration | PASS | None |
| 4: session_id in save-result | PASS | Advisory: guard/result failure semantics (latent) |

**Action required**: Fix SKILL.md Phase 3 prompt to use shell error tracking or allow multiple Bash calls for the finalization step.
