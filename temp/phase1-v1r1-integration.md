# Phase 1 V1R1 -- Integration & Edge Case Review

**Verdict: PASS_WITH_FIXES**

**Reviewer:** v1r1-integration agent (Opus 4.6)
**Cross-validated:** Gemini 3.1 Pro via PAL clink (Codex 5.3 hit rate limit)
**Date:** 2026-02-28

---

## Test Results

```
pytest tests/test_memory_triage.py tests/test_adversarial_descriptions.py -q
202 passed in 0.51s
```

All existing tests pass. No regressions.

---

## End-to-End Flow Analysis

The externalization chain is **complete and correct**:

1. `_run_triage()` triggers categories via `run_triage()` (line 1052)
2. `write_context_files()` writes per-category context files + creates staging dir (line 1139)
3. `build_triage_data()` builds structured JSON dict (line 1147)
4. Atomic write: `.PID.tmp` -> `json.dump()` -> `os.replace()` -> `triage-data.json` (lines 1154-1170)
5. `format_block_message()` receives `triage_data_path` and emits `<triage_data_file>` tag (line 1180)
6. stdout JSON: `{"decision": "block", "reason": "...<triage_data_file>/path/...</triage_data_file>..."}` (line 1185)
7. SKILL.md Phase 0 (line 58): "First try: Extract the file path from within `<triage_data_file>...</triage_data_file>` tags"
8. Fallback: inline `<triage_data>` JSON block if file write fails (line 1177 sets path to None)

**JSON double-encoding:** Verified safe. `format_block_message()` builds a plain string with the `<triage_data_file>` tag. `json.dumps()` at line 1185 properly escapes it within the `reason` field. When Claude Code parses the JSON, the agent sees the literal tag text.

---

## Issues Found

### Issue 1 (Medium): `except OSError` too narrow on outer handler

**Location:** `hooks/scripts/memory_triage.py:1171`

The outer `except OSError:` only catches OS-level errors. If `json.dump()` raises `TypeError` or `ValueError` (non-serializable data), the exception propagates unhandled. The `.PID.tmp` file leaks and the inline fallback is never triggered.

**Practical risk:** LOW. `build_triage_data()` returns a dict of strings, numbers, and lists -- all JSON-serializable by construction. The input comes from internal functions, not user input. A `TypeError` would indicate a code bug, not a runtime condition. The global fail-open handler in main() catches any uncaught exception.

**Recommended fix:** Change `except OSError:` to `except Exception:` to ensure tmp cleanup and inline fallback on any failure type.

### Issue 2 (Low): SKILL.md cleanup commands omit `*.tmp` files

**Location:** `SKILL.md:50` and `SKILL.md:241`

Both cleanup commands (`rm -f ...`) list `triage-data.json`, `context-*.txt`, `.triage-handled`, `.triage-pending.json` but do not clean up orphaned `*.tmp` files. If the process is killed between `os.open()` and `os.replace()`, a stale `.PID.tmp` file remains.

**Practical risk:** VERY LOW. The `.tmp` files are PID-specific, inert, and never read by consumers. Accumulation requires repeated crashes.

**Recommended fix:** Add `*.tmp` glob to both cleanup commands.

### Issue 3 (Informational): Inner fd close triggers harmless EBADF

**Location:** `hooks/scripts/memory_triage.py:1164-1168`

When `os.fdopen()` succeeds and the `with` block raises an exception, the file object's `__exit__` closes `fd`. The inner `except` then tries `os.close(fd)` which raises `OSError(EBADF)`, caught and silently swallowed. Technically correct but unidiomatic.

**Practical risk:** NONE. The pattern is safe.

**No fix needed** -- style observation, not a bug.

---

## Edge Case Analysis

| Edge Case | Result |
|-----------|--------|
| Staging dir doesn't exist | SAFE -- created by sentinel `os.makedirs` (line 1123) before triage-data write. Also created by `write_context_files()` (line 760). If both fail, `os.open` raises ENOENT caught by outer `except OSError`. |
| Stale `.PID.tmp` from crashed write | SAFE -- different PIDs create different filenames. Same PID reuse after crash: `O_CREAT \| O_TRUNC` overwrites. |
| `os.replace()` fails after json.dump | SAFE -- outer `except OSError` catches, unlinks tmp, sets `triage_data_path=None` for inline fallback. |
| Concurrent read during `os.replace()` | SAFE -- POSIX `rename()` is atomic. Readers see either old or new file, never partial. |
| `triage_data_path=None` at format time | SAFE -- `format_block_message()` falls back to inline `<triage_data>` block (lines 966-973). |

---

## Deploy Order Safety

**SAFE.** SKILL.md already contains `<triage_data_file>` parsing at line 58. The fallback chain ensures backwards compatibility: if `triage_data_path` is None, `format_block_message()` outputs inline `<triage_data>` which older SKILL.md versions handle.

---

## Test Coverage Analysis

### Covered:
- `build_triage_data()`: basic structure, descriptions, defaults, missing context paths, JSON serializability (6 tests)
- `format_block_message()` with file path / without / default / with descriptions (4 tests)
- `_run_triage()` end-to-end: writes `triage-data.json`, `<triage_data_file>` in output (1 test)
- `_run_triage()` fallback: `os.open` failure -> inline `<triage_data>` (1 test)

### Gaps (non-blocking):
1. **`os.replace()` failure** after tmp write succeeds -- would verify fallback + tmp cleanup
2. **Multi-category triage-data.json** -- existing tests only trigger DECISION
3. **Content cross-validation** -- triage-data.json `context_file` paths vs actual disk files

---

## Cross-Validation (Gemini 3.1 Pro)

Gemini independently confirmed:
- Atomic write pattern is robust (os.replace + O_NOFOLLOW + 0o600 permissions)
- No race conditions with concurrent readers (POSIX rename atomicity)
- Same Issue 1 (except OSError too narrow) flagged as highest risk
- Same Issue 2 (cleanup omits *.tmp) flagged
- Fallback chain confirmed complete and correct
- os.fdopen EBADF pattern flagged as unidiomatic but safe

---

## Verdict

**PASS_WITH_FIXES** -- The externalization flow is functionally correct and well-tested. Two advisory fixes recommended (neither is a blocker):

| # | Issue | Severity | Blocker? |
|---|-------|----------|----------|
| 1 | Broaden `except OSError` to `except Exception` | Medium (advisory) | No |
| 2 | Add `*.tmp` to SKILL.md cleanup commands | Low (advisory) | No |
| 3 | Inner fd EBADF pattern | Informational | No |
