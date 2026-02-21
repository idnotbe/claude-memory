# impl-docs Output: SKILL.md Updates for Rolling Window

## Changes Made

### 3A: Phase 3 Instructions Update (line 190-196)

**Before:** Single line "After all saves, enforce session rolling window if session_summary was created."

**After:** Replaced with a bash code block calling `memory_enforce.py --category session_summary` plus an explanation that the script reads `max_retained` from config automatically.

Location: `/home/idnotbe/projects/claude-memory/skills/memory-management/SKILL.md` lines 190-196.

### 3B: Session Rolling Window "How It Works" Section (lines 269-276)

**Before:** Steps 1-4 with detailed algorithm (scan logic, index comparison, explicit `memory_write.py --action retire` call). Step 3 had 5 sub-bullets describing the deletion guard comparison algorithm.

**After:** Steps 1-4 kept as concise summaries:
- Steps 1-2: Unchanged (describe what the script does internally).
- Step 3: Simplified to one sentence about the advisory warning + grace period.
- Step 4: Replaced with: "Handled automatically by `memory_enforce.py`. The script acquires the index lock, scans for active sessions, and retires excess sessions in a single atomic operation."

Location: `/home/idnotbe/projects/claude-memory/skills/memory-management/SKILL.md` lines 269-276.

### Sections NOT Modified (as required)
- Configuration section (lines 278-289) -- unchanged
- Manual Cleanup section (lines 291-296) -- unchanged
- hooks.json -- not touched
- All other SKILL.md sections -- unchanged

## Verification
- File compiles as valid markdown
- No references to the old inline Python enforcement remain
- `memory_enforce.py` is referenced as a script call (not a hook)
- Both `$CLAUDE_PLUGIN_ROOT` env var references use proper quoting
