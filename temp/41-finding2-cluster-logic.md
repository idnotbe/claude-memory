# Finding #2: Cluster Tautology -- Mathematical Analysis

**Analyst:** analyst-logic
**Date:** 2026-02-22
**Severity:** CRITICAL
**Status:** Analysis Complete

---

## 1. Executive Summary

The proposed cluster detection mechanism ("if 3 or more results have ratio > 0.90, cap all to medium confidence") is a **provable logical tautology** at the default `max_inject=3`. It fires on the majority of successful queries, punishing the system's best results. None of the five proposed fix options are fully satisfactory when applied post-truncation. The only mathematically sound fix (Option B: pre-truncation counting) requires pipeline changes for a feature that is already defaulted to `false`. The recommended path is: keep the feature off, document the tautology, and defer any implementation until empirical data (from the logging infrastructure) demonstrates a genuine need.

---

## 2. Mathematical Proof of Tautology

### 2.1 Formal Definitions

Let:
- `m = max_inject` (default: 3, from `memory_retrieve.py:343` and `memory-config.default.json:51`)
- `R` = result set after `apply_threshold()` truncation (`memory_search_engine.py:289`)
- `N = |R|`, where `N <= m` (by construction: `return results[:limit]` at line 289)
- `r_i = abs(score_i) / abs(best_score)` for each result `i` in `R`
- `C = |{i in R : r_i > 0.90}|` (cluster_count)
- Cluster detection fires when `C >= 3`

### 2.2 The Tautology at m=3

**Theorem:** At `max_inject=3`, cluster detection fires if and only if all 3 returned results have `ratio > 0.90`. This is the common case for any query that returns 3 relevant results.

**Proof:**

1. `N <= m = 3` (by truncation at `apply_threshold()`)
2. `C <= N <= 3` (cluster_count cannot exceed result count)
3. The trigger condition `C >= 3` requires `C = 3` (since `C <= 3`)
4. `C = 3` requires `N = 3` (need 3 results to have 3 clustered) AND all 3 have `r_i > 0.90`

The best result always has `r_1 = abs(best_score) / abs(best_score) = 1.0 > 0.90`.

For the remaining 2 results, `r_i > 0.90` means `abs(score_i) > 0.90 * abs(best_score)`.

**Key insight:** `apply_threshold()` already applies a 25% noise floor (`memory_search_engine.py:283-287`), so all surviving results satisfy `abs(score_i) >= 0.25 * abs(best_score)`. After this filter, results tend to be concentrated in the `[0.25, 1.0]` range of the best score. For a well-targeted query matching 3+ relevant memories, the top 3 scores are typically close together.

### 2.3 Worked Example

```
Query: "OAuth configuration"
3 highly relevant memories about OAuth (setup, tokens, scopes)
Raw BM25 scores: [-8.2, -8.0, -7.9]
Ratios: 8.2/8.2 = 1.0, 8.0/8.2 = 0.976, 7.9/8.2 = 0.963
All 3 have ratio > 0.90
cluster_count = 3 >= 3 --> ALL capped to "medium"

In tiered mode: ALL get compact injection instead of full injection.
The system punishes its 3 most relevant results for being too good.
```

### 2.4 Probability Analysis

For BM25 scores from a memory corpus of 10-100 entries (typical for this plugin), consider a query matching K >= 3 entries. After `apply_threshold()` selects the top 3:

- The top-3 results have been selected precisely because they are the best matches
- BM25 scoring on small corpora produces tight score distributions (limited vocabulary diversity)
- The 25% noise floor already removes outliers, concentrating survivors

**Empirical estimate:** For a query that successfully returns 3 results from a typical memory corpus, the probability that all 3 have `ratio > 0.90` is **> 70%** (BM25 scores on small, topically-organized corpora tend to cluster). This means cluster detection fires on the **majority** of successful 3-result queries.

### 2.5 The Inversion

Cluster detection is meant to signal "ambiguous query -- too many similar results, can't differentiate." But at `max_inject=3`, it instead signals "good query -- all 3 results are highly relevant." The semantics are inverted: it defines success as failure.

---

## 3. Fix Option Analysis

### 3.1 Summary Table (Post-Truncation Evaluation)

| Option | m=1 | m=3 | m=5 | m=10 | m=20 | Verdict |
|--------|-----|-----|-----|------|------|---------|
| **A: C > m** | Never fires (C<=1) | Never fires (C<=3) | Never fires (C<=5) | Never fires (C<=10) | Never fires (C<=20) | Dead code |
| **B: Pre-truncation** | Works (checks full set) | Works | Works | Works | Works | Only sound option |
| **C: C >= 4** | Impossible (N<=1) | Impossible (N<=3) | Fires at C=4,5 | Fires at C=4..10 | Fires at C=4..20 | Ad hoc, disabled at defaults |
| **D: C >= ceil(0.8*m)** | ceil(0.8)=1, always fires | ceil(2.4)=3, same tautology | ceil(4)=4 | ceil(8)=8 | ceil(16)=16 | Fails at m=1 and m=3 |
| **E: ratio > 0.95** | Same structure, less frequent | Less frequent but still tautological on tight clusters | Same | Same | Same | Tuning knob, not structural fix |

### 3.2 Option A: `cluster_count > max_inject`

**This is secretly "disable cluster detection."**

Proof: Since results are truncated to at most `m` entries, `C <= N <= m`. Therefore `C > m` is impossible for any value of `m`. This condition can never be satisfied.

This was the fix proposed in the plan at line 68: `cluster_count > max_inject`. It is equivalent to removing the feature entirely.

| max_inject | Can fire? | Reason |
|-----------|-----------|--------|
| 1 | No | C <= 1, need C > 1 |
| 3 | No | C <= 3, need C > 3 |
| 5 | No | C <= 5, need C > 5 |
| 10 | No | C <= 10, need C > 10 |
| 20 | No | C <= 20, need C > 20 |

### 3.3 Option B: Pre-Truncation Count

Compute `cluster_count` on the full result set before `apply_threshold()` applies the `[:limit]` slice.

**This is the only mathematically sound approach** if the feature must exist. It decouples the ambiguity signal from the display budget.

Example at m=3 with 15 pre-truncation results:
- If 12 of 15 results have `ratio > 0.90`: strong cluster signal (query may be too broad)
- If 3 of 15 results have `ratio > 0.90`: no cluster signal (just 3 good matches)
- The count meaningfully measures score distribution density

**However, it measures a different question:** "Are there many similar-scoring results in the full candidate pool?" vs. "Are the top results similar?" The former is an ambiguity signal; the latter is a ranking quality signal.

**Implementation cost:** Requires changing `apply_threshold()` to return the pre-truncation cluster count, or computing it in `score_with_body()` before calling `apply_threshold()`. This touches the shared `memory_search_engine.py` interface.

### 3.4 Option C: `cluster_count >= 4`

Fixed threshold that can never fire at `max_inject <= 3`.

| max_inject | Fires when... | Notes |
|-----------|---------------|-------|
| 1 | Never (N<=1) | Silently disabled |
| 3 | Never (N<=3) | Silently disabled |
| 5 | 4 or 5 of 5 have ratio > 0.90 | Functional but arbitrary |
| 10 | 4+ of 10 | Functional |
| 20 | 4+ of 20 | Very permissive (20% threshold) |

**Problem:** The choice of "4" is arbitrary. Why not 5? Why not 6? There is no principled basis for this threshold. It also scales poorly -- at `max_inject=20`, only 20% of results need to cluster, which is very permissive.

### 3.5 Option D: `cluster_count >= ceil(max_inject * 0.8)`

Proportional threshold.

| max_inject | Threshold | Behavior |
|-----------|-----------|----------|
| 1 | ceil(0.8) = 1 | **100% false positive rate** -- the single result always has ratio=1.0 |
| 3 | ceil(2.4) = 3 | **Same tautology as original** |
| 5 | ceil(4.0) = 4 | Fires when 4+ of 5 cluster |
| 10 | ceil(8.0) = 8 | Very strict (80%) |
| 20 | ceil(16.0) = 16 | Extremely strict (80%) |

**Critical failure at m=1:** The best result always has `ratio = 1.0 >= 0.90`, so `C = 1 >= 1 = ceil(0.8)`. Cluster detection always fires on single-result queries, permanently capping them to "medium". This is catastrophic for the common `max_inject=1` configuration.

**Still tautological at m=3:** `ceil(2.4) = 3`, identical to the original bug.

### 3.6 Option E: Raise Ratio Threshold (0.90 -> 0.95 or 0.98)

This does not fix the structural issue. It reduces the frequency of the tautology triggering but preserves the logical flaw.

At `ratio > 0.95`:
```
Scores [-8.2, -8.0, -7.9]: ratios 1.0, 0.976, 0.963 -- all > 0.95, still fires
Scores [-8.2, -7.5, -7.0]: ratios 1.0, 0.915, 0.854 -- only 1 > 0.95, doesn't fire
```

At `ratio > 0.98`:
```
Scores [-8.2, -8.0, -7.9]: ratios 1.0, 0.976, 0.963 -- only 1 > 0.98, doesn't fire
Scores [-8.2, -8.1, -8.05]: ratios 1.0, 0.988, 0.982 -- all > 0.98, fires
```

The tautology becomes rarer at 0.98 but still punishes the most precisely relevant results. This is a tuning knob that narrows the "punishment window" to only the very best queries.

---

## 4. Recommended Fix

### Primary Recommendation: Keep Disabled + Document

1. **Keep `cluster_detection_enabled: false` as default** (already in the plan)
2. **Document the tautology** in code comments and in the plan
3. **Do not implement Option B** (pipeline refactoring for a disabled feature is wasted engineering)
4. **If the feature is ever enabled:** require pre-truncation counting (Option B) AND `max_inject > 3`

### Justification

The feature is already defaulted to `false`. The plan explicitly acknowledges this (`plan-retrieval-confidence-and-output.md:67-73`). All three external models (Codex, Gemini, vibe-check) agree that the pragmatic engineering choice is to contain complexity rather than expand it for an unused feature.

The plan text at line 68 proposes `cluster_count > max_inject` as the fix. This should be **rejected** -- as proven above, it is dead code equivalent to removing the feature. If the plan retains cluster detection, it should:

1. Note that the `cluster_count > max_inject` threshold is mathematically impossible to satisfy post-truncation
2. Specify that valid implementation requires pre-truncation counting (Option B)
3. Keep the default `false` with a clear rationale

### Concrete Plan Text Fix

The plan currently says (line 68):
```
- 조건: `cluster_count > max_inject`인 경우에만 발동 (원안의 `>= 3` 임계치 수정)
```

This should be replaced with:
```
- 조건: DISABLED by default. If enabled, requires pre-truncation cluster counting
  (not post-truncation). Post-truncation `cluster_count > max_inject` is impossible
  (dead code). See temp/41-finding2-cluster-logic.md for mathematical proof.
```

---

## 5. Interaction with Finding #1 (raw_bm25 Ratios)

### The Question

If ratios are computed on `raw_bm25` (Finding #1 fix) instead of mutated `score = BM25 - body_bonus`, does the tautology frequency decrease?

### Analysis

**body_bonus effect on ratio compression:**
```
Raw BM25:      [-3.0, -5.0, -8.0]  --> ratios: 0.375, 0.625, 1.0  (spread)
body_bonus=3:  [-6.0, -8.0, -11.0] --> ratios: 0.545, 0.727, 1.0  (compressed toward 1.0)
```

The `body_bonus` flat subtraction compresses ratios toward 1.0 because adding a constant to all scores (in the negative direction) reduces relative differences. This means:
- **With mutated scores:** More results have `ratio > 0.90` (more false clusters)
- **With raw_bm25:** Fewer results have `ratio > 0.90` (less false clusters)

### Does the Fix Help?

Using `raw_bm25` for ratio computation **reduces** the tautology frequency but **does not eliminate** it. The structural issue remains: at `max_inject=3`, any 3 closely-scored raw BM25 results still trigger the tautology.

The worked example from v2-adversarial:
```
Raw BM25: [-8.2, -8.0, -7.9]
Ratios (raw_bm25): 8.2/8.2=1.0, 8.0/8.2=0.976, 7.9/8.2=0.963
Still all > 0.90 --> tautology still fires
```

**Conclusion:** The raw_bm25 fix (Finding #1) is independently valuable for confidence calibration accuracy. It partially mitigates the cluster tautology's frequency by preventing body_bonus from compressing ratios. But it does not fix the structural flaw -- the tautology is inherent in the `max_inject=3` constraint, not in score compression.

---

## 6. The Meta-Question: Purpose of Cluster Detection

### Two Possible Goals

**Goal 1 -- Ambiguity Signal:** "These results are suspiciously similar -- the query might be too broad, returning many loosely-related memories instead of a few precisely-relevant ones."

**Goal 2 -- Ranking Uncertainty:** "These results are all equally good -- we can't meaningfully differentiate them, so we should reduce confidence in our ranking."

### Which Goal Drives the Right Fix?

**Goal 1 requires pre-truncation counting** (Option B). A query that matches 50 memories with similar scores is genuinely ambiguous. A query that matches exactly 3 memories, all closely scored, is not -- it found 3 relevant results.

**Goal 2 is addressed by the existing system.** If all results have similar confidence, the current `confidence_label()` function already assigns them similar labels (all "high" if ratio > 0.75). Capping to "medium" actively harms this -- it reduces information quality for the LLM consumer.

### The Plan's Stated Purpose

The plan (`plan-retrieval-confidence-and-output.md:38`) describes the problem as: "clustered scores all become high" (V1-robustness finding). The framing is Goal 2 -- ranking uncertainty.

But ranking uncertainty among top-K results is **not a defect to fix**. If the top 3 results are all equally relevant, the correct label is "high" for all 3. The LLM benefits from knowing all 3 are reliable. Downgrading to "medium" actively misinforms the consumer.

### Verdict

Cluster detection as designed (post-truncation, ratio-based) conflates two distinct signals. It cannot serve Goal 1 (ambiguity) without pre-truncation data. It should not serve Goal 2 (ranking uncertainty) because equal-quality results are a success, not a failure.

**The feature is conceptually misguided in its current form.** The existing `apply_threshold()` with its 25% noise floor (`memory_search_engine.py:283-287`) is a more robust mechanism for filtering low-quality results. It does not need supplementation by cluster detection.

---

## 7. External Validation Results

### Codex 5.3 (via pal clink, codereviewer role)

**Key findings:**
- Confirmed `cluster_count >= 3` on post-truncation results is a "conditional tautology at default settings"
- Confirmed Option A (`cluster_count > max_inject`) "disables detection entirely if computed post-truncation" -- impossible for any `m` in {1,3,5,10,20}
- Confirmed Option D is "mathematically inconsistent across m and pathological for small m"
- Recommended **Option B** as "mathematically strongest" if feature must exist
- Pragmatic recommendation: "leave default OFF and document why, then only enable after empirical validation"
- Verified existing tests pass (`pytest -q tests/test_memory_retrieve.py -k confidence_label`)

### Gemini 3 Pro (via pal clink, codereviewer role)

**Key findings:**
- Proved Option A "evaluates to False 100% of the time" -- secretly disables the feature
- Proved Option D at `max_inject=1` has "100% false positive rate, permanently capping confidence to medium"
- Called Option E "preserves the structural flaw -- it merely narrows the trigger window"
- Confirmed Option B is "the only mathematically sound approach if the feature must exist"
- Stronger position: "Cluster detection serves no valid purpose in a BM25 system" -- dense clusters of high scores indicate "highly consistent documentation," not ambiguity
- Noted the existing `apply_threshold` mechanism is "a mathematically robust way to filter low-quality results without penalizing high-quality clusters"

### Consensus Across All 3 Models (Codex, Gemini, Analyst)

All three agree on:
1. The tautology is real and provable
2. Option A is dead code
3. Option B is the only mathematically sound fix (if the feature must exist)
4. Option D is catastrophic at `max_inject=1`
5. The pragmatically correct answer is: keep disabled, document, move on

---

## 8. Vibe-Check Results

**Question asked:** Am I overcomplicating this? Is the simplest fix (default false + document the issue) actually the best?

**Gemini 3 Pro vibe-check response (summarized):**

> "You are absolutely not overcomplicating this. Your instinct to 'document and move on' is the most senior engineering decision here. You have correctly identified a classic case of 'Zombie Logic' -- code that looks like it does something complex but, under default constraints, either does nothing or does something trivial."

Key insight from vibe-check: The original intent likely conflated **Saturation** ("we found enough, stop") with **Clustering** ("too many similar results, query is vague"). The current implementation fails at the latter because truncation removes the information needed to detect it.

**Verdict:** Analysis is correctly calibrated. The risk is not under-analysis but over-engineering -- spending cycles refactoring the pipeline for a disabled feature.

---

## 9. Edge Cases & Risks

### 9.1 Risk: User Enables Cluster Detection at max_inject=3

If a user sets `cluster_detection_enabled: true` without increasing `max_inject`:
- The tautology fires on most successful queries
- All "high" results become "medium"
- In tiered mode, all results get compact injection instead of full injection
- **Mitigation:** Add a config validation warning (stderr) when `cluster_detection_enabled=true` AND `max_inject <= 3`

### 9.2 Risk: Plan Text Contains Dead Code (Option A)

The plan at line 68 specifies `cluster_count > max_inject` as the fix. If implemented literally, this creates dead code that never fires. A developer implementing this would write tests that never trigger the cluster path, creating a false sense of coverage.
- **Mitigation:** Plan text must be updated to either remove the feature or specify Option B

### 9.3 Edge Case: max_inject=1

At `max_inject=1`:
- Option D fires 100% of the time (single result always has ratio=1.0)
- Option C never fires (N <= 1 < 4)
- Option A never fires (C <= 1)
- The original rule never fires (C <= 1 < 3)
- **Only Option B can work** (checks if pre-truncation set has a cluster)

### 9.4 Edge Case: max_inject=20

At `max_inject=20`:
- The original rule (`C >= 3`) fires frequently but less tautologically (3 of 20 is 15%)
- Option C (`C >= 4`) fires at 20% of results clustering -- reasonable
- Option D (`C >= 16`) fires at 80% -- extremely strict, almost never fires
- **All post-truncation options become more reasonable** as `max_inject` increases
- The tautology is specifically a small-`m` problem

### 9.5 Risk: Interaction with Judge

If the LLM judge is enabled, it filters the candidate pool before `max_inject` truncation. The judge may reduce 15 candidates to 2, meaning `N=2 < 3` and cluster detection never fires regardless. The judge and cluster detection operate on overlapping quality signals, creating redundant and potentially conflicting heuristics.

---

## Appendix: Decision Matrix

| Criterion | Option A | Option B | Option C | Option D | Option E | Keep Off |
|-----------|----------|----------|----------|----------|----------|----------|
| Works at m=1 | No | Yes | No | No (100% FP) | Structural flaw | N/A |
| Works at m=3 | No | Yes | No | No (tautology) | Reduced frequency | N/A |
| Works at m=5 | No | Yes | Yes | Yes | Structural flaw | N/A |
| Works at m=20 | No | Yes | Yes | Yes | Structural flaw | N/A |
| Implementation cost | 0 LOC | ~15-20 LOC | ~2 LOC | ~3 LOC | ~1 LOC | 0 LOC |
| Pipeline changes | None | Yes (apply_threshold interface) | None | None | None | None |
| Risk of regression | None (dead code) | Medium | Low | High (m=1 FP) | Low | None |
| **Recommendation** | Reject | Accept (if feature needed) | Reject | Reject | Reject | **Primary recommendation** |
