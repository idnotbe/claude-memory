# Dependency Analysis: 9-Session Implementation Plan

**Date:** 2026-02-21
**Analyst:** Track B (dependency verification)
**Inputs:** rd-08-final-plan.md, memory_retrieve.py (current), test_memory_retrieve.py (current), memory_index.py, conftest.py
**Scope:** Verify ordering, dependencies, parallelism claims, and identify conflicts

---

## Summary of Findings

| Check | User's Claim | Verdict | Severity |
|-------|-------------|---------|----------|
| Session 1->2 | Sequential | PARTIALLY WRONG -- 1c can run in parallel with 2a | Low |
| Session 2->3 | Sequential | WRONG -- 3 can start in parallel with late 2a items | Medium |
| Session 4 timing | After Session 2 | WRONG -- must be after Sessions 2, 3, AND 5 | HIGH |
| Session 4//5 parallel | Can run in parallel | WRONG -- CONFLICT, must be sequential (5 before 4) | HIGH |
| Session 6 prerequisites | After 4+5 | INCOMPLETE -- also needs Session 3 complete | Medium |
| Session 7->8 | Sequential | PARTIALLY WRONG -- test stubs can be written before 7 | Low |
| Circular deps | None claimed | CONFIRMED NONE | N/A |

**Bottom line: The user's dependency graph has 2 HIGH-severity errors (Sessions 4 and 5 ordering) and 3 medium-severity inaccuracies. A corrected graph is provided at the end.**

---

## 1. Session 1 -> Session 2 Dependency

### User's Claim
Sessions 1->2->3 are strictly sequential.

### Analysis

**Session 1 produces three things:**
- 1a: `_TOKEN_RE` regex fix in `memory_retrieve.py` (line 54, currently `r"[a-z0-9]+"`, changed to `r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+"`)
- 1b: `extract_body_text()` function (~50 LOC, new function in `memory_retrieve.py`)
- 1c: `HAS_FTS5` availability check (~15 LOC, new global in `memory_retrieve.py`)

**Session 2 consumes:**
- 2a-FTS5-index: `build_fts_index_from_index()` -- parses `index.md` via `parse_index_line()` (already exists at line 72). Does NOT use the new tokenizer. FTS5's own `unicode61` tokenizer handles tokenization inside the database. The `_TOKEN_RE` fix only matters for the query-building side.
- 2a-query-builder: `build_fts_query()` -- uses `STOP_WORDS` (exists at line 22) and a new regex for cleaning tokens. This is self-contained code per the plan (lines 60-73 of rd-08). It does NOT call `tokenize()` -- it has its own inline cleaning logic (`re.sub(r'[^a-z0-9_.\-]', '', t.lower())`).
- 2a-hybrid-scoring: `score_with_body()` -- calls `extract_body_text()` (from 1b) and `tokenize()` (from 1a). **This is the real dependency.**
- 2a-threshold: `apply_threshold()` -- pure function, no dependencies on Session 1.
- 2a-fallback: FTS5 fallback code -- uses `HAS_FTS5` (from 1c). **This depends on 1c.**

### Verdict: PARTIALLY CORRECT

The dependency is real but not total:
- `build_fts_index_from_index()`, `build_fts_query()`, and `apply_threshold()` do NOT depend on Session 1.
- `score_with_body()` depends on 1a (tokenizer) and 1b (body extract).
- FTS5 fallback depends on 1c.

However, all of these items land in the same file (`memory_retrieve.py`), and the tokenizer fix (1a) is a one-line change. In practice, starting 2a before 1a/1b is finished is more trouble than it's worth due to merge conflicts.

**Practical recommendation:** Keep Session 1->2 sequential. The parallelization opportunity is real but not worth the merge conflict risk for a one-person project. Item 1c (FTS5 check, ~15 LOC) could theoretically be done as part of Session 2 since it's just a guard check, but this saves at most 15 minutes.

---

## 2. Session 2 -> Session 3 Dependency

### User's Claim
Session 3 depends on Session 2 being complete.

### Analysis

**Session 3 creates:**
- `hooks/scripts/memory_search_engine.py` (new file) -- shared FTS5 engine extracted from `memory_retrieve.py`
- `skills/memory-search/SKILL.md` (new file) -- on-demand search skill
- Full FTS5 index (reads all JSON for body content)
- "Hint injection" -- `memory_retrieve.py` outputs `<!-- Use /memory:search <topic> -->` when auto-inject returns 0 results

**What Session 3 extracts FROM Session 2:**
The plan (rd-08, line 276-295) says Session 3 extracts search logic into `memory_search_engine.py` and imports back:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_search_engine import build_fts_index, query_fts
```

This means Session 3 is a **refactoring** of code written in Session 2 -- extracting functions already written in `memory_retrieve.py` into a shared module. The functions being extracted are:
- `build_fts_index_from_index()` (or a variant that also reads body)
- `query_fts()` (the core FTS5 query executor)
- `build_fts_query()` (the smart wildcard query builder)

### Verdict: MOSTLY CORRECT, but with nuance

Session 3's extraction depends on the functions existing in `memory_retrieve.py` first (written in Session 2). However, Session 3 also has independent work:
- `SKILL.md` can be written at any time (it's documentation/prompt)
- The full FTS5 index (with body column) is a variant of the title+tags index -- it could be designed in parallel

The dependency chain is: Session 2 must complete the core FTS5 functions -> Session 3 extracts them into a shared module + adds body-column variant + creates skill file.

**Practical recommendation:** Keep sequential. The extraction refactoring genuinely requires Session 2's code to exist first. The SKILL.md could be drafted earlier, but it's a 30-minute task that doesn't justify parallel scheduling.

---

## 3. Session 4 Timing (Test Rewrite)

### User's Claim
Tests (Session 4) can start after Session 2.

### Analysis -- CRITICAL FINDING

**The plan itself acknowledges (rd-08, lines 298-316) that tests must cover:**
1. FTS5 index build + query -- from Session 2
2. `build_fts_query()` smart wildcard -- from Session 2
3. Body content extraction per category -- from Session 1
4. Hybrid scoring with body bonus -- from Session 2
5. FTS5 fallback to keyword system -- from Session 2
6. End-to-end auto-inject -- from Session 2
7. Performance regression benchmark -- from Session 2

**What tests would ALSO need to cover but is NOT in Session 2:**
- `memory_search_engine.py` (new file from Session 3) -- a shared module with a CLI interface. Tests need to verify the CLI works, the full-body FTS5 index works, and `memory_retrieve.py` correctly imports from it.
- Confidence annotations (Session 5) -- the `confidence_label()` function and the modified output format (`[confidence:high]` suffix). If tests are written against Session 2's output format and Session 5 changes it, ALL integration tests that assert on output format will break.

**Current test state (evidence from `test_memory_retrieve.py`):**
- Line 228: `assert "<memory-context" in stdout or "RELEVANT MEMORIES" in stdout` -- this assertion checks the output format
- Line 393: `assert rc == 0` + content assertions -- these will break when `[confidence:high]` is appended

**The plan's own test list (rd-08, lines 298-316) omits tests for:**
- `memory_search_engine.py` CLI interface
- `confidence_label()` function
- Modified output format with confidence annotations
- The hint injection (`<!-- Use /memory:search ... -->`)

### Verdict: WRONG -- Session 4 must be AFTER Sessions 2, 3, AND 5

If tests are written after Session 2 but before Session 3 and Session 5:
- Tests won't cover `memory_search_engine.py` (doesn't exist yet)
- Tests will assert on output format without `[confidence:...]`, then Session 5 will break them
- Tests won't verify the import chain `memory_retrieve.py -> memory_search_engine.py`

**Severity: HIGH.** Writing tests twice (once after S2, again after S3 and S5 modify the code) is exactly the kind of throwaway work the plan claims to avoid.

---

## 4. Session 4 // Session 5 Parallelism (CONFLICT)

### User's Claim
Session 4 (tests) and Session 5 (confidence annotations) can run in parallel after Session 2.

### Analysis -- CRITICAL FINDING

**Session 5 modifies `memory_retrieve.py` output format.** Specifically:

Current output (line 393 of `memory_retrieve.py`):
```python
print(f"- [{entry['category']}] {safe_title} -> {safe_path}{tags_str}")
```

After Session 5, the plan (rd-08, lines 341-348) changes this to:
```
- [DECISION] JWT token refresh flow -> path #tags:auth,jwt [confidence:high]
```

Session 5 also adds `confidence_label()` (~20 LOC) which depends on BM25 scores (from Session 2).

**Conflict scenario:**
1. Session 4 starts writing tests against Session 2's output format
2. Session 5 modifies the output format to append `[confidence:high/medium/low]`
3. Session 4's integration tests now fail (e.g., `assert "use-jwt" in stdout` may still pass, but format-specific assertions will break)
4. Session 4 must be reworked

**Specific tests affected:**
- `TestRetrieveIntegration.test_matching_prompt_returns_memories` (line 218) -- checks `"<memory-context" in stdout` -- this still works
- `TestRetrieveIntegration.test_category_priority_sorting` (line 245) -- parses lines with `l.startswith("- [")` -- format change could break the extraction
- Any new tests that parse the output format (FTS5 integration tests from Session 4's plan)

**Additionally:** Session 5 depends on BM25 scores, which only exist after Session 2. So Session 5 CANNOT start before Session 2. The user got this part right -- both start after Session 2. But they CONFLICT with each other.

### Verdict: WRONG -- Sessions 4 and 5 CANNOT run in parallel

The correct ordering is: Session 5 (annotations, ~20 LOC, ~1-2 hours) BEFORE Session 4 (tests, ~4-6 hours). Rationale:
- Session 5 is small (20 LOC) and fast
- Session 5 changes the output format that tests must validate
- Session 4 is large and tests should be written against the FINAL output format
- Writing tests against an intermediate format guarantees rework

**Severity: HIGH.** This is the most impactful error in the dependency graph.

---

## 5. Session 6 Prerequisites (Measurement Gate)

### User's Claim
Session 6 depends on Sessions 4 (tests) and 5 (annotations).

### Analysis

Session 6 (measurement gate) runs 20 real queries against the FTS5+confidence system and measures precision. It needs:

1. **FTS5 engine working** -- from Session 2
2. **Confidence annotations working** -- from Session 5
3. **Tests passing** -- from Session 4 (ensures no regressions)
4. **Search skill?** -- from Session 3

Does Session 6 need Session 3 (search skill)?

The measurement gate (rd-08, lines 351-358) measures auto-inject precision, not search precision. The gate prompt says "For each prompt, record which injected memories are relevant." This is testing the `UserPromptSubmit` hook path (auto-inject), not the `/memory:search` path.

However, if Session 3 refactors `memory_retrieve.py` to import from `memory_search_engine.py`, then Session 6 must run AFTER Session 3 because `memory_retrieve.py` would break without `memory_search_engine.py` existing.

**Checking the import chain:** The plan (rd-08, lines 293-295) shows:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_search_engine import build_fts_index, query_fts
```

If this import is at module level (unconditional), `memory_retrieve.py` will crash without `memory_search_engine.py`. If it's conditional or lazy, it might work. The plan doesn't specify -- but extracting shared functions into a module and then importing them back is most naturally done as a top-level import.

### Verdict: INCOMPLETE

Session 6 prerequisites should include Session 3 if Session 3's refactoring changes `memory_retrieve.py`'s import dependencies. The user only lists Sessions 4 and 5.

**Correct prerequisites for Session 6:** Sessions 2, 3, 4, AND 5 (though 2 is transitively covered by 3, 4, 5).

---

## 6. Session 7 -> Session 8 Dependency (Judge Tests)

### User's Claim
Sessions 7->8->9 are strictly sequential.

### Analysis

**Session 7 creates `hooks/scripts/memory_judge.py` (~140 LOC).** The code is fully specified in rd-08 (lines 509-745).

**Session 8 creates `tests/test_memory_judge.py` (~200 LOC).** The test list (rd-08, lines 877-895) tests specific functions:
- `test_call_api_success` -- tests `call_api()` from `memory_judge.py`
- `test_format_judge_input_shuffles` -- tests `format_judge_input()` from `memory_judge.py`
- `test_parse_response_valid_json` -- tests `parse_response()` from `memory_judge.py`
- `test_judge_candidates_integration` -- tests `judge_candidates()` from `memory_judge.py`
- `test_extract_recent_context` -- tests `extract_recent_context()` from `memory_judge.py`

Since all tested functions are in `memory_judge.py` (Session 7), the tests import from that module. So Session 8 genuinely depends on Session 7 for the import targets.

**However:** A test-first approach could write test stubs/skeletons before Session 7:
- Test file structure, imports, fixture setup
- Test docstrings and expected behaviors
- Mock definitions for `urllib.request.urlopen`
- Test cases for `parse_response()` and `_extract_indices()` (pure functions with well-defined I/O per the plan)

The actual test bodies that call `from memory_judge import ...` would fail until Session 7 is done, but the test framework/fixtures could be prepared.

### Verdict: PARTIALLY WRONG

The hard dependency is real (tests import from `memory_judge.py`), but:
- Test stubs, fixtures, and mock setups (~30-40% of test writing work) can be prepared before Session 7
- The plan fully specifies all function signatures and behaviors, enabling true TDD

**Practical recommendation:** Not worth formal parallel scheduling for a one-person project. But if Session 7 takes longer than expected, test prep could start immediately.

---

## 7. Circular Dependency Check

### Analysis

Drawing the dependency edges:
```
S1 -> S2 -> S3 -> S6
            S5 -> S6
            S4 -> S6
S6 -> S7 -> S8 -> S9
```

With corrected dependencies:
```
S1 -> S2 -> S3 -+
           |    |
           +-> S5 -> S4 -> S6 -> S7 -> S8 -> S9
```

No cycles. The graph is a DAG (directed acyclic graph).

### Verdict: CONFIRMED NO CIRCULAR DEPENDENCIES

---

## 8. Corrected Dependency Graph

### User's Original Graph
```
S1 -> S2 -> S3
       |
       +---> S4 (parallel)
       +---> S5 (parallel)
              |
              +-> S6 -> S7 -> S8 -> S9
```

### Corrected Graph
```
S1 -> S2 -> S3 -> S5 -> S4 -> S6 -> S7 -> S8 -> S9
```

**This is a linear chain.** No meaningful parallelism exists.

### Rationale for linearization:

| Edge | Why it must be sequential |
|------|--------------------------|
| S1 -> S2 | Session 2's `score_with_body()` uses `extract_body_text()` (S1b) and `tokenize()` (S1a) |
| S2 -> S3 | Session 3 extracts functions written in S2 into `memory_search_engine.py` |
| S3 -> S5 | Session 5 adds `confidence_label()` which depends on BM25 scores (S2), but S3 must complete first because S3 refactors `memory_retrieve.py` and S5 also modifies it -- concurrent edits to the same file |
| S5 -> S4 | Session 4 writes tests against the output format. Session 5 changes the output format. Tests must target the final format. |
| S4 -> S6 | Session 6 needs tests passing (S4) to ensure the system works correctly before measurement |
| S6 -> S7 | Session 7 is conditional on S6 showing precision < 80% |
| S7 -> S8 | Session 8 tests functions created in S7 |
| S8 -> S9 | Session 9 extends judge with dual verification, needs single judge working + tested |

### Alternative: Slight Parallelism Recovery

If Session 3's refactoring is designed to NOT require `memory_retrieve.py` to import from `memory_search_engine.py` (i.e., code duplication instead of extraction), then:

```
S1 -> S2 -> S5 -> S4 -> S6 -> S7 -> S8 -> S9
       |
       +-> S3 (parallel, independent file, no import back into retrieve)
```

This recovers S3 parallelism but means maintaining duplicate FTS5 code in two files. The plan explicitly rejects this (rd-08, line 276: "Extract search logic into `memory_search_engine.py`").

### Schedule Impact

User's original estimate: "~4-5 focused days" (with parallelism assumed)
Corrected (linear): The total work is unchanged, but elapsed time increases because parallelism is lost.

| Session | Estimated Time | Cumulative |
|---------|---------------|------------|
| S1 | 4-6 hours | 4-6 hours |
| S2 | 6-8 hours | 10-14 hours |
| S3 | 4-6 hours | 14-20 hours |
| S5 | 1-2 hours | 15-22 hours |
| S4 | 4-6 hours | 19-28 hours |
| S6 | 2 hours | 21-30 hours |
| S7 (conditional) | 4-6 hours | 25-36 hours |
| S8 (conditional) | 4-6 hours | 29-42 hours |
| S9 (conditional) | 2-4 hours | 31-46 hours |

Mandatory sessions (S1-S6): 19-30 hours (~3-4 focused days)
With conditional sessions (S7-S9): 31-46 hours (~5-6 focused days)

This is about 1 day longer than the user's original estimate for the full plan.

---

## Detailed Function-Level Dependency Map

For completeness, here is every function referenced in the plan and where it comes from/goes to:

| Function | Created In | Used By | File |
|----------|-----------|---------|------|
| `_TOKEN_RE` (new regex) | S1 (1a) | `tokenize()`, indirectly by S2's query path | `memory_retrieve.py` line 54 |
| `tokenize()` | EXISTS (line 63) but S1 fixes regex | `score_with_body()` (S2), `score_entry()` (exists) | `memory_retrieve.py` |
| `extract_body_text()` | S1 (1b) | `score_with_body()` (S2), full-body index (S3) | `memory_retrieve.py` then extracted to `memory_search_engine.py` (S3) |
| `HAS_FTS5` | S1 (1c) | FTS5 fallback conditional (S2) | `memory_retrieve.py` |
| `build_fts_index_from_index()` | S2 | `main()` in `memory_retrieve.py`, extracted to `memory_search_engine.py` (S3) | `memory_retrieve.py` -> `memory_search_engine.py` |
| `build_fts_query()` | S2 | `score_with_body()`, `main()` | `memory_retrieve.py` -> `memory_search_engine.py` |
| `query_fts()` | S2 | `score_with_body()`, `main()` | `memory_retrieve.py` -> `memory_search_engine.py` |
| `score_with_body()` | S2 | `main()` in `memory_retrieve.py` | `memory_retrieve.py` |
| `apply_threshold()` | S2 | `main()` in `memory_retrieve.py` | `memory_retrieve.py` |
| `parse_index_line()` | EXISTS (line 72) | `build_fts_index_from_index()` (S2) | `memory_retrieve.py` |
| `confidence_label()` | S5 | output formatting in `main()` | `memory_retrieve.py` |
| `memory_search_engine.py` CLI | S3 | `SKILL.md` (S3), tests (S4) | `hooks/scripts/memory_search_engine.py` |
| `judge_candidates()` | S7 | `memory_retrieve.py` integration (S7), tests (S8) | `hooks/scripts/memory_judge.py` |
| `call_api()` | S7 | `judge_candidates()` | `hooks/scripts/memory_judge.py` |
| `format_judge_input()` | S7 | `judge_candidates()`, tests (S8) | `hooks/scripts/memory_judge.py` |
| `parse_response()` | S7 | `judge_candidates()`, tests (S8) | `hooks/scripts/memory_judge.py` |
| `extract_recent_context()` | S7 | `judge_candidates()`, tests (S8) | `hooks/scripts/memory_judge.py` |

---

## Recommendations

1. **Reorder Session 5 before Session 4.** This is the highest-impact fix. Session 5 is small (~20 LOC, 1-2 hours) and changes the output format that Session 4 must test against.

2. **Ensure Session 3 completes before Session 4.** Tests must cover `memory_search_engine.py` and the import chain from `memory_retrieve.py`.

3. **Accept the linear chain.** For a single-developer project, the linear ordering (S1->S2->S3->S5->S4->S6->S7->S8->S9) is cleaner and avoids rework. The parallelism claimed in the original plan does not hold up under analysis.

4. **Consider merging Sessions 1+2** into a single session. Session 1 is only ~80 LOC and takes 4-6 hours. Session 2 is the natural continuation. The split creates an artificial boundary.

5. **Consider merging Sessions 3+5** into a single session. Session 3 (search skill extraction) and Session 5 (confidence annotations) both modify `memory_retrieve.py` and are relatively small. Doing them together avoids two separate edit-test cycles on the same file.

6. **If parallelism is desired**, the only safe option is: design Session 3 so that `memory_search_engine.py` is a standalone module that does NOT require `memory_retrieve.py` to import from it. Instead, `memory_retrieve.py` keeps its own inline FTS5 code, and `memory_search_engine.py` duplicates/adapts it for the search skill. This sacrifices DRY but enables true parallelism of S3 with S5+S4.
