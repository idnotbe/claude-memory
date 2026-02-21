# Verification Round 1: Cross-File Consistency Report

**Reviewer:** verify1-consistency
**Date:** 2026-02-18
**Scope:** Stale reference scan, action terminology, function/dispatch alignment, test alignment

---

## 1. Stale Reference Scan

### 1.1 `--action delete` in *.py, *.md, *.json (excluding temp/ and MEMORY-CONSOLIDATION-PROPOSAL.md)

**Result: ZERO matches in runtime/doc files. PASS.**

All matches are confined to:
- `temp/` working files (historical/planning documents, not runtime)
- `MEMORY-CONSOLIDATION-PROPOSAL.md` (historical proposal, not runtime)

No stale `--action delete` references exist in any active source file.

### 1.2 `DELETE_ERROR` in *.py files

**Result: ZERO matches. PASS.**

### 1.3 `do_delete` in *.py files

**Result: ZERO matches. PASS.**

### 1.4 `"delete"` as an argparse choice in *.py files

**Result: ZERO matches in argparse choices. PASS.**

The only `"delete"` string matches in Python files are:
- `hooks/scripts/memory_index.py:203` -- `config.get("delete", {}).get("grace_period_days", 30)` -- This is a **config key**, not a CLI action. Correct to keep as-is.
- `tests/test_memory_index.py:204` -- `config = {"delete": {"grace_period_days": 7}}` -- Test fixture for the config key above. Correct.

Neither is an argparse choice. The only argparse `choices` definition is in `memory_write.py:1334`:
```python
choices=["create", "update", "retire", "archive", "unarchive", "restore"]
```
This is correct.

### 1.5 `Soft-delete` in *.md files (excluding temp/ and MEMORY-CONSOLIDATION-PROPOSAL.md)

**Result: 2 FINDINGS in active files.**

| File | Line | Content | Severity |
|------|------|---------|----------|
| `commands/memory.md` | 15 | `/memory --retire old-api-design  # Soft-delete a memory` | **MEDIUM** -- should be "Soft-retire" |
| `README.md` | 125 | `Soft-deleted; preserved for 30-day grace period` | **LOW** -- describes the retired state behavior, not the CLI action; arguably acceptable |

**Assessment:**
- `commands/memory.md:15` -- The comment says "Soft-delete" but the action is `--retire`. Should be updated to "Soft-retire a memory" for consistency.
- `README.md:125` -- The table cell describes what "retired" status means ("Soft-deleted"). This is a description of the state's effect, not the CLI action name. It was deliberately left as-is per `temp/impl-docs-report.md:56`. Acceptable but could be "Soft-retired" for full consistency.

---

## 2. Action Terminology Consistency

### Expected 6 actions: create, update, retire, archive, unarchive, restore

| File | Actions Listed | Match? | Notes |
|------|---------------|--------|-------|
| `memory_write.py` argparse (line 1334) | create, update, retire, archive, unarchive, restore | **YES** | |
| `memory_write_guard.py` error msg (line 78) | `<create\|update\|retire\|archive\|unarchive\|restore>` | **YES** | |
| `CLAUDE.md` Write Actions section (line 24) | create, update, retire (soft retire), archive, unarchive, restore | **YES** | Parenthetical clarifies retire semantics |
| `README.md` State transitions (line 129) | References `auto-capture DELETE` | **FINDING** | See below |
| `SKILL.md` Phase 3 (line 127-130) | create, update, retire | **YES** | Only lists the 3 CUD actions (archive/unarchive/restore are lifecycle, not auto-capture) |
| `SKILL.md` subagent report (line 102) | CREATE/UPDATE/RETIRE/NOOP | **YES** | |

**Finding: README.md line 129:**
```
- `active` -> `retired` via `/memory --retire <slug>` or auto-capture DELETE
```
The phrase "auto-capture DELETE" refers to the conceptual CUD operation (Create/Update/Delete), not the CLI `--action` name. However, for full consistency, this could be updated to "auto-capture RETIRE" or "auto-capture retirement". **LOW severity** -- the meaning is clear in context and refers to the CUD resolution table label, not the CLI flag.

---

## 3. Function/Dispatch Alignment in memory_write.py

### 3.1 Function `do_retire` exists

**PASS.** Defined at line 873:
```python
def do_retire(args, memory_root: Path, index_path: Path) -> int:
    """Handle --action retire (soft retire)."""
```

### 3.2 Dispatch block calls `do_retire` for action=="retire"

**PASS.** Lines 1368-1369:
```python
elif args.action == "retire":
    return do_retire(args, memory_root, index_path)
```

### 3.3 No remaining references to `do_delete`

**PASS.** Grep for `do_delete` across all *.py files returned ZERO matches.

### 3.4 Complete dispatch table

| Action | Handler | Verified |
|--------|---------|----------|
| create | `do_create` (line 1364-1365) | YES |
| update | `do_update` (line 1366-1367) | YES |
| retire | `do_retire` (line 1368-1369) | YES |
| archive | `do_archive` (line 1370-1371) | YES |
| unarchive | `do_unarchive` (line 1372-1373) | YES |
| restore | `do_restore` (line 1374-1375) | YES |

All 6 actions have matching handler functions and correct dispatch entries. **PASS.**

---

## 4. Test Alignment in tests/test_memory_write.py

### 4.1 All `run_write` calls use "retire" not "delete"

**PASS.** Verified all `run_write` calls in the file:
- `TestRetireFlow.test_retire_retires` (line 492-494): `run_write("retire", ...)`
- `TestRetireFlow.test_retire_idempotent` (line 512): `run_write("retire", ...)`
- `TestRetireFlow.test_retire_nonexistent` (line 523-525): `run_write("retire", ...)`
- `TestRetireArchiveInteraction.test_retire_clears_archived_fields` (line 796-798): `run_write("retire", ...)`
- `TestRetireArchiveInteraction.test_archived_to_retired_blocked` (line 815-817): `run_write("retire", ...)`
- `TestPathTraversal.test_path_traversal_retire_blocked` (line 845-847): `run_write("retire", ...)`
- `TestArchiveFlow.test_archive_retired_memory_fails` (line 645): `run_write("retire", ...)`

No instances of `run_write("delete", ...)` found. **PASS.**

### 4.2 All error assertions use "RETIRE_ERROR" not "DELETE_ERROR"

**PASS.** Line 528: `assert "RETIRE_ERROR" in stdout`
No instances of `"DELETE_ERROR"` in any test file. **PASS.**

### 4.3 Class/method names updated

**PASS.** Test class is `TestRetireFlow` (line 476), not `TestDeleteFlow`. Methods are `test_retire_*` not `test_delete_*`.

---

## 5. Additional Consistency Checks

### 5.1 Config key `delete.*` is preserved (not renamed)

**PASS.** The config keys `delete.grace_period_days` and `delete.archive_retired` are configuration namespace keys, not CLI action names. They are correctly preserved across all files:
- `CLAUDE.md:58` -- listed as script-read config key
- `README.md:183` -- documented in config table
- `SKILL.md:271` -- documented in config section
- `hooks/scripts/memory_index.py:203` -- read by gc_retired()
- `tests/test_memory_index.py:204` -- tested

### 5.2 CLAUDE.md Key Files table consistency

**PASS.** The Key Files table (CLAUDE.md lines 37-45) lists:
- `memory_candidate.py` role: "ACE candidate selection for update/delete"

The phrase "update/delete" here refers to the CUD conceptual operation, not the CLI flag. The candidate script outputs `UPDATE_OR_DELETE` as a structural CUD signal. This is correct as-is.

### 5.3 SKILL.md CUD resolution table

**PASS.** The CUD table (SKILL.md lines 152-161) uses DELETE as a CUD resolution label, not a CLI action. Phase 3 (line 130) correctly maps DELETE resolution to `--action retire`:
```
- **DELETE** (soft retire): `python3 ... memory_write.py --action retire --target <path> --reason "<why>"`
```

### 5.4 memory_write.py docstring

**PASS.** Line 4: `Handles CREATE, UPDATE, RETIRE, ARCHIVE, UNARCHIVE, and RESTORE operations`

### 5.5 memory_write.py merge protection error message

**PASS.** Line 501: `"fix: Use --action retire to retire, or --action archive to archive"`

---

## Summary

| Check | Result | Issues |
|-------|--------|--------|
| 1.1 `--action delete` in active files | PASS | 0 |
| 1.2 `DELETE_ERROR` in *.py | PASS | 0 |
| 1.3 `do_delete` in *.py | PASS | 0 |
| 1.4 `"delete"` argparse choice in *.py | PASS | 0 |
| 1.5 `Soft-delete` in active *.md | **2 FINDINGS** | commands/memory.md:15 (MEDIUM), README.md:125 (LOW, deliberate) |
| 2. Action terminology consistency | **1 FINDING** | README.md:129 says "auto-capture DELETE" (LOW, CUD label) |
| 3. Function/dispatch alignment | PASS | 0 |
| 4. Test alignment | PASS | 0 |
| 5. Additional checks | PASS | 0 |

### Total findings: 3 (1 MEDIUM, 2 LOW)

**MEDIUM:**
1. `commands/memory.md:15` -- Comment says "Soft-delete a memory", should say "Soft-retire a memory"

**LOW (acceptable as-is):**
2. `README.md:125` -- Table says "Soft-deleted; preserved for 30-day grace period" (describes state effect, not CLI action; deliberately left per impl-docs decision)
3. `README.md:129` -- Says "auto-capture DELETE" (refers to CUD resolution label, not CLI flag)

### Verdict: **PASS with 1 medium finding**

The rename from `--action delete` to `--action retire` is complete and consistent across all runtime files. The one medium finding (`commands/memory.md:15` comment) is a cosmetic documentation issue that does not affect runtime behavior.
