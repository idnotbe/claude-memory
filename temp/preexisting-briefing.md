# Pre-existing Security Bugs — Implementation Briefing

## Bug 1: Staging Dir Symlink Hijack (memory_staging_utils.py)

**Location**: `hooks/scripts/memory_staging_utils.py`, `validate_staging_dir()` lines 91-92

**Current code** (legacy path branch):
```python
else:
    os.makedirs(staging_dir, mode=0o700, exist_ok=True)  # VULNERABLE
```

The /tmp/ path branch (lines 75-90) has proper defense:
- `os.mkdir()` atomic create (not makedirs)
- `os.lstat()` symlink check on FileExistsError
- Permission fix if world-readable

But the legacy path branch has NO defense: follows symlinks, doesn't check ownership, doesn't fix permissions.

**Fix**: Apply the same security checks to the legacy path branch:
1. `os.lstat()` to check for symlink
2. `st.st_uid != os.geteuid()` ownership check
3. Permission fix if `st.st_mode & 0o077`
4. Use `os.mkdir()` with `os.makedirs()` only for parent dirs

**Note**: Legacy path needs `os.makedirs()` for parents (`.claude/memory/` may not exist), but should use `os.mkdir()` for the final `.staging` component.

## Bug 2: Legacy Path Validation Too Permissive (memory_write.py)

**Location**: `hooks/scripts/memory_write.py`, 5 occurrences

**Current pattern**:
```python
is_legacy_staging = (len(parts) >= 2 and parts[-1] == ".staging" and parts[-2] == "memory")
```

Accepts any path like `/tmp/evil/memory/.staging` or `/etc/memory/.staging`.

**Affected functions** (exact lines may vary after recent edits, grep for `is_legacy_staging`):
1. `cleanup_staging()`
2. `cleanup_intents()`
3. `write_save_result()`
4. `update_sentinel_state()`
5. `_read_input()`

**Fix**: Create `_is_valid_legacy_staging()` helper that requires `.claude/memory/.staging` pattern (not just `memory/.staging`):
```python
def _is_valid_legacy_staging(resolved_path: str) -> bool:
    """Check if path is a valid legacy staging directory (.claude/memory/.staging)."""
    # Require .claude as an ancestor directory component
    parts = Path(resolved_path).parts
    try:
        claude_idx = parts.index(".claude")
        return (
            claude_idx + 2 < len(parts)
            and parts[claude_idx + 1] == "memory"
            and parts[claude_idx + 2] == ".staging"
        )
    except ValueError:
        return False
```

Replace all 5 occurrences with calls to this helper.

**Also check** `_read_input()` which has a different pattern: `"/.claude/memory/.staging/" in resolved`.
