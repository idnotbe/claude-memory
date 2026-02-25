# P3 Action #1 Verification: confidence_label abs_floor + cluster_count

**Verifier:** Opus (primary) + Gemini 3.1 Pro (external) + Claude Sonnet 4.6 (external)
**Date:** 2026-02-25
**Status:** PASS with 1 medium advisory finding

---

## Scope

- `hooks/scripts/memory_retrieve.py`: `confidence_label()` function (lines 172-206)
- `hooks/scripts/memory_retrieve.py`: config parsing for `confidence_abs_floor` (lines 479-484)
- `hooks/scripts/memory_retrieve.py`: all call sites passing abs_floor (lines 349, 578, 637, 787)
- `tests/test_memory_retrieve.py`: `TestConfidenceLabelAbsFloor` class (lines 701-758)
- `assets/memory-config.default.json`: new keys `confidence_abs_floor`, `cluster_detection_enabled`

---

## 1. Opus Analysis (Primary)

### 1.1 Correctness: abs_floor logic

**CORRECT.** Line 198:
```python
floor_capped = abs_floor > 0 and abs(best_score) < abs_floor
```

- Strictly less than (`<`) is intentional: when `abs(best_score) == abs_floor`, the score exactly meets the floor, so no cap applies. This matches the docstring semantics.
- The `abs_floor > 0` guard ensures default `abs_floor=0.0` disables the entire check (short-circuit evaluation).
- `floor_capped` only affects the `ratio >= 0.75` branch (high -> medium demotion). Medium and low results are unaffected.

### 1.2 Backward Compatibility

**PRESERVED.** Default parameters `abs_floor=0.0, cluster_count=0` ensure:
- `abs_floor=0.0`: `abs_floor > 0` is `False`, so `floor_capped` is always `False`. No behavior change.
- `cluster_count=0`: Parameter accepted but unused in the function body. No behavior change.
- `memory-config.default.json` sets `"confidence_abs_floor": 0.0` (disabled by default).
- Tests `test_abs_floor_zero_preserves_legacy` and `test_both_params_default_preserves_legacy` explicitly verify this.

### 1.3 Config Parsing (lines 479-484)

```python
raw_floor = retrieval.get("confidence_abs_floor", 0.0)
try:
    abs_floor = max(0.0, float(raw_floor))
except (ValueError, TypeError, OverflowError):
    abs_floor = 0.0
```

**Handles correctly:**
- String inputs like `"invalid"` -> ValueError caught -> 0.0
- `None` -> TypeError caught -> 0.0
- Lists/dicts -> TypeError caught -> 0.0
- Negative numbers -> `max(0.0, -5.0)` = 0.0
- `True`/`False` -> `float(True)` = 1.0, `float(False)` = 0.0 (acceptable)
- `"3.0"` string -> `float("3.0")` = 3.0 (correct)
- `float('nan')` -> `max(0.0, nan)` = 0.0 (safe due to argument order in CPython)
- `"nan"` string -> `float("nan")` = nan -> `max(0.0, nan)` = 0.0 (same)

**ADVISORY (Medium): `"inf"` string or `float('inf')` not caught:**
- `float("inf")` does not raise ValueError.
- `max(0.0, inf)` = inf.
- At line 198: `inf > 0` is `True`, and `abs(any_finite_score) < inf` is `True`.
- Result: ALL high-confidence results silently capped to "medium".
- Practical risk: Low. JSON has no `Infinity` literal, so `float('inf')` cannot come from `json.load()` directly. The string `"inf"` in JSON config is the only attack vector. This requires local config file access.
- **Recommendation:** Add `math.isfinite()` guard after conversion:
  ```python
  abs_floor = max(0.0, float(raw_floor))
  if not math.isfinite(abs_floor):
      abs_floor = 0.0
  ```

### 1.4 cluster_count Parameter

**CORRECT.** The `cluster_count` parameter:
- Has default value 0 (disabled).
- Is documented in the docstring as "currently unused" with clear rationale.
- Is never referenced in the function body -- it exists only as a placeholder for future activation.
- All call sites either omit it (defaulting to 0) or pass `cluster_count=0` explicitly (line 350).

### 1.5 Edge Cases (Manual Verification)

| Case | Result | Correct? |
|------|--------|----------|
| `confidence_label(NaN, 5.0)` | "low" | Yes (NaN ratio fails all >= checks) |
| `confidence_label(5.0, NaN)` | "low" | Yes (NaN != 0, ratio = NaN, falls through) |
| `confidence_label(Inf, 5.0)` | "high" | Acceptable (ratio = Inf, >= 0.75 is True) |
| `confidence_label(Inf, Inf)` | "low" | Yes (Inf/Inf = NaN, falls through) |
| `confidence_label(5.0, Inf)` | "low" | Yes (5/Inf = 0.0, below 0.40) |
| `confidence_label(-0.0, -0.0)` | "low" | Yes (-0.0 == 0 is True, early return) |
| `confidence_label(-0.0, 5.0)` | "low" | Yes (abs(-0.0)/abs(5) = 0.0, below 0.40) |
| `confidence_label(3.0, 3.0, abs_floor=NaN)` | "high" | Safe (NaN > 0 is False, floor disabled) |
| `confidence_label(3.0, 3.0, abs_floor=Inf)` | "medium" | See advisory above |
| `confidence_label(3.0, 3.0, abs_floor=-1.0)` | "high" | Safe (-1.0 > 0 is False, floor disabled) |
| `confidence_label(0.001, 0.001, abs_floor=0.001)` | "high" | Correct (not strictly < floor) |
| `confidence_label(0.0009, 0.0009, abs_floor=0.001)` | "medium" | Correct (strictly < floor, capped) |

### 1.6 Security

- `confidence_label()` is pure arithmetic with no string operations or I/O.
- `abs_floor` flows from config JSON (user-controlled file) through `float()` conversion with exception handling.
- No user content (titles, tags, prompt text) flows into `confidence_label()` -- only numeric scores.
- The only attack surface is config manipulation (setting `confidence_abs_floor` to `"inf"`), which requires local file access.

### 1.7 Call Site Consistency

All 4 call sites verified:
- Line 349 (`_output_results`): passes `abs_floor=abs_floor, cluster_count=0` -- correct.
- Line 578 (FTS5 search logging): passes `abs_floor=abs_floor` -- correct (cluster_count defaults to 0).
- Line 637 (FTS5 inject logging): passes `abs_floor=abs_floor` -- correct.
- Line 787 (legacy inject logging): passes `abs_floor=abs_floor` -- correct.

### 1.8 No Regressions

All 90 tests pass, including:
- 17 original `TestConfidenceLabel` tests (lines 494-563)
- 11 new `TestConfidenceLabelAbsFloor` tests (lines 701-758)

---

## 2. Gemini 3.1 Pro Analysis Summary

**Findings (3 items):**

1. **Medium: Config parsing allows NaN/Inf to leak without warnings** (lines 479-484)
   - `float("nan")` and `float("inf")` do not raise ValueError. NaN is accidentally safe due to `max()` argument order; Inf silently passes through and caps all results to "medium".
   - Recommends explicit `math.isnan()`/`math.isinf()` guard after conversion.

2. **Low: Implicit handling of NaN/Inf in confidence_label** (lines 192-206)
   - NaN inputs return "low" but only because NaN fails all `>=` comparisons. Inf score returns "high" via implicit Inf >= 0.75.
   - Recommends explicit guards, though acknowledges current behavior is safe.

3. **Low: Missing boundary test coverage for floating-point edge cases** (lines 701-758)
   - TestConfidenceLabelAbsFloor omits NaN/Inf/negative-zero edge case assertions.
   - Notes: the parent TestConfidenceLabel class (lines 494-563) DOES cover NaN, Inf, and negative zero, so coverage exists but not in the abs_floor-specific test class.

**Positive practices identified:**
- Strictly less-than operator at line 198 is "semantically perfect."
- Negative-zero interception at line 193 is robust.
- Domain-agnostic abs() normalization is elegant.

---

## 3. Claude Sonnet 4.6 Analysis Summary

**Findings (3 items, same convergence as Gemini):**

1. **Medium: `float("inf")` passes config parsing silently** (lines 479-484)
   - Sets `abs_floor=inf`, permanently caps all high-confidence results to "medium" with no warning.
   - Recommends `math.isfinite()` guard.

2. **Low: NaN handling is safe but accidental** (argument-order-dependent in `max()`)
   - `max(0.0, NaN)` = 0.0 in CPython but not guaranteed by specification. If arguments were swapped, NaN would propagate.

3. **Low: Missing tests for Inf, NaN, very large values, score > best_score, direct negative abs_floor**
   - Suggests additional test cases for completeness.

**Also noted:**
- abs_floor logic correctness confirmed.
- Backward compatibility confirmed.
- Security risk is low (local config file access required).

---

## 4. Codex Analysis

**Unavailable** -- OpenAI Codex CLI returned a usage limit error. Codex review was not obtained.

---

## 5. Consensus

### All Clear (Core Logic)
- abs_floor logic is **correct** (all 3 reviewers agree)
- Strictly less-than comparison at line 198 is **semantically correct** (all 3 agree)
- Backward compatibility is **fully preserved** (all 3 agree)
- cluster_count=0 design is **correct** (all 3 agree)
- No regressions detected (90/90 tests pass)
- Security is adequate (no injection vectors)

### Advisory Finding (Unanimous)

**[MEDIUM] Config parsing does not reject `"inf"` string for confidence_abs_floor**
- **File:** `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`
- **Line:** 482
- **Impact:** If user sets `"confidence_abs_floor": "inf"` in config JSON, all high-confidence results are silently capped to "medium" with no warning.
- **Practical risk:** Low. Requires deliberate config manipulation. JSON has no native Infinity type.
- **Fix:** Add `math.isfinite()` guard after line 482:
  ```python
  abs_floor = max(0.0, float(raw_floor))
  if not math.isfinite(abs_floor):
      abs_floor = 0.0
  ```
- **Consensus:** All 3 reviewers (Opus, Gemini, Sonnet) independently identified this same issue.

### Minor Advisory (2 of 3 reviewers)

**[LOW] NaN safety in `max(0.0, float(raw_floor))` is argument-order-dependent**
- CPython behavior: `max(0.0, NaN)` = 0.0 but `max(NaN, 0.0)` = NaN.
- Currently safe but fragile. The `math.isfinite()` fix above also resolves this.

---

## 6. Verdict

**PASS** -- The core `confidence_label()` abs_floor + cluster_count implementation is correct, backward-compatible, well-tested, and secure. One medium config parsing hardening opportunity identified (Inf string not rejected). This is an advisory finding, not a blocking issue, as the practical attack surface is minimal (local config file with string "inf").
