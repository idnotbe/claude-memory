# S4 Verification Round 1: Correctness Review

**Reviewer:** v1-correctness
**Date:** 2026-02-21
**Verdict:** PASS (with 2 minor observations)

---

## Scope

Reviewed all 4 changed/created files in Session 4:

| File | Change Type | LOC |
|------|-------------|-----|
| tests/test_adversarial_descriptions.py | Modified (import fix) | ~5 lines changed |
| tests/test_fts5_search_engine.py | NEW | ~294 lines, 18 tests |
| tests/test_fts5_benchmark.py | NEW | ~146 lines, 5 tests |
| tests/conftest.py | Modified (factories + fixture) | ~100 lines added |

Cross-referenced against source files:
- hooks/scripts/memory_search_engine.py (500 lines)
- hooks/scripts/memory_retrieve.py (505 lines)

---

## Verification Method

1. Read all 4 changed files and 2 source files completely
2. Ran all 143 tests across the 3 test files (all pass)
3. Independently verified every test assertion against source code logic
4. Manually executed scoring functions to confirm expected values
5. Traced body extraction for all 6 categories
6. Ran benchmarks 3x to verify stability (50-60ms per run, well under 100ms limit)
7. Deep-traced hybrid scoring (score_with_body) step by step

---

## File-by-File Review

### 1. tests/test_adversarial_descriptions.py (import fix)

**Change:** Hard import of `score_description` replaced with conditional `try/except ImportError` pattern (lines 31-35). Added `_require_score_description()` guard to 8 test methods.

**Correctness:** PASS
- Import pattern matches `tests/test_memory_retrieve.py` lines 31-34 (consistency)
- `score_description` IS currently importable (confirmed), so tests run (not skipped)
- The 9th test (`test_score_entry_with_unicode_tokens`) correctly uses `score_entry` not `score_description`, so no guard needed
- All 8 guarded tests call `self._require_score_description()` before using `score_description`

**No issues found.**

### 2. tests/test_fts5_search_engine.py (18 tests)

#### TestFTS5IndexBuild (3 tests) -- PASS
- `test_basic_build_and_query`: Correct. Builds 2 entries, queries for ["jwt", "authentication"], expects first result to match. Verified: FTS5 query becomes `"jwt"* OR "authentication"*`, matches "JWT authentication decision". Query construction confirmed correct.
- `test_build_with_body`: Correct. Sets `include_body=True`, inserts body text "Migrate postgres to version 15", queries for ["postgres"]. Verified: body column is indexed and searchable.
- `test_no_match_returns_empty`: Correct. Queries for ["kubernetes"] against JWT-only entries. Returns [].

#### TestSmartWildcard (4 tests) -- PASS
- `test_compound_token_exact_match`: Verified. `build_fts_query(["user_id"])` returns `'"user_id"'` (no wildcard). Source code line 220: `any(c in cleaned for c in '_.-')` is True for "user_id".
- `test_single_token_prefix_wildcard`: Verified. `build_fts_query(["auth"])` returns `'"auth"*'`. Source code line 223.
- `test_mixed_compound_and_single`: Correct. Both strategies present in one query, joined by " OR ".
- `test_wildcard_matches_prefix_in_index`: Correct end-to-end test. "auth"* matches "authentication" in FTS5.

#### TestBodyExtraction (7 tests) -- PASS
All 7 tests verified against actual factory output:
- Decision: body contains "stateless" and "jwt" (from content.context and content.decision)
- Runbook: body contains "connection" (from content.trigger)
- Constraint: body contains "10mb" (from content.rule) or "payload" (from content.impact)
- Tech_debt: body contains "v1" (from content.description) or "api" (from content.description)
- Preference: body contains "typescript" (from content.value) or "type safety" (from content.reason)
- Session_summary: body contains "test" (from content.goal and content.completed)
- `test_all_body_fields_categories_covered`: Exhaustive check -- every BODY_FIELDS key has a factory producing non-empty body. Verified against BODY_FIELDS dict (6 categories).

#### TestHybridScoring (2 tests) -- PASS with observation

- `test_body_bonus_improves_ranking`: **Weak assertion** (see Observation #1 below). Test passes but the ranking assertion at line 206 (`if len(results) >= 2`) never fires because `apply_threshold` noise floor filters out the no-body entry. The test still verifies `len(results) >= 1` and entry creation, but does not exercise the ranking claim in its docstring.

- `test_body_bonus_capped_at_3`: Correct. Verified: `score_with_body` sets `body_bonus = min(3, len(body_matches))` (source line 247). Test assertion `r.get("body_bonus", 0) <= 3` is correct. Confirmed body_bonus field IS present in results.

#### TestFTS5Fallback (2 tests) -- PASS
- `test_cli_search_returns_empty_when_no_fts5`: Correct. Uses `with patch("memory_search_engine.HAS_FTS5", False)` -- context manager ensures proper cleanup. Source code `cli_search` line 385: `if not HAS_FTS5: return []`.
- `test_retrieve_falls_back_to_legacy_scoring`: Correct. Sets `match_strategy: "title_tags"` in config, which bypasses FTS5 path (source line 395: `if HAS_FTS5 and match_strategy == "fts5_bm25"`). Verifies legacy keyword scoring finds the JWT entry.

**Note:** `_restore_fts5` fixture (line 242-244) is a noop (yield with no save/restore). Not a bug -- tests use context managers for mocking. Just unnecessary boilerplate.

### 3. tests/test_fts5_benchmark.py (5 tests)

All 5 tests -- PASS

- `_memories_to_entries` helper: Correct. Category transform `cat.upper().replace(' ', '_')` matches `parse_index_line` output format. `FOLDER_MAP` imported from conftest correctly maps all 6 categories.
- `test_500_doc_index_build_under_limit`: Correct. Verifies 500 entries, measures only `build_fts_index` time. 100ms threshold generous (actual: ~2ms).
- `test_500_doc_query_under_limit`: Correct. Builds index first (not timed), then times query only.
- `test_500_doc_full_cycle_under_limit`: Correct. Times build + tokenize + query + threshold. Also verifies correctness: `len(filtered) <= 5` (max_inject=5), result structure (title, path, score keys).
- `test_500_doc_results_are_correct`: Correct. "timeout crash" should match RUNBOOK category. Verified: "timeout" and "crash" appear in `_BULK_KEYWORDS["runbook"]`. All 500 RUNBOOK entries contain "timeout" or "crash" in titles via keyword rotation.
- `test_500_doc_with_body_under_limit`: Correct. Adds synthetic body text, indexes with `include_body=True`, queries and verifies results found.

**Benchmark stability:** Ran 3x, consistent at 50-60ms total for all 5 tests. No timing flakiness risk with 100ms threshold.

### 4. tests/conftest.py (factory updates + bulk fixture)

**Factory updates -- PASS**
- `make_session_memory`: Added `in_progress`, `blockers`, `key_changes` -- matches BODY_FIELDS["session_summary"] which includes these fields. Verified all fields extracted by `extract_body_text`.
- `make_runbook_memory`: Added `environment` -- matches BODY_FIELDS["runbook"] which includes "environment". Verified.
- `make_tech_debt_memory`: Added `acceptance_criteria` -- matches BODY_FIELDS["tech_debt"] which includes "acceptance_criteria". Verified.
- All changes are additive (new keys in content dicts). No signatures changed. Backward-compatible.

**bulk_memories fixture -- PASS**
- Generates exactly 500 memories (verified programmatically)
- Distribution: 83-84 per category (6 categories, 500 % 6 = 2 remainder)
- Each entry has unique id (`bulk-{cat}-{i:04d}`), unique title, 3 tags
- Keyword pools are realistic for FTS5 testing (e.g., "timeout", "crash" for runbook)
- No shared mutable state -- fixture returns a new list each time

---

## Test Isolation Check

| Test Class | Isolation | Mechanism |
|-----------|-----------|-----------|
| TestFTS5IndexBuild | GOOD | Each test creates its own FTS5 connection, closes it |
| TestSmartWildcard | GOOD | Pure function tests, no state |
| TestBodyExtraction | GOOD | Factory functions return new dicts each time |
| TestHybridScoring | GOOD | Uses tmp_path fixture (unique per test) |
| TestFTS5Fallback | GOOD | Context manager (patch) and tmp_path |
| TestFTS5Benchmark | GOOD | bulk_memories fixture returns new list each call |

No shared mutable state between tests. No class-level state. No global mutation.

---

## Observations

### Observation #1: Weak Assertion in test_body_bonus_improves_ranking (MINOR)

**File:** tests/test_fts5_search_engine.py:206
**Issue:** The ranking assertion `if len(results) >= 2: assert results[0]["path"].endswith("with-body.json")` never fires because `apply_threshold` noise floor filters the no-body entry. After body bonus, with-body gets score -1.000001 but no-body gets -0.000001. The 25% noise floor (0.25000025) exceeds no-body's abs score (0.000001), so it's filtered.

**Impact:** LOW. The test still verifies: (a) results are non-empty, (b) body bonus creates results. It just doesn't verify the ranking claim in its docstring. Not a false positive (it doesn't assert something wrong), just weaker than intended.

**Fix (optional):** Either increase max_inject or lower the noise floor threshold, or add both entries' titles to contain a common keyword matching the query so both survive thresholding. Or simply remove the `if len(results) >= 2` guard and instead fix the test setup to guarantee 2 results.

### Observation #2: Noop _restore_fts5 Fixture (TRIVIAL)

**File:** tests/test_fts5_search_engine.py:242-244
**Issue:** The `_restore_fts5` autouse fixture does nothing -- it just yields. Tests already use `with patch(...)` context managers for mocking.

**Impact:** NONE. Just unnecessary code. Could be removed for cleanliness.

---

## Cross-Reference Summary

| Test Assertion | Source Code Reference | Verified |
|---------------|----------------------|----------|
| `build_fts_query(["user_id"])` == `'"user_id"'` | memory_search_engine.py:220-221 | YES |
| `build_fts_query(["auth"])` == `'"auth"*'` | memory_search_engine.py:222-223 | YES |
| `score_description` cap at 2 | memory_retrieve.py:106 `min(2, ...)` | YES |
| `score_description` round-half-up | memory_retrieve.py:106 `int(score + 0.5)` | YES |
| `body_bonus` cap at 3 | memory_retrieve.py:247 `min(3, ...)` | YES |
| `cli_search` returns [] when !HAS_FTS5 | memory_search_engine.py:385-386 | YES |
| `match_strategy="title_tags"` bypasses FTS5 | memory_retrieve.py:395 | YES |
| `apply_threshold` respects max_inject | memory_search_engine.py:289 `return results[:limit]` | YES |
| BODY_FIELDS covers 6 categories | memory_search_engine.py:65-75 | YES |
| extract_body_text truncates at 2000 | memory_search_engine.py:152 `[:2000]` | YES |
| Noise floor at 25% of best | memory_search_engine.py:284-287 | YES |

---

## Verdict

**PASS** -- All 23 new tests (18 FTS5 + 5 benchmark) are correct. All assertions match source code behavior. Test isolation is clean. No false positives, no incorrect expected values. Two minor observations noted (weak ranking assertion, noop fixture) -- neither affects test suite validity.

Full test suite: 659 passed, 0 failed, 0 errors.
