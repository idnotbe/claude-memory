# P3 Verification Round 2: Logic Consistency & Edge Cases

**Date:** 2026-02-26
**Perspective:** Logic consistency, cross-action interaction, edge cases
**Files reviewed:** memory_retrieve.py, test_memory_retrieve.py, memory-config.default.json
**Test result:** 90/90 PASSED

---

## Checklist Item 1: All confidence_label() Call Sites

There are **5 call sites** in memory_retrieve.py (excluding the definition at line 172):

| # | Line | Location | abs_floor passed? | Correct? |
|---|------|----------|-------------------|----------|
| 1 | 349-350 | `_output_results()` label pre-computation | `abs_floor=abs_floor` | YES |
| 2 | 582-583 | Logging Point 1: FTS5 search results | `abs_floor=abs_floor` | YES |
| 3 | 641-642 | Logging Point 3: FTS5 inject | `abs_floor=abs_floor` | YES |
| 4 | 791-792 | Logging Point 3: Legacy inject | `abs_floor=abs_floor` | YES |
| 5 | N/A | Not present | N/A | N/A |

**Verdict: PASS.** All 4 active call sites consistently pass `abs_floor=abs_floor`. The parameter defaults to `0.0` in the function signature, which matches the variable initialization at line 455. No call site omits `abs_floor`.

Note: `cluster_count=0` is passed explicitly only at call site #1 (line 350). The other 3 logging call sites do NOT pass `cluster_count`, which defaults to `0` in the signature. This is correct behavior since cluster detection is disabled.

---

## Checklist Item 2: output_mode Propagation

Two call sites for `_output_results()` in `main()`:

| Path | Line | output_mode passed? | Correct? |
|------|------|---------------------|----------|
| FTS5 path | 649-650 | `output_mode=output_mode` | YES |
| Legacy path | 799-800 | `output_mode=output_mode` | YES |

**Verdict: PASS.** Both call sites in `main()` correctly forward the `output_mode` variable.

---

## Checklist Item 3: abs_floor Propagation

Two call sites for `_output_results()` in `main()`:

| Path | Line | abs_floor passed? | Correct? |
|------|------|-------------------|----------|
| FTS5 path | 649-650 | `abs_floor=abs_floor` | YES |
| Legacy path | 799-800 | `abs_floor=abs_floor` | YES |

**Verdict: PASS.** Both call sites correctly forward `abs_floor`.

---

## Checklist Item 4: _emit_search_hint() Function Placement

- **Defined at:** Line 299
- **Call sites:** Lines 358, 387, 657, 700, 768

All call sites are AFTER the definition. The function is defined before `_output_results()` (line 316), which itself calls it at lines 358 and 387. The `main()` function starts at line 391 and calls it at lines 657, 700, 768.

**Verdict: PASS.** Definition precedes all call sites.

---

## Checklist Item 5: Tiered Mode Label Computation

Labels are computed ONCE in `_output_results()` at lines 347-350:

```python
labels = []
for entry in top:
    labels.append(confidence_label(entry.get("score", 0), best_score,
                                   abs_floor=abs_floor, cluster_count=0))
```

These labels are then used:
- Lines 352-354: `any_high`, `any_medium`, `all_low` derived from `labels`
- Line 362: `zip(top, labels)` iteration
- Line 386: `not any_high and any_medium` check

Labels are NOT recomputed. Single computation, multiple uses.

**Verdict: PASS.** Labels computed once and reused consistently.

---

## Checklist Item 6: zip(top, labels) Length Consistency

`labels` is built by iterating over `top` (line 348: `for entry in top`), so `len(labels) == len(top)` is guaranteed by construction. `zip()` would silently truncate if lengths differed, but they cannot differ here.

**Verdict: PASS.** Lengths are always equal by construction.

---

## Checklist Item 7: medium_present Hint Condition Trace

Condition at line 386: `output_mode == "tiered" and not any_high and any_medium`

Trace through all label combinations for a 3-entry result set:

| Labels | any_high | any_medium | all_low | Hint? | Correct? |
|--------|----------|------------|---------|-------|----------|
| [high, medium, low] | T | T | F | NO (any_high=True) | YES - high results dominate |
| [high, high, high] | T | F | F | NO (any_high=True) | YES |
| [medium, medium, low] | F | T | F | YES | YES - only medium, hint is helpful |
| [medium, low, low] | F | T | F | YES | YES |
| [low, low, low] | F | F | T | NO (early return at line 357-359) | YES - all_low path handles this |
| [high, medium, medium] | T | T | F | NO | YES |
| [medium, medium, medium] | F | T | F | YES | YES |

Edge case: single entry with "medium" label:
- `any_high=False`, `any_medium=True` -> hint emitted. Correct.

Edge case: empty top list (impossible in practice since callers check `if results` before calling `_output_results`):
- `labels=[]`, `any_high=False`, `any_medium=False`, `all_low=True` -> early return with "all_low" hint. Acceptable behavior.

**FINDING (MINOR):** The `medium_present` hint at line 387 is printed INSIDE the `<memory-context>` wrapper (before `</memory-context>` at line 388). This means the `<memory-note>` element is nested within `<memory-context>`. This is structurally questionable -- the hint about doing a manual search is semantically outside the results context. However, this is a **cosmetic/formatting issue**, not a logic bug. The LLM consumer will still parse both elements correctly.

**Verdict: PASS (with minor cosmetic note).** Logic is correct for all label combinations.

---

## Checklist Item 8: Test Coverage Gaps

### 8a. Config parsing error paths
- `abs_floor` invalid parsing: Line 483 catches `ValueError, TypeError, OverflowError` and defaults to `0.0`. **NOT tested.** No unit test for config with `confidence_abs_floor: "invalid"`.
- `output_mode` invalid value: Line 487 checks `if raw_mode in ("legacy", "tiered")`, otherwise keeps default `"legacy"`. **NOT tested.** No unit test for config with `output_mode: "unknown"`.

### 8b. abs_floor with legacy mode
- The abs_floor variable is passed through to `_output_results()` at line 800 in the legacy path. This works because `confidence_label()` handles it identically regardless of scoring domain.
- **Tested implicitly** by `TestConfidenceLabelAbsFloor` unit tests (they test the function directly with positive/legacy scores), but **no integration test** exercises the full legacy path with `abs_floor > 0`.

### 8c. Tiered mode with category descriptions
- `TestTieredOutput` tests don't pass `category_descriptions`. The `_output_results` function combines `desc_attr` and tiered output independently, so they don't interact in complex ways. However, **no test verifies tiered output WITH descriptions in the `<memory-context>` opening tag**.

### 8d. Tiered mode with abs_floor combined
- `test_tiered_medium_present_hint` at line 831-837 does test this: uses `abs_floor=10.0` with tiered mode to force all results to medium. **Covered.**

### 8e. No test for `_emit_search_hint` being called from `main()` in FTS5 path (line 657)
- This path (`fts_query` valid, `results` empty) is hard to trigger in integration tests because FTS5 usually returns something if a valid query exists. **Not critical** since the unit test for `_emit_search_hint("no_match")` covers the function itself.

**Verdict: MINOR GAPS.** Config error paths for `abs_floor` and `output_mode` are untested. No integration test for abs_floor in legacy mode. No tiered+descriptions combined test. These are all minor since the unit-level coverage is solid.

---

## Checklist Item 9: Test Score Fragility

The tiered tests use specific score values to trigger specific confidence labels:

| Test | Scores | Expected Labels | Fragile? |
|------|--------|-----------------|----------|
| `test_tiered_medium_as_compact` | [-5.0, -2.5] | [high, medium (ratio=0.5)] | NO - 0.5 is well within medium range (0.40-0.75) |
| `test_tiered_low_silenced` | [-5.0, -1.0] | [high, low (ratio=0.2)] | NO - 0.2 is well below 0.40 |
| `test_tiered_mixed_high_medium_low` | [-10.0, -5.0, -1.0] | [high, medium (0.5), low (0.1)] | NO - clear separation |
| `test_tiered_all_low_skips_wrapper` | [score=0 (no "score" key)] | [low] | NO - best_score=0 always gives "low" |
| `test_tiered_medium_present_hint` | [-5.0, -4.0] with abs_floor=10.0 | [medium, medium] | NO - abs_floor forces cap |

**Verdict: PASS.** Score values are chosen with comfortable margins from thresholds. Not fragile.

---

## Checklist Item 10: Action #1 + #2 Interaction (abs_floor + tiered)

Trace: When `abs_floor=10.0` and scores are [-5.0, -4.0]:

1. `best_score = abs(-5.0) = 5.0`
2. Entry 0: `ratio = 5.0/5.0 = 1.0 >= 0.75` -> would be "high", but `floor_capped = 10.0 > 0 and 5.0 < 10.0 = True` -> **"medium"**
3. Entry 1: `ratio = 4.0/5.0 = 0.8 >= 0.75` -> would be "high", but floor_capped -> **"medium"**
4. `any_high = False`, `any_medium = True`, `all_low = False`
5. Tiered mode: both rendered as `<memory-compact>`, then hint emitted

This is exactly what `test_tiered_medium_present_hint` tests. The interaction is correct.

**Verdict: PASS.** abs_floor correctly affects tiered mode output.

---

## Checklist Item 11: Action #2 + #3 Interaction (tiered all-LOW + hint)

Trace: When all entries have `score=0` (no "score" key):

1. `best_score = max(abs(0), ...) = 0`
2. `confidence_label(0, 0)` -> `best_score == 0` -> returns "low"
3. All labels are "low" -> `all_low = True`
4. Line 357: `output_mode == "tiered" and all_low` -> True
5. `_emit_search_hint("all_low")` called -> prints `<memory-note>Memories exist but confidence was low...`
6. Early return (line 359) -> no `<memory-context>` wrapper, no `</memory-context>`

This is tested by `test_tiered_all_low_skips_wrapper`.

**Verdict: PASS.** Tiered all-LOW correctly calls `_emit_search_hint("all_low")`.

---

## Checklist Item 12: Action #1 + #3 Interaction (abs_floor + hints)

Trace: abs_floor can cause what would be "high" results to become "medium". This means:
- `any_high` can be False when it would normally be True (abs_floor caps high -> medium)
- `any_medium` can be True when there were no organic medium results

This correctly triggers the `medium_present` hint at line 386-387 when `not any_high and any_medium`.

The interaction chain: abs_floor caps high -> medium -> `not any_high and any_medium` -> hint emitted.

**But:** abs_floor does NOT affect the `all_low` path because `all_low` means every label is "low", and abs_floor only caps "high" to "medium" (never "medium" to "low"). So abs_floor cannot create an `all_low` situation that wouldn't already exist.

**Verdict: PASS.** abs_floor can trigger `medium_present` hint (correct behavior), cannot create false `all_low`.

---

## Additional Findings

### F1: Logging label inconsistency (MINOR, PRE-EXISTING)

At Logging Point 1 (line 582), the `_best_score` is computed as `abs(results[0]["score"])` -- this is the best score from the FULL results list (pre-max_inject truncation). But at Logging Point 3 (line 641), `_inj_best = abs(top[0]["score"])` is from the truncated `top` list (post-max_inject).

If judge filtering removes the highest-scoring entry, Logging Point 3's labels could differ from Logging Point 1's labels for the same entry. This is semantically correct (each log point reflects its own context) but could be confusing in log analysis. **Not a bug, but worth noting.**

### F2: Legacy path injects score onto entry dict (MINOR, PRE-EXISTING)

At line 779, `entry["score"] = score` mutates the original entry dict. Since entries are from the parsed index (line 525-531), this mutation persists on the entry dict. This is harmless in the current code because the entries are not used after `_output_results()`, but it's technically a side effect. **Not a bug.**

### F3: medium_present hint inside memory-context (COSMETIC)

As noted in Item 7, the `<memory-note>` from `_emit_search_hint("medium_present")` at line 387 is printed inside the `<memory-context>` wrapper (before `</memory-context>` at line 388). The "all_low" hint (line 358) is printed OUTSIDE (before the wrapper, with early return). This asymmetry is mildly inconsistent but not a logic error.

---

## Summary

| Check | Status | Notes |
|-------|--------|-------|
| 1. confidence_label call sites | PASS | All 4 sites pass abs_floor consistently |
| 2. output_mode propagation | PASS | Both FTS5 and legacy paths forward correctly |
| 3. abs_floor propagation | PASS | Both FTS5 and legacy paths forward correctly |
| 4. _emit_search_hint placement | PASS | Defined before all call sites |
| 5. Label single computation | PASS | Computed once, reused |
| 6. zip length consistency | PASS | Same length by construction |
| 7. medium_present condition | PASS | Correct for all label combinations |
| 8. Test coverage gaps | MINOR | Config error paths, legacy+abs_floor integration untested |
| 9. Score fragility | PASS | Comfortable margins from thresholds |
| 10. abs_floor + tiered | PASS | Correctly interacts |
| 11. tiered + hint | PASS | all-LOW correctly triggers hint |
| 12. abs_floor + hint | PASS | Can trigger medium_present hint (correct) |

**Overall verdict: PASS with minor notes.** No logic bugs found. Three cosmetic/completeness issues identified (F1, F3, test gaps in Item 8). All cross-action interactions behave correctly.
