# Security Review: memory_log_analyzer.py

**Reviewer:** Claude Opus 4.6 + Gemini 3.1 Pro (cross-model)
**Date:** 2026-03-22
**File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_log_analyzer.py`
**Test file:** `/home/idnotbe/projects/claude-memory/tests/test_log_analyzer.py`

---

## Summary

The analyzer is well-structured with strong path traversal defenses and division-by-zero guards. However, several type-safety gaps allow crafted JSONL events to crash the analyzer or suppress legitimate alerts. The module-level constants are safe (Python module-level, not externally configurable). The minimum sample size guards are correctly implemented and well-tested.

---

## CRITICAL Findings

### C1. DoS via unvalidated `timestamp` type (crashes `analyze()`)

**Location:** `analyze()`, line 511
```python
timestamps = [e.get("timestamp", "")[:10] for e in events]
```

**Issue:** If `timestamp` is `int`, `None`, `list`, or any non-string, the `[:10]` slice raises `TypeError`, crashing the entire analyzer before any detector runs. The `.get("timestamp", "")` default only applies when the key is missing -- not when the value is explicitly `None` or a non-string type.

**Verified:** `12345[:10]` -> `TypeError: 'int' object is not subscriptable`; `None[:10]` -> same.

**Impact:** A single malformed log line with `"timestamp": 123` blinds the entire analysis pipeline.

**Fix:** Coerce: `str(e.get("timestamp", "") or "")[:10]` or guard with `isinstance`.

### C2. DoS via unhashable `category` in triage data

**Location:** `_detect_category_never_triggers` (line 238), `_detect_booster_never_hits` (line 308)

**Issue:** If `category` in a `triggered` or `all_scores` entry is a list or dict (unhashable type), using it as a Counter key or adding it to a set raises `TypeError: unhashable type`.

**Verified:** `Counter()[['DECISION']] += 1` -> `TypeError`.

**Impact:** A single crafted triage event with `"category": ["DECISION"]` crashes the detector.

**Fix:** Add `isinstance(cat, str)` guard before using category as a key.

### C3. DoS via non-numeric `score` comparison

**Location:** `_detect_category_never_triggers`, line 246
```python
s.get("score", 0) > 0
```

**Issue:** If `score` is a string (e.g., `"10"`), Python 3 raises `TypeError: '>' not supported between instances of 'str' and 'int'`.

**Verified:** `"10" > 0` -> `TypeError`.

**Fix:** `isinstance(s.get("score"), (int, float)) and s["score"] > 0`

### C4. DoS via non-numeric `primary_hits`/`booster_hits`

**Location:** `_detect_booster_never_hits`, lines 309-310
```python
cat_primary_total[cat] += s.get("primary_hits", 0)
cat_booster_total[cat] += s.get("booster_hits", 0)
```

**Issue:** If these values are strings or lists, the `+=` operation on a Counter raises `TypeError`.

**Fix:** Validate type before accumulating, or use `int(val)` with try/except.

---

## HIGH Findings

### H1. Alert suppression via log flooding (_MAX_EVENTS truncation)

**Location:** `_load_events`, line 115-116

**Issue:** The `_MAX_EVENTS = 100_000` cap is a first-in-wins truncation. An attacker who can write to log files can flood with 100k benign events, pushing all real anomaly data out of the analysis window. Since files are loaded in sorted order (by category directory then filename), an attacker creating a log directory named `aaa/` with 100k benign events would fill the buffer before any `retrieval/` or `triage/` events are loaded.

**Impact:** Complete false negative -- all legitimate alerts suppressed.

**Mitigation notes:** This is an inherent trade-off of memory-bounded loading. A per-category event budget or sampling strategy would be more robust but adds complexity. Upstream rate-limiting in `memory_logger.py` is the better defense layer.

### H2. Ratio manipulation via event injection

**Issue:** All rate-based detectors use ratios (skip_count / retrieval_events, zero_count / skip_events, errors / total). An attacker can inject fake events to inflate denominators:
- Inject `retrieval.search` events -> lowers skip rate below 90%
- Inject `retrieval.skip` events with `prompt_length > 0` -> lowers zero-prompt rate below 50%
- Inject non-error events -> lowers error rate below 10%

**Impact:** Targeted false negatives for specific detectors.

**Mitigation notes:** The minimum sample size guards partially help (attacker needs at least N events), but once past the minimum, ratios are freely manipulable. Defense-in-depth at the logger layer (authenticated writes, write-ahead integrity) would address the root cause.

### H3. event_type coercion bypass for non-string types

**Location:** `_load_events`, lines 122-124
```python
entry["event_type"] = str(entry["event_type"] or "")
```

**Issue:** The `or ""` short-circuit only activates for falsy values (None, 0, False, empty string, empty list). For truthy non-strings:
- `[1,2,3]` -> `str([1,2,3])` = `"[1, 2, 3]"` -- bypasses all `startswith()` checks
- `{"a":1}` -> `str({"a":1})` = `"{'a': 1}"` -- same
- `b"retrieval.skip"` (bytes) -> `"b'retrieval.skip'"` -- bypasses prefix checks

For falsy non-strings, the behavior is also surprising:
- `0` -> `str(0 or "")` = `str("")` = `""` -- value information lost
- `False` -> same as 0

**Impact:** Events with non-string event_type slip through loading but are invisible to all detectors (never match any `startswith` or `==` check). They still consume slots in the _MAX_EVENTS budget.

**Fix:** Replace with `if not isinstance(entry.get("event_type"), str): continue` to reject non-string event_types at load time.

---

## MEDIUM Findings

### M1. OOM via unbounded line length

**Location:** `_load_events`, line 111
```python
for line_no, line in enumerate(fh, 1):
```

**Issue:** Python reads lines into memory. A single line without a newline (multi-GB JSON blob) can exhaust memory before `_MAX_EVENTS` or `json.loads` even runs.

**Impact:** Process OOM kill.

**Fix:** Add `_MAX_LINE_LENGTH` constant and skip lines exceeding it: `if len(line) > _MAX_LINE_LENGTH: continue`

### M2. Negative hit values suppress booster alerts

**Location:** `_detect_booster_never_hits`, lines 309-310

**Issue:** `primary_hits` and `booster_hits` are accumulated via `+=` without clamping. Injecting `"primary_hits": -1000` across multiple events can drive `cat_primary_total[cat]` to a negative value, causing the `primary > 0` check to fail and suppressing the BOOSTER_NEVER_HITS alert.

**Verified:** Counter arithmetic with negative values works: `Counter()["X"] += -100` -> `Counter({"X": -100})`.

**Fix:** Clamp: `max(0, int(s.get("primary_hits", 0)))` after type validation.

### M3. NaN/Inf duration_ms silently corrupts perf detection

**Location:** `_detect_perf_degradation`, lines 423-428

**Issue:** `float('nan')` and `float('inf')` both pass the `isinstance(dur, (int, float))` check. Effects:
- **NaN:** `sum([1.0, nan])` = `nan`, `nan / N` = `nan`, `nan <= 0` = `False`, `nan > 0.50` = `False` -- silently suppresses the alert.
- **Inf:** `sum([1.0, inf])` = `inf`. If both first and last day have inf averages: `inf - inf = nan`, `nan / inf = nan` -> same suppression. If only last day has inf: `(inf - X) / X = inf > 0.50` -> triggers (benign false positive).

**Impact:** A single NaN duration in the first or last day's data silently suppresses the PERF_DEGRADATION detector.

**Fix:** Add `math.isfinite(dur)` check alongside `isinstance`.

---

## LOW / Informational Findings

### L1. Empty-string category grouping in error spike

**Location:** `_detect_error_spike`, line 383

Event types like `""`, `"."`, `".."`, `".a"` all map to the empty-string category `""`. This is not a bug but a minor aesthetic issue -- the output message would read `Error rate in '' is ...`.

### L2. Counter memory with 100k unique keys

With `_MAX_EVENTS = 100_000`, each event could have a unique event_type string, producing 100k Counter keys. Measured at ~3.8 MB for 100k keys -- acceptable.

### L3. Date filtering uses lexicographic comparison

**Location:** `_load_events`, line 106
```python
if file_date < start_date or file_date > end_date:
```

This works correctly for ISO 8601 dates (YYYY-MM-DD) due to lexicographic ordering. However, a file named `99999-99-99.jsonl` would pass `_SAFE_NAME_RE` and pass any date range filter. The impact is minimal since such a file would just contribute extra events.

---

## What's Secure (Positive Findings)

| Area | Assessment |
|------|-----------|
| **Path traversal defense** | Excellent. Triple-layered: symlink skip + `_SAFE_NAME_RE` + `_is_safe_path` with `resolve().relative_to()`. |
| **Division-by-zero guards** | All ratio calculations check for zero denominators or empty lists before dividing. |
| **Module-level constants** | Cannot be manipulated via external input. Python module-level `frozenset`/`int`/`float` are immutable. |
| **Minimum sample size guards** | Correctly prevent false positives from tiny datasets. Well-tested (all 5 detectors have boundary tests). |
| **Counter() with crafted strings** | Safe. Python dicts handle special chars, long strings without issue. Memory bounded by `_MAX_EVENTS`. |
| **Dot-splitting in error spike** | Correct behavior for all edge cases. `"a.b.c.d"` -> `"a"`, `""` -> `""`, `"."` -> `""`. |
| **Fail-open on malformed JSON** | Correct -- `json.JSONDecodeError` and `OSError` are caught and skipped. |
| **Non-dict JSON entries rejected** | Line 119: `if isinstance(entry, dict)` prevents arrays/strings/numbers from entering the event list. |

---

## Recommended Fix Priority

| Priority | ID | Fix |
|----------|----|-----|
| P0 | C1 | Coerce `timestamp` to string before slicing |
| P0 | C2-C4 | Add `isinstance` guards for `category`, `score`, `primary_hits`, `booster_hits` |
| P1 | H3 | Reject non-string `event_type` at load time instead of coercing |
| P1 | M1 | Add `_MAX_LINE_LENGTH` to prevent OOM from single-line bombs |
| P2 | M2 | Clamp negative hit values with `max(0, ...)` |
| P2 | M3 | Add `math.isfinite()` guard for duration_ms |
| P3 | H1-H2 | Consider per-category event budgets or upstream rate-limiting (design change) |

---

## Cross-Model Review Notes

Gemini 3.1 Pro independently identified findings C1-C4, H3, M1, M2, and the positive assessments for path traversal, Counter safety, dot-splitting, and division-by-zero. Claude additionally identified M3 (NaN/Inf in duration_ms), H1/H2 specifics (sorted loading order exploitation for truncation), and L3 (date filtering edge case). Both reviewers agree the path traversal defense is strong and the minimum sample guards are correct.
