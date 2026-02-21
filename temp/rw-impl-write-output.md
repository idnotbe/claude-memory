# impl-write: memory_write.py Part 1 Implementation Report

## Summary

All 4 changes to `hooks/scripts/memory_write.py` have been implemented successfully. All 659 tests pass (50 in test_arch_fixes.py, 609 in other test files).

## Changes Made

### 1A: `require_acquired()` method added
- Added to `FlockIndex` class after `__exit__`
- Raises `TimeoutError` with message `"LOCK_TIMEOUT_ERROR: Index lock not acquired. Another process may hold the lock. Retry later."`
- Only called by new callers needing strict enforcement (memory_enforce.py); existing 6 handlers unchanged

### 1B: Lock timeout increased
- Changed `_LOCK_TIMEOUT = 5.0` to `_LOCK_TIMEOUT = 15.0`
- Accommodates wider critical section in memory_enforce.py (scan + multiple retirements)

### 1C: `_flock_index` renamed to `FlockIndex`
- Class renamed with PEP 8 naming
- Docstring updated to mark as public API
- All 6 internal `with` references updated:
  - `do_create` (line ~706)
  - `do_update` (line ~862)
  - `do_retire` (line ~991)
  - `do_archive` (line ~1043)
  - `do_unarchive` (line ~1109)
  - `do_restore` (line ~1182)
- Tests updated: `test_arch_fixes.py` imports changed from `_flock_index` to `FlockIndex`

### 1D: `retire_record()` extracted
- New function: `retire_record(target_abs: Path, reason: str, memory_root: Path, index_path: Path) -> dict`
- Returns `{"status": "already_retired", "target": str}` if already retired (idempotent)
- Raises `RuntimeError` if archived
- Sets retirement fields: `record_status`, `retired_at`, `retired_reason`, `updated_at`
- Clears archived fields
- Appends change entry with CHANGES_CAP enforcement
- Computes `rel_path` via `memory_root.parent.parent` (NOT `Path.cwd()`)
- Calls `atomic_write_json` and `remove_from_index`
- Returns `{"status": "retired", "target": str, "reason": str}`
- `do_retire()` refactored to call `retire_record()` inside `FlockIndex` block
- Catches `json.JSONDecodeError`, `OSError`, and `RuntimeError` in `do_retire()`

## Verification Checklist

- [x] require_acquired() added with correct error message
- [x] _LOCK_TIMEOUT changed to 15.0
- [x] All _flock_index references renamed to FlockIndex (6 internal + class definition)
- [x] retire_record() extracted with correct signature
- [x] do_retire() refactored to call retire_record()
- [x] rel_path uses memory_root.parent.parent
- [x] py_compile passes
- [x] Existing tests pass (659/659)

## Test Results

```
tests/test_arch_fixes.py: 50 passed
tests/test_adversarial_descriptions.py: (all passed)
tests/test_memory_retrieve.py: (all passed)
tests/test_fts5_search_engine.py: (all passed)
tests/test_fts5_benchmark.py: (all passed)
tests/test_v2_adversarial_fts5.py: (all passed)
Total: 659 passed in 39.30s
```

## Files Modified

1. `hooks/scripts/memory_write.py` - All 4 changes (1A-1D)
2. `tests/test_arch_fixes.py` - Updated `_flock_index` imports to `FlockIndex` (7 occurrences)
