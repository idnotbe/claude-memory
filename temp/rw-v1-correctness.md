# V1 Correctness Review: Rolling Window Implementation

**Reviewer:** v1-correctness
**Date:** 2026-02-21
**Verdict:** PASS (all checklist items verified)

---

## Methodology

1. Read the spec at `/home/idnotbe/projects/claude-code-guardian/temp/prompt-rolling-window-option1.md`
2. Read all 4 implementation files line-by-line
3. Cross-referenced every spec requirement against the implementation
4. Ran all 24 tests (all pass in 1.06s)
5. Ran existing backward-compat tests (`test_lock_timeout`, `test_permission_denied_handling`) -- both pass
6. Verified syntax with `py_compile` on both scripts
7. Searched for stale `_flock_index` references (none found)

---

## memory_write.py Checklist

### [PASS] `retire_record()` signature matches spec exactly

Spec signature:
```python
def retire_record(target_abs: Path, reason: str, memory_root: Path, index_path: Path) -> dict:
```

Implementation at line 893:
```python
def retire_record(target_abs: Path, reason: str, memory_root: Path, index_path: Path) -> dict:
```

Exact match. Docstring also matches spec (returns dict with `status`/`target`/`reason` keys, raises documented exceptions).

### [PASS] `retire_record()` rel_path uses `memory_root.parent.parent` (NOT CWD)

Line 947:
```python
project_root = memory_root.parent.parent  # .claude/memory -> .claude -> project root
rel_path = str(target_abs.relative_to(project_root))
```

Matches spec exactly. No CWD usage, no fallback -- `ValueError` propagates naturally.

### [PASS] `retire_record()` returns correct dict shapes for success/already_retired

Success (line 952-957):
```python
return {"status": "retired", "target": str(target_abs), "reason": data["retired_reason"]}
```

Already retired (line 914):
```python
return {"status": "already_retired", "target": str(target_abs)}
```

Both match spec. Note: spec shows `"target": str` -- implementation uses `str(target_abs)` which is correct since the function receives an absolute path.

### [PASS] `retire_record()` raises RuntimeError for archived

Lines 917-920:
```python
if data.get("record_status") == "archived":
    raise RuntimeError(
        "Archived memories must be unarchived before retiring. "
        "Use --action unarchive first."
    )
```

Matches spec: "RuntimeError: if target is archived (must unarchive first)".

### [PASS] `retire_record()` lets ValueError propagate from relative_to()

Line 948:
```python
rel_path = str(target_abs.relative_to(project_root))
```

No try/except around this. If `target_abs` is not under `project_root`, `relative_to()` raises `ValueError` which propagates to the caller. This matches the spec directive: "Do NOT use a fallback (it would produce a wrong path)."

### [PASS] `do_retire()` properly delegates to retire_record() inside FlockIndex

Lines 975-986:
```python
with FlockIndex(index_path):
    try:
        result = retire_record(target_abs, reason, memory_root, index_path)
    except (json.JSONDecodeError, OSError) as e:
        ...
    except RuntimeError as e:
        ...
```

Lock acquired, then `retire_record()` called inside the lock scope. Correct delegation.

### [PASS] `do_retire()` catches RuntimeError with proper error message

Lines 981-986:
```python
except RuntimeError as e:
    print(
        f"RETIRE_ERROR\ntarget: {args.target}\n"
        f"fix: {e}"
    )
    return 1
```

Matches spec's `do_retire()` refactoring. Note: the spec example didn't show `RuntimeError` catching explicitly in `do_retire()`, but the implementer correctly added it since `retire_record()` can raise `RuntimeError` for archived files. This is a sensible addition not in the spec but necessary for correctness.

### [PASS] `FlockIndex` rename is complete (no `_flock_index` remains)

Verified by `grep -n "_flock_index" hooks/scripts/memory_write.py` -- 0 results. The class is defined as `FlockIndex` at line 1298 with the correct docstring marking it as public API.

### [PASS] `require_acquired()` raises TimeoutError with correct message

Lines 1360-1373:
```python
def require_acquired(self) -> None:
    if not self.acquired:
        raise TimeoutError(
            "LOCK_TIMEOUT_ERROR: Index lock not acquired. "
            "Another process may hold the lock. Retry later."
        )
```

Message matches spec exactly.

### [PASS] `_LOCK_TIMEOUT` is 15.0

Line 1304:
```python
_LOCK_TIMEOUT = 15.0   # Max seconds to wait for lock
```

Changed from 5.0 to 15.0 as required by spec.

### [PASS] All 6 handlers use FlockIndex (not _flock_index)

Verified by test 24 (source code analysis) and manual grep:
- `do_create` line 692: `with FlockIndex(index_path):`
- `do_update` line 848: `with FlockIndex(index_path):`
- `do_retire` line 975: `with FlockIndex(index_path):`
- `do_archive` line 1053: `with FlockIndex(index_path):`
- `do_unarchive` line 1119: `with FlockIndex(index_path):`
- `do_restore` line 1192: `with FlockIndex(index_path):`

All 6 use `FlockIndex`.

### [PASS] No backward-compat breaks in existing handlers

Both `test_lock_timeout` and `test_permission_denied_handling` from `test_arch_fixes.py` still pass. The `__enter__` method still returns `self` with `acquired=False` on timeout/OSError. No existing handler calls `require_acquired()`.

---

## memory_enforce.py Checklist

### [PASS] Correct imports from memory_write

Lines 34-38:
```python
from memory_write import (
    retire_record,
    FlockIndex,
    CATEGORY_FOLDERS,
)
```

Matches spec exactly (retire_record, FlockIndex, CATEGORY_FOLDERS).

### [PASS] Venv bootstrap before imports

Lines 14-22: Venv bootstrap block comes before any imports from `memory_write`. Uses the same `os.execv` pattern as `memory_write.py`.

### [PASS] sys.path.insert before memory_write import

Lines 25-27:
```python
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)
```

Correctly placed between venv bootstrap and the `from memory_write import` statement. Matches the `memory_draft.py` pattern referenced in spec.

### [PASS] _resolve_memory_root() checks $CLAUDE_PROJECT_ROOT then CWD walk-up

Lines 49-71: Strategy exactly matches spec:
1. Check `$CLAUDE_PROJECT_ROOT` env var -> `<root>/.claude/memory`
2. Walk CWD upward with `[cwd] + list(cwd.parents)`
3. `sys.exit(1)` with error message if not found

### [PASS] _read_max_retained() reads from config with CLI override

Lines 78-92:
- CLI override takes priority (line 80-81)
- Config path: `memory_root / "memory-config.json"` (line 83)
- Config key: `categories.<category>.max_retained` (line 88)
- Fallback: `DEFAULT_MAX_RETAINED = 5` (line 92)
- Exception handling: `(json.JSONDecodeError, OSError)` caught silently (line 89)

Matches spec exactly.

### [PASS] _scan_active() returns sorted by (created_at, path.name)

Line 127:
```python
results.sort(key=lambda s: (s["created_at"], s["path"].name))
```

Matches spec. Uses `path.name` (filename) as tiebreaker, not the full path.

### [PASS] enforce_rolling_window() uses FlockIndex + require_acquired()

Lines 217-218:
```python
with FlockIndex(index_path) as lock:
    lock.require_acquired()
```

Strict lock enforcement as specified.

### [PASS] Dry-run does NOT acquire lock

Lines 192-214: The `if dry_run:` branch computes excess and returns without entering any `FlockIndex` context manager. No lock acquisition.

### [PASS] MAX_RETIRE_ITERATIONS applied as safety valve

Line 41: `MAX_RETIRE_ITERATIONS = 10`
Lines 199 and 226: `excess = min(excess, MAX_RETIRE_ITERATIONS)`

Applied in both dry-run and real enforcement paths.

### [PASS] FileNotFoundError caught with continue

Lines 245-251:
```python
except FileNotFoundError as e:
    print(f"[WARN] File gone before retire {victim['id']}: {e}. Continuing.", file=sys.stderr)
    continue
```

### [PASS] General Exception caught with break

Lines 252-258:
```python
except Exception as e:
    print(f"[WARN] Failed to retire {victim['id']}: {e}. Stopping enforcement loop.", file=sys.stderr)
    break
```

### [PASS] --max-retained < 1 rejected

Lines 294-296:
```python
if args.max_retained is not None and args.max_retained < 1:
    print("ERROR: --max-retained must be >= 1", file=sys.stderr)
    sys.exit(1)
```

Validated by tests 14 and 15 (subprocess tests confirm exit code and message).

### [PASS] TimeoutError caught in main() -> sys.exit(1)

Lines 302-306:
```python
try:
    result = enforce_rolling_window(...)
except TimeoutError as e:
    print(str(e), file=sys.stderr)
    sys.exit(1)
```

---

## Tests Checklist

### [PASS] All 24 test cases present and meaningful

Tests 1-15 cover `memory_enforce.py`, tests 16-24 cover `memory_write.py` changes. All 24 pass.

### [PASS] Tests actually verify behavior (not just "no crash")

Every test makes concrete assertions:
- Test 01: Asserts 1 retirement, specific ID `session-000`, active_count=5
- Test 03: Asserts exact IDs `[session-000, session-001, session-002]`
- Test 04: Verifies ordering tiebreaker (aaa-session before zzz-session at same timestamp)
- Test 08: Verifies partial results after mock failure (1 retired, not 3)
- Test 09: Verifies `continue` behavior (file disappears, next one succeeds)
- Test 10: Verifies `dry_run: True` key AND that no files were modified
- Test 20: Verifies all retirement fields (`record_status`, `retired_at`, `retired_reason`, `updated_at`, changes entry with field/old_value/new_value), AND absence of archived fields
- Test 21: Verifies relative path computation AND actual index removal

### [PASS] Edge cases covered (corrupted JSON, file disappears, lock timeout)

- Test 07: Corrupted JSON file
- Test 08: Structural error (RuntimeError) breaks loop
- Test 09: FileNotFoundError continues
- Test 11: Empty/missing directory
- Test 12: Root discovery (env var, CWD fallback, error)
- Test 13: Lock timeout -> TimeoutError
- Test 14-15: Invalid CLI inputs
- Test 16: Lock not acquired -> require_acquired() raises
- Test 18-19: Backward-compat (timeout and permission denied)
- Test 22: Already-retired file (idempotent)
- Test 23: Archived file (RuntimeError)

---

## Issues Found

### No Issues

The implementation matches the spec on every checklist item. No deviations, no missing error handling, no backward-compatibility breaks.

### Observations (not issues)

1. **`do_retire()` catches `RuntimeError`** -- The spec's example code for the refactored `do_retire()` only showed `except (json.JSONDecodeError, OSError)`, but the implementation also catches `RuntimeError` (for archived files). This is correct and necessary since `retire_record()` can raise `RuntimeError`.

2. **Dry-run `active_count` computation** -- In dry-run mode, `active_count` is computed as `len(active) - len(retired_list)`. This is a projection (since no actual retirement happens), which is the correct behavior for a dry run.

3. **`_scan_active()` does sorted glob first then re-sorts** -- Line 109 does `sorted(category_dir.glob("*.json"))` (for deterministic iteration), then line 127 re-sorts by `(created_at, path.name)`. The first sort is for filesystem determinism; the second is for semantic ordering. This is correct.

---

## Summary

| Area | Items | Pass | Fail |
|------|-------|------|------|
| memory_write.py | 12 | 12 | 0 |
| memory_enforce.py | 12 | 12 | 0 |
| Tests | 3 | 3 | 0 |
| **Total** | **27** | **27** | **0** |

**Overall verdict: PASS** -- Implementation is correct and complete per spec.
