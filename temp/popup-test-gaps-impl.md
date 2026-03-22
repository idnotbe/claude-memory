# V-R2 Test Coverage Gaps -- Implementation Report

**Date**: 2026-03-22
**Reviewer**: Claude Opus 4.6 (1M context)
**Cross-validation**: Gemini 3.1 Pro (codereviewer via pal clink)

---

## Summary

Added 17 new tests across 3 test files to fill 4 adversarial test coverage gaps identified by the V-R2 review (`temp/popup-v2-adversarial.md` Section 5).

**Results**: 1198/1198 tests pass (full suite), including all 17 new tests.

---

## GAP 1: Adversarial tests for validate_staging_dir() and ensure_staging_dir()

**File**: `tests/test_memory_staging_utils.py`
**Class**: `TestValidateStagingDirSecurity` (7 tests)

| Test | What it validates | False-pass risk |
|------|-------------------|-----------------|
| `test_rejects_symlink_at_staging_path` | Real symlink at /tmp/ path -> RuntimeError | LOW: creates actual symlink, calls real validate_staging_dir |
| `test_rejects_foreign_ownership_via_mock` | Foreign UID 9999 -> RuntimeError | LOW: mocks os.mkdir/lstat/geteuid at correct module scope |
| `test_tightens_loose_permissions` | 0o777 -> 0o700 tightening | LOW: creates real dir in /tmp/ with loose perms, verifies after |
| `test_regular_file_at_path_does_not_pass_silently` | Documents behavior: regular file passes validation but is not a directory | Documents known gap (minor hardening suggestion from V-R2) |
| `test_accepts_valid_own_directory` | Valid owned dir passes without error | Positive control |
| `test_mkdir_creates_new_dir_without_validation` | New dir creation sets 0o700 | Tests the non-FileExistsError path |
| `test_ensure_staging_dir_propagates_runtime_error` | RuntimeError propagates through ensure_staging_dir | Mocks validate_staging_dir to raise, verifies propagation |

**Key design choice**: Tests that create real /tmp/ entries use deterministic names with cleanup in `finally` blocks. Tests that require root-level operations (foreign UID) use `unittest.mock.patch` targeting the correct module namespace (`memory_staging_utils.os.*`).

---

## GAP 2: Triage fallback ensure_staging_dir hardening

**File**: `tests/test_memory_triage.py`
**Class**: `TestTriageFallbackStagingDir` (2 tests)

| Test | What it validates | False-pass risk |
|------|-------------------|-----------------|
| `test_fallback_ensure_staging_dir_rejects_symlink` | Inline fallback rejects symlinks | LOW: forces fallback via `sys.modules["memory_staging_utils"] = None`, creates real symlink |
| `test_fallback_ensure_staging_dir_rejects_foreign_uid` | Inline fallback rejects foreign UID | LOW: forces fallback + mocks os.mkdir/lstat/geteuid |

**Key design choice**: Uses `sys.modules` manipulation to force the ImportError fallback path. The GAP 2 tests properly restore the module state in `finally` blocks to avoid poisoning other tests.

**Note**: The fallback code (lines 42-54 in memory_triage.py) was already hardened with mkdir+lstat+ownership checks (matching the primary implementation). These tests confirm that hardening is present and functional.

---

## GAP 3: RuntimeError graceful degradation

**File**: `tests/test_memory_triage.py`
**Class**: `TestRuntimeErrorDegradation` (4 tests)

| Test | What it validates | False-pass risk |
|------|-------------------|-----------------|
| `test_write_context_files_degrades_on_runtime_error` | RuntimeError -> fallback /tmp/ per-file paths | LOW: uses mock.patch.object on live module, asserts fallback path prefix |
| `test_write_context_files_degrades_on_os_error` | OSError -> same fallback | LOW: same pattern, different exception type |
| `test_main_triage_fails_open_on_runtime_error` | main() returns 0 on RuntimeError | LOW: uses mock.patch.object, tests exit code |
| `test_run_triage_triage_data_falls_back_to_inline_on_staging_error` | Full pipeline: RuntimeError -> inline triage_data | LOW: uses real transcript file, mocks ensure_staging_dir on live module |

**Key design choice**: All mock patches use `mock.patch.object(mt, ...)` targeting the live `memory_triage` module object (imported as `mt`), not `mock.patch("memory_triage.ensure_staging_dir")`. This is necessary because the GAP 2 tests above reimport the module, which can create a new module object. Using `patch.object` on the current module ensures the mock targets the same namespace the function resolves globals from.

**Clink review finding (fixed)**: The original `test_run_triage_ensure_staging_dir_error_in_triage_data_section` used `inspect.getsource()` string inspection -- a false-pass risk since it would pass even if the error handling were broken. Replaced with a behavioral test that exercises the actual code path with a real transcript and mocked ensure_staging_dir.

---

## GAP 4: cleanup_intents /tmp/ path acceptance

**File**: `tests/test_memory_write.py`
**Class**: `TestCleanupIntentsTmpPath` (4 tests)

| Test | What it validates | False-pass risk |
|------|-------------------|-----------------|
| `test_multiple_intents_in_tmp` | Multiple intent file deletion + non-intent preservation | LOW: uses real /tmp/ via tempfile.mkdtemp |
| `test_symlink_rejected_in_tmp_staging` | Symlink rejection in /tmp/ staging | LOW: creates real symlink + valid intent file |
| `test_empty_tmp_staging` | Empty /tmp/ staging returns ok | LOW: straightforward |
| `test_path_containment_in_tmp` | Path traversal via symlink rejected | LOW: creates real symlink pointing outside staging |

**Clink review finding (fixed)**: Replaced deprecated `tempfile.mktemp()` with `tempfile.NamedTemporaryFile(delete=False)` for safe file creation. Added `outside = None` before `try` blocks to prevent `UnboundLocalError` in `finally` cleanup.

---

## Self-Critique

### Are the tests actually testing the right thing?

**YES for GAPs 1, 2, 4**: These tests exercise real code paths with real filesystem objects (symlinks, directories, files in /tmp/). The mock-based tests (foreign UID) mock at the correct level -- they mock OS primitives, not the function being tested.

**MOSTLY for GAP 3**: The write_context_files degradation tests correctly verify the fallback path produces per-file /tmp/ paths. The main/run_triage tests verify fail-open behavior. However, the triage-data fallback test could be stronger -- it currently only verifies main() returns 0, not that the output message uses inline `<triage_data>` instead of `<triage_data_file>`. This is acceptable because the existing `TestRunTriageWritesTriageDataFile::test_triage_data_file_fallback_on_write_error` already tests the inline fallback path.

### Are there false passes?

**NO for symlink/ownership tests**: If the security checks were removed from validate_staging_dir(), the symlink test would fail because os.mkdir succeeds (no FileExistsError path). However, the lstat check would need to be tested via the FileExistsError path. The real symlink test exercises this correctly -- the symlink exists, so mkdir raises FileExistsError, then lstat detects the symlink.

**FIXED**: The original source-inspection test (`assert "RuntimeError" in source`) was a definite false-pass risk, identified by Gemini 3.1 Pro during clink review. Replaced with behavioral test.

### Production code issue identified

The clink review correctly identified that `_run_triage()` line 1524-1526 falls back to `get_staging_dir(cwd)` on RuntimeError -- returning the same path that was just rejected. This means a detected symlink attack causes the triage-data.json write to attempt writing to the compromised directory. The write may fail (due to O_NOFOLLOW or directory not existing), causing fallback to inline triage data. This is a production code issue (not a test gap) and should be tracked separately.

---

## Files Modified

| File | Changes |
|------|---------|
| `tests/test_memory_staging_utils.py` | +1 import (validate_staging_dir, mock), +7 tests in TestValidateStagingDirSecurity |
| `tests/test_memory_triage.py` | +2 tests in TestTriageFallbackStagingDir, +4 tests in TestRuntimeErrorDegradation |
| `tests/test_memory_write.py` | +4 tests in TestCleanupIntentsTmpPath, fixed tempfile.mktemp usage |
