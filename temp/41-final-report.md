# V2-Adversarial Deep Analysis: Final Report

**Date:** 2026-02-22
**Process:** 7 agents across 5 phases (3 analysts, 2 V1 verifiers, 2 V2 verifiers)
**External validation:** Codex 5.3, Gemini 3 Pro, Gemini 3.1 Pro (via pal clink)

---

## Executive Summary

Five findings from the V2-adversarial review were deeply analyzed. **The V2 adversarial round overturned the core Finding #1 fix**, discovering that using `raw_bm25` for confidence labels creates a ranking-label inversion where the #1 ranked result can be silenced under tiered output. This is a significant course correction.

### Final Dispositions

| # | Finding | Original Severity | Final Severity | Final Fix | Code LOC |
|---|---------|------------------|---------------|-----------|----------|
| 1 | Score Domain Paradox | CRITICAL | **HIGH** | **REJECTED as code change.** Keep composite score for confidence_label. Calibrate abs_floor to composite domain (plan text fix). Log raw_bm25 for diagnostics only. | 0 |
| 2 | Cluster Tautology | CRITICAL | **LOW** | Keep disabled. Replace dead-code threshold in plan text. Proven mathematically. | 0 |
| 3 | PoC #5 Measurement | HIGH | **LOW** | Triple-field logging (raw_bm25, score, body_bonus). Reframe before/after as label_precision. Plan text only. | 0 |
| 4 | PoC #6 Dead Path | HIGH | **LOW** | Add `--session-id` CLI param + env fallback to memory_search_engine.py. PARTIALLY UNBLOCKED. | ~12 |
| 5 | Logger Import Crash | HIGH | **HIGH** | Module-level try/except for memory_logger + harden judge imports + stderr warnings + `e.name` scoping. | ~36 |

**Total code changes: ~48 LOC across 2 files.** No architectural changes required.

### Newly Discovered Issues

| # | Issue | Severity | Disposition |
|---|-------|----------|-------------|
| NEW-1 | apply_threshold noise floor distortion | LOW-MEDIUM | Deferred -- let PoC #5 data inform |
| NEW-2 | Judge import vulnerability (same class as #5) | HIGH | Fixed with Finding #5 |
| NEW-3 | Empty XML after judge rejects all candidates | LOW | Track separately |
| NEW-4 | Ranking-label inversion (broke Finding #1 fix) | HIGH | Resolved by rejecting raw_bm25 code change |
| NEW-5 | ImportError masks transitive failures | MEDIUM | Resolved by e.name scoping |

---

## Finding-by-Finding Analysis

### Finding #1: Score Domain Paradox

**Original problem:** `confidence_label()` receives `BM25 - body_bonus` (composite score), not raw BM25. Plan #1 calibrates `abs_floor` to BM25 ranges, but the function operates on composite domain.

**Proposed fix (from analysts):** Use `raw_bm25` for confidence_label at lines 283 and 299.

**V2-adversarial discovered (NEW-4):** The fix creates a ranking-label inversion:
```
Entry A: raw_bm25=-1.0, body_bonus=3, composite=-4.0 (ranked #1)
Entry B: raw_bm25=-3.5, body_bonus=0, composite=-3.5 (ranked #2)

With raw_bm25 labels: A gets "low", B gets "high"
Under tiered output: A is SILENCED, B gets full injection
```

The #1 ranked result gets silenced while a lower-ranked result gets full injection. This is a functional bug under Action #2's tiered output, where confidence labels drive injection format (low = silence).

**Root cause of the error:** The analysts correctly identified that composite scores distort confidence ratios, but didn't account for the downstream consequence: confidence labels must be monotonic with ranking when labels drive behavioral decisions (tiered output).

**Final resolution:**
1. **REJECT the 2-line code change.** Lines 283 and 299 stay unchanged.
2. **Recalibrate abs_floor to composite domain.** The plan should document that abs_floor operates on composite scores (BM25 - body_bonus, range approximately 0-15 for typical corpora), not raw BM25 scores.
3. **Log raw_bm25 for diagnostics.** The triple-field logging (raw_bm25 + score + body_bonus) remains valuable for PoC #5 analysis -- just don't use raw_bm25 for confidence labeling.
4. **Severity downgrade:** CRITICAL -> HIGH. Labels are informational metadata in the LLM context (not retrieval-critical), and tiered output defaults to "legacy" (no behavioral impact).

### Finding #2: Cluster Tautology

**Proven mathematically.** At `max_inject=3`, cluster detection (`C >= 3`) fires on the majority of successful queries. Five fix options analyzed; only Option B (pre-truncation counting) is sound, but implementing it for a disabled feature is wasted engineering.

**Key correction:** The plan's proposed fix `cluster_count > max_inject` is dead code -- it can NEVER fire because `C <= N <= max_inject`, so `C > max_inject` is impossible.

**Final resolution:** Keep disabled. Document the tautology. Remove dead-code threshold from plan.

### Finding #3: PoC #5 Measurement Invalidity

**Resolved via plan text amendments:**
1. Log triple fields per result: raw_bm25, score (composite), body_bonus
2. Compute dual precision: on raw_bm25 (BM25 quality) AND composite (end-to-end quality)
3. Reframe before/after comparison as label_precision (label classification accuracy), NOT precision@k (unchanged by Action #1)
4. Specify human annotation methodology for relevance ground truth

### Finding #4: PoC #6 Dead Correlation Path

**Resolved with minimal CLI addition:**
1. Add `--session-id` argparse param to `memory_search_engine.py` (optional, default empty)
2. Resolve precedence: `CLI arg > CLAUDE_SESSION_ID env var > empty string`
3. Emit `search.query` log event with session_id after result output (after L495)
4. No SKILL.md changes (LLM cannot access session_id)

**PoC #6 status:** BLOCKED -> PARTIALLY UNBLOCKED. Manual correlation via --session-id possible; automatic skill correlation awaits env var.

### Finding #5: Logger Import Crash + Judge Hardening

**Most impactful fix. Prevents hook crashes on partial deployments.**

Code changes:
1. **memory_logger import** (module-level try/except in memory_retrieve.py and memory_search_engine.py):
   ```python
   try:
       from memory_logger import emit_event
   except ImportError as e:
       if getattr(e, 'name', None) != 'memory_logger':
           raise
       def emit_event(*args, **kwargs): pass
   ```

2. **Judge import hardening** (both FTS5 path L429 and legacy path L503):
   ```python
   try:
       from memory_judge import judge_candidates
   except ImportError as e:
       if getattr(e, 'name', None) != 'memory_judge':
           raise
       judge_candidates = None
       print("[WARN] Judge enabled but memory_judge module not found; "
             "falling back to top-k", file=sys.stderr)
   ```

3. **sys.path.insert** in memory_search_engine.py for standalone CLI sibling module resolution.

**V2 refinement (NEW-5):** `e.name` check distinguishes "module missing" (fallback) from "transitive dependency failure" (fail-fast). This was independently flagged by both Gemini and Codex.

---

## Plan File Updates

### plan-retrieval-confidence-and-output.md

**Changes needed:**

1. **Finding #1 (lines 76-93):** Remove the raw_bm25 code change. Instead document:
   - confidence_label operates on composite score (BM25 - body_bonus) -- this is INTENTIONAL because labels must align with ranking for tiered output
   - abs_floor should be calibrated to composite domain (range ~0-15 for typical corpora), not raw BM25
   - raw_bm25 is preserved at line 256 for diagnostic logging only

2. **Finding #2 (line 68):** Replace `cluster_count > max_inject` with:
   - Post-truncation cluster detection is mathematically tautological at max_inject <= 3 (proven: C <= N <= max_inject, so C > max_inject is impossible)
   - If ever implemented, requires pre-truncation counting
   - Feature remains disabled by default (cluster_detection_enabled: false)

3. **Progress checkboxes (line 131-132):** Update raw_bm25 references -- no longer using raw_bm25 for confidence_label calls

### plan-search-quality-logging.md

**Changes needed:**

1. **Logging schema (line 112):** Add `body_bonus` field to per-result data:
   ```json
   {"path": "...", "score": -4.23, "raw_bm25": -1.23, "body_bonus": 3, "confidence": "high"}
   ```

2. **Lazy import pattern (lines 77-84):** Add `e.name` scoping to try/except:
   ```python
   except ImportError as e:
       if getattr(e, 'name', None) != 'memory_logger':
           raise
       def emit_event(*args, **kwargs): pass
   ```

### plan-poc-retrieval-experiments.md

**Changes needed:**

1. **PoC #5 (lines 191-216):** Expand V2-adversarial caveat:
   - Log triple fields: raw_bm25, score (composite), body_bonus
   - Compute precision on BOTH raw_bm25 and composite rankings
   - Before/after Action #1 measures label_precision (label classification accuracy), NOT precision@k
   - precision@k being identical before/after is the EXPECTED result
   - Relevance ground truth from human annotation on curated query set

2. **PoC #6 (line 278):** BLOCKED -> PARTIALLY UNBLOCKED:
   - `--session-id` CLI param available for manual correlation
   - Automatic skill-to-hook correlation awaits CLAUDE_SESSION_ID env var
   - Manual correlation sufficient for exploratory data collection scope

---

## Process Assessment

The v2-fresh verifier correctly identified process bloat: 7 agents / 5 phases / 10+ documents for ~48 LOC of code changes. However, the process DID find real bugs:

1. **Value found:** Finding #5 (import crash) is a genuine hot-path crash prevention. The judge vulnerability (NEW-2) was discovered during this analysis.
2. **Value found:** The V2 adversarial round discovered the ranking-label inversion (NEW-4), which would have shipped as a regression if the analysts' proposed fix went unchallenged.
3. **Excess:** Findings #2, #3, #4 are LOW severity and could have been handled with plan text notes, not multi-agent review.

**Recommendation for future work:** Use triage sizing. <50 LOC fixes = 2-agent pipeline (analyst + verifier). Reserve the full multi-phase pipeline for >200 LOC architectural changes.

---

## Implementation Priority

1. **Finding #5** (import hardening + judge hardening + e.name scoping) -- ~36 LOC, prevents crashes
2. **Finding #4** (--session-id CLI param) -- ~12 LOC, enables future PoC work
3. **Finding #2** (plan text fix for cluster tautology) -- 0 LOC, corrects dead-code specification
4. **Finding #1** (plan text fix for abs_floor calibration) -- 0 LOC, corrects domain documentation
5. **Finding #3** (plan text fix for PoC #5 methodology) -- 0 LOC, improves measurement accuracy
