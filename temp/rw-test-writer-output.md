# Rolling Window Test Writer Output

## Status: COMPLETE -- 24/24 tests passing

## Test File
`/home/idnotbe/projects/claude-memory/tests/test_rolling_window.py`

## Test Results
```
24 passed in 1.06s
```

## Test Coverage Summary

### memory_enforce.py tests (1-15)

| # | Test | Status |
|---|------|--------|
| 1 | Rolling window triggers: 6 active, max_retained=5 -> retires 1 oldest | PASS |
| 2 | No trigger: 5 active, max_retained=5 -> 0 retirements | PASS |
| 3 | Multiple retirements: 8 active, max_retained=5 -> retires 3 oldest | PASS |
| 4 | Correct ordering: retires by created_at, filename tiebreaker | PASS |
| 5 | Custom max_retained from CLI override | PASS |
| 6 | Custom max_retained from config | PASS |
| 7 | Corrupted JSON skipped, others processed | PASS |
| 8 | retire_record() failure breaks loop, partial results | PASS |
| 9 | File disappears between scan and retire (FileNotFoundError caught) | PASS |
| 10 | --dry-run: no files modified, "dry_run": true in output | PASS |
| 11 | Empty directory: sessions folder missing -> 0 retirements | PASS |
| 12 | Memory root discovery: env var -> CWD fallback -> error | PASS |
| 13 | Lock not acquired -> require_acquired raises TimeoutError | PASS |
| 14 | --max-retained 0 rejected by CLI | PASS |
| 15 | --max-retained -1 rejected by CLI | PASS |

### memory_write.py tests (16-24)

| # | Test | Status |
|---|------|--------|
| 16 | require_acquired() raises when not acquired | PASS |
| 17 | require_acquired() passes when acquired | PASS |
| 18 | Existing test_lock_timeout backward compat | PASS |
| 19 | Existing test_permission_denied backward compat | PASS |
| 20 | retire_record() matches do_retire() behavior (fields, changes) | PASS |
| 21 | retire_record() relative path via memory_root.parent.parent | PASS |
| 22 | retire_record() on already-retired -> idempotent | PASS |
| 23 | retire_record() on archived -> RuntimeError | PASS |
| 24 | FlockIndex rename: no _flock_index references remain | PASS |

## Implementation Notes

- Tests use `conftest.py` fixtures (`make_session_memory`, `write_memory_file`, `write_index`, `build_enriched_index`).
- Tests 14-15 use subprocess to test CLI validation (since `argparse` + `sys.exit` is best tested end-to-end).
- Tests 16, 18 reduce `_LOCK_TIMEOUT` to 0.2s for fast execution (avoids 15s waits in CI).
- Test 08 uses `unittest.mock.patch` on `memory_enforce.retire_record` to simulate structural errors.
- Test 09 uses mock to raise `FileNotFoundError` on first call, verifying the `continue` behavior.
- Test 24 does source-level verification that all 6 action handlers use `FlockIndex` (not `_flock_index`).
