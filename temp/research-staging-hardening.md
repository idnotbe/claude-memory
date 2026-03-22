# Research: validate_staging_dir() Hardening Gaps

**Date**: 2026-03-22
**Status**: Research complete
**Files analyzed**:
- `hooks/scripts/memory_staging_utils.py` (working tree with uncommitted changes)
- `hooks/scripts/memory_triage.py` (callers with fallback patterns)
- `hooks/scripts/memory_draft.py`, `hooks/scripts/memory_write.py` (other callers)
- `tests/test_memory_staging_utils.py` (existing test coverage)

---

## 1. validate_staging_dir() Flow Documentation

### Current State (Working Tree)

The working tree already refactored the validation into a shared helper `_validate_existing_staging()`. The flow:

```
validate_staging_dir(staging_dir)
  |
  +-- Is /tmp/ path? (starts with STAGING_DIR_PREFIX)
  |     |
  |     +-- os.mkdir(staging_dir, 0o700)
  |     |     SUCCESS -> return (new dir, safe: atomic mkdir, owned by us)
  |     |     FileExistsError -> _validate_existing_staging(staging_dir)
  |     |
  +-- Else (legacy path, e.g. <cwd>/.claude/memory/.staging)
        |
        +-- Create parent dirs: os.makedirs(parent, mode=0o700, exist_ok=True)
        +-- os.mkdir(staging_dir, 0o700)
              SUCCESS -> return
              FileExistsError -> _validate_existing_staging(staging_dir)

_validate_existing_staging(staging_dir):
  1. os.lstat(staging_dir) -> st
  2. S_ISLNK(st.st_mode)?  -> RuntimeError("symlink")
  3. S_ISDIR(st.st_mode)?   -> RuntimeError("not a directory")  [NEW - uncommitted]
  4. st.st_uid != geteuid()? -> RuntimeError("foreign ownership")
  5. S_IMODE & 0o077?        -> os.chmod(staging_dir, 0o700) [tighten perms]
```

### Key Security Properties
- **Atomic creation**: `os.mkdir()` is atomic on Linux/POSIX -- if it succeeds, we created it
- **lstat (not stat)**: Does not follow symlinks, so we inspect the actual path entry
- **S_ISDIR check** (new): Rejects regular files, FIFOs, sockets, device files
- **UID check**: Rejects directories owned by other users
- **Permission tightening**: Fixes overly permissive modes

---

## 2. Issue 1: Missing S_ISDIR Check -- ALREADY FIXED

### Status: Fixed in working tree (uncommitted)

The working tree diff adds `_validate_existing_staging()` with an explicit `S_ISDIR` check at line 80:

```python
if not stat.S_ISDIR(st.st_mode):
    raise RuntimeError(
        f"Staging path exists but is not a directory: {staging_dir}"
    )
```

### Previous Behavior (committed code)

Without S_ISDIR, if an attacker pre-creates a regular file at `/tmp/.claude-memory-staging-<hash>`:

1. `os.mkdir()` -> `FileExistsError`
2. `os.lstat()` -> stat result for the regular file
3. Symlink check -> PASSES (not a symlink)
4. UID check -> PASSES (same user created the file -- or attacker if shared project)
5. Permission check -> runs (may chmod a regular file, harmless)
6. Function returns without error
7. Caller attempts to write files "inside" this non-directory -> `ENOTDIR` / `NotADirectoryError`

**Impact assessment**: DoS (confusing errors), not exploitable for data exfiltration. The caller cannot be tricked into writing to attacker-controlled locations because the file open would fail. However, the error messages would be confusing and could mask the real attack vector.

### What the Fix Covers

The S_ISDIR check now rejects:
- Regular files
- FIFOs (`S_ISFIFO`)
- Sockets (`S_ISSOCK`)
- Block devices (`S_ISBLK`)
- Character devices (`S_ISCHR`)

All non-directory types are caught by `not S_ISDIR(st.st_mode)`.

### Remaining Work

The test at `test_memory_staging_utils.py:264` (`test_regular_file_at_path_does_not_pass_silently`) documents the OLD behavior (validate passes, file is not a dir). It needs updating to assert `RuntimeError` now that the fix is in place:

```python
def test_regular_file_at_path_raises_not_directory(self, tmp_path):
    """Regular file at staging path should raise RuntimeError."""
    staging_path = f"{STAGING_DIR_PREFIX}test_regular_file"
    try:
        with open(staging_path, "w") as f:
            f.write("not a directory")
        os.chmod(staging_path, 0o700)

        with pytest.raises(RuntimeError, match="not a directory"):
            validate_staging_dir(staging_path)
    finally:
        if os.path.exists(staging_path):
            os.unlink(staging_path)
```

Additional tests to add:
- FIFO at staging path -> RuntimeError
- Socket at staging path -> RuntimeError (if feasible in test environment)

---

## 3. Issue 2: Multi-User DoS via Hash Collision

### Problem

`get_staging_dir()` at line 37:
```python
project_hash = hashlib.sha256(os.path.realpath(cwd).encode()).hexdigest()[:12]
```

The hash depends only on `realpath(cwd)`, not on the user. Two users on the same project get the same staging path. The second user hits `RuntimeError("owned by uid ...")` from the UID check.

### Scenario Likelihood

| Environment | Likelihood | Impact |
|-------------|-----------|--------|
| Personal workstation | None | Single user, no collision |
| Shared dev server (SSH) | Low-Medium | Multiple developers on same project |
| CI/CD (Jenkins, GitHub Actions) | Low | Usually isolated workspaces, but shared runners possible |
| Docker (standard) | None | UID 0, /tmp isolated per container |
| Docker (rootless) | None | Mount namespace isolates /tmp |
| Pair programming (shared tmux) | Medium | Same machine, same project, different users |

Claude Code is a single-user CLI tool, so the primary deployment is personal workstations. However, shared servers are a real (if uncommon) scenario.

### Proposed Fix: UID-in-Hash

```python
def get_staging_dir(cwd: str = "") -> str:
    if not cwd:
        cwd = os.getcwd()
    # Include euid for per-user isolation on shared systems
    identity = f"{os.geteuid()}:{os.path.realpath(cwd)}"
    project_hash = hashlib.sha256(identity.encode()).hexdigest()[:12]
    return f"{STAGING_DIR_PREFIX}{project_hash}"
```

### Migration Considerations

**Breaking change**: Changing the hash formula means existing staging dirs become orphaned.

| Concern | Assessment |
|---------|-----------|
| Data loss | None -- staging dirs are ephemeral (triage data, intents, drafts). Stale data is cleaned up per-session anyway. |
| Orphaned dirs in /tmp | Harmless. OS-level `systemd-tmpfiles` or `tmpreaper` cleans /tmp periodically. On most distros, /tmp is cleared at reboot. |
| Active session disruption | If a triage is in-flight during upgrade, the new hash will miss the old staging dir. The triage will re-run on next stop hook. |
| Backward compatibility | The triage-data.json includes a `staging_dir` field, so SKILL.md orchestration reads the path from there rather than computing it. Only the initial creation is affected. |

**Recommendation**: Accept orphaned dirs. No migration logic needed. Add a comment documenting the hash change.

### Triage Fallback Bug (Codex Finding)

Codex flagged a critical issue at `memory_triage.py:1524-1526`:

```python
try:
    _staging_dir = ensure_staging_dir(cwd)
except (OSError, RuntimeError):
    _staging_dir = get_staging_dir(cwd)  # <-- UNSAFE FALLBACK
```

When `ensure_staging_dir()` raises RuntimeError (e.g., symlink detected, foreign ownership), the code falls back to `get_staging_dir()` -- the raw, unvalidated path -- and proceeds to write triage-data.json into it. This **defeats the entire validation**.

The same pattern appears at:
- `memory_triage.py:1524-1526` (triage data write)
- `memory_triage.py:1131-1133` (context file write -- but this one falls back to empty string, which is safer)
- `memory_triage.py:847-849` (lock acquisition -- falls back to `_LOCK_ERROR`, which is safe/fail-open)

**Fix**: When validation fails, fall back to inline triage data (the existing backwards-compatible codepath), not to the rejected path:

```python
try:
    _staging_dir = ensure_staging_dir(cwd)
except (OSError, RuntimeError):
    _staging_dir = ""  # Force inline fallback, don't use rejected path
```

### Alternative Approach: XDG_RUNTIME_DIR (Gemini Recommendation)

Gemini strongly recommended abandoning `/tmp/` entirely in favor of user-isolated directories:

1. **`XDG_RUNTIME_DIR`** (usually `/run/user/<uid>`, 0700, user-isolated):
   - Best for ephemeral state that should not survive reboots
   - Automatically per-user, no UID hashing needed
   - Not available on all systems (macOS, minimal Docker images)

2. **`~/.cache/claude-memory/staging-<hash>`**:
   - Works everywhere, inherently per-user
   - Survives reboots (acceptable for staging data)
   - No /tmp squatting concerns at all

3. **`tempfile.mkdtemp()`**:
   - Cryptographically random, no predictability
   - But: not deterministic, requires passing path in env/file

**Assessment**: The XDG approach is architecturally superior but represents a larger change. The UID-in-hash fix is a pragmatic incremental improvement. Both could be done: UID-in-hash as an immediate fix, XDG migration as a future enhancement.

---

## 4. Other Hardening Gaps Found

### 4.1 TOCTOU Race Between lstat and chmod (Low)

```python
st = os.lstat(staging_dir)       # <-- check
# ... validation checks ...
os.chmod(staging_dir, 0o700)     # <-- use (by pathname)
```

Between `lstat` and `chmod`, an attacker could theoretically:
1. Delete the validated directory (requires write on parent)
2. Replace it with a symlink to a target
3. `chmod` follows the symlink and changes permissions on the target

**Mitigation already in place**: The TOCTOU comment in the code correctly notes that `/tmp/` has a sticky bit, so only the owner can delete entries. For legacy paths, the parent is in the user's workspace.

**Ideal fix** (not urgent): Pin the directory with `os.open(staging_dir, O_DIRECTORY | O_NOFOLLOW)`, then use `os.fstat(fd)` and `os.fchmod(fd, 0o700)`. This eliminates the race entirely.

```python
# Ideal TOCTOU-resistant approach (future enhancement):
fd = os.open(staging_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    st = os.fstat(fd)
    if st.st_uid != os.geteuid():
        raise RuntimeError(...)
    if stat.S_IMODE(st.st_mode) & 0o077:
        os.fchmod(fd, 0o700)
finally:
    os.close(fd)
```

**Priority**: Low. The sticky bit on /tmp makes this practically unexploitable in the /tmp path. For legacy paths, the parent directory is user-owned.

### 4.2 Legacy Path Parent Directory Not Validated (Medium)

```python
parent = os.path.dirname(staging_dir)
if parent and not os.path.isdir(parent):  # os.path.isdir follows symlinks!
    os.makedirs(parent, mode=0o700, exist_ok=True)
```

- `os.path.isdir()` follows symlinks. If `.claude` is a symlink to an attacker-controlled dir, `isdir` returns True, and we skip `makedirs` -- then `os.mkdir` creates the staging dir inside the attacker's directory.
- Even if `makedirs` runs, it uses `exist_ok=True` without validating ownership of pre-existing ancestor directories.

**Fix**: Walk ancestors with `os.lstat()`, require directories owned by euid, reject symlinks:

```python
# Validate parent chain for legacy paths
def _validate_parent_chain(path: str) -> None:
    """Validate that all ancestor directories are owned by current user."""
    parts = []
    current = path
    while current != os.path.dirname(current):  # until root
        current = os.path.dirname(current)
        parts.append(current)

    for ancestor in reversed(parts):
        if not os.path.exists(ancestor):
            break  # Will be created by makedirs
        st = os.lstat(ancestor)
        if stat.S_ISLNK(st.st_mode):
            raise RuntimeError(f"Ancestor is a symlink: {ancestor}")
        if not stat.S_ISDIR(st.st_mode):
            raise RuntimeError(f"Ancestor is not a directory: {ancestor}")
        # Only check ownership for directories we expect to own
        # (skip system dirs like / and /home)
```

**Priority**: Medium. Legacy paths are in the user's project workspace, not /tmp, so the attack surface is smaller. But if the project is on a shared filesystem, this matters.

### 4.3 Fallback ensure_staging_dir in memory_triage.py (Medium)

`memory_triage.py:42-54` has a fallback `ensure_staging_dir` for when `memory_staging_utils` is not importable. This fallback:
- Has the **same bugs as the committed code** (no S_ISDIR check)
- Is a maintenance burden (changes to the main module must be replicated)

```python
# Fallback at memory_triage.py:42-54
def ensure_staging_dir(cwd: str = "") -> str:
    d = get_staging_dir(cwd)
    try:
        os.mkdir(d, 0o700)
    except FileExistsError:
        _st = os.lstat(d)
        if _stat.S_ISLNK(_st.st_mode):
            raise RuntimeError(f"Staging dir is a symlink: {d}")
        if _st.st_uid != os.geteuid():
            raise RuntimeError(f"Staging dir owned by uid {_st.st_uid}: {d}")
        if _stat.S_IMODE(_st.st_mode) & 0o077:
            os.chmod(d, 0o700)
    return d
```

**Fix**: Add S_ISDIR check to the fallback too, or document that the fallback is intentionally less strict (fail-open for partial deploys).

### 4.4 chmod on Non-Directory Types Before S_ISDIR Check (Cosmetic -- Fixed)

In the committed code, the order was: symlink check -> UID check -> chmod. If the path was a FIFO with bad perms, we'd chmod a FIFO. With the new `_validate_existing_staging()`, S_ISDIR is checked before chmod, so this is no longer possible.

---

## 5. Cross-Model Opinions

### Codex (OpenAI) -- Security Code Review

**Key findings**:
1. **High**: Shared predictable `/tmp/` name makes cross-user squatting trivial. The triage fallback at `memory_triage.py:1526` reuses the rejected path, defeating validation entirely.
2. **Medium**: Legacy path branch trusts parent directories without validating ownership or symlink status of ancestors.
3. **Medium**: TOCTOU between lstat and chmod -- recommends fd-pinning approach (`O_DIRECTORY | O_NOFOLLOW` + `fstat`/`fchmod`).
4. **Positive**: S_ISDIR fix already in working tree. The `_validate_existing_staging()` refactor is the right direction.

**Recommended approach**: Move to per-user namespace, remove `get_staging_dir()` fallback after validation failure, validate legacy ancestors, consider fd-pinning for race resistance.

### Gemini (Google) -- Architecture Review

**Key findings**:
1. **Critical (CWE-379)**: Predictable paths in `/tmp/` is an anti-pattern. Even with UID in hash, inputs are discoverable.
2. **High**: Recommends `XDG_RUNTIME_DIR` or `~/.cache/claude-memory/staging-<hash>` to eliminate the entire class of /tmp squatting bugs.
3. **Medium**: Correctly rejects `$USER`/`$LOGNAME` (forgeable env vars). `os.geteuid()` is better but still a band-aid.
4. **Low**: Docker and rootless containers have mount-namespace isolation, so /tmp collisions don't apply there.
5. **Low**: Orphaned dirs from hash change are harmless; OS cleans /tmp.

**Recommended approach**: Abandon `/tmp/` entirely. Use `XDG_RUNTIME_DIR` with `~/.cache` fallback.

### Consensus

Both models agree on:
- The triage fallback bug is the most urgent fix (using rejected path after validation failure)
- UID-in-hash is a pragmatic short-term fix but doesn't address the root cause
- The long-term solution is moving out of `/tmp/` entirely
- fd-pinning is ideal but low priority given sticky bit protection

---

## 6. Prioritized Fix List

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| P0 | Triage fallback uses rejected staging path (memory_triage.py:1526) | Small | Defeats entire validation |
| P1 | S_ISDIR check (already in working tree, needs commit + test update) | Done | Blocks FIFO/file/socket DoS |
| P1 | Update fallback ensure_staging_dir in memory_triage.py with S_ISDIR | Small | Parity with main module |
| P2 | UID-in-hash for get_staging_dir() | Small | Multi-user isolation |
| P2 | Update test for regular-file-at-path to assert RuntimeError | Small | Test correctness |
| P3 | Legacy path parent chain validation | Medium | Shared filesystem defense |
| P3 | FIFO/socket test coverage | Small | Regression prevention |
| P4 | fd-pinning for TOCTOU elimination | Medium | Theoretical race resistance |
| P5 | XDG_RUNTIME_DIR migration | Large | Eliminates /tmp class entirely |

---

## 7. Exact Fix Code

### P0: Triage Fallback Bug

```python
# memory_triage.py:1523-1527
# BEFORE:
try:
    _staging_dir = ensure_staging_dir(cwd)
except (OSError, RuntimeError):
    _staging_dir = get_staging_dir(cwd)

# AFTER:
try:
    _staging_dir = ensure_staging_dir(cwd)
except (OSError, RuntimeError):
    _staging_dir = ""  # Force inline triage data fallback
```

The downstream code already handles empty `_staging_dir` by falling back to inline `<triage_data>` JSON in the hook output.

### P1: Fallback ensure_staging_dir S_ISDIR

```python
# memory_triage.py:42-54, add S_ISDIR check after symlink check:
def ensure_staging_dir(cwd: str = "") -> str:
    d = get_staging_dir(cwd)
    try:
        os.mkdir(d, 0o700)
    except FileExistsError:
        _st = os.lstat(d)
        if _stat.S_ISLNK(_st.st_mode):
            raise RuntimeError(f"Staging dir is a symlink: {d}")
        if not _stat.S_ISDIR(_st.st_mode):
            raise RuntimeError(f"Staging path is not a directory: {d}")
        if _st.st_uid != os.geteuid():
            raise RuntimeError(f"Staging dir owned by uid {_st.st_uid}: {d}")
        if _stat.S_IMODE(_st.st_mode) & 0o077:
            os.chmod(d, 0o700)
    return d
```

### P2: UID-in-Hash

```python
# memory_staging_utils.py:get_staging_dir()
def get_staging_dir(cwd: str = "") -> str:
    if not cwd:
        cwd = os.getcwd()
    # Include euid for per-user isolation on shared systems.
    # Hash change from v5.1.0: old dirs (hash of path only) become orphaned
    # in /tmp/ and will be cleaned by OS. No migration needed.
    identity = f"{os.geteuid()}:{os.path.realpath(cwd)}"
    project_hash = hashlib.sha256(identity.encode()).hexdigest()[:12]
    return f"{STAGING_DIR_PREFIX}{project_hash}"
```

Must also update the fallback `get_staging_dir` in `memory_triage.py:37-41`:
```python
def get_staging_dir(cwd: str = "") -> str:
    if not cwd:
        cwd = os.getcwd()
    _identity = f"{os.geteuid()}:{os.path.realpath(cwd)}"
    _h = _hashlib.sha256(_identity.encode()).hexdigest()[:12]
    return f"/tmp/.claude-memory-staging-{_h}"
```

### P2: Test Update for S_ISDIR

```python
# test_memory_staging_utils.py -- replace test_regular_file_at_path_does_not_pass_silently
def test_regular_file_at_path_raises_not_directory(self, tmp_path):
    """Regular file at staging path should raise RuntimeError."""
    staging_path = f"{STAGING_DIR_PREFIX}test_regular_file"
    try:
        with open(staging_path, "w") as f:
            f.write("not a directory")
        os.chmod(staging_path, 0o700)

        with pytest.raises(RuntimeError, match="not a directory"):
            validate_staging_dir(staging_path)
    finally:
        if os.path.exists(staging_path):
            os.unlink(staging_path)
```
