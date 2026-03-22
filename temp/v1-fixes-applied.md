# V-R1 Fixes Applied

## Fix 1: Stop Flag TTL Regression (HIGH)
- Added `STOP_FLAG_TTL = 300` constant (separate from `FLAG_TTL_SECONDS = 1800`)
- `check_stop_flag()` now uses `STOP_FLAG_TTL` instead of `FLAG_TTL_SECONDS`
- Prevents cross-session bleed when new session starts within 30 min

## Fix 2: TTL Except Fail-Open (MEDIUM)
- `check_sentinel_session()` line 691-692: changed `pass` to `return False`
- Corrupted timestamp now allows re-triage (fail-open) instead of indefinite suppression

## Fix 3: FIFO DoS Prevention (MEDIUM)
- `read_sentinel()`: added `O_NONBLOCK` flag and `fstat()` check
- Rejects non-regular files (FIFOs, devices, sockets) before reading

## Fix 4: CWD Validation (MEDIUM)
- `_run_triage()`: `cwd` now passes through `os.path.realpath()` + `os.path.isdir()` check
- Prevents path traversal via malicious cwd in hook input

## Known Limitations (not fixed, documented)
- M2: Sentinel state never advances beyond "pending" (requires SKILL.md orchestration changes)
- H1/Security: /tmp/ staging dir symlink hijack (pre-existing in memory_staging_utils.py)
- H2/Security: Lock TOCTOU double-acquisition (low practical risk, fcntl.flock would be better)
- L1/Security: Sentinel cross-session clobber (per-session sentinel filenames would fix)
