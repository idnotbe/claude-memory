# Follow-up Items Briefing (P2-P3)

## Item 1 (P2): Sentinel State Advancement
**Goal**: Wire sentinel state transitions into the save pipeline so failed saves allow re-triage instead of blocking for 30 min.

**Current state**: Only `write_sentinel(cwd, session_id, "pending")` is called (memory_triage.py ~line 1430). States saving/saved/failed are defined but never written.

**Approach**: Add `--action update-sentinel-state` CLI action to `memory_write.py`. Takes `--staging-dir` and `--state`. Reads current sentinel from staging dir's `.triage-handled`, validates state transition, atomically updates.

**SKILL.md changes** (Phase 3, lines ~270-325):
- Before save commands: advance to "saving"
- After successful save + cleanup: advance to "saved"
- In error handler: advance to "failed"

**Key files**: `hooks/scripts/memory_write.py` (new CLI action), `skills/memory-management/SKILL.md` (Phase 3 orchestration)

**Constraint**: The save pipeline runs in a Task subagent (haiku) that only has Bash access. So the sentinel update must be callable via `python3 memory_write.py --action update-sentinel-state --staging-dir <dir> --state saving`.

## Item 2 (P2): Broaden RUNBOOK Negative Filter
**Goal**: Reduce SKILL.md contamination false positives for RUNBOOK category.

**Current negative patterns** (memory_triage.py ~line 150-157): Only 3 anchored patterns (headings, conditional instructions).

**Problem**: SKILL.md Phase 3 text contains unanchored error/failure keywords + boosters that score 0.78 (threshold 0.5).

**Approach**: Add broader negative patterns for SKILL.md procedural text:
- Phase 3 headings, save command templates
- "Execute memory save commands", "write-save-result", "cleanup-staging"
- "CRITICAL: Using heredoc", "Minimal Console Output"

**Key file**: `hooks/scripts/memory_triage.py` (RUNBOOK category patterns)

## Item 3 (P3): Move Lock to Staging Dir
**Goal**: Move `.stop_hook_lock` from `cwd/.claude/` to staging dir for consistency with sentinel.

**Current**: `_acquire_triage_lock()` creates lock at `os.path.join(cwd, ".claude", ".stop_hook_lock")`
**Target**: `os.path.join(get_staging_dir(cwd), ".stop_hook_lock")`

**Changes needed**:
- `memory_triage.py`: Update `_acquire_triage_lock()` lock path
- `tests/test_memory_triage.py`: Update lock path assertions in tests
- Ensure `get_staging_dir()` creates the directory if needed (it should via makedirs)

**Key file**: `hooks/scripts/memory_triage.py` (~line 784), tests

## Item 4 (P3): Add session_id to Save-Result Schema
**Goal**: Make `_check_save_result_guard()` truly independent of sentinel by embedding session_id in save-result.

**Current**: `_SAVE_RESULT_ALLOWED_KEYS = {"saved_at", "categories", "titles", "errors"}` — no session_id.

**Changes needed**:
1. Add `"session_id"` to `_SAVE_RESULT_ALLOWED_KEYS` in `memory_write.py`
2. In `write-save-result-direct` action: read session_id from sentinel file and include in result
3. In `_check_save_result_guard()` in `memory_triage.py`: read session_id from save-result JSON directly instead of cross-referencing sentinel
4. Update tests to use production-realistic payloads

**Key files**: `hooks/scripts/memory_write.py` (schema + write action), `hooks/scripts/memory_triage.py` (guard function), tests
