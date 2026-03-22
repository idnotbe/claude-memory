# Implementation Log: Legacy Staging Path Validation Fix

## Bug
The legacy staging path validation in `memory_write.py` used an overly permissive pattern:
```python
is_legacy_staging = (len(parts) >= 2 and parts[-1] == ".staging" and parts[-2] == "memory")
```
This accepted ANY path ending in `memory/.staging` (e.g., `/tmp/evil/memory/.staging`, `/etc/memory/.staging`).

## Fix Applied

### Helper Function
Added `_is_valid_legacy_staging(resolved_path, allow_child=False)` at line 81 of `memory_write.py`:
- Iterates path components looking for the exact `.claude -> memory -> .staging` sequence
- `allow_child=False` (default): requires `.staging` as the terminal component (for staging directory validation)
- `allow_child=True`: allows child components after `.staging` (for file-within-staging validation in `_read_input()`)

### Call Sites Updated (5 total)
1. `cleanup_staging()` -- line 553 (directory mode)
2. `cleanup_intents()` -- line 605 (directory mode)
3. `write_save_result()` -- line 655 (directory mode)
4. `update_sentinel_state()` -- line 761 (directory mode)
5. `_read_input()` -- line 1599 (`allow_child=True`)

### Test Fixture Fix
`TestCleanupIntents._make_staging()` was creating paths like `tmp_path / "memory" / ".staging"` which the old permissive check accepted. Updated to use `tmp_path / ".claude" / "memory" / ".staging"` to match the new stricter validation.

## Code Review Findings (Gemini clink)
The reviewer identified two issues, both addressed:

1. **Terminal constraint regression** (Medium): The initial helper dropped the requirement that `.staging` be the final component, allowing subdirectory bypass. Fixed by adding `allow_child` parameter -- directory-mode callers enforce terminal constraint, `_read_input()` uses `allow_child=True`.

2. **Cross-project bypass** (noted but accepted): `/tmp/.claude/memory/.staging` would pass since validation is not anchored to project root. This is acceptable because: (a) the old check had no project anchoring either, (b) staging dirs are set by the plugin, not user-supplied, (c) `.claude/memory/.staging` is a much harder structure to craft than just `memory/.staging`.

## Test Coverage
14 tests in `TestLegacyStagingValidation`:
- Valid paths: standard, nested, root-level
- Rejected paths: evil (`/tmp/evil/`), `/etc/`, wrong order, missing components, partial name
- Terminal constraint: subdirectory bypass rejected, file-in-staging rejected in dir mode
- `allow_child` mode: file accepted, directory accepted, evil path rejected
- `/tmp/` staging paths correctly return False (handled by separate `startswith()` check)

## Verification
- `python3 -m py_compile hooks/scripts/memory_write.py` -- clean
- `pytest tests/test_memory_write.py -v` -- 128 passed
- `pytest tests/ --tb=short` -- 1217 passed
