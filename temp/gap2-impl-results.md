# GAP 2 Implementation Results: Triage Fallback Path Tests

## Status: DONE

## Tests Added

New class `TestTriageFallbackPaths` appended to `tests/test_memory_triage.py` (after line 3015 of the original file).

### 1. `test_run_triage_fallback_when_ensure_staging_fails`

**What it covers**: The full fallback chain in `_run_triage()` when `ensure_staging_dir()` raises RuntimeError:
1. `ensure_staging_dir()` raises RuntimeError -> falls back to `get_staging_dir()`
2. `get_staging_dir()` returns a nonexistent path (`/tmp/.claude-memory-staging-doesnotexist999`)
3. triage-data.json write fails (directory doesn't exist) -> `triage_data_path=None`
4. `format_block_message` uses inline `<triage_data>` instead of `<triage_data_file>`

**Key mocks**: `read_stdin`, `check_stop_flag`, `run_triage` (forces DECISION result), `ensure_staging_dir` (raises RuntimeError), `get_staging_dir` (returns nonexistent path). All mocked via `mock.patch.object(mt, ...)` to ensure correct namespace targeting.

**Assertions**: Valid JSON stdout, `decision=block`, inline `<triage_data>` present, `<triage_data_file>` absent, inline JSON is valid with `categories` and `parallel_config` keys, human-readable part intact.

### 2. `test_write_context_files_returns_empty_on_staging_failure`

**What it covers**: When `ensure_staging_dir()` raises RuntimeError AND the per-file `/tmp/.memory-triage-context-*` fallback writes also fail (simulating completely unavailable /tmp/ filesystem), `write_context_files()` returns empty dict.

**Key mocks**: `ensure_staging_dir` (raises RuntimeError setting `staging_dir=""`), `os.open` (raises OSError for context file paths).

**Assertions**: Return value is exactly `{}`.

### 3. `test_triage_data_path_none_triggers_inline_fallback`

**What it covers**: Unit test for `format_block_message()` with `triage_data_path=None` and multiple categories + descriptions. Verifies the inline fallback produces correct structured output.

**Key setup**: Two triggered categories (DECISION, CONSTRAINT) with descriptions. No mocks needed -- direct function call.

**Assertions**: `<triage_data>` present, `<triage_data_file>` absent, inline JSON valid with both categories (lowercased: `decision`, `constraint`), `parallel_config` present, descriptions appear in human-readable section.

## Issues Encountered During Implementation

1. **stdin mock**: Initially called `_run_triage()` directly without mocking `read_stdin`, causing pytest's captured stdin to fail on `fileno()`. Fixed by using `mock.patch.object(mt, "read_stdin", ...)` pattern consistent with `TestRunTriageWritesTriageDataFile`.

2. **Category name casing**: `build_triage_data()` lowercases category names (line 1276: `"category": cat_lower`), so assertions needed `"decision"` not `"DECISION"`.

## Test Run

```
pytest tests/test_memory_triage.py -v -k "Fallback" --tb=short
# 10 passed (3 new + 7 existing matching "Fallback"), 124 deselected
```
