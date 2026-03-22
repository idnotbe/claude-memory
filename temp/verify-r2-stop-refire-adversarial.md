# Verification Round 2: Adversarial Review -- Stop Hook Re-fire Fix

**Reviewer:** V-R2 (Adversarial)
**Date:** 2026-03-22
**Files reviewed:**
- `hooks/scripts/memory_triage.py` (sentinel, lock, stop flag, `_run_triage()` rewrite)
- `hooks/scripts/memory_write.py` (`_STAGING_CLEANUP_PATTERNS`)
- `tests/test_memory_triage.py` (`TestStopHookRefireFix` class)
- V-R1 reports: correctness, security, operational

**External reviewers:** Codex (codereviewer), Gemini 3.1 Pro (codereviewer)

---

## Verdict: 1 HIGH bug, 1 MEDIUM bug, 1 MEDIUM security, 3 LOW issues

The V-R1 fixes are structurally correct. However, the V-R1 `O_NONBLOCK` + `fstat` fix introduced a **new bug** (double-close) that was not present before. Additionally, the `STOP_FLAG_TTL` fix has zero test coverage, making it fragile to regression. A pre-existing symlink-following vulnerability in `set_stop_flag()` was missed by all V-R1 reviewers.

---

## NEW Findings (not in V-R1)

### H1: Double-close bug in `read_sentinel()` -- introduced by V-R1 Fix 3

**Location:** `memory_triage.py:618-634`

```python
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
try:
    st = os.fstat(fd)
    import stat as stat_mod
    if not stat_mod.S_ISREG(st.st_mode):
        os.close(fd)    # <-- close #1 (line 624)
        return None
    raw = os.read(fd, 4096).decode("utf-8", errors="replace")
finally:
    os.close(fd)         # <-- close #2 (line 628, ALWAYS runs)
```

**Problem:** When the file is not a regular file (FIFO, directory, device), the code closes `fd` explicitly on line 624, then `return None` on line 625 triggers the `finally` block on line 628, which closes `fd` **again**. Python's `finally` always executes after `return`.

**Confirmed behavior (tested):**
- In single-threaded code: the second `os.close()` raises `OSError(EBADF)`, which is caught by the outer `except (OSError, ...)` on line 633 and returns `None`. Functionally correct but wasteful.
- In multi-threaded code: between close #1 and close #2, another thread can open a file and receive the same fd number (fd reuse). Close #2 then closes the **other thread's file descriptor**, causing silent data corruption or read failures in that thread.
- **Deliberately triggerable:** An attacker who controls the `/tmp/` staging directory (per V-R1 Security H1) can replace `.triage-handled` with a *directory*. Linux allows `os.open()` on directories (confirmed by testing). This forces `S_ISREG` to return `False`, triggering the double-close path every time.

**Impact:** HIGH. This is a regression introduced by V-R1 Fix 3 (the `O_NONBLOCK` + `fstat` fix). While the triage hook is currently single-threaded (cross-process concurrency, not cross-thread), this is a correctness bug that violates POSIX fd ownership semantics and creates a latent vulnerability if threading is ever added.

**Fix:** Remove the explicit `os.close(fd)` on line 624. Let the `finally` block own all fd cleanup:

```python
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
try:
    st = os.fstat(fd)
    import stat as stat_mod
    if not stat_mod.S_ISREG(st.st_mode):
        return None       # finally handles close
    raw = os.read(fd, 4096).decode("utf-8", errors="replace")
finally:
    os.close(fd)
```

**Consensus:** Both Codex and Gemini confirmed this finding independently. Codex rated it Low (single-threaded context), Gemini rated it High (attackable via directory substitution). I rate it HIGH because (a) it is a V-R1-introduced regression, (b) it is trivially fixable, and (c) the attacker-triggerable variant compounds with V-R1 Security H1.

---

### M1: `STOP_FLAG_TTL` has zero test coverage

**Location:** `memory_triage.py:69,573` (definition and usage) vs. `tests/test_memory_triage.py` (test file)

**Problem:** V-R1 Fix 1 added `STOP_FLAG_TTL = 300` and changed `check_stop_flag()` to use it instead of `FLAG_TTL_SECONDS = 1800`. This is one of the most important fixes (prevents cross-session bleed). However:

1. `STOP_FLAG_TTL` is **not imported** in the test file
2. No test verifies that `check_stop_flag()` uses `STOP_FLAG_TTL` (300s) instead of `FLAG_TTL_SECONDS` (1800s)
3. The existing `test_flag_ttl_covers_save_flow` only asserts `FLAG_TTL_SECONDS >= 1800` -- it does not test the separation
4. All integration tests mock out `check_stop_flag` entirely (`mock.patch("memory_triage.check_stop_flag", return_value=False)`)

**Impact:** MEDIUM. A future refactor could accidentally revert `check_stop_flag()` to use `FLAG_TTL_SECONDS` without any test failing, silently reintroducing the cross-session bleed bug that was the original HIGH operational finding.

**Fix:** Add tests:
```python
from memory_triage import STOP_FLAG_TTL

def test_stop_flag_ttl_is_separate():
    """STOP_FLAG_TTL must be shorter than FLAG_TTL_SECONDS."""
    assert STOP_FLAG_TTL < FLAG_TTL_SECONDS
    assert STOP_FLAG_TTL == 300

def test_check_stop_flag_uses_stop_flag_ttl(tmp_path):
    """check_stop_flag should use STOP_FLAG_TTL (300s), not FLAG_TTL_SECONDS (1800s)."""
    proj = tmp_path / "proj"
    claude_dir = proj / ".claude"
    claude_dir.mkdir(parents=True)
    flag = claude_dir / ".stop_hook_active"
    # Write a flag that is 400s old (> STOP_FLAG_TTL but < FLAG_TTL_SECONDS)
    flag.write_text(str(time.time()))
    stale_time = time.time() - 400
    os.utime(str(flag), (stale_time, stale_time))
    # Should return False (expired per STOP_FLAG_TTL=300)
    assert check_stop_flag(str(proj)) is False
```

**Consensus:** Both Codex and Gemini confirmed the coverage gap.

---

### M2: `set_stop_flag()` follows symlinks via `Path.write_text()` (Security)

**Location:** `memory_triage.py:578-585`

```python
def set_stop_flag(cwd: str) -> None:
    flag_path = Path(cwd) / ".claude" / ".stop_hook_active"
    try:
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(str(time.time()), encoding="utf-8")  # follows symlinks!
    except OSError:
        pass
```

**Problem:** `Path.write_text()` follows symlinks. If `.claude/.stop_hook_active` is a symlink (committed to repo, or placed by attacker), `set_stop_flag()` writes the timestamp to the symlink target. Combined with the fact that `check_stop_flag()` does NOT unlink the symlink when `stat()` raises `FileNotFoundError` on a dangling symlink (because the exception is caught and returns `False`), the attack flow is:

1. Attacker creates `.claude/.stop_hook_active` as a dangling symlink to `~/target_file`
2. `check_stop_flag()` is called: `stat()` fails with `FileNotFoundError` (dangling), returns `False`, symlink persists
3. `set_stop_flag()` is called: `write_text()` follows the symlink, creates `~/target_file` with timestamp content

**Confirmed by testing:** The symlink-following behavior was verified empirically. `Path.write_text()` creates the target file through the dangling symlink.

**Impact:** MEDIUM (security). Arbitrary file creation with attacker-chosen path but non-attacker-controlled content (just a timestamp float). The attacker must be able to place a symlink in the project's `.claude/` directory, which requires write access to the repo. Pre-existing vulnerability, not introduced by V-R1, but missed by V-R1 Security review.

**Fix:** Use `os.open()` with `O_NOFOLLOW` in `set_stop_flag()`, matching the pattern already used in `write_sentinel()`:

```python
def set_stop_flag(cwd: str) -> None:
    flag_path = os.path.join(cwd, ".claude", ".stop_hook_active")
    try:
        os.makedirs(os.path.dirname(flag_path), exist_ok=True)
        fd = os.open(flag_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, str(time.time()).encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass
```

**Source:** Gemini identified this independently. Codex did not flag it.

---

### L1: `import stat as stat_mod` inside function body -- uncaught `ImportError`

**Location:** `memory_triage.py:622`

**Problem:** The `import stat as stat_mod` is inside `read_sentinel()`. If `stat` fails to import (extremely rare -- corrupted Python installation), `ImportError` propagates out of the function. The `except` clause on line 633 only catches `OSError, json.JSONDecodeError, UnicodeDecodeError`, not `ImportError`. This would crash `check_sentinel_session()` and propagate up to `_run_triage()`, where it would be caught by `main()`'s catch-all `except Exception` (line 1305) and fail-open.

**Impact:** LOW. The crash is caught by the outer handler and fails open. However, hoisting the import to module scope is cleaner and eliminates the edge case entirely.

**Fix:** Move `import stat as stat_mod` to the module's import block at the top of the file, or add `ImportError` to the except clause.

**Consensus:** Both Codex and Gemini confirmed; both rated it as a style/hardening nit.

---

### L2: No test for `read_sentinel()` non-regular-file rejection

**Location:** `tests/test_memory_triage.py` -- `TestStopHookRefireFix` class

**Problem:** The V-R1 fix added `fstat()` + `S_ISREG` checking to `read_sentinel()`, but there is no test that exercises this path. A FIFO- or directory-based test would verify fail-open behavior and would have caught Finding H1 (double-close) during development.

**Impact:** LOW (coverage gap). The code path works correctly despite the double-close (outer except catches the EBADF), but this path should be tested.

**Fix:** Add test:
```python
def test_read_sentinel_rejects_directory(self, tmp_path):
    """read_sentinel returns None for non-regular files (directory)."""
    proj = tmp_path / "proj"
    staging = Path(get_staging_dir(str(proj)))
    staging.mkdir(parents=True, exist_ok=True)
    # Replace sentinel path with a directory
    sentinel_dir = staging / ".triage-handled"
    sentinel_dir.mkdir()
    assert read_sentinel(str(proj)) is None
```

**Consensus:** Codex independently flagged this gap.

---

### L3: No test for corrupted/garbage sentinel content

**Location:** `tests/test_memory_triage.py`

**Problem:** V-R1 Correctness noted "NOT COVERED: Corrupted sentinel timestamp (M1 scenario)" but did not add tests. The test suite has no negative tests for:
- Invalid JSON in sentinel file
- Empty sentinel file
- Binary garbage in sentinel file
- Sentinel with missing required keys

**Impact:** LOW. All these paths return `None` from `read_sentinel()` (fail-open via `json.JSONDecodeError` or the `isinstance(data, dict)` check), which is correct behavior. But without tests, a future change could break the fail-open contract.

---

## V-R1 Fix Assessment

### Fix 1: `STOP_FLAG_TTL = 300` -- Correct but untested (M1 above)
The code change is correct. `check_stop_flag()` now uses `STOP_FLAG_TTL` instead of `FLAG_TTL_SECONDS`. But zero test coverage makes this fragile.

### Fix 2: TTL `except` fail-open (`return False`) -- Correct
Line 702: `return False` instead of `pass`. This is correct and verified by code inspection.

### Fix 3: `O_NONBLOCK` + `fstat` -- Introduced double-close bug (H1 above)
The intent is correct (prevent FIFO DoS), but the implementation has a double-close bug in the non-regular-file path.

### Fix 4: `cwd` realpath validation -- Correct
`os.path.realpath()` + `os.path.isdir()` correctly handles dangling symlinks, path traversal, and normal paths. Verified by testing.

---

## Checklist Results

### V-R1 fixes introduced new issues?
- **YES:** Fix 3 introduced H1 (double-close in read_sentinel)
- Others: No new issues

### `STOP_FLAG_TTL` exported/importable?
- **YES:** It's a module-level constant, importable. But NOT imported in the test file and NOT tested.

### `O_NONBLOCK` on regular files?
- **SAFE:** Tested empirically. `O_NONBLOCK` on regular files has no side effects on Linux; reads return immediately with available data.

### `cwd` realpath + symlinked project directories?
- **SAFE:** `os.path.realpath()` resolves symlinks to their real target. If the project is accessed via a symlink, the resolved path is used for all operations, which is correct and consistent.

### Empty `session_id` matching?
- **SAFE (by accident):** If `transcript_path` is `None` or empty, `get_session_id()` returns `""`. The guards at lines 1355-1360 check `if session_id and ...`, so empty session_id bypasses all guards. However, `_run_triage()` exits at line 1379 (`not transcript_path or not os.path.isfile(transcript_path)`) before reaching the scoring logic, so the bypassed guards are moot.

### Two sessions with same transcript filename stem?
- **Real concern, LOW:** Two `/tmp/transcript-abc123.json` paths from different sessions would produce the same `session_id`. One session's sentinel would block the other's triage. This is a design limitation of using `Path.stem` for session identity. Practically unlikely since Claude Code generates unique transcript filenames.

### Disk full during sentinel write (`ENOSPC`)?
- **SAFE:** `write_sentinel()` catches `OSError` and returns `False` (fail-open). The tmp file cleanup may leave a partial file if `os.unlink()` also fails, but this is acceptable operational debris.

### Staging dir doesn't exist when sentinel read?
- **SAFE:** `os.open()` raises `FileNotFoundError` (subclass of `OSError`), caught by except clause, returns `None`.

### `os.getpid()` wraparound?
- **SAFE:** PID is used for tmp file naming (`{path}.{pid}.tmp`) with `O_TRUNC`. If PID wraps and a stale tmp exists from a previous process with the same PID, `O_TRUNC` safely overwrites it. For the lock file, `os.getpid()` is just informational metadata inside the JSON; lock correctness does not depend on PID uniqueness.

### `os.path.realpath()` with dangling symlinks?
- **SAFE:** Returns the non-existent target path. `os.path.isdir()` returns `False`. Confirmed by testing.

---

## External Reviewer Agreement Matrix

| Finding | Opus (V-R2) | Codex | Gemini |
|---------|-------------|-------|--------|
| H1: Double-close in read_sentinel | HIGH | LOW (confirmed, downgraded) | HIGH (confirmed, attacker-triggerable) |
| M1: STOP_FLAG_TTL untested | MEDIUM | LOW (confirmed) | MEDIUM (confirmed) |
| M2: set_stop_flag symlink-following | MEDIUM | -- (not flagged) | CRITICAL (flagged independently) |
| L1: import stat inside function | LOW | Not material | LOW (confirmed) |
| L2: No non-regular-file test | LOW | LOW (flagged independently) | -- |
| L3: No corrupted sentinel tests | LOW | -- | -- |

### Gemini additional findings (evaluated):
- **Predictable /tmp/ staging dir DoS:** Real, but pre-existing (already documented in V-R1 Security H1). Not new.
- **Partial writes in write_sentinel:** Theoretically possible for large payloads, but the sentinel JSON is ~150 bytes. Linux guarantees atomicity for writes <= PIPE_BUF (4096 bytes) on regular files with `O_WRONLY`. Not a practical issue.
- **Python 3.8 `missing_ok=True`:** Valid compatibility concern if Python 3.7 support is needed. The project likely requires 3.8+ given other f-string and walrus operator usage.

---

## Recommended Fix Priority

1. **H1** (double-close): One-line fix, zero risk, eliminates a V-R1-introduced regression. Must fix before merge.
2. **M1** (STOP_FLAG_TTL tests): Add 2-3 tests. Important for regression protection of the most critical fix.
3. **M2** (set_stop_flag symlink): Replace `Path.write_text` with `O_NOFOLLOW` open. Pre-existing but easy to fix.
4. **L1-L3** (hardening): Hoist import, add negative tests. Follow-up items.

---

## Verdict

The V-R1 fixes are architecturally sound and address the right root causes. However, Fix 3 introduced a new double-close bug that is trivially fixable but should not ship as-is. The `STOP_FLAG_TTL` separation (Fix 1) is the most important operational fix but has zero test coverage, making it the most likely to regress. The `set_stop_flag()` symlink vulnerability is a pre-existing security issue that V-R1 missed and should be addressed alongside these fixes.
