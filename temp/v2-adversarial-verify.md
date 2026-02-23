# V2 Adversarial Attack Report

**Attacker:** v2-adversarial
**Date:** 2026-02-22
**Method:** Code trace analysis, external adversarial opinions (Codex 5.3, Gemini 3.1 Pro), vibe-check metacognitive calibration
**Source files verified:** `memory_retrieve.py` (577 lines), `memory_search_engine.py` (499 lines), `hooks.json` (57 lines), `test_memory_retrieve.py` (lines 493-590)
**Plans attacked:** `draft-plan-actions.md`, `draft-plan-logging-infra.md`, `draft-plan-poc.md`
**Prior reviews referenced:** `review-engineering.md`, `review-adversarial.md`, `v1-robustness-verify.md`

---

## Executive Summary

After 4 rounds of convergent review ("PASS WITH NOTES" consensus), I found **2 CRITICAL integration failures** that every previous reviewer missed, plus **3 HIGH-severity issues**. The critical failures are mathematical -- they create paradoxes where the system punishes its own best results and where PoC measurements are invalid by construction.

**The persistent blindspot across all 4 review rounds:** Every reviewer verified Plan #1's `confidence_label()` changes in isolation and Plan #2's logging schema in isolation, but **nobody traced the actual runtime data flow** through `score_with_body()` -> `apply_threshold()` -> `_output_results()` -> `confidence_label()`. The `body_bonus` mutation at line 257 contaminates every downstream component, and this was invisible to reviewers who checked function signatures without following data provenance.

---

## Top 5 Attack Findings

### FINDING 1: `body_bonus` Mutation Breaks Confidence Calibration (The Score Domain Paradox)

**Severity: CRITICAL**

**Assumption being attacked:** Plan #1 (Action #1) assumes `confidence_label()` operates on BM25 scores and proposes `abs_floor` calibrated to BM25 ranges ("recommended 1.0-2.0"). All reviewers verified the function signature and ratio math in isolation.

**Evidence AGAINST this assumption (code trace):**

The actual runtime data flow in the FTS5 path:

```
1. query_fts()           -> returns entries with raw BM25 scores (negative)
2. score_with_body():257 -> r["score"] = r["score"] - body_bonus  (MUTATES IN-PLACE)
                            r["raw_bm25"] = original score (PRESERVED BUT NEVER USED)
3. apply_threshold()     -> filters on MUTATED scores
4. _output_results():283 -> best_score = max(abs(MUTATED scores))
5. _output_results():299 -> confidence_label(MUTATED score, MUTATED best_score)
```

`confidence_label()` does NOT receive BM25 scores. It receives `BM25 - body_bonus`, a hybrid composite score. The `raw_bm25` field is computed and stored (line 256) but **never consumed by any downstream function**.

**Concrete failure scenarios:**

**Scenario A -- False Cluster Trap (body_bonus compresses ratios):**
```
Raw BM25 scores: [-1.0, -2.0, -3.0]  (spread apart, ratios: 0.33, 0.67, 1.0)
body_bonus = 3 for all three (all have body matches)
Mutated scores: [-4.0, -5.0, -6.0]   (compressed, ratios: 0.67, 0.83, 1.0)

All three have ratio > 0.67 (medium threshold 0.40, high threshold 0.75).
With slightly closer raw scores, all three easily exceed 0.90 ratio.
Cluster detection fires -> ALL demoted to "medium".
In tiered mode -> ALL get compact injection instead of full injection.
Result: The system punishes its 3 most relevant results for being too good.
```

**Scenario B -- abs_floor Evasion (body_bonus inflates weak matches):**
```
Raw BM25: -1.5 (weak match, should be caught by abs_floor=4.0)
body_bonus = 3 (stray body match on common word)
Mutated score: -4.5 (abs = 4.5 > abs_floor of 4.0)
Result: Weak match EVADES the quality gate entirely.
```

**Likelihood of failure:** CERTAIN in normal operation. `body_bonus` is applied to all top-K candidates (line 241). Any index with 3+ entries containing body matches for query terms will trigger this.

**External model consensus:**
- **Codex:** "Plan #1 calibrates confidence/tiering as if scores are BM25, but runtime labels use score after body bonus mutation. That can over-promote weak matches and corrupt both tiered output behavior and PoC #5 conclusions."
- **Gemini:** "Because `body_bonus` applies a flat subtraction to a negative BM25 score, it mathematically compresses the ratios of all top results towards 1.0. [...] The system punishes results for being too good."

**Fix:** Use `raw_bm25` (already preserved at line 256) instead of mutated `score` for confidence labeling:
```python
conf = confidence_label(entry.get("raw_bm25", entry.get("score", 0)), best_raw_bm25)
```

---

### FINDING 2: `max_inject=3` vs `cluster_count >= 3` Is a Design Tautology

**Severity: CRITICAL**

**Assumption being attacked:** Plan #1 states cluster detection triggers when "3 or more results have ratio > 0.90" and `cluster_count` is computed "on the result set after `max_inject` truncation" (Plan #1, line 80).

**Evidence AGAINST this assumption:**

`max_inject` defaults to 3 (verified at `memory_retrieve.py:343`). After truncation, the result set has AT MOST 3 entries. The cluster detection threshold is "3 or more results with ratio > 0.90."

This creates a logical tautology:
- If all 3 returned results have similar scores (ratio > 0.90 to best), cluster_count = 3 >= 3, cluster detection FIRES.
- It is **mathematically impossible** to return 3 "high" confidence results at the default `max_inject=3` when all 3 are equally relevant.

**Worked example:**
```
Query: "OAuth configuration"
Matches: 3 highly relevant memories about OAuth (setup, tokens, scopes)
BM25 scores after body_bonus: [-8.2, -8.0, -7.9]
Ratios: 1.0, 0.98, 0.96 -- ALL above 0.90
cluster_count = 3 >= 3 -> ALL capped to "medium"
In tiered mode -> ALL get compact injection

User receives 3 compact summaries instead of 3 full results for
a perfectly targeted query. This is the worst-case false demotion.
```

**The V1-robustness review (NEW-P1-1) partially identified this** but framed it as "cluster_count computed post-truncation may differ from full set" -- a documentation issue. It is not a documentation issue. It is a **logic error** that makes cluster detection fire on the majority of successful queries at `max_inject=3`.

**Likelihood of failure:** HIGH. Any query that returns 3 closely-scored relevant results (the happy path for a good search system) triggers this.

**Fix options:**
1. Change threshold to `cluster_count > max_inject` (only fire when similar results EXCEED the budget)
2. Compute `cluster_count` on the pre-truncation set (in `apply_threshold()` before slicing)
3. Use `cluster_count >= 4` as threshold (never fires at max_inject=3, activates only when max_inject is raised)

---

### FINDING 3: PoC #5 Measures a Composite Score but Claims "BM25 Precision"

**Severity: HIGH (Measurement Invalidity)**

**Assumption being attacked:** Plan #3 PoC #5 is titled "BM25 Precision Measurement" and frames its baseline as "current BM25 search quality" (Plan #3, lines 166-211). All reviewers accepted this framing.

**Evidence AGAINST this assumption:**

PoC #5 consumes `retrieval.search` log events containing `data.results[].score`. This score is the mutated `BM25 - body_bonus` value (Finding #1). The PoC will:

1. Label results as "relevant / not relevant" based on what was actually injected
2. Compute precision@3, precision@5 on the MUTATED score ranking
3. Report this as "BM25 precision"
4. Use the result to decide whether BM25 is "good enough" or needs replacement

**The measurement is invalid because:**
- A result ranked #1 by mutated score might be ranked #5 by raw BM25 (body_bonus promoted it)
- Precision of the composite score tells you nothing about BM25's quality in isolation
- The "before/after Action #1" comparison measures: `composite_precision_before` vs `composite_precision_after` -- but Action #1 only changes `confidence_label()`, which doesn't affect ranking. The precision numbers will be IDENTICAL before and after, making the PoC produce a null result.

**Likelihood of failure:** CERTAIN. The PoC will produce data that answers the wrong question.

**External model consensus:**
- **Codex:** "PoC #5 will report 'BM25 precision' on a composite score, producing invalid decisions."

**Fix:** Log BOTH `raw_bm25` and `final_score` (mutated). Compute precision on `raw_bm25` ranking for the "BM25 quality" question. Separately report composite precision for the "end-to-end quality" question. Clarify that Action #1 changes confidence LABELS, not ranking, so identical precision is the expected result (not a failure).

---

### FINDING 4: PoC #6 Correlation Path Is Dead on Arrival

**Severity: HIGH**

**Assumption being attacked:** Plan #3 PoC #6 measures nudge compliance by joining `retrieval.inject` events with `search.query` events on `session_id` (Plan #3, lines 282-284, 302-304).

**Evidence AGAINST this assumption:**

1. Plan #2 itself documents: "CLI mode has no hook_input, so session_id is unavailable" (Plan #2, line 124)
2. The `/memory:search` skill invokes `memory_search_engine.py` via CLI (verified: `memory_search_engine.py:425-499` has argparse CLI, no session_id parameter)
3. `search.query` events from CLI will have `session_id = ""` (empty string)
4. Therefore, the join `retrieval.inject.session_id == search.query.session_id` will NEVER match for CLI-initiated searches

**The cascade of failures:**
- Compact injection happens in auto-inject path (has session_id)
- User/Claude runs `/memory:search` via CLI skill (no session_id)
- Log join produces 0 matches
- PoC #6 reports 0% compliance rate
- This is a false negative -- the measurement infrastructure cannot observe the event it's trying to measure

**Prior reviews (adversarial Finding #13, engineering) called this "brittle" but accepted it.** It is not brittle -- it is structurally broken. The CLI search path has no mechanism to receive or propagate session_id.

**Likelihood of failure:** CERTAIN. The measurement will always report 0% unless the search skill is modified to propagate session_id.

**External model consensus:**
- **Codex:** "PoC #6 correlation path is effectively dead. Likely false negatives. Mark PoC #6 as instrumentation-blocked, not merely exploratory."

**Fix:** Add `--session-id` parameter to `memory_search_engine.py` CLI. Have the `/memory:search` skill pass the current session_id when invoking the CLI. Without this, PoC #6 should be marked **BLOCKED**, not "exploratory."

---

### FINDING 5: Logger Import Will Crash the Retrieval Hook (Fail-Open Violation)

**Severity: HIGH**

**Assumption being attacked:** Plan #2 specifies `memory_logger.py` as a new shared module imported by `memory_retrieve.py`. Plan #2 claims "fail-open: all errors are silently caught" (line 76).

**Evidence AGAINST this assumption:**

Current `memory_retrieve.py` imports are at module level (lines 25-37):
```python
from memory_search_engine import (
    BODY_FIELDS, CATEGORY_PRIORITY, HAS_FTS5, ...
)
```

This works because `memory_retrieve.py` has `sys.path.insert(0, str(Path(__file__).resolve().parent))` at line 23. But if `import memory_logger` is added as a top-level import:

1. **During plugin updates/partial installs:** If `memory_logger.py` doesn't exist yet (e.g., Plan #2 Phase 2 not deployed, or file deleted), `import memory_logger` raises `ModuleNotFoundError` at module load time.
2. **Module-level ImportError is NOT caught by any try/except** -- it happens before `main()` executes.
3. The hook process exits with a traceback. No memory retrieval occurs.
4. **This violates the fail-open principle** that the plan claims.

**The existing codebase has a precedent for this problem:** `memory_judge.py` is imported lazily (line 429: `from memory_judge import judge_candidates` inside `main()`), specifically because it's optional. But Plan #2 doesn't specify lazy import for `memory_logger`.

**Likelihood of failure:** MEDIUM. Occurs during partial deployments, plugin updates, or if the file is accidentally deleted.

**Fix:** Import `memory_logger` lazily with a try/except fallback to a no-op logger:
```python
try:
    from memory_logger import emit_event
except ImportError:
    def emit_event(*args, **kwargs): pass
```

---

## Blindspot Analysis: What Has Every Reviewer Missed?

### The Meta-Blindspot: Verification by Signature, Not by Data Flow

Every reviewer (engineering, adversarial, robustness, external models in prior rounds) verified:
- Function signatures are correct
- Config keys have safe defaults
- Line number references are accurate
- Security sanitization chains are intact
- Rollback paths exist

**Nobody traced the actual runtime value of `score` through the pipeline.** The `body_bonus` mutation at `memory_retrieve.py:257` is the single most consequential line in the entire retrieval system, and it was verified only as "ranking adjustment" -- not as "input to confidence calibration, cluster detection, abs_floor gating, logging schema, and PoC measurement."

This is a classic instance of **verification at the wrong abstraction level**. The function-level view says "confidence_label takes score and best_score, both are floats, the ratio math is correct." The data-flow view says "the floats being passed are NOT what the plan thinks they are."

### Why 4 Rounds of Consensus Failed

1. **Round 1 (engineering + adversarial):** Focused on function correctness, config safety, and security. Found real issues (atomic writes, privacy, cluster toggle). These were genuine and distracted from data-flow analysis.
2. **Round 2 (adversarial):** Escalated privacy and schema gaps. Found `matched_tokens` cross-plan gap. Still function-level analysis.
3. **V1-robustness:** Verified rollback completeness, edge cases, concurrency. NEW-P1-1 noticed `cluster_count` post-truncation issue but framed it as documentation, not logic error.
4. **V1-practical:** (Not in my review set but referenced.) Verified implementation feasibility.

Each round found real issues, which created a false sense of completeness. The consensus pressure ("PASS WITH NOTES") made each subsequent reviewer less likely to challenge the overall structure.

---

## Overall Risk Assessment

| Plan | Risk | Justification |
|------|------|---------------|
| Plan #1 (Actions) | **HIGH** | Finding #1 (score domain paradox) and Finding #2 (cluster tautology) are both CRITICAL and both affect Actions #1 and #2. Without fixing the score domain issue, the entire confidence calibration is operating on the wrong inputs. Without fixing the cluster threshold, the feature will false-fire on the majority of successful queries at default settings. |
| Plan #2 (Logging) | **MEDIUM** | Finding #5 (import crash) is HIGH but fixable with 3 LOC. The logging schema records mutated scores, which contaminates PoC measurements (Finding #3), but this is fixable by logging both `raw_bm25` and `score`. Core design (JSONL, fail-open, minimal config) is sound. |
| Plan #3 (PoC) | **HIGH** | Finding #3 (measurement invalidity) and Finding #4 (dead correlation path) mean 2 of 4 PoCs will produce meaningless data. PoC #5 measures the wrong thing. PoC #6 cannot observe the event it needs. These aren't methodology weaknesses -- they're structural impossibilities. |

---

## Summary of Required Changes

| # | Finding | Severity | Fix | Cost |
|---|---------|----------|-----|------|
| 1 | Score domain paradox | CRITICAL | Use `raw_bm25` for confidence_label, not mutated `score` | ~5 LOC |
| 2 | Cluster tautology at max_inject=3 | CRITICAL | Change threshold to `cluster_count > max_inject` or use pre-truncation count | ~3 LOC |
| 3 | PoC #5 measures composite, not BM25 | HIGH | Log both `raw_bm25` and `score`; compute precision on `raw_bm25` | ~10 LOC + plan text |
| 4 | PoC #6 correlation path dead | HIGH | Add `--session-id` to CLI; or mark PoC #6 as BLOCKED | ~15 LOC or plan text |
| 5 | Logger import crash | HIGH | Lazy import with no-op fallback | ~3 LOC |

**Total fix cost: ~36 LOC.** All fixes are surgical. None require architectural changes.

---

## What to Preserve

Despite the critical findings, the plans contain strong decisions that should NOT be changed:

1. **Config-based rollback for all heuristics** (`abs_floor`, `cluster_detection_enabled`, `output_mode`) -- excellent operational safety
2. **`logging.enabled: false` default** -- correct for a plugin; prevents uninvited file creation
3. **Fail-open semantics** throughout logging -- correct pattern for non-essential instrumentation
4. **PoC #4 time-box and kill criteria** -- well-structured, correctly isolated on separate branch
5. **Cross-plan implementation ordering** (Plan #3, lines 437-456) -- the sequencing is correct, the issue is Finding #3's measurement targets, not the ordering itself
6. **`raw_bm25` field already exists** (line 256) -- the data needed for Fix #1 is already computed and stored; it just needs to be consumed
