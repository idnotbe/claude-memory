# Team Orchestration: fix-claude-memory

## Task Summary
Two bugs to fix in claude-memory plugin:
1. **Rename `--action delete` to `--action retire`** across 7 files
2. **Fix `_read_input()` to only allow `.staging/`** (memory_write.py only)

## Instructions File
`temp/fix-claude-memory.md` - the source of truth for all changes

## What NOT to Change (Critical)
- CUD internal labels: `UPDATE_OR_DELETE`, `DELETE` in CUD table
- `"UPDATE over DELETE"` principle in SKILL.md
- `_cleanup_input()` function
- Config keys: `delete.grace_period_days`, `delete.archive_retired`
- Comment at ~line 843 about rename flow
- `temp/*.md` files
- `MEMORY-CONSOLIDATION-PROPOSAL.md`

## Team Structure

### Phase 1: Implementation (parallel)
| Teammate | Scope | Files |
|----------|-------|-------|
| impl-core | memory_write.py (Change 1 + Change 2) | hooks/scripts/memory_write.py |
| impl-docs | Docs & config files (Change 1 only) | SKILL.md, commands/memory.md, memory_write_guard.py, CLAUDE.md, README.md |
| impl-tests | Test file updates (Change 1 only) | tests/test_memory_write.py |

### Phase 2: Verification Round 1 (parallel, after Phase 1)
| Teammate | Perspective | Focus |
|----------|-------------|-------|
| verify1-checklist | Correctness | Line-by-line checklist vs fix instructions |
| verify1-security | Security | Edge cases, injection, unintended changes |
| verify1-consistency | Consistency | Cross-file consistency, no stale refs |

### Phase 3: Verification Round 2 (parallel, after Phase 2 fixes)
| Teammate | Perspective | Focus |
|----------|-------------|-------|
| verify2-functional | Functional | Run pytest, smoke tests |
| verify2-grep-scan | Completeness | grep for ALL stale delete references |
| verify2-holistic | Holistic | Overall quality, do-not-change items preserved |

## Communication Protocol
- All long input/output via files in `temp/`
- Direct messages = file links only
- Each teammate writes their output to `temp/<teammate-name>-report.md`

## Status
- [x] Phase 1: Implementation (3 teammates, all completed)
- [x] Phase 2: Verification Round 1 (3 teammates, all PASS -- 1 medium fix applied: commands/memory.md line 15, 1 low fix applied: README.md line 125)
- [x] Phase 2.5: Test fixture fix (write_input_file + test_arch_fixes.py updated to use .staging/ paths)
- [x] Phase 3: Verification Round 2 (3 fresh teammates, all PASS)
- [x] All tests pass: 435 passed, 10 xpassed, 0 failures

## Additional Changes (found during verification)
1. `commands/memory.md:15`: "Soft-delete a memory" -> "Soft-retire a memory" (found by verify1-consistency)
2. `README.md:125`: "Soft-deleted" -> "Soft-retired" (found by verify1-consistency)
3. `tests/test_memory_write.py`: `write_input_file()` updated to use `.staging/` paths (found by verify2-functional)
4. `tests/test_arch_fixes.py`: 5 input file locations updated to use `.staging/` paths (found by verify2-functional)

## Files Modified (total: 9)
1. hooks/scripts/memory_write.py (Change 1 + Change 2)
2. skills/memory-management/SKILL.md (Change 1)
3. commands/memory.md (Change 1 + consistency fix)
4. hooks/scripts/memory_write_guard.py (Change 1)
5. CLAUDE.md (Change 1)
6. README.md (Change 1 + consistency fix)
7. tests/test_memory_write.py (Change 1 + test fixture fix)
8. tests/test_arch_fixes.py (test fixture fix)

## Team Members Used (12 total)
Phase 1: impl-core, impl-docs, impl-tests
Phase 2: verify1-checklist, verify1-security, verify1-consistency
Phase 2 (Round 2): verify2-functional, verify2-grep, verify2-holistic
Phase 3 (Final): final-functional, final-grep, final-holistic
