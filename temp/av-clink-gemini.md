# Gemini Code Review: memory_log_analyzer.py -- Minimum Sample Size Guards

**Source:** Gemini 3.1 Pro Preview via PAL clink (codereviewer role)
**Date:** 2026-03-22
**File reviewed:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_log_analyzer.py`

---

## Findings

### HIGH: False Positives on Rate-Based Alerts (Small N)

- **Ref:** Lines ~142 (`_detect_skip_rate_high`), ~175 (`_detect_zero_length_prompt`)
- **Impact:** Calculating rates without sample-size bounds produces 100% anomaly rate on as few as 1-4 events. E.g., 4 `retrieval.skip` events with 0 others triggers a `critical` `SKIP_RATE_HIGH` alert. Creates alert fatigue, erodes operator trust.
- **Recommendation:** Implement the proposed `N>=20` for `_detect_skip_rate_high` and `N>=10` for `_detect_zero_length_prompt`. Statistically, requiring 18/20 skips (90%) yields negligible false-positive rate vs 4/4 (100%).

### MEDIUM: Statistically Unsound Threshold for Category Triggers

- **Ref:** Line ~231 (loop over `_ALL_TRIAGE_CATEGORIES`)
- **Impact:** Proposed `N>=30` **aggregate** `triage.score` events is mathematically flawed. Categories are evaluated unevenly -- rare categories (e.g., `TECH_DEBT`) may only be scored twice within 30 overall events. Flagging "never triggers" based on 2 non-zero scores is a false positive.
- **Recommendation:** Track minimums **per category**. Convert `has_nonzero_score` from `set()` to `Counter()`. Only flag a category if it never triggers **and** `has_nonzero_score[cat] >= 10`.

### MEDIUM: Insufficient Granularity in Proposed Booster Detector

- **Ref:** Proposed `_detect_booster_never_hits`
- **Impact:** Aggregate `N>=50` 0% hit-rate warning risks masking isolated failures. If `RUNBOOK` booster breaks completely but `PREFERENCE` booster hits frequently, aggregate rate stays >0%, hiding the broken booster.
- **Recommendation:** Track booster hit opportunities **per category**. Require `N>=15` booster opportunities per specific category before evaluating a 0% hit rate.

### LOW: Silent Data Drop vs Info-Level Warnings

- **Ref:** General behavior when `N < threshold`
- **Impact:** Silent `return None` on insufficient data produces clean anomaly reports for low-volume setups. Operators may mistake "insufficient telemetry" for "perfect system health."
- **Recommendation:** Yield a finding with severity `"info"` and code `"INSUFFICIENT_DATA"` (e.g., `"Skip rate detector requires 20 events, found 4"`). The existing `_SEVERITY_ORDER.get(f["severity"], 99)` automatically sorts unknown severities to the bottom -- full backwards compatibility without breaking existing UIs.

### LOW: Hard Cutoffs vs Confidence Intervals

- **Ref:** Rate thresholds like `_SKIP_RATE_THRESHOLD = 0.90`
- **Impact:** Hard thresholds are brittle. An 89% anomaly rate across 10,000 events indicates a massive systemic issue, yet 90% cutoff ignores it while flagging 95% at exactly N=20.
- **Recommendation:** For a dependency-free (stdlib only) script, **hard N-cutoffs are an excellent pragmatic MVP**. Do not overcomplicate with confidence intervals (Wilson Score lower bounds) unless hard cutoffs prove insufficient after N-guards are implemented.

---

## Summary of Recommended Fixes

1. **Apply N Guards:** Adopt `N>=10` for zero-length prompts and `N>=20` for high skip rates as proposed.
2. **Per-Category State for category_never_triggers:** Convert `has_nonzero_score` set to `Counter()`, require `N>=10` non-zero scores *per category* before flagging.
3. **Per-Category Boosters:** Evaluate 0% booster hit rates per category (`N>=15` per category), not aggregate across 50+ events.
4. **Visibility:** Return `"info"`-severity `INSUFFICIENT_DATA` findings instead of silent `None` to prevent misinterpretation of low-volume data as healthy.

## Key Positives Noted

- **Defensive Data Handling:** `isinstance(data, dict)` guards before `.get()` and safe `json.JSONDecodeError` handling in `_load_events` -- prevents malformed data from crashing the pipeline.
- **Hard Safety Limits:** `_MAX_EVENTS = 100_000` cap is strong architectural defense against OOM on bloated log directories.

---

## Design Decision Matrix

| Detector | Proposed N | Gemini's N | Scope | Data Return on Small N |
|---|---|---|---|---|
| `_detect_zero_length_prompt` | N>=10 | N>=10 (agreed) | aggregate | `INSUFFICIENT_DATA` info finding |
| `_detect_skip_rate_high` | N>=20 | N>=20 (agreed) | aggregate | `INSUFFICIENT_DATA` info finding |
| `_detect_category_never_triggers` | N>=30 aggregate | **N>=10 per category** | per-category | `INSUFFICIENT_DATA` info finding |
| `_detect_booster_never_hits` | N>=50 aggregate | **N>=15 per category** | per-category | `INSUFFICIENT_DATA` info finding |

**Key insight:** Gemini's main pushback is on the two detectors that proposed aggregate thresholds -- both should use **per-category** minimums instead, since aggregate counts mask uneven category distribution.
