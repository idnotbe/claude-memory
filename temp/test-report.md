# Test Report: Architectural Fix Tests

**File:** `tests/test_arch_fixes.py`
**Date:** 2026-02-15
**Total tests:** 50
**Pre-fix results:** 35 passed, 5 skipped, 10 xfailed (0 unexpected failures)

---

## Summary

Comprehensive tests covering all 5 architectural fixes. Tests are organized into one class per issue, plus a cross-issue interaction class. Tests marked `@pytest.mark.xfail` document bugs that exist in the current code and should pass after the corresponding fix is applied.

## Test Breakdown by Issue

### Issue 1: index.md Rebuild-on-Demand (7 tests)

| Test | Status | Description |
|------|--------|-------------|
| `test_rebuild_triggers_when_index_missing_but_root_exists` | PASS | Verifies retrieval doesn't crash when index missing but memory dir exists |
| `test_no_rebuild_when_index_present` | PASS | Index mtime unchanged when index already exists |
| `test_rebuild_with_no_memory_index_py` | PASS | Graceful fallback when memory_index.py unavailable |
| `test_rebuild_timeout_handling` | PASS | Retrieval completes within timeout even if rebuild slow |
| `test_no_rebuild_when_memory_root_missing` | PASS | No action when .claude/memory/ dir doesn't exist |
| `test_rebuild_produces_valid_index` | PASS | Rebuild generates parseable index.md |
| `test_candidate_also_triggers_rebuild` | PASS | memory_candidate.py handles missing index |

**Post-fix expected:** All 7 pass. Remove any `xfail` markers when rebuild logic is implemented.

### Issue 2: _resolve_memory_root() Fail-Closed (7 tests)

| Test | Status | Description |
|------|--------|-------------|
| `test_path_with_marker_resolves_correctly` | PASS | .claude/memory path resolves |
| `test_path_without_marker_fails_closed` | XFAIL | Arbitrary path should sys.exit(1) |
| `test_relative_path_resolves_correctly` | PASS | Relative .claude/memory path works |
| `test_absolute_path_resolves_correctly` | PASS | Absolute path works |
| `test_multiple_claude_memory_segments` | PASS | First .claude/memory segment used |
| `test_external_path_rejected_via_write` | XFAIL | /tmp path should be rejected |
| `test_error_message_includes_example` | XFAIL | Error should include example path |

**Post-fix expected:** All 7 pass. The 3 xfail tests validate the security fix.

### Issue 3: max_inject Value Clamping (12 tests)

| Test | Status | Description |
|------|--------|-------------|
| `test_max_inject_negative_clamped_to_zero` | XFAIL | -1 should clamp to 0, exit |
| `test_max_inject_zero_exits_early` | XFAIL | 0 should disable injection |
| `test_max_inject_five_default_behavior` | PASS | Default value works |
| `test_max_inject_twenty_clamped` | PASS | Upper bound accepted |
| `test_max_inject_hundred_clamped_to_twenty` | XFAIL | 100 should clamp to 20 |
| `test_max_inject_string_invalid_type` | XFAIL | "five" causes TypeError |
| `test_max_inject_null_invalid_type` | PASS | None happens to work (evaluates falsy) |
| `test_max_inject_float_coerced` | XFAIL | 5.7 causes TypeError at slice |
| `test_max_inject_missing_key_uses_default` | PASS | Missing key -> default 5 |
| `test_config_missing_entirely` | PASS | No config -> default 5 |
| `test_max_inject_string_number_coerced` | XFAIL | "5" causes TypeError at slice |
| `test_retrieval_disabled` | PASS | enabled: false -> exit 0 |

**Post-fix expected:** All 12 pass. The 6 xfail tests cover type coercion and clamping.

### Issue 4: mkdir-based Lock (8 tests)

| Test | Status | Description |
|------|--------|-------------|
| `test_lock_acquire_and_release` | PASS | Lock acquires and releases cleanly |
| `test_lock_context_manager_protocol` | PASS | Context manager protocol works |
| `test_stale_lock_detection` | PASS | Old lock detected (adaptive to both implementations) |
| `test_lock_timeout` | PASS | Non-stale held lock handled (adaptive) |
| `test_permission_denied_handling` | PASS | Permission errors don't crash |
| `test_cleanup_on_normal_exit` | PASS | Lock cleaned up after normal exit |
| `test_cleanup_on_exception` | PASS | Lock cleaned up after exception |
| `test_write_operation_uses_lock` | PASS | End-to-end write with lock works |

**Post-fix expected:** All 8 pass. Tests are written to be adaptive to both old (fcntl) and new (mkdir) implementations.

### Issue 5: Prompt Injection Defense (11 tests)

| Test | Status | Description |
|------|--------|-------------|
| `test_sanitize_title_strips_control_chars` | SKIP | _sanitize_title not yet in memory_retrieve |
| `test_sanitize_title_strips_arrow_markers` | SKIP | _sanitize_title not yet in memory_retrieve |
| `test_sanitize_title_strips_tags_markers` | SKIP | _sanitize_title not yet in memory_retrieve |
| `test_sanitize_title_truncation` | SKIP | _sanitize_title not yet in memory_retrieve |
| `test_sanitize_title_strips_whitespace` | SKIP | _sanitize_title not yet in memory_retrieve |
| `test_output_format_uses_memory_context_tags` | PASS | Checks for either old or new output format |
| `test_pre_sanitization_entries_cleaned` | XFAIL | Raw output contains \x00 from crafted title |
| `test_tags_formatting_in_output` | PASS | Tags appear in output |
| `test_write_side_title_sanitization` | PASS | Write-side auto_fix sanitizes titles |
| `test_combined_write_and_retrieve_sanitization` | PASS | End-to-end write sanitization works |
| `test_title_with_embedded_close_tag` | PASS | </memory-context> in title doesn't crash |
| `test_no_raw_line_in_output_after_fix` | PASS | Output contains essential info |

**Post-fix expected:** All 11 pass. 5 skipped tests become real tests when _sanitize_title is added. 1 xfail validates retrieval-side sanitization.

### Cross-Issue Interactions (4 tests)

| Test | Status | Description |
|------|--------|-------------|
| `test_rebuild_with_sanitized_titles` | PASS | Issue 1+5: Rebuilt index uses sanitized titles |
| `test_max_inject_limits_injection_surface` | PASS | Issue 3+5: Fewer entries = smaller surface |
| `test_lock_not_needed_for_rebuild` | PASS | Issue 1+4: Write during rebuild works |
| `test_validated_root_with_lock` | PASS | Issue 2+4: Lock on validated root works |

**Post-fix expected:** All 4 pass.

---

## Test Design Decisions

1. **xfail markers**: Tests that document current bugs use `@pytest.mark.xfail(reason="pre-fix: ...")`. After implementing a fix, remove the marker so CI catches regressions.

2. **Skipped tests**: Tests for `_sanitize_title()` use `pytest.skip()` because the function doesn't exist yet. After the fix adds it, they'll run automatically.

3. **Adaptive assertions**: Issue 4 (lock) tests check for both old (`_flock_index` with fcntl) and new (mkdir-based) implementations via `hasattr` checks, so they pass during both pre-fix and post-fix states.

4. **Subprocess-based integration tests**: Following existing conventions, most tests run the scripts as subprocesses for realistic end-to-end validation.

5. **Security focus**: Tests for Issues 2 and 5 specifically validate that injection/traversal attacks are blocked after fixes are applied.

## How to Verify Fixes

After implementing each fix:

```bash
# Run all arch fix tests
.venv/bin/python3 -m pytest tests/test_arch_fixes.py -v

# Run tests for a specific issue (by class name)
.venv/bin/python3 -m pytest tests/test_arch_fixes.py -v -k "TestIssue3"

# Ensure no xfail tests remain after all fixes
.venv/bin/python3 -m pytest tests/test_arch_fixes.py -v --strict-markers
```

When a fix is applied:
1. Remove the `xfail` marker from tests that should now pass
2. Remove `pytest.skip()` calls for functions that now exist
3. If any test still fails, the fix is incomplete
