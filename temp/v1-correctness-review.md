# V-R1 Correctness Review: V-R2 Gap Tests

**Reviewer:** V-R1 Correctness Reviewer
**Date:** 2026-03-22
**Scope:** All newly added tests filling 4 V-R2 adversarial test gaps
**Files reviewed:**
- `tests/test_memory_staging_utils.py` -- `TestValidateStagingDirSecurity` (1 modified), `TestValidateStagingDirLegacyPath` (6 new)
- `tests/test_memory_triage.py` -- `TestTriageFallbackPaths` (3 new)
- `tests/test_memory_write.py` -- `TestCleanupIntentsTmpPath` (6 new), `TestCleanupStagingTmpPath` (5 new), `TestLegacyStagingValidation` (14 new), `TestRuntimeErrorDegradation` (4 new)
**Total new/modified tests:** 39 (1 modified + 38 new)

---

## Execution Results

All 45 tests in the reviewed classes pass (7 + 6 + 3 + 6 + 5 + 14 + 4 = 45).

---

## Issues Found

### WARN-1: False positive risk in `test_write_context_files_returns_empty_on_staging_failure`

**Test:** `TestTriageFallbackPaths::test_write_context_files_returns_empty_on_staging_failure`
**File:** `tests/test_memory_triage.py` line 3124

**What's wrong:** The test asserts `context_paths == {}` but does not verify that the function actually attempted the fallback write path. If someone accidentally removed the per-result loop body, the test would still pass (empty dict returned from an empty loop is identical to empty dict returned from failed writes). The `mock_os_open` side_effect mock is set up correctly to intercept fallback writes, but there is no assertion that it was called.

**Severity:** Low. The production code loop is exercised (confirmed by code inspection and the mock setup is not trivially bypassed), but a defensive assertion would strengthen the test.

**Suggested fix:** Add `mock_os_open` as a named mock and assert it was called at least once with a path containing `.memory-triage-context-`:
```python
# After the write_context_files call:
# Verify the fallback write was actually attempted
fallback_calls = [c for c in mock_open_obj.call_args_list
                  if '.memory-triage-context-' in str(c)]
assert len(fallback_calls) >= 1, "Fallback write path was never attempted"
```

Alternatively, the existing mock structure (`mock.patch.object(mt.os, "open", side_effect=mock_os_open)`) makes this harder to introspect since it uses a plain function, not a MagicMock. This is a design trade-off that's acceptable.

---

### WARN-2: Hardcoded nonexistent path in triage fallback test

**Test:** `TestTriageFallbackPaths::test_run_triage_fallback_when_ensure_staging_fails`
**File:** `tests/test_memory_triage.py` line 3085

**What's wrong:** The test uses a hardcoded path `/tmp/.claude-memory-staging-doesnotexist999`. While extremely unlikely, if a directory with this exact name exists on the test machine (from a previous crashed test or CI artifact), the triage-data.json write would succeed, and the test would fail because it expects the inline `<triage_data>` fallback.

**Severity:** Very low. The probability of this path existing is negligible.

**Suggested fix:** No change needed. The path name is sufficiently unique and the test cleans up properly (no writes to this path since the dir doesn't exist). If hardening is desired, add a precondition check:
```python
assert not os.path.isdir(nonexistent_staging), "Test precondition: path must not exist"
```

---

### INFO-1: Real /tmp/ cleanup uses `shutil.rmtree` with `ignore_errors=True`

**Tests:** All tests in `TestCleanupIntentsTmpPath`, `TestCleanupStagingTmpPath`, `TestRuntimeErrorDegradation`
**Files:** `tests/test_memory_write.py`

**What's right:** All tests that create real `/tmp/` directories use `try/finally` blocks with `shutil.rmtree(staging, ignore_errors=True)` for cleanup. This is robust against test failures.

**Assessment:** Correct. No issues.

---

### INFO-2: Mock targets are correctly placed

**Verified mock targets:**

| Test | Mock Target | Correctness |
|------|-------------|-------------|
| `test_write_save_result_degrades_on_runtime_error` | `memory_staging_utils.validate_staging_dir` | Correct. `write_save_result()` does a local `from memory_staging_utils import validate_staging_dir` on each call (line 714), which resolves via the module's attribute, so patching the module-level function intercepts it. Verified with live execution. |
| `test_run_triage_fallback_when_ensure_staging_fails` | `mt.ensure_staging_dir` / `mt.get_staging_dir` | Correct. Both are top-level imports on the `memory_triage` module (line 32), so `mock.patch.object(mt, ...)` patches them where they're used by `_run_triage()`. Note: `write_sentinel()` also calls `ensure_staging_dir()` via the same module reference, so it silently degrades (returns False). This is correct -- the test doesn't depend on sentinel state. |
| `test_write_context_files_returns_empty_on_staging_failure` | `mt.ensure_staging_dir` / `mt.os.open` | Correct. The `ensure_staging_dir` mock causes `staging_dir = ""`, forcing fallback paths. The `os.open` mock on `mt.os` catches the per-file writes with pattern matching on `.memory-triage-context-`. |
| `test_rejects_foreign_ownership_via_mock` | `memory_staging_utils.os.mkdir`, `.os.lstat`, `.os.geteuid` | Correct. All resolve within `memory_staging_utils` module scope. |

---

### INFO-3: Race condition analysis

**Real /tmp/ directory tests:** `TestCleanupIntentsTmpPath`, `TestCleanupStagingTmpPath`, `TestRuntimeErrorDegradation`, and `TestValidateStagingDirSecurity` (non-mock tests) all create real directories under `/tmp/` with either `tempfile.mkdtemp` (random suffix) or `STAGING_DIR_PREFIX + "test_*"` (deterministic suffix).

**Risk for deterministic paths:** Tests like `test_rejects_symlink_at_staging_path` use `/tmp/.claude-memory-staging-test_symlink_reject`. If two `pytest` processes run simultaneously, they could collide on this path. However:
- The `try/finally` cleanup prevents stale artifacts from persisting.
- In practice, pytest parallelism (pytest-xdist) would need to be explicitly configured, and these tests are quick enough that contention is negligible.
- The `tempfile.mkdtemp`-based tests are fully safe from collisions.

**Assessment:** Acceptable. Deterministic `/tmp/` paths are mildly fragile under extreme parallelism but fine for the expected single-process test execution.

---

### INFO-4: Unmocked side effects in `test_run_triage_fallback_when_ensure_staging_fails`

**Test:** `TestTriageFallbackPaths::test_run_triage_fallback_when_ensure_staging_fails`
**File:** `tests/test_memory_triage.py` line 3050

**Observation:** The test does not mock `set_stop_flag`, `write_sentinel`, `check_sentinel_session`, `_check_save_result_guard`, `_acquire_triage_lock`, `score_all_categories`, or `emit_event`. Analysis:

- **`set_stop_flag(cwd)`**: Writes to `proj/.claude/.stop_hook_active`. This uses `makedirs(exist_ok=True)` so it succeeds. Leaves a file on disk but inside `tmp_path` (pytest-managed), so cleanup is automatic.
- **`write_sentinel(cwd, ...)`**: Internally calls `ensure_staging_dir(cwd)` which is mocked to raise RuntimeError. The function catches `(OSError, RuntimeError)` and returns False. Safe.
- **`check_sentinel_session(cwd, ...)`**: Calls `read_sentinel(cwd)` which tries to open a non-existent sentinel file, catches OSError, returns None. Then `check_sentinel_session` returns False. Safe.
- **`_check_save_result_guard(cwd, ...)`**: Reads non-existent files, returns False. Safe.
- **`_acquire_triage_lock(cwd, ...)`**: Calls `ensure_staging_dir(cwd)` (mocked to fail), returns `("", _LOCK_ERROR)` (fail-open). Safe.
- **`score_all_categories(text, metrics)`**: Pure function, no side effects. Safe.
- **`emit_event(...)`**: May be a no-op fallback (if `memory_logger` not importable) or write to a log. Non-critical. Safe.

**Assessment:** All unmocked functions degrade gracefully. The test is correct -- it only needs to mock the functions that provide inputs (stdin, stop flag) and the specific functions under test (ensure_staging_dir, get_staging_dir, run_triage).

---

### INFO-5: `TestLegacyStagingValidation` tests exercise pure function correctly

**Tests:** All 14 tests in `TestLegacyStagingValidation`
**File:** `tests/test_memory_write.py` line 1877

**Assessment:** These test `_is_valid_legacy_staging()` which is a pure function (no I/O, no side effects). The tests provide good boundary coverage: valid paths, evil paths without `.claude` ancestor, wrong component order, partial matches, and both `allow_child` modes. No mocking needed. All assertions match the expected function contract from the source code.

---

## Test-to-Code Path Verification

| Gap | Test(s) | Source Code Path Exercised | Verified |
|-----|---------|---------------------------|----------|
| GAP 1 | `test_regular_file_at_path_raises_runtime_error` | `_validate_existing_staging()` S_ISDIR check (line 80-83) | Yes |
| GAP 1 | `TestValidateStagingDirLegacyPath` (6 tests) | `validate_staging_dir()` else-branch (line 116-126) -> `_validate_existing_staging()` | Yes |
| GAP 2 | `test_run_triage_fallback_when_ensure_staging_fails` | `_run_triage()` lines 1523-1560: ensure_staging_dir fails -> get_staging_dir fallback -> triage-data write fails -> inline `<triage_data>` | Yes |
| GAP 2 | `test_write_context_files_returns_empty_on_staging_failure` | `write_context_files()` lines 1130-1133: ensure_staging_dir fails -> per-file fallback -> os.open fails -> empty dict | Yes |
| GAP 2 | `test_triage_data_path_none_triggers_inline_fallback` | `format_block_message()` with `triage_data_path=None` -> inline `<triage_data>` tag | Yes |
| GAP 3 | `test_write_save_result_degrades_on_runtime_error` | `write_save_result()` lines 712-719: validate_staging_dir raises RuntimeError -> returns error dict | Yes |
| GAP 3 | `test_write_save_result_degrades_on_os_error` | Same path but with OSError | Yes |
| GAP 3 | `test_update_sentinel_state_rejects_invalid_path` | `update_sentinel_state()` lines 757-767: path containment check | Yes |
| GAP 3 | `test_write_save_result_error_message_contains_detail` | Verifies error message preserves original exception text | Yes |
| GAP 4 | `TestCleanupIntentsTmpPath` (6 tests) | `cleanup_intents()` lines 585-633: /tmp/ path validation, symlink rejection, path containment | Yes |
| GAP 4 | `TestCleanupStagingTmpPath` (5 tests) | `cleanup_staging()`: /tmp/ path validation, symlink skip, rejection of invalid paths | Yes |
| GAP 4 | `TestLegacyStagingValidation` (14 tests) | `_is_valid_legacy_staging()` lines 81-102: component matching logic | Yes |

---

## Overall Assessment: **PASS**

All tests are correct and exercise real code paths. No critical issues found. Two WARN-level notes (minor false-positive risk in one test, hardcoded path in another) are acceptable as-is and do not require fixes before commit. Mock targets are correctly placed in all cases, cleanup is robust, and race condition risk is negligible under normal test execution.
