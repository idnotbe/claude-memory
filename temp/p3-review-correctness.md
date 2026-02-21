# P3 XML Attribute Migration -- Correctness Review

**Reviewer:** Correctness Reviewer (P3 XML Attribute Migration)
**Date:** 2026-02-21
**Scope:** Backward compatibility, edge cases, test coverage for the `<result category="..." confidence="...">` format migration.

---

## Verdict: PASS

The migration from inline `[confidence:X]` text to XML attributes (`category` and `confidence` as attributes on `<result>` elements) is correctly implemented with no backward compatibility regressions, proper test coverage, and robust security properties.

---

## 1. `_output_results()` Review (`memory_retrieve.py` lines 262-301)

### Format

The new output format is:
```xml
<memory-context source=".claude/memory/" descriptions="...">
<result category="DECISION" confidence="high">Safe Title -> safe/path #tags:a,b</result>
</memory-context>
```

### Findings

**PASS -- Category as XML attribute:** `cat = html.escape(entry["category"])` at line 298 correctly HTML-escapes the category before embedding in the attribute. This prevents attribute injection from category values.

**PASS -- Confidence as XML attribute:** `confidence_label()` returns only one of three hardcoded strings (`"high"`, `"medium"`, `"low"`), so the confidence attribute value is system-controlled and cannot be influenced by user data. This is the core security improvement of P3.

**PASS -- Title sanitization:** `_sanitize_title()` is applied to every entry title (line 287). The function:
- Strips control characters via `re.sub(r'[\x00-\x1f\x7f]', '', title)` (line 148)
- Strips Cf/Mn Unicode categories (zero-width, combining marks) (line 150)
- Replaces index-format injection markers (` -> ` and `#tags:`) (line 152)
- Truncates to 120 chars before escaping (line 155)
- XML-escapes `&`, `<`, `>`, `"` (line 157)

**PASS -- Tag sanitization:** Tags go through Cf/Mn stripping + `html.escape()` (lines 291-295). Empty tags after processing are filtered out.

**PASS -- Path sanitization:** Path is HTML-escaped via `html.escape(entry["path"])` (line 297).

**PASS -- Description attribute sanitization:** Category description keys are sanitized via `re.sub(r'[^a-z_]', '', cat_key.lower())` (line 275), and values go through `_sanitize_title()` (line 274). This prevents attribute injection through crafted category keys (quotes, `=`, etc. are stripped).

**PASS -- `<memory-context>` wrapper unchanged:** The outer wrapper tag remains `<memory-context source=".claude/memory/"...>` with optional `descriptions` attribute. This is backward compatible -- consumers parsing for `<memory-context` will still find it.

### Minor Observation (Not a Bug)

The description attribute format `descriptions="decision=Desc; runbook=Desc"` uses `_sanitize_title()` on values, which XML-escapes `&` to `&amp;`, `<` to `&lt;`, etc. This is correct for attribute values and prevents boundary breakout.

---

## 2. `_sanitize_title()` Review (`memory_retrieve.py` lines 145-158)

### Findings

**PASS -- No longer strips `[confidence:...]`:** The old regex that stripped `[confidence:...]` patterns from titles has been correctly removed. This is the right call because:
- Confidence is now an XML attribute, structurally separated from element content
- `[confidence:high]` in a title is inert text inside an element body
- The `[` and `]` characters are not XML-special, so they pass through harmlessly
- If a title contains `"` it gets escaped to `&quot;`, preventing attribute boundary breakout

**PASS -- `re` import is still needed:** The `re` module is used in two places:
1. Line 148: `re.sub(r'[\x00-\x1f\x7f]', '', title)` -- control character stripping
2. Line 275: `re.sub(r'[^a-z_]', '', cat_key.lower())` -- description key sanitization

Both uses are correct and necessary. The import is justified.

**PASS -- Truncation before escaping:** Line 155 truncates to 120 chars BEFORE XML escaping (line 157). This prevents a truncation cut from splitting an entity mid-sequence (e.g., `&amp;` cut to `&am`), which would produce invalid XML. The ordering is correct: strip -> truncate -> escape.

---

## 3. Test Coverage in `test_memory_retrieve.py`

### `TestSanitizeTitleXmlSafety` (lines 565-613)

**PASS -- Updated for P3:** The docstring explicitly states "After P3, confidence spoofing in titles is harmless because confidence is an XML attribute." Tests verify:
- `test_preserves_legitimate_brackets` -- `[Redis]` passes through
- `test_xml_escapes_angle_brackets` -- `<result>` becomes `&lt;result&gt;`
- `test_xml_escapes_quotes` -- `"quotes"` becomes `&quot;quotes&quot;`
- `test_xml_escapes_ampersand` -- `&` becomes `&amp;`
- `test_cf_mn_stripping_still_active` -- zero-width chars stripped
- `test_confidence_in_title_passes_through` -- `[confidence:high]` in title is harmless

### `TestOutputResultsConfidence` (lines 615-693)

**PASS -- Comprehensive P3 tests:** Tests verify:
- `test_confidence_label_in_output` -- checks `confidence="high"` and `confidence="low"` XML attributes appear
- `test_tag_spoofing_harmless_in_xml` -- tag containing `[confidence:high]` is in element body, counted exactly once as attribute
- `test_no_score_defaults_low` -- missing score defaults to `confidence="low"`
- `test_result_element_format` -- full regex pattern match on `<result category="DECISION" confidence="high">...</result>`
- `test_spoofed_title_in_xml_element` -- title with `confidence="high"` gets XML-escaped to `confidence=&quot;high&quot;`
- `test_closing_tag_in_title_escaped` -- `</result><fake>` becomes `&lt;/result&gt;&lt;fake&gt;`

### Line Matching Patterns

**PASS -- All tests use correct `<result ` pattern:** All test files correctly use `l.strip().startswith("<result ")` to identify per-entry result lines:
- `test_memory_retrieve.py` line 271
- `test_memory_retrieve.py` line 642
- `test_arch_fixes.py` line 431
- `test_arch_fixes.py` line 922
- `test_fts5_smoke.py` lines 234-235

No test still uses the old `startswith("- [")` pattern for retrieval output lines.

---

## 4. `test_fts5_smoke.py` Review

**PASS -- Line matching updated:** Lines 234-235 correctly filter for `<result ` prefix instead of old `- [` prefix.

**PASS -- Format verification:** Lines 238-243 verify that each result line contains ` -> ` delimiter, which is present in the new `<result>` element body format (`{safe_title} -> {safe_path}{tags_str}`).

**PASS -- Wrapper tag checks:** Lines 228-229 check for `<memory-context` opening and `</memory-context>` closing tags, which are unchanged.

---

## 5. `test_v2_adversarial_fts5.py` Review

### `TestOutputSanitization` (lines 1021-1098)

**PASS -- XSS payload tests still valid:** `test_sanitize_title_xss_payloads` verifies `<script>`, `<img`, `<svg` are escaped. These tests work identically with the new format because `_sanitize_title()` is the same function.

**PASS -- Zero-width, BIDI, tag character tests:** Tests at lines 1038-1061 verify Cf/Mn category stripping. These are independent of the output format.

**PASS -- `_output_results` component tests:** `test_output_results_captures_all_paths` (line 1063) and `test_output_results_description_injection` (line 1079) test the function directly. Both tests check for `<script>` / `<system>` absence and presence of escaped variants. These assertions are format-agnostic and valid for the new XML attribute format.

---

## 6. `test_arch_fixes.py` Review

### Line counting patterns

**PASS:** Line 431 uses `l.strip().startswith("<result ")` -- correct for new format.
**PASS:** Line 922 uses `l.strip().startswith("<result ")` -- correct for new format.

### `RELEVANT MEMORIES` references

**PASS -- Backward-compatible assertions:** Two test assertions reference `RELEVANT MEMORIES` as the old format:
- Line 231: `assert "<memory-context" in stdout or "RELEVANT MEMORIES" in stdout` -- uses OR, so it passes with the new format.
- Line 301: `if "RELEVANT MEMORIES" in stdout:` -- conditional block that only executes for the old format; the test still passes when the condition is false.
- Lines 742-744: `has_old_format = "RELEVANT MEMORIES" in stdout` followed by `assert has_new_format or has_old_format` -- passes with either format.

These assertions are safe: they accommodate both old and new formats, so no backward compatibility issue.

---

## 7. Edge Cases Verified

### Empty tags
**PASS:** In `_output_results()` lines 289-296, empty tags after Cf/Mn stripping and `html.escape()` are filtered by `if val:`. When all tags are empty, `safe_tags` is empty, and `tags_str` becomes `""` (no `#tags:` suffix). The `<result>` element still renders correctly without tags.

### Empty entries list
**PASS:** `_output_results()` with an empty `top` list would print only the wrapper tags. However, the callers guard against this: `main()` checks `if results:` (line 407) and `if not final:` (line 486) before calling `_output_results()`.

### Single entry
**PASS:** `best_score` is computed via `max(... , default=0)` (line 283). A single entry's score equals `best_score`, yielding ratio 1.0, so `confidence_label` returns `"high"`. This is verified by `test_single_result_always_high` (line 536).

### Multiple entries with same score
**PASS:** When all entries have the same score, `ratio = abs(score) / abs(best_score) = 1.0` for all, so all get `confidence="high"`. This is verified by `test_all_same_score_all_high` (line 539).

### Title containing `confidence="high"` with XML escaping
**PASS:** A title like `Evil confidence="high" title` gets the `"` characters escaped to `&quot;` by `_sanitize_title()`. The resulting element body is `Evil confidence=&quot;high&quot; title`, which cannot interfere with the real `confidence="high"` XML attribute. Tested by `test_spoofed_title_in_xml_element` (line 670).

### Title containing `</result>` closing tag
**PASS:** `_sanitize_title()` escapes `<` to `&lt;` and `>` to `&gt;`, preventing element boundary breakout. Tested by `test_closing_tag_in_title_escaped` (line 683).

### Description key injection (`decision" evil="true`)
**PASS:** The regex `re.sub(r'[^a-z_]', '', cat_key.lower())` strips all characters except lowercase letters and underscores. Quotes, equals signs, and spaces are removed. Tested by `test_output_results_description_injection` (line 1079).

---

## 8. Backward Compatibility Summary

| Aspect | Status | Notes |
|--------|--------|-------|
| `<memory-context>` wrapper | Unchanged | Same opening/closing tags |
| `source` attribute | Unchanged | Still `source=".claude/memory/"` |
| `descriptions` attribute | Unchanged | Same format |
| Per-entry format | Changed | From `- [CAT] title -> path [confidence:X]` to `<result category="CAT" confidence="X">title -> path</result>` |
| Tag format in body | Unchanged | Still `#tags:a,b` suffix |
| Arrow delimiter in body | Unchanged | Still `title -> path` |
| All test assertions | Updated | Use `<result ` prefix, not `- [` |

The `<memory-context>` wrapper is the external interface for consumers. Any tool or agent parsing for `<memory-context` will still find it. The per-entry format change is an internal detail within the wrapper and improves security by moving system-controlled metadata (category, confidence) into XML attributes.

---

## 9. Issues Found

**None.** The migration is clean, well-tested, and backward compatible at the wrapper level.

---

## 10. Recommendations (Non-blocking)

1. **Consider adding a test for `_output_results` with 0 entries** -- While the callers guard against this, a direct unit test of `_output_results([], {})` would verify the wrapper-only output case is valid XML.

2. **Consider documenting the format change in CLAUDE.md** -- The Hook Type table mentions "UserPromptSubmit" retrieval hook but doesn't specify the per-entry output format. A brief note about the P3 XML attribute format would help future maintainers.

Both are non-blocking and do not affect the PASS verdict.
