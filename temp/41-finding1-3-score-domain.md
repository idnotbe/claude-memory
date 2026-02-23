# Finding #1 & #3: Score Domain Paradox -- Deep Analysis

**Analyst:** analyst-score
**Date:** 2026-02-22
**Findings covered:** #1 (Score Domain Paradox, CRITICAL), #3 (PoC #5 Measurement Invalidity, HIGH)

---

## 1. Executive Summary

The `score` field in the FTS5 retrieval path undergoes in-place mutation at `memory_retrieve.py:257` (`score = raw_bm25 - body_bonus`). This mutated value flows into two downstream consumers -- `apply_threshold()` and `confidence_label()` -- where it creates distinct but related problems:

- **confidence_label():** Receives composite scores, labels indicate "blended relevance" instead of "BM25 match quality." Fix is straightforward: use `raw_bm25` with fallback.
- **apply_threshold() noise floor:** The 25% proportional noise floor computed on composite scores is distorted by the unscaled integer body_bonus (0-3 added to a corpus-scaled BM25 float). This is a **newly discovered concern** beyond the original brief's scope.
- **PoC #5:** Will measure composite precision, not BM25 precision. Dual-score logging (raw_bm25 + score + body_bonus) and reframing the Action #1 comparison as "label quality" resolves this.

**Recommendation:** Fix confidence_label (in-scope). Flag apply_threshold noise floor as a separate tracked issue. Amend PoC #5 methodology.

---

## 2. Pipeline Trace (Every Score Consumer Documented)

### 2.1 Score Creation and Mutation

| Line | File | What happens | Score domain |
|------|------|-------------|-------------|
| `memory_search_engine.py:252` | `query_fts()` | BM25 rank assigned to `result["score"]` | raw BM25 (negative float, more negative = better) |
| `memory_retrieve.py:256` | `score_with_body()` | `r["raw_bm25"] = r["score"]` | Preserved raw BM25 |
| `memory_retrieve.py:257` | `score_with_body()` | `r["score"] = r["score"] - r.get("body_bonus", 0)` | **MUTATED to composite** (raw_bm25 - body_bonus) |

### 2.2 All Downstream Consumers of `score`

#### Consumer 1: `apply_threshold()` -- `memory_search_engine.py:261-289`

Called at `memory_retrieve.py:259` via `return apply_threshold(initial, mode, max_inject=max_inject)`.

```python
# Line 281: SORT by composite score (more negative = better)
results.sort(key=lambda r: (r["score"], CATEGORY_PRIORITY.get(r["category"], 10)))

# Line 284: NOISE FLOOR computed from composite score
best_abs = abs(results[0]["score"])  # <-- uses MUTATED score

# Line 287: FILTER by noise floor
results = [r for r in results if abs(r["score"]) >= noise_floor]  # <-- uses MUTATED score
```

**Analysis:** Two distinct operations:
- **Sorting (line 281):** Composite score is CORRECT for ranking. Body matches are a legitimate relevance signal; an entry matching on title+tags AND body IS more relevant than title-only. Sorting should use composite.
- **Noise floor (lines 284-287):** Using composite score HERE is problematic. The 25% proportional floor mixes domains: BM25 is a corpus-scaled float, body_bonus is a static integer 0-3. When the best entry has `raw_bm25=-2.0, body_bonus=3`, composite is `-5.0`, floor becomes `1.25`. An entry with `raw_bm25=-1.0, body_bonus=0` (composite=-1.0) falls below this floor and gets discarded despite having a reasonable BM25 match.

**Scope decision:** This noise floor distortion is a real concern but was **NOT flagged in the original Finding #1**. The plans explicitly state `apply_threshold()` is not being modified (Plan #1, line 426: "변경하지 않는 파일" lists `memory_search_engine.py`). I recommend documenting this as a **newly discovered issue** for separate tracking, not expanding the current fix scope. Rationale: (a) body_bonus is capped at 3 and typical BM25 scores for meaningful matches are more negative than -3, reducing practical impact; (b) expanding scope risks delaying the confidence_label fix.

#### Consumer 2: `_output_results()` best_score computation -- `memory_retrieve.py:283`

```python
best_score = max((abs(entry.get("score", 0)) for entry in top), default=0)
```

**Bug:** `best_score` is computed from composite scores. This inflated `best_score` is passed to `confidence_label()`, distorting the ratio calculation. An entry with `raw_bm25=-2.0, body_bonus=3` produces `abs(composite)=5.0` as best_score, compressing all other ratios.

**Fix:** Use `raw_bm25` with fallback:
```python
best_score = max((abs(entry.get("raw_bm25", entry.get("score", 0))) for entry in top), default=0)
```

#### Consumer 3: `confidence_label()` call -- `memory_retrieve.py:299`

```python
conf = confidence_label(entry.get("score", 0), best_score)
```

**Bug:** Passes composite score. Combined with inflated `best_score` from Consumer 2, the ratio `abs(composite) / abs(best_composite)` has compressed dynamic range due to body_bonus additive offset, leading to:
- False clusters (many entries cluster near ratio 1.0)
- abs_floor calibrated to BM25 ranges becomes invalid in composite domain

**Fix:**
```python
conf = confidence_label(entry.get("raw_bm25", entry.get("score", 0)), best_score)
```

#### Consumer 4: Legacy path score assignment -- `memory_retrieve.py:571`

```python
entry["score"] = score  # score from (text_score, priority, entry) tuple
```

**No bug here.** The legacy path (lines 462-577) uses keyword scoring (`score_entry()` at line 482), which returns positive integer scores with NO body_bonus mechanism. These entries never have a `raw_bm25` key. The `confidence_label()` call at line 299 in `_output_results()` receives legacy positive scores, and the ratio calculation works correctly for the legacy domain (higher = better, `abs()` handles both).

**Key insight for the fix:** The fallback `entry.get("raw_bm25", entry.get("score", 0))` is essential -- legacy path entries will fall through to `score`, which is correct because their `score` IS the raw score (no mutation).

### 2.3 Non-Consumers (score field present but not consumed for scoring)

- `memory_judge.py`: Receives candidate entries but uses them for path/title extraction, NOT score-based decisions. Judge makes relevance decisions via LLM, not score thresholds. **No fix needed.**
- `memory_search_engine.py:cli_search()` (line 411): Calls `apply_threshold()` but on CLI-path results that never go through `score_with_body()`. These results have raw BM25 scores only. **No fix needed.**
- CLI JSON output (line 494): Prints `r['score']` for display. In CLI mode, score IS raw BM25 (no body_bonus). **No fix needed.**

---

## 3. Finding #1 Solution (Exact Code Changes)

### 3.1 Changes to `memory_retrieve.py`

#### Change 1: `_output_results()` best_score computation (line 283)

```python
# BEFORE (line 283):
best_score = max((abs(entry.get("score", 0)) for entry in top), default=0)

# AFTER:
best_score = max((abs(entry.get("raw_bm25", entry.get("score", 0))) for entry in top), default=0)
```

#### Change 2: `confidence_label()` call (line 299)

```python
# BEFORE (line 299):
conf = confidence_label(entry.get("score", 0), best_score)

# AFTER:
conf = confidence_label(entry.get("raw_bm25", entry.get("score", 0)), best_score)
```

### 3.2 Fallback Behavior for Missing `raw_bm25`

The `entry.get("raw_bm25", entry.get("score", 0))` pattern handles all cases:

| Path | `raw_bm25` present? | Fallback | Correct? |
|------|---------------------|----------|----------|
| FTS5 path (score_with_body) | Yes | Uses raw_bm25 | Yes -- raw BM25 scores |
| Legacy keyword path | No | Uses `score` (legacy integer) | Yes -- no mutation occurred |
| File read failure in score_with_body | Yes (set before body extraction) | Uses raw_bm25 | Yes |
| Entry with body_bonus=0 | Yes | Uses raw_bm25 (equals score) | Yes -- no difference |

### 3.3 What Does NOT Change

- **`apply_threshold()` in `memory_search_engine.py`:** Not modified in this fix. The noise floor distortion is documented as a separate concern (see Section 8.1).
- **`score_with_body()` mutation logic (lines 256-257):** Preserved as-is. The mutation is correct for ranking purposes.
- **Legacy path (lines 462-577):** No changes needed. Legacy scores are unmutated.

### 3.4 Total LOC: ~2 lines changed

Both changes are single-line edits replacing `entry.get("score", 0)` with `entry.get("raw_bm25", entry.get("score", 0))`. The `best_score` computation is similarly a single-line change.

---

## 4. Finding #3 Solution (PoC #5 Amendments)

### 4.1 What PoC #5 Currently Measures vs. What It Should Measure

| Aspect | Current Plan | Corrected Plan |
|--------|-------------|----------------|
| Score field logged | `data.results[].score` (composite) | `data.results[].raw_bm25` + `data.results[].score` + `data.results[].body_bonus` |
| Precision computed on | Composite score ranking | **Two metrics:** raw_bm25 ranking precision (BM25 quality) AND composite ranking precision (end-to-end quality) |
| Action #1 before/after | Compares precision@k | Compares **label quality** (high/medium/low classification accuracy), NOT precision@k |

### 4.2 Logging Schema Additions

The `retrieval.search` event in Plan #2 should log per-result:

```json
{
  "results": [
    {
      "path": ".claude/memory/decisions/use-oauth.json",
      "score": -4.23,
      "raw_bm25": -1.23,
      "body_bonus": 3,
      "confidence": "high"
    }
  ]
}
```

**Why log `body_bonus` separately?**
- Both Codex and Gemini recommend explicit `body_bonus` logging over derivation via subtraction.
- Derivation is fragile: if the formula changes (e.g., weighted body_bonus, non-linear scaling), subtraction breaks.
- Enables direct analysis: "What % of high-confidence results relied on body_bonus > 0?"
- Floating-point arithmetic can introduce precision artifacts when subtracting (`-4.1000003 vs -1.1`).
- Cost: one additional integer field per result in JSONL logs (trivial).

### 4.3 Before/After Framing for Action #1

**Critical clarification:** Action #1 modifies `confidence_label()` (adding abs_floor and cluster detection). It does NOT modify ranking or the result set. Therefore:

- **precision@k will be IDENTICAL before and after Action #1** -- this is the expected result, not a measurement failure.
- **What changes:** The high/medium/low label distribution on the SAME ranked results.
- **What to measure:** Label accuracy -- for each result labeled "high", was it actually relevant? For results labeled "low", were they actually irrelevant?

**Proposed metric:** `label_precision` -- the precision of the "high" confidence label as a binary classifier for relevance.

```
label_precision_high = count(labeled "high" AND relevant) / count(labeled "high")
label_precision_medium = count(labeled "medium" AND relevant) / count(labeled "medium")
```

Before Action #1: All single-result queries produce "high" labels regardless of actual relevance.
After Action #1: Weak single-result matches get capped to "medium" by abs_floor.

### 4.4 Specific Plan Text Amendments

**In `plans/plan-poc-retrieval-experiments.md`:**

1. **Line 167** -- Change "precision@k" framing:
   - Current: "Action #1 (절대 하한선 + 클러스터 감지) 사전/사후 비교 baseline 확보"
   - Amend: Clarify that precision@k is for baseline only; before/after comparison measures label quality, not ranking quality.

2. **Lines 191-196** -- The V2-adversarial caveat block is already partially correct but should be expanded with the triple-field logging schema and explicit `label_precision` metric definition.

3. **Line 210** -- "precision@3, precision@5, recall@k" should add "label_precision_high, label_precision_medium" for the before/after comparison phase.

4. **Lines 215-216** -- "Paired evaluation: Action #1 적용 전/후 동일 쿼리셋으로 비교" should explicitly state: "Comparison measures label quality (label_precision_high/medium) on the same ranked results. precision@k is expected to be unchanged."

---

## 5. Cross-Finding Interactions

### 5.1 Finding #1 x Finding #2 (Cluster Tautology)

If `raw_bm25` is used for ratio computation in cluster detection, body_bonus compression disappears. Consider this example:

**Before fix (composite scores):**
```
Entry A: raw_bm25=-2.0, body_bonus=3 -> composite=-5.0
Entry B: raw_bm25=-1.8, body_bonus=2 -> composite=-3.8
Entry C: raw_bm25=-1.5, body_bonus=1 -> composite=-2.5

Ratios (composite): B/A = 3.8/5.0 = 0.76, C/A = 2.5/5.0 = 0.50
cluster_count (ratio > 0.90) = 1 (only A itself)
```

**After fix (raw_bm25):**
```
Ratios (raw): B/A = 1.8/2.0 = 0.90, C/A = 1.5/2.0 = 0.75
cluster_count (ratio > 0.90) = 2 (A and B)
```

The raw_bm25 ratios are MORE compressed (BM25 scores tend to be closer together without body_bonus spreading), so cluster detection is actually MORE likely to trigger on raw_bm25. This is correct behavior: it detects when BM25 alone can't distinguish between candidates, regardless of body_bonus tiebreaking.

### 5.2 Finding #1 x Finding #3

The dual-score logging (raw_bm25 + score + body_bonus) serves as the bridge:
- PoC #5 computes precision on raw_bm25 for the "BM25 quality" question
- PoC #5 computes precision on composite score for the "end-to-end quality" question
- The difference between these two precision values quantifies body_bonus's contribution to retrieval quality

### 5.3 Finding #1 x Finding #5 (Logger Import)

The confidence_label fix is independent of the logging infrastructure. Even if `memory_logger.py` hasn't been created yet, the raw_bm25 fix can be deployed. The logger will consume raw_bm25 when it exists.

---

## 6. External Validation Results

### 6.1 Codex 5.3 (via clink, codereviewer role)

**Agreement with our analysis:**
- `apply_threshold()` should stay on composite for sorting/ranking -- **agrees**
- `confidence_label()` should use raw_bm25 -- **agrees**
- Dual-score logging is good, but **add body_bonus explicitly** -- **extends our recommendation**

**Key quote:** "confidence labels no longer mean 'BM25 lexical match quality'; they mean 'post-heuristic blended relevance,' which can overstate weak lexical matches with strong body bonus."

**Severity assessment:** HIGH for the confidence_label bug, LOW for logging gap.

### 6.2 Gemini 3 Pro (via clink, codereviewer role)

**Agreement with our analysis:**
- Composite score correct for ranking -- **agrees**
- Raw BM25 correct for noise floor AND confidence labels -- **goes further than Codex**

**Key additional finding:** Gemini flagged the `apply_threshold()` noise floor as a **separate HIGH severity issue**, providing a worked example showing how body_bonus=3 on a -2.0 raw score inflates the floor from 0.5 to 1.25, silently discarding valid -1.0 BM25 matches. Gemini recommended refactoring `apply_threshold()` to sort by composite but filter by raw_bm25.

**Divergence:** Gemini recommends changing `apply_threshold()` now; Codex does not flag it. Our recommendation: document as separate concern (see Section 8.1).

### 6.3 Consensus

| Question | Codex | Gemini | Our Recommendation |
|----------|-------|--------|-------------------|
| apply_threshold sorting | Composite (agrees) | Composite (agrees) | Composite -- no change |
| apply_threshold noise floor | Not flagged | raw_bm25 (HIGH) | Document as new issue, don't expand scope |
| confidence_label score | raw_bm25 (agrees) | raw_bm25 (agrees) | raw_bm25 with fallback |
| Log body_bonus separately? | Yes (recommends) | Yes (recommends) | Yes -- add to logging schema |

---

## 7. Vibe-Check Results

**Challenge posed:** "Am I over-engineering by suggesting apply_threshold also needs to change?"

**Self-assessment result:** The apply_threshold noise floor distortion IS real (Gemini validated with a worked example) but expanding scope beyond the original brief risks:
1. Modifying `memory_search_engine.py` which Plan #1 explicitly excludes from changes
2. Requiring new tests in `test_fts5_search_engine.py` for noise floor behavior
3. Delaying the confidence_label fix
4. Creating merge conflicts with other planned changes

**Decision:** Keep the Finding #1 fix narrow (confidence_label only, ~2 LOC). Log the apply_threshold noise floor as a newly discovered issue for the next review cycle. The data from PoC #5 logging (with body_bonus as a separate field) will provide empirical evidence for whether the noise floor distortion has practical impact.

---

## 8. Risks & Edge Cases

### 8.1 Newly Discovered: apply_threshold Noise Floor Distortion

**Severity:** MEDIUM (potential silent result discarding, but mitigated by body_bonus cap at 3)

**Description:** When the best result has high body_bonus (2-3) and moderate raw BM25 (-2 to -3), the 25% noise floor on composite score can discard entries with strong raw BM25 matches that have body_bonus=0.

**Worked example (from Gemini):**
```
Best entry: raw=-2.0, bonus=3 -> composite=-5.0 -> floor = 5.0 * 0.25 = 1.25
Victim entry: raw=-1.0, bonus=0 -> composite=-1.0 -> abs(composite)=1.0 < 1.25 -> DISCARDED
But raw BM25 of -1.0 is a meaningful match (50% of best raw score).
```

**Recommendation:** Track as a separate issue. Do not expand Finding #1 fix scope. Let PoC #5 data inform whether this occurs in practice.

### 8.2 Edge Case: raw_bm25 Absent on Legacy Path

Legacy path entries (lines 462-577) have positive integer scores and NO `raw_bm25` key. The fallback `entry.get("raw_bm25", entry.get("score", 0))` correctly falls through to `score`, which in the legacy path is the unmutated keyword score. No edge case risk.

### 8.3 Edge Case: body_bonus=0 (No Body Match)

When body_bonus=0, `score == raw_bm25`. The fix is a no-op in this case, which is correct.

### 8.4 Edge Case: FTS5 Unavailable

When FTS5 is unavailable, the code falls to the legacy keyword path. `raw_bm25` is never set. The fallback handles this correctly.

### 8.5 Edge Case: All Entries Have Same raw_bm25

```
3 entries, all raw_bm25=-3.0, body_bonus varies (0, 1, 2)
Composites: -3.0, -4.0, -5.0

Current (composite): ratios = 1.0, 0.8, 0.6 -- looks well-separated
Fixed (raw_bm25): ratios = 1.0, 1.0, 1.0 -- all "high"
```

This is CORRECT behavior. If BM25 can't distinguish the entries, they should all get the same confidence label. The body_bonus differentiation is reflected in ranking order, not confidence labels.

### 8.6 Plan #1 Cluster Detection Interaction

With raw_bm25-based ratios, cluster detection (ratio > 0.90 threshold) will fire more often because BM25 scores cluster more tightly than composite scores. This is by design -- it detects when BM25 alone is ambiguous. The `cluster_count > max_inject` guard (Finding #2 fix) prevents false positives from the tautology issue.

---

## Appendix: File References

| File | Lines | Relevance |
|------|-------|-----------|
| `hooks/scripts/memory_retrieve.py` | 256-257 | Score mutation site |
| `hooks/scripts/memory_retrieve.py` | 283 | best_score computation (FIX) |
| `hooks/scripts/memory_retrieve.py` | 299 | confidence_label call (FIX) |
| `hooks/scripts/memory_retrieve.py` | 462-577 | Legacy path (no changes needed) |
| `hooks/scripts/memory_retrieve.py` | 571 | Legacy score assignment (unmutated) |
| `hooks/scripts/memory_search_engine.py` | 261-289 | apply_threshold (noise floor concern, NOT fixing now) |
| `hooks/scripts/memory_search_engine.py` | 281 | Sorting by composite (correct, no change) |
| `hooks/scripts/memory_search_engine.py` | 284-287 | Noise floor (newly discovered concern) |
| `plans/plan-retrieval-confidence-and-output.md` | 76-93 | Action #1 raw_bm25 plan text |
| `plans/plan-poc-retrieval-experiments.md` | 165-223 | PoC #5 methodology (needs amendments) |
| `plans/plan-search-quality-logging.md` | 112-122 | Logging schema (needs body_bonus field) |
