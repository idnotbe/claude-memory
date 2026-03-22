# Log Analyzer v1 -- Edge Case & Coverage Review

Reviewer: Claude Opus 4.6 + Codex (clink codereviewer)
Date: 2026-03-22
Files reviewed:
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_log_analyzer.py`
- `/home/idnotbe/projects/claude-memory/tests/test_log_analyzer.py`

---

## 1. Completely Untested Detectors

### 1a. `_detect_missing_event_types` (line 343) -- NO TESTS

Missing cases:
- No retrieval events at all -> `None`
- Only `retrieval.skip` (no search/inject) -> finding
- `retrieval.search` present -> `None`
- `retrieval.inject` present -> `None`
- Both present -> `None`
- Assert `data["present_types"]` ordering and `data["missing"] == ["retrieval.search", "retrieval.inject"]`

### 1b. `_detect_perf_degradation` (line 415) -- NO TESTS

Missing cases:
- Fewer than 2 distinct dates -> `None`
- `first_avg <= 0` -> `None`
- Exactly 50% increase -> `None` (threshold is `> 0.50`)
- 51%+ increase -> finding
- Non-numeric / `None` `duration_ms` silently skipped
- Timestamps shorter than 10 chars -> date extraction yields empty string, skipped
- Assert exact `data` fields: `first_day`, `last_day`, `first_avg_ms`, `last_avg_ms`, `increase_pct`

### 1c. `_load_events` (line 70) -- NO TESTS

Missing cases:
- No `logs/` directory -> `[]`
- Symlink category dirs skipped
- Hidden dirs (`.hidden/`) skipped
- Non-safe names skipped
- Date filtering (file outside range skipped)
- Malformed JSON lines silently skipped
- `_MAX_EVENTS` cap honored
- `event_type` coerced to str (including `None` -> `""`)

### 1d. `analyze` (line 473) -- NO TESTS

Missing cases:
- No events -> `NO_DATA` finding produced
- Actual date range extracted from timestamps
- Findings sorted by severity
- `_generate_recommendations` output included

### 1e. `_generate_recommendations` (line 559) -- NO TESTS

### 1f. `format_text` / `format_json` (lines 641, 693) -- NO TESTS

---

## 2. Test Coverage Gaps in TESTED Detectors

### 2a. Boundary value gaps

| Detector | N=0 | N=threshold-1 | N=threshold | N=threshold+1 | Rate at exact boundary | Rate just above |
|---|---|---|---|---|---|---|
| `_detect_zero_length_prompt` | Yes | Yes (9) | Yes (10) | No | Yes (50% exact) | Yes (60%) |
| `_detect_skip_rate_high` | Yes | Yes (19) | Yes (20) | No | Yes (90% exact) | Yes (95%) |
| `_detect_category_never_triggers` | Yes | Yes (29) | Yes (30) | No | N/A | N/A |
| `_detect_booster_never_hits` | Yes | Yes (49) | Yes (50) | No | N/A | N/A |
| `_detect_error_spike` | Yes | Yes (9) | Yes (10) | No | Yes (10% exact) | Yes (20%) |

**N=threshold+1 is never tested for any detector.** While this is a minor gap (if threshold passes, threshold+1 should too), it's a completeness gap.

### 2b. "Guard triggers" vs "guard passes + detection triggers" vs "guard passes + detection doesn't trigger"

All three paths ARE tested for each covered detector. This is solid.

### 2c. Data dict field assertions -- WEAK

Most assertions stop at `code`/`severity` or simple category presence. Very few verify exact numeric values in `data`:

- `SKIP_RATE_HIGH`: Only `sample_size` checked (line 220). Missing: `skip_count`, `total_retrieval`, `skip_rate`.
- `ZERO_LENGTH_PROMPT`: Only `sample_size` checked (line 163). Missing: `zero_count`, `total_skip`, `zero_rate`.
- `CATEGORY_NEVER_TRIGGERS`: `category` checked. Missing: `trigger_count`, `has_nonzero_scores`, `sample_size`.
- `BOOSTER_NEVER_HITS`: `category` checked. Missing: `primary_hits`, `booster_hits`, `sample_size`.
- `ERROR_SPIKE`: Field presence checked (lines 589-591). Missing: exact value assertions for `error_count`, `total_count`, `error_rate`, `sample_size`.

### 2d. `_detect_error_spike` per-category threshold -- PARTIALLY TESTED

The per-category grouping (`et.split(".")[0]`) is tested via `test_error_spike_multiple_categories` which uses `retrieval.skip` and `triage.score`. However, there is **no test that verifies events like `retrieval.skip` and `retrieval.search` aggregate into the same `retrieval` category** for the threshold check. This is a real logic verification gap.

---

## 3. Specific Edge Cases

### 3a. ALL triage.score events with empty data dicts

```python
events = [{"event_type": "triage.score", "data": {}} for _ in range(30)]
```

- `_detect_category_never_triggers`: `data.get("triggered", [])` returns `[]`, `data.get("all_scores", [])` returns `[]`. No crashes. Returns `[]` (no categories with nonzero scores found). **Safe but untested.**
- `_detect_booster_never_hits`: Same -- no `all_scores` entries, `has_booster_fields` stays `False`, returns `[]`. **Safe but untested.**

### 3b. `triggered` list contains non-dict entries

```python
data = {"triggered": ["DECISION", 42, None], "all_scores": [...]}
```

- `_detect_category_never_triggers` line 237: `isinstance(t, dict) and "category" in t` -- non-dict entries are skipped. **Safe but untested.**

### 3c. `all_scores` has negative scores

```python
all_scores = [{"category": "DECISION", "score": -5}]
```

- `_detect_category_never_triggers` line 246-248: `s.get("score", 0) > 0` -- negative scores are treated as zero (not added to `has_nonzero_score`). **Safe but untested.** The category would not be flagged, which is correct behavior.

### 3d. `prompt_length` is `None` instead of 0

```python
data = {"prompt_length": None, "reason": "too_short"}
```

- `_detect_zero_length_prompt` line 189: `e["data"].get("prompt_length", -1) == 0` -- `None != 0`, so it would NOT count as a zero-length prompt. **This is a semantic question**: if the field is explicitly `None`, should it be treated as "no prompt" (equivalent to 0) or "field present but unknown"? Current behavior silently ignores `None`. **Untested and potentially a bug depending on intent.**

### 3e. Booster detector with partial booster data (primary_hits but no booster_hits)

```python
all_scores = [{"category": "DECISION", "score": 5, "primary_hits": 3}]
# No "booster_hits" key
```

- `_detect_booster_never_hits` line 306: `"primary_hits" in s or "booster_hits" in s` -> `True`, so `has_booster_fields = True`.
- Line 309: `cat_primary_total[cat] += s.get("primary_hits", 0)` -> adds 3.
- Line 310: `cat_booster_total[cat] += s.get("booster_hits", 0)` -> adds 0.
- Result: would flag DECISION as having 0 booster hits. **Safe but potentially noisy.** If a log format transition only includes one field, this could produce false positives. **Untested.**

### 3f. Mixed old/new format triage events for booster detector

```python
events = (
    # 25 old-format events (no primary_hits/booster_hits)
    [_make_triage_event(triggered=[], all_scores=[{"category": "DECISION", "score": 3}])]
    * 25
    # 25 new-format events (with booster fields)
    + [_make_triage_event_with_booster("DECISION", primary_hits=3, booster_hits=1)]
    * 25
)
```

- Total triage events = 50 (meets minimum).
- `has_booster_fields` becomes `True` (new-format events have the fields).
- Old-format events are silently skipped in the inner loop (no `primary_hits`/`booster_hits`).
- Only the 25 new-format events contribute to counts: `primary_hits=75`, `booster_hits=25`.
- Would NOT flag (booster > 0). **Safe but untested.**

- If the new-format events had `booster_hits=0`: primary=75, booster=0 -> would flag. The `sample_size` reports 50 events total, but only 25 contributed data. **Potentially misleading sample_size. Untested.**

---

## 4. Additional Edge Cases Identified

### 4a. `_detect_category_never_triggers` -- single trigger suppresses finding

If a category triggers even once across 30+ events, it should NOT be flagged. No test covers the "29 non-triggers + 1 trigger" case to verify suppression works.

### 4b. `_detect_skip_rate_high` -- mixed retrieval event types in denominator

Tests only use `retrieval.skip` and `retrieval.search`. The implementation counts ALL `retrieval.*` events (including `retrieval.inject`, `retrieval.error`, etc.) in the denominator. No test verifies that `retrieval.inject` events contribute to the total.

### 4c. `_detect_error_spike` -- event_type without a dot

```python
{"event_type": "standalone", "level": "error"}
```

Line 383: `et.split(".")[0] if "." in et else et` -> category = `"standalone"`. This works, but the behavior with dot-less event types is **untested**.

### 4d. `_detect_perf_degradation` -- all durations on a single day

If all events share the same date, `len(durations_by_date) < 2` -> returns `None`. **Untested.**

### 4e. `_detect_perf_degradation` -- negative duration_ms

If `duration_ms` is negative (clock skew), it would be included in averages, potentially producing misleading results or `first_avg <= 0`. **Untested.**

### 4f. Type safety for `score`, `primary_hits`, `booster_hits`

Codex CLI confirmed via probes that passing string values like `score="3"` or `primary_hits="3"` causes `TypeError` at comparison/addition. The code does `s.get("score", 0) > 0` -- if score is a string, this raises `TypeError` in Python 3. Same for `cat_primary_total[cat] += s.get("primary_hits", 0)` with string values. **Not handled, not tested. Crash risk from malformed log data.**

---

## 5. Self-Critique / Blind Spots

Things I might be missing:

1. **Concurrency / file system race conditions** in `_load_events`: file deleted between `iterdir()` and `open()`. The `OSError` catch handles this, but not tested.
2. **Timezone edge cases** in `analyze()`: `datetime.now(timezone.utc)` vs log timestamps that might be in local time. Date comparison is string-based, so timezone mismatch could cause off-by-one date filtering.
3. **Very large event counts**: `_MAX_EVENTS` cap is tested only implicitly (no test exists). If exactly 100,000 events are loaded, the 100,001st event in a mid-file position means partial file reads -- is that acceptable?
4. **Unicode in event_type**: The `str()` coercion handles this, but extreme Unicode (RTL markers, zero-width chars) in event_type could cause surprising `startswith()` behavior.
5. **The `analyze()` function's integration behavior**: No integration test verifies that all detectors are actually called and their findings aggregated correctly.
6. **Severity sort stability**: `findings.sort()` uses `_SEVERITY_ORDER.get(f["severity"], 99)`. If two findings have the same severity, is the relative order stable? Python sort is stable, so insertion order is preserved -- but this is **untested**.

---

## 6. Summary: Priority-Ordered Gaps

| Priority | Gap | Risk |
|---|---|---|
| **P0** | `_detect_missing_event_types` and `_detect_perf_degradation` have zero tests | Silent regressions |
| **P0** | Type safety: string/None values for `score`, `primary_hits`, `booster_hits` cause `TypeError` crash | Crash on malformed log data |
| **P1** | Data dict field values not asserted (only presence/code/severity checked) | Regression in output structure goes undetected |
| **P1** | `prompt_length=None` semantic ambiguity | Potential missed detections |
| **P1** | Partial booster fields + mixed format -> misleading `sample_size` | Noisy/misleading findings |
| **P2** | `_load_events`, `analyze`, `_generate_recommendations`, formatters untested | No coverage for orchestration/output |
| **P2** | Single-trigger suppression in `_detect_category_never_triggers` untested | Logic correctness unverified |
| **P2** | Error spike per-category aggregation (`retrieval.skip` + `retrieval.search` -> `retrieval`) untested | Grouping logic unverified |
| **P3** | N=threshold+1 boundary not tested for any detector | Minor completeness gap |
| **P3** | Dot-less event_type, negative duration_ms, timezone edge cases | Low-probability edge cases |
