# Phase C: Audit Actions A-10 and A-11

**Date:** 2026-02-25
**Status:** Complete
**Test count:** 916 (all passing, up from 875)

---

## A-10: Non-Triggered Category Scores in triage.score

### Problem

The `triage.score` event only logged categories that exceeded their threshold (`triggered`), not ALL 6 category scores. This made post-hoc threshold tuning analysis impossible because you couldn't see what scores the non-triggered categories received.

### Changes

**`hooks/scripts/memory_triage.py`:**
1. Added `score_all_categories(text, metrics) -> list[dict]` function (lines 453-485). This mirrors the scoring logic of `run_triage()` but:
   - Returns ALL 6 categories (5 text-based + SESSION_SUMMARY)
   - Excludes snippets (privacy/payload size)
   - Rounds scores to 4 decimal places
   - Does NOT apply threshold filtering
2. Updated the `emit_event("triage.score", ...)` call site (around line 1035) to include `all_scores` alongside the existing `triggered` field.

**Backwards compatibility:** Fully preserved. The `triggered` field is unchanged. `all_scores` is purely additive.

### Schema Update

Updated `temp/p2-logger-schema.md` to document the new `all_scores` field:
- `all_scores` (list[object]): ALL 6 category scores. Each entry: `{category, score}`.

### Tests Added (11 tests)

**`TestScoreAllCategories`** (9 tests):
- `test_returns_all_six_categories` -- always returns exactly 6 entries
- `test_returns_all_categories_even_with_empty_text` -- empty text returns 6 zero scores
- `test_category_names_match_expected` -- matches CATEGORY_PATTERNS + SESSION_SUMMARY
- `test_no_snippets_in_output` -- no snippets key in any entry
- `test_only_category_and_score_keys` -- exactly {category, score} per entry
- `test_scores_are_rounded_to_4_decimals` -- rounding precision
- `test_triggered_category_has_nonzero_score` -- keyword match produces nonzero score
- `test_session_summary_nonzero_with_activity` -- activity metrics produce nonzero score
- `test_consistency_with_run_triage` -- triggered scores match between both functions

**`TestTriageScoreEmitAllScores`** (2 tests):
- `test_all_scores_in_triage_score_data` -- emit_event output contains all_scores with 6 entries
- `test_all_scores_backwards_compatible_with_triggered` -- triggered field still present, is subset of all_scores

---

## A-11: Non-Deterministic Set Serialization Defense

### Problem

`json.dumps(default=str)` converts Python `set` objects to non-deterministic strings like `"{'a', 'b'}"`. The iteration order of sets is not guaranteed across Python runs, making log output non-reproducible and harder to query.

### Changes

**`hooks/scripts/memory_logger.py`:**
1. Added `_json_default(obj)` function (lines 205-213) that:
   - Converts `set` and `frozenset` to `sorted(obj, key=str)` for deterministic output
   - Falls back to `str()` for other non-serializable types (datetime, etc.)
2. Replaced `default=str` with `default=_json_default` in the `json.dumps()` call inside `emit_event()`.

**Behavior change:**
- **Old:** `{"tags": {"b", "a"}}` serialized as `"tags":"{'b', 'a'}"` (string, non-deterministic order)
- **New:** `{"tags": {"b", "a"}}` serialized as `"tags":["a","b"]` (JSON array, deterministic sorted order)

This is a format change for log consumers. Sets are now proper JSON arrays instead of Python `repr()` strings. This improves queryability with `jq` and other JSON tools.

### Tests Updated and Added (12 tests)

**Updated:**
- `TestNonSerializableData::test_set_in_data_converted_to_sorted_list` -- updated from checking `isinstance(str)` to verifying sorted list output

**`TestJsonDefaultSerializer`** (7 tests):
- `test_set_serialized_as_sorted_list` -- set -> sorted list
- `test_frozenset_serialized_as_sorted_list` -- frozenset -> sorted list
- `test_empty_set_serialized_as_empty_list` -- edge case
- `test_empty_frozenset_serialized_as_empty_list` -- edge case
- `test_datetime_uses_str_fallback` -- str() fallback preserved
- `test_set_with_mixed_types_sorted_by_str` -- mixed int types sorted by str repr
- `test_set_determinism_across_calls` -- 10 iterations produce identical output

**`TestSetSerializationInEmitEvent`** (4 tests):
- `test_set_in_data_produces_sorted_list_in_jsonl` -- end-to-end through emit_event
- `test_frozenset_in_data_produces_sorted_list_in_jsonl` -- end-to-end frozenset
- `test_normal_types_unaffected` -- dict, list, str, int, None, bool unchanged
- `test_nested_set_in_data` -- set nested inside list inside data dict

---

## External Review (Gemini 3.1 Pro via clink)

**Verdict:** Both implementations are production-ready with no critical risks.

Key findings:
1. `sorted(obj, key=str)` correctly handles mixed-type sets in Python 3 by comparing stringified versions.
2. `score_all_categories` is an exact functional mirror of `run_triage` scoring logic.
3. The `default=str` -> `_json_default` change is a format change for downstream log parsers (sets become JSON arrays instead of Python repr strings). This is strictly an improvement for queryability.
4. Edge cases covered: broken `__str__` methods are caught by emit_event's fail-open `try/except`; empty transcripts safely produce all-zero scores.

---

## Files Modified

| File | Change |
|------|--------|
| `hooks/scripts/memory_logger.py` | Added `_json_default()`, replaced `default=str` |
| `hooks/scripts/memory_triage.py` | Added `score_all_categories()`, updated emit_event call site |
| `tests/test_memory_logger.py` | Updated 1 test, added 22 new tests (4 classes) |
| `temp/p2-logger-schema.md` | Documented `all_scores` field in triage.score event |
