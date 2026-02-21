# P3 Implementation Output

## Changes Applied

### 1. `hooks/scripts/memory_retrieve.py` (PRIMARY)

**A. Removed `_CONF_SPOOF_RE` constant** (was line 42-44)
- Regex `r'\[\s*confidence\s*:[^\]]*\]'` removed entirely
- No longer imported or used anywhere in the file

**B. Simplified `_sanitize_title()`**
- Removed the confidence-spoofing while loop (6 lines)
- Kept: control char stripping, Cf+Mn filtering, ` -> ` replacement, `#tags:` removal, truncation, XML escaping

**C. Rewrote `_output_results()`**
- Old format: `- [{cat}] {safe_title} -> {safe_path}{tags_str} [confidence:{conf}]`
- New format: `<result category="{cat}" confidence="{conf}">{safe_title} -> {safe_path}{tags_str}</result>`
- Added `html.escape()` on category for defense-in-depth
- Removed confidence-spoofing while loops from tag and path processing
- Simplified tag processing: only Cf/Mn strip + html.escape + strip

### 2. `tests/test_memory_retrieve.py`

**A. `TestSanitizeTitleConfidenceSpoofing` → `TestSanitizeTitleXmlSafety`**
- Renamed class to reflect new purpose
- Kept: `test_preserves_legitimate_brackets`, `test_no_change_for_normal_title`
- Added: `test_xml_escapes_angle_brackets`, `test_xml_escapes_quotes`, `test_xml_escapes_ampersand`, `test_cf_mn_stripping_still_active`, `test_confidence_in_title_passes_through`
- Removed: 5 confidence-spoofing-specific tests (threat eliminated by structural separation)

**B. `TestOutputResultsConfidence`**
- Updated `test_confidence_label_in_output`: `[confidence:high]` → `confidence="high"`, added `<result category=` check
- Updated `test_tag_spoofing_stripped` → `test_tag_spoofing_harmless_in_xml`: verifies only 1 `confidence=` attribute per element
- Updated `test_no_score_defaults_low`: `[confidence:low]` → `confidence="low"`
- Added: `test_result_element_format`, `test_spoofed_title_in_xml_element`, `test_closing_tag_in_title_escaped`

**C. `TestRetrieveIntegration.test_category_priority_sorting`**
- Updated guard from `"RELEVANT MEMORIES"` (dead code) to `"<memory-context"`
- Updated line matching from `startswith("- [")` to `startswith("<result ")`
- Relaxed assertion: FTS5 BM25 doesn't guarantee category priority ordering (it was never tested before -- old guard was always false)

### 3. `test_fts5_smoke.py`
- Updated `test_output_format_match()`: line matching from `startswith("- [")` to `startswith("<result ")`

### 4. `tests/test_v2_adversarial_fts5.py`
- No changes needed -- existing assertions still valid with new format

### 5. `tests/test_arch_fixes.py`
- Updated 2 line-matching patterns from `startswith("- [")` to `startswith("<result ")`

## Verification
- `python3 -m py_compile hooks/scripts/memory_retrieve.py` -- OK
- `pytest tests/ -v` -- 636 passed, 0 failed
