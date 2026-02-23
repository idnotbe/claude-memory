# V2-Adversarial Deep Analysis: Solution Synthesis

**Date:** 2026-02-22
**Sources:** `temp/41-finding1-3-score-domain.md`, `temp/41-finding2-cluster-logic.md`, `temp/41-finding4-5-integration.md`

---

## Executive Summary

Three independent analysts examined 5 findings with external validation (Codex 5.3, Gemini 3 Pro) and vibe-check metacognition. Two additional issues were discovered during analysis. All fixes are surgical, totaling ~40 LOC changed across 2 files.

### Findings Status

| # | Finding | Severity | Solution | LOC | Confidence |
|---|---------|----------|----------|-----|-----------|
| 1 | Score Domain Paradox | CRITICAL | Use `raw_bm25` with fallback in `_output_results()` lines 283, 299 | ~2 | Very High -- unanimous consensus, clean fallback |
| 2 | Cluster Tautology | CRITICAL | Keep disabled (default false). Plan fix `cluster_count > max_inject` is dead code -- must update plan text. | ~0 (plan text only) | Very High -- mathematically proven |
| 3 | PoC #5 Measurement Invalidity | HIGH | Log triple (raw_bm25 + score + body_bonus). Reframe before/after as label_precision. | ~0 (plan text only) | High -- all models agree |
| 4 | PoC #6 Dead Correlation Path | HIGH | Add `--session-id` CLI param + env fallback. PoC #6 PARTIALLY UNBLOCKED. | ~12 | High -- minimal design |
| 5 | Logger Import Crash | HIGH | Module-level `try/except ImportError` for memory_logger. Harden existing judge imports. | ~34 added, ~8 modified | High -- follows existing precedent |
| NEW-1 | apply_threshold noise floor distortion | MEDIUM | Track separately -- body_bonus distorts 25% noise floor on composite score | 0 (future work) | Medium -- Gemini validated, needs empirical data |
| NEW-2 | Judge import vulnerability | HIGH | Same bug class as #5 -- judge_enabled=true + missing module = crash | Fixed with #5 | High -- Gemini discovered |

---

## Solution Details

### Finding #1: Score Domain Paradox Fix

**Two single-line edits in `hooks/scripts/memory_retrieve.py`:**

**Line 283** -- best_score computation:
```python
# BEFORE:
best_score = max((abs(entry.get("score", 0)) for entry in top), default=0)
# AFTER:
best_score = max((abs(entry.get("raw_bm25", entry.get("score", 0))) for entry in top), default=0)
```

**Line 299** -- confidence_label call:
```python
# BEFORE:
conf = confidence_label(entry.get("score", 0), best_score)
# AFTER:
conf = confidence_label(entry.get("raw_bm25", entry.get("score", 0)), best_score)
```

**Why this works:** The `entry.get("raw_bm25", entry.get("score", 0))` pattern is a safe fallback chain:
- FTS5 path: `raw_bm25` present (set at line 256) -> uses raw BM25
- Legacy path: `raw_bm25` absent -> falls back to `score` (unmutated legacy keyword score)
- body_bonus=0: `raw_bm25 == score` -> no difference

**What doesn't change:** `apply_threshold()` stays on composite score for sorting (body matches ARE a legitimate relevance signal for ranking). Noise floor distortion tracked as NEW-1.

### Finding #2: Cluster Tautology Resolution

**No code changes. Plan text fix only.**

analyst-logic proved that Option A (`cluster_count > max_inject`) is mathematically impossible to satisfy post-truncation -- it's dead code that secretly disables the feature. All 5 fix options have flaws when applied post-truncation. Only Option B (pre-truncation counting) is sound, but it requires pipeline changes for a feature defaulted to `false`.

**Recommendation:** Keep `cluster_detection_enabled: false`. Document the tautology. If ever enabled, require pre-truncation counting AND `max_inject > 3`.

**Plan text fix:** Replace the `cluster_count > max_inject` threshold specification with documentation that:
1. Post-truncation cluster detection is tautological at max_inject <= 3
2. Valid implementation requires pre-truncation counting (deferred)
3. Feature remains disabled by default with clear rationale

### Finding #3: PoC #5 Measurement Fix

**Plan text amendments to `plans/plan-poc-retrieval-experiments.md`:**

1. **Logging schema:** Log triple fields per result: `raw_bm25`, `score` (composite), `body_bonus`
2. **Dual precision:** Compute precision on raw_bm25 (BM25 quality) AND composite (end-to-end quality)
3. **Before/after metric:** Action #1 comparison measures `label_precision_high/medium`, NOT precision@k (which is unchanged by Action #1 since it modifies labels, not ranking)
4. **Explicit note:** precision@k being identical before/after is the EXPECTED result, not a failure

**Plan text amendment to `plans/plan-search-quality-logging.md`:**

1. Add `body_bonus` field to logging schema per-result

### Finding #4: --session-id CLI Parameter

**Code changes in `hooks/scripts/memory_search_engine.py`:**

1. Add `--session-id` argparse param (optional, default empty string)
2. Resolve: `args.session_id or os.environ.get("CLAUDE_SESSION_ID", "")`
3. Pass session_id to `emit_event()` when logging is available

**SKILL.md:** No changes. The LLM cannot access session_id (no env var exists). The param serves: (a) future env var availability, (b) manual CLI testing, (c) automated tests.

**PoC #6:** Status from BLOCKED to PARTIALLY UNBLOCKED. Manual correlation possible; automatic skill correlation awaits env var.

### Finding #5: Lazy Import Pattern + Judge Hardening

**`hooks/scripts/memory_retrieve.py`:**

1. **Module-level try/except for memory_logger** (after line 37):
   ```python
   try:
       from memory_logger import emit_event
   except ImportError:
       def emit_event(*args, **kwargs): pass
   ```

2. **Harden judge imports** at lines 429 and 503: wrap existing `from memory_judge import judge_candidates` in `try/except ImportError` with `judge_candidates = None` fallback, then check before calling.

**`hooks/scripts/memory_search_engine.py`:**

1. Add `sys.path.insert(0, ...)` for sibling module resolution in standalone CLI mode
2. Same module-level try/except for memory_logger

---

## Cross-Finding Interactions

| Interaction | Impact | Resolution |
|-------------|--------|-----------|
| #1 + #2: raw_bm25 ratios reduce false clusters | Positive -- less ratio compression | Independent fixes, both needed |
| #1 + #3: raw_bm25 logging enables dual-precision PoC | Synergistic -- same field serves both | Plan updates reference both |
| #2 + plan text: dead code threshold must be corrected | Critical -- wrong fix in plan | Plan text update required |
| #4 + #5: both touch CLI/hook boundary | Shared principle: optional features must not break core | Consistent patterns applied |
| #5 + NEW-2: same bug class (missing optional module) | Judge vulnerability is identical pattern | Fixed together |

---

## Newly Discovered Issues (For Separate Tracking)

### NEW-1: apply_threshold Noise Floor Distortion (MEDIUM)

**Discovered by:** Gemini 3 Pro (via analyst-score)

The 25% noise floor in `apply_threshold()` (`memory_search_engine.py:284-287`) uses composite score, not raw_bm25. When best entry has high body_bonus, the floor is inflated, potentially discarding entries with reasonable raw BM25 matches but body_bonus=0.

**Recommendation:** Track separately. Let PoC #5 logging data (with body_bonus field) provide empirical evidence of practical impact. Plans explicitly exclude `memory_search_engine.py` from changes.

### NEW-2: Judge Import Vulnerability (HIGH)

**Discovered by:** Gemini 3 Pro (via analyst-integration)

Existing judge imports at `memory_retrieve.py:429,503` lack `try/except ImportError`. If `judge.enabled=true` but `memory_judge.py` is missing, the hook crashes. Same bug class as Finding #5.

**Resolution:** Fixed as part of Finding #5 solution (judge hardening).

---

## Plan File Updates Needed

### plan-retrieval-confidence-and-output.md (Findings #1, #2)

1. **Line 68:** Replace `cluster_count > max_inject` with documentation that post-truncation cluster detection is tautological. Specify pre-truncation counting as the valid implementation (deferred).
2. **Lines 76-82:** Verify raw_bm25 fix description is accurate (already mostly correct)
3. **Line 90:** Note that `score`, `best_score` params now use `raw_bm25` domain with fallback
4. **Line 130 progress checkbox:** Update cluster_count threshold description

### plan-search-quality-logging.md (Finding #5)

1. **Lines 77-84:** Verify lazy import pattern matches our recommendation (already mostly correct)
2. **Line 112 schema:** Add `body_bonus` field to per-result logging
3. Add note about judge import hardening as a related fix

### plan-poc-retrieval-experiments.md (Findings #3, #4)

1. **Lines 191-196:** Expand V2-adversarial caveat with triple-field logging and label_precision metric
2. **Line 210:** Add `label_precision_high`, `label_precision_medium` to metrics list
3. **Lines 215-216:** Explicitly state precision@k unchanged by Action #1 (expected result)
4. **Line 278:** Change PoC #6 from BLOCKED to PARTIALLY UNBLOCKED
5. **Lines 282-283:** Add --session-id design and limitations

---

## Verification Questions for V1 Round

1. **Code correctness:** Are the 2-line raw_bm25 fallback changes correct at lines 283 and 299? Does the fallback chain handle all entry sources?
2. **Design quality:** Does the judge hardening pattern (try/except + None check + fallback) introduce any new failure modes?
3. **Security:** Does the --session-id parameter create any injection vectors? (analyst-integration says no -- only written to JSONL logs)
4. **Emergent issues:** Do the 5 fixes interact badly? (Cross-finding analysis says they're independent or synergistic)
5. **Plan text accuracy:** Are the proposed plan amendments consistent with the actual code behavior?
