# V2 Fresh Eyes Verification

**Date:** 2026-02-22
**Verifier:** v2-fresh (independent, no prior review files read)
**Method:** Read all 3 plans + briefing, verified claims against source code, consulted vibe-check + Codex + Gemini for external perspective

---

## Plan #1: Actions #1-#4 (draft-plan-actions.md)

### Fresh Impression
Well-structured plan with clear dependency ordering (#1 -> #2 -> #3, #4 independent on separate branch). Code references are accurate -- I verified `confidence_label()` at line 161-174, `_output_results()` at line 262-301, and all three hint locations (458, 495, 560) against the actual source. The config-based rollback strategy for each action is a smart design pattern. However, there is one significant design flaw in Action #1 that could cause widespread false demotion in practice.

### Clarity Score: 8/10
A developer can implement this without asking additional questions. Each action specifies exact file locations, function signatures, config keys, test impacts, and rollback strategies. The Korean + English hybrid is readable. Minor deduction: the relationship between `apply_threshold()` and `confidence_label()` is explained but could benefit from a concrete numerical example showing the interaction.

### Scope Assessment: RIGHT-SIZED (with one over-engineered element)
Actions #1-#3 are appropriately scoped for the identified problems. Action #4 (Agent Hook PoC) is correctly isolated on a separate branch. The total LOC estimate (~196-345) is credible for the described changes.

### Top Concerns

**1. CRITICAL: Cluster detection interacts destructively with max_inject=3 (default)**

This is the most serious issue across all three plans. The cluster detection fires when >= 3 results have ratio > 0.90. But `max_inject` defaults to 3 (`assets/memory-config.default.json:51`). After cap, you typically have exactly 3 results. If those 3 results are all genuinely relevant (common case -- e.g., "API rate limits" matching 3 real rate-limit memories), all 3 get ratio > 0.90, cluster detection fires, and all 3 get demoted to "medium".

Combined with Action #2's tiered output (MEDIUM = compact format), this means the system actively *punishes* high-quality retrieval by truncating the very results that should be fully injected. The plan acknowledges this risk (line 69) and adds a config toggle, but the default is `enabled: true`.

**External consensus:** Both Codex and Gemini flagged this as the highest-severity issue. Gemini recommends removing cluster detection entirely or decoupling it from max_inject (e.g., only trigger on > 5 results). Codex recommends computing on the pre-cap candidate set or raising the trigger threshold.

**Recommendation:** Either (a) default `cluster_detection_enabled: false`, or (b) compute cluster_count on the pre-threshold candidate set rather than the post-cap set, or (c) raise the threshold to >= 4 with percentage-based logic.

**2. HIGH: abs_floor is corpus-dependent with insufficient calibration guidance**

The plan acknowledges (line 64) that `abs_floor` is corpus-dependent and that BM25 scores are unnormalized. The suggested range "1.0-2.0" is arbitrary and will break as the memory corpus grows or shrinks. There is no defined calibration protocol -- only a vague reference to "PoC #5 empirical data" and future "percentile-based approach".

**External consensus:** Gemini recommends dropping abs_floor entirely and sticking to relative thresholds. Codex recommends defining a calibration protocol now (percentile-based from logged score distribution).

**Recommendation:** Either define a concrete calibration protocol or set `abs_floor: 0.0` (disabled) as default with explicit documentation that it requires empirical tuning before activation.

**3. MEDIUM: recall@k is undefined under top-k-only labeling (PoC #5 dependency)**

Plan #1's verification (Gate D) depends on PoC #5 metrics, but PoC #5 (Plan #3) proposes measuring `recall@k` with only top-k labeling. Recall requires knowing the total relevant set beyond top-k, which top-k-only labeling cannot provide. This is a methodology gap that Plan #1 inherits.

### Missing Items
- No concrete numerical example showing cluster detection + tiered output interaction in practice
- No definition of what "successful calibration" of abs_floor looks like

### Overall: NEEDS WORK
Specifically: cluster detection default should be `false` until the interaction with max_inject is resolved. Everything else is solid.

---

## Plan #2: Logging Infrastructure (draft-plan-logging-infra.md)

### Fresh Impression
Thorough and well-researched design. The `os.open(O_APPEND|O_CREAT|O_WRONLY|O_NOFOLLOW)` + `os.write(fd, line_bytes)` pattern for atomic append is correct and matches the existing `memory_triage.py` pattern. The schema design with `schema_version` field, event-type taxonomy, and fail-open semantics are all sound engineering decisions. The `logging.enabled: false` default is the right call (confirmed by engineering + adversarial review consensus). However, the plan is heavy for what it needs to deliver in v1.

### Clarity Score: 8/10
Very detailed -- perhaps overly so. A developer can follow this, but the sheer volume (400+ lines) may cause important details to be missed. The 6-phase progression is clear. The PoC dependency mapping table is excellent. Minor deduction: the `emit_event()` function signature shows both `memory_root` and `config` parameters -- unclear when the caller should provide config vs when it's auto-loaded.

### Scope Assessment: SLIGHTLY OVER-ENGINEERED
The core need is: "record search events so PoCs can analyze them." The plan delivers a 7-event-type taxonomy, 4-level filtering, automatic cleanup with `.last_cleanup` gating, migration of 3 existing log sources, and 150-250 LOC of dedicated tests. This is good engineering for a production logging system, but the PoCs only need `retrieval.search` and `retrieval.inject` events to get started.

### Top Concerns

**1. HIGH: Heavy infrastructure blocks PoC execution**

The plan requires ~80-120 LOC for `memory_logger.py`, ~65-105 LOC of modifications across 4 scripts, ~150-250 LOC of tests, plus 6 implementation phases. This creates a hard dependency for Plan #3's PoCs, especially PoC #5 which needs baseline data *before* Plan #1 changes are applied. The cross-plan ordering (Plan #3, Appendix) correctly identifies this coupling but the solution (interleaving Plan #2 phases with PoC execution) adds complexity.

**External consensus:** Both Codex and Gemini recommend a v0 minimal logger to unblock PoCs faster. Gemini suggests a 15-line `open(..., 'a')` approach (POSIX append is atomic for writes < 4KB).

**Recommendation:** Phase the implementation more aggressively. Ship a v0 with just `emit_event()` for `retrieval.search` and `retrieval.inject` -- no cleanup, no level filtering, no migration. This is ~30-40 LOC and unblocks all PoCs immediately.

**2. MEDIUM: session_id gap affects PoC #6 cross-event correlation**

The plan acknowledges (line 124) that CLI mode (`memory_search_engine.py --mode search`) has no `hook_input` and therefore no `session_id`. But PoC #6 (Plan #3) requires joining `retrieval.inject` events with `search.query` events by `session_id`. This means PoC #6's attribution analysis will have a systematic gap for CLI-initiated searches.

**External consensus:** Codex flagged this as a HIGH issue -- the correlation can fail or be noisy by design.

**Recommendation:** Add a `nudge_id` or `turn_id` propagation mechanism as a first-class requirement for PoC #6, not a "future consideration."

**3. LOW: matched_tokens field complexity underestimated**

The plan notes (line 305) that `matched_tokens` for PoC #7 requires ~10-15 LOC of title+tags token intersection. This estimate feels optimistic given that it needs to handle tokenization edge cases (stopwords, partial matches, prefix matching from FTS5 `*` operator) and integrate into the logging data flow. Likely 20-30 LOC with proper handling.

### Missing Items
- No explicit "v0 minimal" milestone -- the plan jumps straight to the full 6-phase implementation
- The `emit_event()` function takes `config: dict | None` as a parameter but it's unclear when this is passed vs auto-loaded -- potential for inconsistent usage across scripts

### Overall: APPROVE (with recommendation to phase more aggressively)
The design is sound. The concern is execution ordering, not design quality. A v0 milestone would resolve the PoC coupling issue.

---

## Plan #3: PoC Experiments (draft-plan-poc.md)

### Fresh Impression
Well-organized experimental plan with clear purpose-to-action mapping. The strongest elements: PoC #6's reclassification from "decision gate" to "exploratory data collection" shows genuine intellectual honesty about causal inference limitations. PoC #4's strict 1-day time-box with explicit kill criteria and failure path is exactly right. The cross-plan implementation order in the appendix is the most important section and correctly identifies the interleaving needed. The weakest element is the statistical methodology for PoC #5.

### Clarity Score: 7/10
A developer can follow the high-level structure, but would need to ask clarifying questions about PoC #5 specifically: What exactly does "verify methodology" mean for the pilot? At what point do you decide the pilot methodology is valid vs needs redesign? The rubric "would Claude give a better answer with this memory?" is subjective enough that test-retest reliability might be low.

### Scope Assessment: RIGHT-SIZED
Four PoCs, each with a clear question to answer and defined success/failure criteria (except PoC #6, which is correctly scoped as exploratory). The time-boxing on PoC #4 prevents scope creep. PoC #7 smartly reuses PoC #5 data.

### Top Concerns

**1. HIGH: PoC #5 pilot sample size is statistically insufficient for decision-making**

At n=30 and k=3, you have 90 binary relevance judgments. For a true precision of 80%, the 95% confidence interval is approximately +/-14% (Wilson interval). This means the measured precision could be anywhere from 66% to 94% -- far too wide to make architectural decisions. The plan says "pilot 25-30, then expand to 50+" but doesn't define what triggers the expansion vs abandonment.

**External consensus:** Both Codex (50-80 paired) and Gemini (50-100 stratified) recommend larger samples. Both agree 25-30 is pilot-only, not decision-quality.

**Recommendation:** Either (a) define the pilot as strictly methodology validation (not for metrics), with 50+ as the real measurement, or (b) be explicit that pilot precision numbers carry +/-14% uncertainty and cannot support fine-grained comparisons.

**2. HIGH: recall@k is not measurable with top-k-only labeling**

Plan #3 proposes measuring `recall@k` (line 204, 429) but the labeling methodology only labels the top-k results. Recall = relevant_in_top_k / total_relevant. Without labeling the full result set (or at least a deeper pool), `total_relevant` is unknown. The plan does not acknowledge this limitation.

**External consensus:** Codex flagged this -- "drop recall in pilot, or build a deeper judged pool."

**Recommendation:** Either drop recall@k from the pilot metrics, or label the top-15 results (not just top-3/5) to estimate total_relevant.

**3. MEDIUM: Tight Plan #2 coupling creates schedule fragility**

The cross-plan ordering requires Plan #2 Phase 1-2 to complete before PoC #5 Phase A can start baseline measurement. If logging infrastructure is delayed, the entire PoC timeline shifts. The plan acknowledges this (line 342: "Plan #2 logging delay") and notes PoC #4 and #5 pilot can run manually, but this workaround undermines the point of building the logging infrastructure.

### Missing Items
- No explicit "pilot verification criteria" -- what would cause the PoC #5 methodology to be deemed invalid?
- recall@k measurement limitation not acknowledged
- No fallback if test-retest reliability is low (what if the labeling rubric doesn't produce consistent results?)

### Overall: APPROVE (with caveats on PoC #5 methodology)
The experimental design is sound in structure. The statistical methodology needs tightening: acknowledge the confidence interval width at n=30, drop recall@k or expand labeling depth, and define explicit pilot verification criteria.

---

## Cross-Plan Assessment

### Logical Gaps / Circular Dependencies
1. **Plan #1 Gate D depends on PoC #5 data, but PoC #5 depends on Plan #2 logging** -- This is acknowledged and the cross-plan ordering handles it, but it creates a 3-plan dependency chain that is fragile.
2. **Plan #1 cluster detection interacts with Plan #1 tiered output** -- When cluster detection demotes to "medium" AND tiered output shows "medium" as compact, the combined effect is stronger than either alone. This interaction is not explicitly analyzed.
3. No circular dependencies found.

### Are Estimates Believable?
- Plan #1 LOC estimates (~66-105 code, ~130-240 tests): **Credible.** The code changes are well-scoped and the test counts align with the described scenarios.
- Plan #2 LOC estimates (~80-120 new, ~65-105 modifications, ~150-250 tests): **Slightly optimistic** on the logger module. A production-quality logger with cleanup, level filtering, and fail-open semantics in 80-120 LOC is tight. 120-150 LOC is more realistic.
- Plan #3 has no LOC estimates (appropriate for experimental plans).

### What Would a First-Time Reader Notice?

1. **All plans are in Korean** -- This matches the user's preference per the briefing, but could be a barrier for contributors who don't read Korean. The code itself (function names, comments) remains in English, so the disconnect is manageable.

2. **The ratio of infrastructure to functional change is high** -- Plans #2 and #3 combined are ~1000+ LOC of logging + experiments to support ~66-105 LOC of actual feature changes in Plan #1. This is defensible (measurement-driven development) but a first-time reader might wonder if the same improvements could be made with less ceremony.

3. **README docs-to-code inconsistency** -- Codex discovered that README states `max_inject=5` while the actual default config has `max_inject=3`. This could lead to PoC baselines calibrated against wrong assumptions. Should be fixed before any PoC execution.

---

## Summary Verdicts

| Plan | Clarity | Scope | Overall |
|------|---------|-------|---------|
| #1 Actions | 8/10 | Right-sized | **NEEDS WORK** -- cluster detection default must be `false` |
| #2 Logging | 8/10 | Slightly over-engineered | **APPROVE** -- add v0 milestone for faster PoC unblocking |
| #3 PoC | 7/10 | Right-sized | **APPROVE** -- tighten PoC #5 methodology (sample size, recall@k) |

### Top 3 Issues Across All Plans (Priority Order)

1. **Cluster detection + max_inject=3 interaction** (Plan #1) -- Default-on cluster detection will false-demote in the common case of 3 genuinely relevant results. Combined with tiered output, this is actively harmful. Fix: default to disabled.

2. **PoC #5 statistical methodology** (Plan #3) -- n=30 gives +/-14% CI at 80% precision; recall@k is unmeasurable with top-k-only labeling. Fix: define pilot as methodology-only, expand to 50+ for metrics, drop or redefine recall@k.

3. **Logging infra blocking PoCs** (Plan #2 x Plan #3) -- Full 6-phase logging implementation creates schedule fragility for PoC execution. Fix: add a v0 minimal milestone (~30-40 LOC) that ships `retrieval.search` + `retrieval.inject` events only.

### Additional Issue (from Codex)

4. **README vs code baseline inconsistency** -- README says `max_inject=5` while `assets/memory-config.default.json` says `max_inject: 3`. PoC baselines must use the actual code defaults. Fix before PoC execution.
