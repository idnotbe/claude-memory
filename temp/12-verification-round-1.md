# Verification Round 1: --action restore Implementation + Documentation

**Verifier:** Independent review (Opus 4.6)
**Date:** 2026-02-16
**Scope:** Code correctness, structural consistency, documentation accuracy, edge cases

---

## 1. Code Verification: `do_restore()` (lines 1087-1157)

### 1.1 Status Check -- PASS
- Line 1109: `data.get("record_status", "active") == "active"` -- correctly defaults missing field to "active", returns idempotent success.
- Line 1115: `data.get("record_status") != "retired"` -- correctly rejects anything that isn't "retired" (after the idempotent active check above). This catches "archived" status.
- Ordering is correct: idempotent check FIRST, then retired-only gate.

### 1.2 Idempotent Handling -- PASS
- Line 1108-1112: Already-active returns `{"status": "already_active", ...}` with exit code 0.
- Matches `do_delete()` pattern (line 893-897: `"already_retired"`).
- Matches `do_archive()` pattern (line 969-971: `"already_archived"`).
- Matches `do_unarchive()` -- note: `do_unarchive()` does NOT have an idempotent check for already-active. It would fall through to the "Only archived memories can be unarchived" error at line 1043. This is actually a minor asymmetry: `do_restore()` is MORE robust than `do_unarchive()` in handling an already-active memory. Not a bug, but worth noting.

### 1.3 Archived Rejection -- PASS
- Line 1115-1121: When `record_status` is "archived", the retired check fails (since "archived" != "retired").
- Error message at line 1119-1120: `"Use --action unarchive for archived memories."` -- helpful and correct.
- Note: The error message also displays the current `record_status` value (line 1118), which is good for debugging.

### 1.4 Field Clearing -- PASS
- Line 1125: Sets `record_status = "active"`.
- Line 1126: Sets `updated_at = now_utc()`.
- Line 1128: Clears `retired_at` via `.pop()`.
- Line 1129: Clears `retired_reason` via `.pop()`.
- Does NOT clear `archived_at` or `archived_reason`. This is correct because a restored memory was retired (not archived), so those fields should not be present. If they somehow were, they'd be left in place -- acceptable edge case (the memory came from retired state, not archived).

### 1.5 Changes Entry -- PASS
- Lines 1132-1142: Adds change entry with:
  - `date`: now_utc()
  - `summary`: "Restored: returned to active from retired"
  - `field`: "record_status"
  - `old_value`: "retired"
  - `new_value`: "active"
- CHANGES_CAP overflow handled at lines 1140-1141 (FIFO trim).
- Structure matches `do_unarchive()` (lines 1059-1069).

### 1.6 Atomic Write + Flock -- PASS
- Lines 1147-1150: Inside `_flock_index()` context manager.
- `atomic_write_json()` called first (line 1148).
- `build_index_line()` + `add_to_index()` called next (lines 1149-1150).
- Pattern is identical to `do_unarchive()` (lines 1074-1077).

### 1.7 Index Re-addition -- PASS
- Line 1150: `add_to_index(index_path, index_line)` -- correctly re-adds to index.
- This is necessary because `do_delete()` calls `remove_from_index()` (line 936).
- Both `do_restore()` and `do_unarchive()` use `add_to_index()` (not `update_index_entry()`), which is correct for entries that were previously removed.

### 1.8 Path Traversal Check -- PASS
- Lines 1093-1094: `_check_path_containment(target_abs, memory_root, "RESTORE")`.
- Uses "RESTORE" label for error messages.
- Pattern matches all other action handlers.

### 1.9 Argparse Choices -- PASS
- Line 1323: `choices=["create", "update", "delete", "archive", "unarchive", "restore"]` -- "restore" is present.

### 1.10 Routing in main() -- PASS
- Lines 1363-1364: `elif args.action == "restore": return do_restore(args, memory_root, index_path)` -- correctly routed.

### 1.11 Result Output -- PASS
- Lines 1152-1156: Returns `{"status": "restored", "target": str(target)}`.
- Consistent with `do_unarchive()` result format (`{"status": "unarchived", ...}`).

---

## 2. Structural Comparison: `do_restore()` vs `do_unarchive()`

| Aspect | do_restore() | do_unarchive() | Match? |
|--------|-------------|---------------|--------|
| Path traversal check | Yes ("RESTORE") | Yes ("UNARCHIVE") | Yes |
| File existence check | Yes | Yes | Yes |
| File read + error handling | Yes (JSONDecodeError, OSError) | Yes (JSONDecodeError, OSError) | Yes |
| Idempotent handling | Yes ("already_active", exit 0) | No (falls to error) | ASYMMETRY |
| Status gate | retired-only | archived-only | Correct |
| Helpful rejection message | Yes (suggests --action unarchive) | Yes (generic) | Yes |
| Set record_status = active | Yes | Yes | Yes |
| Set updated_at | Yes | Yes | Yes |
| Clear lifecycle fields | retired_at, retired_reason | archived_at, archived_reason | Correct |
| Changes entry | Yes (correct old/new values) | Yes (correct old/new values) | Yes |
| CHANGES_CAP overflow | Yes | Yes | Yes |
| flock on index | Yes | Yes | Yes |
| atomic_write_json | Yes | Yes | Yes |
| add_to_index (re-add) | Yes | Yes | Yes |
| Result JSON | {"status": "restored"} | {"status": "unarchived"} | Yes |

**Asymmetry note:** `do_restore()` has an idempotent check for already-active memories (returns success), but `do_unarchive()` does not -- calling unarchive on an active memory returns an error. This is a minor inconsistency. The `do_restore()` approach is arguably better because it matches the `do_delete()`/`do_archive()` idempotency pattern. However, this is a pre-existing pattern in `do_unarchive()`, not a problem introduced by the restore implementation.

---

## 3. Documentation Verification

### 3.1 commands/memory.md -- PASS
- Lines 74-82: `## --restore <slug>` section uses `--action restore` (line 81).
- Flow is correct: find file, check record_status, call `memory_write.py --action restore`.
- Clean and concise (5 steps).
- No workaround language, no manual JSON editing.

### 3.2 README.md -- PASS
- **State transitions (lines 128-133):** Clean, no workaround note.
  - `retired` -> `active` via `/memory --restore <slug>` -- correct.
  - All 4 transitions listed symmetrically.
- **Commands table (lines 138-149):** Includes `/memory --restore <slug>` with description "Restore a retired memory within the grace period" (line 144). Correct.
- **Examples section (line 161):** Shows `--restore` usage. Correct.
- **Design Decisions (lines 400-403):**
  - Anti-resurrection documented as intentional safety feature. Correct framing.
  - Mentions that `--action restore` bypasses the anti-resurrection check. Accurate (restore doesn't go through create path).
  - Agent-interpreted config keys documented as intentional architecture. Correct.
- **Known Limitations (lines 398-399):** Only mentions custom categories. Does NOT mention restore or agent-interpreted keys. Correct -- these were moved to Design Decisions.

### 3.3 CLAUDE.md -- PASS
- Line 24: "6 actions: `create`, `update`, `delete` (soft retire), `archive`, `unarchive`, and `restore`" -- correct count and listing.
- Line 24: Restore description: "transitions `retired` -> `active` (clears retirement fields, re-adds to index)" -- accurate.
- Line 43: Key Files table, memory_write.py role: "Schema-enforced CRUD + lifecycle (archive/unarchive/restore)" -- includes restore. Correct.

### 3.4 skills/memory-management/SKILL.md -- PASS
- Line 233: `/memory --restore <slug>` -- restore a retired session to active status. Clean description, no workaround note.
- The SKILL.md does not contain extensive restore documentation (appropriate -- restore is a user-facing lifecycle command, not part of the 4-phase auto-capture flow).

---

## 4. Edge Case Analysis

### 4.1 No record_status field -- PASS (Idempotent success)
- Line 1109: `data.get("record_status", "active") == "active"` -- defaults to "active".
- Returns `{"status": "already_active"}` with exit code 0.
- This is the correct behavior: a memory with no record_status is treated as active.

### 4.2 Archived memory -- PASS (Rejected with helpful message)
- Line 1109: "archived" != "active" -- not idempotent.
- Line 1115: "archived" != "retired" -- triggers error.
- Error at lines 1116-1121: "Only retired memories can be restored. Use --action unarchive for archived memories." -- correct and helpful.

### 4.3 File does not exist -- PASS
- Line 1096-1097: Returns `RESTORE_ERROR` with "File does not exist."
- Mirrors all other action handlers.

### 4.4 Invalid JSON in file -- PASS
- Lines 1103-1105: Catches `json.JSONDecodeError` and `OSError`, returns `READ_ERROR`.
- Pattern matches all other handlers.

### 4.5 Compile check -- PASS
- Ran `python3 -m py_compile hooks/scripts/memory_write.py` -- clean compilation, no errors.

---

## 5. Anti-Resurrection Interaction

**Question:** Does `do_restore()` interact with the anti-resurrection check in `do_create()`?

**Answer:** No, and this is correct. The anti-resurrection check lives in `do_create()` (lines 672-693) and only runs during CREATE operations. `do_restore()` is a completely separate code path that modifies the existing file in-place rather than creating a new one. The anti-resurrection window is irrelevant for restore because:
1. Restore operates on the existing retired file (doesn't create a new one).
2. The user explicitly chose to restore, not re-create.
3. This is documented in README.md Design Decisions.

---

## 6. Summary

| Area | Verdict | Notes |
|------|---------|-------|
| do_restore() correctness | PASS | All checks, field operations, and error handling correct |
| Structural consistency with do_unarchive() | PASS | Near-identical structure; restore is actually slightly better (has idempotent handling) |
| Argparse + routing | PASS | "restore" in choices, routed in main() |
| Path safety | PASS | Path traversal check present |
| Atomic writes + locking | PASS | flock + atomic_write_json + add_to_index |
| commands/memory.md | PASS | Uses --action restore, clean flow |
| README.md | PASS | State transitions clean, Design Decisions well-framed, Known Limitations updated |
| CLAUDE.md | PASS | "6 actions", restore described |
| SKILL.md | PASS | Clean restore description |
| Edge cases | PASS | No record_status, archived, missing file all handled correctly |
| Compile check | PASS | No errors |

**Overall: PASS -- No issues found.**

The only observation (not a blocker) is that `do_unarchive()` lacks the idempotent handling for already-active memories that `do_restore()` has. This is a pre-existing minor inconsistency in `do_unarchive()`, not a problem introduced by this change.
