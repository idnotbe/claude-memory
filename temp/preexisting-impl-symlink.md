# Implementation Log: Staging Dir Symlink/Permission Bypass Fix

**Bug**: `validate_staging_dir()` legacy path branch (line 92) used `os.makedirs(staging_dir, mode=0o700, exist_ok=True)` which:
1. Follows symlinks silently (attacker can redirect writes to arbitrary location)
2. Doesn't check ownership (attacker-created dir accepted as valid)
3. Doesn't fix permissions (0o777 stays 0o777)

The /tmp/ path branch already had proper defense via `os.mkdir()` + `os.lstat()` validation.

## Changes Made

### `hooks/scripts/memory_staging_utils.py`

**Extracted `_validate_existing_staging()` helper** (review recommendation: eliminate code duplication between branches):
- `os.lstat()` to detect symlinks without following them
- `stat.S_ISLNK()` check -- raises RuntimeError on symlink
- `stat.S_ISDIR()` check -- raises RuntimeError on non-directory (new: regular files at staging path were silently accepted before)
- `st.st_uid != os.geteuid()` ownership check -- raises RuntimeError on foreign owner
- Permission tightening: `os.chmod(staging_dir, 0o700)` if `st.st_mode & 0o077`
- TOCTOU comment explaining why the chmod race window is practically unexploitable

**Fixed legacy path branch** in `validate_staging_dir()`:
- `os.makedirs(parent, mode=0o700, exist_ok=True)` for parent dirs only (`.claude/memory/`)
- `os.mkdir(staging_dir, 0o700)` for the final `.staging` component (atomic create)
- On `FileExistsError`: calls shared `_validate_existing_staging()` helper

Both branches now use the same shared validation helper, preventing future divergence.

### `tests/test_memory_staging_utils.py`

**New test class `TestValidateStagingDirLegacyPath`** with 5 tests:
- `test_legacy_staging_rejects_symlink` -- symlink at legacy staging path raises RuntimeError
- `test_legacy_staging_fixes_permissions` -- world-readable dir tightened to 0o700
- `test_legacy_staging_rejects_wrong_owner` -- foreign UID raises RuntimeError (mocked)
- `test_legacy_staging_creates_parents` -- parent dirs created when missing
- `test_legacy_staging_idempotent` -- calling twice on legacy path works without error

**Updated existing test**:
- `test_regular_file_at_path_does_not_pass_silently` -> `test_regular_file_at_path_raises_runtime_error` -- now asserts RuntimeError is raised for the new S_ISDIR check

## Review Findings (Gemini clink)

| Finding | Severity | Resolution |
|---------|----------|------------|
| Missing S_ISDIR validation | Medium | Fixed: added to shared helper |
| Code duplication | Low | Fixed: extracted `_validate_existing_staging()` |
| TOCTOU in chmod | Low | Acknowledged with comment (unexploitable) |
| FileNotFoundError race | Low | Accepted: callers catch OSError (parent class), fail-open by design |

## Test Results

- Compile check: OK
- Staging utils tests: 32/32 passed
- Full test suite: 1213/1213 passed
