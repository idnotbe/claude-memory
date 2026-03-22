# CONSTRAINT Threshold Fix -- Design Decision

**Date**: 2026-03-22
**Author**: Research & Design Phase (Phase 1)
**Status**: Final recommendation for Phase 2 implementation

---

## 1. Chosen Option: Modified Hybrid (Option C variant)

**Decision**: Lower threshold to **0.45** + demote `cannot` to booster + expand booster vocabulary with structural/permanence terms.

This is a modified hybrid that takes the best elements from all three options:
- From Option A: booster vocabulary expansion (structural terms, not speculative discovery narrative)
- From Option B: `cannot` demotion, ops-relevant primary additions, threshold lowering
- Modification: threshold 0.45 instead of 0.47 for margin robustness (vibe-check correction)

### Why not 0.47?

The vibe check identified that 0.47 leaves only 0.0037 margin above the 3-primary score quantum (0.4737). This is dangerously fragile -- any future weight adjustment, rounding change, or denominator modification could silently re-break the category. Threshold 0.45 provides 0.0237 margin (6x more) while preserving identical crossing behavior: 3 primaries required, 2 primaries insufficient.

### Why not pure Option A (keep 0.5, expand boosters only)?

RUNBOOK proves booster-gating can work (13/71 triggers), but there is zero empirical evidence that the proposed new CONSTRAINT boosters would fire in real conversations. Option A remains speculative -- it might fix the vocabulary misalignment, or it might leave the category dead with a different set of non-firing boosters. The structural impossibility (threshold > max-no-booster) is a mathematical bug that must be fixed regardless of booster quality.

### Why not pure Option B (threshold only + keyword cleanup)?

Option B without booster expansion leaves the booster mechanism vestigial. If we're going to keep the booster architecture (which RUNBOOK validates), the booster vocabulary should at least have a fighting chance of matching real constraint conversations.

---

## 2. Exact Keyword Changes

### Primary Pattern (memory_triage.py line 134)

**Remove from primary**: `cannot`

**Current primary terms** (after removal):
`limitation|api\s+limit|restricted|not\s+supported|quota|rate\s+limit`

**Add to primary**:
`does\s+not\s+support|limited\s+to|hard\s+limit|service\s+limit|vendor\s+limitation`

**Final primary pattern**:
```python
re.compile(
    rf"{_WORD}(limitation|api\s+limit|restricted|not\s+supported|quota|rate\s+limit|does\s+not\s+support|limited\s+to|hard\s+limit|service\s+limit|vendor\s+limitation){_WORD}",
    re.IGNORECASE,
)
```

### Booster Pattern (memory_triage.py line 140)

**Keep existing**: `discovered|found\s+that|turns\s+out|permanently|enduring|platform`

**Add**: `cannot|by\s+design|upstream|provider|not\s+configurable|managed\s+plan|incompatible|deprecated`

**Final booster pattern**:
```python
re.compile(
    rf"{_WORD}(discovered|found\s+that|turns\s+out|permanently|enduring|platform|cannot|by\s+design|upstream|provider|not\s+configurable|managed\s+plan|incompatible|deprecated){_WORD}",
    re.IGNORECASE,
)
```

### Rationale for each keyword change

| Change | Keyword | Rationale |
|--------|---------|-----------|
| Primary REMOVE | `cannot` | 58.8% RUNBOOK overlap. Too generic -- fires in error debugging ("cannot find file") not just constraints. |
| Primary ADD | `does not support` | Explicit constraint signal. More specific than `not supported` (which is kept). |
| Primary ADD | `limited to` | Explicit capacity constraint ("limited to 100 req/s"). |
| Primary ADD | `hard limit` | Unambiguous constraint term. |
| Primary ADD | `service limit` | Cloud/API-specific constraint. |
| Primary ADD | `vendor limitation` | External/third-party constraint. |
| Booster ADD | `cannot` | Demoted from primary. Still contributes when co-occurring with real constraint keywords. |
| Booster ADD | `by design` | Indicates permanence -- constraint is intentional, not a bug. |
| Booster ADD | `upstream` | Indicates external origin -- constraint imposed by dependency/platform. |
| Booster ADD | `provider` | Cloud/SaaS context -- constraint from service provider. |
| Booster ADD | `not configurable` | Indicates the constraint cannot be worked around. |
| Booster ADD | `managed plan` | Cloud tier-specific constraint. |
| Booster ADD | `incompatible` | Structural incompatibility constraint. |
| Booster ADD | `deprecated` | Capability removal constraint. |

---

## 3. Exact Threshold Value

**New threshold**: `0.45`

### Score Quantum Verification at 0.45

| Scenario | Raw Score | Normalized | vs 0.45 |
|----------|-----------|-----------|---------|
| 1 primary only | 0.3 | 0.1579 | BELOW |
| 2 primaries only | 0.6 | 0.3158 | BELOW |
| **3 primaries only** | **0.9** | **0.4737** | **ABOVE** (margin: 0.0237) |
| 1 boosted only | 0.5 | 0.2632 | BELOW |
| 1 boosted + 1 primary | 0.8 | 0.4211 | BELOW |
| **1 boosted + 2 primaries** | **1.1** | **0.5789** | **ABOVE** |
| **2 boosted** | **1.0** | **0.5263** | **ABOVE** |

**Key property**: Requires either 3 distinct primary matches OR significant booster co-occurrence. This maintains strong noise filtering while being mathematically achievable.

---

## 4. Denominator Recalculation

**No change needed.** The denominator is calculated from `max_primary * primary_weight + max_boosted * boosted_weight`:

```
3 * 0.3 + 2 * 0.5 = 0.9 + 1.0 = 1.9
```

The weights (`primary_weight=0.3`, `boosted_weight=0.5`) and caps (`max_primary=3`, `max_boosted=2`) are not changing. Only the regex patterns and the threshold change. Denominator remains **1.9**.

---

## 5. Cross-Model Consensus Summary

### Gemini (gemini-3.1-pro-preview): Option C (Hybrid)
- Recommends threshold 0.47 + `cannot` demotion + booster expansion
- Key insight: booster-gating structure should be preserved but booster vocabulary must shift from "discovery narrative" to "structural/permanence" terms
- Argues threshold fix IS a bug fix warranting global default change
- Agrees `cannot` as booster still contributes when co-occurring with real constraint keywords

### Codex (o4-mini): Option B (with caveats)
- Recommends threshold 0.47 + `cannot` demotion + new constraint primaries
- Prefers B over C because "C mixes required fix with speculative tuning"
- Strongly recommends per-project first deployment
- Key insight: thresholds are per-project but keywords are code-global, creating an inherent tension
- Wants boundary tests at 0.4737 and 0.5

### Prior Analysis (from log-review-triage-analysis.md)
- Previous Codex assessment: "calibration bug, fix with quantum-aligned thresholds"
- Previous Gemini assessment: "expected behavior, do not change defaults"
- Synthesis: both partially correct -- structural problem exists, but keywords must be fixed alongside threshold

### Consensus Points (all models agree)
1. The threshold > max-no-booster gap is a real structural problem
2. `cannot` should be removed from primary (too noisy, RUNBOOK overlap)
3. Booster vocabulary needs expansion toward structural/permanence terms
4. Changes must be atomic (threshold + keywords in single PR)

### Disagreement Point
- **Scope**: Gemini says global (it's a bug fix), Codex says per-project first (validation gate not met)
- **Resolution**: See Section 7 below

---

## 6. Risk Assessment and Mitigations

### Risk 1: False Positive Increase
**Severity**: Medium
**Cause**: Lower threshold means weaker signals could trigger
**Mitigation**: At 0.45, you still need 3 distinct primary keyword matches on 3 separate lines. The new primaries (`does not support`, `limited to`, `hard limit`, etc.) are more specific than `cannot`, so false positive rate should actually *decrease* compared to a threshold-only change. The original analysis showed 23.9% false trigger rate from threshold-only change; with `cannot` removal, this should drop significantly.
**Monitoring**: Log replay of 71-event corpus after implementation to measure actual trigger rate and overlap.

### Risk 2: Tight Margin at 0.47 (mitigated by choosing 0.45)
**Severity**: Low (was Medium at 0.47)
**Cause**: Score quantum 0.4737 barely crosses threshold
**Mitigation**: Chose 0.45 instead of 0.47, providing 0.0237 margin (6x improvement). This survives minor weight adjustments.

### Risk 3: Cannot-as-Booster Unexpected Interactions
**Severity**: Low
**Cause**: `cannot` as booster would amplify any line containing a primary keyword + `cannot` within 4 lines
**Mitigation**: In genuine constraint conversations ("rate limited... cannot increase"), this is desired behavior. In debugging conversations ("error... cannot find"), primary keywords like `limitation` or `quota` are unlikely to co-occur, so the boost wouldn't apply. The overlap reduction is directionally correct.

### Risk 4: New Boosters Too Generic
**Severity**: Low
**Cause**: Terms like `provider` or `upstream` could appear in non-constraint contexts
**Mitigation**: Boosters only contribute when co-occurring with primary keywords within 4 lines. A line saying "upstream pipeline failed" (RUNBOOK territory) won't boost CONSTRAINT unless `limitation`, `quota`, etc. also appear nearby. The co-occurrence window is the safety mechanism.

### Risk 5: Insufficient Validation Data
**Severity**: Medium
**Cause**: Only 71 events from 1 project, 1 day
**Mitigation**: See scope decision below. The keyword changes are strictly improvements (more specific primaries, structural boosters). Threshold 0.45 is still the second-highest threshold in the system (after SESSION_SUMMARY at 0.6). Post-deployment monitoring with log replay.

---

## 7. Scope Decision: Global Default

**Decision**: Apply as **global default** change with the following framing.

### Justification

The change has two components with different characters:

1. **Threshold 0.5 -> 0.45**: This is a **bug fix**. A threshold that is mathematically unreachable without booster co-occurrence, combined with boosters that demonstrably never fire, constitutes a disabled category. This is not a tuning preference -- it is a structural defect. Bug fixes do not require the N>=300 validation gate.

2. **Keyword changes** (`cannot` demotion, primary additions, booster expansion): These are **improvements** accompanying the bug fix. They are applied globally because:
   - Keywords live in code (`memory_triage.py`), not in per-project config
   - A threshold fix without keyword cleanup produces 23.9% false positive rate (per analysis)
   - The keyword changes are directionally uncontroversial: removing the noisiest primary (`cannot`) and adding more specific terms
   - The changes are strictly additive/conservative: existing specific primaries are kept, `cannot` is preserved as booster (not deleted)

### Validation Plan

Despite being a global change, the following validation applies:

- **Immediate**: Replay 71-event corpus and verify:
  - CONSTRAINT trigger rate > 0% (was: 0%)
  - CONSTRAINT/RUNBOOK overlap rate < 58.8% (was: 58.8%)
  - No new false positive categories emerge
- **Short-term**: Monitor triage logs across projects for 2 weeks post-deployment
- **Medium-term**: If precision < 70% observed, add per-project threshold override or further tune keywords

### Per-Project Escape Hatch

Projects can always override the threshold via `memory-config.json`:
```json
{
  "triage": {
    "thresholds": {
      "constraint": 0.5
    }
  }
}
```
This restores the old behavior if the new threshold proves too sensitive for a particular project.

---

## 8. Files to Modify

| File | Change | Type |
|------|--------|------|
| `hooks/scripts/memory_triage.py` (L132-149) | Keyword changes (primary + booster patterns) | Code |
| `assets/memory-config.default.json` (L73) | `"constraint": 0.5` -> `"constraint": 0.45` | Config |
| `README.md` (L192, L285) | Update threshold documentation | Docs |
| `tests/test_memory_triage.py` | Add boundary regression tests at 0.4737, 0.45, 0.5 | Test |

---

## 9. Test Requirements

### Boundary Tests (new)
1. **3-primary-only crosses 0.45**: Text with 3 distinct constraint keywords (e.g., "quota", "rate limit", "restricted") on separate lines scores 0.4737 > 0.45
2. **2-primary-only does NOT cross 0.45**: Text with 2 constraint keywords scores 0.3158 < 0.45
3. **`cannot` alone does NOT score as primary**: Text containing only "cannot" should score 0.0 for CONSTRAINT primary
4. **`cannot` as booster works**: Text with "quota" (primary) + "cannot" within 4 lines should score 0.2632 (1 boosted)

### Overlap Tests (new)
5. **CONSTRAINT/RUNBOOK overlap reduced**: Text with "error" + "cannot" should NOT trigger CONSTRAINT (since `cannot` is now booster, not primary, and "error" is not a CONSTRAINT primary)

### Regression Tests (existing behavior preserved)
6. **Other categories unaffected**: DECISION, RUNBOOK, TECH_DEBT, PREFERENCE, SESSION_SUMMARY thresholds and keywords unchanged
7. **Booster window mechanics unchanged**: Co-occurrence window remains 4 lines

---

## 10. Implementation Checklist

- [ ] Update CONSTRAINT primary regex: remove `cannot`, add 5 ops-specific terms
- [ ] Update CONSTRAINT booster regex: add `cannot` + 7 structural terms
- [ ] Update threshold in `assets/memory-config.default.json`: 0.5 -> 0.45
- [ ] Update README.md threshold table (L192)
- [ ] Update README.md triage signal description (L285) if needed
- [ ] Add 7 boundary/overlap/regression tests
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Compile check: `python3 -m py_compile hooks/scripts/memory_triage.py`
- [ ] Replay 71-event corpus (manual verification)
