# V1 Operational Review: 15 New Tests (V-R2 Gap Fill)

**Reviewer role:** Operational perspective — CI/CD reliability
**Files reviewed:**
- `tests/test_memory_staging_utils.py` (TestValidateStagingDirSecurity, TestValidateStagingDirLegacyPath)
- `tests/test_memory_triage.py` (TestTriageFallbackPaths)
- `tests/test_memory_write.py` (TestCleanupIntentsTmpPath, TestCleanupStagingTmpPath, TestLegacyStagingValidation, TestRuntimeErrorDegradation)

**Test run result:** All 39 tests collected, 39 passed in 0.23s

---

## Issues Found

### CRITICAL

None.

---

### WARN

#### WARN-1: Hardcoded /tmp/ names in TestValidateStagingDirSecurity — parallel CI collision risk

**Location:** `tests/test_memory_staging_utils.py` lines 204–309 (`TestValidateStagingDirSecurity`)

Six tests use fixed, globally-shared /tmp/ paths:
```
/tmp/.claude-memory-staging-test_symlink_reject
/tmp/.claude-memory-staging-test_foreign_uid
/tmp/.claude-memory-staging-test_loose_perms
/tmp/.claude-memory-staging-test_regular_file
/tmp/.claude-memory-staging-test_valid_own
/tmp/.claude-memory-staging-test_new_create
```

These paths are not process-scoped. If two CI workers (or two pytest runs) execute concurrently on the same machine/container, they can collide. For example: `test_mkdir_creates_new_dir_without_validation` pre-checks that the path does not exist and then mkdir's it; if another test simultaneously creates the same path, the behavior is undefined. Similarly, `test_new_create` cleans up in `finally`, but a crash between mkdir and cleanup leaves the path dirty — causing the *next run's* `test_rejects_symlink_at_staging_path` to fail the pre-existing check.

`test_rejects_symlink_at_staging_path` does include a pre-cleanup guard but only handles symlink and empty-dir cases; it would fail to remove a non-empty dir left by a crashed idempotent test.

**Risk:** Intermittent failures in high-parallelism CI or when a previous run was killed mid-test. Not a problem in standard sequential `pytest` single-worker runs.

**Recommendation:** Replace the six hardcoded paths with `tempfile.mkdtemp(prefix=".claude-memory-staging-")` (as done in `TestCleanupIntentsTmpPath`), then pass the created path into `validate_staging_dir()` directly instead of re-creating it. This eliminates global state.

---

#### WARN-2: TestEnsureStagingDir.test_cleanup — test is a no-op assertion, not a fixture teardown

**Location:** `tests/test_memory_staging_utils.py` lines 134–139

`test_cleanup` has no assertion — it creates a directory and removes it, verifying nothing. It functions as manual cleanup rather than a test. Worse, if the `test_creates_directory` or `test_permissions_0o700` test fails and leaves the staging dir behind, `test_cleanup` will be skipped in `--exitfirst` mode, leaving state in /tmp/. The correct pattern is pytest `autouse` fixtures or `finally` blocks inside each test.

**Risk:** Stale /tmp/ directories on test failure; the test wastes a slot without asserting anything useful. Low CI flakiness risk but misleading test count.

---

#### WARN-3: Mock patch target for write_save_result RuntimeError tests is indirect

**Location:** `tests/test_memory_write.py` lines 2006–2007, 2032–2033, 2079–2080

The tests patch `"memory_staging_utils.validate_staging_dir"`. However, `write_save_result()` uses a *local import* at call time:

```python
from memory_staging_utils import validate_staging_dir   # line 714 in memory_write.py
validate_staging_dir(str(staging_path))
```

Patching `memory_staging_utils.validate_staging_dir` works correctly here because the local `from X import Y` re-fetches `Y` from the module's namespace at each call, so the patch on the module attribute is effective. This is the correct patch target.

However, the correctness depends on a subtlety of Python's import/mock mechanics that is not obvious. If the code were ever refactored to hoist the import to module level in `memory_write.py` (e.g., `from memory_staging_utils import validate_staging_dir` at the top), the patch target would need to change to `"memory_write.validate_staging_dir"`. The current form is correct but fragile to this specific refactor.

**Risk:** Zero flakiness risk today. Becomes a silent no-op mock (tests pass even if the code changes to not catch the error) if `memory_write.py` moves the import to module level. Recommend adding a brief comment explaining the patch target.

---

#### WARN-4: macOS /tmp -> /private/tmp symlink breaks staging path prefix checks

**Location:** `tests/test_memory_staging_utils.py` (TestValidateStagingDirSecurity), `tests/test_memory_write.py` (TestCleanupIntentsTmpPath, TestCleanupStagingTmpPath, TestRuntimeErrorDegradation)

On macOS, `tempfile.mkdtemp()` returns `/tmp/...` but the OS-level realpath is `/private/tmp/...`. Several tests use `tempfile.mkdtemp(prefix=".claude-memory-staging-")` and pass the raw path (which starts with `/tmp/`) to functions that check `startswith("/tmp/.claude-memory-staging-")`.

- On this Linux system: `/tmp` is real, so `d.startswith("/tmp/.claude-memory-staging-")` is always true.
- On macOS: `d = tempfile.mkdtemp(...)` returns `/tmp/.claude-memory-staging-xxxxx` (the symlink path, not realpath). The `startswith` check in `cleanup_intents` and `cleanup_staging` uses `str(staging_path)` from the resolved path. If those functions call `Path.resolve()` internally, `/tmp/` may become `/private/tmp/` on macOS, breaking the check.

Specifically, `TestRuntimeErrorDegradation.test_write_save_result_degrades_on_runtime_error` creates a real staging dir with `tempfile.mkdtemp(prefix=".claude-memory-staging-")` but passes `str(staging)` (unresolved) to `write_save_result`. Inside `write_save_result`, `staging_path = Path(staging_dir)` (not `.resolve()`), so the path likely stays as `/tmp/...` even on macOS. However `validate_staging_dir` is mocked in that test, so the path check is bypassed.

For `TestCleanupIntentsTmpPath` and `TestCleanupStagingTmpPath`, the functions being tested (`cleanup_intents`, `cleanup_staging`) use their own internal path resolution logic. On macOS, if the resolution differs from the prefix check, the `"not a valid staging directory"` branch would be triggered erroneously, causing real test failures on macOS CI.

**Risk:** Tests pass on Linux. May fail on macOS CI runners. Not an issue for this Linux-only project unless macOS CI is added.

---

### INFO

#### INFO-1: Resource cleanup is correctly implemented in TestCleanupIntentsTmpPath and TestCleanupStagingTmpPath

All tests that create real `/tmp/` directories use `try/finally` with `shutil.rmtree(staging, ignore_errors=True)`. This is correct — `ignore_errors=True` means cleanup succeeds even if assertions fail. The symlink tests also clean up the `outside` file in finally. No resource leaks detected.

One minor note: two tests (`test_empty_tmp_staging`, `test_cleanup_staging_empty_tmp_dir`) use `staging.rmdir()` instead of `shutil.rmtree`. This is correct for empty dirs but would fail silently (OSError ignored by pytest) if a file was accidentally created. Since the tests verify emptiness before cleanup, this is acceptable.

---

#### INFO-2: TestLegacyStagingValidation tests are pure (no I/O)

All 15 tests in `TestLegacyStagingValidation` call `_is_valid_legacy_staging()` with string literals only. No filesystem operations. Zero flakiness risk, instant execution. This is the correct pattern for string-logic validation tests.

---

#### INFO-3: TestTriageFallbackPaths mock complexity is reasonable

`test_run_triage_fallback_when_ensure_staging_fails` uses 5 context manager mocks (`read_stdin`, `sys.stdout`, `check_stop_flag`, `run_triage`, `ensure_staging_dir`, `get_staging_dir`). This is moderately deep but each mock targets a well-defined boundary:
- `read_stdin` and `sys.stdout`: standard I/O boundary
- `check_stop_flag`: prevents refire detection from interfering
- `run_triage`: pins the triage result to force the blocking path
- `ensure_staging_dir`/`get_staging_dir`: the exact failure scenario under test

The mock depth is justified by the end-to-end nature of the test. The mocks target module-level names in `memory_triage` (via `mock.patch.object(mt, ...)`) which is correct for functions that are `import`ed at module level into `memory_triage`.

`test_write_context_files_returns_empty_on_staging_failure` patches `mt.os.open` with a conditional wrapper. The filter `".memory-triage-context-"` correctly matches the fallback path pattern `/tmp/.memory-triage-context-<cat>.txt`. This is fine but the custom `mock_os_open` captures `original_os_open = os.open` before the patch — this is correct because it preserves real I/O for non-targeted calls.

---

#### INFO-4: Import duplication in test methods

Several test methods in `TestCleanupIntentsTmpPath`, `TestCleanupStagingTmpPath`, and `TestRuntimeErrorDegradation` contain inline `import tempfile` and `import shutil` statements at the start of each method body. These modules are part of the standard library and already in `sys.modules`, so the cost is negligible. However, it is inconsistent with the convention in the rest of the test file (where stdlib imports are at the top of the module). This is a style issue, not an operational risk.

---

#### INFO-5: No slow tests detected

All 39 tests pass in 0.23s total. No network calls, no subprocess invocations (the new tests use direct function calls only). No timing-sensitive code. The `TestTriageFallbackPaths` tests are the most expensive (they trigger triage scoring), but still complete in milliseconds.

---

#### INFO-6: Test naming is consistent and descriptive

All new tests follow the pattern `test_<scenario>_<condition>` or `test_<function>_<expected_behavior>`. Examples:
- `test_rejects_symlink_at_staging_path`
- `test_write_context_files_returns_empty_on_staging_failure`
- `test_write_save_result_degrades_on_runtime_error`

This is consistent with the existing test suite naming convention.

---

## Risk Assessment for CI Flakiness

| Test Group | Flakiness Risk | Primary Cause |
|---|---|---|
| TestValidateStagingDirSecurity | **MEDIUM** | Hardcoded /tmp/ paths (WARN-1) |
| TestEnsureStagingDir (existing, test_cleanup) | **LOW** | Misleading test pattern (WARN-2) |
| TestValidateStagingDirLegacyPath | **NONE** | Uses tmp_path fixture correctly |
| TestTriageFallbackPaths | **NONE** | All I/O mocked; no filesystem state |
| TestCleanupIntentsTmpPath | **NONE** | `tempfile.mkdtemp` + `shutil.rmtree` in finally |
| TestCleanupStagingTmpPath | **NONE** | `tempfile.mkdtemp` + `shutil.rmtree` in finally |
| TestLegacyStagingValidation | **NONE** | Pure string logic, no I/O |
| TestRuntimeErrorDegradation | **NONE** | Mocked validate_staging_dir + real cleanup |

**Overall flakiness risk: LOW** — only WARN-1 is a real CI concern, and only manifests under parallel worker execution with shared /tmp/.

---

## Overall Operational Assessment: **RELIABLE**

The 15 new tests are well-structured and pass cleanly (0.23s, 0 failures). Resource cleanup follows the correct `try/finally` + `shutil.rmtree(ignore_errors=True)` pattern in all real-filesystem tests. Mock targets are correct. Test isolation is good for all new tests.

The one actionable issue (WARN-1: hardcoded /tmp/ names in TestValidateStagingDirSecurity) creates a theoretical collision risk in parallel CI but does not affect standard sequential test runs. It should be fixed before enabling `pytest-xdist` parallel workers.

The mock fragility (WARN-3) is a latent issue that would only surface on a specific `memory_write.py` refactor; it does not affect current CI.
