# V1 Security Fix Applied

## Issue
V1 security reviewer found: A file named `memory-config.json` in a category subfolder (e.g., `decisions/memory-config.json`) would bypass both guards because the basename check matched without verifying the file was at the memory root level.

## Fix Applied
Added directory-depth validation to the basename exemption in both files:
- The config exemption now only fires when the file is **directly** in `.claude/memory/` (no `/` after the memory dir segment before the filename)
- Files with the same basename in subfolders (e.g., `decisions/memory-config.json`) fall through to normal deny/validate logic

### memory_write_guard.py (lines 53-62)
```python
# Allow writes to the plugin config file (not a memory record).
# Only exempt when the file is directly in the memory root, not in a subfolder
normalized = resolved.replace(os.sep, "/")
if basename == _CONFIG_BASENAME:
    idx = normalized.find(MEMORY_DIR_SEGMENT)
    if idx >= 0:
        after_mem = normalized[idx + len(MEMORY_DIR_SEGMENT):]
        if "/" not in after_mem:
            sys.exit(0)
    else:
        sys.exit(0)
```

### memory_validate_hook.py (lines 162-170)
```python
# Config file is not a memory record -- skip schema validation.
# Only exempt when the file is directly in the memory root, not in a subfolder.
if os.path.basename(resolved) == _CONFIG_BASENAME:
    norm = resolved.replace(os.sep, "/")
    idx = norm.find(MEMORY_DIR_SEGMENT)
    if idx >= 0:
        after_mem = norm[idx + len(MEMORY_DIR_SEGMENT):]
        if "/" not in after_mem:
            sys.exit(0)
    # If in a subfolder, fall through to validation
```

## Tests Added
- `test_config_file_in_subdirectory_still_blocked` (write guard) - 6 subdirectories tested
- `test_config_file_in_subdirectory_still_validated` (validate hook) - real file on disk

## Results
- 34/34 tests pass (14 write guard + 20 validate hook)
- Both scripts compile cleanly
