# P3 Action #2: Tiered Output Mode -- Verification Report

**Date:** 2026-02-25
**Reviewer:** Opus 4.6 (verification agent)
**External reviews:** Claude Sonnet (completed), Codex (unavailable -- usage limit), Gemini (unavailable -- network error)

---

## 1. Own Analysis

### 1.1 Correctness: Tiered Mode HIGH/MEDIUM/LOW Output

**CORRECT.** Lines 376-384 of `memory_retrieve.py` implement the three tiers exactly as specified:

- `conf == "high"` -> `<result>` element (line 378)
- `conf == "medium"` -> `<memory-compact>` element (line 380)
- `conf == "low"` -> no output (line 381, comment-only)

The `confidence_label()` function (lines 172-206) correctly maps:
- ratio >= 0.75 -> "high"
- ratio >= 0.40 -> "medium"
- else -> "low"

Both `<result>` and `<memory-compact>` elements include the same attributes (`category`, `confidence`) and the same body format (`safe_title -> safe_path tags_str`). This ensures consistent structure between tiers.

### 1.2 All-LOW Case: Wrapper Skipped, Hint Emitted

**CORRECT.** Lines 357-359:
```python
if output_mode == "tiered" and all_low:
    _emit_search_hint("all_low")
    return
```
The early `return` correctly prevents the `<memory-context>` wrapper from being opened (line 361) and the `</memory-context>` closer from being printed (line 388).

**Edge case (Low severity):** `all(l == "low" for l in [])` returns `True` in Python (vacuous truth). If `top=[]` reaches `_output_results()` in tiered mode, the "Memories exist but confidence was low" hint fires, which is factually incorrect. However, both call sites guard against this: the FTS5 path checks `if results:` at line 585 before calling, and the legacy path checks `if not final:` at line 760. This is unreachable in practice but lacks a defensive guard.

### 1.3 Medium-Present Hint: Only When No HIGH Exists

**CORRECT logic.** Line 386:
```python
if output_mode == "tiered" and not any_high and any_medium:
    _emit_search_hint("medium_present")
```

The boolean conditions are correct:
- `not any_high` ensures hint only fires when no HIGH results exist
- `any_medium` ensures at least one MEDIUM result exists
- The condition is guarded by `output_mode == "tiered"` so legacy mode is unaffected

**Structural concern (Medium severity):** The `<memory-note>` from this hint is emitted at line 387, which is *inside* the `<memory-context>` block (between the for loop and `</memory-context>` on line 388). This contrasts with the `all_low` hint which is emitted *outside* any wrapper (lines 358-359). The resulting output structure is:

```xml
<memory-context source=".claude/memory/">
  <memory-compact ...>...</memory-compact>
  <memory-note>Some results had medium confidence...</memory-note>
</memory-context>
```

This is inconsistent but arguably intentional -- placing the hint inside the wrapper keeps it contextually associated with the results. However, it may surprise downstream XML consumers that expect only `<result>` and `<memory-compact>` children inside `<memory-context>`. Whether to move it after `</memory-context>` is a design decision, not a correctness bug.

### 1.4 Legacy Mode: Completely Unchanged

**CORRECT.** When `output_mode != "tiered"`:
- The `all_low` early return is guarded by `output_mode == "tiered"` (line 357)
- The `medium_present` hint is guarded by `output_mode == "tiered"` (line 386)
- All entries hit the `else` branch (line 382-384), printing `<result>` for every entry

No legacy behavior is affected by the new code paths.

### 1.5 Security: XML Escaping in Compact Format

**CORRECT.** The escaping logic is shared across both tiers:

| Field | Escaping | Line |
|-------|----------|------|
| title | `_sanitize_title()` (control char strip + Cf/Mn strip + XML entity escape) | 363 |
| path | `html.escape()` | 373 |
| category | `html.escape()` | 374 |
| tags | Cf/Mn strip + `html.escape()` | 367-371 |

The `tags_str` variable is constructed at line 372, *before* the `if output_mode == "tiered"` branch, so both `<result>` and `<memory-compact>` elements receive the same escaped tags string. No user-controlled content can break out of element boundaries.

The `_sanitize_title()` function (lines 156-169) applies escaping in the correct order: truncate first, then escape (to avoid splitting mid-entity).

### 1.6 Config Parsing: output_mode Validation

**CORRECT but silent on invalid values.** Lines 486-488:
```python
raw_mode = retrieval.get("output_mode", "legacy")
if raw_mode in ("legacy", "tiered"):
    output_mode = raw_mode
```

- Only `"legacy"` and `"tiered"` are accepted
- Default is `"legacy"` (initialized at line 456)
- Invalid values silently fall back to `"legacy"`

**Minor gap (Low severity):** No `[WARN]` is emitted for invalid values, unlike `max_inject` validation (line 474-477) which emits `[WARN] Invalid max_inject value`. Consistency suggests adding a similar warning, but silent fallback to safe defaults is acceptable.

### 1.7 Both Call Sites Pass New Params

**CORRECT.** Both call sites pass `output_mode` and `abs_floor` as keyword arguments:

- FTS5 path (line 649-650):
  ```python
  _output_results(top, category_descriptions,
                 output_mode=output_mode, abs_floor=abs_floor)
  ```
- Legacy keyword path (line 799-800):
  ```python
  _output_results(top_list, category_descriptions,
                  output_mode=output_mode, abs_floor=abs_floor)
  ```

The function signature has safe defaults (`output_mode="legacy"`, `abs_floor=0.0`), so any missed call site would degrade gracefully to legacy behavior.

### 1.8 Pre-Computed Labels Match Zip Iteration

**CORRECT.** Labels are built by iterating `top` in order (lines 347-350):
```python
labels = []
for entry in top:
    labels.append(confidence_label(entry.get("score", 0), best_score,
                                   abs_floor=abs_floor, cluster_count=0))
```

Then `zip(top, labels)` at line 362 pairs each entry with its corresponding label. Since both lists are derived from the same source list, lengths are guaranteed to match. The pre-computation also correctly enables `any_high`, `any_medium`, `all_low` booleans to be determined before any rendering occurs.

### 1.9 Default Config in assets/memory-config.default.json

**CORRECT.** Line 54 of `assets/memory-config.default.json`:
```json
"output_mode": "legacy"
```
The default config correctly specifies "legacy" mode, preserving backward compatibility.

---

## 2. External Review: Claude Sonnet (codereviewer role)

Claude Sonnet performed a 10-turn review with full file access. Key findings:

### Issues Found

1. **(Medium) `<memory-note>` inside `<memory-context>` for medium-present hint** (line 387): The hint is emitted inside the wrapper block. Inconsistent with the `all_low` hint which is emitted outside. May confuse downstream XML consumers.

2. **(Low) Silent invalid `output_mode` config** (line 487): No stderr warning for unrecognized values. Inconsistent with `max_inject` validation.

3. **(Low) Vacuous `all_low` for empty list**: Empty `top` list in tiered mode emits misleading "Memories exist but confidence was low" note. Add `if not top: return` guard.

### Test Gaps Identified

1. `test_tiered_compact_xml_escaping` (line 866-878): Has `"tags": {"evil<tag>"}` but only asserts title escaping (`"&lt;script&gt;" in out`). Missing assertion that tag `evil<tag>` is escaped to `evil&lt;tag&gt;`.

2. No test for invalid `output_mode` config value fallback to legacy.

3. No test for empty entry list in tiered mode.

4. No structural test for `</memory-context>` ordering relative to `<memory-note>`.

### Positive Observations

- `zip(top, labels)` pairing is correct and safe
- Both call sites pass new parameters
- Legacy mode is completely unmodified
- Tag/path/category escaping is uniformly applied
- Feature is well-structured with good happy-path coverage

---

## 3. External Review: Codex + Gemini

- **Codex:** Unavailable (usage limit reached). No review obtained.
- **Gemini:** Failed twice due to network errors (TypeError: fetch failed). No review obtained.

---

## 4. Consolidated Findings

### Issues Found

| # | Severity | Location | Description |
|---|----------|----------|-------------|
| 1 | Medium | `memory_retrieve.py:386-387` | `<memory-note>` for medium-present hint is emitted *inside* `<memory-context>` block, inconsistent with `all_low` hint placement. Design decision, not a correctness bug -- but should be explicitly documented or standardized. |
| 2 | Low | `memory_retrieve.py:487` | Invalid `output_mode` config values silently fall back to "legacy" without stderr warning. Inconsistent with `max_inject` validation pattern. |
| 3 | Low | `memory_retrieve.py:354-358` | Empty `top` list + tiered mode triggers vacuous `all_low` (Python `all([])` is `True`), emitting misleading "Memories exist but confidence was low" hint. Unreachable in practice but lacks defensive guard. |

### Test Gaps

| # | Description |
|---|-------------|
| 1 | `test_tiered_compact_xml_escaping`: Missing assertion for tag escaping (`evil<tag>` -> `evil&lt;tag&gt;`) |
| 2 | No test for invalid `output_mode` config value fallback |
| 3 | No test for `_output_results([], {}, output_mode="tiered")` (empty list edge case) |
| 4 | No structural ordering test for `<memory-note>` position relative to `</memory-context>` in medium-present case |

### Verdict

**ALL CLEAR (with minor recommendations).** The core tiered output implementation is correct and secure. No critical or high-severity bugs were found. The three low/medium issues identified are edge cases or consistency improvements, none of which affect correctness in production scenarios. All 90 existing tests pass, and the new TestTieredOutput tests (10 tests) comprehensively cover the happy paths. The feature is ready for use.

### Recommended Follow-Up (Non-Blocking)

1. Decide on `<memory-note>` placement: either standardize inside or outside `<memory-context>` for both hint types
2. Add defensive `if not top: return` guard at top of `_output_results()`
3. Add stderr `[WARN]` for invalid `output_mode` config values
4. Extend `test_tiered_compact_xml_escaping` with tag escaping assertion
