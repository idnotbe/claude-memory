# Phase 1 V1R2 -- Test Adequacy & Edge Case Review

**Reviewer**: v1r2-tests agent (Opus 4.6)
**Cross-validation**: PAL clink (Gemini 3.1 Pro)
**Date**: 2026-02-28
**Verdict**: **PASS_WITH_FIXES**

---

## V1R1 Fix Verification

### 1. `test_triage_data_file_written` (line 1767)

**PASS.** The V1R1 fix is correctly applied:
- Mocks `memory_triage.run_triage` with `forced_results` containing a guaranteed blocking result (line 1791)
- Assertions at lines 1794-1813 are fully unconditional -- they always execute regardless of transcript content
- No dependency on transcript scoring heuristics; the mock guarantees the blocking path is taken
- Validates: exit code, stdout JSON structure, `decision == "block"`, file existence, JSON validity, `<triage_data_file>` tag presence

### 2. `test_triage_data_file_fallback_on_write_error` (line 1815)

**PASS.** The V1R1 fix is correctly applied:
- Same `run_triage` mock pattern (line 1846), assertions are unconditional
- `mock_os_open` (lines 1838-1841) correctly intercepts PID-unique tmp filenames:
  - Checks `isinstance(path, str)` (always True for f-string-constructed paths)
  - Matches `"triage-data.json." in path and path.endswith(".tmp")` -- catches any PID value
  - Falls through to `original_os_open` for non-triage writes (sentinel file, context files, etc.)
- Validates: inline `<triage_data>` fallback, no `<triage_data_file>` tag

## Missing Test Scenarios Analysis

### 3. `os.replace()` failure (not `os.open`)

**GAP -- Low severity.** No test covers `os.replace()` raising `OSError` (e.g., cross-device rename, permission denied on target). The production code at `memory_triage.py:1170-1177` handles this correctly (cleans up tmp, sets `triage_data_path = None` for inline fallback), but it lacks explicit test coverage.

**Recommendation**: Add a test mocking `memory_triage.os.replace` with `side_effect=OSError("cross-device link")` and verify inline `<triage_data>` fallback.

### 4. `json.dump` TypeError (non-serializable data)

**GAP -- Very low severity.** If `json.dump` raises `TypeError`, the inner `except Exception` (line 1164) re-raises, and the outer `except OSError` (line 1171) does NOT catch it. The `TypeError` would bubble up to `main()`'s fail-open handler (line 991-993), so the hook returns 0 but skips both file and inline output.

However, this is nearly impossible in practice: `build_triage_data()` constructs its output from `str`, `float`, `bool`, `list`, `dict` values only -- all natively JSON-serializable. Gemini 3.1 Pro concurs this is theoretically possible but practically unreachable.

**Recommendation**: Defensively widen `except OSError` at line 1171 to `except (OSError, TypeError, ValueError)` so the inline fallback triggers even for serialization errors. But not a blocking issue.

### 5. Multiple categories in triage-data.json

**PARTIAL COVERAGE.** `TestBuildTriageData.test_build_triage_data_includes_descriptions` (line 1588) tests `build_triage_data()` with 2 categories (DECISION + RUNBOOK) at the unit level. `TestBuildTriageData.test_build_triage_data_json_serializable` (line 1639) tests with 2 categories (DECISION + SESSION_SUMMARY).

However, the integration tests (`TestRunTriageWritesTriageDataFile`) only use a single-category `forced_results`. This means multi-category file writing + formatting in `_run_triage()` is only indirectly covered.

**Severity**: Low. The file-writing code (`json.dump(triage_data, ...)`) doesn't have category-count-dependent behavior.

### 6. `format_block_message` with empty results

**NOT NEEDED.** The function returns `""` for empty results (line 932-933). In `_run_triage()`, `format_block_message` is only called inside `if results:` (line 1116), making empty results unreachable from the integration path. The guard exists as defense-in-depth. No test needed.

## Test Isolation

**PASS.** Both integration tests:
- Use `tmp_path` (pytest auto-cleanup fixture)
- Use context manager `mock.patch` (auto-revert on exit)
- No shared mutable state between tests
- No interference with other test classes

## Cross-Validation Summary (Gemini 3.1 Pro)

Gemini confirmed all findings independently:
1. `run_triage` mocking makes assertions "100% unconditional" -- AGREED
2. `mock_os_open` PID interception is correct -- AGREED
3. `os.replace()` failure test gap -- AGREED (medium priority)
4. `json.dump` TypeError not caught by `except OSError` -- AGREED (flagged as "significant bug"; I assess lower severity due to `main()` fail-open + data always being serializable)
5. Empty results test not needed due to `if results:` guard -- AGREED

## Verdict: PASS_WITH_FIXES

All V1R1 fixes verified correct. Tests are reliable and well-isolated. Two low-severity gaps identified:

| # | Finding | Severity | Fix Required? |
|---|---------|----------|---------------|
| 1 | Missing `os.replace()` failure test | Low | Recommended |
| 2 | `except OSError` doesn't catch `TypeError` from `json.dump` | Very Low | Recommended (defensive) |
| 3 | Integration tests only use single category | Low | Optional |

None of these are blocking. The test suite adequately covers the Phase 1 externalization feature.
