# Follow-up Implementation: Triage Items 2 & 3

## Item 2: Broaden RUNBOOK Negative Filter (P2)

### Problem
SKILL.md Phase 3 text contains error/failure keywords + boosters that scored 0.78 (threshold 0.5), causing RUNBOOK false positives during re-fire. The existing negative patterns (1 regex group with 3 anchored patterns) only covered markdown headings and conditional instructions.

### Solution
Expanded from 1 negative pattern group to 5 groups, covering:

1. **Group 1**: Markdown headings -- `^#+ Error Handling`, `^#+ Retry/Fallback Logic/Strategy`, `^#+ Write Pipeline Protections`, `^#+ Step N:` (removed trailing `\b` after `:` which was preventing matches)
2. **Group 2**: Conditional subagent failure instructions -- `^[-*] If (a )?(subagent|Task subagent) fails`
3. **Group 3**: Phase 3 save command templates -- `Execute (these )?memory save commands`, `memory_write.py.*--action [-\w]+`, `memory_enforce.py`
4. **Group 4**: Phase 3 subagent prompt boilerplate -- `CRITICAL: Using heredoc`, `Minimal Console Output`, `Combine ALL numbered commands`, `NEVER use Bash for file writes`
5. **Group 5**: SKILL.md-specific instructional patterns -- `^Run the following`, `If ALL commands succeeded (no errors)`, `If ANY command failed, do NOT delete`

### Review-driven Tightening
After initial implementation, Codex and Gemini both flagged that Groups 3 and 5 were too broad:
- **Group 3**: Standalone `cleanup-staging` and `write-save-result` substrings could match in natural text. **Fix**: Changed `--action\s+\w+` to `--action\s+[-\w]+` to catch hyphenated actions (`cleanup-staging`, `write-save-result-direct`) via the `memory_write.py` pattern, and removed standalone patterns.
- **Group 5**: `If ANY command failed` and `If ALL commands succeeded` suppressed real troubleshooting like "If any command failed, we checked the logs." **Fix**: Extended to match the full SKILL.md instruction: `If ALL commands succeeded (no errors)` and `If ANY command failed, do NOT delete`.

### Tests Added (7 new)
- `test_negative_patterns_suppress_phase3_save_commands` -- Phase 3 command templates suppressed
- `test_negative_patterns_suppress_phase3_boilerplate` -- Phase 3 subagent prompt boilerplate suppressed
- `test_negative_patterns_suppress_phase3_headings` -- Step/pipeline headings suppressed
- `test_negative_patterns_dont_suppress_real_error_fix` -- Real "error + root cause + fix" text NOT suppressed
- `test_negative_patterns_mixed_skillmd_and_real` -- Mixed lines: only real content scores
- `test_negative_patterns_dont_suppress_similar_real_text` -- Adversarial regression: "If any command failed, we checked..." NOT suppressed

## Item 3: Move Lock to Staging Dir (P3)

### Problem
Lock at `cwd/.claude/.stop_hook_lock` was inconsistent with sentinel at `/tmp/.claude-memory-staging-<hash>/.triage-handled`. The lock should co-locate with the sentinel for consistency.

### Solution
Changed `_acquire_triage_lock()`:
- **Before**: `lock_path = os.path.join(cwd, ".claude", ".stop_hook_lock")` with `os.makedirs(os.path.dirname(lock_path))`
- **After**: `staging_dir = ensure_staging_dir(cwd)` then `lock_path = os.path.join(staging_dir, ".stop_hook_lock")`

### Fail-open Hardening
Per vibe-check feedback: wrapped `ensure_staging_dir(cwd)` in try/except to maintain the fail-open contract documented in the function docstring:
```python
try:
    staging_dir = ensure_staging_dir(cwd)
except (OSError, RuntimeError):
    return "", _LOCK_ERROR  # Fail-open: staging dir unavailable
```
This handles both OS-level failures and `ensure_staging_dir()`'s symlink attack detection (`RuntimeError`).

### Lock cleanup safety
Verified that `cleanup_staging()` patterns (`triage-data.json`, `context-*.txt`, `draft-*.json`) do NOT match `.stop_hook_lock`, so the lock file is safe from accidental cleanup.

### Tests Updated/Added (2 updated, 1 new)
- `test_atomic_lock_acquire_release` -- Updated: removed `.claude` dir creation, added assertion that lock path is in staging dir
- `test_atomic_lock_held_blocks_second_acquire` -- Updated: removed `.claude` dir creation
- `test_lock_path_in_staging_dir` -- New: explicitly verifies lock is NOT in `cwd/.claude/` and IS in staging dir

## Verification
- `python3 -m py_compile hooks/scripts/memory_triage.py` -- passes
- 129/131 tests pass (2 pre-existing failures in `TestRuntimeErrorDegradation` unrelated to these changes)
- Vibe-check: addressed fail-open hardening concern
- Codex review: addressed overly broad negative patterns, lock migration approved
- Gemini review: addressed same pattern breadth concern, lock migration approved

## Files Modified
- `hooks/scripts/memory_triage.py` -- RUNBOOK negative patterns (5 groups), lock path migration
- `tests/test_memory_triage.py` -- 8 new/updated tests

## Pre-existing Test Failures (not from this change)
- `TestRuntimeErrorDegradation::test_write_context_files_degrades_on_runtime_error`
- `TestRuntimeErrorDegradation::test_write_context_files_degrades_on_os_error`
These test `write_context_files` fallback behavior when `ensure_staging_dir` raises, but the mock doesn't appear to take effect (possibly a mock targeting issue). Not related to Item 2 or 3.
