# V2-Fresh-Eyes Review: plan-poc-retrieval-experiments.md

**Reviewer perspective:** First-time reader, developer assigned to execute 4 PoC experiments.
**Date:** 2026-02-22
**Verdict:** APPROVE WITH NOTES

---

## Overall Ratings

| Dimension | Score | Notes |
|-----------|-------|-------|
| **Clarity** | 8/10 | Each PoC's purpose is immediately clear. Blockquotes occasionally interrupt flow but are individually understandable. |
| **Completeness** | 7/10 | Executable for PoC #4, #5, #7. PoC #6 has known gaps (acknowledged in the plan). Some implicit knowledge assumed. |
| **Structure** | 9/10 | Excellent table-driven layout. Cross-Plan sequence in appendix is a standout. Progress checklists are actionable. |
| **Korean quality** | 9/10 | Natural, professional technical Korean. English terms used appropriately. No awkward translations. |

---

## 1. Can I understand what to do?

### PoC #4: Agent Hook Experiment
**Verdict: YES -- clear and self-contained.**

The experiment design diagram (baseline vs. Experiment A vs. Experiment B) is immediately understandable. Kill criteria (p95 > 5s, injection impossible, 1-day timebox) are concrete. The explicit failure path section added from review feedback is excellent -- I know exactly what to do when the experiment fails.

One minor gap: the plan says "20 controlled prompts" for latency measurement but does not specify what these prompts should be or how to construct them. A first-time executor might wonder: should they be diverse, representative, or stress-testing edge cases?

### PoC #5: BM25 Precision Measurement
**Verdict: YES with caveats.**

The two-phase approach (pilot 25-30 then expand to 50+) is well-structured. The labeling rubric ("Would seeing this memory help Claude give a better answer?") is clear. The 5 query types with examples are helpful.

However, the section is dense due to multiple interleaved blockquotes. A first-time reader has to mentally separate three layers: (1) original experiment design, (2) Deep Analysis findings, and (3) V2-adversarial resolution. The final methodology (what I *actually* do) requires synthesizing information scattered across these layers.

**Specific confusion:** The plan says both "precision@k" and "label_precision" are measurement targets. The relationship is explained in the Deep Analysis blockquote, but a developer might not realize that Action #1 pre/post comparison should use label_precision (not precision@k, which stays the same). The explanation is there but buried.

### PoC #7: OR-query Precision
**Verdict: YES -- the clearest PoC section.**

Metric definitions (`polluted_query_rate`, `single_token_fp_rate`) are unambiguous with formulas. The token matching extraction method is concrete with a code example. Decision thresholds (>30%, >50%) are pre-defined. The dependency on PoC #5 data is explicit.

### PoC #6: Nudge Compliance Rate
**Verdict: PARTIAL -- acknowledged gaps remain.**

The plan is honest about limitations (reclassified to exploratory data collection, no decision thresholds). A first-time reader can understand the methodology, but the implementation path is less clear because:
1. It requires Action #2 (tiered output) which does not exist yet
2. The `--session-id` CLI parameter needs to be implemented first
3. The correlation methodology is explicitly labeled as unreliable

This is more of a specification than an executable plan, which is appropriate given its dependencies.

---

## 2. Are the blockquotes confusing?

**Overall: Acceptable but with friction.**

| Blockquote | Location | Positioned correctly? | Understandable without Deep Analysis? |
|-----------|----------|----------------------|---------------------------------------|
| Import Crash (Finding #5) | After dependency mapping table | YES -- annotates Plan #2 dependency | YES -- code example is self-explanatory |
| Cluster Tautology (Finding #2) | After PoC #5 purpose | YES -- explains why Action #1 comparison only measures abs_floor | MOSTLY -- the mathematical proof is asserted, not shown. You have to trust it. |
| NEW-1 noise floor | After PoC #5 problem #2 | YES -- extends the noise floor discussion | YES -- the numeric example makes it clear |
| Score Domain + Finding #1 REJECTED | After PoC #5 problems | PARTIALLY -- this is the longest blockquote and covers multiple topics | MOSTLY -- the ranking-label inversion example is clear, but the connection to "what do I actually measure?" requires careful reading |
| Dead Correlation Path | Before PoC #6 purpose | YES -- critical blocker information | YES -- the fix is concrete (~12 LOC) |

**Main issue with blockquotes:** The PoC #5 section has three blockquotes interspersed with the original content, making it the densest section. A fresh reader might benefit from a short summary paragraph after all blockquotes that says "Given all the above, here is what PoC #5 actually measures and how."

---

## 3. Technical clarity

### Code examples: MOSTLY CLEAR

- The `confidence_label()` code snippet (lines 161-174 reference) is accurate -- I verified it matches the actual source.
- The `build_fts_query()` OR join (line 226 reference) is accurate.
- The `apply_threshold()` noise floor (lines 283-288 reference) is accurate.
- The token matching extraction pseudocode for PoC #7 is clear and implementable.
- The `e.name` scoping pattern for ImportError is well-explained with the code example.

### Line number references: ONE INACCURACY FOUND

| Plan reference | Actual location | Severity |
|---------------|----------------|----------|
| `hooks/hooks.json` lines 43-55 | Actually lines 54-66 (UserPromptSubmit) | LOW -- minor off-by-one in reference, the text description is unambiguous |
| `memory_retrieve.py` lines 161-174 | Correct (verified) | -- |
| `memory_retrieve.py` lines 262-301 | Correct (verified) | -- |
| `memory_retrieve.py` lines 458, 495, 560 | 458 and 560 confirmed; 495 confirmed | -- |
| `memory_search_engine.py` lines 205-226 | Correct (verified) | -- |
| `memory_search_engine.py` lines 283-288 | Correct (verified) | -- |
| `memory_retrieve.py` lines 283, 299 | Correct -- confidence_label calls | -- |
| `memory_retrieve.py:429, 503` in Import Crash note | These lines exist in the file | LOW -- should verify exact judge import locations |

### Formulas: WELL-DEFINED

- `precision@k = count(relevant in top-k) / k` -- standard and clear
- `label_precision_high = count(labeled "high" AND relevant) / count(labeled "high")` -- explicitly defined
- `polluted_query_rate` and `single_token_fp_rate` -- explicitly defined with formulas
- `nudge_compliance_rate` -- explicitly defined as ratio

### Missing technical detail

The `recall@k` metric is mentioned in the progress checklist (line 475) and metrics table (line 513) but the plan never defines how "total relevant" is determined. For precision, you only need to label the returned results. For recall, you need to know the *complete* set of relevant memories for each query -- which requires labeling the entire memory corpus for each query. This is a significant methodological gap that is never addressed.

---

## 4. Is the Korean clear?

**Overall: Excellent.**

- Technical Korean is natural and professional throughout.
- English technical terms are used appropriately: "precision@k", "recall@k", "body_bonus", "confidence_label", "fail-open", "time-box", "kill criteria" are all kept in English, which is standard practice.
- Korean sentence structure is clear and concise. The plan avoids unnecessarily long sentences.
- The mixed Korean/English style is consistent throughout -- there is no jarring switch between languages.
- Domain-specific terms like "귀인 윈도우 (Attribution Window)", "반사실 분석 (Counterfactual Analysis)" provide both Korean and English, which is helpful.

Minor note: "검증 소스: Codex 5.3 (planner), Gemini 3 Pro (planner), Vibe-check" at the top uses "검증 소스" which could be read as "verification source." A first-time reader might not immediately understand these are external AI models consulted during planning. This only becomes clear in the "외부 모델 합의" section much later.

---

## 5. Structure and navigation

**Overall: Very well organized.**

Strengths:
- The table-driven format (dependency mapping, risk matrix, metric summary, consensus table) makes scanning efficient.
- The Progress checklists at the end map directly to the methodology sections -- easy to track.
- The Cross-Plan implementation sequence appendix (lines 521-540) is a standout -- it resolves ordering ambiguity across three plans.
- Each PoC section follows a consistent structure: purpose, core problem (with code), logging dependencies, methodology, decision thresholds.

Cross-references:
- References to "Plan #1", "Plan #2" are frequent but never fully specified (file paths not given). A first-time executor would need to find these files independently.
- References to "Action #1", "Action #2", "Action #4" assume familiarity with Plan #1's action numbering. The plan does provide brief inline descriptions (e.g., "Action #1 (절대 하한선)") which partially mitigate this.
- The reference to `temp/agent-hook-verification.md` is a file path, which is helpful.

One structural issue: PoC #7 is placed between #5 and #6 in the detailed design section (matching execution order), but the numbering (#4, #5, #7, #6) could momentarily confuse a reader who expects sequential numbering. The plan justifies this order in the "실행 순서 및 근거" section, but a brief note at the start of the detailed design section ("Note: PoCs are presented in execution order, not numerical order") would help.

---

## 6. Potential confusion points

### HIGH severity

1. **recall@k methodology gap.** The plan lists `recall@k` as a metric for PoC #5 (in the metrics table, in the progress checklist, and in Phase A step 4) but never explains how the denominator (total number of relevant memories per query) is determined. For a memory corpus of potentially hundreds of entries, labeling ALL entries for each of 50+ queries is impractical. Without addressing this, an executor will either skip recall@k or invent their own methodology, leading to unreliable data. This was flagged in prior reviews (line 548: "recall@k limitation") but the plan body does not address it.

2. **PoC #5: What metric to use for Action #1 comparison is unclear without careful reading.** The plan says (a) precision@k is the baseline metric and (b) label_precision is the Action #1 comparison metric, and (c) precision@k will be the same before and after Action #1. This three-part relationship is distributed across the main text and a blockquote. An executor might run the Action #1 comparison, see identical precision@k numbers, and conclude Action #1 had no effect -- which is actually the expected result. The plan should state this more prominently, perhaps with a callout box or bold text outside the blockquote.

### MEDIUM severity

3. **`hooks.json` line reference is wrong.** The plan says lines 43-55 for UserPromptSubmit, but the actual lines are 54-66. This is a minor navigation inconvenience but could cause momentary confusion.

4. **"검증 소스" at the top is not self-explanatory.** The document header lists "Codex 5.3 (planner), Gemini 3 Pro (planner), Vibe-check" as "검증 소스" but never explains what these are until the "외부 모델 합의" section 400+ lines later. A one-line explanation near the top would help.

5. **PoC #5 Phase B lacks success criteria.** Phase A has implicit criteria (calculate precision, validate methodology). Phase B says "paired evaluation" and "stratum analysis" but does not define what constitutes a "successful" outcome. What precision@3 level would be considered acceptable? What label_precision improvement from Action #1 would justify the change? The plan pre-defines thresholds for #4 and #7 but not for #5.

6. **PoC #4 experiment prompts not specified.** The plan says "20 controlled prompts" but does not define them or provide selection criteria. Should they cover all 5 query types from PoC #5? Should they include edge cases? Should they be the same for command vs. agent hook comparison?

### LOW severity

7. **`memory_retrieve.py:429, 503` reference in Import Crash blockquote.** These are described as "Judge import" locations. A fresh reader would need to open the file to verify these are the correct import points. The plan could have included the relevant code snippets.

8. **Non-sequential PoC numbering in detailed design.** The PoCs appear as #4, #5, #7, #6 -- matching execution order but breaking numerical order. While justified, a brief note explaining the ordering would prevent momentary confusion.

9. **"Deep Analysis 반영" blockquote in the dependency mapping table area.** This blockquote (lines 73-83) is about Plan #2 implementation details (fail-open import pattern). While relevant, it might better belong in Plan #2 itself rather than in Plan #3. Its placement here makes the reader responsible for tracking a Plan #2 implementation detail while trying to understand Plan #3's dependency structure.

10. **Inconsistent use of "Action #1" descriptions.** In the PoC #5 purpose line, Action #1 is described as "(절대 하한선; 클러스터 감지는 Finding #2에서 dead code로 확인됨)". Later it is just "Action #1" or "Action #1 (abs_floor)". While none of these are wrong, a consistent short-form would reduce cognitive load.

---

## Summary

This is a well-structured, thorough experimental plan. The core methodologies for PoCs #4, #5, and #7 are clear and executable. PoC #6 is honestly positioned as a future-dependent exploratory effort. The biggest gaps are:

1. The undefined recall@k methodology (HIGH -- likely impractical as specified)
2. The precision@k vs. label_precision distinction for Action #1 evaluation being buried in a blockquote rather than prominently stated (HIGH -- risk of misinterpretation)
3. Missing success criteria for PoC #5 Phase B (MEDIUM)

The blockquotes from Deep Analysis add valuable context but create reading friction, particularly in the PoC #5 section where three consecutive blockquotes fragment the narrative. Consider adding a synthesis paragraph after the blockquotes that summarizes "what we actually do, given all the above."

The Korean is professional and natural. The plan would be immediately usable by a Korean-speaking developer familiar with IR metrics and BM25.
