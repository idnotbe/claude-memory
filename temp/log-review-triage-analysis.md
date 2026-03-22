# Triage CATEGORY_NEVER_TRIGGERS Deep Analysis

**Date**: 2026-03-22
**Analyzer Report**: `temp/log-review-analyzer-report.json`
**Raw Data**: `/home/idnotbe/projects/ops/.claude/memory/logs/triage/2026-03-21.jsonl` (71 events)
**Scope**: CONSTRAINT, DECISION, PREFERENCE -- 3 HIGH severity findings

---

## 1. Raw Data Summary

### Score Distributions (71 triage.score events)

#### CONSTRAINT (threshold=0.5) -- NEVER TRIGGERED
| Metric | Value |
|--------|-------|
| Non-zero events | 38/71 (53.5%) |
| Distinct scores | 0.1579, 0.3158, 0.4737 |
| Max observed | 0.4737 (17 times) |
| Score meaning | 0.1579=1 primary, 0.3158=2 primaries, 0.4737=3 primaries |
| Boosters fired | **NEVER** (all scores are exact multiples of primary_weight/denominator) |
| Gap to threshold | 0.0263 (0.4737 vs 0.5) |

#### DECISION (threshold=0.4) -- NEVER TRIGGERED
| Metric | Value |
|--------|-------|
| Non-zero events | 12/71 (16.9%) |
| Distinct scores | 0.1579, 0.2632 |
| Max observed | 0.2632 (9 times) |
| Score meaning | 0.1579=1 primary (no boost), 0.2632=1 boosted match |
| Boosters fired | YES (9 times), but only 1 match per event |
| Gap to threshold | 0.1368 (0.2632 vs 0.4) |

#### PREFERENCE (threshold=0.4) -- NEVER TRIGGERED
| Metric | Value |
|--------|-------|
| Non-zero events | 9/71 (12.7%) |
| Distinct scores | 0.1707, 0.3415 |
| Max observed | 0.3415 (1 time) |
| Score meaning | 0.1707=1 primary, 0.3415=2 primaries |
| Boosters fired | **NEVER** |
| Gap to threshold | 0.0585 (0.3415 vs 0.4) |

### Triggering Categories (for comparison)

| Category | Threshold | Triggered | Max Score | Trigger Rate |
|----------|-----------|-----------|-----------|-------------|
| SESSION_SUMMARY | 0.6 | 70/71 | 1.0 | 98.6% |
| RUNBOOK | 0.4 | 13/71 | 1.0 | 18.3% |
| TECH_DEBT | 0.4 | 6/71 | 0.8421 | 8.5% |
| CONSTRAINT | 0.5 | 0/71 | 0.4737 | 0.0% |
| DECISION | 0.4 | 0/71 | 0.2632 | 0.0% |
| PREFERENCE | 0.4 | 0/71 | 0.3415 | 0.0% |

---

## 2. Threshold Analysis

### The Scoring Math

Each category scores via: `raw_score / denominator`, where raw_score = (primary_matches * primary_weight) + (boosted_matches * boosted_weight), capped at max_primary and max_boosted respectively.

### CONSTRAINT: Structural Impossibility

```
primary_weight=0.3, boosted_weight=0.5, max_primary=3, max_boosted=2, denominator=1.9
threshold=0.5

Max score WITHOUT booster = 3 * 0.3 / 1.9 = 0.4737
Threshold = 0.5
Gap = 0.0263

VERDICT: It is mathematically impossible to reach the threshold without at least
one booster keyword co-occurring within 4 lines of a primary keyword.

Minimum score WITH 1 booster + 1 primary = (0.5 + 0.3) / 1.9 = 0.4211
Minimum score WITH 1 booster only = 0.5 / 1.9 = 0.2632
Score WITH 1 booster + 2 primaries = (0.5 + 0.6) / 1.9 = 0.5789  <-- would trigger
```

The booster keywords for CONSTRAINT are: `discovered, found that, turns out, permanently, enduring, platform`. These never co-occurred within 4 lines of the primary keywords (`limitation, api limit, cannot, restricted, not supported, quota, rate limit`) across 71 events.

### DECISION: Mathematically Reachable but Practically Unmet

```
Same weights as CONSTRAINT. threshold=0.4
Max WITHOUT booster = 0.4737 (would trigger, but never observed)
Max observed = 0.2632 (1 boosted match)

The threshold IS reachable without boosters (3 primaries = 0.4737 > 0.4).
The issue is that ops conversations never produce 3+ decision keywords.
```

### PREFERENCE: Mathematically Reachable but Practically Unmet

```
primary_weight=0.35, boosted_weight=0.5, max_primary=3, max_boosted=2, denominator=2.05
threshold=0.4

Max WITHOUT booster = 3 * 0.35 / 2.05 = 0.5122 (would trigger)
Max observed = 0.3415 (2 primaries)

The threshold IS reachable (3 primaries or 1 boosted + 1 primary).
The issue is that ops conversations never produce 3+ preference keywords.
```

---

## 3. Root Cause Analysis

### CONSTRAINT: Calibration Bug + Keyword Mismatch (Dual Root Cause)

**Root Cause 1 -- Threshold Calibration Bug**: The threshold (0.5) exceeds the maximum achievable score without booster co-occurrence (0.4737). This means that even a conversation saturated with constraint-related language ("cannot do X", "restricted by Y", "API limit on Z") will never trigger unless it also contains discovery-narrative phrases ("discovered", "turns out", "permanently"). This is a structural gap of 0.0263 in the scoring math.

**Root Cause 2 -- Keyword Cross-Contamination**: 58.8% of the CONSTRAINT=0.4737 events also had RUNBOOK >= 0.4. The primary keyword `cannot` is extremely common in error-debugging contexts (which are RUNBOOK territory), not just genuine platform constraints. The high overlap suggests that many of the 17 max-scoring CONSTRAINT events are actually collateral hits from debugging conversations, not genuine constraint discoveries.

**Root Cause 3 -- Booster Vocabulary Misalignment**: The booster keywords (`discovered, found that, turns out, permanently, enduring, platform`) are discovery-narrative phrases. In ops work, constraints are often stated matter-of-factly ("the managed plan doesn't support X", "rate limited to 100 req/s") rather than narrated as discoveries.

### DECISION: Keyword Set Too Narrow for Ops Domain

The DECISION primary keywords require explicit decision verbs: "decided", "chose", "selected", "went with", "let's go with", "we should use", etc. In ops/infrastructure work, decisions tend to be implicit ("using nginx", "deploying to us-east-1") rather than explicit ("we decided to use nginx"). The 9 events with score 0.2632 show that boosters DO fire (1 time each), but the primary signal itself is too weak for the ops domain.

### PREFERENCE: Low Signal Density in Ops

Only 9/71 events had any preference signal at all. Preference keywords ("always use", "prefer", "convention", "from now on") appear infrequently in infrastructure work. The max of 2 primary matches (0.3415) appeared only once. This is likely expected behavior for the ops domain.

---

## 4. False Positive Risk Assessment

### If CONSTRAINT Threshold Lowered to 0.45

| Scenario | Events | Rate | Risk Level |
|----------|--------|------|-----------|
| Would newly trigger | 17/71 | 23.9% | **HIGH** |
| Of those, also RUNBOOK >= 0.4 | 10/17 | 58.8% | Dual-trigger noise |
| Short text (<5k) triggers | 5/17 | 29.4% | Possible FP from sparse "cannot" |
| Long text (>10k) triggers | 12/17 | 70.6% | More likely genuine signal |

**Risk**: High false positive rate due to `cannot` cross-contamination with debugging contexts. Lowering the threshold alone (without keyword refinement) would cause ~24% of all triage events to trigger CONSTRAINT, many of which would be error-debugging conversations misclassified as platform constraints.

### If DECISION Threshold Lowered to 0.26

| Scenario | Events | Rate | Risk Level |
|----------|--------|------|-----------|
| Would newly trigger | 12/71 | 16.9% | **MODERATE** |
| All 9 of the 0.2632 events are boosted | 9/12 | 75% | Reasonable signal quality |

**Risk**: Moderate. The 0.2632 events represent a boosted match (primary + booster within 4 lines), which is a stronger signal than primary-only. However, a single decision phrase + rationale word may not always indicate a memory-worthy decision.

### If PREFERENCE Threshold Lowered to 0.34

| Scenario | Events | Rate | Risk Level |
|----------|--------|------|-----------|
| Would newly trigger | 1/71 | 1.4% | **LOW** |
| At 0.15 (catching all non-zero) | 9/71 | 12.7% | Moderate volume |

**Risk**: Low at 0.34 (only 1 additional trigger). But this threshold captures only the single event with 2+ primary matches, which may be too conservative to be useful.

---

## 5. Self-Critique

### What I might be wrong about

1. **Calling CONSTRAINT a "bug" may be too strong.** Gemini's cross-model assessment argues this is intentional design -- the threshold deliberately requires booster co-occurrence as a noise filter, since `cannot`/`restricted` are too noisy alone. The 58.8% RUNBOOK overlap supports this interpretation. If it IS intentional, the "fix" is not to lower the threshold but to improve the booster vocabulary so genuine constraints CAN reach the threshold.

2. **One day of data is insufficient for threshold tuning.** This analysis covers 71 events from a single ops project on a single day. The plugin is designed to work across diverse project types. Lowering global defaults based on this narrow sample risks overfitting to ops-style conversations at the expense of other project types (greenfield development, frontend work, API design) where different patterns dominate.

3. **"Never triggers" may be correct behavior.** If the ops project genuinely does not produce constraint/decision/preference-worthy content, then zero triggers is the correct outcome. The analyzer flags these as "HIGH severity" because it cannot distinguish between "correctly silent" and "broken silent."

4. **The DECISION booster signal is actually working.** Unlike CONSTRAINT and PREFERENCE where boosters never fired, DECISION boosters DO fire (producing 0.2632 scores). The issue is that only 1 match is found per event. This suggests the booster vocabulary is appropriate but the primary keyword coverage is too narrow for ops conversations.

### What I am confident about

1. **The CONSTRAINT threshold math is a structural problem regardless of intent.** Whether intentional or not, a category that can NEVER trigger without booster co-occurrence -- when boosters demonstrably never fire in real usage -- is effectively disabled. If it was intentional, the booster vocabulary needs expansion so the intended gate mechanism actually works.

2. **The booster vocabularies for CONSTRAINT and PREFERENCE need review.** Zero booster hits across 38 non-zero CONSTRAINT events and 9 non-zero PREFERENCE events means the booster keywords are misaligned with real ops conversation patterns.

3. **Per-project threshold tuning is the safest short-term solution.** The ops project config already supports `triage.thresholds` overrides.

---

## 6. Cross-Model Opinions

### Codex Assessment: "Calibration bug, fix with quantum-aligned thresholds"

**Verdict**: Confirms CONSTRAINT is a structural calibration error. Recommends threshold changes aligned to attainable score quanta:

| Category | Codex Recommended | Rationale |
|----------|-------------------|-----------|
| CONSTRAINT | 0.47 | Smallest change to re-enable 3-primary pattern |
| DECISION | 0.26 | Captures the 1-boosted-match pattern observed |
| PREFERENCE | 0.34 | Captures 2+ primary matches |

**Key insight from Codex**: CONSTRAINT needs keyword changes alongside threshold adjustment -- bare `cannot` should be demoted or replaced with structural phrases (`does not support`, `limited to`, `hard limit`, `vendor limitation`). Recommends phased rollout: fix DECISION + PREFERENCE thresholds first, then CONSTRAINT after keyword cleanup.

**False positive estimates**: CONSTRAINT 23.9%, DECISION 16.9%, PREFERENCE 12.7% max additional trigger rate.

### Gemini Assessment: "Expected behavior, do not change defaults"

**Verdict**: Strongly argues this is correct behavior, not a bug. Key arguments:

1. The CONSTRAINT threshold intentionally requires booster co-occurrence as a noise filter for the noisy primary keywords (`cannot`, `restricted`).
2. Ops projects inherently produce fewer decisions/preferences compared to greenfield development.
3. Lowering thresholds would cause "extreme feature fatigue" by interrupting users with false captures.
4. Per-project tuning already exists for users who want higher sensitivity.
5. One day of data from one project is insufficient to change global defaults.

**Key insight from Gemini**: The 58.8% CONSTRAINT/RUNBOOK overlap "proves the design intent" -- the booster gate deliberately filters transient debugging noise from permanent platform constraints.

### Synthesis

The models disagree fundamentally on whether the CONSTRAINT threshold is a bug (Codex) or a feature (Gemini). Both make valid points:

- Codex is right that a category that *never* triggers in practice is effectively disabled, which undermines its purpose.
- Gemini is right that lowering the threshold without fixing the keywords would produce false positives from debugging noise.
- Both agree that the keyword vocabulary needs attention, particularly for CONSTRAINT.

The resolution is that **both are partially correct**: the threshold math is structurally problematic (Codex), but the fix must address keywords alongside thresholds (also Codex), and global default changes should wait for broader data (Gemini). Per-project tuning is the right immediate action (Gemini).

---

## 7. Final Assessment

**Confidence Level: HIGH for diagnosis, MODERATE for recommendations**

### Diagnosis (HIGH confidence)

1. **CONSTRAINT has a structural scoring gap**: The threshold (0.5) exceeds the max-without-booster ceiling (0.4737) by 0.0263. This is a mathematical fact, not interpretation. Combined with zero booster hits in 71 events, CONSTRAINT is effectively disabled.

2. **Booster vocabularies are misaligned for ops usage**: CONSTRAINT and PREFERENCE boosters never fired. This is a systemic gap, not category-specific.

3. **DECISION and PREFERENCE are domain-limited, not structurally broken**: Their thresholds are mathematically reachable but the keyword coverage is too narrow for ops conversations.

### The Nuanced Truth

The "never triggers" finding is **both a structural problem AND partly expected behavior**:
- CONSTRAINT: Structural problem (threshold > max-no-booster ceiling) compounded by keyword noise. **This IS a bug**, whether the booster-gating was intentional or not, because the gate never opens.
- DECISION: Domain mismatch. The keywords expect explicit decision verbs that ops work rarely uses. **Partly expected, partly a keyword coverage gap.**
- PREFERENCE: Low signal density in ops domain. **Mostly expected behavior** for this project type.

---

## 8. Recommended Threshold Adjustments

### Tier 1: Immediate (per-project config for ops)

Adjust `triage.thresholds` in the ops project's `memory-config.json`:

```json
{
  "triage": {
    "thresholds": {
      "constraint": 0.45,
      "decision": 0.35,
      "preference": 0.35
    }
  }
}
```

**Rationale**: Per-project tuning avoids affecting other projects. The ops project can tolerate slightly more triggers to verify if the captures are useful.

### Tier 2: Short-term (default config keyword improvements)

**CONSTRAINT keyword refinements** (in `memory_triage.py`):
- Demote bare `cannot` -- too noisy, fires in every debugging conversation
- Add ops-relevant primary phrases: `does not support`, `limited to`, `hard limit`, `service limit`, `vendor limitation`, `managed plan`
- Expand boosters: `incompatible`, `deprecated`, `blocked by`, `upstream`, `provider`, `by design`, `not configurable`

**PREFERENCE booster expansion**:
- Add: `standard`, `always`, `formatting`, `naming`, `style guide`, `prefer to`

### Tier 3: Medium-term (default threshold adjustment)

After keyword improvements are validated across multiple projects:

| Category | Current | Proposed | Rationale |
|----------|---------|----------|-----------|
| CONSTRAINT | 0.50 | 0.47 | Allows 3 primaries to trigger; keywords must be cleaned first |
| DECISION | 0.40 | 0.35 | Allows 2 primaries + no booster to trigger (0.3158) |
| PREFERENCE | 0.40 | 0.35 | Allows 2 primaries to trigger (0.3415) |

### Tier 4: Validation requirement

Before merging any default threshold changes:
- Collect triage logs from 3+ different project types (ops, frontend, backend/API, plugin development)
- Manually label 50+ newly-triggered events as true positive / false positive
- Target precision >= 70% for each category before accepting new thresholds

---

## Appendix: Score Quantum Reference

For quick reference, here are all achievable score values for each category:

### CONSTRAINT / DECISION (denom=1.9, pw=0.3, bw=0.5)
| Pattern | Raw | Normalized |
|---------|-----|-----------|
| 1 primary | 0.3 | 0.1579 |
| 2 primaries | 0.6 | 0.3158 |
| 3 primaries | 0.9 | 0.4737 |
| 1 boosted | 0.5 | 0.2632 |
| 1 boosted + 1 primary | 0.8 | 0.4211 |
| 1 boosted + 2 primaries | 1.1 | 0.5789 |
| 1 boosted + 3 primaries | 1.4 | 0.7368 |
| 2 boosted | 1.0 | 0.5263 |
| 2 boosted + 1 primary | 1.3 | 0.6842 |
| 2 boosted + 2 primaries | 1.6 | 0.8421 |
| 2 boosted + 3 primaries | 1.9 | 1.0000 |

### PREFERENCE (denom=2.05, pw=0.35, bw=0.5)
| Pattern | Raw | Normalized |
|---------|-----|-----------|
| 1 primary | 0.35 | 0.1707 |
| 2 primaries | 0.70 | 0.3415 |
| 3 primaries | 1.05 | 0.5122 |
| 1 boosted | 0.50 | 0.2439 |
| 1 boosted + 1 primary | 0.85 | 0.4146 |
| 2 boosted + 3 primaries | 2.05 | 1.0000 |
