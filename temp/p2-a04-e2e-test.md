# A-04: End-to-End Integration Test Report

**Date:** 2026-02-25
**Action:** A-04 -- Write E2E integration test for retrieval pipeline JSONL logging
**Status:** COMPLETE -- 10/10 tests passing

## Summary

Added `TestEndToEndLogging` class (10 tests) to `tests/test_memory_logger.py` that traces the COMPLETE retrieval pipeline via subprocess and verifies actual JSONL output on disk. These tests validate that real `memory_retrieve.py` execution produces correct, schema-valid JSONL log entries -- filling the gap identified in the audit where all 52 existing tests used synthetic `emit_event()` calls with fabricated data dicts.

## Test Inventory

| # | Test Method | What It Validates |
|---|------------|-------------------|
| 1 | `test_full_pipeline_produces_valid_jsonl` | Main test: 8-point schema verification on every log entry (schema_version, timestamp/filename match, known event_type, data keys, duration_ms, session_id, hook/script, level) |
| 2 | `test_search_event_results_structure` | `retrieval.search` results array: path, score, confidence fields |
| 3 | `test_inject_event_results_structure` | `retrieval.inject` event: injected_count matches results array length |
| 4 | `test_short_prompt_skip_event` | Short prompt produces `retrieval.skip` with reason=`short_prompt` (validates A-01 fix) |
| 5 | `test_empty_prompt_skip_event` | Whitespace-padded short prompt also triggers skip |
| 6 | `test_no_match_produces_skip_or_no_inject` | Non-matching query: skip event logged or no inject event present |
| 7 | `test_logging_disabled_no_log_files` | Config `logging.enabled: false` produces zero filesystem artifacts |
| 8 | `test_multiple_memories_pipeline` | Two similar memories both survive BM25 threshold and inject >= 2 |
| 9 | `test_log_entries_ordered_by_pipeline_stage` | search event precedes inject event within the same JSONL file |
| 10 | `test_inject_duration_covers_full_pipeline` | inject duration_ms >= search duration_ms (pipeline timer correctness) |

## Key Design Decisions

1. **Self-contained helpers:** All memory factories (`_make_e2e_decision`, etc.), index builder (`_build_e2e_index`), and project scaffolding (`_setup_e2e_project`) are defined locally with `_e2e_` prefixes to avoid namespace collisions with existing test infrastructure. No imports from conftest factories.

2. **Subprocess execution:** Tests use `subprocess.run` with `memory_retrieve.py` piped on stdin, matching exact production execution. `ANTHROPIC_API_KEY` is stripped from env to ensure LLM judge is always disabled.

3. **BM25 noise floor awareness:** The multiple-memories test uses two decision memories with identical tags and overlapping titles so BM25 scores stay within the 25% noise floor cutoff. An earlier attempt with mixed categories (decision + runbook + preference) failed because body content divergence caused score spread beyond the threshold.

4. **No API key required:** All tests work without ANTHROPIC_API_KEY. Judge is disabled by env stripping.

## Test Results

```
tests/test_memory_logger.py - 72 passed in 0.98s

TestEndToEndLogging (10 tests):
  test_full_pipeline_produces_valid_jsonl         PASSED
  test_search_event_results_structure             PASSED
  test_inject_event_results_structure             PASSED
  test_short_prompt_skip_event                    PASSED
  test_empty_prompt_skip_event                    PASSED
  test_no_match_produces_skip_or_no_inject        PASSED
  test_logging_disabled_no_log_files              PASSED
  test_multiple_memories_pipeline                 PASSED
  test_log_entries_ordered_by_pipeline_stage       PASSED
  test_inject_duration_covers_full_pipeline        PASSED
```

## Files Modified

- `tests/test_memory_logger.py` -- Added ~400 lines: helpers + `TestEndToEndLogging` class (10 tests)

## Coverage Gap Closed

Before: 62 tests covering `emit_event()` with synthetic data. No test validated the actual data dicts constructed by `memory_retrieve.py` or verified the end-to-end pipeline's JSONL output.

After: 72 tests total. The 10 new E2E tests exercise the full `memory_retrieve.py -> memory_logger.emit_event -> JSONL on disk` chain, validating both the schema correctness of logged data and the accuracy of data dict construction at each pipeline stage (search, inject, skip).
