# Final Holistic Review Report

**Reviewer**: final-holistic
**Date**: 2026-02-18
**Scope**: End-to-end review of all changed files for Change 1 (rename `--action delete` to `--action retire`) and Change 2 (`_read_input()` staging-only restriction), including the test fixture fix.

## 1. hooks/scripts/memory_write.py

### 1.1 `do_retire` function (lines 873-945)
- **PASS**: Function named `do_retire`, docstring says "Handle --action retire (soft retire)."
- **PASS**: Error prefixes are `RETIRE_ERROR` (lines 883, 901-906)
- **PASS**: Line 879: path containment label is `"RETIRE"` (not "DELETE")
- **PASS**: Line 843: comment says "Rename flow: write new, update index, delete old" -- this refers to filesystem file deletion during slug rename, NOT the CLI action. Correct and unchanged.
- **PASS**: Idempotent path returns `"already_retired"` (line 896)
- **PASS**: Blocks archived->retired transition with clear error (lines 901-906)

### 1.2 `_read_input()` staging-only (lines 1165-1205)
- **PASS**: Docstring says "Read JSON from input file in .claude/memory/.staging/"
- **PASS**: Checks `".." in input_path` (line 1173) -- path traversal block
- **PASS**: Checks `"/.claude/memory/.staging/" in resolved` (line 1181) -- staging-only enforcement
- **PASS**: Both checks produce `SECURITY_ERROR` with clear fix message

### 1.3 `_cleanup_input()` (line 1208-1213)
- **PASS**: Unchanged from original -- simple `os.unlink` with OSError catch

### 1.4 argparse choices (line 1334)
- **PASS**: `choices=["create", "update", "retire", "archive", "unarchive", "restore"]` -- no "delete"

### 1.5 Dispatch block (lines 1364-1375)
- **PASS**: `elif args.action == "retire": return do_retire(...)` -- correct dispatch

### 1.6 No stale references
- **PASS**: Grep for `"delete"`, `do_delete`, `DELETE_ERROR`, `--action delete` in this file: **0 matches**

## 2. skills/memory-management/SKILL.md

### 2.1 CUD labels preserved
- **PASS**: Line 90: `structural_cud` includes `"UPDATE_OR_DELETE"` -- internal CUD label, correctly preserved
- **PASS**: Line 95: "decide UPDATE or DELETE" -- internal CUD decision, not CLI action
- **PASS**: Line 96: "Prefer UPDATE over DELETE" -- safety default principle
- **PASS**: Line 155-159: CUD resolution table uses DELETE as internal label
- **PASS**: Line 167: "UPDATE over DELETE (non-destructive)" -- principle statement

### 2.2 CLI action uses `--action retire`
- **PASS**: Line 100: `{"action": "retire", ...}` for DELETE draft output
- **PASS**: Line 102: "Report: action (CREATE/UPDATE/RETIRE/NOOP)" -- RETIRE not DELETE
- **PASS**: Line 130: `--action retire --target <path> --reason "<why>"` in Phase 3

### 2.3 Session rolling window
- **PASS**: Line 218: `--action retire` in rolling window retirement call

## 3. tests/test_memory_write.py

### 3.1 `write_input_file` helper (lines 47-53)
- **PASS**: Uses `memory_project / ".claude" / "memory" / ".staging"` -- project-local staging path
- **PASS**: Creates staging dir with `mkdir(parents=True, exist_ok=True)`

### 3.2 All callers pass `memory_project` not `tmp_path`
- **PASS**: All 12 call sites pass `memory_project` as first argument (lines 316, 345, 367, 404, 420, 438, 467, 836, 919, 936, 963, 1012)
- **PASS**: No callers pass `tmp_path` to `write_input_file`

### 3.3 All retire calls use correct action string
- **PASS**: `run_write("retire", ...)` at lines 494, 514, 516, 525, 647, 798, 817
- **PASS**: Zero instances of `run_write("delete", ...)`

### 3.4 All error assertions use RETIRE_ERROR
- **PASS**: `assert "RETIRE_ERROR"` at lines 530, 822
- **PASS**: Zero instances of `assert "DELETE_ERROR"`

### 3.5 Class and method naming
- **PASS**: `TestRetireFlow` class (line 478) -- correctly named
- **PASS**: Method names: `test_retire_retires`, `test_retire_idempotent`, `test_retire_nonexistent`

## 4. tests/test_arch_fixes.py

### 4.1 All 5 input file locations use .staging/ inside proj
- **PASS**: Line 334-336: `staging = proj / ".claude" / "memory" / ".staging"` -> `input_file = str(staging / "input.json")`
- **PASS**: Line 659-661: Same pattern
- **PASS**: Line 827-829: Same pattern
- **PASS**: Line 943-945: Same pattern
- **PASS**: Line 967-969: Same pattern
- **PASS**: All use `proj` (project directory), not `tmp_path` directly

## 5. commands/memory.md

- **PASS**: Line 15: "Soft-retire a memory" in examples section
- **PASS**: Line 52: `--action retire --target <path> --reason "User-initiated retirement via /memory --retire"`
- **PASS**: No instances of `--action delete`

## 6. README.md

- **PASS**: Line 125: "Soft-retired; preserved for 30-day grace period" in lifecycle table
- **PASS**: Line 129: "auto-capture DELETE" -- internal CUD label preserved (refers to the CUD decision, not the CLI action)
- **PASS**: Line 141: `/memory --retire <slug>` in commands table
- **PASS**: Actions in commands table: retire, archive, unarchive, restore -- no "delete"

## 7. CLAUDE.md

- **PASS**: Line 24: "`retire` action sets `record_status=\"retired\"` (soft retire with grace period)"
- **PASS**: Line 24: "6 actions: `create`, `update`, `retire` (soft retire), `archive`, `unarchive`, and `restore`"
- **PASS**: Line 43: "Schema-enforced CRUD + lifecycle (retire/archive/unarchive/restore)" in Key Files table
- **PASS**: Line 76: "memory_write.py -- create/update/retire operations" in test list

## 8. hooks/scripts/memory_write_guard.py

- **PASS**: Line 78: Error message lists `<create|update|retire|archive|unarchive|restore>` -- full action list with `retire` not `delete`

## 9. Config files

### 9.1 assets/memory-config.default.json
- **PASS**: `delete.grace_period_days: 30` -- config key unchanged (refers to deletion policy, not CLI action)
- **PASS**: `delete.archive_retired: true` -- config key unchanged

### 9.2 CLAUDE.md config references
- **PASS**: `delete.grace_period_days` documented correctly
- **PASS**: `delete.archive_retired` documented correctly

## 10. Test Results

- **ALL 435 tests pass** (10 xpassed from pre-existing xfail markers for pre-fix tests that now pass)
- **Compile checks pass** for all 3 changed scripts (memory_write.py, memory_triage.py, memory_write_guard.py)
- **Zero stale references** to `--action delete`, `do_delete`, or `DELETE_ERROR` in any production file

## Summary

| Category | Status | Details |
|----------|--------|---------|
| Change 1: rename --action delete to --action retire | **PASS** | Complete across all 7 files |
| Change 2: _read_input() staging-only restriction | **PASS** | Security enforcement + defense-in-depth |
| Test fixture fix: write_input_file uses .staging/ | **PASS** | All 12 callers pass memory_project |
| test_arch_fixes.py: input files in .staging/ | **PASS** | All 5 locations correct |
| CUD labels preserved (UPDATE_OR_DELETE, DELETE) | **PASS** | Internal labels unchanged |
| Config keys unchanged (delete.grace_period_days) | **PASS** | Policy keys unaffected |
| Full test suite | **PASS** | 435 passed, 0 failed |
| Compile checks | **PASS** | All scripts compile clean |

**VERDICT: ALL CHANGES ARE CORRECT AND COMPLETE. NO ISSUES FOUND.**
