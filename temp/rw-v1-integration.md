# V1 Integration Review: Rolling Window Enforcement

**Reviewer**: v1-integration
**Date**: 2026-02-21
**Verdict**: PASS (with one documentation gap noted)

---

## Files Reviewed

| File | Status | Verdict |
|------|--------|---------|
| `hooks/scripts/memory_write.py` | Modified | PASS |
| `hooks/scripts/memory_enforce.py` | New | PASS |
| `skills/memory-management/SKILL.md` | Modified | PASS |
| `tests/test_rolling_window.py` | New | PASS |
| `hooks/hooks.json` | Verified unmodified | PASS |
| `tests/conftest.py` | Uses existing fixtures | PASS |
| `tests/test_arch_fixes.py` | Still passes | PASS |
| `CLAUDE.md` | Needs update | ADVISORY |

---

## Integration Review Checklist

### Backward Compatibility

- [x] **hooks.json is unmodified** -- `git diff hooks/hooks.json` shows no changes. PASS
- [x] **All existing tests pass (683 tests)** -- `pytest tests/ -v --tb=short` => `683 passed in 35.64s`. PASS
- [x] **test_arch_fixes.py tests still import FlockIndex correctly** -- All 13 imports in test_arch_fixes.py use `from memory_write import FlockIndex` (lines 506, 529, 540, 560, 585, 607, 623). The only `_flock_index` reference is in a docstring comment (line 500), not executable code. PASS
- [x] **Other scripts that import from memory_write.py still work** -- Verified:
  - `memory_draft.py`: imports `slugify, now_utc, build_memory_model, CONTENT_MODELS, CATEGORY_FOLDERS, ChangeEntry, ValidationError` -- loads successfully
  - `memory_validate_hook.py`: imports `validate_memory` lazily -- module loads successfully
  - `memory_enforce.py`: imports `retire_record, FlockIndex, CATEGORY_FOLDERS` -- loads successfully
  PASS
- [x] **SKILL.md changes don't break Phase 3 flow** -- Phase 3 save flow (lines 174-196) is preserved. The rolling window instruction (line 190-196) now references `memory_enforce.py` instead of inline Python. The rest of Phase 3 is untouched. PASS

### Import Chain

- [x] **memory_enforce.py can import FlockIndex, retire_record, CATEGORY_FOLDERS from memory_write** -- Verified with direct Python import test. PASS
- [x] **Venv bootstrap in memory_enforce.py matches the pattern in memory_write.py** -- Lines 15-22 of memory_enforce.py use the identical pattern: `_venv_python` resolved relative to script dir `../../.venv/bin/python3`, checks `os.path.isfile` and `os.path.realpath` match, tries `import pydantic`, falls back to `os.execv`. Matches memory_write.py lines 28-35 exactly. PASS
- [x] **sys.path setup is correct** -- Lines 25-27: `_script_dir = os.path.dirname(os.path.abspath(__file__))`, inserts at position 0 if not already present. This matches the pattern used by `memory_draft.py` (lines 41-43). PASS
- [x] **No circular imports** -- memory_enforce.py imports from memory_write.py (one-way). memory_write.py does not import from memory_enforce.py. No cycles. PASS

### Config Compatibility

- [x] **memory-config.json format unchanged** -- memory_enforce.py reads `categories.<name>.max_retained` using the same JSON path as the existing config format. No new config keys introduced. PASS
- [x] **max_retained field already exists in default config** -- `assets/memory-config.default.json` line 10: `"max_retained": 5` under `session_summary`. PASS
- [x] **Config reading in memory_enforce.py matches existing patterns** -- `_read_max_retained()` (lines 78-92) reads config with `json.load()`, catches `JSONDecodeError` and `OSError`, falls back to default. Matches the defensive pattern used in other scripts. PASS

### CLAUDE.md Updates Needed

- [ ] **Key Files table should include memory_enforce.py** -- ADVISORY: The Key Files table in CLAUDE.md (lines 37-47) does not list `memory_enforce.py`. It should be added:
  ```
  | hooks/scripts/memory_enforce.py | Rolling window enforcement for categories | pydantic v2 (via memory_write imports) |
  ```
  This is a documentation gap, not a functional issue. The script works correctly without this entry.
- [ ] **Architecture section should mention the new script** -- ADVISORY: The Architecture section (lines 14-20) could mention that `memory_enforce.py` is called by the agent (not a hook) for rolling window enforcement. The Venv Bootstrap section (lines 55-57) should also note that `memory_enforce.py` uses the same venv bootstrap pattern.

### SKILL.md Consistency

- [x] **Phase 3 instructions correctly reference memory_enforce.py** -- Line 193: `python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_enforce.py" --category session_summary`. Uses `$CLAUDE_PLUGIN_ROOT` consistently with all other script invocations. PASS
- [x] **Rolling window section updated correctly** -- Lines 267-296: "How It Works" section step 4 (line 276) now says "Handled automatically by `memory_enforce.py`". The detailed algorithm steps are removed (now internal to the script). Configuration and manual cleanup sections unchanged. PASS
- [x] **No orphaned references to old inline Python approach** -- Searched for `python3 -c` and `import json.*glob` patterns -- no orphaned inline Python. The only "inline" reference is the explanatory note on line 196: "This replaces the previous inline Python enforcement." PASS

### Test Integration

- [x] **conftest.py fixtures sufficient for new tests** -- test_rolling_window.py uses `make_session_memory`, `write_memory_file`, `build_enriched_index`, `write_index` from conftest.py. All exist and work correctly. The test also creates its own `_setup_enforce_project` helper for the project structure setup specific to enforcement tests. PASS
- [x] **New tests follow existing patterns** -- test_rolling_window.py follows the same patterns as test_arch_fixes.py:
  - SCRIPTS_DIR and sys.path setup at module level
  - Helper functions for project setup
  - Class-based test organization
  - subprocess runs for CLI validation
  - Direct imports for unit tests
  - `tmp_path` and `monkeypatch` fixtures
  PASS
- [x] **No test file conflicts** -- test_rolling_window.py is a new file. No naming conflicts with existing test files. PASS

---

## Detailed Findings

### 1. retire_record() extraction is correct

The `retire_record()` function (memory_write.py lines 893-957) correctly:
- Is a standalone function (not inside `do_retire()`)
- Does NOT acquire the lock (caller's responsibility)
- Computes `rel_path` relative to `memory_root.parent.parent` (line 947-948), not `Path.cwd()`
- Returns correct result dicts for both normal and idempotent cases
- Raises `RuntimeError` for archived files
- Handles `changes[]` with CHANGES_CAP enforcement

### 2. do_retire() correctly calls retire_record()

`do_retire()` (lines 960-989) now delegates to `retire_record()` inside a `FlockIndex` context, catching `json.JSONDecodeError`, `OSError`, and `RuntimeError`. The refactored code is cleaner and preserves backward compatibility.

### 3. FlockIndex rename is complete

No remaining `_flock_index` references in executable code:
- Class definition: `class FlockIndex` (line 1298)
- All 6 action handlers use `FlockIndex(index_path)`: `do_create` (692), `do_update` (848), `do_retire` (975), `do_archive` (1053), `do_unarchive` (1119), `do_restore` (1195)
- `require_acquired()` method added (lines 1360-1373)
- `_LOCK_TIMEOUT` increased from 5.0 to 15.0 (line 1304)

### 4. memory_enforce.py structure is sound

- Venv bootstrap before imports
- sys.path.insert before memory_write imports
- Clean separation: `_resolve_memory_root()`, `_read_max_retained()`, `_scan_active()`, `_deletion_guard()`, `enforce_rolling_window()`
- Safety valve: `MAX_RETIRE_ITERATIONS = 10`
- CLI validation: `--max-retained >= 1`
- Lock enforcement: `lock.require_acquired()` inside `enforce_rolling_window()`
- Error handling: `FileNotFoundError` -> continue, other exceptions -> break

### 5. Test coverage is comprehensive

24 tests covering all spec requirements:
- Tests 1-15: memory_enforce.py behavior (trigger, no-trigger, multiple retirements, ordering, config, corrupted files, error handling, dry-run, empty dir, root discovery, lock, CLI validation)
- Tests 16-24: memory_write.py changes (require_acquired, backward compat, retire_record behavior, relative paths, idempotency, archived check, rename verification)

---

## Recommendations

1. **ADVISORY -- Update CLAUDE.md**: Add `memory_enforce.py` to the Key Files table and mention it in the Venv Bootstrap section. This is documentation-only; functionality is not affected.

2. **ADVISORY -- Quick smoke check section**: Consider adding `python3 -m py_compile hooks/scripts/memory_enforce.py` to the Quick Smoke Check section in CLAUDE.md.

3. No blocking issues found. All functional integration checks pass.

---

## Summary

| Area | Items | Pass | Fail | Advisory |
|------|-------|------|------|----------|
| Backward Compatibility | 5 | 5 | 0 | 0 |
| Import Chain | 4 | 4 | 0 | 0 |
| Config Compatibility | 3 | 3 | 0 | 0 |
| CLAUDE.md Updates | 2 | 0 | 0 | 2 |
| SKILL.md Consistency | 3 | 3 | 0 | 0 |
| Test Integration | 3 | 3 | 0 | 0 |
| **Total** | **20** | **18** | **0** | **2** |

**Overall: PASS** -- All functional integration checks pass. 683/683 tests pass. Two advisory documentation items noted for CLAUDE.md but no blocking issues.
