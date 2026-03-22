# Source Analysis: fix-stop-hook-refire Changes

Comprehensive function-level analysis of all code added or modified in the "fix-stop-hook-refire" action plan across 3 source files. Purpose: identify every testable code path, edge case, and security check.

---

## File 1: memory_triage.py

**Path**: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_triage.py`

### Constants Changed

| Constant | Line | Old Value | New Value | Purpose |
|----------|------|-----------|-----------|---------|
| `FLAG_TTL_SECONDS` | 76 | 300 | 1800 | Extended to cover 10-28 min save flows; prevents sentinel/result guard expiring mid-save |
| `STOP_FLAG_TTL` | 80 | (new) | 300 | Separate TTL for `.stop_hook_active` flag; prevents cross-session bleed that V-R1 HIGH found |
| `DEFAULT_THRESHOLDS["RUNBOOK"]` | 88 | 0.4 | 0.5 | Raised to reduce SKILL.md keyword contamination false positives |

### Functions Added or Modified

#### 1. `check_stop_flag(cwd: str) -> bool` (lines 603-619)

**Modified**: Now uses `STOP_FLAG_TTL` (300s) instead of `FLAG_TTL_SECONDS` (1800s).

**Code paths**:
- Flag file exists and age < STOP_FLAG_TTL -> returns True (skip triage, allow stop)
- Flag file exists and age >= STOP_FLAG_TTL -> returns False (stale, proceed with triage)
- Flag file does not exist (OSError) -> returns False (proceed with triage)
- Flag deletion via `unlink(missing_ok=True)` after reading mtime

**Edge cases**:
- TOCTOU: file could be deleted between `stat()` and `unlink()` -- handled by `missing_ok=True`
- Negative mtime (clock skew) -> `age` would be large, returns False (correct behavior)
- `time.time()` returns float; mtime is float; subtraction safe

**Testable assertions**:
- Fresh flag (age=0) returns True
- Expired flag (age=STOP_FLAG_TTL) returns False
- Missing flag returns False
- Flag is deleted after check regardless of TTL result
- Uses `STOP_FLAG_TTL` not `FLAG_TTL_SECONDS`

#### 2. `set_stop_flag(cwd: str) -> None` (lines 622-640)

**Modified**: Now uses `O_NOFOLLOW` flag for symlink safety (V-R2 finding).

**Code paths**:
- `.claude` dir exists -> creates/overwrites flag file with timestamp
- `.claude` dir does not exist -> `makedirs` creates it, then creates flag
- `makedirs` fails (permissions) -> silently passes (non-critical)
- `os.open` fails (OSError) -> silently passes
- Symlink at flag path -> `O_NOFOLLOW` causes OSError -> silently passes

**Security checks**:
- `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW` prevents symlink following
- File permissions `0o600` (owner read/write only)

**Edge cases**:
- Flag path is a symlink -> OSError raised by O_NOFOLLOW -> silent pass
- Directory `.claude` is a symlink -> `makedirs` will follow it (no defense here)
- Write to fd writes `str(time.time())` encoded as UTF-8
- `os.close(fd)` in finally block ensures no fd leak

**Testable assertions**:
- Creates `.claude/.stop_hook_active` file
- File contains a timestamp
- Symlink at flag path is not followed
- Permission is 0o600

#### 3. `_sentinel_path(cwd: str) -> str` (lines 655-662)

**Added**: Returns absolute path to `.triage-handled` in staging dir.

**Code paths**:
- Calls `get_staging_dir(cwd)` + joins `.triage-handled`

**Testable assertions**:
- Returns `<staging_dir>/.triage-handled`
- Deterministic for same cwd

#### 4. `read_sentinel(cwd: str) -> Optional[dict]` (lines 665-687)

**Added**: Reads sentinel JSON with security hardening.

**Code paths**:
- File exists, is regular file, contains valid JSON dict -> returns dict
- File exists, is regular file, contains valid JSON non-dict -> returns None
- File exists, is regular file, contains invalid JSON -> returns None (JSONDecodeError)
- File exists, is not regular file (FIFO, device) -> returns None (fstat S_ISREG check)
- File does not exist -> returns None (OSError)
- File is a symlink -> `O_NOFOLLOW` raises OSError -> returns None
- File unreadable (permissions) -> OSError -> returns None
- UnicodeDecodeError -> returns None

**Security checks**:
- `O_RDONLY | O_NOFOLLOW | O_NONBLOCK` prevents symlink following and FIFO DoS
- `os.fstat(fd)` + `stat_mod.S_ISREG` rejects non-regular files
- Read limited to 4096 bytes (prevents memory exhaustion)
- `finally: os.close(fd)` prevents fd leak

**Edge cases**:
- Empty file -> `json.loads("")` raises JSONDecodeError -> returns None
- File larger than 4096 bytes -> truncated read, likely invalid JSON -> returns None
- O_NONBLOCK on regular file: on Linux this is a no-op for regular files (harmless)
- Concurrent write while reading -> partial JSON -> JSONDecodeError -> returns None

**Testable assertions**:
- Valid JSON dict returns the dict
- Non-dict JSON returns None
- Invalid JSON returns None
- Nonexistent file returns None
- Symlink returns None (O_NOFOLLOW)
- FIFO/device returns None (S_ISREG check)
- fd is always closed (no leak)

#### 5. `write_sentinel(cwd: str, session_id: str, state: str) -> bool` (lines 690-727)

**Added**: Atomic sentinel write via tmp+rename.

**Code paths**:
- Staging dir creation succeeds -> writes tmp file -> renames -> returns True
- Staging dir creation fails (OSError/RuntimeError) -> returns False
- tmp file write fails -> cleans up tmp -> returns False
- os.replace fails -> cleans up tmp -> returns False
- tmp cleanup itself fails (double OSError) -> returns False

**Security checks**:
- `ensure_staging_dir(cwd)` called for symlink/ownership defense
- `O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW` on tmp file
- File permissions `0o600`

**Edge cases**:
- tmp file name includes PID for uniqueness: `f"{path}.{os.getpid()}.tmp"`
- Sentinel JSON format: `{"session_id", "state", "timestamp", "pid"}`
- Concurrent writes from same PID: tmp file overwritten (O_TRUNC)
- `os.replace` is atomic on same filesystem (POSIX guarantee)

**Testable assertions**:
- Returns True on success
- Returns False on staging dir failure
- Returns False on write failure
- Sentinel file contains valid JSON with session_id, state, timestamp, pid
- Uses atomic tmp+rename pattern
- Stale tmp cleaned on failure

#### 6. `check_sentinel_session(cwd: str, current_session_id: str) -> bool` (lines 730-764)

**Added**: Session-scoped idempotency check.

**Code paths**:
- No sentinel exists -> returns False (proceed)
- Sentinel exists, different session_id -> returns False (proceed)
- Sentinel exists, empty session_id -> returns False (proceed)
- Sentinel exists, same session, expired (age >= FLAG_TTL_SECONDS) -> returns False (proceed)
- Sentinel exists, same session, invalid timestamp (TypeError/ValueError) -> returns False (proceed, fail-open)
- Sentinel exists, same session, within TTL, state in blocking set {pending, saving, saved} -> returns True (skip)
- Sentinel exists, same session, within TTL, state = "failed" -> returns False (proceed, allows re-triage)
- Sentinel exists, same session, within TTL, unknown state -> returns False

**Security checks**:
- `FLAG_TTL_SECONDS` (1800s) safety net prevents permanent suppression
- Fail-open on all error paths

**Edge cases**:
- `sentinel_ts` could be string, None, or non-numeric -> `float()` conversion may raise TypeError/ValueError -> returns False
- `current_session_id = ""` -> `sentinel_session != current_session_id or not sentinel_session` -> depends on sentinel value
- State "failed" explicitly allows re-triage (recovery path)

**Testable assertions**:
- Same session + pending state -> skip (True)
- Same session + saving state -> skip (True)
- Same session + saved state -> skip (True)
- Same session + failed state -> proceed (False)
- Different session -> proceed (False)
- Expired sentinel -> proceed (False)
- Invalid timestamp -> proceed (False)
- No sentinel -> proceed (False)
- Empty session_id in sentinel -> proceed (False)

#### 7. `_check_save_result_guard(cwd: str, current_session_id: str) -> bool` (lines 767-825)

**Added**: Defense-in-depth guard checking `last-save-result.json`.

**Code paths**:
- **Primary path**: Result file has `session_id` field matching `current_session_id` -> returns True
- **Primary path**: Result file has `session_id` field not matching -> continues to next candidate
- **Fallback path**: Result file lacks `session_id`, sentinel has matching session + blocking state -> returns True
- **Fallback path**: Result file lacks `session_id`, sentinel mismatch -> continues
- Result file stale (age >= FLAG_TTL_SECONDS) -> skip to next candidate
- Result file missing (OSError) -> skip to next candidate
- Result file unreadable or invalid JSON -> `result_data = {}` (fail-open)
- No candidates match -> returns False

**Candidate paths checked**:
1. `<cwd>/.claude/memory/.staging/last-save-result.json` (legacy)
2. `<staging_dir>/last-save-result.json` (new /tmp/ path)

**Security checks**:
- `O_RDONLY | O_NOFOLLOW` on result file read
- Read limited to 16384 bytes
- Age check against `FLAG_TTL_SECONDS`

**Edge cases**:
- `get_staging_dir()` raises exception -> only legacy path checked (catches `Exception`)
- `result_data` is not a dict -> `result_session` = None -> falls through to fallback
- `result_session` is non-string -> treated as absent -> falls through to fallback
- Both candidates exist with different session_ids -> checks both, returns False if neither matches
- Fresh result with matching session_id but sentinel says "failed" -> still returns True (guard is independent of sentinel state for primary path)

**Testable assertions**:
- Fresh result with matching session_id -> skip (True)
- Fresh result with different session_id -> proceed (False)
- Stale result -> proceed (False)
- Missing result -> proceed (False)
- Result without session_id + matching sentinel -> skip (True)
- Result without session_id + mismatched sentinel -> proceed (False)
- Both legacy and /tmp/ paths checked
- Bad JSON in result file -> graceful degradation

#### 8. `_acquire_triage_lock(cwd: str, session_id: str) -> tuple[str, str]` (lines 838-886)

**Added**: Atomic lock via `O_CREAT|O_EXCL`.

**Code paths**:
- Staging dir creation fails -> returns ("", _LOCK_ERROR)
- Lock file created successfully (O_EXCL) -> returns (lock_path, _LOCK_ACQUIRED)
- Lock file exists, fresh (< 120s) -> returns (lock_path, _LOCK_HELD)
- Lock file exists, stale (> 120s) -> deletes + retries:
  - Retry succeeds -> returns (lock_path, _LOCK_ACQUIRED)
  - Retry fails (FileExistsError/OSError) -> returns (lock_path, _LOCK_HELD)
- Lock file exists, can't stat -> returns (lock_path, _LOCK_HELD)
- os.open fails with non-FileExistsError OSError -> returns (lock_path, _LOCK_ERROR)

**Security checks**:
- `O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW` prevents race conditions
- Lock content includes session_id, pid, timestamp (JSON)
- `ensure_staging_dir(cwd)` for staging directory defense

**Edge cases**:
- Stale lock detection uses 120s threshold (any triage completes in <1s)
- Lock file in staging dir (consistent with sentinel)
- PID reuse scenario: stale lock from same PID -> stale detection handles it
- Two processes racing for stale lock cleanup: one wins O_EXCL, other gets HELD

**Testable assertions**:
- Clean acquisition returns ACQUIRED
- Existing fresh lock returns HELD
- Stale lock (>120s) cleaned and re-acquired
- Lock content is valid JSON with session_id, pid, timestamp
- Staging dir failure returns ERROR
- O_NOFOLLOW used

#### 9. `_release_triage_lock(lock_path: str) -> None` (lines 889-894)

**Added**: Best-effort lock release.

**Code paths**:
- File exists -> deleted
- File doesn't exist -> silently passes
- Deletion fails (permissions) -> silently passes

**Testable assertions**:
- Lock file deleted on release
- No exception on missing file

#### 10. `_run_triage() -> int` (lines 1391-1568) — MODIFIED

**Key modifications**:

**Step 4 - Session-scoped idempotency guards** (lines 1419-1435):
- Derives `session_id` early via `get_session_id(transcript_path)`
- Checks `check_stop_flag(cwd)` (backward compat)
- Checks `check_sentinel_session(cwd, session_id)`
- Checks `_check_save_result_guard(cwd, session_id)`
- Each returns 0 (allow stop) if guard fires

**Step 5 - Atomic lock** (lines 1437-1447):
- Acquires lock, yields if HELD, proceeds on ERROR (fail-open)

**Step 5.5 - Double-check under lock** (lines 1449-1451):
- Re-checks sentinel after acquiring lock (double-check locking pattern)

**Step 6 - cwd validation** (line 1410-1412):
- `cwd = os.path.realpath(hook_input.get("cwd", os.getcwd()))` (V-R1 fix: realpath)
- `os.path.isdir(cwd)` validation (rejects non-directories)

**Step 6 - Transcript path validation** (lines 1457-1461):
- `os.path.realpath(transcript_path)` resolves symlinks
- Validates path starts with `/tmp/` or `$HOME/`

**Step 9 - On block** (lines 1500-1561):
- Calls `set_stop_flag(cwd)` (with O_NOFOLLOW)
- Calls `write_sentinel(cwd, session_id, "pending")`
- Writes context files and triage data (atomic, O_NOFOLLOW)

**Step finally - Lock release** (lines 1565-1568):
- Releases lock if status was ACQUIRED (V-R2 finding)

**Edge cases in flow**:
- `session_id = ""` when `get_session_id` fails -> sentinel checks short-circuit (`session_id and ...` is False)
- Lock HELD -> returns 0 immediately (no triage)
- Lock ERROR -> proceeds without lock (sentinel provides idempotency)
- Sentinel re-check under lock prevents TOCTOU between initial check and lock acquisition
- triage_data_path = None on write failure -> inline fallback in format_block_message

**Testable assertions**:
- Full flow: stdin JSON -> check guards -> check lock -> parse transcript -> score -> output
- cwd validation rejects non-directory paths
- cwd is realpath-resolved
- transcript path validated against /tmp/ or $HOME
- Lock released in finally block
- Sentinel re-checked under lock

### RUNBOOK Negative Patterns (lines 162-201)

**Added**: 5 groups of negative patterns to reduce false positives from SKILL.md contamination.

**Group 1** (line 163-168): Markdown headings for error/retry sections
- `^#+\s*Error\s+Handling\b`
- `^#+\s*(?:Retry|Fallback)\s+(?:Logic|Strategy)\b`
- `^#+\s*(?:Write\s+Pipeline\s+Protections|Step\s+\d+:)`

**Group 2** (line 171-173): Conditional subagent failure instructions
- `^[-*]\s*If\s+(?:a\s+)?(?:subagent|Task\s+subagent)\s+fails`

**Group 3** (line 177-182): Phase 3 save command templates
- `Execute\s+(?:these\s+)?memory\s+save\s+commands`
- `memory_write\.py.*--action\s+[-\w]+`
- `memory_enforce\.py\b`

**Group 4** (line 185-191): Phase 3 subagent prompt boilerplate
- `CRITICAL:\s*Using\s+heredoc`
- `Minimal\s+Console\s+Output`
- `Combine\s+ALL\s+numbered\s+commands`
- `NEVER\s+use\s+Bash\s+for\s+file\s+writes`

**Group 5** (line 195-200): SKILL.md-specific instructional patterns
- `^Run\s+the\s+following\b`
- `If\s+ALL\s+commands\s+succeeded\s*\(no\s+errors\)`
- `If\s+ANY\s+command\s+failed,\s+do\s+NOT\s+delete`

**Code path in `score_text_category()`** (line 460):
- Before checking primary patterns on a line, all negative patterns are checked
- If any negative pattern matches the line, the entire line is skipped (no scoring)
- Negative patterns are ONLY defined for RUNBOOK (other categories have empty list)

**Testable assertions**:
- Lines matching any negative pattern are excluded from RUNBOOK scoring
- Negative patterns don't affect non-RUNBOOK categories
- Real troubleshooting text (e.g., "The error was fixed by...") is NOT suppressed
- Each of the 5 groups correctly matches its target text
- Each group does NOT match legitimate error discussion text

### Sentinel State Constants (line 652)

```python
_SENTINEL_BLOCK_STATES = frozenset({"pending", "saving", "saved"})
```

**Testable assertions**:
- "pending" is in blocking set
- "saving" is in blocking set
- "saved" is in blocking set
- "failed" is NOT in blocking set
- Unknown states are NOT in blocking set

---

## File 2: memory_staging_utils.py

**Path**: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_staging_utils.py`

### Functions Added or Modified

#### 1. `_validate_existing_staging(staging_dir: str) -> None` (lines 63-94)

**Added**: Shared validation helper for existing staging directories.

**Code paths**:
- Path is a symlink -> raises RuntimeError
- Path exists but is not a directory (regular file, FIFO, etc.) -> raises RuntimeError
- Path owned by different UID -> raises RuntimeError
- Path has group/other permissions (0o077 mask) -> chmod to 0o700 (auto-fix)
- Path is valid directory, owned by us, correct perms -> returns None (success)

**Security checks**:
- `os.lstat()` (not stat) to detect symlinks without following them
- `stat.S_ISLNK(st.st_mode)` explicit symlink check
- `stat.S_ISDIR(st.st_mode)` type check (V-R2 finding: prevents non-directory)
- `st.st_uid != os.geteuid()` ownership check
- `stat.S_IMODE(st.st_mode) & 0o077` permission check with auto-tightening

**Edge cases**:
- TOCTOU between lstat and chmod: acknowledged in comment as practically unexploitable (/tmp sticky bit, user workspace)
- `os.chmod` could fail if path was deleted between lstat and chmod -> OSError
- Character device or block device at path -> caught by S_ISDIR check
- Socket at path -> caught by S_ISDIR check
- Path owned by root but current user is non-root -> raises RuntimeError

**Testable assertions**:
- Symlink raises RuntimeError with "symlink" in message
- Non-directory raises RuntimeError with "not a directory" in message
- Foreign ownership raises RuntimeError with uid info
- World-readable permissions auto-tightened to 0o700
- Valid directory returns without error
- Uses lstat (not stat)

#### 2. `validate_staging_dir(staging_dir: str) -> None` (lines 97-126)

**Added**: Unified creation + validation for both /tmp/ and legacy staging paths.

**Code paths for /tmp/ staging** (starts with STAGING_DIR_PREFIX):
- Directory doesn't exist -> `os.mkdir(staging_dir, 0o700)` creates it
- Directory exists -> `_validate_existing_staging()` called
- mkdir fails for non-FileExistsError reason -> OSError propagates

**Code paths for legacy staging** (doesn't start with STAGING_DIR_PREFIX):
- Parent doesn't exist -> `os.makedirs(parent, mode=0o700, exist_ok=True)` creates parents
- Parent exists -> skips makedirs
- Final component doesn't exist -> `os.mkdir(staging_dir, 0o700)` creates it
- Final component exists -> `_validate_existing_staging()` called

**Edge cases**:
- Parent is empty string (root path) -> `os.path.dirname("/foo") = "/"`, isdir("/") is True -> skips makedirs
- Legacy path like `/home/user/.claude/memory/.staging` -> parent is `/home/user/.claude/memory`
- makedirs for parents uses `exist_ok=True` (safe for concurrent calls)
- mkdir for final component uses raw `os.mkdir` (no exist_ok) -> FileExistsError triggers validation

**Testable assertions**:
- /tmp/ path: creates with 0o700
- /tmp/ path: validates existing (calls _validate_existing_staging)
- Legacy path: creates parents if needed
- Legacy path: validates existing final component
- Correct permissions on new directories
- Rejects symlinked staging dirs (via _validate_existing_staging)

#### 3. `ensure_staging_dir(cwd: str) -> str` (lines 41-60) — MODIFIED

**Modified**: Now delegates to `validate_staging_dir()` instead of inline logic.

**Code paths**:
- Computes staging dir path via `get_staging_dir(cwd)`
- Calls `validate_staging_dir(staging_dir)` for creation/validation
- Returns staging_dir path

**Testable assertions**:
- Returns the staging directory path
- Raises RuntimeError if staging dir is compromised (propagated from validate_staging_dir)

#### 4. Inline fallback functions (lines 42-53 in triage.py)

**Modified**: The inline fallback `ensure_staging_dir()` inside `memory_triage.py` (when `memory_staging_utils` import fails) also has symlink + ownership defense, but lacks S_ISDIR check and permission tightening that the shared helper has.

**Testable gap**:
- Fallback lacks S_ISDIR check
- Fallback lacks permission auto-tightening

---

## File 3: memory_write.py

**Path**: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_write.py`

### Constants Changed

| Constant | Line | Change | Purpose |
|----------|------|--------|---------|
| `_STAGING_CLEANUP_PATTERNS` | 523-534 | Removed `.triage-handled` from list | Sentinel must survive cleanup to prevent re-fire |
| `_SAVE_RESULT_ALLOWED_KEYS` | 636 | Added `"session_id"` | Session ID in save result for guard independence |

### Functions Added or Modified

#### 1. `_is_valid_legacy_staging(resolved_path: str, allow_child: bool = False) -> bool` (lines 81-102)

**Added**: Validates legacy staging paths require `.claude/memory/.staging` ancestry.

**Code paths**:
- Path contains `.claude` -> `memory` -> `.staging` sequence:
  - `allow_child=False`: `.staging` must be the last component -> returns True
  - `allow_child=True`: `.staging` can have children -> returns True
- Path contains `memory/.staging` but not under `.claude` -> returns False
- Path has no `.claude/memory/.staging` sequence -> returns False

**Edge cases**:
- `/tmp/evil/.claude/memory/.staging` -> returns True (has the required sequence)
- `/tmp/evil/memory/.staging` -> returns False (no `.claude` parent)
- `/home/user/.claude/memory/.staging/file.json` with allow_child=False -> returns False
- `/home/user/.claude/memory/.staging/file.json` with allow_child=True -> returns True
- `.claude` appearing multiple times in path -> first match wins
- `.claude` at very end of path (i+2 >= len(parts)) -> returns False

**Testable assertions**:
- Valid legacy path accepted
- Path without `.claude` parent rejected
- `allow_child=False` rejects files within staging
- `allow_child=True` accepts files within staging
- Arbitrary paths like `/tmp/evil/memory/.staging` rejected

#### 2. `cleanup_staging(staging_dir: str) -> dict` (lines 537-582) — MODIFIED

**Key change**: `.triage-handled` removed from `_STAGING_CLEANUP_PATTERNS`.

**Modified behavior**:
- Sentinel file `.triage-handled` is now preserved during cleanup
- All other staging files (triage-data.json, context-*.txt, draft-*.json, etc.) still deleted
- `.triage-pending.json` still deleted

**Path containment** (lines 549-558):
- Accepts `/tmp/.claude-memory-staging-*` paths
- Accepts legacy `.claude/memory/.staging` paths via `_is_valid_legacy_staging()`
- Rejects all other paths

**Security checks**:
- Symlink rejection per file (`f.is_symlink()` -> skip)
- Path containment per file (`f.resolve().relative_to(staging_path)`)
- Catches RuntimeError from resolve() on symlink loops

**Testable assertions**:
- `.triage-handled` is NOT deleted by cleanup
- Other staging files ARE deleted
- Invalid staging paths rejected with error status
- Symlinked files skipped (counted in `skipped`)
- Files escaping staging dir via symlink skipped

#### 3. `cleanup_intents(staging_dir: str) -> dict` (lines 585-633) — MODIFIED

**Modified**: Added `_is_valid_legacy_staging()` validation for legacy paths.

**Path containment** identical to `cleanup_staging()`.

**Testable assertions**:
- Only `intent-*.json` files deleted
- Legacy path validation via `_is_valid_legacy_staging()`

#### 4. `write_save_result(staging_dir: str, result_json: str) -> dict` (lines 643-723) — MODIFIED

**Key changes**:
- `session_id` added to allowed keys (line 636)
- `session_id` validation: must be string or null (lines 708-710)
- `_is_valid_legacy_staging()` used for legacy path validation
- `validate_staging_dir()` called for symlink/ownership defense (lines 713-719)
- `RuntimeError` added to except clause (line 718, V-R1 fix)

**Code paths for session_id validation**:
- `session_id` absent -> OK (allowed)
- `session_id` is string -> OK
- `session_id` is None/null -> OK
- `session_id` is non-string (int, list, etc.) -> returns error

**Code paths for staging validation**:
- `validate_staging_dir` import succeeds -> validates staging dir
- `validate_staging_dir` import fails -> falls back to `os.makedirs`
- `validate_staging_dir` raises RuntimeError -> returns error (V-R1 fix)
- `validate_staging_dir` raises OSError -> returns error

**Testable assertions**:
- `session_id` field accepted in result JSON
- Non-string `session_id` rejected
- String or null `session_id` accepted
- RuntimeError from staging validation caught (not crash)
- Legacy path validation uses `_is_valid_legacy_staging()`

#### 5. `update_sentinel_state(staging_dir: str, target_state: str) -> dict` (lines 739-832)

**Added**: Atomically advances sentinel state.

**State machine** (lines 731-734):
```
pending -> {saving, failed}
saving  -> {saved, failed}
```

**Code paths**:
- Invalid target_state (not in {saving, saved, failed}) -> returns error
- Staging dir not valid (/tmp/ or legacy) -> returns error
- Cannot read sentinel (OSError/JSONDecodeError) -> returns error
- Sentinel not a dict -> returns error
- Invalid state transition (e.g., saved->saving) -> returns error with allowed transitions
- Valid transition -> updates state + timestamp, writes atomically -> returns ok with previous/new state + session_id
- Atomic write via tmp+rename with `O_CREAT | O_WRONLY | O_EXCL`
- Stale tmp from previous failed attempt (same PID) cleaned before write
- Write failure -> cleans tmp -> returns error

**Security checks**:
- `O_RDONLY | O_NOFOLLOW` for sentinel read
- `O_CREAT | O_WRONLY | O_EXCL` for tmp write (prevents hard link attacks)
- Path containment: `/tmp/.claude-memory-staging-*` or valid legacy path
- Read limited to 4096 bytes

**Edge cases**:
- Current state has no allowed transitions (e.g., "saved", "failed") -> `allowed = set()` -> returns error
- Unknown current state -> `_SENTINEL_TRANSITIONS.get(current_state, set())` returns empty set -> error
- Stale tmp file from crashed previous run with same PID -> unlinked before write
- `os.replace` atomicity guarantees
- session_id preserved from original sentinel data (not overwritten)

**Testable assertions**:
- pending -> saving: allowed
- pending -> failed: allowed
- saving -> saved: allowed
- saving -> failed: allowed
- saved -> anything: disallowed
- failed -> anything: disallowed
- pending -> saved: disallowed (must go through saving)
- Invalid target_state rejected
- Invalid staging dir rejected
- Unreadable sentinel returns error
- Non-dict sentinel returns error
- Response includes previous_state, new_state, session_id
- Atomic write (tmp+rename)
- Stale tmp cleaned

#### 6. `write-save-result-direct` CLI action (lines 1894-1948 in main()) — MODIFIED

**Key change**: Reads `session_id` from sentinel file and embeds it in result.

**Code paths for session_id extraction** (lines 1919-1936):
- Sentinel file exists and contains valid JSON with string session_id -> captured
- Sentinel file exists but lacks session_id -> `sentinel_session_id = None`
- Sentinel file exists but session_id is non-string -> `sentinel_session_id = None`
- Sentinel file doesn't exist (OSError) -> `sentinel_session_id = None`
- Sentinel file has invalid JSON (JSONDecodeError) -> `sentinel_session_id = None`
- Sentinel file read fails (UnicodeDecodeError) -> `sentinel_session_id = None`

**Security checks**:
- `O_RDONLY | O_NOFOLLOW` on sentinel read
- Read limited to 4096 bytes
- `Path(args.staging_dir).resolve()` for path resolution

**Testable assertions**:
- session_id embedded in result when sentinel has it
- session_id is None when sentinel missing/invalid
- Non-string session_id in sentinel not propagated
- Uses O_NOFOLLOW for sentinel read

#### 7. `update-sentinel-state` CLI action (lines 1860-1873 in main())

**Added**: CLI entry point for sentinel state advancement.

**Code paths**:
- Missing `--staging-dir` -> prints error JSON, returns 0 (fail-open)
- Missing `--state` -> prints error JSON, returns 0 (fail-open)
- Calls `update_sentinel_state()` -> prints result JSON
- Unexpected exception -> catches, prints error JSON, returns 0 (fail-open)

**Testable assertions**:
- Always returns exit code 0 (fail-open)
- Missing args produce error JSON
- Delegates to `update_sentinel_state()`
- Catches all exceptions

#### 8. `do_retire()` (lines 1328-1359) — MODIFIED

**Key change**: Catches `RuntimeError` in addition to `json.JSONDecodeError` and `OSError`.

**Code paths**:
- `retire_record()` raises RuntimeError (archived memory) -> prints error, returns 1

**Testable assertions**:
- RuntimeError from retire_record caught and formatted

#### 9. `_read_input()` (lines 1579-1627) — MODIFIED

**Key change**: Uses `_is_valid_legacy_staging(resolved, allow_child=True)` for legacy path validation.

**Testable assertions**:
- Legacy staging paths validated via `_is_valid_legacy_staging(allow_child=True)`
- Arbitrary `*/memory/.staging` without `.claude` parent rejected

---

## Cross-Cutting Concerns

### 1. FLAG_TTL_SECONDS vs STOP_FLAG_TTL Split

- `FLAG_TTL_SECONDS = 1800` used by: sentinel TTL, save-result guard TTL
- `STOP_FLAG_TTL = 300` used by: `check_stop_flag()` only
- Rationale: sentinel/result guards need long TTL for save flow; stop flag needs short TTL to prevent cross-session bleed

### 2. Session ID Flow

1. Derived from transcript path hash via `get_session_id(transcript_path)`
2. Written into sentinel by `write_sentinel(cwd, session_id, "pending")`
3. Read from sentinel by `write-save-result-direct` CLI action
4. Embedded in `last-save-result.json`
5. Checked by `_check_save_result_guard()` independently of sentinel

### 3. Fail-Open Pattern

Every security/idempotency check is fail-open:
- `check_stop_flag`: returns False on error
- `check_sentinel_session`: returns False on error
- `_check_save_result_guard`: returns False on error
- `_acquire_triage_lock`: _LOCK_ERROR proceeds without lock
- `update_sentinel_state` CLI: always returns exit 0
- `write_sentinel`: returns False on error

### 4. Symlink Safety Audit

| Location | O_NOFOLLOW | lstat | Notes |
|----------|-----------|-------|-------|
| `set_stop_flag` | Yes | No | V-R2 fix |
| `read_sentinel` | Yes | No | O_NONBLOCK also set |
| `write_sentinel` | Yes (tmp) | No | Via ensure_staging_dir for dir |
| `_validate_existing_staging` | N/A | Yes | Explicit S_ISLNK check |
| `_check_save_result_guard` | Yes | No | Per-file read |
| `_acquire_triage_lock` | Yes | No | O_EXCL also set |
| Triage data write | Yes | No | O_TRUNC also set |
| Context file write | Yes | No | O_TRUNC also set |

### 5. Atomic Write Patterns

| Operation | Pattern | Cleanup |
|-----------|---------|---------|
| Sentinel write | tmp (`{path}.{pid}.tmp`) + `os.replace` | Stale tmp deleted on failure |
| Sentinel state update | tmp (`{path}.{pid}.tmp`) + `os.replace` with O_EXCL | Pre-existing tmp deleted, failure tmp deleted |
| Triage data write | tmp (`{path}.{pid}.tmp`) + `os.replace` | Stale tmp deleted on failure |
| Save result write | `atomic_write_text` (mkstemp + rename) | Stale tmp deleted on failure |

---

## Summary Statistics

| File | Functions Added | Functions Modified | Constants Changed | Negative Pattern Groups | Security Checks |
|------|----------------|-------------------|-------------------|------------------------|-----------------|
| memory_triage.py | 8 | 2 | 3 | 5 | 12 |
| memory_staging_utils.py | 2 | 1 | 0 | 0 | 5 |
| memory_write.py | 2 | 5 | 2 | 0 | 6 |
| **Total** | **12** | **8** | **5** | **5** | **23** |
