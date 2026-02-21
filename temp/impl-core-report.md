# impl-core Report: memory_write.py Changes

**File**: `hooks/scripts/memory_write.py`
**Status**: All changes applied and verified. Compile check passes.

---

## Change 1: Rename --action delete to --action retire (items 1.1.1-1.1.9)

| Item | Location | Old | New | Line |
|------|----------|-----|-----|------|
| 1.1.1 | Module docstring | `DELETE` | `RETIRE` | ~4 |
| 1.1.2 | Usage example | `--action delete` | `--action retire` | ~17 |
| 1.1.3a | Comment near record_status | `only via delete/archive` | `only via retire/archive` | ~497 |
| 1.1.3b | Error message string | `--action delete to retire` | `--action retire to retire` | ~501 |
| 1.1.4 | Function definition | `do_delete` / `--action delete (retire)` | `do_retire` / `--action retire (soft retire)` | ~873-874 |
| 1.1.5 | _check_path_containment label | `"DELETE"` | `"RETIRE"` | ~879 |
| 1.1.6a | Error output (nonexistent) | `DELETE_ERROR` | `RETIRE_ERROR` | ~883 |
| 1.1.6b | Error output (archived block) | `DELETE_ERROR` | `RETIRE_ERROR` | ~903 |
| 1.1.7 | argparse choices | `"delete"` | `"retire"` | ~1334 |
| 1.1.8 | --reason help text | `deletion or archival (delete/archive)` | `retirement or archival (retire/archive)` | ~1345 |
| 1.1.9 | Dispatch block | `== "delete"` / `do_delete` | `== "retire"` / `do_retire` | ~1369 |

## Change 2: Replace _read_input() to only allow .staging/ paths

| What | Old | New |
|------|-----|-----|
| Docstring | `Read JSON from input temp file` / `/tmp/` | `Read JSON from input file in .claude/memory/.staging/` |
| Path traversal check | Combined with startswith | Separate `".." in input_path` check |
| Path validation | `resolved.startswith("/tmp/")` | `"/.claude/memory/.staging/" in resolved` |
| Error messages | Reference `/tmp/` | Reference `.staging/` |
| FileNotFoundError message | `Write JSON to the temp file first` | `Write JSON to the staging path first` |

## Verified NOT changed

- `_cleanup_input()` function -- intact (lines 1208-1213)
- Config keys `delete.grace_period_days`, `delete.archive_retired` -- not present in this file (config only)
- Line 843 comment `# Rename flow: write new, update index, delete old` -- intact
- CUD internal labels -- not present in this file
- Module docstring usage examples at lines 11, 15 still reference `/tmp/` for `--input` (these are create/update examples, not part of Change 2 scope)

## Verification

- `python3 -m py_compile hooks/scripts/memory_write.py` -- passes clean
- `grep "DELETE_ERROR\|do_delete\|--action delete\|\"delete\"" hooks/scripts/memory_write.py` -- zero matches
- All `do_retire`, `RETIRE_ERROR`, `--action retire` references confirmed present
