# Stop Hook Re-fire — Clink Review (All Phases)

## Codex Review (codex-5.3)

### High: Lock fail-open defeats TOCTOU prevention
- `_acquire_triage_lock()` returned None on FileExistsError, caller proceeded anyway
- Two concurrent hooks could both pass guards and emit block
- **Fixed**: Lock now returns `(path, status)` tuple. `HELD` -> `return 0` (yield to holder)

### High: Sentinel state machine has dead states
- Only `write_sentinel(..., "pending")` exists in codebase
- Nothing advances to `saving/saved/failed`
- `FLAG_TTL_SECONDS=1800` without timestamp check = indefinite suppression
- **Fixed**: Added TTL check in `check_sentinel_session()`. Sentinel expires after FLAG_TTL_SECONDS even within same session.
- Note: Save pipeline in SKILL.md will call write_sentinel to advance states (future work)

### Medium: RUNBOOK negative filter too blunt
- "On error, restart the worker; this fixed the crash" scored 0.0
- Line-level skip was too aggressive for non-anchored patterns
- **Fixed**: Anchored negatives to markdown headings and list-item doc scaffolding only

### Low: Pre-existing staging path migration test failures
- 4 tests expect cwd-local staging path, but staging_utils uses /tmp/-based path
- Pre-existing issue from staging_utils refactoring, not from this fix
- Status: All 1095 tests pass after our changes (resolved by other working tree changes)

## Gemini Review (gemini-3.1-pro)

### Critical: TOCTOU lock defeated by fail-open
- Same finding as Codex
- **Fixed**: See above

### High: macOS /private/tmp transcript validation
- `os.path.realpath("/tmp/...")` on macOS resolves to `/private/tmp/...`
- Path validation `startswith("/tmp/")` would fail
- **Not fixed**: Pre-existing issue, out of scope for this fix. Filed as note.

### Low: Inaccurate TTL comment in memory_write.py
- Comment said "Its TTL provides self-cleanup" but sentinel is now session-scoped
- **Fixed**: Updated comment to "Session-scoped: overwritten by new sessions, expired via FLAG_TTL_SECONDS safety net"

## Positives (both reviewers)
- Excluding .triage-handled from cleanup is the right fix
- Atomic tmp+replace writes with O_NOFOLLOW are solid
- try/finally lock release is correctly placed
- Fail-open semantics on all error paths
- Broader staging validation in memory_write.py
