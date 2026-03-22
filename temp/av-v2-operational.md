# Operational Review: memory_log_analyzer.py & memory_triage.py

**Reviewer**: Operational (v2)
**Date**: 2026-03-22
**Files**: `hooks/scripts/memory_log_analyzer.py`, `hooks/scripts/memory_triage.py`
**External input**: Codex (via clink, codereviewer role)

---

## Summary

The changes add minimum sample size guards to all rate-based anomaly detectors in the log analyzer, introduce a new `BOOSTER_NEVER_HITS` detector, add `sample_size` to finding data dicts, and extend `score_all_categories()` in triage.py to emit `primary_hits`/`booster_hits` alongside each category score. One test fails due to the triage output contract change.

Overall assessment: **mostly sound, with one migration-safety bug and one type-safety gap**.

---

## (a) Backwards Compatibility: Old Logs Without Booster Fields

**PASS with one issue.**

All existing detectors (`SKIP_RATE_HIGH`, `ZERO_LENGTH_PROMPT`, `CATEGORY_NEVER_TRIGGERS`, `MISSING_EVENT_TYPES`, `ERROR_SPIKE`, `PERF_DEGRADATION`) are unaffected by the booster changes. They do not read `primary_hits` or `booster_hits` fields.

The new `_detect_booster_never_hits` detector has an explicit old-format skip path at line 312-313:

```python
if not has_booster_fields:
    return []
```

This correctly returns no findings when analyzing a log window composed entirely of old-format entries. **Old logs are safe.**

---

## (b) Log Format Migration: Mixed Old/New Logs

**FAIL -- migration-safety bug in `_detect_booster_never_hits`.**

The sample size guard at line 287 counts **all** `triage.score` events:

```python
if len(triage_events) < _MIN_TRIAGE_EVENTS_BOOSTER:  # 50
    return []
```

But the accumulation loop (lines 295-310) only processes entries that have both `primary_hits` and `booster_hits` fields (new-format). In a mixed-version log window:

- 49 old-format events + 1 new-format event = 50 total triage events
- The guard passes (50 >= 50)
- But only 1 event is actually analyzed for booster data
- If that 1 event has `primary_hits > 0` and `booster_hits == 0`, a warning is raised
- The `sample_size` field reports 50 (misleading -- only 1 was usable)
- The message says "across 50 triage events" -- incorrect

**Impact**: False `BOOSTER_NEVER_HITS` warnings during rollout transition period. Premature operational conclusions based on effectively tiny compatible samples. Severity is "warning" level so not a critical false alarm, but still misleading.

**Fix**: Track compatible-event count separately and use it for both the threshold guard and the reported `sample_size`:

```python
compatible_events = 0
for e in triage_events:
    ...
    for s in all_scores:
        if "primary_hits" in s and "booster_hits" in s:
            has_booster_fields = True
            compatible_events += 1  # count per-event, not per-score-entry
            ...

if compatible_events < _MIN_TRIAGE_EVENTS_BOOSTER:
    return []
# Use compatible_events in message and sample_size
```

---

## (c) Performance Impact of Sample Size Guards

**PASS -- negligible overhead.**

Each guard is a single integer comparison (`len(list) < constant`) that short-circuits before any accumulation loop. The guards reduce work, not increase it. For detectors that do proceed, the accumulation loops are identical in complexity to before -- just with an additional field read per iteration.

No new I/O, no new regex compilation, no new allocations. Performance impact is effectively zero.

---

## (d) Output Format Changes: `sample_size` in Findings

**PASS -- low risk, but not uniform.**

The `sample_size` field was added to finding data dicts for `SKIP_RATE_HIGH`, `ZERO_LENGTH_PROMPT`, `CATEGORY_NEVER_TRIGGERS`, `BOOSTER_NEVER_HITS`, and `ERROR_SPIKE`. It is **not** present in `MISSING_EVENT_TYPES`, `PERF_DEGRADATION`, or `NO_DATA` findings.

No downstream automated pipeline consumes the analyzer JSON output. The only consumers are:
- Human-readable text formatter (`format_text()`) -- does not read `data` dicts, only `severity`/`code`/`message`
- Action plan markdown reports (manual review)
- Test assertions in `test_log_analyzer.py`

Since JSON is additive-compatible (extra keys don't break permissive consumers) and there are no strict schema validators downstream, this is safe. A strict consumer would break, but none exist.

**Minor inconsistency**: Not all finding types include `sample_size`. If a future consumer expects it uniformly, some findings will be missing it. Consider adding it to all finding types or documenting which ones include it.

---

## (e) CLI Behavior

**PASS.**

```
$ python3 hooks/scripts/memory_log_analyzer.py --help
usage: memory_log_analyzer.py [-h] --root ROOT [--days DAYS]
                              [--format {json,text}]
```

The CLI accepts `--root`, `--days`, and `--format` as documented. Help output is correct. No changes to CLI interface.

---

## (f) Full Regression Test Results

**1 FAILED, 1094 PASSED, 1 warning.**

```
FAILED tests/test_memory_logger.py::TestScoreAllCategories::test_only_category_and_score_keys
```

The failing test asserts the exact key set of `score_all_categories()` output:

```python
assert set(entry.keys()) == {"category", "score"}
```

But the function now returns `{"category", "score", "primary_hits", "booster_hits"}`.

**Analysis**: This is a **stale contract test**, not a real regression. The function's output was intentionally expanded, and the test wasn't updated to match. The only production consumer of `score_all_categories()` is the `emit_event("triage.score", ...)` call at triage.py:1119-1127, which logs the full payload -- it benefits from the extra fields.

However, the docstring at triage.py:503-504 still documents the old shape:

```python
Returns:
    [{"category": "DECISION", "score": 0.32}, ...]
```

**Fix required**:
1. Update the test to accept the new key set: `{"category", "score", "primary_hits", "booster_hits"}`
2. Update the docstring to document the new return shape

---

## Additional Finding: Type Safety Gap in Analyzer

**Severity: Medium**

The analyzer does not validate numeric types before comparison/arithmetic on values read from log JSON:

- Line 246: `s.get("score", 0) > 0` -- raises `TypeError` if `score` is a string
- Lines 309-310: `cat_primary_total[cat] += s.get("primary_hits", 0)` -- raises `TypeError` if value is a string

A single malformed or hand-edited log line with `"score": "3"` or `"primary_hits": "2"` will crash the entire analysis, bypassing the otherwise fail-open design (malformed JSON lines are skipped at load time, but malformed *values* within valid JSON are not).

**Fix**: Validate numeric types before use, e.g.:

```python
score_val = s.get("score", 0)
if not isinstance(score_val, (int, float)):
    continue
```

---

## Codex Review Alignment

Codex (via clink, codereviewer role) independently identified:
1. **High**: Same mixed-format sample size bug in `_detect_booster_never_hits` -- confirmed and reproduced
2. **Medium**: Same type safety gap for malformed numeric values -- confirmed via Python REPL
3. **Low**: Same stale docstring/test contract issue -- confirmed

Full alignment on all three findings. No disagreements.

---

## Action Items

| Priority | Item | Files |
|----------|------|-------|
| **Must fix** | Mixed-format sample size bug in `_detect_booster_never_hits` | `memory_log_analyzer.py:286-336` |
| **Must fix** | Update failing test `test_only_category_and_score_keys` | `tests/test_memory_logger.py:2617-2625` |
| **Must fix** | Update stale docstring in `score_all_categories()` | `memory_triage.py:503-504` |
| **Should fix** | Type safety for numeric fields in analyzer detectors | `memory_log_analyzer.py:244-246, 309-310` |
| **Nice to have** | Uniform `sample_size` across all finding types | `memory_log_analyzer.py` (all detectors) |
