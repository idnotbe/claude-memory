# Session 5 Correctness Review -- Confidence Annotations

**Reviewer:** Claude Opus 4.6 (independent correctness review)
**Date:** 2026-02-21
**File reviewed:** `hooks/scripts/memory_retrieve.py` (lines 160-173, 279-291, 485-493)
**Implementation report:** `temp/s5-implementer-output.md`
**Plan reference:** `research/rd-08-final-plan.md` section 2e (lines 385-411)
**External validation:** Gemini 3.1 Pro (via pal clink MCP) -- reviewed and concurs

---

## Verdict: APPROVE

The confidence annotation implementation is correct, matches the plan specification, introduces no regressions, and handles all edge cases properly. Two low-severity observations are noted for future improvement but do not block approval.

**Test verification:** All 33 tests in `tests/test_memory_retrieve.py` pass (0 failures, 0.38s).

---

## Correctness Checklist

### 1. Does `confidence_label()` correctly map ratios? (lines 160-173)

**PASS.** Thresholds match the plan specification in `research/rd-08-final-plan.md` section 2e exactly:

```python
def confidence_label(score: float, best_score: float) -> str:
    if best_score == 0:
        return "low"
    ratio = abs(score) / abs(best_score)
    if ratio >= 0.75:
        return "high"
    elif ratio >= 0.40:
        return "medium"
    return "low"
```

Boundary verification:
- `ratio = 0.75` -> "high" (inclusive, correct)
- `ratio = 0.749` -> "medium" (correct)
- `ratio = 0.40` -> "medium" (inclusive, correct)
- `ratio = 0.399` -> "low" (correct)

### 2. Does `abs()` correctly handle both FTS5 and legacy scores?

**PASS.** The `abs()` approach correctly normalizes both scoring semantics:

| Path | Score example | abs() values | Best abs | Ratios | Labels |
|------|-------------|-------------|----------|--------|--------|
| FTS5 BM25 | -5.2, -3.1, -1.0 | 5.2, 3.1, 1.0 | 5.2 | 1.0, 0.60, 0.19 | high, medium, low |
| FTS5 + body bonus | -7.2 (=-5.2-2), -3.1 | 7.2, 3.1 | 7.2 | 1.0, 0.43 | high, medium |
| Legacy keyword | 8, 5, 3 | 8, 5, 3 | 8 | 1.0, 0.625, 0.375 | high, medium, low |

The mathematical invariant: in both scoring systems, the "best" result has the largest magnitude. `abs()` extracts magnitude regardless of sign, making ratio computation universally correct.

**Gemini concurrence:** "abs() cleanly unifies both models into strictly positive scaling values. The ratio calculation accurately evaluates magnitude against the strongest match."

### 3. Is `best_score` correctly computed? (line 280)

**PASS.**
```python
best_score = max((abs(entry.get("score", 0)) for entry in top), default=0)
```

- `abs()` normalizes scores before taking max
- `default=0` handles the degenerate empty-list case
- `entry.get("score", 0)` provides safe fallback for entries missing score key
- The generator expression iterates over the same `top` list that will be labeled

### 4. Edge Cases

All verified programmatically:

| Edge Case | Expected | Actual | Status |
|-----------|----------|--------|--------|
| Empty list | best_score=0, all "low" | `max(..., default=0)` -> 0, guard returns "low" | PASS |
| Single result | ratio=1.0, "high" | `abs(s)/abs(s) = 1.0 >= 0.75` | PASS |
| All same score | all ratio=1.0, all "high" | Every `abs(s)/abs(s) = 1.0` | PASS |
| Score=0, best=0 | "low" | `best_score == 0` guard fires | PASS |
| Score=0, best>0 | ratio=0.0, "low" | `abs(0)/abs(5) = 0.0 < 0.40` | PASS |
| Negative zero (-0.0) | "low" | `abs(-0.0) = 0.0`, `0.0 == 0` is True (IEEE 754) | PASS |
| Missing score key | defaults to 0, "low" | `entry.get("score", 0)` -> 0 | PASS |
| Legacy int scores | arithmetic correct | `int` is subtype of `float` for `/` operator | PASS |

### 5. Does output format match plan spec? (line 290)

**PASS.** Plan spec (rd-08-final-plan.md:404-407):
```xml
- [DECISION] JWT token refresh flow -> path #tags:auth,jwt [confidence:high]
```

Implementation:
```python
print(f"- [{cat}] {safe_title} -> {safe_path}{tags_str} [confidence:{conf}]")
```

Format is identical. `conf` is always one of exactly three hardcoded strings ("high", "medium", "low"), so no injection risk from the annotation itself.

### 6. Backward compatibility

**PASS.** Verified across all potential consumers:

- **Existing tests:** All 33 tests pass. Tests use substring checks (`"use-jwt" in stdout`, `"<memory-context" in stdout`), not exact line format assertions. Appended `[confidence:*]` is transparent.
- **Skills (SKILL.md):** No regex or parsing logic that consumes `memory-context` output format found in `skills/`.
- **Commands:** No parsers found in `commands/` directory.
- **Other hooks:** No hooks parse the retrieval output.
- **LLM consumption:** `<memory-context>` XML is consumed by the main Claude model. The annotation is additive information. Per spec: "The main model naturally deprioritizes `[confidence:low]` entries."
- **Token cost:** ~15 extra tokens per prompt as spec predicted.

### 7. Legacy path: does mutating entry dicts cause issues? (lines 487-493)

**PASS.** The mutation pattern:
```python
for score, _, entry in top_entries:
    entry["score"] = score
    top_list.append(entry)
```

Analysis of dict lifecycle:
1. `entry` dicts created by `parse_index_line()` at line 373 (one fresh dict per index line)
2. Referenced in `entries[]` -> `scored[]` -> `final[]` -> `top_entries`
3. Mutation `entry["score"] = score` occurs at line 489
4. `_output_results()` called immediately after, then `main()` returns
5. No code reads `entries[]`, `scored[]`, or `final[]` after mutation point

**Verdict:** Safe. End-of-lifecycle enrichment with no downstream consumers.

### 8. Score semantics: FTS5 vs legacy path asymmetry

**PASS (with observation).** There is an asymmetry in pre-filtering that affects confidence distribution, but it is correct behavior:

**FTS5 path:** Results pass through `apply_threshold()` which applies a 25% noise floor:
- Filter: `abs(score) >= best_abs * 0.25`
- Minimum ratio entering `confidence_label`: 0.25
- Effective bands: [0.25, 0.40) = low (15%), [0.40, 0.75) = medium (35%), [0.75, 1.0] = high (25%)
- "Low" is narrow (15% of range) but still reachable and meaningful

**Legacy path:** No noise floor applied. Results are sorted and sliced by `max_inject`:
- Minimum possible ratio: any `score > 0` / best_score
- Effective bands: (0, 0.40) = low (wide), [0.40, 0.75) = medium, [0.75, 1.0] = high
- "Low" is a much wider band, correctly reflecting the legacy path's less precise scoring

**This asymmetry is intentional and correct.** FTS5's threshold already filters weak results, so confidence differentiates within a quality pool. Legacy's wider "low" band compensates for its cruder scoring mechanism.

**Gemini concurrence:** "The 25% pre-filter does not execute for Legacy path. Legacy scoring purely slices final[:max_inject] after sorting. Thus, the effective range for Legacy spans all the way down to >0, making 'low' a wide (0, 0.40) band."

---

## FTS5 Score Transformation Chain (Traced End-to-End)

Verified the complete data flow for the FTS5 path:

1. `query_fts()` -> raw BM25 `rank` as `score` (negative float, more negative = better)
2. `score_with_body()` -> `score = score - body_bonus` (0-3 subtracted, making more negative)
3. `score_with_body()` -> preserves `raw_bm25` for debugging
4. `apply_threshold()` -> sorts by score (most negative first), applies 25% noise floor, limits to `max_inject`
5. `_output_results()` -> `best_score = max(abs(score) for each entry)`
6. `confidence_label()` -> `ratio = abs(score) / abs(best_score)`

Confidence labels correctly reflect the **final** ranking order (including body bonus adjustments), not the raw BM25 scores. This is the desired behavior.

---

## Findings

### LOW: Legacy Path Entry Dict Mutation (line 489)

**Severity:** LOW
**Description:** The legacy path mutates shared entry dicts by adding `entry["score"] = score`. These dicts originate from `parse_index_line()` and are referenced in `entries`, `scored`, and `final` lists.
**Current risk:** None. Safe in current flow -- mutation occurs at function exit with no downstream readers.
**Future risk:** If `main()` is refactored to reuse `entries` after the legacy output path, the injected `"score"` key could cause unexpected behavior.
**Recommendation:** No action required. If the legacy path is ever extended, consider `{**entry, "score": score}` shallow copies.

### LOW: Redundant `abs(best_score)` in Function (line 168)

**Severity:** LOW (cosmetic)
**Description:** `best_score` is computed at line 280 as `max(abs(...), default=0)`, so it is already non-negative when passed to `confidence_label`. The `abs(best_score)` inside the function is redundant.
**Impact:** None. This is defense-in-depth that makes the function correct regardless of caller behavior.
**Recommendation:** Keep as-is. If the function is extracted or reused by other callers, the internal `abs()` prevents subtle bugs from unsigned assumptions.

### INFO: Minor Parameter Naming Deviation from Plan

**Severity:** INFO
**Plan:** `confidence_label(bm25_score: float, best_score: float)`
**Implementation:** `confidence_label(score: float, best_score: float)`
**Impact:** None. The implementation's naming is actually more accurate since the function handles both BM25 and legacy scores, not just BM25. This is an improvement over the plan.

### INFO: No Unit Tests for `confidence_label()`

**Severity:** INFO
**Description:** No unit tests exist specifically for `confidence_label()` or for verifying `[confidence:*]` annotations in output. The function was verified programmatically during this review.
**Recommendation:** Add unit tests in a future session covering: boundary ratios, zero scores, single result, all-same-score, and integration test verifying annotations appear in output.

---

## External Validation

### Gemini 3.1 Pro (via pal clink MCP)

Gemini performed an independent code review and concurred on all correctness points:

1. **abs() correctness:** Confirmed both scoring models are correctly unified via abs()
2. **Noise floor interaction:** Correctly identified FTS5 vs legacy asymmetry. Noted "Low" is a useful Pareto-like distribution for FTS5 path isolating borderline matches
3. **No score mixing:** Confirmed FTS5 and legacy paths are strictly mutually exclusive via early return/sys.exit(0)
4. **Float comparison safety:** Confirmed `best_score == 0` is safe -- SQLite BM25 and integer accumulations produce exact zeros; `max(..., default=0)` guarantees exact 0 fallback
5. **Additional findings:** Same redundant `abs(best_score)` and type hint observations
6. **Verdict:** "No bugs, regressions, security gaps, or critical performance overheads"

### Codex (via pal clink MCP)

Codex was unavailable (usage limit reached). Review proceeded with Gemini + independent manual analysis.

### Vibe Check Assessment

Validated the review approach as proportionate. Key insight: verify the `apply_threshold` noise floor interaction with `confidence_label` thresholds. This was confirmed as the most important correctness question and was verified in checklist item 8.

---

## Summary

| # | Finding | Severity | Action Required |
|---|---------|----------|----------------|
| 1 | Legacy path entry dict mutation | LOW | None (safe in current flow) |
| 2 | Redundant abs(best_score) | LOW | None (defense-in-depth) |
| 3 | Parameter naming deviation | INFO | None (improvement over plan) |
| 4 | No unit tests for confidence_label | INFO | Add in future session |

**Total LOC reviewed:** ~30 (lines 160-173, 279-291, 485-493)
**Bugs found:** 0
**Regressions:** 0 (33/33 tests pass)
**Deviations from plan:** 0 (naming change is an improvement)
**Security concerns:** 0 (annotation is hardcoded string, no user input in label)
