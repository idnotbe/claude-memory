# R4 Writer Summary: rd-08-final-plan.md Integration

**Date:** 2026-02-21
**Writer:** r4-writer agent
**Document:** `research/rd-08-final-plan.md`

## Line Counts

- **Before:** 1297 lines
- **After:** 1332 lines
- **Delta:** +35 lines

## All Changes Made

### From Technical Review

1. **[H1] Fixed `build_fts_index_from_index()` FTS5 schema** -- Removed `id UNINDEXED` and `updated_at UNINDEXED` from both the standalone CREATE TABLE example and the function definition. Changed INSERT from 6 values to 4 values. Removed `parsed["id"]` and `parsed["updated_at"]` references. Added `[R4-fix]` note.

2. **[H2] Fixed `score_with_body()` undefined variable** -- Added `user_prompt: str` parameter to function signature. Replaced `set(tokenize(fts_query_source_text))` with `tokenize(user_prompt)`. Added `[R4-fix]` note explaining both the parameter addition and the redundant `set()` removal.

3. **[M1] Fixed CATEGORY_PRIORITY keys to UPPERCASE** -- Changed `"decision"` to `"DECISION"`, `"constraint"` to `"CONSTRAINT"`, etc. to match codebase convention where `parse_index_line()` returns uppercase categories. Added `[R4-fix]` note.

4. **[M2] Removed redundant `set()` wrapper** -- Addressed inline as part of H2 fix (the `set(tokenize(...))` became just `tokenize(user_prompt)` with an inline note explaining both fixes).

5. **[M3] Added camelCase blind spot to Risk Matrix** -- Added new row: "CamelCase identifier blind spot | Medium | Likely" with mitigation about preferring snake_case in titles and adding snake_case tag variants. Marked `[R4-reviewed]`.

6. **[L1] Added test factory coverage note to Session 4 checklist** -- Added new checklist item: "Update `conftest.py` test factories to cover all `BODY_FIELDS` paths" with specific field examples.

7. **[L2] Fixed line reference** -- Changed "line 29" to "line 28" for `score_description` import reference in `test_adversarial_descriptions.py`.

### From Practical Review

8. **[A1] Added main() integration pseudocode** -- Added a `Modified main() flow (pseudocode)` block after the `score_with_body()` section showing the FTS5/fallback branch, `apply_threshold`, and `apply_confidence` flow. Marked `[R4-fix]`.

9. **[A2] Added definitive score_description() decision** -- Added new Decision #8 after Decision #7: "DECISION: `score_description()` is PRESERVED -- called only in fallback/keyword path. Dead code in FTS5 path. No import changes needed in test files." Marked `[R4-reviewed]`.

10. **[G1] Added Config Migration subsection** -- Added new subsection under Configuration specifying: `match_strategy` defaults to `fts5_bm25` when absent (silent upgrade), `max_inject` defaults to 3 but respects explicit values, CLAUDE.md upgrade notes required. Marked `[R4-fix]`.

11. **[G2] Added tokenizer sync tracking item** -- Added to Session 3 checklist: "Track: synchronize `memory_candidate.py` tokenizer with `memory_retrieve.py`". Marked `[R4-fix]`.

12. **[G3] Updated sys.path import pattern** -- Updated both the Phase 2b import path fix description and the Session 3 checklist item. Notes that Python handles `sys.path[0]` natively for script execution; `sys.path.insert` only needed in test files. Changed `os.path.abspath()` to `os.path.realpath()`. Marked `[R4-fix]`.

13. **[I1] Made definitive skill vs command decision** -- Changed Session 3 checklist from "Reconcile with existing `commands/memory-search.md`" to "DECISION: Replace `commands/memory-search.md` with `skills/memory-search/SKILL.md`". Also updated the Phase 2b description to match. Marked `[R4-fix]`.

14. **[I2] Expanded CLAUDE.md update scope** -- Replaced generic "Update CLAUDE.md: Key Files table, Architecture section" with specific 4-item list: (1) Key Files, (2) Architecture UserPromptSubmit, (3) Security FTS5 query injection, (4) Quick Smoke Check. Marked `[R4-fix]`.

15. **[E1] Updated Session 4 time estimate** -- Changed from 8-10 hours to 10-12 hours. Added note about potential 4a/4b split. Updated both the session header, the Corrected Estimates Table, and the Schedule table.

16. **[E2] Added measurement gate prerequisite** -- Added to Session 6 checklist: "Prerequisite: Ensure at least 50 active memories across 4+ categories." Marked `[R4-fix]`.

### Metadata Updates

17. **Updated header** -- Added R4 review date, updated status line, updated validated-by line.

18. **Added R4 row to Audit Trail** -- Comprehensive row summarizing all technical (2H, 3M, 2L) and practical (2H, 7M, 2L) findings.

## Findings NOT Integrated (with reason)

- **A3 (0-result hint injection format)** -- The practical review asked for a specific output format for the 0-result hint. The existing Session 3 checklist already specifies "only at scoring exit points, not empty-index exits" which is the key constraint. The exact output string (`<!-- Tip: Use /memory:search ... -->`) is an implementation detail better decided during Session 3 when the developer has the full context of the output formatting code. No change needed in the plan document.

- **A4 (Smart wildcard regex edge cases)** -- The practical review suggested adding edge-case tokens (`_private`, `.env`, `-v`) to Session 1d validation. This is a LOW severity item and the existing validation list already covers the critical patterns. The regex's first alternative requires starting with `[a-z0-9]`, so leading special chars are naturally rejected. This is an implementation-time concern, not a plan-level fix.
