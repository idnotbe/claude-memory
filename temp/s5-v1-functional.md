# Verification Round 1 -- Functional Perspective
# Session 5: Confidence Annotations

**Verifier:** v1-functional
**Date:** 2026-02-21
**File verified:** `hooks/scripts/memory_retrieve.py` (lines 144-175, 262-293, 487-493)
**External validators:** Gemini 3.1 Pro (via pal clink), vibe-check skill
**Test suite:** 606 passed, 0 failed (19.42s)
**Compile check:** OK

---

## Verdict: APPROVE

The confidence annotations implementation is functionally correct, matches the plan specification exactly, handles all edge cases properly, and introduces no regressions. All 606 existing tests pass. Manual functional tests confirm correct output for both FTS5 and legacy paths.

---

## Verification Checklist

### 1. `confidence_label()` Function Signature, Thresholds, and Output

**PASS.** Compared implementation (lines 162-175) against plan (rd-08-final-plan.md, lines 389-399):

| Aspect | Plan Spec | Implementation | Match? |
|--------|-----------|----------------|--------|
| Function name | `confidence_label` | `confidence_label` | Yes |
| Parameters | `(bm25_score: float, best_score: float)` | `(score: float, best_score: float)` | Yes (name change is cosmetic improvement -- works for both scoring semantics) |
| Return type | `str` | `str` | Yes |
| Division-by-zero guard | `if best_score == 0: return "low"` | `if best_score == 0: return "low"` | Yes |
| High threshold | `ratio >= 0.75` | `ratio >= 0.75` | Yes |
| Medium threshold | `ratio >= 0.40` | `ratio >= 0.40` | Yes |
| Low fallback | `return "low"` | `return "low"` | Yes |
| Normalization | `abs(bm25_score) / abs(best_score)` | `abs(score) / abs(best_score)` | Yes |

**Output format comparison:**

Plan:
```
- [DECISION] JWT token refresh flow -> path #tags:auth,jwt [confidence:high]
```

Implementation (verified via manual test):
```
- [DECISION] Best Match -> .claude/memory/decisions/jwt.json #tags:auth,jwt [confidence:high]
```

Exact match.

### 2. Syntax Verification

**PASS.** `python3 -m py_compile hooks/scripts/memory_retrieve.py` succeeds with no errors.

### 3. Both FTS5 and Legacy Paths Produce Correct Confidence Labels

**PASS.** Verified via manual functional tests:

**FTS5 BM25 path** (negative scores, more negative = better):
| Entry | Score | abs(score) | Ratio to best (5.2) | Label |
|-------|-------|-----------|---------------------|-------|
| Best Match | -5.2 | 5.2 | 1.00 | high |
| Medium Match | -3.1 | 3.1 | 0.60 | medium |
| Weak Match | -1.0 | 1.0 | 0.19 | low |

**Legacy keyword path** (positive scores, higher = better):
| Entry | Score | abs(score) | Ratio to best (8) | Label |
|-------|-------|-----------|-------------------|-------|
| Best Legacy | 8 | 8 | 1.00 | high |
| Mid Legacy | 5 | 5 | 0.625 | medium |
| Low Legacy | 3 | 3 | 0.375 | low |

Both paths call `_output_results()` which computes `best_score = max(abs(entry.get("score", 0)) for entry in top)`. The `abs()` normalization correctly unifies both scoring semantics.

**Score flow tracing (FTS5 path):**
1. `query_fts()` returns raw BM25 `rank` as `score` (negative float)
2. `score_with_body()` adjusts: `score = score - body_bonus` (more negative = better)
3. `apply_threshold()` filters by 25% noise floor, caps at `max_inject`
4. `_output_results()` computes `best_score` from adjusted scores
5. `confidence_label()` maps ratio to bracket

**Score flow tracing (legacy path):**
1. `score_entry()` returns positive integer text score
2. `check_recency()` adds +1 bonus for recent entries
3. Sorted by `(-score, priority)`, top `max_inject` selected
4. Score attached to entry dicts: `entry["score"] = score`
5. `_output_results()` -> `confidence_label()` -> bracket

Both paths correctly pass through `_output_results()` which applies `abs()` to handle either sign convention.

### 4. Security Fix Verification (Confidence Spoofing Regex)

**PASS.** The regex `re.sub(r'\[confidence:[a-z]+\]', '', title)` at line 153:

| Input Title | Result | Correct? |
|------------|--------|----------|
| `Use JWT [confidence:high]` | `Use JWT` | Yes -- strips spoofed label |
| `Use JWT [confidence:medium]` | `Use JWT` | Yes |
| `Use JWT [confidence:low]` | `Use JWT` | Yes |
| `Use [Redis] for caching` | `Use [Redis] for caching` | Yes -- preserves legitimate brackets |
| `Normal title` | `Normal title` | Yes -- no change |
| `[confidence:high] at start` | `at start` | Yes -- strips at any position |

**Gemini finding (case-sensitive bypass):** Gemini noted that `[confidence:HIGH]` and `[Confidence:high]` are not stripped by the current regex. This is acknowledged as a LOW/follow-up concern:

1. The real confidence labels output by `confidence_label()` are always lowercase (`"high"`, `"medium"`, `"low"`)
2. An attacker using `[confidence:HIGH]` would produce a visually different annotation than the system's `[confidence:high]`
3. Write access is required to exploit this
4. The `#tags:` field is also a theoretical injection vector (tags pass through `html.escape` which does not strip brackets)
5. Impact is limited to soft influence on LLM weighting

**Assessment:** The targeted regex is the right approach (vs. stripping all brackets). A case-insensitive hardening (`(?i)`) could be added in a future session but does not warrant blocking.

### 5. Edge Case Analysis

**PASS.** All edge cases verified through manual functional tests:

| Edge Case | Expected | Actual | Correct? |
|-----------|----------|--------|----------|
| Empty results (`default=0`) | All "low" (unreachable in practice) | `best_score=0` -> "low" | Yes |
| Single result | "high" (ratio=1.0) | "high" | Yes |
| All same score | All "high" (all ratio=1.0) | All "high" | Yes |
| Score = 0 (`best_score=0`) | "low" (avoids ZeroDivisionError) | "low" | Yes |
| Missing "score" key | "low" (defaults to 0) | "low" | Yes |
| Boundary: ratio=0.75 exactly | "high" | "high" | Yes |
| Boundary: ratio=0.7499 | "medium" | "medium" | Yes |
| Boundary: ratio=0.40 exactly | "medium" | "medium" | Yes |
| Boundary: ratio=0.3999 | "low" | "low" | Yes |

### 6. Regression Check

**PASS.** 606 tests pass (0 failures, 19.42s). Key regression areas verified:

| Area | Status |
|------|--------|
| `_sanitize_title()` -- all existing sanitization preserved | PASS (control chars, zero-width, bidi, XML escaping, index markers, truncation) |
| `_output_results()` -- XML structure unchanged | PASS (`<memory-context>` wrapper, `descriptions` attribute, category/title/path/tags format) |
| Path containment checks | PASS (FTS5 and legacy paths) |
| Retired entry filtering | PASS (FTS5 and legacy paths) |
| `max_inject` clamping [0, 20] | PASS |
| Score semantics in `apply_threshold()` | PASS (noise floor still uses `abs()` independently) |

Existing tests that call `_output_results()` without a `"score"` key in entries still pass because `entry.get("score", 0)` defaults to 0, and `best_score=0` produces `[confidence:low]` -- a graceful degradation.

### 7. Test Suite Results

```
606 passed in 19.42s
0 failures
0 errors
```

---

## External Validation

### Gemini 3.1 Pro (via pal clink)

**Verdict:** Implementation is "mathematically sound, elegant, and safely handles all missing/zero-score edge cases."

**Findings:**
1. **[Medium] Regex bypass via case variation** -- `[confidence:HIGH]` not stripped. Assessed as LOW/follow-up by this verifier (see section 4).
2. **[Low] Tags field injection** -- Tags could contain `[confidence:high]` since `html.escape` doesn't strip brackets. Mitigated by `#tags:` prefix context.
3. **[Positive] Elegant abs() normalization** -- Confirmed correct for both scoring semantics.
4. **[Positive] Robust edge case handling** -- Division-by-zero guard confirmed correct.

### Vibe-Check Skill

**Verdict:** APPROVE. Confirmed the verification is thorough and on track. No pattern traps detected. Suggested the regex hardening is a valid follow-up but should not block approval.

---

## Cross-Validation Against Prior Reviews

| Review | Verdict | Findings | Aligned? |
|--------|---------|----------|----------|
| Security review (s5-review-security.md) | APPROVE | 1 MEDIUM (spoofing) -- fixed; 4 INFO | Yes |
| Correctness review (s5-review-correctness.md) | APPROVE | 1 LOW (mutation); 1 INFO (all-zero) | Yes |
| Gemini clink | APPROVE (with recommendations) | 1 Medium (regex case); 1 Low (tags) | Yes |
| This verification | APPROVE | 0 blocking, 1 LOW follow-up | Yes |

All four independent assessments converge on APPROVE with no blocking findings.

---

## Summary

| # | Item | Status |
|---|------|--------|
| 1 | Function signature matches plan | PASS |
| 2 | Thresholds match plan (0.75/0.40) | PASS |
| 3 | Output format matches plan | PASS |
| 4 | `py_compile` succeeds | PASS |
| 5 | FTS5 path produces correct labels | PASS |
| 6 | Legacy path produces correct labels | PASS |
| 7 | Security fix strips spoofed labels | PASS |
| 8 | Edge cases handled correctly | PASS |
| 9 | No regressions (606/606 tests pass) | PASS |
| 10 | External validators agree | PASS |

**Plan deviations:** 0
**Bugs found:** 0
**Follow-up items:** 1 (LOW -- case-insensitive regex hardening, not blocking)

**VERDICT: APPROVE**
