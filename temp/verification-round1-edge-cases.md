# Verification Round 1: Edge Cases and Security Review (Updated)

**Reviewer**: verifier-edge-cases
**Date**: 2026-02-18
**Scope**: R2-triage (staging paths), R3 (sentinel idempotency), R1/R2-SKILL/R5 (SKILL.md fixes)
**Files reviewed**:
- `hooks/scripts/memory_triage.py` (1062 lines)
- `tests/test_memory_triage.py` (1159 lines)
- `skills/memory-management/SKILL.md` (273 lines)
- `CLAUDE.md` (130 lines)

**Test results**: 56 passed (test_memory_triage.py), 120 passed (test_adversarial_descriptions.py), 216 passed total across triage-related suites

---

## 1. Staging Directory Edge Cases

### 1a. Fresh project (`.claude/memory/` does not exist yet)

**Verdict: PASS**

`write_context_files()` at line 707 calls `os.makedirs(staging_dir, exist_ok=True)` which creates the entire path chain including `.claude/`, `.claude/memory/`, and `.claude/memory/.staging/`. If creation fails (any OSError), `staging_dir` is set to empty string (line 709), triggering the `/tmp/` fallback at line 719. Same pattern for sentinel dir (line 1025) and score log dir (line 996).

Evidence: The test `test_block_output_is_valid_stdout_json` creates only `proj/.claude/memory/` (for config), and the staging dir `.staging/` is created automatically by the code. The `test_score_log_written` test confirms the staging path is auto-created.

### 1b. `.claude/memory/.staging/` already exists

**Verdict: PASS**

`os.makedirs(staging_dir, exist_ok=True)` is idempotent. If the directory already exists, it succeeds silently. This is used at all three staging directory creation points (lines 707, 996, 1025).

### 1c. No write permissions

**Verdict: PASS**

If `os.makedirs()` raises `OSError` (includes `PermissionError`), all three callsites catch it:
- Line 708-709: `staging_dir = ""` falls back to `/tmp/`
- Line 998-999: falls back to `log_path = "/tmp/.memory-triage-scores.log"`
- Line 1036-1037: `pass` (sentinel creation is non-critical)

Fail-open behavior is correct: inability to create staging dir does not block the stop hook.

### 1d. `/tmp/` fallback correctness

**Verdict: PASS**

When `cwd=""` (no cwd provided, backward compat for test callers) OR staging dir creation fails:
- Context files: written to `/tmp/.memory-triage-context-{cat_lower}.txt` (line 719)
- Score log: written to `/tmp/.memory-triage-scores.log` (line 999)

The fallback paths are consistent with the pre-fix behavior. All existing tests that call `write_context_files()` without `cwd` (6 calls in test_adversarial_descriptions.py, 3 in test_memory_triage.py) correctly get `/tmp/` paths.

---

## 2. Sentinel File Edge Cases

### 2a. Stale sentinel from a different session

**Verdict: PASS**

The sentinel check at lines 953-958 uses a time-based TTL:
```python
if time.time() - sentinel_mtime < FLAG_TTL_SECONDS:  # 300 seconds = 5 min
    return 0
```

A sentinel older than 5 minutes is ignored (the `OSError` catch handles both "file missing" and any stat failure). This means stale sentinels from previous sessions (>5 minutes ago) are effectively expired and do not suppress new triage.

### 2b. Clock jump (NTP correction)

**Verdict: PASS with NOTE**

If `time.time()` jumps backward (clock correction makes current time earlier), `time.time() - sentinel_mtime` could become negative, which is `< 300`, so triage would be suppressed. This is the safe direction: suppressing triage means allowing stop (not blocking), so the user is not trapped.

If `time.time()` jumps forward, `time.time() - sentinel_mtime` becomes very large, sentinel is expired, and triage runs normally.

NOTE: An extremely rare edge case where the clock jumps backward by >5 minutes and then a new session starts within that window could suppress triage for the new session. This is unlikely and non-critical (worst case: one missed auto-capture).

### 2c. Corrupted sentinel file

**Verdict: PASS**

The sentinel check uses `os.stat(sentinel_path).st_mtime` (line 954), not file contents. The mtime is filesystem metadata, not dependent on file contents. The sentinel file's contents (a timestamp string written at line 1033) are never read -- they exist only for human debugging. Even if the file is truncated or filled with garbage, mtime-based checking works correctly.

### 2d. Race condition between check and create

**Verdict: PASS (acceptable)**

There is a theoretical TOCTOU between checking the sentinel (line 953) and creating it (line 1027). If two hook invocations run near-simultaneously:
1. Process A checks sentinel: not found
2. Process B checks sentinel: not found
3. Process A creates sentinel and outputs block
4. Process B creates sentinel and outputs block

However, this race is extremely unlikely in practice because:
- The stop hook fires serially (Claude Code waits for the hook to complete)
- Even if it occurred, the consequence is a duplicate triage (not data loss or corruption)
- The existing `check_stop_flag()` at line 948 provides a first layer of idempotency

### 2e. Sentinel creation failure (OSError)

**Verdict: PASS**

Lines 1036-1037: `except OSError: pass`. Failure to create the sentinel is non-critical. The worst case is that triage fires again on the next stop attempt (pre-fix behavior). The comment "Non-critical: worst case is duplicate triage" accurately describes the impact.

---

## 3. Backward Compatibility

### 3a. All existing tests pass

**Verdict: PASS**

```
tests/test_memory_triage.py: 56 passed in 0.09s
tests/test_adversarial_descriptions.py: 120 passed in 0.13s
tests/test_arch_fixes.py: 40 passed, 10 xpassed
Total triage-related: 216 passed
```

### 3b. `write_context_files()` without `cwd`

**Verdict: PASS**

The function signature is `write_context_files(..., *, cwd: str = "", ...)`. Default `cwd=""` causes `staging_dir` to remain `""` (line 703-704: the `if cwd:` check fails), which triggers `/tmp/` fallback paths. This preserves backward compatibility for all callers not passing `cwd`.

Verified: 9 test callsites in test_memory_triage.py and test_adversarial_descriptions.py call without `cwd` and all pass.

### 3c. External callers of `write_context_files()`

**Verdict: PASS**

Searched all callers across the codebase. `write_context_files()` is called from:
1. `_run_triage()` at line 1041 -- now passes `cwd=cwd` (updated call site)
2. Test files (9 callsites) -- all use the default `cwd=""` or explicit kwarg

No external callers exist outside of the script and tests.

---

## 4. Security Review

### 4a. Sentinel uses O_NOFOLLOW

**Verdict: PASS**

Line 1027-1030:
```python
fd = os.open(
    sentinel_file,
    os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW,
    0o600,
)
```

`O_NOFOLLOW` prevents symlink attacks. `0o600` sets owner-only permissions. Confirmed `O_NOFOLLOW` is available on this platform (Linux, value 131072).

### 4b. Context files use O_NOFOLLOW

**Verdict: PASS**

Line 770-773:
```python
fd = os.open(
    path,
    os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW,
    0o600,
)
```

All three `os.open()` calls in the file use `O_NOFOLLOW`:
1. Context files (line 772) -- O_NOFOLLOW
2. Score log (line 1002) -- O_NOFOLLOW
3. Sentinel file (line 1029) -- O_NOFOLLOW

### 4c. Path traversal via category names

**Verdict: PASS**

Category names used in `write_context_files()` come exclusively from:
- `CATEGORY_PATTERNS` dict keys (hardcoded: DECISION, RUNBOOK, CONSTRAINT, TECH_DEBT, PREFERENCE)
- String literal "SESSION_SUMMARY" in `run_triage()`

These are `.lower()`'d to form filenames like `context-decision.txt`. No user-controlled input reaches the category names used in file paths. Path traversal via category is not possible.

### 4d. .staging directory permissions

**Verdict: PASS (acceptable)**

`os.makedirs(staging_dir, exist_ok=True)` creates directories with the default umask (typically 0o022, resulting in 0o755). Files within the staging dir are created with `0o600` (owner-only read/write). The directory itself is readable by others, but files are not. This is acceptable for a project-local `.claude/memory/.staging/` directory. The containing `.claude/` directory is typically also user-owned.

### 4e. Score log symlink protection

**Verdict: PASS (fixed from previous round)**

In the previous review round, the score log used plain `open()` without `O_NOFOLLOW`. This has been fixed. Line 1000-1003 now uses:
```python
fd = os.open(
    log_path,
    os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
    0o600,
)
```

This addresses the previous FINDING 2 (MEDIUM severity symlink risk).

---

## 5. CLAUDE.md Consistency

### 5a. Stale `/tmp/` reference in CLAUDE.md

**Verdict: FAIL (documentation inconsistency)**

CLAUDE.md line 31 still references the old path:
```
3. **Context files** at `/tmp/.memory-triage-context-<CATEGORY>.txt` with generous transcript excerpts
```

This should be updated to reference `.claude/memory/.staging/context-<category>.txt` with a note about `/tmp/` fallback. The code has been updated but the documentation has not.

The skill-fixer report (line 48) explicitly noted this: "CLAUDE.md line 31 still references `/tmp/.memory-triage-context-<CATEGORY>.txt` -- this is outside scope of Task #1 but should be updated separately for consistency."

### 5b. SKILL.md `/tmp/` references

**Verdict: PASS**

Grep for `/tmp/` in SKILL.md returns zero matches. All staging paths have been updated to `.claude/memory/.staging/`.

### 5c. SKILL.md script paths

**Verdict: PASS**

All 4 script invocations in SKILL.md now use `${CLAUDE_PLUGIN_ROOT}`:
- Line 86: `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_candidate.py" ...`
- Line 127: `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action create ...`
- Line 129: `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action update ...`
- Line 130: `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action delete ...`

### 5d. Plugin self-check (R5)

**Verdict: PASS**

SKILL.md line 19 has the self-check blockquote:
```
> **Plugin self-check:** Before running any memory operations, verify plugin
> scripts are accessible by confirming `"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/
> memory_candidate.py"` exists.
```

---

## 6. Previous Round Findings Status

| Finding | Severity | Status |
|---------|----------|--------|
| F1: `datetime.utcnow()` deprecation | MEDIUM | **FIXED** - Line 984 now uses `datetime.datetime.now(datetime.timezone.utc).isoformat()` |
| F2: Score log symlink risk | MEDIUM | **FIXED** - Now uses `os.open()` with `O_NOFOLLOW` and `0o600` |
| F3: `or` fallback correctness | LOW | No change needed (was already correct) |
| F4: `_sanitize_snippet` type guard | LOW | No change needed (all callers guarantee str) |
| F5: Missing test for `None` with flat fallback | LOW | Not addressed (test gap, non-critical) |
| F6: Score log cwd in world-readable `/tmp/` | INFO | **MITIGATED** - Score log now goes to project-local staging dir with `0o600` |
| F7: Concurrent score log writes | INFO | No change needed (was already safe) |

---

## Summary Table

| Item | Verdict |
|------|---------|
| 2.1a Fresh project `.claude/memory/` | PASS |
| 2.1b `.staging/` already exists | PASS |
| 2.1c No write permissions | PASS |
| 2.1d `/tmp/` fallback | PASS |
| 2.2a Stale sentinel | PASS |
| 2.2b Clock jump | PASS (note: backward jump suppresses triage -- safe direction) |
| 2.2c Corrupted sentinel | PASS (uses mtime, not content) |
| 2.2d Race condition | PASS (serial hook execution, benign consequence) |
| 2.2e Sentinel creation failure | PASS |
| 3a All existing tests pass | PASS (216 passed, 0 failed) |
| 3b `write_context_files()` without `cwd` | PASS |
| 3c External callers | PASS (none exist) |
| 4a Sentinel O_NOFOLLOW | PASS |
| 4b Context files O_NOFOLLOW | PASS |
| 4c Path traversal via category | PASS (hardcoded categories only) |
| 4d .staging dir permissions | PASS |
| 4e Score log symlink protection | PASS (fixed) |
| 5a CLAUDE.md stale `/tmp/` reference | **FAIL** (line 31 not updated) |
| 5b SKILL.md `/tmp/` references | PASS (all removed) |
| 5c SKILL.md script paths | PASS (all use `${CLAUDE_PLUGIN_ROOT}`) |
| 5d Plugin self-check | PASS |

---

## Overall Verdict

**PASS with 1 documentation issue.**

All code changes are correct, secure, and backward-compatible. The only outstanding item is CLAUDE.md line 31 which still references `/tmp/.memory-triage-context-<CATEGORY>.txt` instead of the new `.claude/memory/.staging/context-<category>.txt` path. This is a documentation-only issue and does not affect runtime behavior.

Previous round's two MEDIUM findings (datetime.utcnow deprecation and score log symlink risk) have both been fixed.
