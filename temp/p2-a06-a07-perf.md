# A-06 & A-07 Audit Results: Logger Performance Tests

**Date:** 2026-02-25
**Status:** PASS -- all 4 tests green

## A-06: Cleanup Latency Under Accumulated Logs

**Problem:** The existing p95 benchmark test runs against a clean directory. In production, after 14+ days of logging, `cleanup_old_logs()` inside `emit_event()` scans many files. Need to verify p95 stays under budget even with accumulated state.

**Test Class:** `TestCleanupLatencyUnderLoad`

**Setup:**
- 7 event-type subdirectories (`retrieval`, `triage`, `judge`, `write`, `validate`, `enforce`, `search`)
- 14 `.jsonl` files per category = 98 total files
- 4 files per category with mtime 30 days ago (beyond 14-day retention -- should be deleted)
- 10 files per category with mtime 2 days ago (within retention -- should be preserved)
- `.last_cleanup` file set to >24h ago so cleanup actually runs (bypasses time gate)

**Tests:**
1. `test_emit_with_cleanup_under_50ms` -- Measures a single `emit_event()` call that triggers full cleanup scan of 98 files. Asserts total latency < 50ms.
2. `test_old_files_deleted_recent_preserved` -- Verifies correctness: all 28 old files deleted, all 70 recent files preserved.

**Result:** Both tests pass. Cleanup of 98 files (deleting 28) completes well under 50ms budget.

## A-07: Large Payload Concurrent Append (PIPE_BUF Boundary)

**Problem:** The existing concurrent test uses 100-byte payloads. Real `retrieval.search` events with 20 results can reach 2-4KB. POSIX `O_APPEND` atomicity is guaranteed up to `PIPE_BUF` (4096 bytes on Linux). Need to test near this boundary.

**Test Class:** `TestLargePayloadConcurrentAppend`

**Payload Design:**
- 20 result entries, each with `path`, `score`, `title`, and `snippet` fields
- Total JSONL line size: ~3.0-3.5KB (verified to be between 2048 and 4096 bytes)

**Tests:**
1. `test_large_payload_no_corruption` -- 8 threads x 20 writes = 160 concurrent large-payload writes. Verifies all 160 JSONL lines are valid JSON with correct schema (no interleaving/corruption).
2. `test_payload_size_near_pipe_buf` -- Writes a single event and verifies the line size is between 2KB and 4KB (PIPE_BUF), confirming we are actually testing near the atomicity boundary.

**Result:** Both tests pass. 160 concurrent writes of ~3.5KB payloads produce zero corruption.

## Full Test Suite

```
62 passed in 0.61s
```

All 62 tests in `test_memory_logger.py` pass, including the 4 new A-06/A-07 tests.

## Files Modified

- `tests/test_memory_logger.py` -- Added `TestCleanupLatencyUnderLoad` (2 tests) and `TestLargePayloadConcurrentAppend` (2 tests)
