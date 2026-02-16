# Task 12: --action restore Implementation + Documentation Decisions

## Two Tasks

### Task A: Implement `--action restore` in memory_write.py
- Add `restore` to argparse choices
- Create `do_restore()` function (retired → active)
- Model after `do_unarchive()` (archived → active)
- Clear retirement fields (retired_at, etc.)
- Add changes entry
- Anti-resurrection does NOT apply (separate code path)

### Task B: Document design decisions in official docs
- Anti-resurrection: intentional safety feature, not a limitation
- Agent-interpreted config keys: intentional architecture, not a deficiency
- Remove any "Known Limitations" framing added by doc team for these
- Update CLAUDE.md, README.md as needed

## Implementation Plan for do_restore()

### Reference: do_unarchive() structure (lines 1021-1084)
1. Read target file
2. Check record_status == "retired" (only retired can be restored)
3. Set record_status = "active"
4. Clear retired_at field
5. Add changes entry
6. Write back
7. Update index

### Files to modify
- `hooks/scripts/memory_write.py` - add restore action + do_restore()
- `README.md` - update command table, remove wrong "Known Limitations"
- `CLAUDE.md` - document design decisions
- `commands/memory.md` - update --restore to use proper restore action
- `skills/memory-management/SKILL.md` - if relevant

## Changes Made

### Implementation (memory_write.py)
1. Added `do_restore()` function (modeled after `do_unarchive()`)
   - Path traversal check
   - Validates record_status == "retired"
   - Sets record_status = "active", clears retired_at/retired_reason
   - Adds changes entry
   - Atomic write + re-adds to index (since delete removes from index)
2. Added "restore" to argparse choices
3. Added routing in main()
4. Compile check: PASSED

### Documentation Updates
1. **commands/memory.md**: Replaced 26-line workaround with 5-line proper restore flow
2. **README.md**:
   - Fixed state transitions (removed "workaround" note)
   - Replaced "Known Limitations" restore item with "Design Decisions" section
   - Anti-resurrection documented as intentional safety feature
   - Agent-interpreted keys documented as intentional architecture
3. **CLAUDE.md**: Updated "5 actions" → "6 actions", added restore description
4. **SKILL.md**: Updated --restore description (removed workaround note)

## Additional Fixes (from verification)
- Added idempotent handling for already-active memories (vibe-check suggestion)
- Fixed stale module docstring ("3 operations" → "6 operations")
- Fixed --reason help text (was "delete only", now "delete/archive")
- Fixed misleading "within grace period" phrasing in README (restore works on any existing retired file; GC controls deletion)

## Status
- [x] Read current source code
- [x] Implement do_restore()
- [x] Update documentation
- [x] Vibe check (suggested idempotent handling - applied)
- [x] Pal clink (codex: rate limited, gemini: rate limited)
- [x] Verification round 1 (PASS - no issues)
- [x] Verification round 2 (PASS - 2 cosmetic fixes applied)
- [x] Final compile check: PASS
