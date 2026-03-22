# GAP 4 Implementation Results: cleanup_intents/cleanup_staging /tmp/ Path Tests

## Status: COMPLETE -- All tests passing

## What Was Done

Added 7 new tests across 2 test classes in `tests/test_memory_write.py` to cover the /tmp/ path acceptance gap identified by V-R2 adversarial review.

### Tests Added to `TestCleanupIntentsTmpPath` (existing class)

| Test | What It Verifies |
|------|-----------------|
| `test_rejects_invalid_tmp_path` | `/tmp/evil-dir-*` (non-staging prefix) returns `{"status": "error"}` and does NOT delete files |
| `test_rejects_arbitrary_memory_staging` | `/tmp/evil-*/memory/.staging` (no `.claude` ancestor) returns error and does NOT delete files |

### New Class: `TestCleanupStagingTmpPath`

| Test | What It Verifies |
|------|-----------------|
| `test_cleanup_staging_accepts_real_tmp_path` | Real `/tmp/.claude-memory-staging-*` dir: deletes context-*, triage-data.json, .triage-pending.json, intent-*; preserves non-matching files (last-save-result.json) |
| `test_cleanup_staging_rejects_invalid_tmp_path` | `/tmp/evil-dir-*` (non-staging prefix) returns error, no file deletion |
| `test_cleanup_staging_rejects_arbitrary_memory_staging` | `/tmp/evil-*/memory/.staging` (no `.claude` ancestor) returns error, no file deletion |
| `test_cleanup_staging_symlink_skipped_in_tmp` | Symlink context file in /tmp/ staging is skipped (not followed), real context file is deleted, outside target preserved |
| `test_cleanup_staging_empty_tmp_dir` | Empty /tmp/ staging returns `{"status": "ok", "deleted": [], "errors": [], "skipped": 0}` |

### Import Change

Added `cleanup_staging` to the import block from `memory_write`.

## Pre-existing Tests (Already Present)

The `TestCleanupIntentsTmpPath` class already had 4 tests covering the happy path:
- `test_multiple_intents_in_tmp` -- accepts real /tmp/ path, deletes multiple intents
- `test_symlink_rejected_in_tmp_staging` -- symlink intent in /tmp/ staging rejected
- `test_empty_tmp_staging` -- empty /tmp/ staging returns ok
- `test_path_containment_in_tmp` -- path traversal via symlink rejected

## Test Results

```
12 passed, 127 deselected in 0.31s
```

All new and pre-existing /tmp/ path tests pass.

## Key Design Decisions

1. **Real /tmp/ directories**: Tests use `tempfile.mkdtemp(prefix=".claude-memory-staging-")` to create actual `/tmp/` directories, exercising the real `startswith("/tmp/.claude-memory-staging-")` code path that pytest `tmp_path` cannot reach.

2. **Always-cleanup pattern**: All tests use `try/finally` with `shutil.rmtree(staging, ignore_errors=True)` to ensure /tmp/ cleanup even on assertion failures.

3. **Parallel structure**: `TestCleanupStagingTmpPath` mirrors `TestCleanupIntentsTmpPath` to ensure both cleanup functions have consistent /tmp/ path coverage (accept valid, reject invalid prefix, reject fake legacy, reject symlinks).
