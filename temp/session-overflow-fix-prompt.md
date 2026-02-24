# Session Memory Overflow Fix Prompt

Run this prompt in the `claude-memory` repo: `cd ~/projects/claude-memory && claude`

---

## Prompt to paste:

```
## Problem: Session Memory Overflow in ops repo

The ops project at `/home/idnotbe/projects/ops` has a session memory overflow:
- Location: `/home/idnotbe/projects/ops/.claude/memory/sessions/`
- Current state: **67 active session files** exist
- Expected: max **5** active sessions (per `max_retained: 5` in memory-config.json)
- Config location: `/home/idnotbe/projects/ops/.claude/memory/memory-config.json`

### Root Cause Investigation

The `memory_enforce.py` script should enforce the rolling window by retiring
sessions beyond the max_retained limit after each new session is created.
However, 67 files accumulated, meaning either:
1. `memory_enforce.py` was not being called consistently after session saves
2. The script has a bug preventing it from retiring old sessions
3. Sessions were created before the rolling window feature was implemented

### What I Need You To Do

1. **Investigate**: Read `hooks/scripts/memory_enforce.py` and understand how it works.
   Check if there are bugs that would prevent it from retiring sessions beyond the limit.

2. **Test**: Run `memory_enforce.py` in dry-run mode (if available) against the ops
   project's session directory to see what it would retire:
   ```
   python3 hooks/scripts/memory_enforce.py --category session_summary \
     --root /home/idnotbe/projects/ops/.claude/memory
   ```
   If there's no dry-run mode, check the script's behavior first before running.

3. **Fix the overflow**: Run `memory_enforce.py` to retire sessions down to max 5.
   It should keep the 5 most recent sessions (by `created_at`) and retire the rest
   with `record_status: "retired"`.

4. **Verify**: After enforcement, confirm:
   - Exactly 5 active session files remain
   - The 5 retained are the most recent by `created_at`
   - Retired files have `record_status: "retired"` and `retired_reason` set

5. **Root cause**: If you find a bug in `memory_enforce.py` that caused this, fix it.
   If the issue is that enforce wasn't being called, document this so we can ensure
   it's called consistently.

### Important Context

- The ops project uses the claude-memory plugin at `/home/idnotbe/projects/claude-memory`
- Config is at `/home/idnotbe/projects/ops/.claude/memory/memory-config.json`
- Session files are JSON with fields: `schema_version`, `category`, `id`, `title`,
  `record_status` ("active"/"retired"/"archived"), `created_at`, `updated_at`, etc.
- The rolling window keeps the N most recent by `created_at`, retires the rest
- Retirement sets `record_status: "retired"`, adds `retired_at` and `retired_reason`
- There is a 30-day grace period before retired sessions are GC-eligible
```

---

## Notes

- The 67 session files have been accumulating across many sessions
- Most should be retired (keep only the 5 most recent)
- After fixing, the stop hook's memory consolidation flow should call `memory_enforce.py`
  automatically at the end of Phase 3 (this is already in the skill instructions)
