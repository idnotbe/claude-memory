# Analyzer Validity Guards — Final Synthesis

**Date:** 2026-03-22
**Plan:** action-plans/plan-fix-analyzer-validity.md
**Status:** DONE (items 1-2), DEFERRED (items 3-4)

## Changes Made

### Files Modified
| File | Changes |
|------|---------|
| `hooks/scripts/memory_log_analyzer.py` | 5 min-sample constants, 4 detector guards, 1 new detector, 1 new recommendation |
| `hooks/scripts/memory_triage.py` | `score_text_category` → 4-tuple return, `_score_all_raw` + `score_all_categories` expose `primary_hits`/`booster_hits` |
| `tests/test_log_analyzer.py` | NEW: 40 tests covering all guards, boundary values, edge cases |
| `tests/test_memory_logger.py` | Updated `test_only_category_and_score_keys` → `test_only_expected_keys` (now expects `primary_hits`/`booster_hits`) |

### Plan Item Status
| Item | Status | Notes |
|------|--------|-------|
| 1. Min sample guards | DONE | N>=10/20/30 + bonus: error_spike N>=10 per-category |
| 2. Booster-hit-rate | DONE | Detector added + triage.py upstream (primary_hits/booster_hits) |
| 3. Version boundary | DEFERRED | Optional, lower priority |
| 4. Snapshot discipline | DEFERRED | Optional, lower priority |

### Bonus Fix (not in plan)
- `_detect_error_spike`: Added per-category N>=10 guard (same false-positive class, identified by Gemini 3.1 Pro)

## Cross-Model Validation Summary

| Phase | Models | Consensus |
|-------|--------|-----------|
| Design | Opus 4.6 + Codex 5.3 + Gemini 3.1 Pro | N=10/20/30/50 reasonable; silent None; per-category booster; hard cutoffs over CI |
| V1 Correctness | Codex 5.3 | `or` → `and` for booster field detection (FIXED); zero check redundant but harmless |
| V1 Correctness | Gemini 3.1 Pro | Ordering safe; Counter handles duplicates; perf_degradation sample_size gap (noted) |
| V2 Adversarial | Opus 4.6 | Guard bypass at boundary acceptable; false negative trade-off intentional |
| V2 Operational | Opus 4.6 | Old log compat verified; mixed format safe; 137/137 tests pass |

## Key Design Decisions
1. **Silent None** over INSUFFICIENT_DATA findings — avoids alert fatigue
2. **Require both** `primary_hits` AND `booster_hits` — prevents partial-field misclassification (Codex finding)
3. **SESSION_SUMMARY excluded** from booster detector — activity-based, no pattern matching
4. **Booster detector graceful skip** on old-format logs — `has_booster_fields` check

## Test Results (Final)
- `test_log_analyzer.py`: 40/40 passed
- `test_memory_triage.py`: 97/97 passed
- `test_memory_logger.py`: 116/116 passed
- Total: **253/253 passed, 0 failed, 0 regressions**

## V1/V2 Agent Findings Incorporated
| Finding | Source | Action |
|---------|--------|--------|
| `or` → `and` for booster field detection | V1 Codex | FIXED |
| `test_only_category_and_score_keys` broken | V1 Edge-case agent | FIXED |
| Pre-existing type-safety crashes (non-numeric fields) | V1 Security agent | NOTED — separate issue, not introduced by this change |
| Per-category minimum for CATEGORY_NEVER_TRIGGERS | V1 Correctness + Codex | NOTED — future improvement |
| sample_size in mixed old/new booster logs misleading | V1 Correctness | NOTED — acceptable for now |

## Known Limitations / Future Work
1. `_detect_skip_rate_high` denominator includes all retrieval.* event types, not just prompt attempts (Codex finding — separate fix)
2. `_detect_perf_degradation` lacks per-day sample count guard (Codex/Gemini — separate fix)
3. Pre-existing type-safety: non-numeric `score`/`primary_hits`/`booster_hits` can crash detectors (Security agent finding — separate hardening)
4. Per-category minimum guards for CATEGORY_NEVER_TRIGGERS and BOOSTER_NEVER_HITS (V1 Correctness finding — future refinement)
5. Version boundary awareness and snapshot discipline remain deferred (plan items 3-4)
