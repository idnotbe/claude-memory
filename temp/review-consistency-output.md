# Consistency Review: Staging Path Fix

**Reviewer:** reviewer-consistency
**Date:** 2026-02-20
**Scope:** Cross-file consistency of the `/tmp/` -> `.staging/` migration in `commands/memory-save.md`

---

## 1. Cross-File Path Pattern Comparison

### 1.1 The Two Write Flows

| Flow | Staging File Pattern | Used In |
|------|---------------------|---------|
| Manual `/memory:save` | `.claude/memory/.staging/.memory-write-pending.json` | `commands/memory-save.md:39-40` |
| Auto-capture (Phase 1) | `.claude/memory/.staging/draft-<category>-<pid>.json` | `skills/memory-management/SKILL.md:99` |

Both flows now write to `.claude/memory/.staging/` -- this is **consistent** at the directory level.

### 1.2 Naming Convention Difference: Intentional and Correct

The different filenames (`.memory-write-pending.json` vs `draft-<category>-<pid>.json`) are **intentionally different** and this is appropriate:

- **`.memory-write-pending.json`**: Used by the manual `/memory:save` command. There is only ever one manual save in progress at a time. A single, fixed filename is sufficient. The leading dot hides it from casual `ls` output.
- **`draft-<category>-<pid>.json`**: Used by auto-capture Phase 1 subagents. Multiple subagents run in **parallel** (one per triggered category), so each needs a unique filename. The `<category>-<pid>` suffix ensures no collisions between concurrent subagents.

**Verdict: NOT an inconsistency.** The naming serves different concurrency requirements. Unifying them would be wrong -- the manual command has no category/PID context at write time, and using a fixed name for parallel subagents would cause race conditions.

### 1.3 Both Paths Pass `memory_write.py` Validation

The `_read_input()` function at `hooks/scripts/memory_write.py:1181` checks:
```python
in_staging = "/.claude/memory/.staging/" in resolved
```

Both `.memory-write-pending.json` and `draft-<category>-<pid>.json` resolve to paths containing `/.claude/memory/.staging/`, so both pass. **Consistent.**

### 1.4 Both Paths Pass the Write Guard

`hooks/scripts/memory_write_guard.py:53-58` allows all writes to `.claude/memory/.staging/`:
```python
staging_segment = "/.claude/memory/.staging/"
if staging_segment in normalized:
    sys.exit(0)
```

Both file patterns are inside `.staging/` and pass this check. **Consistent.**

---

## 2. Remaining `/tmp/` References: Full Codebase Audit

### 2.1 Runtime Code (Python scripts) -- ISSUES FOUND

| File | Line(s) | Reference | Status |
|------|---------|-----------|--------|
| `memory_write_guard.py` | 42-51 | `/tmp/` allowlist for `.memory-write-pending`, `.memory-draft-`, `.memory-triage-context-` | **STALE** -- Dead code. Since staging moved to `.claude/memory/.staging/`, these `/tmp/` patterns are never hit in the happy path. The `.staging/` allowlist at lines 53-58 handles all cases. |
| `memory_write_guard.py` | 45 | `if resolved.startswith("/tmp/"):` | **STALE** -- Same as above. This entire branch is orphaned for normal operation. |
| `memory_triage.py` | 697, 709, 719 | `/tmp/` fallback when staging dir creation fails | **INTENTIONAL** -- This is a legitimate fallback. If `.claude/memory/.staging/` cannot be created (e.g., permissions, missing cwd), context files fall back to `/tmp/`. This is correct defensive coding. |
| `memory_triage.py` | 967 | `resolved.startswith("/tmp/")` in transcript path validation | **INTENTIONAL** -- Defense-in-depth for transcript path validation. Not related to staging. |
| `memory_triage.py` | 999 | `/tmp/.memory-triage-scores.log` fallback | **INTENTIONAL** -- Same pattern: falls back to `/tmp/` if `.staging/` dir fails. |
| `memory_write.py` | 11, 15 | Docstring examples use `/tmp/.memory-write-pending.json` | **STALE** -- The docstring examples show the old path. Should be updated to `.claude/memory/.staging/`. |

### 2.2 Operational Documentation (.md files) -- ISSUES FOUND

| File | Context | Status |
|------|---------|--------|
| `commands/memory-save.md` | Lines 39-40 | **FIXED** by this change |
| `skills/memory-management/SKILL.md` | Lines 71, 99, 124 | **ALREADY CORRECT** -- Uses `.staging/` paths |
| `CLAUDE.md` | Line 31 | **CORRECT** -- References `.staging/context-<CATEGORY>.txt` |
| `README.md` | Lines 236, 245, 270 | **STALE** -- Still references `/tmp/.memory-triage-context-<cat>.txt` (line 236), `/tmp/.memory-draft-<cat>-<pid>.json` (line 245), and `/tmp/.memory-triage-context-<category>.txt` (line 270) |
| `TEST-PLAN.md` | Lines 140-142 | **STALE** -- References `/tmp/.memory-write-pending.json` and `/tmp/.memory-draft-*.json` as test expectations |
| `MEMORY-CONSOLIDATION-PROPOSAL.md` | Lines 394-425+ | **HISTORICAL** -- Design doc with `/tmp/` references. These are historical context documenting the original design. Acceptable as-is, but a note that paths have since changed would prevent confusion. |

### 2.3 Test Files -- ISSUES FOUND

| File | Lines | Status |
|------|-------|--------|
| `test_memory_write_guard.py` | 58-61 | **STALE** -- Tests that `/tmp/.memory-write-pending.json` is allowed. This tests the dead `/tmp/` branch in the write guard. The test passes but tests orphaned code. |
| `test_memory_write_guard.py` | 173 | Tests `/tmp/test-project/.claude/memory/...` -- not a staging path issue, fine. |
| `test_memory_triage.py` | 1196-1206 | Tests the `/tmp/` fallback behavior. **CORRECT** -- This is testing the intentional fallback path. |

### 2.4 JSON files

No `/tmp/` references found in any `.json` files. **Clean.**

---

## 3. CLAUDE.md Alignment

CLAUDE.md currently says (line 31):
> Context files at `.claude/memory/.staging/context-<CATEGORY>.txt`

This is **correct** and aligned with the fix. No CLAUDE.md update needed for this specific change.

However, CLAUDE.md does not mention the `.memory-write-pending.json` staging file pattern at all. It only documents context files. This is acceptable since CLAUDE.md documents architecture (hooks), not command-level implementation details.

**Verdict: No CLAUDE.md update required.**

---

## 4. Documentation Coherence Assessment

### 4.1 Coherent After Fix

| Document | Staging Path | Status |
|----------|-------------|--------|
| `CLAUDE.md` | `.claude/memory/.staging/context-<CATEGORY>.txt` | Correct |
| `SKILL.md` | `.claude/memory/.staging/draft-<category>-<pid>.json` | Correct |
| `commands/memory-save.md` | `.claude/memory/.staging/.memory-write-pending.json` | Correct (after fix) |
| `memory_write.py` validation | `/.claude/memory/.staging/` substring check | Correct |
| `memory_write_guard.py` `.staging/` exemption | `/.claude/memory/.staging/` substring check | Correct |

### 4.2 Incoherent (Stale)

| Document | Issue |
|----------|-------|
| `README.md` | Lines 236, 245, 270 still reference `/tmp/` for context and draft files |
| `TEST-PLAN.md` | Lines 140-142 reference `/tmp/` paths as test expectations |
| `memory_write.py` docstring | Lines 11, 15 show `/tmp/` example paths |
| `memory_write_guard.py` lines 41-51 | Dead `/tmp/` allowlist code and stale comments |

---

## 5. Summary of Findings

### No Issues (The Fix Is Correct)

1. **The fix itself is correct.** `commands/memory-save.md` now uses `.claude/memory/.staging/.memory-write-pending.json`, which passes `memory_write.py` validation and the write guard.
2. **Different naming conventions are intentional.** `.memory-write-pending.json` (manual, single file) vs `draft-<category>-<pid>.json` (auto-capture, parallel) serve different concurrency requirements.
3. **CLAUDE.md needs no update** for this specific change.

### Issues Found (Outside Fix Scope but Flagged for Awareness)

| ID | Severity | File | Issue |
|----|----------|------|-------|
| C1 | **LOW** | `README.md:236,245,270` | Stale `/tmp/` path references in architecture diagram and Phase 0 description. Should be updated to `.staging/` paths for documentation accuracy. |
| C2 | **LOW** | `memory_write.py:11,15` | Docstring examples show old `/tmp/` input paths. Should reference `.staging/`. |
| C3 | **INFO** | `memory_write_guard.py:41-51` | Dead code: `/tmp/` allowlist branch. The `.staging/` allowlist at lines 53-58 handles everything. The `/tmp/` branch only activates if `memory_triage.py` falls back to `/tmp/` (which is a legitimate edge case for context files, but the `.memory-write-pending` and `.memory-draft-` patterns in `/tmp/` are truly dead). |
| C4 | **LOW** | `TEST-PLAN.md:140-142` | Test plan references `/tmp/` paths. Should be updated to match current `.staging/` paths. Existing test at `test_memory_write_guard.py:58-61` tests the dead `/tmp/` branch. |
| C5 | **INFO** | `MEMORY-CONSOLIDATION-PROPOSAL.md` | Historical design doc with `/tmp/` references. Acceptable as historical record but could benefit from a note at the top that paths have since migrated. |

### Recommendation

The fix to `commands/memory-save.md` is **APPROVED** from a consistency perspective. The remaining stale references (C1-C5) are outside the scope of this specific fix but should be tracked as follow-up work to complete the `/tmp/` -> `.staging/` migration across all documentation and dead code.

---

## 6. Methodology

- Grepped entire codebase for `/tmp/` in `*.md`, `*.py`, and `*.json` files
- Grepped for `.staging/`, `memory-write-pending`, and `draft-` patterns
- Read all operational docs, runtime scripts, and test files referencing staging paths
- Cross-compared the manual `/memory:save` flow against the auto-capture SKILL.md flow
- Verified both paths pass `memory_write.py` `_read_input()` validation and write guard checks
