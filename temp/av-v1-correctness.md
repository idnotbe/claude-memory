# Correctness Review: memory_log_analyzer.py & memory_triage.py

**Reviewer:** Claude Opus 4.6 + Codex (via clink)
**Date:** 2026-03-22
**Scope:** All uncommitted changes in both files (minimum sample guards, booster detector, 4-tuple return type, constraint pattern expansion)

---

## Test Suite Results

```
128 passed in 0.55s
```

All tests in `tests/test_log_analyzer.py` (40 tests) and `tests/test_memory_triage.py` (88 tests) pass.

---

## Checklist Review

### 1. Minimum sample guards -- placement correctness

**Verdict: CORRECT**

All five detectors place their minimum-sample guard in the correct position: after the empty/zero-data early-return, before any rate computation or division.

| Detector | Empty check | Min-sample guard | Computation |
|----------|-----------|-----------------|------------|
| `_detect_skip_rate_high` | L146: `retrieval_events == 0` | L150: `< _MIN_RETRIEVAL_EVENTS_SKIP_RATE` | L153: `skip_count / retrieval_events` |
| `_detect_zero_length_prompt` | L179: `not skip_events` | L183: `< _MIN_SKIP_EVENTS_ZERO_PROMPT` | L191: `zero_count / len(skip_events)` |
| `_detect_category_never_triggers` | L217: `not triage_events` | L221: `< _MIN_TRIAGE_EVENTS_CATEGORY` | L228+: Counter accumulation |
| `_detect_booster_never_hits` | L283: `not triage_events` | L287: `< _MIN_TRIAGE_EVENTS_BOOSTER` | L296+: Counter accumulation |
| `_detect_error_spike` | (no global empty check needed) | L392: `total < _MIN_ERROR_SPIKE_EVENTS` (per-category) | L394: `errors / total` |

### 2. `< threshold` condition (strict less-than)

**Verdict: CORRECT**

All guards use `<` (strict less-than), meaning `N == threshold` passes through to computation. This is the correct semantic: if you have exactly 20 retrieval events and the min is 20, analysis proceeds. Tests confirm this: `test_skip_rate_at_min_triggers` uses exactly 20 events and expects a finding, `test_booster_at_min_triggers` uses exactly 50, etc.

### 3. `_detect_booster_never_hits` logic

**Verdict: CORRECT with a noted limitation**

- **Per-category accumulation:** Uses `Counter` objects `cat_primary_total` and `cat_booster_total`, iterating over `all_scores` entries. Each entry's `category` key is used to accumulate per-category. Correct.
- **Old-format handling:** The `has_booster_fields` flag starts `False` and is set `True` only when `primary_hits` or `booster_hits` is found in any score entry. If no entries have these fields, the function returns `[]` silently. Correct.
- **SESSION_SUMMARY exclusion:** Line 319: `if cat == "SESSION_SUMMARY": continue` in the findings loop. Correct -- SESSION_SUMMARY is activity-based and has no booster concept. The test `test_booster_session_summary_excluded` verifies this.

**Noted limitation (medium):** The `sample_size` reported is `len(triage_events)` (total triage events), not the number of events that actually contained booster fields for the specific category. In a mixed old/new log window, this can be misleading (e.g., "across 50 triage events" when only 5 had the new fields). This is a cosmetic/statistical accuracy issue, not a correctness bug.

### 4. triage.py return type changes (4-tuple)

**Verdict: CORRECT**

`score_text_category` now returns `(float, list[str], int, int)`:
- L366: Early return for unknown category: `return 0.0, [], 0, 0` (4-tuple)
- L404: Normal return: `return normalized, snippets, primary_count, boosted_count` (4-tuple)
- Both `primary_count` and `boosted_count` are initialized to `0` at L377-378 and only incremented within the scoring loop. Correct.

### 5. `_score_all_raw` destructuring

**Verdict: CORRECT**

L450: `score, snippets, p_hits, b_hits = score_text_category(lines, category)` -- 4-value destructuring matches the 4-tuple return. The values are then stored in the dict at L451-457 under `primary_hits` and `booster_hits` keys.

SESSION_SUMMARY (L460-467) correctly gets hardcoded `"primary_hits": 0, "booster_hits": 0` since it uses `score_session_summary()` which returns a 2-tuple (no booster concept).

### 6. `sample_size` field consistency

**Verdict: PARTIALLY CONSISTENT (low issue)**

Five detectors include `sample_size` in their finding `data`:
- `_detect_skip_rate_high`: `sample_size: retrieval_events`
- `_detect_zero_length_prompt`: `sample_size: len(skip_events)`
- `_detect_category_never_triggers`: `sample_size: len(triage_events)`
- `_detect_booster_never_hits`: `sample_size: len(triage_events)`
- `_detect_error_spike`: `sample_size: total` (per-category total)

Two detectors do NOT include `sample_size`:
- `_detect_missing_event_types`: No `sample_size` (this is a presence/absence check, not a rate calculation, so arguably N/A)
- `_detect_perf_degradation`: No `sample_size` (compares two day-averages, not a rate)

Additionally, `NO_DATA` findings (from `analyze()`) have no `sample_size`.

This is defensible: the detectors without `sample_size` are not rate-based, so the field is less meaningful. However, if downstream consumers expect uniform finding schemas, this could cause issues.

### 7. `analyze()` wiring

**Verdict: CORRECT**

L529: `findings.extend(_detect_booster_never_hits(events, event_counts))` is placed after `_detect_category_never_triggers` and before `_detect_missing_event_types`. The detector returns a list, and `extend` is used (not `append`). Consistent with the other list-returning detectors.

### 8. `_generate_recommendations()` for BOOSTER_NEVER_HITS

**Verdict: CORRECT**

L589-600: Checks `"BOOSTER_NEVER_HITS" in codes_seen`, extracts affected category names from findings, formats a descriptive recommendation. The recommendation text references `memory_triage.py CATEGORY_PATTERNS` which is the correct file for users to check booster patterns.

---

## Edge Case Analysis

### What happens if `event_counts` has non-retrieval events mixed in for skip_rate?

**Safe.** `_detect_skip_rate_high` uses a comprehension that filters by `et.startswith("retrieval.")`:
```python
retrieval_events = sum(c for et, c in event_counts.items() if et.startswith("retrieval."))
```
Non-retrieval events (e.g., `triage.score`) are excluded from both the numerator and denominator. Test `test_skip_rate_non_retrieval_events_ignored` confirms this: 5 retrieval events + 50 triage events -> only 5 counted, below the min threshold.

### What if `triage.score` events have malformed `data` fields?

**Safe.** Both `_detect_category_never_triggers` and `_detect_booster_never_hits` have:
```python
data = e.get("data", {})
if not isinstance(data, dict):
    continue
```
Additionally, `all_scores` is checked with `if not isinstance(all_scores, list): continue` and individual score entries with `if not isinstance(s, dict) or "category" not in s: continue`. These guard against:
- `data` being `None`, a string, a list, or any non-dict
- `all_scores` being missing, `None`, or non-list
- Score entries being non-dicts or missing `category`

### What if `all_scores` entries are missing `category` keys?

**Safe.** Both detectors check `"category" not in s` before accessing `s["category"]`. In `_detect_category_never_triggers`, the check is `if isinstance(s, dict) and s.get("score", 0) > 0 and "category" in s`. In `_detect_booster_never_hits`, the check is `if not isinstance(s, dict) or "category" not in s: continue`. Entries without `category` are silently skipped.

---

## Codex Review Summary

Codex confirmed all positive correctness aspects and identified the same two medium-severity observations:

1. **CATEGORY_NEVER_TRIGGERS per-category sample size (medium):** The detector uses aggregate `len(triage_events)` as its sample guard but flags category-specific conclusions. After 30 total events, a single non-zero score for a rare category is enough to trigger the finding. A per-category minimum would reduce false positives.

2. **BOOSTER_NEVER_HITS mixed old/new format sample size (medium):** The `sample_size` field reports total triage events, not per-category events that actually contain booster fields. During rollout with mixed log formats, this overstates the evidence base.

3. **sample_size inconsistency across finding types (low):** `MISSING_EVENT_TYPES`, `PERF_DEGRADATION`, and `NO_DATA` findings lack `sample_size`, making the field non-universal.

---

## Final Verdict

**The implementation is correct.** All core mechanics work as designed:
- Guards are properly ordered and use correct comparison operators
- The 4-tuple plumbing through triage.py is clean and complete
- The booster detector logic is sound (accumulation, old-format skip, SESSION_SUMMARY exclusion)
- The analyzer wiring and recommendation generation are correct
- All 128 tests pass
- Edge cases (malformed data, missing keys, mixed event types) are handled safely

**Improvement opportunities (non-blocking):**
- Consider per-category sample minimums for `CATEGORY_NEVER_TRIGGERS` and `BOOSTER_NEVER_HITS` to reduce false positives during early adoption or for infrequent categories
- Consider adding `sample_size` to all finding types or documenting it as optional
- Consider tracking per-category instrumented observations for `BOOSTER_NEVER_HITS` during mixed old/new log windows
