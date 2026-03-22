# Analyzer Validity Guards -- Test Implementation

**Date:** 2026-03-22
**File:** tests/test_log_analyzer.py

## Summary

Created comprehensive pytest test suite (40 tests) covering all 5 rate-based anomaly detectors in `memory_log_analyzer.py` and their minimum sample size guards.

## Test Coverage

| Class | Tests | Detector | Guard Constant |
|-------|-------|----------|----------------|
| TestDetectZeroLengthPrompt | 7 | `_detect_zero_length_prompt` | `_MIN_SKIP_EVENTS_ZERO_PROMPT=10` |
| TestDetectSkipRateHigh | 7 | `_detect_skip_rate_high` | `_MIN_RETRIEVAL_EVENTS_SKIP_RATE=20` |
| TestDetectCategoryNeverTriggers | 6 | `_detect_category_never_triggers` | `_MIN_TRIAGE_EVENTS_CATEGORY=30` |
| TestDetectBoosterNeverHits | 8 | `_detect_booster_never_hits` | `_MIN_TRIAGE_EVENTS_BOOSTER=50` |
| TestDetectErrorSpike | 7 | `_detect_error_spike` | `_MIN_ERROR_SPIKE_EVENTS=10` |
| TestConstantValues | 5 | (all constants) | N/A |

## Key Patterns Tested

- **Empty input**: 0 events returns None/[]
- **Below minimum**: N-1 events returns None/[] even with 100% anomaly rate
- **At minimum, triggers**: N events with anomalous data returns finding
- **At minimum, below rate**: N events with sub-threshold rate returns None/[]
- **Boundary conditions**: Exact threshold values (e.g., 50% at >50%, 90% at >90%)
- **Finding structure**: sample_size key, severity, code fields
- **Category exclusions**: SESSION_SUMMARY excluded from booster findings
- **Old format tolerance**: Missing booster fields treated as no data

## Results

- **40/40 tests pass** against current implementation
- 1 pre-existing failure in `test_memory_logger.py::test_only_category_and_score_keys` (unrelated; old test doesn't expect new `primary_hits`/`booster_hits` fields in triage output)
- Full suite: 1085 passed, 1 failed (pre-existing)
