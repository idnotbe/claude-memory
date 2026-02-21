# Hook-Fixer Report: memory_triage.py Changes

## Summary

Applied R2-triage (staging paths) and R3 (sentinel idempotency) fixes to `hooks/scripts/memory_triage.py`. All 56 tests pass.

## Changes Made

### R2-triage: Context files moved to project-local staging directory

**File: `hooks/scripts/memory_triage.py`**

1. **`write_context_files()` (line 682)** -- Added `cwd: str = ""` keyword parameter. When `cwd` is provided, context files are written to `{cwd}/.claude/memory/.staging/context-{cat_lower}.txt`. Falls back to `/tmp/` when `cwd` is empty (backward compatibility for tests calling without `cwd`).

2. **Staging directory creation (line 702-709)** -- Creates `.claude/memory/.staging/` via `os.makedirs(staging_dir, exist_ok=True)`. Falls back to `/tmp/` on OSError.

3. **Score log path (line 994-999)** -- Changed from hardcoded `/tmp/.memory-triage-scores.log` to `{cwd}/.claude/memory/.staging/.triage-scores.log`, with `/tmp/` fallback on directory creation failure.

4. **Call site in `_run_triage()` (line ~1035)** -- Updated `write_context_files()` call to pass `cwd=cwd`.

### R3: Sentinel-based idempotency

**File: `hooks/scripts/memory_triage.py`**

1. **Sentinel check (line 951-958)** -- After `check_stop_flag()`, checks if `{cwd}/.claude/memory/.staging/.triage-handled` exists and is < 300 seconds old. If so, returns 0 (allow stop) to prevent duplicate triage firing.

2. **Sentinel creation (line 1022-1031)** -- When blocking (results found), creates/touches the sentinel file using secure `os.open()` with `O_CREAT|O_WRONLY|O_TRUNC|O_NOFOLLOW` and `0o600` permissions.

### Test updates

**File: `tests/test_memory_triage.py`**

1. **`test_score_log_written`** -- Updated to check the new staging path `{cwd}/.claude/memory/.staging/.triage-scores.log` instead of `/tmp/.memory-triage-scores.log`.

## Backward Compatibility

- `write_context_files()` defaults `cwd=""`, so existing callers without `cwd` still work (fall back to `/tmp/`).
- All 56 existing tests pass without modification (except the score log test which was updated for the new path).
- The sentinel check uses `OSError` catch so it gracefully handles missing `.staging/` directories.

## Test Results

```
56 passed in 0.15s
```

## Security Notes

- Sentinel file uses `O_NOFOLLOW` to prevent symlink attacks.
- Sentinel file uses `0o600` permissions (owner read/write only).
- Directory creation uses `exist_ok=True` to avoid TOCTOU races.
- All file operations are wrapped in try/except OSError for fail-open behavior.
