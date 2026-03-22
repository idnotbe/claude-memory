# Test Gap Briefing (V-R2 Adversarial Review)

## Source
From eliminate-all-popups.md action plan, 4 test gaps identified by V-R2 adversarial reviewer.

## Working Tree State
The following files have **unstaged changes** with code fixes already applied but tests incomplete:
- `hooks/scripts/memory_staging_utils.py` — refactored to `_validate_existing_staging()` helper, added S_ISDIR check, legacy path defense
- `hooks/scripts/memory_write.py` — added `_is_valid_legacy_staging()`, RuntimeError graceful degradation in `write_save_result()`, O_EXCL sentinel
- `hooks/scripts/memory_triage.py` — pattern fixes, session check `continue` vs `return False`
- `tests/test_memory_staging_utils.py` — updated S_ISDIR test (committed version documents missing check; working tree tests the fix)
- `tests/test_memory_write.py` — added `TestLegacyStagingValidation` class, updated fixture paths

## GAP 1: ensure_staging_dir() / validate_staging_dir() Security Tests

**What's missing**: The committed tests don't verify the S_ISDIR check (the test documents its *absence*). Working tree has the fix + updated test but it's unstaged.

**Code location**: `hooks/scripts/memory_staging_utils.py` lines 63-94 (`_validate_existing_staging()`)

**What to test**:
- Symlink at staging path -> RuntimeError (already tested, verify committed)
- Foreign UID ownership -> RuntimeError via mock (already tested)
- S_ISDIR check: regular file at path -> RuntimeError "not a directory" (working tree has this)
- Permission tightening: 0o777 -> 0o700 (already tested)
- ensure_staging_dir() propagates RuntimeError (already tested)
- Legacy path branch: symlink, ownership, permissions, parent creation (already tested)

**Assessment**: Tests exist in working tree but need to be committed. Verify completeness.

## GAP 2: Triage Fallback Path Tests

**What's missing**: When `ensure_staging_dir()` fails in `_run_triage()`, it falls back to `get_staging_dir()` (which returns the path without creating/validating). This fallback reuses the *rejected path*, meaning triage-data.json write will fail (directory doesn't exist). The fallback to inline triage data kicks in, but this path is untested.

**Code location**: `hooks/scripts/memory_triage.py` lines 1523-1552

```python
try:
    _staging_dir = ensure_staging_dir(cwd)
except (OSError, RuntimeError):
    _staging_dir = get_staging_dir(cwd)  # Returns path that may not exist
triage_data["staging_dir"] = _staging_dir
triage_data_path = os.path.join(_staging_dir, "triage-data.json")
# ... write attempt ...
except Exception:
    triage_data_path = None  # Fallback to inline
```

**What to test**:
- Mock `ensure_staging_dir` to raise RuntimeError -> verify `_staging_dir` falls back to `get_staging_dir()` result
- When directory doesn't exist, triage-data.json write fails -> `triage_data_path = None` (inline fallback)
- format_block_message receives `triage_data_path=None` -> inline `<triage_data>` tag used instead of file reference

Also in `write_context_files()` (line 707-721):
```python
ensure_staging_dir(cwd)  # line 709
# ... later writes context files to staging ...
except (OSError, RuntimeError):
    pass  # Silently skipped
```

**What to test**:
- Mock `ensure_staging_dir` to raise RuntimeError -> `write_context_files()` returns empty dict (no context files)
- Triage still outputs valid block message without context files

## GAP 3: RuntimeError Graceful Degradation Tests

**What's missing**: `write_save_result()` in memory_write.py now catches RuntimeError from validate_staging_dir and returns error status. This is new in the working tree diff.

**Code location**: `hooks/scripts/memory_write.py` lines 714-716 (working tree)

```python
except (RuntimeError, OSError) as e:
    return {"status": "error", "message": f"Staging dir validation failed: {e}"}
```

**What to test**:
- `write_save_result()` with a staging dir that triggers RuntimeError (symlink) -> returns `{"status": "error", ...}` instead of crashing
- Verify the error message includes the RuntimeError detail

Also check other callers:
- `update_sentinel_state()` — does it handle RuntimeError? (Need to verify)

## GAP 4: cleanup_intents /tmp/ Path Acceptance Tests

**What's missing**: `cleanup_intents()` accepts both /tmp/ and legacy paths, but the test fixture was broken — it tried to create `/tmp/` paths but fell back to legacy. The working tree fixes the fixture but still uses legacy paths because pytest `tmp_path` doesn't resolve to `/tmp/.claude-memory-staging-*`.

**Code location**: `hooks/scripts/memory_write.py` lines 585-633

**What to test**:
- cleanup_intents with actual `/tmp/.claude-memory-staging-*` path (use real /tmp/ in test)
- cleanup_intents with legacy `.claude/memory/.staging` path (already partially tested)
- cleanup_intents with invalid path (neither /tmp/ nor legacy) -> returns error
- cleanup_intents with /tmp/ path containing intent-*.json files -> deletes them
- Edge case: symlink intent file inside staging -> rejected (errors list)

## File Map

| File | Tests To Add/Verify |
|------|---------------------|
| tests/test_memory_staging_utils.py | GAP 1: Verify committed + working tree tests comprehensive |
| tests/test_memory_triage.py | GAP 2: Triage fallback path when ensure_staging_dir fails |
| tests/test_memory_write.py | GAP 3: write_save_result RuntimeError degradation; GAP 4: cleanup_intents /tmp/ actual path |
