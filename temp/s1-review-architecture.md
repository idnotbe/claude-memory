# Session 1 Architecture Review

**Date:** 2026-02-21
**Reviewer:** reviewer-architecture (Opus 4.6)
**Reviewed:** Session 1 implementation in `hooks/scripts/memory_retrieve.py`
**External validation:** Gemini 3.1 Pro (via pal clink, codereviewer role)
**Status:** APPROVED WITH MEDIUM FINDINGS -- no blockers, safe to proceed to Session 2

---

## 1. Plan vs Implementation Gap Analysis

### 1a. Dual Tokenizer

**Plan spec (Phase 1a):**
```python
def tokenize(text: str, legacy: bool = False) -> set[str]:
```
Default `legacy=False` (compound). All fallback callers must use `legacy=True`.

**Implementation:** Matches plan exactly. All 3 call sites in production code use `legacy=True`:
- Line 102: `score_entry()` title tokenization
- Line 351: `main()` prompt tokenization
- Line 359: `main()` description tokenization

**Verdict:** CORRECT. The implementer also correctly applied `legacy=True` to `main()` prompt and description tokenization (lines 351, 359), which the plan only explicitly required for `score_entry()` and `score_description()`. The rationale is sound: prompt tokens are compared against title tokens via set intersection in `score_entry()`, so both must use the same tokenizer to avoid scoring regression.

### 1b. Body Content Extraction

**Plan spec:** `BODY_FIELDS` dict with 6 categories, `extract_body_text()` function.

**Implementation:** Matches plan exactly for field mappings. One improvement over the plan: the implementer added `isinstance(content, dict)` guard (line 230) that the plan's code lacked. The plan's `content.get(field)` would crash on non-dict content values.

**Verdict:** CORRECT. The non-dict guard is a good defensive addition.

### 1c. FTS5 Availability Check

**Plan spec:** `sqlite3.OperationalError` catch.

**Implementation:** Uses `except Exception` instead (line 259). This is a deliberate widening to also catch `ImportError` when sqlite3 itself is missing.

**Verdict:** CORRECT. The broader exception is more robust. The plan's `sqlite3.OperationalError` would throw `NameError` if `import sqlite3` failed. The implementer's decision to use `except Exception` handles both failure modes cleanly.

### 1d. Summary

| Item | Plan Match | Deviations |
|------|-----------|------------|
| `_LEGACY_TOKEN_RE` | Exact | None |
| `_COMPOUND_TOKEN_RE` | Exact | None |
| `tokenize()` signature | Exact | None |
| Call site updates | Extended | Prompt + desc also use legacy=True (correct) |
| `BODY_FIELDS` | Exact | None |
| `extract_body_text()` | Improved | Added non-dict content guard |
| `HAS_FTS5` | Improved | Broader exception handling |

---

## 2. Session 2 Readiness

### 2a. Will `tokenize(text)` (default compound) work for `build_fts_query()`?

**YES.** The default `legacy=False` path produces compound tokens (`user_id`, `react.fc`, `rate-limiting`), which is exactly what `build_fts_query()` needs for its smart wildcard logic:
- Compound tokens -> exact phrase match: `"user_id"`
- Simple tokens -> prefix wildcard: `"auth"*`

The compound tokenizer regex `[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+` correctly handles all documented test cases. Session 2 code will call `tokenize(user_prompt)` (default=compound) for FTS5 query construction.

### 2b. Will `extract_body_text()` integrate with `score_with_body()`?

**YES.** The function returns a plain string (truncated to 2000 chars) ready for tokenization. Session 2's `score_with_body()` will call:
```python
body_text = extract_body_text(data)
body_tokens = tokenize(body_text)  # compound tokenizer for FTS5 path
```

All 6 category types are covered. Edge cases (empty content, non-dict content, unknown category) return empty string. Clean integration surface.

### 2c. Will `HAS_FTS5` cleanly gate FTS5 vs fallback?

**YES.** The boolean flag is set at module level during import. Session 2's `main()` restructuring will use:
```python
if HAS_FTS5 and match_strategy == "fts5_bm25":
    # FTS5 path
else:
    # Legacy keyword path (preserved, unchanged)
```

One note: the FTS5 check runs at import time, which means it executes during test imports too. This is fine -- sqlite3 FTS5 is available on this system, and the check is fast (<1ms). If FTS5 were unavailable, the stderr warning would appear during test collection, but tests would still pass.

### 2d. Session 2 Risk Assessment

**RISK: LOW.** All three foundation pieces are clean, well-tested integration surfaces. No blockers for proceeding.

---

## 3. API Design Analysis

### 3a. `tokenize(text, legacy=False)` -- Boolean Flag Concern

**Finding: MEDIUM**

Both Gemini 3.1 Pro and my own analysis agree: the boolean flag pattern has a design smell. The concerns:

1. **Unused default:** The default `legacy=False` is currently unused by all production callers. Every call site passes `legacy=True`. This inverts the typical expectation that the default represents the common case.

2. **Boolean blindness:** At call sites, `tokenize(text, legacy=True)` is less self-documenting than `tokenize_legacy(text)` or `tokenize(text, pattern=_LEGACY_TOKEN_RE)`.

3. **Test compatibility:** All 12 test calls to `tokenize()` across 3 test files (`test_memory_retrieve.py`, `test_memory_candidate.py`, `test_adversarial_descriptions.py`) use `tokenize()` **without the `legacy` parameter**. This means they get the **new compound behavior** (default `legacy=False`). This is a **silent behavior change** for tests -- though because compound tokenization is a superset of legacy tokenization for simple words, these tests still pass. But it means tests are now exercising the compound tokenizer path, not the legacy path that production code uses.

**However, this is NOT a blocker because:**
- The plan explicitly specifies `legacy: bool = False` as the signature
- The default being compound-mode is correct for Session 2: `build_fts_query()` will call `tokenize(text)` without the flag
- Tests passing with compound mode is actually useful -- it validates the compound tokenizer on existing test cases
- Changing the API now would deviate from the verified plan

**Alternative designs considered (for future sessions if desired):**

| Option | Pros | Cons |
|--------|------|------|
| A. `tokenize(text, legacy=False)` (current) | Matches plan exactly; single function | Boolean flag; unused default |
| B. `tokenize(text)` + `tokenize_legacy(text)` | Self-documenting; no boolean | Two functions for same logic |
| C. `tokenize(text, pattern=_LEGACY_TOKEN_RE)` | Flexible; DI pattern; default=legacy | Exposes regex internals; callers need to know patterns |
| D. `tokenize_words(text)` + `tokenize_compounds(text)` | Behavior-descriptive names | Bigger rename; no "legacy" concept |

Gemini recommended Option C or D. My assessment: the current implementation (Option A) is adequate for the plan's goals. If the API is revisited in Session 2 or 3, Option B is the cleanest balance. But this is not worth changing now.

**Recommendation:** Accept as-is. Note for Session 2 that the default behavior is compound tokenization and tests exercise that path.

### 3b. BODY_FIELDS as Module-Level Dict

**Finding: POSITIVE (no issue)**

Module-level constant dict is the correct Python pattern. Gemini 3.1 Pro confirmed this is optimal -- avoids re-allocation on every call. Uppercase naming communicates immutability. No change needed.

---

## 4. Code Conventions

### 4a. Naming Consistency

- `_LEGACY_TOKEN_RE` / `_COMPOUND_TOKEN_RE`: Private module constants, consistent with existing `_INDEX_RE`, `_DEEP_CHECK_LIMIT`, `_RECENCY_DAYS`.
- `BODY_FIELDS`: Public constant, consistent with existing `STOP_WORDS`, `CATEGORY_PRIORITY`.
- `extract_body_text()`: Public function, snake_case, consistent with existing `parse_index_line()`, `check_recency()`.
- `HAS_FTS5`: Public constant, uppercase, consistent with `STOP_WORDS`.

**Verdict:** All naming follows existing conventions.

### 4b. Code Organization

New code is placed in clearly delineated sections with header comments:
```python
# ---------------------------------------------------------------------------
# Body content extraction (Phase 1b)
# ---------------------------------------------------------------------------
```
This matches the existing comment style in the file. Good.

### 4c. Error Handling

- `extract_body_text()`: Defensive with `isinstance` checks, returns empty string for edge cases. Consistent with `check_recency()` pattern.
- FTS5 check: `except Exception` with stderr warning. Consistent with existing error handling in `main()`.
- No exceptions leak. No silent failures in production paths.

**Verdict:** Consistent with existing patterns.

---

## 5. Backward Compatibility

### 5a. `test_adversarial_descriptions.py` Import

**Finding: VERIFIED SAFE**

Line 25-30 of `test_adversarial_descriptions.py`:
```python
from memory_retrieve import (
    tokenize,
    score_entry,
    score_description,
    _sanitize_title,
)
```

This is a **non-conditional import** of `score_description`. The implementation preserves `score_description()` unchanged (it was not modified in Session 1). This import continues to work.

**Risk for Session 2+:** The plan (Decision #8) says `score_description()` is PRESERVED for the fallback path. As long as this decision holds, no import cascade. If a future session removes it, the conditional import fix must happen FIRST.

### 5b. Test Calls to `tokenize()` Without `legacy` Parameter

**Finding: MEDIUM -- Silent Behavior Change**

12 test calls across 3 files use `tokenize(text)` without the `legacy` parameter:

| File | Count | Effect |
|------|-------|--------|
| `test_memory_retrieve.py` | 7 | Now uses compound tokenizer (was legacy) |
| `test_memory_candidate.py` | 4 | Imports from `memory_candidate.py` (unchanged, separate function) |
| `test_adversarial_descriptions.py` | 1 | Now uses compound tokenizer |

For `test_memory_candidate.py`: These import `tokenize` from `memory_candidate.py`, which has its own independent `tokenize()` function (line 83, `len(word) > 2` threshold). **No impact.**

For `test_memory_retrieve.py` and `test_adversarial_descriptions.py`: These import from `memory_retrieve.py`. The 8 calls now get compound tokenization (default `legacy=False`). Tests still pass because:
- For simple words like "configure", "jwt", "authentication", both tokenizers produce the same output
- The compound tokenizer is a superset -- it matches everything legacy does, plus compound tokens

This is safe but means tests are validating the compound path, not the legacy path that production code actually uses. **No immediate risk, but worth noting for Session 4 test rewrite.**

### 5c. `score_entry()` and `score_description()` Backward Compatibility

Both functions are unchanged in logic. `score_entry()` now calls `tokenize(entry["title"], legacy=True)` explicitly, which produces the exact same output as the old `tokenize(entry["title"])` with the old single regex. **Zero behavioral change.**

### 5d. Module-Level Side Effect: FTS5 Check

The FTS5 availability check (lines 253-261) runs at import time. This means:
- Every `import memory_retrieve` triggers an `sqlite3.connect(":memory:")` and FTS5 table creation
- This adds ~1-2ms to import time
- If FTS5 is unavailable, a warning is printed to stderr

**This is acceptable.** The check is fast, idempotent, and only runs once per process. Tests already import the module, so the check runs during test collection. The `_test` connection is properly closed.

Minor note: the temporary table name `_t` is fine for a disposable in-memory database.

---

## 6. Findings Summary

### BLOCKER (0)

None.

### HIGH (0)

None.

### MEDIUM (2)

**M1. Boolean flag API design (`tokenize(text, legacy=False)`)**
- The default is compound mode but all callers use legacy mode
- Tests exercise compound mode silently (not the production code path)
- **Disposition:** Accept as-is per plan spec. Session 2 will use the compound default for FTS5 query construction, validating the design choice. Revisit API if needed in Session 3 refactoring.

**M2. Test tokenizer path divergence**
- 8 test calls in 2 files now exercise compound tokenizer instead of legacy
- Tests pass because compound is a superset for simple words
- **Disposition:** Note for Session 4 test rewrite. Consider adding explicit `legacy=True` to test calls that validate the keyword scoring path, and separate compound tokenizer tests.

### LOW (2)

**L1. Import-time FTS5 side effect**
- Module import triggers sqlite3 connection and table creation
- Adds ~1-2ms per import, prints stderr warning if FTS5 unavailable
- **Disposition:** Acceptable. Standard pattern for feature detection. No action needed.

**L2. `except Exception` breadth in FTS5 check**
- Catches all exceptions, not just `ImportError` and `sqlite3.OperationalError`
- Could theoretically mask unexpected errors (e.g., `MemoryError`)
- **Disposition:** Acceptable for a feature-detection probe. The fallback to `HAS_FTS5 = False` is safe regardless of the exception type.

---

## 7. External Validation Summary

### Gemini 3.1 Pro (codereviewer role)

Key opinions:
1. **Boolean flag is Control Coupling anti-pattern** -- recommends separate functions or pattern injection. Severity: HIGH.
2. **BODY_FIELDS as module-level constant is correct** -- confirmed as optimal pattern. Severity: POSITIVE.
3. **Suggested Option C** (DI via pattern parameter) as superior third option.

**My assessment of Gemini's review:** Gemini's concerns about the boolean flag are valid from a clean-API perspective, but overweighted for this context. The plan explicitly specifies this signature, it was verified across 4 rounds of review (R1-R4), and changing it now would create plan/implementation divergence. The flag serves a clear transitional purpose: legacy callers opt in to legacy behavior, Session 2's new code uses the default. After Session 2 ships, the flag can be revisited.

### Codex

Unavailable (usage limit reached). Not a gap -- Gemini's review plus my own analysis provides sufficient coverage.

---

## 8. Session 2 Readiness Assessment

| Criterion | Status | Notes |
|-----------|--------|-------|
| `tokenize(text)` ready for `build_fts_query()` | READY | Compound tokens produced correctly |
| `extract_body_text()` ready for `score_with_body()` | READY | Clean string output, all categories covered |
| `HAS_FTS5` ready for conditional routing | READY | Boolean flag set at import time |
| Existing tests pass | PASS | 435 passed, 10 xpassed, 0 failed |
| No regressions in keyword scoring path | VERIFIED | All callers use `legacy=True` |
| `score_description()` import preserved | VERIFIED | Non-conditional import in test_adversarial_descriptions.py works |
| Plan alignment | HIGH | Implementation matches or improves on plan spec |

**Overall risk for proceeding to Session 2: LOW.**

No blockers. Two medium findings are documented for future sessions. The foundation is solid and the integration surfaces are clean.
