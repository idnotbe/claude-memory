# Verification Report: CONSTRAINT Threshold Fix (Round 2 -- Holistic & Cross-Model Consensus)

**Verdict: PASS_WITH_NOTES**

**Verifier**: Opus 4.6 (1M context)
**Date**: 2026-03-22
**Perspective**: Holistic goal achievement, systemic balance, documentation completeness, cross-model consensus

---

## 1. Goal Achievement Summary

The fix had 3 stated goals (from `action-plans/plan-fix-constraint-threshold.md`):

| # | Goal | Status | Evidence |
|---|------|--------|----------|
| 1 | CONSTRAINT can actually trigger (was: structurally impossible) | **ACHIEVED** | 3 primaries = `0.9/1.9 = 0.4737 > 0.45`. Test `test_three_primaries_crosses_threshold` confirms. Previously `0.4737 < 0.5` made pure-primary triggering impossible. |
| 2 | CONSTRAINT/RUNBOOK overlap reduced (was: 58.8%) | **ACHIEVED** | `cannot` demoted from primary to booster. Test `test_constraint_runbook_overlap_reduced` confirms `error + cannot` scores 0.0 for CONSTRAINT. No keyword overlap remains between CONSTRAINT primaries and RUNBOOK primaries. |
| 3 | Booster hit rate > 0% (was: 0%) | **ACHIEVED** | 8 new boosters added (`cannot`, `by design`, `upstream`, `provider`, `not configurable`, `managed plan`, `incompatible`, `deprecated`). Test `test_new_boosters_boost` confirms all 7 new boosters (excluding `cannot` which was moved, not new) amplify scores above baseline. The broader vocabulary makes booster hits statistically likely in real constraint-discovery conversations. |

All 3 goals are fully met.

---

## 2. Systemic Assessment

### 2.1 Structural Consistency Across Categories

Compared CONSTRAINT's pattern structure with all other text-based categories:

| Category | Primaries | Boosters | Weights (p/b) | Denom | Threshold | 3p-only score |
|----------|-----------|----------|---------------|-------|-----------|---------------|
| DECISION | 2 patterns (14 terms) | 1 pattern (7 terms) | 0.3/0.5 | 1.9 | 0.40 | 0.4737 |
| RUNBOOK | 1 pattern (7 terms) | 1 pattern (6 terms) | 0.2/0.6 | 1.8 | 0.40 | 0.3333 |
| **CONSTRAINT** | **1 pattern (11 terms)** | **1 pattern (14 terms)** | **0.3/0.5** | **1.9** | **0.45** | **0.4737** |
| TECH_DEBT | 1 pattern (7 terms) | 1 pattern (7 terms) | 0.3/0.5 | 1.9 | 0.40 | 0.4737 |
| PREFERENCE | 2 patterns (14 terms) | 1 pattern (6 terms) | 0.35/0.5 | 2.05 | 0.40 | 0.5122 |

**Observations:**
- CONSTRAINT now shares identical weights (0.3/0.5) and denominator (1.9) with DECISION and TECH_DEBT. Structurally consistent.
- CONSTRAINT has the richest booster vocabulary (14 terms) -- appropriate given that constraint contexts benefit from structural/permanence co-occurrence signals.
- The 3-primary-only score (0.4737) is identical for DECISION, CONSTRAINT, and TECH_DEBT, meaning 3 primaries alone trigger DECISION/TECH_DEBT (threshold 0.4) but barely triggers CONSTRAINT (threshold 0.45). This 0.05 gap is a deliberate precision guard.

### 2.2 Threshold Differential (0.45 vs 0.40) -- Appropriate?

**Yes, appropriate.** Gemini 3.1 Pro independently confirmed this in the cross-model review:

- If CONSTRAINT used 0.40 like others, then 1 boosted + 1 unboosted primary (score 0.4211) would trigger. Given that the new primaries include common phrases like `limited to` and `does not support`, a lower threshold would risk false positives in ordinary API discussion.
- The 0.45 threshold ensures minimum trigger paths are: 3 pure primaries, 2 boosted, or 2 primaries + 1 boosted. This is a reasonable precision floor for a category that captures enduring limitations.

### 2.3 Triage System Personality Impact

The fix does NOT change the triage system's overall personality:
- Other categories are completely unaffected (verified by `test_other_categories_unaffected`)
- The scoring algorithm (`score_text_category`) is unchanged
- The co-occurrence window (4 lines) is unchanged
- Code-fence stripping and inline-code stripping are unchanged
- The fix only modifies CONSTRAINT-specific data (patterns + threshold)

The net effect is that CONSTRAINT goes from "dead category" to "selective but functional category" -- a pure improvement with no systemic side effects.

---

## 3. Documentation Completeness

All documentation touchpoints verified:

| Document | Location | Status |
|----------|----------|--------|
| `README.md` line 192 | `constraint=0.45` | **CORRECT** |
| `README.md` line 285 | "Limitation keywords + structural/permanence co-occurrence" | **ACCEPTABLE** (see note below) |
| `commands/memory-config.md` line 36 | `constraint=0.45` | **CORRECT** |
| `assets/memory-config.default.json` line 73 | `"constraint": 0.45` | **CORRECT** |
| `SKILL.md` | Uses "constraint" as category name only, no keyword-level references | **N/A -- no update needed** |
| `CLAUDE.md` | No CONSTRAINT-specific references (references categories generically) | **N/A -- no update needed** |
| `action-plans/plan-fix-constraint-threshold.md` | Describes problem accurately, status=active | **ACCURATE** (status should be updated to "done" in Phase 6) |

**Documentation note (non-blocking):** README line 285 describes CONSTRAINT's triage signal as "Limitation keywords + structural/permanence co-occurrence". Post-fix, the booster set is broader than just "structural/permanence" -- it now includes operational terms like `provider`, `upstream`, `deprecated`, `by design`. A more accurate description might be "Limitation keywords + structural/operational co-occurrence". This is cosmetic and does not affect behavior.

**R1-math reported stale documentation in `commands/memory-config.md` line 36.** Upon verification, this file already shows `constraint=0.45` -- the issue was either pre-emptively fixed or was a false finding.

---

## 4. Cross-Model Final Consensus

### Gemini 3.1 Pro (via clink)

**Verdict: APPROVE**

Key findings:
1. **System balance**: "깨뜨리지 않으며 오히려 균형을 복원합니다" (Does not break balance; rather restores it). The old threshold created dead code; the fix restores normal operation.
2. **Threshold differential (0.45 vs 0.40)**: "매우 적절합니다" (Very appropriate). The 0.05 gap filters out the 1-boosted + 1-unboosted combination (0.4211) that would be a false-positive risk given the expanded primary vocabulary.
3. **Maintenance concern**: Flagged "Magic Number" risk -- the threshold 0.45 is coupled to the weight structure (0.3/0.5/1.9). If weights are later changed, the threshold could silently become unreachable again. Recommends long-term evolution to formula-based thresholds.
4. **Overall**: "수학적 모순 해결, 높은 Precision 유지, 완벽한 테스트 커버리지를 갖추었으므로 즉시 승인 및 병합 권장" (Resolves mathematical contradiction, maintains high precision, complete test coverage -- recommend immediate approval and merge).

### Synthesis with R1 Verification Results

| Aspect | R1-Math | R1-Ops | R2-Holistic | Gemini | Consensus |
|--------|---------|--------|-------------|--------|-----------|
| Math correctness | PASS | -- | PASS | PASS | **UNANIMOUS PASS** |
| Regex safety | PASS | PASS (ReDoS) | -- | PASS | **UNANIMOUS PASS** |
| Backwards compat | PASS | PASS | PASS | -- | **UNANIMOUS PASS** |
| Test coverage | PASS | PASS | PASS (97/97) | PASS | **UNANIMOUS PASS** |
| Documentation | NOTE (stale) | PASS | PASS (verified current) | -- | **PASS** |
| False-positive risk | -- | LOW | LOW | LOW | **ACCEPTABLE** |
| Threshold appropriateness | -- | PASS | PASS | PASS | **UNANIMOUS PASS** |
| Magic-number fragility | -- | -- | NOTED | FLAGGED | **FUTURE IMPROVEMENT** |

**Cross-model consensus: APPROVE with no blocking issues.**

---

## 5. Remaining Concerns and Follow-Up Items

### Non-Blocking (Future Improvements)

| # | Item | Severity | Source |
|---|------|----------|--------|
| 1 | **Magic-number coupling**: Threshold 0.45 is implicitly coupled to `3 * 0.3 / 1.9 = 0.4737`. Future weight changes could silently re-break the category. Consider formula-based threshold or a comment documenting the coupling. | LOW | Gemini, R2 |
| 2 | **README triage signal description**: Line 285 says "structural/permanence co-occurrence" but boosters now include operational terms (`provider`, `upstream`, `deprecated`). Minor wording refinement opportunity. | INFO | R2 |
| 3 | **Missing edge-case test**: No test for 1 boosted + 1 unboosted primary (0.4211 < 0.45). The quanta math is deterministic so this is not a risk, but would strengthen the regression suite. | INFO | R1-Math |
| 4 | **Plural form matching**: `\b` word boundaries mean `limitation` matches but `limitations` does not. Pre-existing behavior, not introduced by this fix. | INFO | R1-Math |

### Blocking Issues

**None.**

---

## 6. Overall Recommendation

### **MERGE**

The CONSTRAINT threshold fix achieves all 3 stated goals, follows established category patterns, maintains system balance, has complete documentation alignment, unanimous cross-model approval, and 97/97 tests passing. The implementation is mathematically sound, ReDoS-safe, backwards-compatible, and introduces no security regressions.

The fix transforms CONSTRAINT from a structurally dead category (0% trigger rate over 71 events) into a selective but functional category, while simultaneously reducing RUNBOOK overlap and improving prompt-injection resistance (by removing the overly generic `cannot` from primaries).

**No revisions required before merge.**
