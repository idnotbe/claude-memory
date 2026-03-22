# Security Review: Stop-Hook-Refire Fix (V-R1)

**Reviewer:** V-R1 Security
**Scope:** `hooks/scripts/memory_triage.py` (sentinel, lock, save-result guard, `_run_triage` rewrite), `hooks/scripts/memory_write.py` (cleanup pattern change)
**External reviewers:** Codex (codereviewer), Gemini 3.1 Pro (codereviewer) -- both converged on the same top findings

---

## Severity Summary

| Severity | Count | Description |
|----------|-------|-------------|
| HIGH     | 2     | Staging dir symlink hijack, lock TOCTOU double-acquisition |
| MEDIUM   | 2     | Unsanitized `cwd` from stdin, FIFO/special-file DoS on sentinel |
| LOW      | 2     | Sentinel cross-session clobber, 4096-byte truncation bypass |
| INFO     | 2     | PID-namespaced temp (safe), session_id JSON injection (safe) |

---

## HIGH Findings

### H1: `/tmp/` Staging Directory Symlink Hijack

**Location:** `memory_staging_utils.py:36-37`, `memory_triage.py:644`
**Both Codex and Gemini flagged this independently.**

The staging path `/tmp/.claude-memory-staging-{hash}` is deterministic (SHA-256 of `realpath(cwd)`). The hash is only 12 hex chars but collision is not the issue -- predictability is.

**Attack:** A local attacker pre-creates the directory as a symlink:
```bash
ln -s /home/victim/.ssh /tmp/.claude-memory-staging-abc123def456
```

`os.makedirs(staging_dir, mode=0o700, exist_ok=True)` follows the symlink and succeeds silently. All subsequent `O_NOFOLLOW` opens only protect the *final path component* (e.g., `.triage-handled`), not the parent directory. The sentinel, triage-data.json, and context files are written into the attacker-controlled target.

Even without a symlink, if the attacker pre-creates the directory with `0o777` permissions, `os.makedirs(exist_ok=True)` does NOT fix the permissions -- it silently succeeds with the existing mode. The attacker can then read/write sentinel files to manipulate triage state.

**Impact:** Arbitrary file writes (`.triage-handled`, `triage-data.json`, context files) to attacker-chosen directories. Sentinel tampering enables triage suppression or re-fire.

**Recommended fix:** After `os.makedirs`, validate with `os.lstat()`:
```python
st = os.lstat(staging_dir)
if not stat.S_ISDIR(st.st_mode):
    raise OSError("Staging path is not a real directory")
if st.st_uid != os.getuid():
    raise OSError("Staging directory not owned by current user")
if st.st_mode & 0o077:
    os.chmod(staging_dir, 0o700)
```

**Pre-existing:** This vulnerability exists in `memory_staging_utils.py` before this PR. The stop-refire fix *expands the attack surface* by writing more files (sentinel JSON) to this directory.

---

### H2: Stale Lock TOCTOU Allows Double Acquisition

**Location:** `memory_triage.py:782-795`
**Both Codex and Gemini flagged this independently.**

The stale lock recovery sequence is:
1. `os.stat(lock_path)` -- check age (line 783)
2. `os.unlink(lock_path)` -- delete stale lock (line 785)
3. `os.open(lock_path, O_CREAT | O_EXCL ...)` -- retry (line 788)

**Attack/Race:**
- Process A holds a legitimately stale lock (>120s old, crashed)
- Process B stats it, sees it's stale, gets suspended before unlink
- Process C stats it, sees it's stale, unlinks it, creates new lock (ACQUIRED)
- Process B resumes, unlinks C's fresh lock, creates its own (ACQUIRED)
- Both B and C believe they own the lock

**Impact:** Two concurrent triages can run, potentially writing conflicting sentinels and producing duplicate triage output. The sentinel double-check (line 1363) provides partial mitigation but doesn't fully prevent duplicate work.

**Recommended fix:** Replace with `fcntl.flock(fd, LOCK_EX | LOCK_NB)`:
```python
fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return fd, _LOCK_ACQUIRED
except BlockingIOError:
    os.close(fd)
    return "", _LOCK_HELD
```
Kernel releases lock automatically on process death -- no stale lock cleanup needed.

**Practical severity note:** In the actual deployment, triage runs are single-threaded short scripts (<1s) invoked by Claude Code's hook runner. The 120s timeout is generous. Two triages racing in real usage requires extremely precise timing. This is a correctness issue more than a practical exploit, but the fix is straightforward.

---

## MEDIUM Findings

### M1: Unsanitized `cwd` from Hook Input

**Location:** `memory_triage.py:1325`

```python
cwd: str = hook_input.get("cwd", os.getcwd())
```

`cwd` comes from stdin JSON (provided by Claude Code). It flows unsanitized into:
- `check_stop_flag(cwd)` -- reads/deletes `cwd/.claude/.stop_hook_active`
- `_acquire_triage_lock(cwd, ...)` -- creates `cwd/.claude/.stop_hook_lock`
- `set_stop_flag(cwd)` -- creates `cwd/.claude/.stop_hook_active`
- `write_sentinel(cwd, ...)` -- via `get_staging_dir(cwd)` which uses `os.path.realpath()` (safe for sentinel)
- `load_config(cwd)` -- reads `cwd/.claude/memory/memory-config.json`

**Impact:** A malicious `cwd` value like `../../../../etc` causes the script to create/read/delete `.claude/` subdirectories under arbitrary paths. However, the attacker must control stdin to Claude Code's hook process, which typically requires local code execution -- at which point they have broader access anyway.

**Threat model assessment:** Low practical risk because Claude Code controls the hook invocation and provides `cwd`. But defense-in-depth recommends:
```python
cwd = os.path.realpath(hook_input.get("cwd", os.getcwd()))
if not os.path.isdir(cwd):
    return 0
```

---

### M2: FIFO/Special File DoS on Sentinel Read

**Location:** `memory_triage.py:614`

```python
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
```

`O_NOFOLLOW` rejects symlinks but not FIFOs, device files, or sockets. If an attacker replaces the sentinel file with a named pipe:
```bash
mkfifo /tmp/.claude-memory-staging-hash/.triage-handled
```

The `os.open()` call will block indefinitely waiting for a writer, hanging the triage hook. Claude Code has a hook timeout, but this still causes a denial-of-service for that triage invocation.

**Fix:** Add `O_NONBLOCK` to the open, or `fstat()` after open and reject non-regular files:
```python
fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
st = os.fstat(fd)
if not stat.S_ISREG(st.st_mode):
    os.close(fd)
    return None
```

**Pre-existing:** Same pattern exists in the codebase before this PR. The hook timeout provides an external safety net.

---

## LOW Findings

### L1: Sentinel Cross-Session Clobber

**Location:** `memory_triage.py:603, 654`

`_sentinel_path()` returns one file per project (not per session). Two concurrent sessions for the same project will race on `os.replace()`. Session B's sentinel overwrites Session A's, causing A's idempotency guard to disappear. A later re-fire for Session A would not be suppressed.

**Impact:** Triage re-fire in a multi-session scenario. The lock provides partial protection, but the sentinel survives beyond the lock lifetime.

**Fix (if needed):** Use per-session sentinel filenames, e.g., `.triage-handled-{session_hash}`.

---

### L2: 4096-Byte Sentinel Truncation Bypass

**Location:** `memory_triage.py:616`

`os.read(fd, 4096)` is hard-capped. A sentinel file >4096 bytes (e.g., from an extremely long session_id) will be truncated, causing `json.loads()` to throw `JSONDecodeError`. `read_sentinel()` returns `None` (fail-open), and the idempotency check is bypassed.

**Practical impact:** `session_id` comes from `Path(transcript_path).stem`. Claude Code transcript paths are short (~50 chars), so this is not triggerable in normal usage. An attacker who can control transcript filenames could exploit this, but that requires a deeper compromise.

---

## INFORMATIONAL (Safe)

### I1: PID-Namespaced Temp Files

`write_sentinel()` uses `tmp_path = f"{path}.{os.getpid()}.tmp"` with `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW`. On PID recycling, `O_TRUNC` safely handles stale files and `O_NOFOLLOW` prevents symlink substitution. This is a well-implemented pattern.

### I2: session_id JSON Injection

`get_session_id()` returns `Path(transcript_path).stem`. All uses serialize via `json.dumps()`, which properly escapes special characters. No injection vector.

---

## Positive Security Practices

1. **`O_NOFOLLOW` consistently used** on all file creation/read paths for the final component
2. **`os.replace()` for atomic writes** -- no torn-write risk on sentinel or triage-data
3. **Fail-open design** throughout -- errors in the idempotency mechanism cause re-triage (annoying but not data-losing), never suppress triage
4. **Transcript path validation** (line 1371-1374) bounds transcript reads to `/tmp/` or `$HOME`
5. **Size-bounded reads** prevent memory exhaustion
6. **Staging cleanup exclusion** of `.triage-handled` is correctly done via pattern list, not ad-hoc logic

---

## Recommendations Priority

1. **Fix H1** (staging dir validation) -- highest practical impact, especially on shared machines
2. **Fix H2** (replace with `fcntl.flock`) -- straightforward, removes complexity
3. **Fix M2** (add `O_NONBLOCK` or `fstat` check) -- quick one-liner
4. **Consider M1** (canonicalize `cwd`) -- defense-in-depth, low urgency
5. **Defer L1/L2** -- edge cases with minimal practical impact

---

## Verdict

The stop-hook-refire fix is **architecturally sound** with good defensive patterns (fail-open, atomic writes, O_NOFOLLOW, bounded reads). The two HIGH findings (H1: staging dir hijack, H2: lock TOCTOU) are real but have important context: H1 is pre-existing (not introduced by this PR, only expanded), and H2 requires extremely precise timing in a scenario (concurrent Stop hooks for the same project) that is rare in practice. Both have clean, well-understood fixes. No data-corruption or remote-exploitation vectors found.
