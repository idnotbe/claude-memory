# Config + Triage Hook Implementation Notes

**Task:** #1 -- Implement config schema + triage hook changes
**Date:** 2026-02-16
**Author:** config-hook-dev

---

## Files Modified

### 1. `assets/memory-config.default.json`

Added `triage` section (lines 52-73) with:
- `enabled`, `max_messages`, `thresholds` (documenting existing hook defaults)
- `parallel` sub-section with:
  - `enabled: true`
  - `category_models`: per-category model mapping (haiku/sonnet)
  - `verification_model: "sonnet"`
  - `default_model: "haiku"`

### 2. `hooks/scripts/memory_triage.py`

Four categories of changes, all stdlib-only:

#### A. Config loading (`load_config()` + helpers, lines 466-588)

- New constants: `VALID_MODELS`, `DEFAULT_PARALLEL_CONFIG`, `VALID_CATEGORY_KEYS`
- `load_config()` now returns a `parallel` key alongside existing `enabled`, `max_messages`, `thresholds`
- `_deep_copy_parallel_defaults()`: safe copy factory to avoid shared mutable state
- `_parse_parallel_config()`: validates model values against `VALID_MODELS` set, falls back to defaults for invalid values

**Validation rules:**
- Model values must be in `{"haiku", "sonnet", "opus"}` -- invalid values silently fall back to defaults
- `category_models` only accepts keys in `VALID_CATEGORY_KEYS` (the 6 known categories)
- `enabled` is coerced to bool
- If `triage.parallel` is missing entirely, full defaults are used

#### B. Context file generation (lines 591-700)

New functions:
- `_find_match_line_indices()`: finds lines where primary patterns match for a category
- `_extract_context_excerpt()`: extracts +/- 10 lines around matches, merges overlapping windows, separates non-adjacent excerpts with `---`
- `write_context_files()`: writes per-category context to `/tmp/.memory-triage-context-<CATEGORY>.txt`

**Context file contents:**
- Text categories: category name, score, generous transcript excerpts around keyword matches, key snippets
- SESSION_SUMMARY: category name, score, activity metrics (tool uses, distinct tools, exchanges)

**Design decisions:**
- Context window is 10 lines (not the 4-line co-occurrence window) to give subagents enough surrounding context
- Overlapping windows are merged to avoid duplicate content
- OSError on write is caught and silently ignored (non-critical -- subagent can still work)

#### C. Structured JSON output (`format_block_message()`, lines 727-793)

- `format_block_message()` now takes `context_paths` and `parallel_config` parameters
- Human-readable message is preserved above the `<triage_data>` block (backwards compat)
- `<triage_data>` JSON block contains:
  - `categories[]`: each with `category`, `score`, optional `context_file`
  - `parallel_config`: `enabled`, `category_models`, `verification_model`, `default_model`
- Scores are `round()`ed to 4 decimal places in the JSON

#### D. Main flow (`_run_triage()`, lines 863-877)

- After `run_triage()` returns results, calls `write_context_files()` before `format_block_message()`
- Passes `parallel_config` from loaded config to `format_block_message()`

---

## Backwards Compatibility

1. **No config file**: `load_config()` returns full defaults including `parallel` defaults
2. **Config without `triage` section**: same as above
3. **Config with `triage` but without `parallel`**: parallel defaults are used
4. **Old consumers of stderr**: human-readable message is still the first part of output; `<triage_data>` is appended after
5. **All 229 existing tests pass**: verified across all 7 test files

---

## Testing

- Python syntax verified: `python3 -m py_compile hooks/scripts/memory_triage.py`
- 9 manual smoke tests covering:
  - `_parse_parallel_config` with valid, invalid, and missing input
  - Context file generation for text categories and SESSION_SUMMARY
  - `format_block_message` structured output parsing
  - Human-readable message preservation
  - `_find_match_line_indices` and `_extract_context_excerpt` with range merging
- All 229 existing tests pass (no regressions)

---

## Security Notes

- Context files written to `/tmp/` with predictable names -- this is acceptable since they contain transcript content that is already available to the agent
- No new prompt injection vectors: the `<triage_data>` block is generated from internal state, not from user-controlled input
- Snippet sanitization (`_sanitize_snippet`) is still applied to the human-readable portion
- Model values are validated against a fixed allowlist (`VALID_MODELS`)
