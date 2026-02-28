# Phase 1: triage_data Externalization — Implementation Results

## Summary

Successfully implemented triage_data externalization in `memory_triage.py`. The Stop hook now writes triage data to a file (`triage-data.json`) and references it via `<triage_data_file>` tag, with automatic inline `<triage_data>` fallback on write failure.

## Changes Made

### 1. hooks/scripts/memory_triage.py

**New function: `build_triage_data()`** (placed before `format_block_message()`)
- Extracted triage_data dict construction from `format_block_message()` into a standalone helper
- Parameters: `results, context_paths, parallel_config, category_descriptions=None`
- Returns the triage_data dict (categories + parallel_config)
- Used by both `_run_triage()` (file write) and `format_block_message()` (inline fallback)

**Updated function: `format_block_message()`**
- Added `triage_data_path=None` keyword parameter
- When `triage_data_path` is provided: outputs `<triage_data_file>{path}</triage_data_file>`
- When `triage_data_path` is None: calls `build_triage_data()` and outputs inline `<triage_data>` (backwards-compatible fallback)

**Updated function: `_run_triage()`** (output section)
- After `write_context_files()`: builds triage_data via `build_triage_data()`
- Atomic write to `.claude/memory/.staging/triage-data.json` using tmp+os.replace pattern (O_CREAT|O_WRONLY|O_TRUNC|O_NOFOLLOW, 0o600)
- On OSError: sets `triage_data_path = None` (triggers inline fallback)
- Passes `triage_data_path` to `format_block_message()`

### 2. tests/test_memory_triage.py

**New import:** `build_triage_data`

**New test class: `TestBuildTriageData`** (7 tests)
- `test_build_triage_data_basic_structure` — correct top-level keys and values
- `test_build_triage_data_includes_descriptions` — descriptions passed through
- `test_build_triage_data_no_description_when_absent` — omitted when not provided
- `test_build_triage_data_parallel_config_defaults` — defaults for missing config keys
- `test_build_triage_data_no_context_path` — omits context_file when absent
- `test_build_triage_data_json_serializable` — output roundtrips through JSON

**New test class: `TestFormatBlockMessageTriageDataPath`** (4 tests)
- `test_format_block_message_with_triage_data_path` — outputs `<triage_data_file>` tag
- `test_format_block_message_without_triage_data_path` — inline `<triage_data>` fallback
- `test_format_block_message_default_is_inline` — default kwarg produces inline
- `test_format_block_message_file_path_with_descriptions` — file mode + descriptions

**New test class: `TestRunTriageWritesTriageDataFile`** (2 tests)
- `test_triage_data_file_written` — e2e: _run_triage() creates triage-data.json + references in output
- `test_triage_data_file_fallback_on_write_error` — e2e: mocked OSError falls back to inline

### 3. tests/test_adversarial_descriptions.py

**No changes needed.** All adversarial tests call `format_block_message()` without `triage_data_path`, so they exercise the inline fallback path. All 69 adversarial tests pass unchanged.

### 4. CLAUDE.md

Updated two references:
- Hook table: "outputs structured `<triage_data>` JSON" -> "writes `triage-data.json` to staging (file-based `<triage_data_file>` with inline `<triage_data>` fallback)"
- Parallel processing section: Updated item 2 to describe file-based output with fallback

## Test Results

- **981 tests passed** (0 failures)
- **13 new tests** added (7 build_triage_data + 4 format_block_message + 2 _run_triage e2e)
- Compile check: clean (`python3 -m py_compile` passes)

## Cross-Validation (PAL clink)

**Codex:** Rate-limited, unable to review.

**Gemini (gemini-3.1-pro-preview):** Reviewed and identified 3 actionable issues, all fixed:

1. **High: Static tmp filename race condition** -- Fixed by appending PID: `f"{triage_data_path}.{os.getpid()}.tmp"`
2. **Medium: os.write() short writes** -- Fixed by using `os.fdopen(fd, "w")` + `json.dump()` (same pattern as existing context file writes)
3. **Medium: Stale tmp file on error** -- Fixed by adding `os.unlink(tmp_path)` in the except block

Item 4 (redundant re-computation on fallback) was noted as Low and intentionally not addressed to keep `format_block_message()` self-contained and independently testable.

## Issues Found

None blocking. All existing tests continued to pass without modification because:
1. The inline fallback path is backwards-compatible
2. All existing tests call `format_block_message()` without `triage_data_path`
3. The `build_triage_data()` extraction is a pure refactor of existing logic

All 3 Gemini-identified issues were fixed and re-validated (981 tests pass).
