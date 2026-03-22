# Adversarial Analysis: memory_log_analyzer.py -- Sample Guards & Booster Detector

**Date:** 2026-03-22
**Scope:** Minimum sample guards (`_MIN_*` constants), booster detector (`_detect_booster_never_hits`), and related detectors
**Reviewers:** Claude Opus 4.6 (primary), Gemini 3.1 Pro Preview (cross-review via clink)

---

## 1. Log Injection: Type Confusion DoS (CONFIRMED -- HIGH)

**Vector:** Crafted JSONL entries with wrong types for nested fields crash the entire analyzer with unhandled `TypeError`.

**Confirmed crash paths:**

| Location | Crafted Input | Exception |
|----------|--------------|-----------|
| L238: `trigger_counts[t["category"]] += 1` | `{"category": [1,2]}` in `triggered` array | `TypeError: unhashable type: 'list'` |
| L249: `has_nonzero_score.add(s["category"])` | `{"category": [1,2], "score": 5}` in `all_scores` | `TypeError: unhashable type: 'list'` |
| L246: `s.get("score", 0) > 0` | `{"category": "DECISION", "score": "high"}` | `TypeError: '>' not supported between instances of 'str' and 'int'` |
| L309: `cat_primary_total[cat] += s.get("primary_hits", 0)` | `{"primary_hits": "10", "booster_hits": 0, "category": "X"}` | `TypeError: unsupported operand type(s) for +=: 'int' and 'str'` |

**Impact:** The `analyze()` function at L517-539 calls all detectors without try/except. A single malformed JSONL line crashes the entire analyzer, suppressing ALL findings (including legitimate critical anomalies). This is a monitoring-blind attack: an attacker injects one bad line to disable anomaly detection, then exploits the system while the operator believes everything is fine.

**Mitigation path:** The existing code already has partial type guards (`isinstance(data, dict)`, `isinstance(all_scores, list)`, `isinstance(s, dict)`) but stops one level short. Need to add `isinstance(cat, str)` before using as Counter key/set element, and `isinstance(val, (int, float))` before arithmetic.

**Severity assessment:** HIGH. Requires file-write access to `{root}/logs/` directory (same privilege as the plugin itself), but the impact is total monitoring suppression. The logger (`memory_logger.py`) does not validate internal `data` dict structure, only that `data` itself is a dict.

---

## 2. Negative Value Evasion in Booster Detector (CONFIRMED -- MEDIUM)

**Vector:** Inject events with `primary_hits: -50` to drive a category's accumulated primary total to zero or negative, evading the `primary > 0` check at L323.

**Confirmed behavior:**
```
Counter['DECISION'] += -50  =>  Counter['DECISION'] == -50
-50 > 0  =>  False  =>  no finding emitted
```

**Scenario:** An attacker injects 10 events with `primary_hits: -100` among 50 legitimate events where `primary_hits` averages 1. The accumulated total becomes `50*1 + 10*(-100) = -950`. The detector sees `primary == -950`, which is not `> 0`, so the legitimate booster-never-hits anomaly is silently suppressed.

**Mitigation:** Clamp values: `max(0, int(s.get("primary_hits", 0)))`.

---

## 3. False Negatives from Rigid Guards (ACCEPTED RISK -- MEDIUM)

**Vector:** A genuine systemic failure goes undetected because the sample count is below the minimum threshold.

**Concrete scenarios:**

| Guard | Threshold | Scenario | Miss? |
|-------|-----------|----------|-------|
| `_MIN_RETRIEVAL_EVENTS_SKIP_RATE` | 20 | 15 retrieval events, 15 are skips (100% skip rate). Pipeline is broken. | YES -- no alert |
| `_MIN_SKIP_EVENTS_ZERO_PROMPT` | 10 | 8 skip events, all with prompt_length=0. Hook input field is broken. | YES -- no alert |
| `_MIN_TRIAGE_EVENTS_BOOSTER` | 50 | 30 triage events, DECISION has 20 primary hits, 0 booster. Genuine booster issue. | YES -- no alert |

**Assessment:** This is a design tradeoff, not a bug. The guards exist to prevent false positives from tiny samples (e.g., first day of use). However, the current design has NO fallback for catastrophic failure rates (100%). A 100% failure rate with 15 events is almost certainly real.

**Possible improvement:** Add a "catastrophic rate" fallback: if rate >= 100% AND sample >= 5, emit a lower-severity "warning" finding instead of suppressing entirely. This preserves the guard's intent (prevent false positives from noise) while not being completely blind to total failures.

---

## 4. Booster Detector False Positives (DESIGN QUESTION -- LOW)

**Vector:** Category legitimately has primary hits but no booster co-occurrences, and this is normal behavior rather than a misconfiguration.

**Analysis:** The booster detector fires when `primary > 0 AND booster == 0` across all events. For this to be a false positive, a category would need to:
- Consistently match primary patterns (user regularly discusses that topic)
- Never have booster patterns co-occur within the `CO_OCCURRENCE_WINDOW`

**Is this realistic?** Looking at `memory_triage.py` L355-405, booster patterns are contextual terms that should naturally co-occur with primary patterns in real conversations. For example, if "DECISION" primary patterns fire (phrases like "we decided", "let's go with"), booster terms (like "tradeoff", "alternative", "because") should appear nearby in genuine decision-making conversations.

**Edge case:** Short conversations or one-line prompts where the user types a primary keyword in isolation (e.g., "we decided to use X") without any surrounding context. In this case, primary fires but the booster window has nothing to match.

**Assessment:** The severity is correctly set to "warning" (lowest severity). Over 50 events, a category with zero booster hits is genuinely unusual and worth investigating. The detector is well-calibrated for its purpose. However, it could produce noise for categories where booster patterns are too specific. The recommendation message correctly suggests reviewing booster patterns.

---

## 5. Guard Bypass via Exact-Threshold Crafting (LOW -- THEORETICAL)

**Vector:** Attacker crafts exactly N events (at the minimum threshold) to trigger a misleading finding.

**Analysis:** This requires the attacker to:
1. Have write access to log files
2. Know the exact threshold values (they're in the source code, so this is trivial)
3. Craft events that both pass the guard AND produce a misleading rate

**Example:** Inject exactly 10 `retrieval.skip` events with `prompt_length=0` to trigger ZERO_LENGTH_PROMPT. But this requires the operator to have zero legitimate events in the time window (otherwise the rate gets diluted).

**Assessment:** LOW. An attacker with file-write access to the logs directory has far more impactful attacks available (e.g., the type confusion DoS in finding #1). Crafting misleading findings is less damaging than suppressing real findings.

---

## 6. Resource Exhaustion via Oversized Event Payloads (LOW)

**Vector:** A single JSONL line contains an `all_scores` array with millions of entries, causing CPU/memory exhaustion during parsing and iteration.

**Measured impact:**
- 10K `all_scores` entries = ~624 KB per line
- 100K entries = ~6.2 MB per line
- The `_MAX_EVENTS` cap limits event count but not per-event size
- 100K events each with 100 `all_scores` entries = 10M Counter entries = ~38 MB

**Per-category Counter pollution:** The booster detector only checks `_ALL_TRIAGE_CATEGORIES` (6 known names) at L317. Adversarial category names in Counter objects waste memory but cannot affect findings. With 100K events and 100 categories each = 10M Counter entries, memory stays under ~100MB.

**Assessment:** LOW. The `json.loads` call is the real bottleneck -- Python will parse any valid JSON line regardless of size. But realistic JSONL lines from the logger are ~1-5 KB. An attacker would need file-write access to inject oversized lines, and the impact is temporary CPU/memory during analysis (not persistent).

**Possible mitigation:** Skip lines exceeding 64KB before `json.loads` (cheap length check on raw string).

---

## 7. Threshold Level Vibe Check

| Constant | Value | Assessment |
|----------|-------|------------|
| `_MIN_SKIP_EVENTS_ZERO_PROMPT` | 10 | **Reasonable.** This catches "hook input field changed" scenarios. 10 skip events with >50% zero-length is a strong signal. A user would need to submit ~10 prompts to generate this many retrieval events, which is a typical short session. |
| `_MIN_RETRIEVAL_EVENTS_SKIP_RATE` | 20 | **Slightly conservative.** 20 is reasonable for a >90% rate check. At 18/20 (90% exactly), no alert fires. At 19/20 (95%), alert fires. The real question is whether 15 events at 100% should trigger -- see finding #3. |
| `_MIN_TRIAGE_EVENTS_CATEGORY` | 30 | **Good.** Triage fires once per Stop hook invocation. 30 Stop events represents substantial usage. Non-zero scores with 0 triggers across 30 events is a meaningful pattern. |
| `_MIN_TRIAGE_EVENTS_BOOSTER` | 50 | **Appropriately high.** The booster detector checks an absolute-zero condition (booster == 0 across ALL events). Since even rare booster co-occurrences would produce nonzero hits, requiring 50 events to confirm "never" is statistically sound. |
| `_MIN_ERROR_SPIKE_EVENTS` | 10 | **Slightly aggressive for HIGH severity.** 2/10 error events (20%) triggers a HIGH finding. This could fire during initial setup or after a config change. Consider 15-20 for HIGH severity, or demote to "warning" at sample sizes 10-20. |

**Overall:** The thresholds are well-balanced for their intended purpose. The biggest gap is the lack of a "catastrophic rate" fallback (finding #3), not the threshold values themselves. Gemini's suggestion to raise all thresholds to 50-100 is too aggressive -- it would make the analyzer useless for projects with low-to-moderate usage.

---

## Cross-Reviewer Agreement (Claude vs Gemini)

| Finding | Claude | Gemini | Agreement |
|---------|--------|--------|-----------|
| Type confusion DoS | HIGH (confirmed with code) | Critical | AGREE on severity/existence |
| Negative value evasion | MEDIUM (confirmed) | High (mentioned) | AGREE on existence, differ on severity |
| False negatives from guards | MEDIUM (design tradeoff) | High | AGREE, both suggest 100% rate fallback |
| Booster false positives | LOW | High (says "highly likely") | DISAGREE -- Gemini overestimates; "warning" severity is appropriate |
| Resource exhaustion | LOW | Low | AGREE |
| Threshold vibe check | "Reasonable with minor tweaks" | "Too aggressive, raise to 50-100" | DISAGREE -- Gemini's suggestion would cripple the analyzer for low-usage projects |
| Line-length limit | Not initially considered | Suggested 64KB | AGREE -- cheap defense worth adding |

**Key disagreement:** Gemini suggests using a ratio for booster detection (`booster/primary < 0.01`) instead of strict zero. This is overkill -- the detector's purpose is to catch a complete absence of booster hits (misconfiguration), not a low ratio. A category with 1 booster hit out of 100 primary hits is not misconfigured; it just has low co-occurrence. The absolute-zero check is the correct design.

---

## Recommended Fixes (Priority Order)

1. **P1 -- Type safety in detectors:** Add `isinstance(cat, str)` and `isinstance(val, (int, float))` checks in `_detect_category_never_triggers` and `_detect_booster_never_hits` inner loops. A single poisoned JSONL line should not crash the entire analyzer.

2. **P2 -- Clamp numeric values:** Use `max(0, int(...))` for `primary_hits` and `booster_hits` to prevent negative-value evasion.

3. **P2 -- Catastrophic rate fallback:** When rate == 100% and sample >= 5, emit a "warning" level finding instead of suppressing. Apply to `_detect_skip_rate_high` and `_detect_zero_length_prompt`.

4. **P3 -- Line-length limit:** Skip JSONL lines exceeding 64KB before `json.loads` to limit per-event resource consumption.

5. **P3 -- Error spike threshold adjustment:** Consider raising `_MIN_ERROR_SPIKE_EVENTS` to 15 or demoting to "warning" for samples < 20.
