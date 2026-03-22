# Architect Design: Analyzer Validity Guards

## Summary

Fix false positives in `memory_log_analyzer.py` by adding minimum sample size guards to three rate-based detectors, and add a new `_detect_booster_never_hits` detector. The real-world trigger was a CRITICAL `ZERO_LENGTH_PROMPT` finding from only 5 skip events (4/5 = 80%), which is statistically meaningless.

---

## 1. New Constants

Add immediately after `_MAX_EVENTS = 100_000` (line 47):

```python
# Minimum sample sizes for rate-based anomaly detection (statistical validity)
_MIN_SKIP_EVENTS_ZERO_PROMPT = 10   # _detect_zero_length_prompt
_MIN_RETRIEVAL_EVENTS_SKIP_RATE = 20  # _detect_skip_rate_high
_MIN_TRIAGE_EVENTS_CATEGORY = 30   # _detect_category_never_triggers
_MIN_TRIAGE_EVENTS_BOOSTER = 50    # _detect_booster_never_hits
```

**Rationale for thresholds:**
- 10 for zero-prompt: Even at N=10, a single-day anomaly can produce 10 skips. Below this, a handful of edge cases (e.g., internal prompts, healthchecks) dominate the rate.
- 20 for skip-rate: Retrieval events span multiple event types (skip, search, inject). Need enough diversity to distinguish "everything skips" from "mostly works, some skips." 20 gives 5% resolution per event.
- 30 for category-never-triggers: The system has 6 categories. With 30 triage events, each category has been evaluated ~30 times. Below this, a category may simply not have appeared in the conversation content yet.
- 50 for booster: Booster hits are naturally rarer than primary hits (co-occurrence requirement). Need larger N to conclude "zero boosters" is anomalous rather than simply infrequent.

---

## 2. Changes to `_detect_zero_length_prompt` (lines 162-192)

### Current code (lines 162-192):
```python
def _detect_zero_length_prompt(events, event_counts):
    """ZERO_LENGTH_PROMPT: >50% of retrieval.skip events have prompt_length=0."""
    skip_events = [
        e for e in events if e.get("event_type") == "retrieval.skip"
    ]
    if not skip_events:
        return None

    zero_count = sum(
        1 for e in skip_events
        if isinstance(e.get("data"), dict)
        and e["data"].get("prompt_length", -1) == 0
    )
    zero_rate = zero_count / len(skip_events)
    if zero_rate <= _ZERO_PROMPT_THRESHOLD:
        return None

    return {
        "severity": "critical",
        "code": "ZERO_LENGTH_PROMPT",
        "message": (
            f"{zero_rate * 100:.1f}% of retrieval.skip events have "
            f"prompt_length=0 ({zero_count}/{len(skip_events)}). "
            f"Hook is not receiving user prompts."
        ),
        "data": {
            "zero_count": zero_count,
            "total_skip": len(skip_events),
            "zero_rate": round(zero_rate, 4),
        },
    }
```

### New code:
```python
def _detect_zero_length_prompt(events, event_counts):
    """ZERO_LENGTH_PROMPT: >50% of retrieval.skip events have prompt_length=0."""
    skip_events = [
        e for e in events if e.get("event_type") == "retrieval.skip"
    ]
    if not skip_events:
        return None

    # Guard: insufficient sample size for reliable rate calculation
    if len(skip_events) < _MIN_SKIP_EVENTS_ZERO_PROMPT:
        return None

    zero_count = sum(
        1 for e in skip_events
        if isinstance(e.get("data"), dict)
        and e["data"].get("prompt_length", -1) == 0
    )
    zero_rate = zero_count / len(skip_events)
    if zero_rate <= _ZERO_PROMPT_THRESHOLD:
        return None

    return {
        "severity": "critical",
        "code": "ZERO_LENGTH_PROMPT",
        "message": (
            f"{zero_rate * 100:.1f}% of retrieval.skip events have "
            f"prompt_length=0 ({zero_count}/{len(skip_events)}). "
            f"Hook is not receiving user prompts."
        ),
        "data": {
            "zero_count": zero_count,
            "total_skip": len(skip_events),
            "zero_rate": round(zero_rate, 4),
            "sample_size": len(skip_events),
        },
    }
```

**Changes:**
1. Added early return `if len(skip_events) < _MIN_SKIP_EVENTS_ZERO_PROMPT` after the empty check, before rate computation.
2. Added `"sample_size"` to data dict for transparency.

---

## 3. Changes to `_detect_skip_rate_high` (lines 131-159)

### Current code (lines 131-159):
```python
def _detect_skip_rate_high(events, event_counts):
    """SKIP_RATE_HIGH: retrieval.skip >90% of all retrieval events."""
    retrieval_events = sum(
        c for et, c in event_counts.items()
        if et.startswith("retrieval.")
    )
    skip_count = event_counts.get("retrieval.skip", 0)

    if retrieval_events == 0:
        return None

    skip_rate = skip_count / retrieval_events
    if skip_rate <= _SKIP_RATE_THRESHOLD:
        return None

    return {
        "severity": "critical",
        "code": "SKIP_RATE_HIGH",
        "message": (
            f"Retrieval skip rate is {skip_rate * 100:.1f}% "
            f"({skip_count}/{retrieval_events}). "
            f"Memory injection not functioning."
        ),
        "data": {
            "skip_count": skip_count,
            "total_retrieval": retrieval_events,
            "skip_rate": round(skip_rate, 4),
        },
    }
```

### New code:
```python
def _detect_skip_rate_high(events, event_counts):
    """SKIP_RATE_HIGH: retrieval.skip >90% of all retrieval events."""
    retrieval_events = sum(
        c for et, c in event_counts.items()
        if et.startswith("retrieval.")
    )
    skip_count = event_counts.get("retrieval.skip", 0)

    if retrieval_events == 0:
        return None

    # Guard: insufficient sample size for reliable rate calculation
    if retrieval_events < _MIN_RETRIEVAL_EVENTS_SKIP_RATE:
        return None

    skip_rate = skip_count / retrieval_events
    if skip_rate <= _SKIP_RATE_THRESHOLD:
        return None

    return {
        "severity": "critical",
        "code": "SKIP_RATE_HIGH",
        "message": (
            f"Retrieval skip rate is {skip_rate * 100:.1f}% "
            f"({skip_count}/{retrieval_events}). "
            f"Memory injection not functioning."
        ),
        "data": {
            "skip_count": skip_count,
            "total_retrieval": retrieval_events,
            "skip_rate": round(skip_rate, 4),
            "sample_size": retrieval_events,
        },
    }
```

**Changes:**
1. Added early return `if retrieval_events < _MIN_RETRIEVAL_EVENTS_SKIP_RATE` after the zero check, before rate computation.
2. Added `"sample_size"` to data dict.

---

## 4. Changes to `_detect_category_never_triggers` (lines 195-247)

### Current code (lines 195-247):
```python
def _detect_category_never_triggers(events, event_counts):
    """CATEGORY_NEVER_TRIGGERS: category has 0 triggers but non-zero scores."""
    triage_events = [
        e for e in events if e.get("event_type") == "triage.score"
    ]
    if not triage_events:
        return []

    # Collect per-category: trigger count + whether it ever had score > 0
    trigger_counts = Counter()
    has_nonzero_score = set()

    for e in triage_events:
        data = e.get("data", {})
        if not isinstance(data, dict):
            continue

        # Count triggers
        triggered = data.get("triggered", [])
        if isinstance(triggered, list):
            for t in triggered:
                if isinstance(t, dict) and "category" in t:
                    trigger_counts[t["category"]] += 1

        # Check all_scores for non-zero values
        all_scores = data.get("all_scores", [])
        if isinstance(all_scores, list):
            for s in all_scores:
                if (
                    isinstance(s, dict)
                    and s.get("score", 0) > 0
                    and "category" in s
                ):
                    has_nonzero_score.add(s["category"])

    findings = []
    for cat in sorted(_ALL_TRIAGE_CATEGORIES):
        if trigger_counts.get(cat, 0) == 0 and cat in has_nonzero_score:
            findings.append({
                "severity": "high",
                "code": "CATEGORY_NEVER_TRIGGERS",
                "message": (
                    f"Category {cat} has non-zero scores but never triggers. "
                    f"Threshold may be too high."
                ),
                "data": {
                    "category": cat,
                    "trigger_count": 0,
                    "has_nonzero_scores": True,
                },
            })

    return findings
```

### New code:
```python
def _detect_category_never_triggers(events, event_counts):
    """CATEGORY_NEVER_TRIGGERS: category has 0 triggers but non-zero scores."""
    triage_events = [
        e for e in events if e.get("event_type") == "triage.score"
    ]
    if not triage_events:
        return []

    # Guard: insufficient sample size for reliable category analysis
    if len(triage_events) < _MIN_TRIAGE_EVENTS_CATEGORY:
        return []

    # Collect per-category: trigger count + whether it ever had score > 0
    trigger_counts = Counter()
    has_nonzero_score = set()

    for e in triage_events:
        data = e.get("data", {})
        if not isinstance(data, dict):
            continue

        # Count triggers
        triggered = data.get("triggered", [])
        if isinstance(triggered, list):
            for t in triggered:
                if isinstance(t, dict) and "category" in t:
                    trigger_counts[t["category"]] += 1

        # Check all_scores for non-zero values
        all_scores = data.get("all_scores", [])
        if isinstance(all_scores, list):
            for s in all_scores:
                if (
                    isinstance(s, dict)
                    and s.get("score", 0) > 0
                    and "category" in s
                ):
                    has_nonzero_score.add(s["category"])

    findings = []
    for cat in sorted(_ALL_TRIAGE_CATEGORIES):
        if trigger_counts.get(cat, 0) == 0 and cat in has_nonzero_score:
            findings.append({
                "severity": "high",
                "code": "CATEGORY_NEVER_TRIGGERS",
                "message": (
                    f"Category {cat} has non-zero scores but never triggers. "
                    f"Threshold may be too high. "
                    f"(based on {len(triage_events)} triage events)"
                ),
                "data": {
                    "category": cat,
                    "trigger_count": 0,
                    "has_nonzero_scores": True,
                    "sample_size": len(triage_events),
                },
            })

    return findings
```

**Changes:**
1. Added early return `if len(triage_events) < _MIN_TRIAGE_EVENTS_CATEGORY` after the empty check.
2. Added `"sample_size"` to each finding's data dict.
3. Appended `(based on N triage events)` to the message for transparency.

---

## 5. New Detector: `_detect_booster_never_hits`

### Prerequisite: Triage logging must include booster data

**Problem:** The current `triage.score` event logs `all_scores` as `[{"category": "DECISION", "score": 0.32}, ...]`. There is no per-category booster hit count. The `score_text_category()` function in `memory_triage.py` internally tracks `boosted_count` and `primary_count` but discards them, returning only `(normalized_score, snippets)`.

**Required upstream change in `memory_triage.py`:**

1. Modify `score_text_category()` to return a 4-tuple: `(normalized_score, snippets, primary_count, boosted_count)`.
2. Modify `_score_all_raw()` to include the counts in its output: `{"category": ..., "score": ..., "snippets": ..., "primary_hits": N, "booster_hits": N}`.
3. Modify `score_all_categories()` to include the counts (without snippets): `{"category": ..., "score": ..., "primary_hits": N, "booster_hits": N}`.

This is a **separate change to `memory_triage.py`** -- the analyzer can only detect booster anomalies if the data is logged. Since the task is specifically about `memory_log_analyzer.py`, the detector should be written to gracefully handle both old-format and new-format log data.

### Function design

Place after `_detect_category_never_triggers` (after current line 247), before `_detect_missing_event_types`:

```python
def _detect_booster_never_hits(events, event_counts):
    """BOOSTER_NEVER_HITS: category has 0 booster hits but non-zero primary scores.

    Requires triage.score events to include per-category primary_hits and
    booster_hits fields in all_scores. If these fields are absent (old log
    format), the detector is silently skipped.
    """
    triage_events = [
        e for e in events if e.get("event_type") == "triage.score"
    ]
    if not triage_events:
        return []

    # Guard: insufficient sample size
    if len(triage_events) < _MIN_TRIAGE_EVENTS_BOOSTER:
        return []

    # Accumulate per-category: total primary hits and total booster hits
    cat_primary_total = Counter()
    cat_booster_total = Counter()
    has_booster_fields = False

    for e in triage_events:
        data = e.get("data", {})
        if not isinstance(data, dict):
            continue
        all_scores = data.get("all_scores", [])
        if not isinstance(all_scores, list):
            continue
        for s in all_scores:
            if not isinstance(s, dict) or "category" not in s:
                continue
            # Detect new-format log data
            if "primary_hits" in s or "booster_hits" in s:
                has_booster_fields = True
                cat = s["category"]
                cat_primary_total[cat] += s.get("primary_hits", 0)
                cat_booster_total[cat] += s.get("booster_hits", 0)

    # If no events contain booster fields, skip silently (old format)
    if not has_booster_fields:
        return []

    findings = []
    for cat in sorted(_ALL_TRIAGE_CATEGORIES):
        # SESSION_SUMMARY is activity-based, no booster concept -- skip
        if cat == "SESSION_SUMMARY":
            continue
        primary = cat_primary_total.get(cat, 0)
        booster = cat_booster_total.get(cat, 0)
        if primary > 0 and booster == 0:
            findings.append({
                "severity": "warning",
                "code": "BOOSTER_NEVER_HITS",
                "message": (
                    f"Category {cat} has {primary} primary pattern hits "
                    f"but 0 booster hits across {len(triage_events)} "
                    f"triage events. Booster patterns may be too narrow."
                ),
                "data": {
                    "category": cat,
                    "primary_hits": primary,
                    "booster_hits": 0,
                    "sample_size": len(triage_events),
                },
            })

    return findings
```

**Design decisions:**
- **Severity: "warning"** (not "high") -- booster patterns being too narrow is a tuning concern, not an operational failure.
- **Graceful degradation:** The `has_booster_fields` check means this detector is no-op on old-format logs. No errors, no false positives.
- **SESSION_SUMMARY excluded:** It's activity-based (tool uses, exchanges), not pattern-based, so it has no booster concept.
- **Accumulation across events:** We sum `primary_hits` and `booster_hits` across ALL triage events rather than checking per-event. A category might have 0 booster hits per event individually due to short sessions, but if across 50+ events the total is still 0, the patterns genuinely aren't matching.

### Wiring in `analyze()` function

Add after the `_detect_category_never_triggers` call (after current line 431):

```python
    findings.extend(_detect_booster_never_hits(events, event_counts))
```

### Wiring in `_generate_recommendations()`

Add a new recommendation block:

```python
    if "BOOSTER_NEVER_HITS" in codes_seen:
        booster_cats = sorted(
            f["data"]["category"]
            for f in findings
            if f["code"] == "BOOSTER_NEVER_HITS"
        )
        recs.append(
            f"Categories {', '.join(booster_cats)} have primary pattern "
            f"matches but zero booster co-occurrence hits. Review booster "
            f"patterns in memory_triage.py CATEGORY_PATTERNS or check "
            f"that conversation content includes contextual booster terms."
        )
```

---

## 6. "insufficient_data" Info-Level Finding Decision

**Decision: Do NOT emit info-level findings when guards trigger.**

Rationale:
1. **Noise at startup:** Every new deployment will have <30 events. Emitting "insufficient data" for every detector on every early run creates noise that obscures real findings.
2. **Silent absence is the correct behavior.** If there are no findings, the output already says "No anomalies detected. System operating normally." The absence of a finding is the intended signal.
3. **Transparency is in the data dict.** For findings that DO fire, we include `sample_size`. For findings that don't fire, there's nothing to annotate.
4. **Existing precedent:** The `retrieval_events == 0` early return in `_detect_skip_rate_high` already returns None silently. The guards follow the same pattern.

If operational visibility of the guard-triggering is needed in the future, it should be added as structured logging (`emit_event("analyzer.guard_triggered", ...)`) in the analyzer script itself, not as a finding in the output.

---

## 7. Edge Case Analysis

### N=0 (no relevant events)

| Detector | Current behavior | New behavior | Change? |
|---|---|---|---|
| `_detect_zero_length_prompt` | `skip_events` empty -> returns None | Same (empty check before guard) | No change |
| `_detect_skip_rate_high` | `retrieval_events == 0` -> returns None | Same (zero check before guard) | No change |
| `_detect_category_never_triggers` | `triage_events` empty -> returns [] | Same (empty check before guard) | No change |
| `_detect_booster_never_hits` | N/A (new) | `triage_events` empty -> returns [] | Correct |

### N = threshold - 1 (just below minimum)

| Detector | Threshold | N | Behavior |
|---|---|---|---|
| `_detect_zero_length_prompt` | 10 | 9 skip events | Returns None (guard triggers) |
| `_detect_skip_rate_high` | 20 | 19 retrieval events | Returns None (guard triggers) |
| `_detect_category_never_triggers` | 30 | 29 triage events | Returns [] (guard triggers) |
| `_detect_booster_never_hits` | 50 | 49 triage events | Returns [] (guard triggers) |

**Verification:** The original false positive (N=5 skip events) is correctly suppressed by the N>=10 guard.

### N = threshold (exactly at minimum)

| Detector | Threshold | N | Behavior |
|---|---|---|---|
| `_detect_zero_length_prompt` | 10 | 10 skip events | Guard passes, normal analysis proceeds |
| `_detect_skip_rate_high` | 20 | 20 retrieval events | Guard passes, normal analysis proceeds |
| `_detect_category_never_triggers` | 30 | 30 triage events | Guard passes, normal analysis proceeds |
| `_detect_booster_never_hits` | 50 | 50 triage events | Guard passes, normal analysis proceeds |

**Note:** The guard condition is `< threshold` (strict less-than), so N == threshold passes.

### N = threshold + 1 (just above minimum)

Same as N = threshold. Analysis proceeds normally. No special behavior.

### Special edge: all old-format log data for booster detector

If ALL triage.score events lack `primary_hits`/`booster_hits` fields (pre-change logs), `has_booster_fields` stays False and the function returns []. This is correct -- cannot analyze what isn't logged.

### Special edge: mixed old/new format log data for booster detector

If SOME events have booster fields (post-upgrade) but some don't (pre-upgrade), the detector only counts from events that have the fields. The `sample_size` in findings reports total `len(triage_events)`, which includes both old and new. This is acceptable since:
- The guard threshold (50) is high enough that we need substantial new-format data.
- The accumulation only uses actual booster data, not assuming zeros for old events.

---

## 8. Upstream Change Required (memory_triage.py)

To enable `_detect_booster_never_hits`, the following change to `memory_triage.py` is needed:

### 8a. `score_text_category` return type (line 355-404)

**Old:** Returns `tuple[float, list[str]]` (score, snippets)

**New:** Returns `tuple[float, list[str], int, int]` (score, snippets, primary_count, boosted_count)

Change the return statement (line 403-404) from:
```python
    normalized = min(1.0, raw_score / denominator) if denominator > 0 else 0.0
    return normalized, snippets
```
to:
```python
    normalized = min(1.0, raw_score / denominator) if denominator > 0 else 0.0
    return normalized, snippets, primary_count, boosted_count
```

### 8b. `_score_all_raw` (lines 431-464)

Change the text-category loop (lines 448-454) from:
```python
    for category in CATEGORY_PATTERNS:
        score, snippets = score_text_category(lines, category)
        all_raw.append({
            "category": category,
            "score": score,
            "snippets": snippets,
        })
```
to:
```python
    for category in CATEGORY_PATTERNS:
        score, snippets, p_hits, b_hits = score_text_category(lines, category)
        all_raw.append({
            "category": category,
            "score": score,
            "snippets": snippets,
            "primary_hits": p_hits,
            "booster_hits": b_hits,
        })
```

And for SESSION_SUMMARY (lines 457-462), add zero hits since it's activity-based:
```python
    score, snippets = score_session_summary(metrics)
    all_raw.append({
        "category": "SESSION_SUMMARY",
        "score": score,
        "snippets": snippets,
        "primary_hits": 0,
        "booster_hits": 0,
    })
```

### 8c. `score_all_categories` (lines 488-505)

Change the return list comprehension (lines 501-504) from:
```python
    return [
        {"category": entry["category"], "score": round(entry["score"], 4)}
        for entry in all_raw
    ]
```
to:
```python
    return [
        {
            "category": entry["category"],
            "score": round(entry["score"], 4),
            "primary_hits": entry.get("primary_hits", 0),
            "booster_hits": entry.get("booster_hits", 0),
        }
        for entry in all_raw
    ]
```

### 8d. Callers of `score_text_category` outside `_score_all_raw`

Search confirms `score_text_category` is only called from `_score_all_raw`, so the return type change is safe. However, tests may destructure as `score, snippets = score_text_category(...)`. Those need updating to `score, snippets, _, _ = ...` or `score, snippets, p, b = ...`.

---

## 9. Severity Level for _SEVERITY_ORDER

The existing `_SEVERITY_ORDER` dict (line 35) is:
```python
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "warning": 3}
```

The new `BOOSTER_NEVER_HITS` finding uses severity `"warning"`, which is already in the ordering. No change needed.

However, the `_SEVERITY_ICONS` dict (line 522-527) also includes `"warning"`. No change needed there either.

---

## 10. Complete File Change Summary

### `hooks/scripts/memory_log_analyzer.py`

| Location | Change |
|---|---|
| Line 47 (after `_MAX_EVENTS`) | Add 4 `_MIN_*` constants |
| `_detect_skip_rate_high` (line 139) | Add guard after `retrieval_events == 0` check; add `sample_size` to data |
| `_detect_zero_length_prompt` (line 167) | Add guard after `not skip_events` check; add `sample_size` to data |
| `_detect_category_never_triggers` (line 200) | Add guard after `not triage_events` check; add `sample_size` to data; update message |
| After `_detect_category_never_triggers` | Insert new `_detect_booster_never_hits` function |
| `analyze()` (line 431) | Add `findings.extend(_detect_booster_never_hits(...))` call |
| `_generate_recommendations()` | Add `BOOSTER_NEVER_HITS` recommendation block |

### `hooks/scripts/memory_triage.py` (upstream prerequisite)

| Location | Change |
|---|---|
| `score_text_category` return | Add `primary_count, boosted_count` to return tuple |
| `_score_all_raw` text loop | Destructure 4 values; add `primary_hits`/`booster_hits` to dict |
| `_score_all_raw` SESSION_SUMMARY | Add `primary_hits: 0, booster_hits: 0` |
| `score_all_categories` | Include `primary_hits`/`booster_hits` in output dicts |

### Tests needed

| Test | Purpose |
|---|---|
| `test_zero_prompt_guard_below_threshold` | N=9 skip events, all with prompt_length=0 -> returns None |
| `test_zero_prompt_guard_at_threshold` | N=10 skip events, all with prompt_length=0 -> returns finding |
| `test_zero_prompt_guard_zero_events` | N=0 skip events -> returns None (existing behavior preserved) |
| `test_skip_rate_guard_below_threshold` | N=19 retrieval events (all skip) -> returns None |
| `test_skip_rate_guard_at_threshold` | N=20 retrieval events (all skip) -> returns finding |
| `test_category_guard_below_threshold` | N=29 triage events -> returns [] |
| `test_category_guard_at_threshold` | N=30 triage events with never-triggering category -> returns findings |
| `test_booster_never_hits_below_threshold` | N=49 triage events with booster data -> returns [] |
| `test_booster_never_hits_at_threshold` | N=50, primary>0, booster=0 -> returns finding |
| `test_booster_never_hits_old_format` | N=50 events without booster fields -> returns [] |
| `test_booster_never_hits_mixed_format` | Mix of old/new format events -> correct accumulation |
| `test_booster_never_hits_session_summary_excluded` | SESSION_SUMMARY category never appears in findings |
| `test_booster_never_hits_nonzero_booster` | primary>0 AND booster>0 -> no finding |
| `test_sample_size_in_data` | All findings include `sample_size` key |

---

## 11. Alternatives Considered

### A. Configurable thresholds via memory-config.json
**Rejected.** The minimum sample sizes are statistical validity concerns, not user preferences. Making them configurable invites users setting them to 1, defeating the purpose. These should be code-level constants.

### B. Emitting "info" severity findings when guards trigger
**Rejected.** See Section 6. Creates noise during normal startup and early usage. Silent suppression with eventual structured logging is the better approach.

### C. Using confidence intervals instead of hard cutoffs
**Considered, deferred.** A Wilson score interval or similar could compute confidence bounds on rates, allowing smaller N with wider intervals. This is more statistically rigorous but adds complexity. The hard cutoffs are simple, predictable, and sufficient for the problem at hand. Can revisit if false negatives become an issue with the current thresholds.

### D. Separate upstream PR for triage.py changes
**Recommended.** The triage.py changes (exposing booster hit counts) should be implemented first, since the booster detector in the analyzer depends on the data being present. The three guard changes to the analyzer can be implemented independently and immediately, without waiting for triage.py changes. The booster detector can be added in the same PR as the triage.py change, since it's no-op without the data.

### E. Computing booster hit rate from score delta instead of explicit counts
**Rejected.** Theoretically, if primary_weight and boosted_weight are known, you could reverse-engineer hit counts from the final score. But this is fragile (depends on caps, denominator, normalization) and breaks if the scoring formula changes. Explicit counts from the source are more reliable.
