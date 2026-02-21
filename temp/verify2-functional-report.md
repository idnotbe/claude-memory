# Verification Round 2: Functional Test Report

**Agent**: verify2-functional
**Date**: 2026-02-18
**Scope**: Change 1 (rename `--action delete` to `--action retire`) and Change 2 (`_read_input()` staging-only restriction)

---

## 1. Compile Checks -- ALL PASS

All 7 hook scripts compile cleanly with `python3 -m py_compile`:

| Script | Result |
|--------|--------|
| `hooks/scripts/memory_write.py` | PASS |
| `hooks/scripts/memory_triage.py` | PASS |
| `hooks/scripts/memory_retrieve.py` | PASS |
| `hooks/scripts/memory_index.py` | PASS |
| `hooks/scripts/memory_candidate.py` | PASS |
| `hooks/scripts/memory_write_guard.py` | PASS |
| `hooks/scripts/memory_validate_hook.py` | PASS |

---

## 2. pytest Results -- 12 FAILURES in test_memory_write.py, 4 in test_arch_fixes.py

### Full suite: 16 failed, 419 passed, 10 xpassed (445 total)

### 2.1 test_memory_write.py: 12 failures (all same root cause)

**Root cause**: The `_read_input()` security fix (Change 2) now requires input files to reside in `.claude/memory/.staging/`. However, 12 tests use `write_input_file(tmp_path, ...)` which writes to pytest's `tmp_path` (e.g., `/tmp/pytest-*/input.json`), which is outside `.staging/`. These tests get `SECURITY_ERROR` instead of the expected behavior.

**Affected tests**:

| Test | Expected behavior | Actual |
|------|-------------------|--------|
| `TestCreateFlow::test_create_valid` | rc=0, file created | SECURITY_ERROR (input not in .staging/) |
| `TestCreateFlow::test_create_anti_resurrection` | rc=0, anti-resurrection | SECURITY_ERROR |
| `TestCreateFlow::test_create_with_auto_fixes` | rc=0, auto-fixes applied | SECURITY_ERROR |
| `TestUpdateFlow::test_update_valid` | rc=0, updated | SECURITY_ERROR |
| `TestUpdateFlow::test_update_occ_hash_mismatch` | rc=1, OCC_CONFLICT | SECURITY_ERROR |
| `TestUpdateFlow::test_update_slug_rename` | rc=0, slug renamed | SECURITY_ERROR |
| `TestUpdateFlow::test_update_changes_fifo_overflow` | rc=0, FIFO overflow | SECURITY_ERROR |
| `TestPathTraversal::test_path_traversal_create_blocked` | rc=1, traversal blocked | SECURITY_ERROR (correct rejection, wrong reason) |
| `TestCreateRecordStatusInjection::test_create_forces_active_status` | rc=0, status forced active | SECURITY_ERROR |
| `TestCreateRecordStatusInjection::test_create_forces_active_strips_archived` | rc=0, archived stripped | SECURITY_ERROR |
| `TestTagCapEnforcement::test_create_with_many_tags_succeeds_within_cap` | rc=0, tags truncated | SECURITY_ERROR |
| `TestOCCWarning::test_update_without_hash_warns` | rc=0, warning emitted | SECURITY_ERROR |

**Fix needed**: Update `write_input_file()` helper to write input files into `memory_project / ".claude" / "memory" / ".staging"` instead of `tmp_path`. The `memory_project` fixture already creates `.claude/memory/` -- just need to add `.staging/` mkdir and write there.

### 2.2 test_arch_fixes.py: 4 failures (same root cause)

| Test | Root Cause |
|------|-----------|
| `TestIssue4MkdirLock::test_write_operation_uses_lock` | Input file not in .staging/ |
| `TestIssue5TitleSanitization::test_combined_write_and_retrieve_sanitization` | Input file not in .staging/ |
| `TestCrossIssueInteractions::test_lock_not_needed_for_rebuild` | Input file not in .staging/ |
| `TestCrossIssueInteractions::test_validated_root_with_lock` | Input file not in .staging/ |

Same fix: update the input file creation helpers in these tests to use `.staging/`.

### 2.3 Passing tests (68 in test_memory_write.py)

The 68 passing tests are:
- **Unit tests** (TestAutoFix, TestSlugify, TestValidation, TestFormatValidationError, TestBuildIndexLine, TestWordDifferenceRatio, TestMergeProtections): 34 tests -- these test imported functions directly, no subprocess needed
- **TestRetireFlow**: 3 tests -- PASS (retire uses `--reason`, not `--input`, so no staging check)
- **TestPydanticValidation**: 10 tests -- PASS (direct function tests)
- **TestArchiveFlow**: 4 tests -- PASS (archive/unarchive/restore use `--reason`, not `--input`)
- **TestGCFlow**: 3 tests -- PASS (gc doesn't use `--input`)
- **TestRestoreFlow**: 3 tests -- PASS (restore uses `--reason`, not `--input`)
- **TestAntiResurrection**: 1 test (retire side) -- PASS
- **TestRetireArchiveValidation**: 6 tests -- PASS
- **TestPathTraversal** (remaining 2): PASS
- **TestSanitizeTitleOnWrite**: 2 tests -- PASS (direct function tests)

---

## 3. Stale Reference Grep -- CLEAN

### 3.1 `--action delete` in production files

Searched `*.py`, `*.md`, `*.json` across the entire repo:

| Directory | Result |
|-----------|--------|
| `hooks/` | 0 matches |
| `skills/` | 0 matches |
| `tests/` | 0 matches |
| `commands/` | 0 matches |
| `README.md` | 0 matches |
| `CLAUDE.md` | 0 matches |

**Only matches**: `MEMORY-CONSOLIDATION-PROPOSAL.md` (historical, excluded per instructions) and `temp/` files (working notes, not production).

### 3.2 `DELETE_ERROR` in test_memory_write.py

```
grep "DELETE_ERROR" tests/test_memory_write.py -- 0 matches
```

**CLEAN**: The old `DELETE_ERROR` constant has been fully removed/renamed.

---

## 4. Documentation Verification

| Check | Expected | Actual | Result |
|-------|----------|--------|--------|
| `commands/memory.md` line 15 | "Soft-retire" | `/memory --retire old-api-design  # Soft-retire a memory` | PASS |
| `README.md` line 125 | "Soft-retired" | `retired ... Soft-retired; preserved for 30-day grace period` | PASS |

---

## 5. Summary

| Category | Result | Details |
|----------|--------|---------|
| Compile checks (7 scripts) | PASS | All clean |
| Stale `--action delete` in production | PASS | 0 matches |
| Stale `DELETE_ERROR` in tests | PASS | 0 matches |
| Doc verification (memory.md, README.md) | PASS | Correct wording |
| pytest: unit tests (direct imports) | PASS | 68/68 |
| pytest: retire/archive/gc/restore flows | PASS | All pass |
| pytest: create/update subprocess flows | **FAIL** | 12 failures -- tests need `.staging/` fix |
| pytest: test_arch_fixes.py | **FAIL** | 4 failures -- same `.staging/` root cause |

### Verdict

**Change 1 (rename --action delete to --action retire)**: FULLY VERIFIED. All references updated, tests using `--action retire` pass, no stale references in production files.

**Change 2 (_read_input() staging-only restriction)**: CODE IS CORRECT but **tests are not updated**. The `_read_input()` function correctly rejects input files outside `.staging/`. The 12+4 test failures are caused by tests writing input files to `tmp_path` instead of the `.staging/` directory. This is a test infrastructure issue, not a code bug. The security enforcement is working as designed.

### Required Fix

Update `write_input_file()` in `tests/test_memory_write.py` (and equivalent helpers in `tests/test_arch_fixes.py`) to write input files into `memory_project / ".claude" / "memory" / ".staging"` instead of `tmp_path`. This will align the test infrastructure with the new security requirement while preserving test coverage.
