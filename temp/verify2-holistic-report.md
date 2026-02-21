# Verification Round 2: Holistic Quality Review

**Reviewer**: verify2-holistic
**Date**: 2026-02-18
**Scope**: End-to-end review of all changed files for the rename `--action delete` to `--action retire` + `_read_input()` staging-only restriction

---

## 1. hooks/scripts/memory_write.py

### 1.1 do_retire function (lines 873-945)
- **PASS**: Function is named `do_retire`, docstring says `"""Handle --action retire (soft retire)."""`
- **PASS**: Complete and correct -- reads existing file, checks already-retired (idempotent), blocks archived->retired (must unarchive first), sets retirement fields, adds change entry, writes atomically under flock, removes from index
- **PASS**: Error prefix is `RETIRE_ERROR` (not `DELETE_ERROR`)
- **PASS**: Function is fully self-contained and correct as a "retire" not "delete" operation

### 1.2 _read_input() (lines 1165-1205)
- **PASS**: Validates `".." in input_path` -- rejects traversal
- **PASS**: Validates `"/.claude/memory/.staging/" in resolved` -- only allows staging directory
- **PASS**: Returns `None` on any violation (fails closed)
- **PASS**: Error messages reference `.claude/memory/.staging/`

### 1.3 _cleanup_input() (lines 1208-1213)
- **PASS**: UNCHANGED -- still just `os.unlink(input_path)` with `OSError` catch. No staging validation here (by design: cleanup only runs after _read_input succeeds).

### 1.4 Rename flow comment (line 843)
- **PASS**: `# Rename flow: write new, update index, delete old` -- preserved exactly. This is internal file operation terminology, not the user-facing action name.

### 1.5 Argparse choices (line 1334)
- **PASS**: `choices=["create", "update", "retire", "archive", "unarchive", "restore"]` -- no "delete"

### 1.6 Dispatch block (lines 1364-1375)
- **PASS**: `elif args.action == "retire": return do_retire(args, memory_root, index_path)` -- correctly dispatches to do_retire

### 1.7 Module docstring (lines 2-6)
- **PASS**: Says "CREATE, UPDATE, RETIRE, ARCHIVE, UNARCHIVE, and RESTORE" -- no mention of DELETE

### 1.8 Usage examples (lines 8-19)
- **PASS**: Shows `--action retire` in the usage docstring

### 1.9 No residual delete references
- **PASS**: Grep for `"delete"`, `do_delete`, `DELETE_ERROR`, `--action delete` in memory_write.py returned ZERO matches

---

## 2. skills/memory-management/SKILL.md

### 2.1 UPDATE_OR_DELETE (internal CUD label)
- **PASS**: Appears 6 times at lines 90, 91, 95, 155, 156, 159 -- all in the CUD verification table and subagent instruction context. These are correct internal labels for the candidate selection system.

### 2.2 DELETE in CUD decision table
- **PASS**: Present in the CUD verification table (lines 155-160) as internal resolution labels. These are NOT CLI action names -- they are internal decision labels that the CUD system uses. The mapping is: internal DELETE -> CLI `--action retire`.

### 2.3 "UPDATE over DELETE" principle
- **PASS**: Appears at line 96 ("Prefer UPDATE over DELETE") and line 167 ("Safety defaults: UPDATE over DELETE"). These are correct CUD policy labels.

### 2.4 --action retire in CLI invocations
- **PASS**: Line 100: `"action": "retire"` in DELETE draft JSON
- **PASS**: Line 130: `--action retire --target <path> --reason "<why>"` in Phase 3 save
- **PASS**: Line 218 (session rolling window): references `--action retire`
- **PASS**: No `--action delete` in any CLI invocation

### 2.5 Correct semantic separation
- **PASS**: The SKILL.md correctly maintains the separation between:
  - Internal CUD labels: CREATE, UPDATE, DELETE, UPDATE_OR_DELETE (decision system)
  - External CLI actions: `--action create`, `--action update`, `--action retire` (execution)

---

## 3. commands/memory.md

### 3.1 Line 15
- **PASS**: `"/memory --retire old-api-design  # Soft-retire a memory"` -- correct

### 3.2 --retire subcommand section (lines 45-54)
- **PASS**: `## --retire <slug>` heading
- **PASS**: Line 52: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action retire --target <path> --reason "User-initiated retirement via /memory --retire"`
- **PASS**: Description says "User-initiated soft delete" -- appropriate human-readable description

---

## 4. README.md

### 4.1 Line 125 (Memory Lifecycle table)
- **PASS**: `| \`retired\` | No | No | Yes (after grace period) | Soft-retired; preserved for 30-day grace period |`

### 4.2 Line 129 (State transitions)
- **PASS**: `\`active\` -> \`retired\` via \`/memory --retire <slug>\` or auto-capture DELETE` -- "auto-capture DELETE" is the internal CUD label, correctly preserved

### 4.3 Actions list
- **PASS**: Line 141: `/memory --retire <slug>` with description "Soft-retire a memory (30-day grace period)"
- **PASS**: No `--action delete` in any CLI context

### 4.4 Architecture diagram (line 253)
- **PASS**: `memory_write.py --action create/update/retire/archive/unarchive` -- lists retire, not delete

---

## 5. Other Files

### 5.1 CLAUDE.md
- **PASS**: Write Actions section (line 24): "supports 6 actions: `create`, `update`, `retire` (soft retire), `archive`, `unarchive`, and `restore`"
- **PASS**: Key Files table (line 43): "Schema-enforced CRUD + lifecycle (retire/archive/unarchive/restore)"
- **PASS**: No `--action delete` in the file

### 5.2 hooks/scripts/memory_write_guard.py
- **PASS**: Line 78: Error message action list reads `"<create|update|retire|archive|unarchive|restore>"` -- correct, no "delete"

### 5.3 tests/test_memory_write.py
- **PASS**: `TestRetireFlow` class (lines 476-528) -- all tests use `"retire"` action
- **PASS**: `run_write("retire", ...)` calls throughout
- **PASS**: Checks for `RETIRE_ERROR` in error tests
- **PASS**: `TestRetireArchiveInteraction` class tests retire/archive interactions correctly
- **PASS**: No references to `"delete"` as a CLI action or `do_delete` function

### 5.4 tests/conftest.py
- **PASS**: Memory factory functions support `record_status="retired"` and `retired_at` parameters
- **PASS**: No references to `--action delete`

---

## 6. Config Integrity

### 6.1 assets/memory-config.default.json
- **PASS**: `"delete": { "grace_period_days": 30, "archive_retired": true }` -- config key names unchanged (these are config keys, not CLI action names; "delete" here refers to the conceptual deletion policy, not the CLI command)

### 6.2 CLAUDE.md Config Architecture
- **PASS**: References `delete.grace_period_days` and `delete.archive_retired` as script-read and agent-interpreted config keys respectively -- unchanged

### 6.3 SKILL.md Config section
- **PASS**: Lines 271-272: `delete.grace_period_days` and `delete.archive_retired` documented correctly

---

## 7. Cross-Cutting Concerns

### 7.1 _read_input() security hardening
The new `_read_input()` implementation (lines 1165-1205):
- Rejects paths containing `..`
- Only accepts paths where `resolved` contains `/.claude/memory/.staging/`
- Uses `os.path.realpath()` to resolve symlinks before checking
- Error messages are informative without leaking internal paths

**Potential edge case**: The `".." in input_path` check is on the raw string, while the staging check is on the resolved path. A symlink from `.staging/foo` pointing outside would be caught by the staging check on the resolved path. This is correct defense-in-depth.

### 7.2 Consistency of error prefixes
- `do_create`: No custom error prefix (uses validation errors)
- `do_update`: `UPDATE_ERROR`, `OCC_CONFLICT`, `MERGE_ERROR`
- `do_retire`: `RETIRE_ERROR` (was `DELETE_ERROR`)
- `do_archive`: `ARCHIVE_ERROR`
- `do_unarchive`: `UNARCHIVE_ERROR`
- `do_restore`: `RESTORE_ERROR`

All consistent, no stale DELETE_ERROR references.

### 7.3 Internal vs external terminology
The codebase correctly separates:
- **Internal CUD labels** (DELETE, UPDATE_OR_DELETE) -- used in candidate selection logic, CUD resolution tables, and SKILL.md subagent instructions
- **External CLI actions** (--action retire) -- used in all user-facing commands and script invocations
- **Config keys** (delete.grace_period_days) -- config namespace, not CLI action names

This separation is intentional and correct.

---

## Summary

| Area | Status | Issues |
|------|--------|--------|
| memory_write.py (do_retire) | PASS | 0 |
| memory_write.py (_read_input) | PASS | 0 |
| memory_write.py (_cleanup_input) | PASS | 0 (unchanged) |
| memory_write.py (argparse/dispatch) | PASS | 0 |
| SKILL.md (UPDATE_OR_DELETE labels) | PASS | 0 |
| SKILL.md (CLI invocations) | PASS | 0 |
| SKILL.md (UPDATE over DELETE principle) | PASS | 0 |
| commands/memory.md | PASS | 0 |
| README.md (lifecycle table) | PASS | 0 |
| README.md (state transitions) | PASS | 0 |
| CLAUDE.md | PASS | 0 |
| memory_write_guard.py | PASS | 0 |
| tests/test_memory_write.py | PASS | 0 |
| Config integrity | PASS | 0 |
| Cross-cutting consistency | PASS | 0 |

**Overall verdict: ALL CHECKS PASS. No issues found.**

The rename from `--action delete` to `--action retire` is complete and consistent across all production files. Internal CUD labels (DELETE, UPDATE_OR_DELETE) are correctly preserved as they serve a different purpose. The `_read_input()` staging-only restriction is properly implemented with defense-in-depth. Config keys (`delete.*`) are correctly unchanged as they refer to deletion policy, not CLI actions.
