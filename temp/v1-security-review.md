# V-R1 Security Review: V-R2 Gap Tests

**Reviewer**: Security perspective
**Date**: 2026-03-22
**Files reviewed**:
- `tests/test_memory_staging_utils.py` -- `TestValidateStagingDirSecurity`, `TestValidateStagingDirLegacyPath`
- `tests/test_memory_write.py` -- `TestRuntimeErrorDegradation`, `TestCleanupIntentsTmpPath`, `TestCleanupStagingTmpPath`
- `hooks/scripts/memory_staging_utils.py` -- production code under test
- `hooks/scripts/memory_write.py` -- `cleanup_intents()`, `cleanup_staging()`, `write_save_result()`, `update_sentinel_state()`

---

## Finding 1: No `../` Path Traversal Test for `validate_staging_dir`

**Severity**: WARN

The `validate_staging_dir()` function relies on `os.mkdir()` to create the final path component atomically. A path like `/tmp/.claude-memory-staging-abc123/../../../etc/evil` would be accepted by the `startswith(STAGING_DIR_PREFIX)` check but `os.mkdir()` would operate on the resolved target.

**Analysis**: In practice, `os.mkdir()` does not resolve `../` -- it creates the literal directory component, and intermediate `../` traversals are handled by the kernel, meaning the created directory is actually at the traversed location. However, the `startswith()` prefix check is performed on the *raw* (unrealized) path. An attacker cannot influence the `staging_dir` argument to `validate_staging_dir()` because it is computed deterministically from `get_staging_dir()` (SHA-256 hash), so the raw path never contains `../`. The risk exists only if a caller passes an externally-controlled path directly to `validate_staging_dir()`.

**Current callers**: `ensure_staging_dir()` always passes `get_staging_dir()` output (safe). `write_save_result()` calls `validate_staging_dir(str(staging_path))` where `staging_path = Path(staging_dir).resolve()` -- the `resolve()` eliminates `../` before the prefix check.

**Test gap**: No test explicitly verifies that a `../` traversal path is rejected by `validate_staging_dir()`. The code is safe due to `Path.resolve()` in callers, but a regression test documenting this invariant would strengthen defense-in-depth.

**Recommendation**: Add a test verifying that `validate_staging_dir("/tmp/.claude-memory-staging-abc/../../../etc/evil")` either raises RuntimeError or that callers always resolve before passing. Low priority since current callers all resolve.

---

## Finding 2: No Root UID (uid=0) Boundary Test for Ownership Check

**Severity**: INFO

The ownership check in `_validate_existing_staging()` is:
```python
if st.st_uid != os.geteuid():
    raise RuntimeError(...)
```

When running as root (euid=0), any directory passes the ownership check only if `st_uid == 0`. This is correct behavior -- root-owned staging dirs are valid when running as root. However, there is no test verifying:
1. When `geteuid() == 0` and `st_uid == 0`, the check passes (root owns its own staging).
2. When `geteuid() == 0` and `st_uid == 1000`, the check correctly rejects (root should not accept user-owned staging dirs).

The existing mock tests only cover `geteuid() == 1000, st_uid == 9999`.

**Impact**: Low. The equality check is trivially correct for all UID values. The missing test is a completeness gap, not a security vulnerability.

**Recommendation**: Add a mock test with `geteuid=0, st_uid=1000` -> RuntimeError, and `geteuid=0, st_uid=0` -> passes. Purely for documentation value.

---

## Finding 3: `tempfile.mkdtemp` Creates Directories with 0o700 by Default

**Severity**: INFO (positive finding)

All `/tmp/` test directories are created via `tempfile.mkdtemp(prefix=".claude-memory-staging-")`, which creates directories with 0o700 permissions (restricted to owner only). This is correct. Other users on a shared system cannot read or interfere with test staging directories during test execution.

The `try/finally` cleanup pattern used consistently across all test classes (`shutil.rmtree(staging, ignore_errors=True)`) prevents stale directories from accumulating in `/tmp/`.

**Assessment**: Good. No issue.

---

## Finding 4: TOCTOU Window in `_validate_existing_staging()` -- Documented and Acceptable

**Severity**: INFO

The code has a known TOCTOU window between `os.lstat()` (check) and `os.chmod()` (use) in `_validate_existing_staging()`:

```python
st = os.lstat(staging_dir)        # check
if stat.S_ISLNK(st.st_mode): ... # check
if st.st_uid != os.geteuid(): ...# check
if stat.S_IMODE(st.st_mode) & 0o077:
    os.chmod(staging_dir, 0o700)  # use
```

An attacker could theoretically delete the directory and replace it with a symlink between `lstat` and `chmod`. The code includes a comment acknowledging this:

> "TOCTOU note: the window between lstat and chmod is practically unexploitable -- /tmp/ has sticky bit, legacy paths are in the user's workspace."

This is correct. On `/tmp/` with the sticky bit set, only the owner can delete their own directories. An attacker without ownership cannot perform the delete+replace race.

**Test gap**: No test explicitly demonstrates the TOCTOU window is non-exploitable (this would require a multi-threaded race test, which is impractical and non-deterministic).

**Assessment**: Acceptable. The sticky bit defense is standard practice and the comment documents the reasoning.

---

## Finding 5: `cleanup_intents()` and `cleanup_staging()` -- Symlink Rejection is Well-Tested

**Severity**: INFO (positive finding)

Both cleanup functions have thorough symlink attack coverage:

| Vector | `cleanup_intents` test | `cleanup_staging` test |
|--------|----------------------|----------------------|
| Symlink intent file in /tmp/ staging | `test_symlink_rejected_in_tmp_staging` | `test_cleanup_staging_symlink_skipped_in_tmp` |
| Path containment (symlink to outside) | `test_path_containment_in_tmp` | (same symlink test covers this) |
| Invalid /tmp/ prefix rejected | `test_rejects_invalid_tmp_path` | `test_cleanup_staging_rejects_invalid_tmp_path` |
| Fake legacy staging path rejected | `test_rejects_arbitrary_memory_staging` | `test_cleanup_staging_rejects_arbitrary_memory_staging` |
| Legacy symlink path traversal | `test_path_traversal_rejected` (legacy class) | -- |

**Assessment**: Good coverage. The dual-layer defense (is_symlink check + resolve relative_to containment) is tested for both /tmp/ and legacy paths.

---

## Finding 6: Deep Symlink in Path (Directory Symlink Attack) Not Tested

**Severity**: WARN

The tests cover symlinks at the staging directory itself and symlinks on individual files within staging. However, no test covers a deep symlink in the path hierarchy. Example attack:

1. Attacker creates `/tmp/.claude-memory-staging-abc123/` (a real dir)
2. Inside it, attacker creates a symlink: `subdir -> /etc/`
3. If any code ever uses `staging_path / "subdir" / "file"`, it would resolve to `/etc/file`

**Analysis**: The current code never creates or accesses subdirectories within staging. All operations are flat (intent-*.json, context-*.txt, etc. are all direct children). The `Path.glob()` patterns used in cleanup functions only match direct children (no `**/` recursion). Therefore this attack vector is not exploitable with the current code.

**Recommendation**: No test needed now, but if staging ever gains subdirectory support, a deep symlink test would be critical.

---

## Finding 7: `write_save_result()` RuntimeError Degradation Uses Mock, Not Real Symlink

**Severity**: INFO

`TestRuntimeErrorDegradation.test_write_save_result_degrades_on_runtime_error` mocks `validate_staging_dir` to raise RuntimeError rather than creating an actual symlink at the staging path. This tests the error-handling code path but not the full integration (real symlink -> validate detects -> write_save_result catches).

**Analysis**: The unit test for `validate_staging_dir` itself (`test_rejects_symlink_at_staging_path`) uses a real symlink, so the detection logic is tested at the lower layer. The mock in `write_save_result` correctly tests the catch-and-degrade path. The combined behavior is covered by two separate tests. This is acceptable test architecture.

**Recommendation**: No change needed. The layered testing is sufficient.

---

## Finding 8: `atomic_write_text()` Does Not Use O_NOFOLLOW

**Severity**: WARN

`atomic_write_text()` uses `tempfile.mkstemp()` + `os.rename()` for atomic writes. `mkstemp()` uses O_EXCL internally, preventing creation through existing symlinks. However, the final `os.rename(tmp_path, target)` would follow a symlink at the `target` path.

**Analysis**: In the `write_save_result()` flow, the `target` is `str(staging_path / "last-save-result.json")` where `staging_path` is already resolved. The staging directory itself is validated. A symlink at `last-save-result.json` within the staging directory could redirect the write. However, only the staging directory owner (the current user) can create files within the 0o700 staging directory, so an attacker cannot plant a symlink there.

**Recommendation**: This is a defense-in-depth concern. Using `os.open(target, O_CREAT|O_WRONLY|O_NOFOLLOW)` + `os.write()` + `os.replace()` would be safer. Not critical given the 0o700 directory permissions.

**Test gap**: No test verifies that a symlink at `last-save-result.json` is rejected. Low priority due to directory permission protection.

---

## Finding 9: Test Cleanup Race -- Real /tmp/ Tests Could Leak on Test Framework Crash

**Severity**: INFO

All real /tmp/ tests use `try/finally` with `shutil.rmtree(staging, ignore_errors=True)`. If the test runner is killed (SIGKILL, OOM) during a test, the cleanup block does not execute, leaving directories in `/tmp/`.

**Analysis**: This is inherent to any test that creates real /tmp/ directories. The directories are small and named with a distinctive prefix, making manual cleanup easy. The sticky bit on /tmp/ prevents other users from accessing them.

**Recommendation**: No change needed. This is acceptable test behavior.

---

## Finding 10: `update_sentinel_state()` Does Not Call `validate_staging_dir()`

**Severity**: WARN

`write_save_result()` calls `validate_staging_dir()` before writing (line 714-715). `update_sentinel_state()` performs path containment (startswith + legacy check) but does NOT call `validate_staging_dir()`. It relies on O_NOFOLLOW for sentinel file reads and O_EXCL for sentinel writes.

**Analysis**: The sentinel path is derived from `staging_path / ".triage-handled"`. If the staging directory itself is a symlink, `Path(staging_dir).resolve()` follows it, and the resolved path would pass the `startswith` check if the symlink target happens to be in `/tmp/.claude-memory-staging-*`. This is an unlikely but theoretical attack vector: attacker creates symlink `/tmp/.claude-memory-staging-X -> /tmp/.claude-memory-staging-Y` (another user's staging), and `update_sentinel_state` would read/write the wrong sentinel.

**Mitigation**: The O_NOFOLLOW on reads and O_EXCL on writes provide per-file symlink defense for the sentinel itself. The staging directory symlink issue is mitigated by `ensure_staging_dir()` being called earlier in the flow (which does validate).

**Test gap**: `TestRuntimeErrorDegradation.test_update_sentinel_state_rejects_invalid_path` only tests path containment rejection, not symlink-at-staging-dir behavior. This is acceptable because the sentinel operations use O_NOFOLLOW/O_EXCL directly.

---

## Summary Table

| # | Finding | Severity | Tested? | Action |
|---|---------|----------|---------|--------|
| 1 | `../` traversal in validate_staging_dir raw path | WARN | No | Low priority -- callers resolve first |
| 2 | Root UID (uid=0) boundary case | INFO | No | Documentation-value test only |
| 3 | tempfile.mkdtemp 0o700 permissions | INFO | Yes (inherent) | No action |
| 4 | TOCTOU in lstat->chmod | INFO | N/A (impractical) | Acceptable, documented |
| 5 | Symlink rejection in cleanup functions | INFO | Yes, thorough | No action |
| 6 | Deep symlink in path hierarchy | WARN | No | Not exploitable currently |
| 7 | RuntimeError degradation uses mock | INFO | Yes (layered) | No action |
| 8 | atomic_write_text lacks O_NOFOLLOW | WARN | No | Low priority, dir perms protect |
| 9 | Test cleanup on framework crash | INFO | N/A | Acceptable |
| 10 | update_sentinel_state skips validate_staging_dir | WARN | Partial | O_NOFOLLOW/O_EXCL mitigate |

---

## Overall Security Assessment: **SECURE**

The test suite provides strong security coverage for the core threat vectors:
- **Symlink attacks**: Tested at both directory level (validate_staging_dir) and file level (cleanup functions) for both /tmp/ and legacy paths.
- **Ownership checks**: Tested via mocks (correct approach since real foreign-UID tests require root).
- **Path containment**: Tested for both cleanup functions with real /tmp/ paths and legacy paths.
- **Graceful degradation**: RuntimeError and OSError catch paths in write_save_result() are tested.
- **Permission tightening**: 0o777 -> 0o700 tested for both /tmp/ and legacy paths.

The 4 WARN findings are defense-in-depth gaps, not exploitable vulnerabilities. The code has multiple layers of protection (directory permissions, symlink checks, path containment, O_NOFOLLOW) that compensate for any individual gap. No CRITICAL findings.
