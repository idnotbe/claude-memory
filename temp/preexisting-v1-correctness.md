# Correctness Review: Staging Dir Symlink + Validation Fixes

**Reviewer:** Opus 4.6 (correctness focus)
**Cross-check:** Gemini 3.1 Pro (clink code review)
**Date:** 2026-03-22

## Verdict: PASS (with 1 medium finding)

Both fixes are correct, well-tested, and backward-compatible. One medium-severity issue found in error handling.

---

## Bug 1: Symlink/Permission Bypass Fix (`memory_staging_utils.py`)

### `_validate_existing_staging()` shared helper

| Check | Result |
|-------|--------|
| Works for /tmp/ paths | PASS -- identical validation logic, both branches call via FileExistsError handler |
| Works for legacy paths | PASS -- same function, same checks |
| Symlink detection via `os.lstat()` | PASS -- lstat does not follow symlinks |
| `S_ISDIR` check for non-directory | PASS -- catches regular files, FIFOs, sockets, char devices |
| Ownership check `st_uid != geteuid()` | PASS -- correctly rejects foreign-owned dirs |
| Permission tightening `chmod(0o700)` | PASS -- only triggers when group/other bits set |

### Legacy path branch in `validate_staging_dir()`

| Check | Result |
|-------|--------|
| `os.makedirs(parent)` for parent dirs | PASS -- creates `.claude/memory/` if missing |
| `os.mkdir(staging_dir)` for final component | PASS -- atomic create, fails if exists |
| FileExistsError -> shared validation | PASS -- same defense as /tmp/ branch |
| Parent is empty string (relative path) | SAFE -- `if parent` guard skips makedirs |
| Parent is "/" (root-level staging) | SAFE -- "/" is already a dir, makedirs skipped |
| `.claude/memory/` exists but `.staging` doesn't | PASS -- isdir(parent) is True, skip makedirs, mkdir creates .staging |
| Path is a regular file (not dir) | PASS -- mkdir raises FileExistsError, S_ISDIR rejects it |

### TOCTOU Analysis (lstat -> chmod window)

- **/tmp/ paths:** Sticky bit prevents non-owner deletion/replacement. Unexploitable.
- **Legacy paths:** Attacker needs write access to `.claude/memory/` parent dir. If they have that, they already have workspace write access. The chmod only tightens to `0o700` (more restrictive), so even if a symlink target got chmod'd, it would become MORE restrictive, not less. **Severity: Low (not practically exploitable).**
- **Gemini suggested `os.open(O_NOFOLLOW|O_DIRECTORY)` + `os.fchmod()`:** This is a theoretically stronger defense but adds complexity for a non-exploitable window. Acceptable as future hardening, not a correctness issue.

### Multi-User Hash Collision (Gemini Finding)

Gemini flagged that two users on the same machine with the same project path get the same staging dir hash. This is a **pre-existing design issue**, not introduced by the fix. The staging dir path generation is unchanged. **Out of scope for this review.**

---

## Bug 2: Legacy Staging Path Validation Fix (`memory_write.py`)

### `_is_valid_legacy_staging()` correctness

| Input | Expected | Actual | Status |
|-------|----------|--------|--------|
| `/home/user/.claude/memory/.staging` | True | True | PASS |
| `/tmp/evil/memory/.staging` | False | False | PASS |
| `/etc/memory/.staging` | False | False | PASS |
| `/home/.claude/memory/.staging` (root-adjacent) | True | True | PASS |
| `/.claude/memory/.staging` (root-level) | True | True | PASS |
| `/home/user/claude/memory/.staging` (no dot) | False | False | PASS |
| `/home/user/.claude/.staging` (no memory) | False | False | PASS |
| `/home/user/memory/.claude/.staging` (wrong order) | False | False | PASS |
| Empty string | False | False | PASS |
| Relative `.claude/memory/.staging` | True | True | SAFE (callers resolve first) |
| Windows `C:\Users\.claude\memory\.staging` | False | False | PASS (Linux-only plugin) |
| Very long path (500+ chars) | True | True | PASS (no length limits needed) |
| Unicode path components | True | True | PASS |
| Trailing slash `/.../.staging/` | True | True | PASS (Path normalizes) |
| Double slashes `//.claude/...` | True | True | PASS (Path normalizes) |

### Early-Return on First Match (Gemini Finding #4)

Gemini flagged the early return as a bug, recommending `continue` instead of `return`. **This recommendation is INCORRECT.** The early return is a deliberate security feature:

- Path `/foo/.claude/memory/.staging/evil/.claude/memory/.staging` -- the early return correctly rejects this because the FIRST match is non-terminal, meaning the path traverses through a staging dir.
- No legitimate path has nested `.claude/memory/.staging` sequences.
- Changing to `continue` would weaken security by allowing paths that traverse through staging dirs.

**Verdict: Current behavior is correct.**

### `allow_child=True` mode

- Returns True on first `.claude/memory/.staging` match regardless of terminal position.
- Called only from `_read_input()` which uses `os.path.realpath()` to resolve paths first.
- Safe because the first match establishes valid `.claude/memory/.staging` ancestry.

### Cross-project bypass

`/tmp/.claude/memory/.staging` passes validation (attacker could craft this structure). Accepted risk per implementation log: (a) old check was even more permissive, (b) staging dirs are plugin-controlled, (c) `.claude/memory/.staging` is structurally difficult to plant.

---

## Backward Compatibility

| Concern | Status |
|---------|--------|
| Legitimate legacy staging paths still work | PASS -- `.claude/memory/.staging` is accepted |
| `/tmp/` staging paths still work | PASS -- separate `startswith()` check, unchanged |
| TestCleanupIntents fixture updated | PASS -- uses `.claude/memory/.staging` (matches stricter validation) |
| `_make_staging()` helper uses correct path | PASS -- both `new` and `legacy` prefixes create `.claude/memory/.staging` |
| All 1217+ tests pass | PASS |

---

## FINDING: Uncaught RuntimeError in write_save_result()

**Severity: Medium (correctness)**
**Location:** `hooks/scripts/memory_write.py`, lines 712-717

```python
try:
    from memory_staging_utils import validate_staging_dir
    validate_staging_dir(str(staging_path))
except ImportError:
    os.makedirs(str(staging_path), exist_ok=True)
```

`RuntimeError` from `validate_staging_dir()` (symlink detected, foreign owner, non-directory) propagates uncaught, causing a hard crash with a stack trace instead of the expected `{"status": "error", ...}` JSON response. This breaks the function's API contract.

**Same pattern exists in `memory_draft.py`:** `_ensure_staging_dir_safe()` wraps `validate_staging_dir()` without catching RuntimeError. The CLI entry point would crash with a traceback.

**Fix:** Add `RuntimeError` to the except clause:
```python
except (ImportError, RuntimeError) as e:
    if isinstance(e, ImportError):
        os.makedirs(str(staging_path), exist_ok=True)
    else:
        return {"status": "error", "message": str(e)}
```

**Impact:** This is an edge case (only triggers during active attacks or OS-level anomalies) but violates the JSON API contract that callers depend on.

---

## Summary

| Category | Finding | Severity |
|----------|---------|----------|
| Correctness | Uncaught RuntimeError in `write_save_result()` | Medium |
| Security | TOCTOU in chmod (legacy paths) | Low (unexploitable in practice) |
| Design | Multi-user hash collision | Informational (pre-existing, not a regression) |
| Maintainability | Redundant `os.path.isdir(parent)` check | Low |
| Correctness | Early-return in `_is_valid_legacy_staging()` | Non-issue (correct behavior) |
| Correctness | Relative path acceptance | Non-issue (callers always resolve) |

**Overall:** Both fixes are well-implemented. The symlink defense extraction into a shared helper eliminates code duplication and ensures consistent behavior. The legacy staging validation correctly tightens the path requirements from `memory/.staging` to `.claude/memory/.staging`. The one actionable finding (uncaught RuntimeError) should be addressed to maintain API contract integrity.
