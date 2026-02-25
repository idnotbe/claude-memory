# Plan #2 Phase 1-2: Self-Review

**Date:** 2026-02-25
**Module:** `hooks/scripts/memory_logger.py` (289 LOC)
**Config:** `assets/memory-config.default.json` (logging section added)
**Schema:** `temp/p2-logger-schema.md` (finalized)

---

## Correctness

### Checklist

- [x] All `os.write()` calls use single syscall (not fdopen)
  - Line 277: `os.write(fd, line_bytes)` -- direct file descriptor write
  - Line 158: `os.write(fd, str(now).encode("utf-8"))` -- cleanup timestamp write

- [x] Every code path has try/except with pass (fail-open)
  - `emit_event`: outer `except Exception: pass` at line 287-288
  - `cleanup_old_logs`: outer `except Exception: pass` at line 164-165
  - `parse_logging_config`: outer `except Exception` at line 66-67
  - `get_session_id`: outer `except Exception` at line 88-89
  - Inner loops in cleanup each have individual `except OSError: pass`

- [x] Level comparison works correctly (debug=0 < info=1 < warning=2 < error=3)
  - Lines 223-231: `event_level = _LEVELS.get(normalized_level, 1)` defaults unknown to info-level (1)
  - Unknown levels are clamped to "info" in output (line 230-231)

- [x] Cleanup doesn't race or crash on missing .last_cleanup
  - Line 114-120: `last_cleanup_file.exists()` wrapped in try/except OSError
  - Missing file = proceed with cleanup (safe default)

- [x] No external dependencies
  - Imports: json, os, re, time, datetime, pathlib -- all stdlib

- [x] results[] truncation is enforced
  - Lines 234-238: Checks `len(results) > _MAX_RESULTS`, truncates with shallow copy

- [x] Symlink attack prevention (O_NOFOLLOW on file opens, is_symlink() in cleanup)
  - Line 35: `_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)` -- portable
  - Lines 129, 136: Explicit `is_symlink()` checks before `is_dir()`/`is_file()` in cleanup

- [x] Directory creation is safe (makedirs exist_ok)
  - Line 151, 266: `os.makedirs(str(...), exist_ok=True)`

- [x] Timestamp is UTC ISO format
  - Lines 243-245: `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"`
  - Verified: produces "2026-02-25T10:30:00.123Z" format

- [x] session_id extraction handles edge cases
  - Empty string -> ""
  - None -> ""
  - Normal path -> stem (filename without extension)

---

## Security

### Path Traversal (FIXED)

`_sanitize_category()` (lines 172-185) uses a strict regex allowlist `^[a-zA-Z0-9_-]+$`. Any event_type that splits to an unsafe category (containing `/`, `..`, `.`, etc.) is sanitized by stripping non-safe characters. Empty result falls back to `"unknown"`. This prevents writing files outside `{memory_root}/logs/`.

**Tested:** `../../etc/cron.d.pwn` -> `"unknown"`, `../../../tmp.pwn` -> `"unknown"`

### Symlink Traversal in Cleanup (FIXED)

Cleanup now explicitly checks `is_symlink()` before `is_dir()` and `is_file()` (lines 129, 136). Symlinks are skipped entirely. This prevents an attacker from placing a symlink under `logs/` to redirect file deletion to external directories.

**Tested:** Created symlink `logs/evil -> /tmp/external/`, verified target files survive cleanup.

### Secret Residue Prevention

At info level, log entries contain only file paths, not titles. This matches the plan's privacy requirement. The schema contract documents that debug level may include titles.

### File Permissions

All log files created with mode `0o600` (owner read/write only). This prevents other users on a shared system from reading log data.

---

## Edge Cases

| Edge Case | Behavior | Verified |
|-----------|----------|----------|
| Logging disabled | Returns immediately, zero file I/O | Test 6 |
| Empty memory_root | Returns immediately | Test 14 |
| Missing logs directory | Created automatically (makedirs) | Test 7 |
| Invalid config (None, string, etc.) | Falls back to safe defaults | Test 13 |
| Invalid level string | Defaults to "info" (numeric=1) | Test 3, 18 |
| 50+ results in data | Truncated to 20, original dict not mutated | Test 9 |
| Non-serializable data (datetime, set) | Converted via `default=str` | Test 17 |
| Nonexistent memory_root path | Silently fails (fail-open) | Test 10 |
| Path traversal in event_type | Sanitized to safe characters | Test 15 |
| Symlink in log directory | Skipped during cleanup | Test 16 |
| .last_cleanup missing | Cleanup proceeds normally | Test 11 |
| .last_cleanup recent (< 24h) | Cleanup skipped | Test 12 |
| retention_days = 0 | Cleanup disabled | Covered by code path |
| retention_days < 0 | Falls back to 14 | Test 4 |

---

## POSIX Compliance

### O_APPEND Atomicity

POSIX.1 specifies that `O_APPEND` causes each `write()` to atomically seek to the end of the file before writing. For writes smaller than `PIPE_BUF` (typically 4096 bytes on Linux, 512 bytes minimum per POSIX), the write is guaranteed to be atomic. Our JSONL lines are typically < 2KB due to results[] truncation at 20 entries, well within this limit.

### O_NOFOLLOW

`O_NOFOLLOW` is POSIX.1-2008. The module uses `getattr(os, "O_NOFOLLOW", 0)` for portability on platforms that may not support it. On such platforms, the flag degrades to 0 (no symlink protection on file open), but cleanup still has explicit `is_symlink()` guards.

### File Descriptor Management

All `os.open()` calls are paired with `os.close()` in a `try/finally` block (lines 157-160, 276-279). No file descriptor leaks.

---

## Performance

### emit_event Hot Path

When logging is disabled (the default): `parse_logging_config()` + `dict.get()` + early return. No file I/O. Estimated < 1us.

When logging is enabled:
1. Config parse: ~1us (dict operations)
2. Level check: ~0.1us (dict lookup + comparison)
3. JSON serialization: ~10-50us (depends on data size)
4. makedirs: ~5us (exist_ok fast path after first call)
5. os.open + os.write + os.close: ~50-200us (disk I/O, but O_APPEND is kernel-buffered)
6. cleanup_old_logs: ~1us (stat() on .last_cleanup, early return via time gate)

**Total estimated p95: < 1ms** -- well within the < 5ms budget.

### Cleanup Overhead

The cleanup runs inside every `emit_event` call but is gated by `.last_cleanup` stat check. This adds one `stat()` syscall per emit (~5us). The actual directory walk happens at most once per 24 hours.

---

## Plan Compliance

| Plan Requirement | Status |
|------------------|--------|
| `emit_event()` interface matches plan spec | Compliant |
| `get_session_id()` interface | Compliant |
| `cleanup_old_logs()` interface | Compliant |
| `parse_logging_config()` interface | Compliant |
| stdlib only | Compliant |
| Atomic append via os.write | Compliant |
| O_NOFOLLOW | Compliant (portable) |
| Fail-open semantics | Compliant |
| Lazy file handle (no I/O if disabled) | Compliant |
| Level filtering | Compliant |
| Directory structure `logs/{category}/{date}.jsonl` | Compliant |
| schema_version: 1 in every event | Compliant |
| results[] max 20 | Compliant |
| Info level: paths only, no titles | Compliant (enforced at caller) |
| Config keys: enabled, level, retention_days | Compliant |
| Config defaults: false, "info", 14 | Compliant |
| LOC target: 80-120 | Slightly over at ~140 effective LOC (due to security fixes) |

### LOC Deviation

The module is ~140 effective LOC vs the plan's 80-120 estimate. The increase is due to security hardening added after cross-model review: `_sanitize_category()` (+14 LOC), symlink checks (+4 LOC), `_O_NOFOLLOW` portability (+1 LOC), level normalization (+3 LOC). This is justified by the Critical/High severity of the issues fixed.

---

## Remaining Work (Phase 3+)

This review covers Phase 1 (Schema Contract) and Phase 2 (Logger Module) only. Remaining phases:

- **Phase 3:** Instrument `memory_retrieve.py`, `memory_judge.py`, `memory_search_engine.py` with `emit_event()` calls
- **Phase 4:** Migrate `memory_triage.py` from `.triage-scores.log` to new logger
- **Phase 5:** Write `tests/test_memory_logger.py` (formal pytest suite)
- **Phase 6:** Update CLAUDE.md Key Files table
