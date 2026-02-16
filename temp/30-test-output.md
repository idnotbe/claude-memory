# Test Output: Config Exemption Tests

## Summary

Added 7 new tests across 2 test files covering the `memory-config.json` exemption feature. All 32 tests (9 pre-existing + 4 new in write guard, 12 pre-existing + 3 new in validate hook) pass.

## Tests Added

### test_memory_write_guard.py (4 new tests in TestWriteGuard)

| Test | What It Verifies |
|------|-----------------|
| `test_allows_config_file_write` | `memory-config.json` in `.claude/memory/` is ALLOWED through the guard (no deny output) |
| `test_blocks_memory_file_but_allows_config` | Config file is allowed AND memory files are still blocked in the same test -- confirms the exemption is selective |
| `test_config_file_in_different_project_paths` | Config file under 4 different project roots (Linux home, macOS home, /tmp, bare .claude) all pass through |
| `test_similar_config_filenames_still_blocked` | 6 similar-but-different filenames (`not-memory-config.json`, `memory-config.json.bak`, `.jsonl`, `.invalid.12345`, `my-memory-config.json`, `memory-config-v2.json`) are still blocked |

### test_memory_validate_hook.py (3 new tests in TestValidateHookIntegration)

| Test | What It Verifies |
|------|-----------------|
| `test_config_file_skips_validation` | Config file path produces no deny decision (subprocess integration test) |
| `test_config_file_not_quarantined` | Writes a real config JSON file to a tmp_path `.claude/memory/` structure, runs the hook, verifies the file still exists with its original name and no `.invalid.*` siblings |
| `test_memory_files_still_validated` | Invalid memory file in `decisions/` is still quarantined after the config exemption is in place |

## Edge Cases Considered

1. **Path variation**: Config file tested under Linux (`/home/alice/...`), macOS (`/Users/bob/...`), temp (`/tmp/...`), and bare user home (`/home/user/.claude/memory/...`) paths
2. **Similar filenames**: Six different filename variants that look like but are NOT the config file -- ensures the basename check is exact-match only
3. **Selective exemption**: Dual assertions in `test_blocks_memory_file_but_allows_config` confirm that the exemption is narrow (config allowed, memory files blocked)
4. **Real file system**: `test_config_file_not_quarantined` uses `tmp_path` to create actual files on disk and verify no quarantine rename occurs
5. **Contrast test**: `test_memory_files_still_validated` confirms the validation hook still works for non-config files after the exemption

## Test Run Results

```
32 passed in 1.12s
```

All tests pass, including both existing tests and new config exemption tests.

### Breakdown
- `test_memory_write_guard.py`: 13 tests (9 existing + 4 new) -- all PASSED
- `test_memory_validate_hook.py`: 19 tests (16 existing + 3 new) -- all PASSED

## Files Modified

- `/home/idnotbe/projects/claude-memory/tests/test_memory_write_guard.py` -- added 4 test methods
- `/home/idnotbe/projects/claude-memory/tests/test_memory_validate_hook.py` -- added 3 test methods
