# V2 Independent Review: Rolling Window Enforcement

**Reviewer**: v2-independent (fresh eyes, no prior V1 review exposure)
**Date**: 2026-02-21
**Scope**: Full spec compliance, code quality, test coverage, "What NOT to Do" compliance

---

## Executive Summary

The implementation is **spec-compliant on all critical requirements**. All 24 tests pass. All 683 existing tests pass. No regressions. The code is clean, well-structured, and follows the spec closely. A few minor concerns and recommendations are noted below but nothing rises to NON-COMPLIANT.

---

## Step 1: Spec Compliance Audit

### Part 1: memory_write.py Changes

| Requirement | Status | Evidence |
|---|---|---|
| 1A. Fix lock timeout fallback (require_acquired) | **COMPLIANT** | `FlockIndex.require_acquired()` raises `TimeoutError` when `self.acquired is False` (line 1360-1373). Existing `__enter__` still returns self on timeout/OSError without raising -- backward compatible. |
| 1B. Increase lock timeout from 5.0 to 15.0 | **COMPLIANT** | `_LOCK_TIMEOUT = 15.0` at line 1304. Confirmed via grep. |
| 1C. Rename `_flock_index` to `FlockIndex` | **COMPLIANT** | Class renamed. All 6 internal references updated. Zero remaining `_flock_index` references (grep confirms). Docstring marks it as public API. |
| 1D. Extract `retire_record()` from `do_retire()` | **COMPLIANT** | Function extracted at line 893-957. `do_retire()` refactored to call it (line 960-989). Signature matches spec exactly: `retire_record(target_abs, reason, memory_root, index_path)`. |
| retire_record: read + mutate + write inside caller's lock | **COMPLIANT** | All operations (read line 909, mutate lines 923-944, write line 950, index removal line 951) are inside the function body. Caller holds the lock. TOCTOU gap eliminated. |
| retire_record: idempotent on already-retired | **COMPLIANT** | Returns `{"status": "already_retired", ...}` at line 914. |
| retire_record: archived raises RuntimeError | **COMPLIANT** | Raises `RuntimeError` at line 918-921. |
| retire_record: rel_path uses memory_root.parent.parent | **COMPLIANT** | Line 947: `project_root = memory_root.parent.parent`. Line 948: `rel_path = str(target_abs.relative_to(project_root))`. No CWD usage. |
| retire_record: no ValueError fallback | **COMPLIANT** | `relative_to()` call at line 948 is unguarded -- ValueError propagates. Docstring documents this at line 905. |
| retire_record: clears archived fields | **COMPLIANT** | Lines 930-931: `data.pop("archived_at", None)` and `data.pop("archived_reason", None)`. |
| retire_record: CHANGES_CAP enforcement | **COMPLIANT** | Lines 942-943: FIFO at CHANGES_CAP (50). |
| do_retire: catches RuntimeError from retire_record | **COMPLIANT** | Lines 981-986: explicit `except RuntimeError as e` handler. |

### Part 2: memory_enforce.py (New File)

| Requirement | Status | Evidence |
|---|---|---|
| Venv bootstrap before imports | **COMPLIANT** | Lines 14-22: identical pattern to memory_write.py. |
| sys.path.insert before memory_write import | **COMPLIANT** | Lines 25-27: `sys.path.insert(0, _script_dir)`. |
| Imports retire_record, FlockIndex, CATEGORY_FOLDERS | **COMPLIANT** | Lines 34-38. |
| MAX_RETIRE_ITERATIONS = 10 | **COMPLIANT** | Line 41. |
| DEFAULT_MAX_RETAINED = 5 | **COMPLIANT** | Line 42. |
| _resolve_memory_root: CLAUDE_PROJECT_ROOT -> CWD -> error | **COMPLIANT** | Lines 49-71: env var first, CWD walk second, sys.exit(1) on failure. |
| _read_max_retained: CLI override > config > default | **COMPLIANT** | Lines 78-92: cli_override short-circuits, then config lookup, then DEFAULT_MAX_RETAINED. |
| _scan_active: sorts by (created_at, filename) | **COMPLIANT** | Line 127: `results.sort(key=lambda s: (s["created_at"], s["path"].name))`. |
| _scan_active: treats absent record_status as active | **COMPLIANT** | Line 117: `data.get("record_status", "active")` with default "active". |
| _scan_active: skips corrupted JSON | **COMPLIANT** | Lines 113-114: except catches JSONDecodeError/OSError, prints warning, continues. |
| _deletion_guard: advisory only | **COMPLIANT** | Lines 135-154: prints warning to stderr, does not block. |
| enforce_rolling_window: dry-run mode | **COMPLIANT** | Lines 192-214: no lock acquired, no files modified, returns `"dry_run": True`. |
| enforce_rolling_window: real mode acquires lock + require_acquired | **COMPLIANT** | Lines 217-218: `with FlockIndex(index_path) as lock: lock.require_acquired()`. |
| enforce_rolling_window: calls retire_record (NOT do_retire) | **COMPLIANT** | Line 232: `result = retire_record(...)`. No do_retire reference in file. |
| enforce_rolling_window: FileNotFoundError -> continue | **COMPLIANT** | Lines 245-251: catches FileNotFoundError, prints warning, continues. |
| enforce_rolling_window: other Exception -> break | **COMPLIANT** | Lines 252-258: catches Exception, prints warning, breaks loop. |
| enforce_rolling_window: MAX_RETIRE_ITERATIONS safety valve | **COMPLIANT** | Line 226: `excess = min(excess, MAX_RETIRE_ITERATIONS)`. Also at line 199 for dry-run. |
| CLI: --category required, choices from CATEGORY_FOLDERS | **COMPLIANT** | Lines 275-279. |
| CLI: --max-retained type=int, default=None | **COMPLIANT** | Lines 281-285. |
| CLI: --dry-run store_true | **COMPLIANT** | Lines 287-290. |
| CLI: rejects --max-retained < 1 | **COMPLIANT** | Lines 295-297: `if args.max_retained is not None and args.max_retained < 1`. |
| CLI: catches TimeoutError -> exit 1 | **COMPLIANT** | Lines 302-306. |
| CLI: outputs JSON to stdout | **COMPLIANT** | Line 308: `print(json.dumps(result))`. |

### Part 3: SKILL.md Updates

| Requirement | Status | Evidence |
|---|---|---|
| Phase 3: references memory_enforce.py | **COMPLIANT** | SKILL.md lines 192-196: `python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_enforce.py" --category session_summary`. |
| Rolling window "How It Works" step 4 updated | **COMPLIANT** | SKILL.md line 276: "Handled automatically by `memory_enforce.py`". |

### Part 4: CLAUDE.md Updates

| Requirement | Status | Evidence |
|---|---|---|
| Key Files table includes memory_enforce.py | **COMPLIANT** | CLAUDE.md line 47: `hooks/scripts/memory_enforce.py | Rolling window enforcement: scans category, retires oldest beyond limit | pydantic v2 (via memory_write imports)`. |
| Quick Smoke Check includes memory_enforce.py | **COMPLIANT** | CLAUDE.md line 133: `python3 -m py_compile hooks/scripts/memory_enforce.py`. |

---

## Step 2: Code Quality Review

### memory_enforce.py

**Structure**: Well-organized with clear section headers (root derivation, config reading, scanning, deletion guard, enforcement logic, CLI). Each function has a focused responsibility.

**Docstrings**: All public functions have clear docstrings documenting args, return values, and behavior.

**Error handling**: Comprehensive. Corrupted files skipped, FileNotFoundError caught and continued, structural errors break loop, TimeoutError propagated to CLI.

**Code smells**: None detected. The code is straightforward and does not over-engineer.

### memory_write.py retire_record()

**Structure**: Clean extraction from do_retire(). The function does exactly what the docstring says -- read, mutate, write, index update. No lock acquisition.

**Docstring**: Excellent -- documents return types, exceptions, and usage notes.

**Error handling**: Deliberately minimal -- errors propagate to caller. This is correct since the caller (enforce_rolling_window) has its own error handling.

### FlockIndex

**Backward compatibility**: `__enter__` behavior preserved exactly. Only addition is `require_acquired()`. Existing callers are unchanged.

**CONCERN**: The `acquired` attribute is initialized to `False` in `__init__` (line 1310), set to `True` on successful mkdir (line 1317), and checked in `require_acquired()` (line 1369). The attribute is also correctly checked in `__exit__` (line 1354). This is clean.

---

## Step 3: Verification Checklist (from spec)

| Check | Result |
|---|---|
| `python3 memory_enforce.py --category session_summary` runs without error | **PASS** -- tested via pytest subprocess tests (14, 15) |
| `python3 memory_enforce.py --category session_summary --dry-run` outputs JSON to stdout | **PASS** -- test_10 verifies dry_run key in output |
| `FlockIndex.require_acquired()` raises TimeoutError when lock not held | **PASS** -- test_16, test_13 |
| `FlockIndex` used consistently (no remaining `_flock_index`) | **PASS** -- grep returns 0 matches; test_24 verifies |
| `retire_record()` importable from memory_write | **PASS** -- verified via `python3 -c "from memory_write import retire_record"` |
| memory_enforce.py has venv bootstrap AND sys.path.insert | **PASS** -- lines 14-27 |
| SKILL.md references memory_enforce.py for rolling window | **PASS** -- line 193 |
| ALL existing tests pass | **PASS** -- 683/683 pass |
| rel_path in retire_record() uses memory_root.parent.parent | **PASS** -- line 947 |
| --max-retained 0 and -1 rejected | **PASS** -- tests 14, 15 |
| No ValueError fallback in rel_path computation | **PASS** -- line 948, no try/except |

**All 11 checks PASS.**

---

## Step 4: Test Execution Results

```
tests/test_rolling_window.py: 24/24 passed (1.50s)
tests/ (full suite):          683/683 passed (39.77s)
py_compile memory_write.py:   OK
py_compile memory_enforce.py: OK
grep _flock_index:            0 matches
```

---

## Step 5: "What NOT to Do" Compliance

| Rule | Status | Evidence |
|---|---|---|
| 1. hooks.json NOT modified | **COMPLIANT** | `git diff hooks/hooks.json` is empty |
| 2. No --root CLI argument on memory_enforce.py | **COMPLIANT** | argparse has only --category, --max-retained, --dry-run |
| 3. No Path.cwd() in retire_record() rel_path | **COMPLIANT** | Line 947 uses `memory_root.parent.parent`. The only `Path.cwd()` in memory_enforce.py is in `_resolve_memory_root()` for root discovery, which is spec-permitted. |
| 4. memory_enforce.py does NOT call do_retire() | **COMPLIANT** | grep for `do_retire` in memory_enforce.py returns 0 matches |
| 5. No new dependencies | **COMPLIANT** | Only stdlib + memory_write imports |
| 6. memory-config.default.json NOT changed | **COMPLIANT** | `git diff assets/memory-config.default.json` is empty |
| 7. Existing 6 handlers NOT changed beyond FlockIndex rename | **COMPLIANT** | Diff shows only `_flock_index(` -> `FlockIndex(` in do_create, do_update, do_archive, do_unarchive, do_restore. do_retire was intentionally refactored per spec. |
| 8. No --max-retained 0 or negative accepted | **COMPLIANT** | CLI validation at lines 295-297 |

**All 8 rules COMPLIANT.**

---

## Additional Observations

### CONCERN: Non-spec changes bundled in the diff

The `git diff` for `memory_write.py` includes changes that are NOT part of the rolling window spec:

1. **S5F confidence label spoofing defense** (title sanitization): Lines adding `re.sub(r'\[\s*confidence\s*:[^\]]*\]', ...)` in `auto_fix()` for both titles and tags.
2. **S5F combining mark stripping**: `unicodedata.category(c) not in ('Cf', 'Mn')` replacing just `'Cf'`.
3. **S5F `_check_dir_components()` function**: New directory name validation.
4. **S5F `_SAFE_DIR_RE` regex**: New constant for path component validation.

These appear to be from a separate S5F security hardening effort that was already in the working tree. They are not related to rolling window enforcement but are bundled in the same uncommitted diff. This is **not a defect** in the rolling window implementation -- it's a staging concern. The rolling window changes themselves are isolated and correct.

**Rating**: CONCERN (minor) -- recommend committing S5F changes separately from rolling window changes for clean git history.

### RECOMMENDATION: Test coverage for _read_max_retained edge cases

The `_read_max_retained` function silently falls back to `DEFAULT_MAX_RETAINED` if config parsing fails (JSONDecodeError, OSError). Test 06 covers the happy path (config exists, returns value). Consider adding:
- Config file with invalid JSON -> falls back to 5
- Config file missing the nested key path -> falls back to 5
- Config file with non-integer max_retained value -> returns whatever json.load returns (could be a float or string -- potential type issue at the enforce_rolling_window call site since it's used in `len(active) - max_retained`)

**Rating**: RECOMMENDATION (minor) -- not a bug, just a test coverage gap.

### RECOMMENDATION: Type safety in _read_max_retained

If `memory-config.json` contains `"max_retained": "five"` (a string), `_read_max_retained` returns the string directly. This would then hit `len(active) - max_retained` in `enforce_rolling_window`, causing a TypeError. The CLI path is safe (argparse enforces `type=int`), but the config-file path has no type validation.

**Rating**: RECOMMENDATION (minor) -- would only matter with a corrupted/malicious config file. The function matches the spec exactly.

---

## Overall Assessment

**PASS** -- Implementation is spec-compliant across all requirements, passes all verification checks, follows all "What NOT to Do" rules, and maintains full backward compatibility with existing tests. Code quality is high.

| Area | Rating |
|---|---|
| Spec compliance | 11/11 checklist items PASS |
| "What NOT to Do" compliance | 8/8 rules COMPLIANT |
| Test coverage | 24/24 spec tests pass, 683/683 full suite |
| Code quality | Clean, well-structured, well-documented |
| Backward compatibility | Preserved (existing lock timeout and permission denied behavior unchanged) |
| Security | No new attack vectors introduced |
