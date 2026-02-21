# Bug Fix Working Memory

## Source: temp/claude-memory-plugin-architecture-issues.md

## Bugs to Fix

### R1 (P0): Script paths in SKILL.md need `${CLAUDE_PLUGIN_ROOT}` prefix
- **File**: `skills/memory-management/SKILL.md`
- **What**: All `hooks/scripts/memory_candidate.py` and `hooks/scripts/memory_write.py` references must become `"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/..."`
- **Lines affected**: ~84, ~97, ~125-128 and anywhere else these paths appear

### R2 (P0): Move staging files from `/tmp/` to `.claude/memory/.staging/`
- **Files**:
  - `skills/memory-management/SKILL.md` - all `/tmp/.memory-draft-*` and `/tmp/.memory-triage-context-*` references
  - `hooks/scripts/memory_triage.py` - `write_context_files()` function writes to `/tmp/`
- **What**: Replace `/tmp/` staging with `.claude/memory/.staging/`
- **SKILL.md lines**: ~69, ~97, ~121-123
- **triage.py lines**: ~703 (path construction), ~969 (log path)

### R3 (P1): Make Stop hook idempotent via sentinel file
- **File**: `hooks/scripts/memory_triage.py`
- **What**: Add sentinel file check at `.claude/memory/.staging/.triage-handled` before blocking. If sentinel exists and is < 5 min old, allow stop.
- **Where**: In `_run_triage()` after config load, before transcript parsing

### R5 (P3): Add plugin self-validation to SKILL.md
- **File**: `skills/memory-management/SKILL.md`
- **What**: Add verification step at skill start to check `${CLAUDE_PLUGIN_ROOT}` scripts exist

### R4 (P2): Clean up dev artifacts from ops project
- **Note**: This is in `/home/idnotbe/projects/ops/temp/` -- different repo, skip for now

## Team Structure

### Implementation Phase (parallel)
- **skill-fixer**: Fix SKILL.md (R1, R2-SKILL parts, R5)
- **hook-fixer**: Fix memory_triage.py (R2-triage parts, R3)

### Verification Round 1 (parallel, after implementation)
- **verifier-correctness**: Verify all path changes are correct, no missed occurrences
- **verifier-edge-cases**: Verify edge cases, security, staging dir creation

### Verification Round 2 (parallel, after round 1)
- **verifier-functional**: Run tests, compile-check, functional verification
- **verifier-integration**: Cross-file consistency, integration between SKILL.md and triage.py

## Status Log
- [x] Team created (bugfix-squad)
- [x] Implementation started (skill-fixer + hook-fixer running in parallel)
- [x] Implementation complete (both tasks done, 56 tests pass)
- [x] Verification round 1 complete (PASS - both verifiers)
  - Correctness: All 4 pre-existing bug fixes + R1-R5 verified PASS
  - Edge cases: No CRITICAL issues. 2 MEDIUM findings already addressed by hook-fixer
  - Quick spot-check by lead: R1 (0 unqualified paths), R2 (0 /tmp/ in SKILL.md), datetime.utcnow() already fixed
- [x] Verification round 2 complete (PASS - both verifiers: SHIP IT)
  - Functional: 56/56 existing tests pass, 0 warnings, manual code walk-through PASS
  - Integration: All E2E paths verified, V1 issues confirmed fixed
  - Gap found: No tests for R2 staging paths or R3 sentinel - FIXED by lead
- [x] Tests passing: 65 tests (56 existing + 5 staging + 4 sentinel), 0 failures, 0 warnings
- [x] CLAUDE.md /tmp/ reference updated to .staging/ path
- [x] BLOCKING issue found by verifier-integration: write guard blocks .staging/ writes - FIXED
- [x] Write guard tests pass (14/14)
- [x] Final test count: 70 triage + 14 write guard = 84 tests, all passing
- [x] ALL DONE

## Teammates
| Name | Role | Task | Status |
|------|------|------|--------|
| skill-fixer | Fix SKILL.md | #1 | Running |
| hook-fixer | Fix memory_triage.py | #2 | Running |
| (TBD) | Verification R1 - Correctness | #3 | Blocked by #1, #2 |
| (TBD) | Verification R1 - Edge cases | #3 | Blocked by #1, #2 |
| (TBD) | Verification R2 - Functional | #4 | Blocked by #3 |
| (TBD) | Verification R2 - Integration | #4 | Blocked by #3 |
