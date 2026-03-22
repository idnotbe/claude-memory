# Stop Hook Re-fire Fix — Implementation Briefing

## Problem
Stop hook fires 2-3 extra times per session end. Each re-fire produces ~26 visible output items.
Both idempotency guards are destroyed before re-check.

## Root Causes
| ID | Cause | Location |
|----|-------|----------|
| RC-1 | `.triage-handled` sentinel deleted by `cleanup_staging()` | `memory_write.py:506` in `_STAGING_CLEANUP_PATTERNS` |
| RC-2 | `FLAG_TTL_SECONDS = 300` (5 min) too short for 17-28 min save flow | `memory_triage.py:49` |
| RC-3 | SESSION_SUMMARY always re-triggers (cumulative activity metrics) | `memory_triage.py:408-429` |
| RC-4 | RUNBOOK false positive from SKILL.md keyword contamination | RUNBOOK patterns `memory_triage.py:114-124` |

## Phase 1: P0 Hotfix (4 changes)

### Step 1.1: Remove `.triage-handled` from cleanup patterns
- File: `hooks/scripts/memory_write.py:506`
- Action: Delete the `".triage-handled",` line from `_STAGING_CLEANUP_PATTERNS`
- Why: Sentinel's TTL already provides self-cleanup. Cleanup destroying it causes re-fire.

### Step 1.2: Increase FLAG_TTL_SECONDS
- File: `hooks/scripts/memory_triage.py:49`
- Action: Change `FLAG_TTL_SECONDS = 300` to `FLAG_TTL_SECONDS = 1800`
- Why: Save flow takes 10-28 min with subagent spawning. 5 min is too short.

### Step 1.3: Add save-result guard in `_run_triage()`
- File: `hooks/scripts/memory_triage.py` in `_run_triage()` after sentinel check (~line 1084)
- Action: Check `last-save-result.json` mtime AND session_id. If fresh (< FLAG_TTL_SECONDS) AND same session, return 0.
- Note: `last-save-result.json` persists through cleanup (not in `_STAGING_CLEANUP_PATTERNS`)
- **V-R1 note**: Must compare session_id in result file, not just mtime, to avoid blocking new sessions started within 30 min.

### Step 1.4: Add atomic lock for TOCTOU prevention
- File: `hooks/scripts/memory_triage.py` at top of `_run_triage()` after stdin read
- Action: `os.open('.claude/.stop_hook_lock', os.O_CREAT | os.O_EXCL)` with session_id
- Prevents TOCTOU race when multiple stop hooks fire concurrently
- **Must clean up lock on exit** (V-R2 finding)
- Lock file should contain session_id + PID for debugging

## Phase 2: Raise RUNBOOK Threshold

### Step 2.1: Change RUNBOOK threshold
- File: `hooks/scripts/memory_triage.py:57`
- Action: Change `"RUNBOOK": 0.4` to `"RUNBOOK": 0.5`

### Step 2.2: Negative filter for instructional text
- Consider adding negative filter for patterns like "If a subagent fails", "Error Handling" headings
- This reduces SKILL.md contamination in transcript

## Phase 3: Session-Scoped Idempotency (defense-in-depth)

### Step 3.1: Session-scoped sentinel
- Replace dual TTL guards with session-scoped sentinel
- Use `get_session_id(transcript_path)` to key the sentinel
- Same session = skip triage, New session = allow triage

### Step 3.2: Sentinel as JSON state file
- Remove `.stop_hook_active` flag (consumed-on-check = fragile)
- Replace with session state in `.triage-handled` JSON:
```json
{"session_id": "...", "transcript_hash": "...", "state": "pending|saving|saved|failed", "timestamp": ...}
```

### Step 3.3: Make sentinel survive cleanup permanently
- Only overwrite on new session

### Step 3.4: Retry-aware state management
- Only set state="saved" AFTER successful commit
- If save fails, set state="failed"
- When checking sentinel:
  - Skip triage if state in ("pending", "saving", "saved")
  - ALLOW re-triage if state="failed" AND `.triage-pending.json` exists
- Bypass sentinel entirely when `/memory:save` is manually invoked

## Key Code Locations

### `_run_triage()` current flow (memory_triage.py:1047-1207):
1. Read stdin JSON (line 1052)
2. Extract fields (line 1064)
3. Load config (line 1069)
4. Check `stop_hook_active` flag (line 1074) ← consumed-on-check, fragile
5. Check `.triage-handled` sentinel (line 1078) ← destroyed by cleanup
6. Read transcript (line 1087)
7. Score categories (line 1105)
8. Output block decision (line 1134)

### `_STAGING_CLEANUP_PATTERNS` (memory_write.py:499-508):
```python
_STAGING_CLEANUP_PATTERNS = [
    "triage-data.json", "context-*.txt", "draft-*.json",
    "input-*.json", "intent-*.json", "new-info-*.txt",
    ".triage-handled",        # ← RC-1: REMOVE THIS
    ".triage-pending.json",
]
```

### `get_session_id()` (memory_logger.py:81-96):
Extracts session ID from transcript path filename stem.
Example: "/tmp/transcript-abc123.json" → "transcript-abc123"

### `check_stop_flag()` / `set_stop_flag()` (memory_triage.py:522-548):
Uses `.claude/.stop_hook_active` file with mtime check. Consumed on check (unlinks).
Phase 3 replaces this with session-scoped sentinel.

## Constraints
- `memory_triage.py` is stdlib-only (no pydantic)
- Must fail-open on all error paths
- Must not break existing sentinel path used by other scripts (memory_write_guard.py references `.triage-handled`)
- `last-save-result.json` format: written by `memory_write.py:562+`, contains results dict
