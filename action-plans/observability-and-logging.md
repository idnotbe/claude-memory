---
status: blocked
progress: "Phase 1 + Phase 4 (4.1, 4.2) complete (34 tests). Phase 2-3 + Step 4.3 blocked on architecture-simplification.md (not-started)."
---

# Observability and Logging — Action Plan

**V-R1/R2 NOTE**: Gemini recommends deferring most logging until architecture-simplification.md lands, to avoid re-implementing in legacy code. **Exception**: Phase 1 (triage observability) is independent and should proceed with P0 hotfix. Phase 2-3 should wait for new architecture.

Current logging captures triage scores and guard decisions but misses critical operational data. When debugging popup/noise issues, the logs don't provide enough information to understand what happened.

## Logging Gaps

| Gap | Impact | Currently Logged? |
|-----|--------|-------------------|
| Stop hook re-fire count per session | Can't verify fix effectiveness | No |
| Save flow end-to-end timing | Can't identify bottlenecks | No |
| User popup confirmations | Can't measure popup frequency | No (platform limitation) |
| Guardian popup triggers | Can't correlate with memory ops | No (guardian logs separately) |
| Subagent model compliance (e.g., haiku heredoc) | Can't detect instruction violations | No |
| Write tool vs script path usage | Can't verify migration completeness | No |
| Save operation success/failure/retry | Can't measure reliability | Partial (memory_write.py logs) |
| Triage-to-save latency | Can't measure user wait time | No |

## Phases

### Phase 1: Triage Observability [v]
- [v] **Step 1.1**: Add `fire_count` to triage log event. Counter file at `{staging_dir}/.triage-fire-count` (workspace-scoped via /tmp/). Included in `triage.score` and `triage.idempotency_skip` events. O_NONBLOCK + fstat defense.
- [v] **Step 1.2**: `session_id` included in all 6 triage log events (5 skip + 1 score).
- [v] **Step 1.3**: `triage.idempotency_skip` event emitted for all 5 guards: stop_flag, sentinel, save_result, lock_held, sentinel_recheck.

### Phase 2: Save Flow Timing [ ]
- [ ] **Step 2.1**: Add start timestamp to triage-data.json (written by triage hook).
- [ ] **Step 2.2**: Add `save.start` log event at SKILL.md Phase 0 start (via a script call or SKILL.md instruction to log).
- [ ] **Step 2.3**: Add `save.complete` log event in `memory_write.py --action write-save-result`. Include duration_ms from triage start to save complete.
- [ ] **Step 2.4**: Add `save.phase_timing` to the save result JSON: `{"triage_ms": N, "draft_ms": N, "verify_ms": N, "write_ms": N}`.

### Phase 3: Operational Metrics Dashboard [ ]
- [ ] **Step 3.1**: Create `memory_log_analyzer.py` CLI tool (already exists, extend): add `--metrics` mode that outputs:
  - Avg/p95 save flow duration
  - Re-fire count distribution
  - Category trigger frequency
  - Save success/failure rate
  - Popup approximation (guardian deny/ask events if available)
- [ ] **Step 3.2**: Add `--watch` mode for real-time log tailing with event filtering.

### Phase 4: Tests [partial]
- [v] **Step 4.1**: Test triage fire count logging (8 unit + 5 edge-case tests: workspace isolation, truncation, permissions, large values, non-UTF8)
- [v] **Step 4.2**: Test idempotency skip logging (7 guard tests + 2 session_id bypass + 1 kwargs + 2 control-flow + 1 disabled + 2 score completeness + 3 fail-open = 18 additional tests)
- [ ] **Step 4.3**: Test save timing in result file (blocked: depends on Phase 2)
- [v] Verification: 2 independent rounds per phase with vibe-check + pal clink (codex 5.3 + gemini 3.1 pro). Total: 34 tests.

## Files Changed

| File | Changes | Status |
|------|---------|--------|
| hooks/scripts/memory_triage.py | `_increment_fire_count()`, 5 `triage.idempotency_skip` events, `fire_count` in `triage.score` | Done |
| hooks/scripts/memory_write.py | save.complete event with timing | Deferred (Phase 2) |
| hooks/scripts/memory_logger.py | No changes needed (session_id already supported) | N/A |
| tests/test_triage_observability.py | 34 tests: fire_count (13), idempotency_skip (7), session_id bypass (2), score completeness (2), kwargs (1), control-flow (2), disabled (1), fail-open (3), edge cases (3) | Done |
