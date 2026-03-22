# Implementation Log: Expose Booster Hit Counts in Triage Score Logging

**Date:** 2026-03-22
**File:** `hooks/scripts/memory_triage.py`

## Changes Made

### 1. `score_text_category` return type (lines 355-404)
- Changed return type annotation from `tuple[float, list[str]]` to `tuple[float, list[str], int, int]`.
- Updated docstring to document the two new return values (`primary_hit_count`, `boosted_hit_count`).
- Early return for missing config now returns `0.0, [], 0, 0` (4-tuple).
- Final return now includes `primary_count, boosted_count` (already tracked as locals).

### 2. `_score_all_raw` function (lines 431-464)
- Text-category loop: destructures 4 values (`score, snippets, p_hits, b_hits`) and adds `primary_hits` / `booster_hits` keys to each dict.
- SESSION_SUMMARY entry: adds `primary_hits: 0, booster_hits: 0` (activity-based, no pattern matching).

### 3. `score_all_categories` function (lines 488-505)
- Return list comprehension now includes `primary_hits` and `booster_hits` from `_score_all_raw` output, using `.get()` with default 0 for safety.

## Verification

- `python3 -m py_compile hooks/scripts/memory_triage.py` -- passed.
- `pytest tests/ -v -k triage` -- 126 passed, 0 failed.
- Searched for external callers of `score_text_category` -- only called from `_score_all_raw`, no test files destructure it directly. No breakage.

## Impact

The `triage.score` log event will now include `primary_hits` and `booster_hits` per category, enabling the log analyzer to distinguish between "primary hit with no booster" and "no primary hit at all" for diagnostic purposes.
