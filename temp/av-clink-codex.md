# Codex Code Review: Minimum Sample Size Guards for memory_log_analyzer.py

**Source**: codex (codereviewer role) via PAL clink
**Date**: 2026-03-22
**File reviewed**: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_log_analyzer.py`

---

## Findings

### HIGH: Booster detector not implementable from current log schema

`memory_triage.py` tracks `boosted_count` only as a local variable inside `score_text_category()`, but `all_scores` is stripped down to `{category, score}` before logging. The analyzer cannot distinguish "primary hit with no booster" from "no primary hit at all" or "low final score for another reason."

**Fix**: Extend `triage.score.data.all_scores[]` to include per-category observability fields: `primary_hits`, `boosted_hits`, `had_booster`, and ideally `threshold`.

### MEDIUM: Global N>=30 guard insufficient for _detect_category_never_triggers

A global `N >= 30 triage.score events` guard is not sufficient. Even after adding a 30-event global floor, one category could still have only 1-2 meaningful exposures and get flagged.

**Fix**: Guard on per-category eligible exposures, not total triage volume. Count events where that category had `score > 0`, and require a category-specific minimum before warning.

### MEDIUM: ZERO_LENGTH_PROMPT uses wrong denominator

The detector divides zero-length cases by all `retrieval.skip` events, but most skip reasons do not carry `prompt_length`; only the short-prompt path does. Unrelated skip reasons dilute or distort the rate.

**Fix**: Base the detector and its min-sample guard on "eligible skip events with `prompt_length` present," not all skip events.

### LOW: INSUFFICIENT_DATA as ordinary finding does not fit output model

Severity handling is hard-coded, and recommendations/exit behavior assume findings are actionable anomalies. Extra noise in reports and automation.

**Fix**: Return `None` silently in the main findings list. If visibility is needed, add a separate `suppressed_checks` / `analysis_meta` section rather than an info-level finding.

---

## Threshold Assessment

| Detector | Proposed N | Codex Assessment |
|---|---|---|
| `_detect_zero_length_prompt` | N>=10 | Weak for `critical` severity. Use **15-20**, or downgrade severity |
| `_detect_skip_rate_high` | N>=20 | Reasonable |
| `_detect_category_never_triggers` | N>=30 | Reasonable **only if** it means 30 eligible exposures for that specific category, not 30 total triage events |
| `_detect_booster_never_hits` | N>=50 | Strong, but requires schema changes first |

---

## Answers to Specific Questions

### Insufficient-sample behavior
Prefer silent `None` for `findings`. If operators need visibility, expose suppressed checks in metadata, not as ordinary findings.

### Booster detector output fields
Include: `category`, `eligible_events`, `booster_hit_events`, `booster_hit_rate`, `trigger_count`, `avg_score`, `max_score`, and `threshold`. To compute correctly, log `primary_hits` and `boosted_hits` per category in `triage.score`.

### Edge cases and pitfalls
- **Mixed-version windows**: Older logs without new booster fields will confound rates. Must suppress the detector rather than guess.
- **Live log mutation**: Logs can mutate during analysis.
- **SESSION_SUMMARY exclusion**: Should be excluded from booster logic (it uses different triggering).
- **Denominator correctness**: `ZERO_LENGTH_PROMPT` denominator must filter to eligible skip events only.

---

## Positives Noted
- Clean structured finding format and deterministic severity sorting
- Logging `all_scores` in triage was the right move -- good base for richer analytics
- Loader's path validation and fail-open parsing are solid operational choices

---

## Summary

The current analyzer is structurally sound, but the proposed guard work has two important design constraints:

1. `_detect_booster_never_hits` cannot be implemented correctly from today's logs because `triage.score` only records `{category, score}`; `boosted_count` is computed in `memory_triage.py` and discarded before logging. Schema changes needed first.

2. The sample-size guard for `_detect_category_never_triggers` must be per-category exposure, not just "30 triage events overall," otherwise sparse categories will still false-positive.

For insufficient data handling, do not emit an ordinary info-level finding. Use silent suppression in `findings`, and optionally expose a separate `suppressed_checks` metadata block.
