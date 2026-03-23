---
status: done
progress: "All phases complete. Phase 1 (34 tests), Phase 2 (save flow timing, 26 tests), Phase 3 (metrics dashboard, 56 tests), Phase 4 (complete). Total: 116 new tests."
---

# Observability and Logging — Action Plan

**V-R1/R2 NOTE**: Gemini recommends deferring most logging until architecture-simplification.md lands, to avoid re-implementing in legacy code. **Exception**: Phase 1 (triage observability) is independent and should proceed with P0 hotfix. Phase 2-3 should wait for new architecture.

**Update (2026-03-23)**: Architecture simplification is complete (v6). Phase 2-3 blocker resolved. All phases implemented with 2 independent verification rounds each (vibe-check + pal clink: codex 5.3 + gemini 3.1 pro).

Current logging captures triage scores and guard decisions but misses critical operational data. When debugging popup/noise issues, the logs don't provide enough information to understand what happened.

## Logging Gaps

| Gap | Impact | Currently Logged? |
|-----|--------|-------------------|
| Stop hook re-fire count per session | Can't verify fix effectiveness | **Yes** (Phase 1) |
| Save flow end-to-end timing | Can't identify bottlenecks | **Yes** (Phase 2) |
| User popup confirmations | Can't measure popup frequency | No (platform limitation) |
| Guardian popup triggers | Can't correlate with memory ops | No (guardian logs separately) |
| Subagent model compliance (e.g., haiku heredoc) | Can't detect instruction violations | No |
| Write tool vs script path usage | Can't verify migration completeness | No |
| Save operation success/failure/retry | Can't measure reliability | **Yes** (Phase 2) |
| Triage-to-save latency | Can't measure user wait time | **Yes** (Phase 2) |

## Phases

### Phase 1: Triage Observability [v]
- [v] **Step 1.1**: Add `fire_count` to triage log event. Counter file at `{staging_dir}/.triage-fire-count` (workspace-scoped via /tmp/). Included in `triage.score` and `triage.idempotency_skip` events. O_NONBLOCK + fstat defense.
- [v] **Step 1.2**: `session_id` included in all 6 triage log events (5 skip + 1 score).
- [v] **Step 1.3**: `triage.idempotency_skip` event emitted for all 5 guards: stop_flag, sentinel, save_result, lock_held, sentinel_recheck.

### Phase 2: Save Flow Timing [v]
- [v] **Step 2.1**: `triage_start_ts` (wall-clock `time.time()`) added to `build_triage_data()` output and triage-data.json. Fail-open float conversion with type safety.
- [v] **Step 2.2**: `save.start` log event emitted at `execute_saves()` entry in `memory_orchestrate.py`. Reads triage-data.json for triage_start_ts, loads config for logging. Fail-open.
- [v] **Step 2.3**: `save.complete` log event emitted at `execute_saves()` exit. Includes duration_ms from triage start to save complete (total including post-write cleanup). Negative durations clamped to None.
- [v] **Step 2.4**: `phase_timing` dict added to save result JSON: `{"triage_ms", "orchestrate_ms", "write_ms", "total_ms", "draft_ms": null, "verify_ms": null}`. Negative cross-process durations clamped to None. NaN/Infinity guarded via `math.isfinite()`. Added to `_SAVE_RESULT_ALLOWED_KEYS` with dict-or-null type validation.

### Phase 3: Operational Metrics Dashboard [v]
- [v] **Step 3.1**: `--metrics` mode in `memory_log_analyzer.py` computes:
  - Save flow duration (count, avg, p50, p95 nearest-rank, max, distribution buckets)
  - Re-fire count distribution (1, 2, 3+, average)
  - Category trigger frequency (per-category count + rate)
  - Save success/failure rate (success, partial, total, rate %)
  - Phase timing averages (triage_ms, orchestrate_ms, write_ms)
- [v] **Step 3.2**: `--watch` mode for real-time log tailing. Features: `--filter` prefix filtering, 1s polling, date rollover, inode/size truncation detection, symlink protection, graceful Ctrl+C exit.

### Phase 4: Tests [v]
- [v] **Step 4.1**: Test triage fire count logging (8 unit + 5 edge-case tests: workspace isolation, truncation, permissions, large values, non-UTF8)
- [v] **Step 4.2**: Test idempotency skip logging (7 guard tests + 2 session_id bypass + 1 kwargs + 2 control-flow + 1 disabled + 2 score completeness + 3 fail-open = 18 additional tests)
- [v] **Step 4.3**: Test save timing (26 tests): triage_start_ts in build_triage_data (4), write_save_result phase_timing validation (5), execute_saves phase_timing (9), save.start/complete events (5), integration flow (3).
- [v] **Step 4.4**: Test metrics dashboard (56 tests): compute_metrics (28), format_metrics_text (5), format_watch_line (7), watch_logs (5), CLI (4), edge cases (7).
- [v] Verification: 2 independent rounds per phase with vibe-check + pal clink (codex 5.3 + gemini 3.1 pro). Total: 116 tests.

## Files Changed

| File | Changes | Status |
|------|---------|--------|
| hooks/scripts/memory_triage.py | Phase 1: `_increment_fire_count()`, 5 `triage.idempotency_skip` events, `fire_count` in `triage.score`. Phase 2: `triage_start_ts` in `build_triage_data()` | Done |
| hooks/scripts/memory_orchestrate.py | Phase 2: `save.start`/`save.complete` events, `phase_timing` dict, triage_start_ts read, negative clamping, isfinite guard, `phase_timing` in all_noop paths | Done |
| hooks/scripts/memory_write.py | Phase 2: `phase_timing` in `_SAVE_RESULT_ALLOWED_KEYS`, dict-or-null type validation | Done |
| hooks/scripts/memory_log_analyzer.py | Phase 3: `compute_metrics()`, `format_metrics_text()`, `--metrics` CLI, `watch_logs()`, `--watch`/`--filter` CLI, inode/size truncation detection, nearest-rank p95 | Done |
| hooks/scripts/memory_logger.py | No changes needed (session_id already supported) | N/A |
| tests/test_triage_observability.py | 34 tests (Phase 1) | Done |
| tests/test_save_timing.py | 26 tests (Phase 2) | Done |
| tests/test_log_analyzer_metrics.py | 56 tests (Phase 3) | Done |

## Known Issues

- **Pre-existing test isolation**: `test_memory_triage.py` module-level imports contaminate `test_triage_observability.py` when run in the same pytest session. All 34 triage observability tests pass in isolation. This is NOT caused by the observability changes.
