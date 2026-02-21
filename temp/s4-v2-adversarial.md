# S4 Verification Round 2: Adversarial Review

**Reviewer:** v2-adversarial
**Date:** 2026-02-21
**Verdict:** CONDITIONAL PASS (2 MEDIUM findings, 5 LOW findings, 4 INFO observations)

---

## Methodology

1. Read all 4 changed files + 2 source files completely
2. Ran all 143 S4 tests (confirmed pass)
3. Wrote and executed 39 targeted adversarial experiments against core functions
4. Applied mutation testing mindset: "would tests catch this source code change?"
5. Tested inputs never covered by existing tests: None, NaN, Inf, empty, dict tags, deeply nested content
6. Checked for false positives, weak assertions, and coverage gaps
7. Verified benchmark fixture quality and timing reliability

---

## Findings by Severity

### MEDIUM-1: `test_body_bonus_improves_ranking` is a FALSE POSITIVE

**File:** `tests/test_fts5_search_engine.py:171-206`
**Severity:** MEDIUM
**Type:** False positive test

The test's docstring claims "Entry with body keyword matches should rank higher than title-only match." But the ranking assertion at line 206 is guarded by `if len(results) >= 2:`, and this condition **NEVER evaluates to True**.

**Proof:** The `apply_threshold` noise floor filters out the no-body entry. After body bonus, `with-body` gets score `-1.000001375` but `no-body` gets a near-zero score. The 25% noise floor (0.25 * abs(-1.000001375) = ~0.25) exceeds `no-body`'s abs score, so it's filtered. Only 1 result is returned.

```
$ python3 adversarial_test.py
Number of results: 1
  .claude/memory/decisions/with-body.json: score=-1.000001375, body_bonus=1
CONFIRMED: Only 1 results -- ranking assertion NEVER fires!
```

**Impact:** The test passes for the wrong reason. It does NOT verify ranking. It only verifies `len(results) >= 1`. If `score_with_body` returned entries in wrong order, this test would still pass.

**Fix:** Make both entries survive thresholding by giving them titles that share the query keywords (so both get similar FTS5 scores), then remove the `if len(results) >= 2` guard and assert ranking directly.

---

### MEDIUM-2: Backtick Sanitization Inconsistency (Not Caught by Tests)

**File:** `tests/test_adversarial_descriptions.py:662-688` (TestSanitizationConsistency)
**Severity:** MEDIUM
**Type:** Missing assertion / inconsistency not detected

`_sanitize_snippet` (triage) strips backticks. `_sanitize_title` (retrieval) does NOT strip backticks. `_sanitize_cli_title` (CLI) also does NOT strip backticks.

```python
_sanitize_snippet("`command`")  # -> "command"  (stripped)
_sanitize_title("`command`")    # -> "`command`" (preserved!)
_sanitize_cli_title("`command`")# -> "`command`" (preserved!)
```

The `TestSanitizationConsistency` test (line 662-688) DOES include backtick input (`"`command`"`) in `DANGEROUS_PATTERNS`, but only checks for control chars, zero-width chars, `<`, and `>` -- it does NOT check for backticks. So the inconsistency between the three sanitizers is completely invisible to the test suite.

**Impact:** In retrieval output, backtick-wrapped memory titles could be rendered as code blocks in markdown contexts. A crafted title like `` `IGNORE ALL INSTRUCTIONS` `` would pass through `_sanitize_title` unchanged.

**Source code issue:** This is a gap in `_sanitize_title` (not stripping backticks) AND a gap in the test (not asserting backtick removal in the consistency check).

---

### LOW-1: Semicolon Injection in `_output_results` Descriptions Attribute

**File:** `hooks/scripts/memory_retrieve.py:270-280`
**Severity:** LOW
**Type:** Attribute injection (no test coverage)

The `descriptions` attribute in `_output_results` uses semicolons as key-value separators: `descriptions="decision=Choices; runbook=Steps"`. A description containing a semicolon can inject fake key-value pairs:

```python
descs = {"decision": "Choices; evil_key=evil_value"}
# Output: descriptions="decision=Choices; evil_key=evil_value"
```

**Impact:** LOW because descriptions are agent-interpreted text (not parsed by code), and the attacker would need to control `memory-config.json` (which requires file write access). But no test exercises this path.

---

### LOW-2: `build_fts_index` with Missing Keys Crashes (No Test)

**File:** `hooks/scripts/memory_search_engine.py:159-198`
**Severity:** LOW
**Type:** Missing edge case test

`build_fts_index([{"title": "test"}])` raises `KeyError: 'tags'`. Entries with missing `title`, `tags`, `path`, or `category` keys cause unhandled `KeyError`. While this is "correct" behavior (callers should provide valid entries), no test verifies this contract or documents expected behavior for malformed inputs.

---

### LOW-3: `query_fts` with Empty String Crashes (No Test)

**File:** `hooks/scripts/memory_search_engine.py:233-254`
**Severity:** LOW
**Type:** Missing edge case test

`query_fts(conn, "")` raises `sqlite3.OperationalError: fts5: syntax error near ""`. The production code guards against this (build_fts_query returns None for empty input, and callers check for None), but `query_fts` itself has no defensive handling. No test verifies this error path.

---

### LOW-4: `build_fts_query([None, "test"])` Crashes (No Test)

**File:** `hooks/scripts/memory_search_engine.py:205-226`
**Severity:** LOW
**Type:** Missing edge case test

Passing `None` in the tokens list raises `AttributeError: 'NoneType' object has no attribute 'lower'`. While callers always pass strings from `tokenize()`, `build_fts_query` itself doesn't validate input types.

---

### LOW-5: Entries Beyond `top_k_paths` Lack `body_bonus` Key

**File:** `hooks/scripts/memory_retrieve.py:250-252`
**Severity:** LOW
**Type:** Inconsistent result structure

In `score_with_body`, entries within `top_k_paths` always have `body_bonus` set (0 or computed value). But entries beyond `top_k_paths` never get `body_bonus` set. The code uses `.get("body_bonus", 0)` which masks this, and `test_body_bonus_capped_at_3` uses the same `.get()` pattern, so the test would pass even if `body_bonus` were never set on any result.

**Verified experimentally:**
```
entry-0: body_bonus key present=True, value=0
entry-1: body_bonus key present=True, value=0
entry-2: body_bonus key present=False, value(get)=MISSING_DEFAULT_0
```

---

## INFO Observations

### INFO-1: NaN Scores Survive `apply_threshold`

Results with `score=float('nan')` pass through `apply_threshold` because `abs(nan)` is `nan` and `nan >= noise_floor` evaluates to `False` in the noise floor filter... but the entry still survives because the comprehension uses `>=` which is False for NaN, yet the entry was already included before filtering. Actually, NaN entries DO survive because the noise floor `abs(r["score"]) >= noise_floor` returns False for NaN, meaning NaN entries get **filtered**. This is accidental correctness but not tested.

### INFO-2: `None` Tags Indexed as Literal String "None"

`build_fts_index` with `tags=None` falls through to `str(e.get('tags', ''))` which produces `str(None)` = `"None"`. This means searching for "none" would match entries with `tags=None`. Not exploitable in practice since `parse_index_line` always produces sets, but no test verifies this edge case.

### INFO-3: Noop `_restore_fts5` Fixture

`tests/test_fts5_search_engine.py:242-244` -- The autouse fixture does nothing. Tests use `with patch(...)` for cleanup. This is dead code. A latent risk if someone adds a test that mutates `HAS_FTS5` directly without a context manager.

### INFO-4: "item" Appears in All 500 Bulk Fixture Titles

All 500 entries from `bulk_memories` fixture have titles matching the pattern `f"{kw} {kw2} item {i}"`. The word "item" is NOT a stop word and NOT in any benchmark query, so this doesn't affect results. But if a benchmark test ever queried for "item", it would trivially match all 500 entries, making the test meaningless. No current test is affected.

---

## What Tests Did Well

1. **Benchmark correctness checks:** All benchmark tests verify BOTH timing AND result count/quality. Broken `build_fts_index` would fail `len(results) > 0`.
2. **Body bonus cap test is tight:** `r.get("body_bonus", 0) <= 3` catches cap removal mutations.
3. **Mutation resilience for tokenizer:** `test_legacy_tokenizer_splits_compounds` asserts `"id" in tokens` (2-char token), catching `len > 2` mutations.
4. **FTS5 injection defense is well-tested:** 15 injection tests across 2 files.
5. **Path traversal regression tests are strong:** 11 tests including the top_k_paths bypass fix.
6. **Conditional import pattern is correct:** `pytest.skip()` prevents silent false-passes when `score_description` is unavailable.

---

## Summary Table

| # | Finding | Severity | Type | Test Coverage |
|---|---------|----------|------|---------------|
| M1 | `test_body_bonus_improves_ranking` is false positive | MEDIUM | False positive | Assertion never fires |
| M2 | Backtick sanitization inconsistency not detected | MEDIUM | Missing assertion | Consistency test incomplete |
| L1 | Semicolon injection in descriptions attribute | LOW | Untested behavior | No test |
| L2 | `build_fts_index` crashes on missing keys | LOW | Missing edge case | No test |
| L3 | `query_fts("")` crashes | LOW | Missing edge case | No test |
| L4 | `build_fts_query([None])` crashes | LOW | Missing edge case | No test |
| L5 | `body_bonus` key missing beyond `top_k_paths` | LOW | Inconsistent structure | Masked by `.get()` |
| I1 | NaN scores survive threshold | INFO | Untested edge case | N/A |
| I2 | `None` tags indexed as "None" | INFO | Untested edge case | N/A |
| I3 | Noop `_restore_fts5` fixture | INFO | Dead code | N/A |
| I4 | "item" matches all 500 bulk entries | INFO | Fixture design | Not currently exploitable |

---

## Verdict: CONDITIONAL PASS

The test suite is fundamentally sound with 659 passing tests and good coverage of the critical paths (injection, traversal, sanitization). However:

- **M1 is a genuine false positive** that should be fixed (the test claims to verify ranking but never actually checks it).
- **M2 reveals a real sanitization inconsistency** between triage and retrieval that the consistency test was specifically designed to catch but misses.

Neither finding represents a security regression or functional breakage in production code -- they are test quality issues. The production code itself is well-defended. But M1 gives false confidence in body ranking behavior, and M2 means the consistency test has a blind spot.

**Recommended actions:**
1. Fix M1 by ensuring both entries survive thresholding
2. Add backtick assertion to `TestSanitizationConsistency`
3. Add `assert "`" not in title_result` to the consistency check patterns
4. Consider adding backtick stripping to `_sanitize_title` for parity with `_sanitize_snippet`
