# impl-docs Report: Rename --action delete to --action retire

## Summary

All 5 assigned files have been updated. A total of 13 edits were made across the files.

## Changes by File

### 1. skills/memory-management/SKILL.md (6 edits)

| Item | Line (approx) | Change |
|------|---------------|--------|
| 1.2.1 | 100 | Draft JSON: `"action": "delete"` -> `"action": "retire"` |
| 1.2.2 | 130 | Phase 3 CLI: `--action delete` -> `--action retire` |
| 1.2.3 | 218 | Session rolling window: `--action delete` -> `--action retire` |
| 1.2.4 | 244 | User intent mapping: `--action delete` -> `--action retire` |
| 1.2.5 | 102 | Subagent report: `CREATE/UPDATE/DELETE/NOOP` -> `CREATE/UPDATE/RETIRE/NOOP` |
| 1.2.6 | 143 | Write protections: `use delete/archive actions` -> `use retire/archive actions` |

**Preserved (not changed):**
- `UPDATE_OR_DELETE` labels (lines 90, 91, 95, 155, 156, 159) -- internal CUD state machine labels
- `DELETE` in CUD decision table (lines 95, 156, 158, 167) -- CUD resolution values
- `"UPDATE over DELETE"` principle (lines 96, 167) -- safety default text
- `delete.grace_period_days` and `delete.archive_retired` config keys (lines 271-272)

### 2. commands/memory.md (1 edit)

| Item | Line (approx) | Change |
|------|---------------|--------|
| 1.3.1 | 52 | `--action delete` -> `--action retire` in --retire subcommand definition |

### 3. hooks/scripts/memory_write_guard.py (1 edit)

| Item | Line (approx) | Change |
|------|---------------|--------|
| 1.4.1 | 78 | `--action <create\|update\|delete>` -> `--action <create\|update\|retire\|archive\|unarchive\|restore>` |

Compile check: PASS (`python3 -m py_compile` succeeded)

### 4. CLAUDE.md (3 edits)

| Item | Line (approx) | Change |
|------|---------------|--------|
| 1.5.1 | 24 | `delete (soft retire)` -> `retire (soft retire)`, `delete action` -> `retire action`, `soft delete` -> `soft retire` |
| 1.5.2 | 43 | Key Files table: `CRUD + lifecycle (archive/unarchive/restore)` -> `CRUD + lifecycle (retire/archive/unarchive/restore)` |
| Extra | 76 | Testing section: `create/update/delete operations` -> `create/update/retire operations` |

### 5. README.md (3 edits)

| Item | Line (approx) | Change |
|------|---------------|--------|
| 1.7.1 | 141 | `Soft-delete a memory` -> `Soft-retire a memory` |
| 1.7.2 | 159 | `# Soft-delete, 30-day grace period` -> `# Soft-retire, 30-day grace period` |
| 1.7.3 | 253 | `create/update/delete/archive/unarchive` -> `create/update/retire/archive/unarchive` |

**Note:** Line 125 has "Soft-deleted; preserved for 30-day grace period" in the lifecycle status table. This describes the retired status behavior, not the CLI action, so it was left as-is per instructions.

## Verification

- Grep for `--action delete` in all 5 files: **0 matches** (clean)
- Grep for `Soft-delete` in README.md: **0 matches in targeted locations** (clean)
- Grep for `create/update/delete` in CLAUDE.md and README.md: **0 matches** (clean)
- SKILL.md `UPDATE_OR_DELETE` labels: **preserved** (7 occurrences intact)
- SKILL.md `"UPDATE over DELETE"` principle: **preserved** (2 occurrences intact)
- Config keys `delete.grace_period_days`, `delete.archive_retired`: **preserved** (unchanged)
- Python compile check on memory_write_guard.py: **PASS**

## Files NOT Changed (as instructed)

- temp/*.md files
- MEMORY-CONSOLIDATION-PROPOSAL.md
- hooks/scripts/memory_write.py (assigned to impl-core)
- tests/test_memory_write.py (assigned to impl-tests)
