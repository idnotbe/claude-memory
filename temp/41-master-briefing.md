# V2-Adversarial Deep Analysis -- Master Briefing

**Date:** 2026-02-22
**Source:** `temp/v2-adversarial-verify.md`
**Goal:** Deeply analyze 5 findings, propose thoroughly vetted solutions, update plan files.

---

## Overview

The V2-adversarial review found **2 CRITICAL** and **3 HIGH** issues that 4 prior review rounds missed. The core blindspot: every reviewer verified function signatures in isolation but **nobody traced the actual runtime data flow** through the pipeline. The `body_bonus` mutation at `memory_retrieve.py:257` is the epicenter.

---

## Finding #1: Score Domain Paradox (CRITICAL)

**Summary:** `confidence_label()` receives `BM25 - body_bonus` (mutated composite score), NOT raw BM25 scores. Plan #1 calibrates `abs_floor` to BM25 ranges, but the function operates on a different score domain.

**Code trace (memory_retrieve.py):**
```
1. query_fts()           -> returns entries with raw BM25 scores (negative)
2. score_with_body():257 -> r["score"] = r["score"] - body_bonus  (MUTATES IN-PLACE)
                            r["raw_bm25"] = original score (line 256, PRESERVED BUT NEVER CONSUMED)
3. apply_threshold()     -> filters on MUTATED scores (memory_search_engine.py:261-289)
4. _output_results():283 -> best_score = max(abs(MUTATED scores))
5. _output_results():299 -> confidence_label(MUTATED score, MUTATED best_score)
```

**Key code locations:**
- `memory_retrieve.py:256` -- `r["raw_bm25"] = r["score"]` (raw preserved but unused)
- `memory_retrieve.py:257` -- `r["score"] = r["score"] - r.get("body_bonus", 0)` (in-place mutation)
- `memory_retrieve.py:283` -- `best_score = max(abs(entry.get("score", 0)) for entry in top)` (uses mutated)
- `memory_retrieve.py:299` -- `conf = confidence_label(entry.get("score", 0), best_score)` (uses mutated)

**Failure scenarios:**
- body_bonus compresses score ratios toward 1.0 -> false cluster triggers
- body_bonus inflates weak BM25 matches past abs_floor -> quality gate evasion

**Preliminary fix from v2-adversarial:**
Use `raw_bm25` instead of mutated `score` for confidence labeling:
```python
conf = confidence_label(entry.get("raw_bm25", entry.get("score", 0)), best_raw_bm25)
```

**Analysis directions for analyst-score:**
1. Trace EVERY consumer of `score` vs `raw_bm25` through the full pipeline -- who else uses mutated `score`?
2. Should `apply_threshold()` also use `raw_bm25`? Or is the composite score correct for ranking?
3. What's the impact on the legacy path (lines 462-577) which doesn't have body_bonus?
4. How should `best_score` be computed -- from `raw_bm25` or mutated `score`?
5. Edge case: what happens when `raw_bm25` is absent (legacy fallback entries)?

---

## Finding #2: Cluster Tautology (CRITICAL)

**Summary:** `max_inject` defaults to 3. After truncation, result set has AT MOST 3 entries. Cluster detection threshold of "3 or more with ratio > 0.90" is a logical tautology -- it fires on the majority of successful queries.

**Code reference:**
- `memory_retrieve.py:343` -- `max_inject` default is 3 (via config)
- `memory_search_engine.py:270` -- `MAX_AUTO = 3` in apply_threshold()
- Plan #1 line 68 -- proposes `cluster_count > max_inject` fix

**Worked example:**
```
Query: "OAuth configuration"
3 highly relevant memories -> scores [-8.2, -8.0, -7.9]
Ratios: 1.0, 0.98, 0.96 -- ALL above 0.90
cluster_count = 3 >= 3 -> ALL capped to "medium"
```

**Fix options from v2-adversarial:**
1. `cluster_count > max_inject` (only fire when similar results EXCEED budget)
2. Compute `cluster_count` on pre-truncation set (in apply_threshold before slicing)
3. `cluster_count >= 4` (never fires at max_inject=3)

**Analysis directions for analyst-logic:**
1. Formalize the counting logic mathematically -- prove the tautology with concrete examples
2. Validate fix option 1 (`> max_inject`) at edge cases: max_inject=1, 3, 5, 20
3. What happens with fix option 2 (pre-truncation count)? Does pre-truncation cluster_count of 10 when max_inject=3 actually indicate "ambiguous" results or just "many relevant"?
4. Is ratio 0.90 the right threshold? Body_bonus compression (Finding #1) affects this.
5. Interaction with `raw_bm25` fix: if ratios are computed on raw_bm25, does the tautology still occur?

---

## Finding #3: PoC #5 Measurement Invalidity (HIGH)

**Summary:** PoC #5 claims to measure "BM25 precision" but will measure precision of the composite `BM25 - body_bonus` score. The before/after Action #1 comparison will produce IDENTICAL precision (since Action #1 changes labels, not ranking).

**Code reference:**
- `memory_retrieve.py:256-257` -- raw_bm25 vs mutated score
- Plan #3 lines 166-211 -- PoC #5 methodology
- Plan #2 line 112 -- log schema `results[].score` field

**Key insight:** A result ranked #1 by mutated score might be ranked #5 by raw BM25 (body_bonus promoted it). Precision of composite score ≠ precision of BM25.

**Preliminary fix:** Log BOTH `raw_bm25` and `score`. Compute precision on `raw_bm25` for BM25 quality question. Clarify that Action #1 changes LABELS not ranking.

**Analysis directions for analyst-score:**
1. Trace which fields the PoC #5 analysis scripts would consume from the log
2. What's the right way to frame the "before/after" comparison? (label quality, not ranking quality)
3. Should the logging schema include `body_bonus` as a separate field for debugging?
4. How should the PoC #5 plan text be amended to reflect the dual-score measurement?

---

## Finding #4: PoC #6 Dead Correlation Path (HIGH)

**Summary:** PoC #6 joins `retrieval.inject` and `search.query` events on `session_id`. But CLI mode (`memory_search_engine.py`) has no hook_input, so session_id is always empty string. The join produces 0 matches.

**Code reference:**
- `memory_search_engine.py:425-499` -- CLI argparse, no --session-id parameter
- `skills/memory-search/SKILL.md:37` -- CLI invocation has no session_id
- Plan #2 line 124 -- documents CLI session_id limitation
- Plan #3 lines 282-284, 302-304 -- PoC #6 correlation method

**The cascade:**
1. Compact injection happens in auto-inject path (has session_id from hook_input)
2. User runs `/memory:search` via CLI skill (no session_id)
3. Log join produces 0 matches
4. PoC #6 reports 0% compliance (false negative)

**Preliminary fix:** Add `--session-id` to memory_search_engine.py CLI. Have the skill pass session_id.

**Analysis directions for analyst-integration:**
1. Design the `--session-id` CLI parameter for memory_search_engine.py
2. How does the /memory:search skill get the current session_id? (check SKILL.md, hooks environment)
3. Map the import dependency graph for the logging module integration
4. What's the minimal change to make PoC #6 unblocked?

---

## Finding #5: Logger Import Crash (HIGH)

**Summary:** If `memory_logger.py` is added as a top-level import in `memory_retrieve.py`, and the file doesn't exist (partial deploy), `ModuleNotFoundError` crashes the entire hook. This violates fail-open.

**Code reference:**
- `memory_retrieve.py:25-37` -- current top-level imports
- `memory_retrieve.py:23` -- `sys.path.insert(0, ...)` for local imports
- `memory_retrieve.py:429` -- lazy import precedent: `from memory_judge import judge_candidates` (inside main())
- `memory_retrieve.py:503` -- another lazy import of judge

**Existing precedent:** `memory_judge.py` is imported lazily inside `main()` with implicit try (if judge not enabled, import never runs). Plan #2 doesn't specify lazy import for memory_logger.

**Preliminary fix:**
```python
try:
    from memory_logger import emit_event
except ImportError:
    def emit_event(*args, **kwargs): pass
```

**Analysis directions for analyst-integration:**
1. Map ALL import patterns in memory_retrieve.py -- which are top-level, which are lazy?
2. Should the lazy import be at module level (with try/except) or inside each calling function?
3. Should memory_judge.py adopt the same explicit try/except pattern for consistency?
4. What about memory_search_engine.py and memory_triage.py that also need to import memory_logger?
5. Design a consistent "optional module import" pattern for the entire plugin

---

## Cross-Finding Interactions

These findings are NOT independent. Key interactions:

1. **Finding #1 + #2:** If raw_bm25 is used for ratios (Fix #1), the ratio compression from body_bonus disappears, which may reduce false cluster triggers (partially mitigating #2). But the tautology at max_inject=3 remains regardless.

2. **Finding #1 + #3:** The PoC #5 measurement fix (log both scores) depends on the score domain fix being clearly documented. The dual-score logging is the bridge.

3. **Finding #4 + #5:** Both are integration issues in the logging/CLI boundary. The --session-id pattern and the lazy import pattern should follow consistent design principles.

4. **All findings + Plan updates:** The renamed plan files need to incorporate refined solutions from this analysis. Each plan maps to findings:
   - plan-retrieval-confidence-and-output.md: Finding #1, #2
   - plan-search-quality-logging.md: Finding #5
   - plan-poc-retrieval-experiments.md: Finding #3, #4
