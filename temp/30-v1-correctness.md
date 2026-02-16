# V1 Correctness Review: Config Exemption Fix

## Rating: PASS

## Spec Compliance Matrix

| Checklist Item | Status | Notes |
|---|---|---|
| `_CONFIG_BASENAME` constant value | PASS | `"mem" + "ory-config.json"` evaluates to `"memory-config.json"` -- verified via Python eval |
| `_CONFIG_BASENAME` placement in write_guard.py | PASS | Line 20-21, after `MEMORY_DIR_TAIL` (line 18), before `main()` -- matches spec "around line 14-18 near other path markers" |
| `_CONFIG_BASENAME` placement in validate_hook.py | PASS | Line 38-39, after `MEMORY_DIR_SEGMENT` (line 36), before `FOLDER_TO_CATEGORY` -- matches spec "around lines 33-36" |
| Exemption check placement in write_guard.py | PASS | Lines 53-55, after `/tmp/` staging checks (line 51), before `normalized` deny block (line 57) -- exactly matches spec |
| Variable reuse in write_guard.py | PASS | Uses existing `basename` variable from line 44 (`basename == _CONFIG_BASENAME`), does NOT recompute `os.path.basename(resolved)` |
| Exemption check placement in validate_hook.py | PASS | Lines 162-164, after "bypassed PreToolUse guard" warning (line 160), before non-JSON check (line 166) -- exactly matches spec |
| `os.path.basename(resolved)` in validate_hook.py | PASS | Uses `os.path.basename(resolved)` since no pre-existing `basename` variable in that function -- correct per spec |
| `sys.exit(0)` in write_guard.py exemption | PASS | Line 55 -- allows the write through |
| `sys.exit(0)` in validate_hook.py exemption | PASS | Line 164 -- skips schema validation |
| Comment style consistency | PASS | Both files use single-line `#` comments matching existing style |
| Runtime string construction convention | PASS | Follows `_DOT_CLAUDE = ".clau" + "de"` pattern exactly |
| Files NOT changed (per spec) | PASS | `memory_triage.py`, `memory_retrieve.py`, `memory_candidate.py`, `memory_write.py`, `memory_index.py` have no staged changes related to this fix |
| No side effects | PASS | Exemption only fires for exact basename match; all other memory file paths still blocked/validated |

## Detailed Verification

### 1. write_guard.py Logic Flow

The main() function flow is:
1. Parse stdin JSON (exit 0 on failure)
2. Extract file_path (exit 0 if empty)
3. Resolve path via realpath/expanduser
4. Check /tmp/ staging file patterns (exit 0 if match)
5. **NEW: Check if basename == `memory-config.json` (exit 0 if match)**
6. Check if path contains memory dir segment (deny if match)
7. Exit 0 (allow) for all other paths

The config exemption at step 5 is correctly placed BEFORE the deny block at step 6. This means `memory-config.json` inside `.claude/memory/` will be allowed through before the deny check can fire. The exemption is also correctly OUTSIDE the `/tmp/` guard -- config files live in `.claude/memory/`, not `/tmp/`.

### 2. validate_hook.py Logic Flow

The main() function flow is:
1. Parse stdin JSON (exit 0 on failure)
2. Extract file_path (exit 0 if empty)
3. Resolve path
4. Check `is_memory_file()` (exit 0 if NOT a memory file)
5. Print warning about bypassed guard
6. **NEW: Check if basename == `memory-config.json` (exit 0 if match)**
7. Check if non-JSON (deny if so)
8. Run schema validation
9. Quarantine if invalid

The config exemption at step 6 is correctly placed AFTER the warning (useful for debugging) but BEFORE validation/quarantine. Since `memory-config.json` is a `.json` file, it would pass the non-JSON check at step 7 and reach schema validation at step 8, which would fail because config has no `category` field. The exemption correctly short-circuits this.

### 3. Test Coverage vs Manual Test Scenarios

| Spec Manual Test | Automated Test(s) | Status |
|---|---|---|
| Test 1: Write guard allows config write | `test_allows_config_file_write`, `test_blocks_memory_file_but_allows_config`, `test_config_file_in_different_project_paths` | Covered |
| Test 2: Validate hook skips config | `test_config_file_skips_validation`, `test_config_file_not_quarantined` | Covered |
| Test 3: Memory files still protected | `test_blocks_memory_file_but_allows_config` (write guard), `test_memory_files_still_validated` (validate hook) | Covered |
| Test 4: Invalid memory files still quarantined | `test_memory_files_still_validated` (validate hook), existing `test_invalid_memory_file_quarantined` | Covered |

### 4. Edge Case Coverage

- **Similar filenames**: `test_similar_config_filenames_still_blocked` tests 6 variants (`not-memory-config.json`, `.bak`, `.jsonl`, `.invalid.12345`, prefix variant, version variant) -- all correctly blocked
- **Multiple project paths**: 4 different root paths tested in `test_config_file_in_different_project_paths`
- **Real filesystem**: `test_config_file_not_quarantined` creates an actual file on disk and verifies no `.invalid.*` rename

### 5. Compile and Test Results

- Both source files compile cleanly (`py_compile` passes)
- All 32 tests pass (13 write guard + 19 validate hook)

## Discrepancies Found

None. The implementation exactly matches the spec in every detail.
