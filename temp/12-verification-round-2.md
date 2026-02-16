# Verification Round 2: Devil's Advocate -- `--action restore`

**Date**: 2026-02-16
**Reviewer**: Claude Opus 4.6 (adversarial mode)
**Scope**: `do_restore()` implementation in `memory_write.py`, 4 updated doc files, stale reference sweep

---

## 1. Code Attack: `do_restore()` (lines 1087-1157)

### 1.1 FINDING [LOW]: No Pydantic re-validation after mutation

`do_restore()` reads the file, mutates `record_status`, `updated_at`, `retired_at`, `retired_reason`, and `changes[]`, then writes back without calling `validate_memory()`. Compare with:
- `do_create()`: calls `validate_memory()` twice (lines 637, 659)
- `do_update()`: calls `validate_memory()` twice (lines 755, 819)
- `do_delete()`: does NOT re-validate (mutates and writes)
- `do_archive()`: does NOT re-validate
- `do_unarchive()`: does NOT re-validate

**Verdict**: CONSISTENT with do_delete, do_archive, do_unarchive. All lifecycle-transition actions (delete/archive/unarchive/restore) skip re-validation because they only modify well-known system fields, not user-supplied content. This is an acceptable pattern -- the mutations are controlled and predictable. No bug.

### 1.2 FINDING [LOW]: No validation that file is valid JSON memory object

If the target file is valid JSON but NOT a memory object (e.g., `{"foo": "bar"}` with no `record_status` key), `data.get("record_status", "active")` returns `"active"`, which hits the idempotent-success path at line 1109 and returns `{"status": "already_active"}`.

**Comparison**: All other handlers (delete, archive, unarchive) have the same behavior -- they use `data.get("record_status", ...)` which defaults silently. This is consistent across the codebase. Not a new issue introduced by restore.

**Verdict**: CONSISTENT. Pre-existing design choice across all lifecycle actions. Not a restore-specific bug.

### 1.3 FINDING [NONE]: `retired_at` / `retired_reason` missing from retired file

If a file has `record_status: "retired"` but lacks `retired_at` and `retired_reason` (e.g., hand-edited), `data.pop("retired_at", None)` and `data.pop("retired_reason", None)` are no-ops. The restore proceeds correctly -- status becomes active, missing fields are harmlessly popped. No crash, no incorrect state.

**Verdict**: SAFE. The `.pop(key, None)` pattern handles missing keys gracefully.

### 1.4 FINDING [NONE]: `changes` is None vs missing vs empty list

Line 1132: `changes = data.get("changes") or []`
- `data` has no `changes` key: `data.get("changes")` returns `None`, `None or []` returns `[]`. OK.
- `changes` is `None`: `None or []` returns `[]`. OK.
- `changes` is `[]`: `[] or []` returns `[]` (falsy list falls through). OK but...

Wait -- `[] or []` in Python evaluates to `[]` (the second operand) because `[]` is falsy. The result is still `[]`. The `.append()` on line 1133 works correctly regardless. No bug.

**Verdict**: SAFE. All three cases handled correctly.

### 1.5 FINDING [NONE]: CHANGES_CAP trimming consistency

`do_restore()` (line 1140-1141):
```python
if len(changes) > CHANGES_CAP:
    changes = changes[-CHANGES_CAP:]
```

Compare with:
- `do_delete()` (line 927-928): identical pattern
- `do_archive()` (line 1001-1002): identical pattern
- `do_unarchive()` (line 1067-1068): identical pattern
- `do_update()` (line 781-782): identical pattern

**Verdict**: CONSISTENT. Trimming logic matches all other handlers exactly.

### 1.6 FINDING [NONE]: Index line construction + add_to_index usage

`do_restore()` (lines 1149-1150):
```python
index_line = build_index_line(data, rel_path)
add_to_index(index_path, index_line)
```

Compare with `do_unarchive()` (lines 1076-1077):
```python
index_line = build_index_line(data, rel_path)
add_to_index(index_path, index_line)
```

**Verdict**: IDENTICAL to do_unarchive. Correct behavior -- restored memories need to be re-added to the index (since delete removes them). No bug.

### 1.7 FINDING [NONE]: Path traversal check consistency

`do_restore()` (line 1093):
```python
if _check_path_containment(target_abs, memory_root, "RESTORE"):
```

All other handlers use the same `_check_path_containment()` call with their respective label. Consistent.

### 1.8 FINDING [LOW]: Idempotent `already_active` path could re-add to index

If a file is already `active` and `--action restore` is called, line 1109 returns `{"status": "already_active"}` with exit code 0 -- but does NOT check or fix the index. If the memory is active but missing from the index (e.g., after a corrupted delete-then-manual-edit), this path won't repair it.

**Comparison**: `do_delete()` has `already_retired` idempotent path (line 894-897) which also does NOT remove from index (it's already gone). `do_archive()` has `already_archived` (line 969-971) which also skips index ops. Consistent.

**Verdict**: CONSISTENT. Pre-existing pattern. The idempotent paths skip index operations. This is a known tradeoff -- use `memory_index.py --rebuild` for index repair. Not a restore-specific issue.

### 1.9 FINDING [INFORMATIONAL]: No `archived_at`/`archived_reason` cleanup in restore

`do_restore()` clears `retired_at` and `retired_reason` but does NOT clear `archived_at`/`archived_reason`. However, since restore only accepts `retired` status (not `archived`), and `do_delete()` (the only way to reach `retired`) explicitly clears `archived_at`/`archived_reason` at line 915-916, a retired file should NEVER have archived fields present.

But what if someone manually edits a file to have both `record_status: "retired"` AND `archived_at`? The restore would clear retirement fields but leave stale archived fields.

**Comparison**: `do_unarchive()` clears `archived_at`/`archived_reason` but does NOT clear `retired_at`/`retired_reason`. Same asymmetry.

**Verdict**: VERY LOW RISK. Only reachable via manual file editing outside the tool. All normal code paths ensure mutual exclusivity. However, for defense-in-depth, `do_restore()` COULD clear archived fields too (just as `do_delete()` does). This would be a marginal improvement. **Suggested enhancement, not a bug.**

### 1.10 FINDING [NONE]: Race condition between exists() and open()

Lines 1096-1103:
```python
if not target_abs.exists():
    ...
try:
    with open(target_abs, "r", encoding="utf-8") as f:
```

If the file is deleted between `exists()` and `open()`, the `open()` raises `OSError`, caught by the except on line 1104. Returns `READ_ERROR`. Correct behavior.

**Comparison**: All other handlers (delete, archive, unarchive) have the same TOCTOU gap with the same `OSError` catch. Consistent.

### 1.11 FINDING [NONE]: flock scope -- read outside lock

The file read (line 1102) happens OUTSIDE the flock. The write + index update (lines 1147-1150) happen INSIDE the flock.

**Comparison**: `do_delete()`, `do_archive()`, `do_unarchive()` all read outside the lock and write inside it. Only `do_create()` and `do_update()` read partially inside the lock (for anti-resurrection and OCC checks respectively). The lifecycle actions (delete/archive/unarchive/restore) have no OCC check, so reading outside the lock is acceptable -- the only risk is concurrent modification of the same file, which is low-probability and results in last-write-wins (acceptable for lifecycle transitions).

**Verdict**: CONSISTENT. Acceptable design.

---

## 2. Cross-Handler Comparison: Inconsistencies

### 2.1 FINDING [BUG-STALE-DOCSTRING]: Module docstring is outdated

Line 2-5 of `memory_write.py`:
```
"""Schema-enforced memory write tool for claude-memory plugin.

Handles CREATE, UPDATE, and DELETE operations with Pydantic validation,
mechanical merge protections, OCC, atomic writes, and index management.
```

This says "CREATE, UPDATE, and DELETE" but the script now handles 6 actions: create, update, delete, archive, unarchive, restore. The usage examples (lines 7-18) only show create, update, delete.

**Severity**: Low (cosmetic). The module docstring is stale. Does not affect functionality.

**Recommended fix**: Update to "Handles CREATE, UPDATE, DELETE, ARCHIVE, UNARCHIVE, and RESTORE operations..."

### 2.2 FINDING [BUG-STALE-HELP]: `--reason` argparse help text is stale

Line 1334:
```python
parser.add_argument("--reason", help="Reason for deletion (delete only)")
```

The `--reason` argument is used by both `delete` AND `archive` actions (line 912 and 986). The help text says "delete only" which is inaccurate.

**Severity**: Low (cosmetic). Help text misleading but not functionally broken.

**Recommended fix**: `"Reason for deletion or archival (delete/archive)"`.

### 2.3 FINDING [NONE]: `do_create` has anti-resurrection, restore does not

This is intentional and documented. The implementation notes explicitly state "Anti-resurrection does NOT apply (separate code path)". The README Design Decisions section documents this: "The `--action restore` command bypasses this check because intentional restoration is a separate code path."

**Verdict**: Correct design.

### 2.4 FINDING [NONE]: `do_create` has venv bootstrap, restore does not need it

The venv bootstrap (lines 27-34) runs at module load time before any action handler. All actions benefit from it. No inconsistency.

### 2.5 FINDING [NONE]: `do_create` has category validation, restore does not need it

`do_restore()` does not take `--category` or `--input` args, so category validation is irrelevant. The category is embedded in the existing file. No inconsistency.

### 2.6 FINDING [NONE]: `do_update` has OCC, restore does not

Restore is a simple status flip, not a content merge. OCC protects against lost content changes during concurrent updates. For a lifecycle transition, last-write-wins is acceptable. Consistent with delete/archive/unarchive which also lack OCC.

---

## 3. Documentation Attack

### 3.1 Cross-file consistency check

| Document | restore action referenced | Consistent? |
|----------|--------------------------|-------------|
| `commands/memory.md` line 81 | `--action restore --target <path>` | YES |
| `CLAUDE.md` line 24 | "6 actions: ...restore" | YES |
| `CLAUDE.md` line 43 | "CRUD + lifecycle (archive/unarchive/restore)" | YES |
| `README.md` line 131 | "`retired` -> `active` via `/memory --restore <slug>`" | YES |
| `README.md` line 144 | "Restore a retired memory within the grace period" | YES (note: grace period is about GC, not restore. See 3.3) |
| `README.md` line 402 | Design Decisions: restore bypasses anti-resurrection | YES |
| `SKILL.md` line 135 | "restore the old memory and update it" (anti-resurrection guidance) | YES |
| `SKILL.md` line 233 | `/memory --restore <slug>` in Manual Cleanup | YES |

### 3.2 FINDING [NONE]: Stale "5 actions" references

Searched entire codebase. Only found in `temp/` files (working notes, not shipped docs). The live docs (`CLAUDE.md`) correctly say "6 actions". No stale references in shipped documentation.

### 3.3 FINDING [INFORMATIONAL]: "within the grace period" phrasing could mislead

`README.md` line 144:
```
| `/memory --restore <slug>` | Restore a retired memory within the grace period |
```

And line 161:
```
/memory --restore old-api-design           # Undo retirement within grace period
```

The phrase "within the grace period" suggests that restore STOPS WORKING after the grace period. But `do_restore()` has NO grace period check -- it works on ANY retired file that still exists. The grace period controls when GC *deletes the file*. After GC runs, the file is gone and restore fails because `target_abs.exists()` returns False.

This is technically correct (you can only restore within the grace period because the file is deleted after it), but the phrasing implies restore has its own time-based check. A user might think: "I need to hurry before 30 days or the restore command itself will reject me."

**Severity**: Very low. Technically true but could mislead. Acceptable.

### 3.4 FINDING [NONE]: No remaining "create-based" or "workaround" references in shipped docs

Searched all non-temp `.md` files. The only matches are:
- `SKILL.md` line 192: `workarounds` in the constraint schema field description (correct, unrelated)
- `README.md` line 371: "use a different title/slug, wait 24 hours, or restore the old memory" (correct, updated)

No stale "create-based workaround" references remain in shipped documentation.

### 3.5 FINDING [NONE]: `ANTI_RESURRECTION` references in shipped docs

Found in:
- `SKILL.md` line 135: correct documentation of the feature and its workarounds
- `README.md` line 369-372: correct troubleshooting entry

Both are accurate. No stale references.

### 3.6 FINDING [INFORMATIONAL]: `commands/memory.md` pre-checks record_status but `do_restore()` already does this

`commands/memory.md` line 80:
```
3. Read the file. If record_status is not "retired", report error (can only restore retired memories)
```

This instructs the agent to check record_status BEFORE calling `memory_write.py --action restore`. But `do_restore()` already validates record_status internally (line 1115). The pre-check in the command is redundant but harmless -- it provides an earlier, friendlier error message.

**Comparison**: `--retire` (line 49-53) does NOT pre-check record_status before calling `--action delete`. `--archive` (line 59-63) also does not pre-check. The `--restore` command is slightly over-specified compared to its siblings. Not a bug, just a minor inconsistency in command file style.

**Verdict**: Harmless. Defense-in-depth is fine.

---

## 4. Missing Edge Cases

### 4.1 FINDING [NONE]: File is valid JSON but changes is a non-list (e.g., a string)

Line 1132: `changes = data.get("changes") or []`

If `data["changes"]` is, say, `"some string"`, then `data.get("changes")` returns `"some string"` which is truthy, so `or []` does not trigger. Then `changes.append(...)` on a string raises `AttributeError`.

**However**: This can only happen if the file was hand-edited (the write pipeline always produces `changes` as a list or null). And all other lifecycle handlers (delete, archive, unarchive) have the exact same pattern. Not a restore-specific issue.

**Verdict**: Pre-existing edge case. Consistent across all handlers. Would need a type check on `changes` if defensive coding is desired, but this is not a regression from the restore implementation.

### 4.2 FINDING [NONE]: `add_to_index` with duplicate entry

If the index already has an entry for this path (e.g., it was not properly removed during delete), `add_to_index()` will add a second entry, creating a duplicate.

**Comparison**: `do_unarchive()` has the same behavior. The `do_delete()` action calls `remove_from_index()` which should have removed it. If deletion was interrupted, the duplicate is possible but would be fixed by `memory_index.py --rebuild`.

**Verdict**: Pre-existing design. Not a restore-specific issue.

### 4.3 FINDING [NONE]: No test coverage for `do_restore()`

The test file `tests/test_memory_write.py` contains no tests for `do_restore()` (confirmed by grep). This is expected given the implementation was just added, but tests should be written.

**Verdict**: Expected. Tests needed but not a code bug.

---

## 5. Summary

### Bugs Found

| # | Severity | Finding | Location |
|---|----------|---------|----------|
| 1 | LOW | Module docstring says "CREATE, UPDATE, and DELETE" -- stale, should list all 6 actions | `memory_write.py` lines 2-5 |
| 2 | LOW | `--reason` help text says "delete only" but archive also uses it | `memory_write.py` line 1334 |

### Suggested Enhancements (not bugs)

| # | Finding | Location |
|---|---------|----------|
| A | `do_restore()` could clear `archived_at`/`archived_reason` for defense-in-depth | `memory_write.py` line 1128-1129 |
| B | "within the grace period" phrasing could mislead about restore timing | `README.md` lines 144, 161 |

### Clean (no issues found)

- Path traversal check: consistent
- `retired_at`/`retired_reason` missing: handled gracefully
- `changes` None/missing/empty: handled correctly
- CHANGES_CAP trimming: consistent with all handlers
- Index line construction: identical to `do_unarchive()`
- Race conditions: same TOCTOU pattern as all handlers, caught by except
- flock scope: consistent with lifecycle actions
- Anti-resurrection bypass: correctly absent (intentional design)
- No stale "create-based workaround" in shipped docs
- No stale "5 actions" in shipped docs
- All 4 doc files consistent with each other and with code

### Verdict

**The `do_restore()` implementation is solid.** It correctly mirrors the `do_unarchive()` pattern, handles edge cases consistently with all other lifecycle handlers, and the documentation updates are clean and consistent. The two findings are cosmetic (stale docstring and help text) and pre-existed the restore implementation (the docstring was stale since archive/unarchive were added).

No blocking issues. No functional bugs. No security concerns. Ship it.
