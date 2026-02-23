# V1 Code Correctness Verification Report

**Verifier:** v1-code-verifier
**Date:** 2026-02-22
**Source:** `temp/41-solution-synthesis.md` + 3 analyst reports
**Method:** Line-by-line source code trace, external validation (Gemini 3 Pro), vibe-check

---

## 1. Verification Results

### Finding #1: raw_bm25 Fallback -- PASS

| Check | Result | Details |
|-------|--------|---------|
| Line 283 current code | PASS | Confirmed: `best_score = max((abs(entry.get("score", 0)) for entry in top), default=0)` |
| Line 283 proposed change | PASS | `entry.get("raw_bm25", entry.get("score", 0))` is valid nested `.get()` fallback |
| Line 299 current code | PASS | Confirmed: `conf = confidence_label(entry.get("score", 0), best_score)` |
| Line 299 proposed change | PASS | Same fallback pattern, correct |
| raw_bm25 creation order (L256-257) | PASS | L256: `r["raw_bm25"] = r["score"]` executes BEFORE L257: `r["score"] = r["score"] - r.get("body_bonus", 0)`. Order is correct. |
| FTS5 path entries have raw_bm25 | PASS | All entries from `score_with_body()` pass through L255-257 loop. Every entry gets `raw_bm25`. |
| Legacy path entries lack raw_bm25 | PASS | Legacy entries (L462-572) never call `score_with_body()`. No `raw_bm25` key. Fallback correctly uses `score`. |
| Judge filtering preserves keys | PASS | Judge filter at L446 is `[e for e in results if e["path"] in filtered_paths]` -- no key modification. `memory_judge.py` accesses `title`, `category`, `tags` only, never `score` or `raw_bm25`. |
| FTS5 and legacy paths mutually exclusive | PASS | FTS5 path exits via `return` (L456) or `sys.exit(0)` (L460). Legacy path only reachable if FTS5 block skipped entirely. No entry mixing possible. |
| best_score domain consistency | PASS | Within a single `_output_results()` call, all entries come from exactly one path. No domain mixing. |
| Edge: score=0 legitimately | PASS | FTS5: BM25 MATCH only returns actual matches (score != 0). Legacy: entries with score 0 filtered at L489. Pathological case: returns "low" label (correct). |
| Edge: empty `top` list | PASS | `max((...), default=0)` returns 0. Empty iteration, `confidence_label` never called. No division by zero. |
| abs() correctness across domains | PASS | BM25 negative scores and legacy positive scores both handled by `abs()` in `confidence_label()`. |

### Finding #2: Cluster Tautology Proof -- PASS

| Check | Result | Details |
|-------|--------|---------|
| MAX_AUTO = 3 | PASS | Confirmed at `memory_search_engine.py:270` |
| return results[:limit] | PASS | Confirmed at `memory_search_engine.py:289`. Truncation to `limit` items. |
| N <= max_inject after truncation | PASS | `results[:limit]` guarantees `len(results) <= limit`. |
| C <= N <= 3 mathematical proof | PASS | At max_inject=3: C (cluster count) counts elements of results, so C <= N <= 3. For C >= 3 to fire, C must equal 3, requiring ALL 3 entries to cluster. Proof is sound. |
| Edge: empty results | PASS | L278: returns `[]` immediately. |
| Edge: limit=0 | PASS | `results[:0]` returns `[]` in Python. |
| Edge: negative limit | PASS | Caller clamps max_inject to [0, 20] at `memory_retrieve.py:358`. Even if negative slipped through, `results[:negative]` returns `[]`. |
| apply_threshold never exceeds limit | PASS | Noise floor can only REDUCE count, never increase. `[:limit]` is final operation. |

### Finding #5: Judge Import Vulnerability -- PASS

| Check | Result | Details |
|-------|--------|---------|
| FTS5 judge import (L429) | PASS | Confirmed: bare `from memory_judge import judge_candidates` inside `if judge_enabled and results:`. No try/except. Crash if module missing + judge enabled. |
| Legacy judge import (L503) | PASS | Confirmed: same bare import pattern at L503. Same vulnerability. |
| Proposed try/except: module present | PASS | Import succeeds, `judge_candidates` is function, `is not None` is True, existing logic unchanged. |
| Proposed try/except: module absent | PASS | ImportError caught, `judge_candidates = None`, fallback activates. |
| ImportError vs SyntaxError | PASS | `ImportError` does NOT catch `SyntaxError`. Only missing modules trigger fallback. Correct exception type. |
| Fallback: FTS5 path (`results[:fallback_k]`) | PASS | `results` exists as list from `score_with_body()`. Slicing is valid. Flow continues to L454: `top = results[:max_inject]`. |
| Fallback: legacy path (`scored[:fallback_k]`) | PASS | `scored` exists as list of tuples. Slicing is valid. Flow continues to deep check at L532. |
| Line numbers for both import sites | PASS | L429 (FTS5 path) and L503 (legacy path) confirmed exactly. |

### Finding #4: --session-id Parameter -- PASS WITH NOTES

| Check | Result | Details |
|-------|--------|---------|
| Argparse position (after --format, L443) | PASS | --format ends at L443. No positional args would conflict. |
| `os` already imported | PASS | `import os` at `memory_search_engine.py:17`. |
| emit_event placement | **CONCERN** | Synthesis says "after line 482" but L482 is inside the JSON output branch only. The call should be AFTER the entire if/else output block (after L495) to cover both JSON and text output paths. See Line Number Corrections below. |

### Finding #5 (Logger Import): memory_search_engine.py -- PASS

| Check | Result | Details |
|-------|--------|---------|
| sys.path.insert needed for standalone CLI | PASS | `memory_search_engine.py` is invoked directly as CLI. No sibling path setup exists currently. Adding `sys.path.insert(0, str(Path(__file__).resolve().parent))` is correct. |
| sys import already present | PASS | `import sys` at L19. |
| Idempotent with memory_retrieve.py's sys.path.insert | PASS | When imported as module (via memory_retrieve.py), the insert is harmless (same path already in sys.path). |

---

## 2. Line Number Corrections

| Fix | Claimed Line | Actual Line | Correction |
|-----|-------------|-------------|-----------|
| emit_event placement | "after line 482" (synthesis section 7.1, Change 3) | Should be after L495 | The emit_event() call must be placed AFTER the entire if/else output block (both json and text branches), not inside the JSON branch at L482. Place at approximately L496, after the text output for-loop ends. |

All other line number references verified correct:
- L283: best_score computation -- CORRECT
- L299: confidence_label call -- CORRECT
- L256-257: raw_bm25 creation -- CORRECT
- L429: FTS5 judge import -- CORRECT
- L503: legacy judge import -- CORRECT
- L443: --format argparse end -- CORRECT

---

## 3. Missed Edge Cases

### 3.1 Empty XML Output After Judge Rejection (NEW -- from Gemini 3 Pro)

**Severity:** LOW
**Location:** `memory_retrieve.py:454-455`

If `judge_enabled=true` and the judge filters out ALL candidates, `results` becomes `[]`, then `top = results[:max_inject]` is `[]`. `_output_results([], ...)` outputs an empty `<memory-context>...</memory-context>` XML block. This wastes tokens and provides no hint to the user.

The legacy path correctly handles this at L558: `if not final:` prints a hint comment.

**Recommended fix:** Add `if not top:` guard before `_output_results()` in the FTS5 path:
```python
top = results[:max_inject]
if not top:
    print("<!-- No matching memories found. If project context is needed, use /memory:search <topic> -->")
    return
_output_results(top, category_descriptions)
return
```

### 3.2 score=0 Edge Case in Fallback Chain

**Severity:** NONE (verified safe)

Investigated whether `entry.get("raw_bm25", entry.get("score", 0))` could misinterpret a legitimate `score=0`. Concluded:
- FTS5 path: BM25 MATCH only returns actual matches, `score=0.0` is essentially impossible. Even if it occurred, `raw_bm25=0.0` would also be set.
- Legacy path: Entries with score 0 are filtered at L489 (`if text_score > 0`).
- Pathological case: Returns "low" label, which is correct.

---

## 4. Cross-Fix Interactions

| Interaction | Finding | Verdict |
|-------------|---------|---------|
| #1 (raw_bm25) + #5 (judge hardening) | Judge does not access `score` or `raw_bm25` keys. Filter operation preserves all keys. | NO CONFLICT |
| #4 (--session-id) + #5 (logger import) | Both touch `memory_search_engine.py` but in different locations (argparse vs module-level imports). `emit_event()` call depends on logger import being present. | NO CONFLICT (must apply together) |
| #1 (raw_bm25) + #2 (cluster tautology) | Using raw_bm25 for ratios reduces body_bonus compression, making cluster detection slightly more likely to fire on raw scores. But cluster detection is disabled by default, so no practical impact. | NO CONFLICT |
| All 5 fixes together | Fixes touch independent code sections. No shared mutable state, no overlapping line edits. | CLEAN INTEGRATION |

---

## 5. External Validation Results

### Gemini 3 Pro (codereviewer role)

**Question asked:** Are the FTS5 and legacy paths truly mutually exclusive? Can entries from one path mix with entries from the other in a single `_output_results()` call?

**Answer:** "The claim is correct. The paths are strictly mutually exclusive. There is zero possibility of domain mixing." Gemini traced the control flow: FTS5 block always terminates via `return` (L456) or `sys.exit(0)` (L460). Legacy path only reachable if FTS5 block was bypassed.

**Bonus finding:** Empty XML output when judge rejects all candidates (Section 3.1 above).

**Verdict:** External validation CONFIRMS the core architectural assumption underlying the raw_bm25 fallback fix.

---

## 6. Vibe-Check Results

**Challenge posed:** Am I being thorough enough? Specifically, does the fallback pattern handle `score=0` legitimately?

**Self-assessment:**
- The `score=0` edge case is safe (Section 3.2 above).
- The `abs()` normalization in `confidence_label()` correctly handles both negative BM25 and positive legacy scores.
- The one gap identified (emit_event placement at L482 vs L495) is a genuine line number error in the synthesis.
- The bonus finding (empty XML after judge rejection) is a real but low-severity issue outside the current fix scope.

**Calibration:** Analysis is appropriately thorough. All critical claims verified against source code. No over-analysis (didn't expand into unrelated code). No under-analysis (traced all code paths, checked edge cases, got external confirmation on the key architectural assumption).

---

## 7. Overall Verdict: PASS WITH NOTES

All 5 proposed fixes are code-correct. The fixes are safe to implement.

**Notes:**
1. **Line number correction:** `emit_event()` placement in Finding #4 should reference "after L495" (after entire output block), not "after L482" (inside JSON branch only).
2. **New minor finding:** Empty `<memory-context>` XML output when judge rejects all candidates in FTS5 path. Recommend adding `if not top:` guard (LOW severity, can be tracked separately).
3. **Dependency:** Finding #4 (--session-id with emit_event) depends on Finding #5 (logger import). Must be applied together or emit_event call must be conditional.

No FAIL or NEEDS WORK findings. All proposed code changes are sound, all mathematical proofs verified, all fallback chains traced end-to-end.
