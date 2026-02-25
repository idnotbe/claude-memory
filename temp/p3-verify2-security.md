# P3 Verification Round 2: Security & Operations

**Scope:** Actions #1-#3 changes in `memory_retrieve.py`
**Perspective:** Security and Operations (complementary to Round 1 correctness review)
**Date:** 2026-02-26
**Test results:** 90/90 passed (`pytest tests/test_memory_retrieve.py -v`)

---

## Security Checklist

### 1. Config injection: `confidence_abs_floor` float parsing

**Status: PASS (with minor note)**

- **NaN bypass:** `max(0.0, float('nan'))` returns `0.0` in CPython (NaN comparisons return False, so max keeps the first argument). This safely disables the feature. **No bypass.**
- **Overflow/Inf:** `float("inf")` or JSON number `1e309` produces `inf`. Then `max(0.0, inf) = inf`. This sets `abs_floor=inf`, which caps ALL results to "medium" maximum. **Impact: degraded UX (no "high" confidence), not a security breach.** Severity: LOW -- attacker with config write access could also just set `retrieval.enabled=false` for greater impact.
- **Negative values:** `max(0.0, float(-5.0)) = 0.0`. Negative values are clamped to 0.0. **Safe.**
- **Non-numeric strings:** Caught by `except (ValueError, TypeError, OverflowError)` at line 483, falls back to `abs_floor = 0.0`. **Safe.**

**Lines reviewed:** 479-484

### 2. Config injection: `output_mode` validation

**Status: PASS**

Whitelist approach at line 487: `if raw_mode in ("legacy", "tiered")`. Any other string value (including injection attempts) silently defaults to `"legacy"` (the initial value at line 456). In `_output_results()`, the `else` branch (line 383) handles any value that is not `"tiered"`, providing defense-in-depth.

**Lines reviewed:** 456, 486-488, 376-384

### 3. Config injection: `cluster_detection_enabled` bool() wrapping

**Status: PASS**

Line 492: `bool(retrieval.get("cluster_detection_enabled", False))`. The `bool()` function in Python converts ANY value to True/False deterministically:
- `bool("false")` = True (string "false" is truthy) -- but this is a parsed-but-unused config key, so no functional impact.
- The value is stored in `_cluster_detection_enabled` (prefixed with underscore) and never used in any code path.

**Lines reviewed:** 489-492

### 4. XML injection via tiered output: `<memory-compact>` format

**Status: PASS**

All four user-controlled data fields in the output are properly escaped:

| Field | Escaping | Line | Notes |
|-------|----------|------|-------|
| Title | `_sanitize_title()` | 363 | Strips control chars, Cf/Mn unicode, escapes `&<>"` |
| Path | `html.escape()` | 373 | Python 3 `html.escape` defaults to `quote=True` |
| Tags | Cf/Mn strip + `html.escape()` | 368-369 | Each tag individually escaped |
| Category | `html.escape()` | 374 | Regex `[A-Z_]+` ensures only safe chars; escape is defense-in-depth |

The `<memory-compact>` element (line 380) uses the exact same escaping pipeline as `<result>` (line 378), just a different tag name. **No new injection surface.**

**Lines reviewed:** 362-384

### 5. Hint injection: `_emit_search_hint()`

**Status: PASS**

Function at lines 299-313 is fully hardcoded. The `reason` parameter is compared against string literals (`"all_low"`, `"medium_present"`), with unrecognized values falling through to the `else` branch (no_match default). No user-controlled data is interpolated into output. The `<topic>` placeholder in hint text is pre-escaped as `&lt;topic&gt;`.

**Lines reviewed:** 299-313

### 6. Prompt injection via `</memory-note>` in title

**Status: PASS**

`_sanitize_title()` at line 168 escapes `<` to `&lt;` and `>` to `&gt;`. Tested explicitly:
- Input: `Title</memory-note>INJECTED` -> Output: `Title&lt;/memory-note&gt;INJECTED`
- Input: `Title</memory-context>EVIL` -> Output: `Title&lt;/memory-context&gt;EVIL`
- Input: `Title</memory-compact>EVIL` -> Output: `Title&lt;/memory-compact&gt;EVIL`

All closing tag injection attempts are neutralized.

### 7. Description attribute injection in `<memory-context>`

**Status: PASS**

Line 336: Category keys sanitized via `re.sub(r'[^a-z_]', '', cat_key.lower())` -- strips everything except lowercase letters and underscores. Empty results skipped (line 337-338).

Line 335: Description values sanitized via `_sanitize_title(desc)` which escapes `"` to `&quot;`, preventing attribute boundary breakout. Pre-truncated to 500 chars at line 509.

**Lines reviewed:** 331-341, 503-509

---

## Operations Checklist

### 5. Backward compatibility: legacy mode byte-identical output

**Status: PASS**

With defaults (`abs_floor=0.0`, `output_mode="legacy"`):
- `abs_floor=0.0`: The floor check condition `abs_floor > 0 and abs(best_score) < abs_floor` evaluates to `False` because `0.0 > 0` is `False`. Floor capping never activates. Confidence labels are computed identically to pre-change code.
- `output_mode="legacy"`: The `if output_mode == "tiered"` branches at lines 357 and 376 are never taken. Every entry goes through the `else` branch (line 383) which outputs `<result>` elements -- identical to pre-change format.
- Pre-computing labels (lines 347-354) is a read-only operation that does not affect the output path in legacy mode.

**Verified:** Default config produces functionally identical output.

### 6. Performance: pre-computing labels

**Status: PASS -- negligible**

The extra computation is:
- 1 pass to compute `labels` list from `top` entries (line 347-350)
- 3 generator comprehensions: `any_high`, `any_medium`, `all_low` (lines 352-354)

Total: 4 passes over a list capped at `max_inject` (maximum 20 entries, clamped at line 471). This adds approximately 80 comparisons in the worst case, which is negligible compared to FTS5 query execution, file I/O, and potential judge API calls.

### 7. Rollback safety: independent feature disable

**Status: PASS**

| Feature | Disable Config | Default | Effect |
|---------|---------------|---------|--------|
| abs_floor | `confidence_abs_floor: 0.0` | 0.0 | Floor check completely disabled |
| tiered output | `output_mode: "legacy"` | "legacy" | All tiered branches skipped |
| cluster detection | `cluster_detection_enabled: false` | false | Parsed but unused |
| search hints | (no dedicated toggle) | N/A | Only fires in tiered mode or no-results path |

Each feature can be independently disabled by setting its config to the default value. No feature has dependencies on other new features.

### 8. Error handling: corrupt config values

**Status: PASS**

| Config Key | Corrupt Value | Handling | Line |
|-----------|---------------|----------|------|
| `confidence_abs_floor` | Non-numeric string | `except (ValueError, TypeError, OverflowError)` -> `0.0` | 483-484 |
| `confidence_abs_floor` | `null` / None | `float(None)` -> `TypeError` caught -> `0.0` | 483-484 |
| `confidence_abs_floor` | `"inf"` string | `float("inf")` -> `max(0.0, inf)` -> `inf` (caps to medium) | 482 |
| `confidence_abs_floor` | JSON `1e309` | Parsed as `inf` by Python JSON -> same as above | 482 |
| `output_mode` | Any non-whitelist string | Silently defaults to `"legacy"` | 486-488 |
| `output_mode` | `null` / None | `None not in ("legacy", "tiered")` -> stays `"legacy"` | 487 |
| `cluster_detection_enabled` | Any type | `bool()` converts to True/False; unused anyway | 492 |

---

## Edge Cases

### 9. Empty results in tiered mode: `all([]) = True`

**Status: PASS (cosmetic note)**

When `_output_results()` receives an empty `top` list:
- `best_score = max((), default=0)` = 0
- `labels = []` (empty list)
- `all_low = all(l == "low" for l in [])` = `True` (vacuous truth)
- Tiered mode emits `<memory-note>` "all_low" hint and returns early

**Impact:** In practice, callers never invoke `_output_results([])` -- the FTS5 path checks `if results:` (line 590) and the legacy path checks `if not final:` (line 766). However, if it were called with empty list, the "all_low" hint is a reasonable degradation (better than an empty `<memory-context>` wrapper which legacy mode would produce).

**Recommendation:** No action needed. If desired, could add `if not top: return` guard, but callers already handle this.

### 10. Mixed NaN scores

**Status: PASS**

If some entries have NaN scores:
- `max((abs(entry.get("score", 0)) for entry in top), default=0)`: If any entry has NaN score, `abs(NaN) = NaN`. Python's `max()` with NaN follows comparison rules -- `NaN > x` is always False, so NaN values are "transparent" in max computation. If all values are NaN, max returns the first NaN.
- `confidence_label(NaN, best_score)`: `abs(NaN)/abs(best_score) = NaN`. Then `NaN >= 0.75` is False, `NaN >= 0.40` is False. Returns `"low"`.
- `confidence_label(score, NaN)`: `abs(score)/abs(NaN) = NaN`. Same logic. Returns `"low"`.
- `confidence_label(NaN, 0)`: `best_score == 0` check triggers first. Returns `"low"`.

**Existing test:** `test_nan_degrades_to_low` confirms NaN -> "low". All NaN paths degrade to "low" confidence, which is the safest default (conservative).

### 11. Very large abs_floor

**Status: PASS (by design)**

`abs_floor=999999` -> `abs(best_score) < 999999` is True for any realistic score -> `floor_capped = True` -> all "high" results capped to "medium". This is the intended behavior: a very high floor means "I consider all these matches weak." The worst case is that all results display as "medium" instead of "high", which is a UX degradation, not a security issue.

The attack surface for setting extreme abs_floor values is the same as setting `max_inject=0` (requires config file write access), and the impact is strictly less severe (results still appear, just with reduced confidence labels).

---

## Summary

| # | Check | Status | Severity |
|---|-------|--------|----------|
| 1 | Config injection: abs_floor float parsing | PASS | Note: `"inf"` string or JSON `1e309` produces inf -> caps to medium |
| 2 | Config injection: output_mode validation | PASS | Whitelist with safe fallback |
| 3 | Config injection: cluster_detection bool() | PASS | Unused, no impact |
| 4 | XML injection: `<memory-compact>` escaping | PASS | All 4 fields properly escaped |
| 5 | Hint injection: `_emit_search_hint()` | PASS | Fully hardcoded, no user data |
| 6 | Prompt injection: `</memory-note>` in title | PASS | Angle brackets escaped to entities |
| 7 | Description attribute injection | PASS | Key regex + title sanitization |
| 5b | Backward compatibility: legacy mode | PASS | Byte-identical with defaults |
| 6b | Performance: label pre-computation | PASS | Negligible (~80 comparisons max) |
| 7b | Rollback safety: independent disable | PASS | Each feature has config toggle |
| 8 | Error handling: corrupt config | PASS | All paths have safe fallbacks |
| 9 | Empty results tiered mode | PASS | Cosmetic: shows "all_low" hint (callers prevent this) |
| 10 | Mixed NaN scores | PASS | Degrades to "low" (conservative) |
| 11 | Very large abs_floor | PASS | By design: caps to "medium" max |

**Overall: PASS** -- No security vulnerabilities found. One minor hardening opportunity identified (clamping `abs_floor` to finite values with `math.isfinite()` check) but severity is LOW and the current behavior (capping to medium) is not exploitable.
