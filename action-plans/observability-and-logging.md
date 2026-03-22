---
status: not-started
progress: "Not started"
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

### Phase 1: Triage Observability [ ]
- [ ] **Step 1.1**: Add `fire_count` to triage log event. Increment a counter file (`.claude/memory/.staging/.triage-fire-count`) on each triage execution. Include count in `triage.score` log event.
- [ ] **Step 1.2**: Add `session_id` to all triage log events (already available via `get_session_id()`).
- [ ] **Step 1.3**: Log `triage.idempotency_skip` event when any guard (flag, sentinel, save-result) short-circuits triage. Include which guard triggered.

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

### Phase 4: Tests [ ]
- [ ] **Step 4.1**: Test triage fire count logging
- [ ] **Step 4.2**: Test idempotency skip logging
- [ ] **Step 4.3**: Test save timing in result file
- [ ] Verification: 1 round (lower risk than code changes)

## Files Changed

| File | Changes |
|------|---------|
| hooks/scripts/memory_triage.py | fire_count, session_id, idempotency_skip events |
| hooks/scripts/memory_write.py | save.complete event with timing |
| hooks/scripts/memory_logger.py | Ensure session_id propagation |
| tests/ | New logging tests |
