# Audit Synthesis: eliminate-all-popups Action Plan

**Date:** 2026-03-22
**Sources:** audit-phase12.md, audit-phase3.md, audit-phase4.md, audit-files.md

---

## Executive Summary

The plan's `status: done` is **functionally accurate** — all popup sources (P1, P2, P3) are eliminated and 37 regression tests pass. However, the plan document itself is **stale**: the Files Changed table and Decision Log reflect pre-implementation Option A design, not the final Option B (/tmp/ migration) implementation.

## Phase-by-Phase Status

| Phase | Verdict | Detail |
|-------|---------|--------|
| Phase 1 (P1 fix) | **DONE** | cleanup-intents action, SKILL.md updated, Rule 0 comprehensive. Tests: 15 (name differs from plan) |
| Phase 2 (P2 fix) | **DONE** | write-save-result-direct action, SKILL.md Phase 3 updated, heredoc warning. Tests: 9 (name differs) |
| Phase 3 (P3 fix) | **DONE** | Option B fully implemented. 8/8 scripts migrated. O_NOFOLLOW + symlink defense. staging_utils.py created. |
| Phase 4 (Tests) | **DONE** | 37 regression tests confirmed. 1198 total tests. V-R2 gap fill evidenced. |

## Discrepancies Found

### 1. Files Changed Table (2/5 accurate, 2 inaccurate, 1 partial)

| File | Plan Says | Reality | Issue |
|------|-----------|---------|-------|
| memory_write.py | "write-staging action" | Never implemented | Option A abandoned for Option B |
| agents/memory-drafter.md | "Return JSON as output instead of Write tool" | Still uses Write tool | /tmp/ migration made this unnecessary |
| memory_write_guard.py | "Remove staging auto-approve" | NEW auto-approve ADDED + legacy kept | Opposite of plan |
| SKILL.md | Accurate | Accurate | OK |
| tests/ | Accurate | Accurate | OK |

### 2. Unlisted Files (8 files changed but not in table)
- memory_staging_utils.py (NEW), memory_triage.py, memory_staging_guard.py, memory_validate_hook.py, memory_draft.py, memory_retrieve.py, CLAUDE.md, commands/memory-save.md

### 3. Decision Log (1/3 fully implemented)
| Decision | Status |
|----------|--------|
| Script writes over Write tool | PARTIALLY IMPLEMENTED, then superseded by /tmp/ migration |
| Return-JSON drafter | NOT IMPLEMENTED (rendered unnecessary) |
| Direct CLI args for save-result | FULLY IMPLEMENTED |

### 4. Minor Discrepancies
- Progress note says "1164 tests" — actual is 1198 (post V-R2 gap fill)
- Test names differ from plan (class-based vs standalone function names)
- V-R1 evidence is implied but not separately committed

## Root Cause
The plan was written before Option B (/tmp/ migration) was chosen. After Option B was implemented, the Files Changed table, Decision Log, and some Phase 3 checklist items were not updated to reflect the actual implementation path.

## Checklist Status Update Needed

### Phase 1 Checklist
- [x] Step 1.1: cleanup-intents action ✓
- [x] Step 1.2: SKILL.md Phase 0 updated ✓
- [x] Step 1.3: Rule 0 forbids python3 -c ✓
- [x] Step 1.4: Tests exist (15 tests, name differs) ✓

### Phase 2 Checklist
- [x] Step 2.1: Heredoc warning in Phase 3 ✓
- [x] Step 2.2: write-save-result-direct action ✓
- [x] Step 2.3: SKILL.md uses direct action ✓
- [x] Step 2.4: Tests exist (9 tests, name differs) ✓

### Phase 3 Checklist
- [x] Option C investigated, abandoned ✓
- [x] Step 3.1: Staging moved to /tmp/ ✓
- [x] Step 3.2: Deterministic hash + O_NOFOLLOW ✓
- [x] Step 3.3: All 8 scripts updated ✓
- [x] Step 3.4: write_guard auto-approve for /tmp/ ✓
- [x] Step 3.5: staging_guard guards new path ✓
- [x] Step 3.6: .gitignore N/A ✓

### Phase 4 Checklist
- [x] Step 4.1: Staging Write tool tests (3 tests) ✓
- [x] Step 4.2: python3 -c tests (2 tests) ✓
- [x] Step 4.3: Heredoc tests (3 tests) ✓
- [x] Step 4.4: cleanup-intents tests (12 tests) ✓
- [x] 37 regression tests confirmed ✓
- [x] V-R2 verification round evidenced ✓

## What the Updated Plan Should Reflect
1. Files Changed table: remove write-staging, add 8 unlisted files, correct memory-drafter.md and write_guard.py descriptions
2. Decision Log: update Decision 1 and 2 to reflect Option B outcome
3. Progress note: update test count to 1198
4. Phase 3 checklist: mark all Option B steps as [x]
