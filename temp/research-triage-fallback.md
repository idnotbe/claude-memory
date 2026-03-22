# Research: Triage Fallback Symlink Bypass

## 1. Full Fallback Flow Trace

### Primary vulnerability: `memory_triage.py:1523-1526` (main() function)

```
main() triggers categories
  -> write_context_files()          # writes context-<category>.txt files
  -> build_triage_data()            # builds triage JSON in memory
  -> ensure_staging_dir(cwd)        # VALIDATES: symlink? foreign-owned?
     RAISES RuntimeError            # Symlink detected!
  -> FALLBACK: get_staging_dir(cwd) # Returns the SAME path!
  -> triage_data["staging_dir"] = _staging_dir  # Poisoned path stored in data
  -> triage_data_path = os.path.join(_staging_dir, "triage-data.json")
  -> os.open(tmp_path, O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW, 0o600)
     ^^ O_NOFOLLOW only protects the FINAL component (tmp file itself)
     ^^ The directory component /tmp/.claude-memory-staging-<hash> is STILL
        resolved through the symlink!
  -> json.dump(triage_data, f)      # Writes conversation excerpts to attacker path
  -> os.replace(tmp_path, triage_data_path)  # Atomic rename in attacker dir
```

**Data exposed**: `triage-data.json` contains:
- Category names and scores
- `staging_dir` path
- `parallel` config (model names, timeouts)
- `context_paths` dict (paths to context files with conversation excerpts)
- `category_descriptions`

### Secondary vulnerability: `write_context_files()` at line 1130-1133

Called BEFORE the main triage-data write (line 1509). Has its own fallback:

```
ensure_staging_dir(cwd)             # VALIDATES
  RAISES RuntimeError               # Symlink detected!
  -> staging_dir = ""               # Falls back to empty string
  -> path = f"/tmp/.memory-triage-context-{cat_lower}.txt"  # Predictable name!
  -> os.open(path, O_CREAT | O_WRONLY | O_TRUNC | O_NOFOLLOW, 0o600)
```

**Data exposed**: Context files contain:
- Category name, score, description
- `<transcript_data>` blocks with conversation excerpts (head + tail for session summaries, match-based excerpts for other categories)
- Key snippets from keyword matching
- Up to 50KB per file (`MAX_CONTEXT_FILE_BYTES`)

This fallback is LESS severe than the main one because:
- `/tmp/` itself is a real directory (trusted), not a symlink
- `O_NOFOLLOW` on the file basename does protect against symlinked files
- But the predictable names enable a different attack: pre-creating the file as a symlink to overwrite arbitrary files (mitigated by O_NOFOLLOW), or pre-creating the file to read its contents after the plugin writes (mitigated by 0o600 permissions, but TOCTOU exists)

## 2. ALL Similar Fallback Patterns

### Pattern A: Falls back to SAME compromised path (VULNERABLE)

| Location | Lines | Fallback behavior | Severity |
|----------|-------|-------------------|----------|
| `memory_triage.py` main() | 1523-1526 | `get_staging_dir(cwd)` = same path | **HIGH** -- writes triage-data.json with conversation data |

### Pattern B: Falls back to bare /tmp/ predictable paths (MODERATE)

| Location | Lines | Fallback behavior | Severity |
|----------|-------|-------------------|----------|
| `memory_triage.py` write_context_files() | 1130-1133 | `/tmp/.memory-triage-context-{cat}.txt` | **MODERATE** -- predictable names, O_NOFOLLOW mitigates symlink-on-file |

### Pattern C: Correctly degrades (SAFE)

| Location | Lines | Fallback behavior | Severity |
|----------|-------|-------------------|----------|
| `memory_triage.py` _acquire_triage_lock() | 847-849 | Returns `_LOCK_ERROR`, skips lock (fail-open) | **SAFE** -- no write to compromised path |
| `memory_triage.py` write_sentinel() | 709, 721 | `ensure_staging_dir()` inside try block, entire write wrapped in `except (OSError, RuntimeError)` -> returns False | **SAFE** -- aborts write on failure |

### Pattern D: Uses get_staging_dir() without ensure (READ-ONLY, LOW RISK)

| Location | Lines | Usage | Severity |
|----------|-------|-------|----------|
| `memory_triage.py` _sentinel_path() | 662 | Returns path for read_sentinel (read-only, O_RDONLY \| O_NOFOLLOW) | **LOW** -- reads only, fstat check on fd |
| `memory_triage.py` get_previous_save_result() | 785 | Reads last-save-result.json | **LOW** -- read-only |
| `memory_retrieve.py` main | 448 | Reads last-save-result.json and sentinel | **LOW** -- read-only |

### Pattern E: Different script, no fallback (SAFE)

| Location | Lines | Usage | Severity |
|----------|-------|-------|----------|
| `memory_draft.py` _ensure_staging_dir_safe() | 56-58, 250 | Calls validate_staging_dir() directly, no fallback | **SAFE** -- raises on failure, caller aborts |

## 3. Attack Surface Assessment

### Can an attacker pre-create the symlink?

**Yes.** The staging directory path is deterministic: `/tmp/.claude-memory-staging-<sha256(realpath(cwd))[:12]>`. An attacker who knows (or can guess) the project path can:

1. Compute the hash: `sha256(b"/home/idnotbe/projects/claude-memory").hexdigest()[:12]`
2. Create a symlink: `ln -s /attacker/controlled/dir /tmp/.claude-memory-staging-<hash>`

### Does /tmp/ sticky bit prevent this?

**No.** The sticky bit on `/tmp/` (mode 1777) only prevents:
- Deleting or renaming files/dirs owned by OTHER users

It does NOT prevent:
- Creating new files, directories, or symlinks in /tmp/
- Any user can create `/tmp/.claude-memory-staging-<hash>` -> `/anywhere`

### TOCTOU window in the success path

Even when `ensure_staging_dir()` succeeds, there is a time-of-check-to-time-of-use gap:

```
T1: ensure_staging_dir() validates -- dir is real, owned by us     [CHECK]
T2: attacker deletes the real dir (impossible due to sticky bit on /tmp/ if owned by us)
                                   ^^ Actually SAFE for /tmp/ top-level entries
T3: os.open(path_inside_dir, ...)                                  [USE]
```

The sticky bit actually DOES protect here for the success case: once our user creates the real directory in `/tmp/`, another user cannot delete or rename it. So the TOCTOU window in the success path is closed by the sticky bit.

The problem is exclusively in the FAILURE path: if the attacker creates the symlink FIRST (before our first `ensure_staging_dir()` call), validation correctly detects it, but the fallback ignores the detection result.

### What data is exposed?

In order of severity:
1. **triage-data.json**: Category triggers, scores, staging paths, config
2. **context-*.txt files**: Conversation transcript excerpts (up to 50KB each, up to 6 categories = 300KB of conversation data)
3. **Sentinel files**: Session ID, PID, timestamps (lower sensitivity)

## 4. Recommended Fix

### Option A: Degrade to inline data (RECOMMENDED)

**Rationale**: Simplest, most robust, zero new attack surface. The inline fallback path already exists and is tested (triage_data_path=None triggers inline `<triage_data>` emission).

#### Fix for main() -- lines 1523-1526

```python
# BEFORE (vulnerable):
try:
    _staging_dir = ensure_staging_dir(cwd)
except (OSError, RuntimeError):
    _staging_dir = get_staging_dir(cwd)  # BUG: same compromised path!

# AFTER (safe):
try:
    _staging_dir = ensure_staging_dir(cwd)
except (OSError, RuntimeError):
    _staging_dir = ""  # Degrade: no staging dir available
```

Then guard the triage-data.json write:

```python
triage_data_path = None
if _staging_dir:
    triage_data["staging_dir"] = _staging_dir
    triage_data_path = os.path.join(_staging_dir, "triage-data.json")
    tmp_path = None
    try:
        tmp_path = f"{triage_data_path}.{os.getpid()}.tmp"
        fd = os.open(
            tmp_path,
            os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
        )
        # ... existing write logic ...
    except Exception:
        # ... existing cleanup ...
        triage_data_path = None
# If _staging_dir was empty, triage_data_path stays None -> inline fallback
```

#### Fix for write_context_files() -- lines 1130-1133

```python
# BEFORE (moderate risk):
try:
    staging_dir = ensure_staging_dir(cwd or "")
except (OSError, RuntimeError):
    staging_dir = ""  # Falls through to predictable /tmp/ paths

# AFTER (safe):
try:
    staging_dir = ensure_staging_dir(cwd or "")
except (OSError, RuntimeError):
    staging_dir = ""
    # If staging dir is compromised, skip ALL context file writes
    return {}  # No context files -- subagents work without them
```

Alternatively, if context files are important for quality, use `tempfile.mkdtemp()`:

```python
except (OSError, RuntimeError):
    import tempfile
    staging_dir = tempfile.mkdtemp(prefix=".claude-memory-fallback-")
    # mkdtemp creates a unique dir with 0o700 permissions, owned by us
```

### Why NOT Option B (O_NOFOLLOW on directory)

Not possible with standard Python. `O_NOFOLLOW` on `os.open()` with `O_DIRECTORY` would work for opening the directory fd, but subsequent writes would need `dir_fd=` parameter everywhere. This is a much larger refactor.

### Why NOT Option C (dir_fd pattern) as primary fix

Codex confirmed that `os.open(path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW)` + `os.open("child", ..., dir_fd=dfd)` works in Python 3.11+. This is the most correct solution but:
- Requires refactoring every write site to use `dir_fd`
- `os.replace()` also needs `src_dir_fd` and `dst_dir_fd` parameters
- More invasive change = higher regression risk
- Not needed if we simply refuse to write to compromised paths

**Recommendation**: Use Option A now, consider Option C as a follow-up hardening pass for the success path (closing the theoretical TOCTOU window, which is already mitigated by sticky bit).

## 5. Cross-Model Opinion (Codex)

Codex confirmed the analysis and provided additional details:

### Key findings from Codex:
1. **Python's `os.open()` supports `dir_fd` parameter** -- this is the `openat()` equivalent. Verified working on Python 3.11.14.
2. **`O_NOFOLLOW` only applies to the final path component** -- confirmed. The directory traversal still resolves symlinks.
3. **The correct robust pattern** for when you must write to /tmp/:
   ```python
   dfd = os.open(staging_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
   st = os.fstat(dfd)  # Verify ownership/type on the OPEN fd
   fd = os.open("child.txt", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600, dir_fd=dfd)
   ```
4. **Best practice hierarchy**:
   - Prefer `$XDG_RUNTIME_DIR` / `/run/user/$UID` over `/tmp/` for sensitive data
   - If deterministic path needed, pin with directory fd + `dir_fd` for all child ops
   - If validation fails, REFUSE to write -- do not fall back to the same path
   - `tempfile.mkdtemp()` / `mkstemp()` for non-deterministic fallback
5. **Linux `openat2(RESOLVE_NO_SYMLINKS)`** is the gold standard but not exposed in Python stdlib.

### Codex's assessment of write_context_files fallback:
The bare `/tmp/.memory-triage-context-*.txt` fallback (line 1143) is less severe because `/tmp/` itself is trusted and `O_NOFOLLOW` protects the basename, but `mkstemp()` would be better than predictable names.

## 6. Summary of Required Changes

| File | Line(s) | Change | Priority |
|------|---------|--------|----------|
| `memory_triage.py` | 1525-1526 | Replace `get_staging_dir()` fallback with `_staging_dir = ""` | **P0** |
| `memory_triage.py` | 1527-1552 | Guard triage-data write with `if _staging_dir:` | **P0** |
| `memory_triage.py` | 1132-1133 | Return empty dict on staging failure (or use mkdtemp) | **P1** |
| `memory_staging_utils.py` | (new) | Consider adding `open_staging_dir_fd()` helper for dir_fd pattern | **P2** (follow-up) |
| All write sites | Various | Future: migrate to dir_fd pattern for TOCTOU closure | **P3** (follow-up) |
