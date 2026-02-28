# Action Plan V2 -- Completeness Review

**Reviewer:** Opus 4.6 completeness checker
**Date:** 2026-02-28
**Target:** `temp/action-plan-draft-v2.md` (Memory Save UI Noise Reduction)

---

## 1. Rollback Instructions

**Verdict: MISSING for all phases.**

No phase includes rollback/undo instructions. If a phase is partially deployed and causes regressions, the plan gives no guidance on how to revert.

| Phase | What Is Missing |
|-------|----------------|
| Phase 0 | OK -- isolated on `exp/agent-hook-stop` branch, naturally reverts by switching back to `main`. The plan documents this. |
| Phase 1 | No rollback. If `format_block_message()` change breaks SKILL.md parsing, reverting requires knowing which files changed. Need: "Rollback: `git revert` the Phase 1 commit. SKILL.md fallback handles inline `<triage_data>`, so partial revert is safe." |
| Phase 2 | No rollback. SKILL.md Phase 3 is rewritten. If the single-subagent pattern fails (e.g., venv bootstrap issue in subagent), there is no documented path to restore the original main-agent save flow. Need: "Rollback: restore the original SKILL.md Phase 3 section from git." |
| Phase 3 | No rollback. `memory_retrieve.py` is modified. If the save confirmation logic causes parsing issues or crashes, need: "Rollback: remove the save confirmation block from `memory_retrieve.py` (lines N-M)." |
| Phase 4 | No rollback. If the deferred sentinel creates stale files that accumulate, need cleanup instructions. |
| Phase 5 | Optional, but still no rollback mentioned for `hooks.json` type change from `command` to `agent`. |

**Recommendation:** Add a "Rollback" subsection to each phase (Phases 1-4 at minimum). For a plugin where `hooks.json` changes affect all sessions, rollback clarity is critical.

---

## 2. Test Automatability

**Verdict: PARTIAL -- most described tests are manual integration tests, not pytest-automatable.**

### Phase 1 Tests (lines 236-241):
- `python3 -m py_compile` -- automatable (already standard practice)
- `pytest tests/ -v` -- automatable
- `.staging/triage-data.json` file generation -- **automatable** (can be a unit test on `_run_triage()`)
- SKILL.md loads from file -- **manual only** (requires running a full Claude session with the plugin active)
- Inline `<triage_data>` fallback -- **manual only** (requires a Claude session where the file is absent)

### Phase 2 Tests (lines 302-307):
- All 6 items -- **manual only** (require spawning a Task subagent, running `memory_write.py`, measuring visible output). None of these can be automated with pytest.

### Phase 3 Tests (lines 388-391):
- Save confirmation display -- **manual only** (requires two Claude sessions: one to save, one to confirm)
- File deletion after display -- **partially automatable** (can unit test the file read/delete logic in `memory_retrieve.py`)

### Phase 4 Tests (line 445):
- Save failure simulation -- **partially automatable** (can unit test the pending file creation/detection logic, but end-to-end requires a Claude session)

**What's missing:** The plan does not distinguish between pytest-automatable unit tests and manual integration tests. It should:
1. Explicitly list which tests go into `tests/test_memory_triage.py` and `tests/test_memory_retrieve.py`
2. Note which tests are manual-only and describe the manual verification procedure
3. For Phase 1, specify new test functions: e.g., `test_triage_data_written_to_file()`, `test_format_block_message_with_file_path()`

---

## 3. CLAUDE.md Updates

**Verdict: MISSING -- no CLAUDE.md update step in any phase.**

The plan changes architecture in ways that require CLAUDE.md updates:

### Architecture Table (CLAUDE.md line 17):
Current description of Stop hook says:
> "outputs structured `<triage_data>` JSON + per-category context files"

After Phase 1, this should say:
> "outputs structured triage data to `.staging/triage-data.json` file + per-category context files"

### Parallel Per-Category Processing Section (CLAUDE.md lines 29-34):
Current item 2 says:
> **`<triage_data>` JSON block** with per-category scores, context file paths, and model assignments

After Phase 1, this becomes a file reference, not an inline JSON block.

### Phase 2 changes SKILL.md Phase 3 from "Main Agent" to "Single Subagent":
CLAUDE.md line 34 says:
> "See `skills/memory-management/SKILL.md` for the full 4-phase flow."

If Phase 3 moves into a subagent, the architecture description in CLAUDE.md should reflect this change.

### Phase 3 adds save confirmation to `memory_retrieve.py`:
CLAUDE.md Key Files table (line 41) describes `memory_retrieve.py` as:
> "FTS5 BM25 retrieval hook, injects context (fallback: legacy keyword)"

After Phase 3, it also handles save confirmation from previous sessions. The Role column should be updated.

### Phase 4 adds deferred sentinel handling to `memory_retrieve.py`:
Same Key Files update needed -- `memory_retrieve.py` now also detects pending saves.

**Recommendation:** Add a "Documentation Update" step to Phases 1, 2, 3, and 4 that explicitly lists which CLAUDE.md sections to update.

---

## 4. Existing Test Breakage

**Verdict: CRITICAL -- at least 6 existing tests will break from Phase 1 changes.**

Phase 1 changes `format_block_message()` to output `<triage_data_file>` instead of inline `<triage_data>`. The following existing tests in `tests/test_memory_triage.py` directly parse the inline `<triage_data>` XML tags:

| Test | Line | What It Asserts | Will Break? |
|------|------|----------------|-------------|
| `test_triage_data_includes_description` | 238 | `assert "<triage_data>" in message` + parses JSON between tags | **YES** |
| `test_triage_data_no_description_when_absent` | 269 | `message.index("<triage_data>")` + parses JSON between tags | **YES** |
| `test_human_readable_includes_description` | 287 | `message[:message.index("<triage_data>")]` | **YES** |
| `test_format_block_message_works_without_descriptions` | 342 | `assert "<triage_data>" in message` | **YES** |
| Integration test (any test calling `format_block_message()` and checking output) | various | Depends on inline triage_data | **YES** |

The plan mentions "단위 테스트 작성/업데이트" (write/update unit tests) in Phase 1 steps but does not specifically call out that **at least 4 existing `TestTriageDataIncludesDescription` tests and 1 `TestBackwardCompatNoDescriptions` test** need to be rewritten. This is the highest-risk omission because running `pytest tests/ -v` as a check will fail immediately after Phase 1 changes.

Additionally, the plan's Phase 1 proposes backwards-compatible fallback in SKILL.md (check for `<triage_data_file>`, fall back to inline `<triage_data>`). But `format_block_message()` itself will NO LONGER produce inline `<triage_data>`. So the "backwards compatibility" is only for SKILL.md parsing of old-format output -- the function signature changes. Tests should reflect both the new behavior AND the migration path.

**Recommendation:** Phase 1 must include an explicit step: "Update existing tests in `TestTriageDataIncludesDescription` and `TestBackwardCompatNoDescriptions` classes to assert on `<triage_data_file>` tag instead of inline `<triage_data>` JSON parsing."

---

## 5. Git Workflow

**Verdict: PARTIALLY PRESENT -- Phase 0 has branch strategy, Phases 1-4 have none.**

Phase 0 correctly specifies:
- Branch name: `exp/agent-hook-stop`
- Isolation rationale (hooks.json changes affect all sessions)
- Archive strategy (keep branch, don't merge to main)

Phases 1-4 have NO git workflow:
- No branch naming convention (e.g., `feat/noise-reduction-fix-a`, `feat/noise-reduction-fix-b`)
- No commit strategy (one commit per phase? per sub-step?)
- No PR creation guidance
- No guidance on whether Phases 1-4 should be on one feature branch or separate branches
- No guidance on when to merge to main (after each phase? after Phase 4?)

**Recommendation:** Add a top-level "Git Workflow" section specifying:
1. Branch strategy: single feature branch `feat/noise-reduction` or per-phase branches
2. Commit granularity: one commit per phase minimum, tests included in same commit
3. PR strategy: single PR for Phases 1-4 or incremental PRs
4. The action plan file itself should be in `action-plans/` (not `temp/`) when work begins

---

## 6. Action Plan Format Compliance

**Verdict: MOSTLY COMPLIANT with 2 issues.**

### Frontmatter: COMPLIANT
```yaml
---
status: not-started
progress: "미시작"
---
```
Matches the required format from `action-plans/README.md`.

### Checkmark Format: NON-COMPLIANT
The README requires `[v]`, `[ ]`, `[/]` for done/not-started/in-progress.

The action plan uses `[ ]` correctly for not-started items in the checklist (lines 151-157, 247-251, etc.). However, the phase headers use a different format: `### Phase 0: Agent Hook Isolation 실험 [ ]` -- the `[ ]` is in the header itself rather than as a checklist item. This is cosmetic but inconsistent with the README's example format which puts checkmarks on sub-items only.

### File Location: NEEDS ATTENTION
The plan is currently at `temp/action-plan-draft-v2.md`. Per `action-plans/README.md`, active plans should be root `.md` files in `action-plans/`. The plan should be moved to `action-plans/plan-noise-reduction.md` (or similar) when finalized.

---

## Summary of All Omissions

| # | Omission | Severity | Phases Affected |
|---|----------|----------|----------------|
| 1 | No rollback instructions | **High** | Phases 1-4 |
| 2 | No distinction between automatable vs manual tests | **Medium** | All phases |
| 3 | No CLAUDE.md update steps | **High** | Phases 1-4 |
| 4 | Existing test breakage not identified | **Critical** | Phase 1 (4-6 tests in `test_memory_triage.py`) |
| 5 | No git workflow for Phases 1-4 | **Medium** | Phases 1-4 |
| 6 | Plan not yet in `action-plans/` directory | **Low** | Meta |
| 7 | `format_block_message()` signature change not reflected in test update plan | **High** | Phase 1 |
| 8 | No new test file/function names specified | **Low** | Phases 1-4 |
