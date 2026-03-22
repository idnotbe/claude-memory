# Initial Gap Analysis: fix-stop-hook-refire Tests

## Confirmed Gaps

### GAP-1: MISSING — Atomic lock stale detection (120s timeout)
- **Function**: `_acquire_triage_lock()` in memory_triage.py
- **What's missing**: No test verifies stale lock bypass path (lock older than 120s → delete + re-acquire)
- **Existing tests**: acquire/release, HELD blocks second acquire
- **Risk**: Stale lock could permanently block triage in production

### GAP-2: PARTIAL — Sentinel "saving" state via check_sentinel_session()
- **Function**: `check_sentinel_session()` in memory_triage.py
- **What's missing**: No test for state="saving" returning True (blocking)
- **Existing tests**: "saved" blocks, "failed" allows, "pending" blocks
- **Risk**: "saving" state might not block, causing re-fire during active save

## Potential Additional Gaps (need deep verification)

### GAP-3?: read_sentinel() FIFO/device rejection
- S_ISREG check rejects non-regular files — tested?
- O_NOFOLLOW symlink rejection — tested?

### GAP-4?: write_sentinel() failure paths
- Returns False on staging dir failure — tested?
- Returns False on write failure — tested?

### GAP-5?: _check_save_result_guard() edge cases
- Bad JSON in result file → graceful degradation — tested?
- Both legacy and /tmp/ paths checked — tested?

### GAP-6?: _run_triage() flow guards
- cwd validation rejects non-directory paths — tested?
- transcript path validated — tested?
- Double-check sentinel under lock — tested?

### GAP-7?: set_stop_flag() O_NOFOLLOW
- Symlink at flag path not followed — tested?

### GAP-8?: check_sentinel_session() edge cases
- Empty session_id in sentinel → proceed — tested?
- Invalid timestamp → fail-open — tested?
- Unknown state → proceed — tested?
