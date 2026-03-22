# GAP 1 Audit Results: staging security tests

## Summary

All 12 required test cases verified present and passing. One additional test added for completeness.

## Test Coverage Matrix

| # | Required Test Case | Test Name | Status |
|---|---|---|---|
| 1 | Symlink at /tmp/ staging path -> RuntimeError "symlink" | `test_rejects_symlink_at_staging_path` | PASS (pre-existing) |
| 2 | Foreign UID ownership -> RuntimeError "owned by uid" | `test_rejects_foreign_ownership_via_mock` | PASS (pre-existing) |
| 3 | S_ISDIR: regular file at path -> RuntimeError "not a directory" | `test_regular_file_at_path_raises_runtime_error` | PASS (pre-existing) |
| 4 | Permission tightening: 0o777 -> 0o700 | `test_tightens_loose_permissions` | PASS (pre-existing) |
| 5 | Valid directory passes without error | `test_accepts_valid_own_directory` | PASS (pre-existing) |
| 6 | New directory created with correct permissions | `test_mkdir_creates_new_dir_without_validation` | PASS (pre-existing) |
| 7 | ensure_staging_dir() propagates RuntimeError | `test_ensure_staging_dir_propagates_runtime_error` | PASS (pre-existing) |
| 8 | Legacy path: symlink -> RuntimeError | `test_legacy_staging_rejects_symlink` | PASS (pre-existing) |
| 9 | Legacy path: foreign ownership -> RuntimeError | `test_legacy_staging_rejects_wrong_owner` | PASS (pre-existing) |
| 10 | Legacy path: permission tightening | `test_legacy_staging_fixes_permissions` | PASS (pre-existing) |
| 11 | Legacy path: parent directory creation | `test_legacy_staging_creates_parents` | PASS (pre-existing) |
| 12 | Legacy path: idempotent calls | `test_legacy_staging_idempotent` | PASS (pre-existing) |

## Added Test

| # | Test Case | Test Name | Rationale |
|---|---|---|---|
| 13 | Legacy path: S_ISDIR regular file -> RuntimeError "not a directory" | `test_legacy_staging_rejects_regular_file` | Mirror of /tmp/ S_ISDIR test (#3) for legacy branch. Both branches call `_validate_existing_staging()` on FileExistsError, so this ensures the legacy code path exercises the S_ISDIR rejection too. |

## Test Run

```
33 passed in 0.15s
```

All 33 tests pass (7 get_staging_dir + 5 ensure_staging_dir + 8 is_staging_path + 7 /tmp/ security + 6 legacy security).

## Code Under Test

- `_validate_existing_staging()`: lines 63-94 of memory_staging_utils.py -- 4 checks (symlink, S_ISDIR, UID, perms), all exercised by tests for both /tmp/ and legacy branches.
- `validate_staging_dir()`: lines 97-126 -- both branches (line 111 if/else) covered. Fresh mkdir path and FileExistsError->validation path both tested.
- `ensure_staging_dir()`: lines 41-60 -- delegates to validate_staging_dir, RuntimeError propagation tested.

## Assessment

Coverage is comprehensive. No remaining gaps for GAP 1.
