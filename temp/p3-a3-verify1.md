# P3 Action #3 Verification: Hint Improvement -- HTML Comments to XML Tags

**Verifier:** Claude Opus 4.6 (verification agent)
**Date:** 2025-02-25
**Status:** PASS (with 1 minor design observation)

---

## Summary

All 3 original HTML comment hints have been successfully replaced with `_emit_search_hint()` calls that emit `<memory-note>` XML tags. The implementation is clean, secure, and well-tested. 90/90 tests pass with no regressions.

---

## Checklist

### 1. All 3 original HTML comment hints replaced

**PASS.** The git diff shows exactly 3 replacement sites where `print("<!-- ... -->")` was changed to `_emit_search_hint("no_match")`:

| Location | Old code | New code |
|----------|----------|----------|
| Line 651 (FTS5 path, no results) | `print("<!-- No matching memories found... -->")` | `_emit_search_hint("no_match")` |
| Line 694 (legacy path, no entries scored) | `print("<!-- No matching memories found... -->")` | `_emit_search_hint("no_match")` |
| Line 762 (legacy path, no results after deep check) | `print("<!-- No matching memories found... -->")` | `_emit_search_hint("no_match")` |

Additionally, 2 new call sites were added for the tiered output mode:
- Line 358: `_emit_search_hint("all_low")` -- when tiered mode + all results are LOW confidence
- Line 387: `_emit_search_hint("medium_present")` -- when tiered mode + medium results but no high

### 2. `_emit_search_hint()` outputs `<memory-note>` XML tags, NOT HTML comments

**PASS.** The function definition (lines 299-313) uses `<memory-note>...</memory-note>` for all 3 reason branches. Grep confirms zero `<!--` patterns in `memory_retrieve.py`.

### 3. "all_low" and "medium_present" reasons work correctly

**PASS.**
- `"all_low"` prints: `<memory-note>Memories exist but confidence was low. Use /memory:search &lt;topic&gt; for detailed lookup.</memory-note>`
- `"medium_present"` prints: `<memory-note>Some results had medium confidence. Use /memory:search &lt;topic&gt; for detailed lookup.</memory-note>`

Both messages are semantically correct for their contexts.

### 4. Default reason "no_match" is correct

**PASS.** The function signature `def _emit_search_hint(reason: str = "no_match")` uses "no_match" as default. The else branch handles this and any unknown reason values, printing the "No matching memories found" message. Tests verify both `_emit_search_hint("no_match")` and `_emit_search_hint()` (no-arg) produce the same output.

### 5. No user-controlled data in hint text (hardcoded strings only)

**PASS.** All 3 `print()` calls in `_emit_search_hint()` use only string literals. The `reason` parameter is only used for branching (string comparison), never interpolated into output. No f-strings or format operations on user data.

### 6. XML-safe: `<topic>` properly escaped as `&lt;topic&gt;`

**PASS.** All 3 hint messages use `&lt;topic&gt;` (HTML entity encoding) in the string literals, preventing any XML parsing confusion. Test `test_hint_contains_no_user_data` explicitly verifies `"&lt;topic&gt;"` is present in output.

### 7. No leftover HTML comment hints in the code

**PASS.** Grep for `<!--` in `memory_retrieve.py` returns zero matches. The only `<!--` patterns in the hooks/scripts/ directory are in `memory_index.py` (line 115) and `memory_write.py` (line 453), both for auto-generated index file headers -- completely unrelated to search hints.

### 8. Integration with tiered mode: all-LOW triggers `_emit_search_hint("all_low")`

**PASS.** In `_output_results()` (lines 357-359):
```python
if output_mode == "tiered" and all_low:
    _emit_search_hint("all_low")
    return
```
This correctly skips the `<memory-context>` wrapper entirely and returns early, so the all-LOW case produces only the `<memory-note>` hint with no other output. Verified by test `test_tiered_all_low_skips_wrapper`.

### 9. `_emit_search_hint("medium_present")` placement inside `<memory-context>` wrapper

**OBSERVATION (design note, not a bug).** Lines 386-388:
```python
    if output_mode == "tiered" and not any_high and any_medium:
        _emit_search_hint("medium_present")
    print("</memory-context>")
```

The `<memory-note>` hint is emitted *inside* the `<memory-context>...</memory-context>` wrapper. This means the output looks like:
```xml
<memory-context source=".claude/memory/">
<memory-compact category="DECISION" confidence="medium">...</memory-compact>
<memory-note>Some results had medium confidence. Use /memory:search &lt;topic&gt; for detailed lookup.</memory-note>
</memory-context>
```

This is a **reasonable design choice**: the hint is contextually associated with the memory results. Placing it inside the wrapper keeps all memory-related output contained in one XML block. The alternative (placing it after `</memory-context>`) would work too but would create two separate output blocks. Neither approach is wrong; the current placement is arguably cleaner for parsers that read the entire `<memory-context>` element.

---

## Test Coverage Assessment

The `TestEmitSearchHint` class has 6 tests covering:

| Test | What it verifies |
|------|-----------------|
| `test_no_match_hint` | "no_match" reason produces correct XML tag and message |
| `test_all_low_hint` | "all_low" reason produces correct message with /memory:search |
| `test_medium_present_hint` | "medium_present" reason produces correct message |
| `test_default_reason_is_no_match` | Calling with no args defaults to "no_match" behavior |
| `test_hint_contains_no_user_data` | Output contains only hardcoded strings, `&lt;topic&gt;` escaping |
| `test_hint_uses_xml_not_html_comment` | No `<!--` in output, `<memory-note>` present |

Integration with tiered mode is covered by `TestTieredOutput`:
- `test_tiered_all_low_skips_wrapper` -- verifies all-LOW path
- `test_tiered_medium_present_hint` -- verifies medium-only path

**Coverage is thorough.** All branches of `_emit_search_hint()` are exercised, security properties are verified, and integration with the tiered output mode is tested.

---

## External Review Status

| Reviewer | Status | Notes |
|----------|--------|-------|
| Codex CLI | UNAVAILABLE | Usage limit hit (resets Feb 28) |
| Gemini CLI | UNAVAILABLE | Network fetch error (API connectivity issue) |

Both external reviewers were unavailable due to service issues. The manual analysis above is thorough and covers all verification points.

---

## Issues Found

**None.** The implementation is correct, secure, and complete.

---

## Full Test Run

```
90 passed in 0.80s
```

All 90 tests in `test_memory_retrieve.py` pass, including the 6 new `TestEmitSearchHint` tests and the 10 `TestTieredOutput` tests that exercise `_emit_search_hint()` integration.
