# Rolling Window Implementation - Master Plan

## Problem
Guardian approval popup during session rolling window enforcement caused by inline Python with `>` operator being falsely matched as shell redirect.

## Solution
Replace inline rolling window logic with `memory_enforce.py` script + refactor `memory_write.py`.

## Phases

### Phase 1: Implement memory_write.py changes (impl-write teammate)
- 1A: Add `require_acquired()` method to `_flock_index` (keep backward compat)
- 1B: Increase `_LOCK_TIMEOUT` from 5.0 to 15.0
- 1C: Rename `_flock_index` -> `FlockIndex` (public class)
- 1D: Extract `retire_record()` from `do_retire()`

### Phase 2: Create memory_enforce.py (impl-enforce teammate)
- Depends on Phase 1 completion
- New file: `hooks/scripts/memory_enforce.py`
- Imports FlockIndex + retire_record from memory_write
- CLI with --category, --max-retained, --dry-run
- Root derivation, config reading, active scanning, enforcement

### Phase 3: Update SKILL.md (impl-docs teammate)
- Can run parallel with Phase 2
- 3A: Phase 3 instructions update
- 3B: Session Rolling Window section update

### Phase 4: Write Tests (test-writer teammate)
- 15 tests for memory_enforce.py
- 9 tests for memory_write.py changes
- Total: 24 test cases

### Phase 5: Verification Round 1
- v1-correctness: Code correctness review
- v1-security: Security review
- v1-integration: Integration review

### Phase 6: Verification Round 2
- v2-adversarial: Adversarial testing perspective
- v2-independent: Fresh-eyes independent review

## Key Files
- `hooks/scripts/memory_write.py` (modify)
- `hooks/scripts/memory_enforce.py` (create)
- `skills/memory-management/SKILL.md` (modify)
- `tests/test_rolling_window.py` (create)
- `tests/conftest.py` (may need session memory factory updates)

## Constraints
- Do NOT modify hooks.json
- Do NOT add --root CLI argument to memory_enforce.py
- Do NOT use Path.cwd() for relative paths in retire_record()
- Do NOT call do_retire() from memory_enforce.py (use retire_record())
- All 6 existing action handlers must keep backward compat
- Existing tests must pass (especially test_lock_timeout, test_permission_denied_handling)

## Status Tracking
- [x] Phase 1: memory_write.py changes (impl-write: COMPLETE)
- [x] Phase 2: memory_enforce.py creation (impl-enforce: COMPLETE)
- [x] Phase 3: SKILL.md updates (impl-docs: COMPLETE)
- [x] Phase 4: Tests written (test-writer: COMPLETE, 24/24 passing)
- [x] Phase 5: Verification Round 1 (3 reviewers: ALL PASS, no blocking issues)
  - v1-correctness: 27/27 checklist items PASS
  - v1-security: SAFE, 6 low-severity advisory items
  - v1-integration: 18/20 PASS, 2 CLAUDE.md doc gaps (fixed)
- [x] Phase 6: Verification Round 2 (2 reviewers: ALL PASS)
  - v2-adversarial: Found 2 medium issues (F1: do_retire output path, F2: bool config) -> FIXED
  - v2-independent: 11/11 spec compliance, 8/8 "What NOT to Do" compliance
- [x] Post-V2 Fixes Applied: F1 (relative path output) + F2 (boolean type guard)
- [x] CLAUDE.md documentation gaps fixed (Key Files + Smoke Check)
- [x] Final full test suite: 683/683 PASS

## Test Results
- 24 new rolling window tests: ALL PASS
- 683 total tests (full suite): ALL PASS
- Backward compatibility: CONFIRMED
