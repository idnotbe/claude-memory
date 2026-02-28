# Phase 1: Fix A — triage_data Externalization Implementation Context

## Goal
Remove the inline `<triage_data>` JSON blob from the Stop hook's `reason` field. Instead, write triage data to a file and reference it. This reduces the `reason` from ~25 lines to ~5 lines.

## CRITICAL: Deploy Order
**SKILL.md must be updated FIRST, then memory_triage.py.**
New SKILL.md supports both `<triage_data_file>` and inline `<triage_data>` (backwards compatible).
Old SKILL.md only knows `<triage_data>`. If memory_triage.py changes first → silent save failure.

SKILL.md Phase 0 was already updated in a previous session to support `<triage_data_file>` + inline fallback.

## Changes Required

### 1. memory_triage.py — extract `build_triage_data()` helper

Currently, triage_data dict is built inside `format_block_message()` (lines 911-948). This is a local variable — `_run_triage()` can't access it to write to file.

**Solution:** Extract triage_data construction into `build_triage_data()` helper that both `_run_triage()` and `format_block_message()` can use.

```python
def build_triage_data(results, context_paths, parallel_config, category_descriptions=None):
    """Build structured triage data dict from results."""
    triage_categories = []
    for r in results:
        category = r["category"]
        cat_lower = category.lower()
        entry = {
            "category": cat_lower,
            "score": round(r["score"], 4),
        }
        if category_descriptions:
            desc = category_descriptions.get(cat_lower, "")
            if desc:
                entry["description"] = desc
        ctx_path = context_paths.get(cat_lower)
        if ctx_path:
            entry["context_file"] = ctx_path
        triage_categories.append(entry)

    return {
        "categories": triage_categories,
        "parallel_config": {
            "enabled": parallel_config.get("enabled", True),
            "category_models": parallel_config.get("category_models", DEFAULT_PARALLEL_CONFIG["category_models"]),
            "verification_model": parallel_config.get("verification_model", DEFAULT_PARALLEL_CONFIG["verification_model"]),
            "default_model": parallel_config.get("default_model", DEFAULT_PARALLEL_CONFIG["default_model"]),
        },
    }
```

### 2. _run_triage() — add triage_data file writing (atomic)

After `write_context_files()` (line 1123), build triage_data and write to file:

```python
# Build triage data
triage_data = build_triage_data(results, context_paths, parallel_config, category_descriptions=cat_descs)

# Atomic write triage-data.json
triage_data_path = os.path.join(cwd, ".claude", "memory", ".staging", "triage-data.json")
try:
    tmp_path = triage_data_path + ".tmp"
    fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, json.dumps(triage_data, indent=2).encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(tmp_path, triage_data_path)
except OSError:
    triage_data_path = None  # Fallback to inline
```

### 3. format_block_message() — accept triage_data_path parameter

```python
def format_block_message(results, context_paths, parallel_config, *,
                         category_descriptions=None, triage_data_path=None):
    # ... human-readable lines stay the same ...

    # Replace inline <triage_data> with file reference
    if triage_data_path:
        lines.append("")
        lines.append(f"<triage_data_file>{triage_data_path}</triage_data_file>")
    else:
        # Inline fallback
        triage_data = build_triage_data(results, context_paths, parallel_config,
                                         category_descriptions=category_descriptions)
        lines.append("")
        lines.append("<triage_data>")
        lines.append(json.dumps(triage_data, indent=2))
        lines.append("</triage_data>")
```

### 4. Update _run_triage() call to format_block_message()

Pass triage_data_path:
```python
message = format_block_message(
    results, context_paths, parallel_config,
    category_descriptions=cat_descs,
    triage_data_path=triage_data_path,
)
```

### 5. Doc Updates
- CLAUDE.md: Update "structured `<triage_data>` JSON" references
- SKILL.md line 58: Already updated in previous session

### 6. Test Updates
- Tests asserting `<triage_data>` in output need updating to check for `<triage_data_file>`
- New tests: file creation, JSON validity, fallback when file write fails

## Key File Locations

| File | Lines | Change |
|------|-------|--------|
| hooks/scripts/memory_triage.py | 870-955 (format_block_message) | Add triage_data_path param, conditional output |
| hooks/scripts/memory_triage.py | 908-948 (triage_data build) | Extract to build_triage_data() |
| hooks/scripts/memory_triage.py | 1117-1131 (_run_triage output) | Add file write + pass triage_data_path |
| skills/memory-management/SKILL.md | 56-59 (Phase 0) | Already done |
| CLAUDE.md | ~36 | Update triage_data reference |
| tests/test_memory_triage.py | Multiple | Update <triage_data> assertions |
| tests/test_adversarial_descriptions.py | Multiple | Update <triage_data> assertions |

## Important Constraints
1. staging dir already exists at this point (created by sentinel write at line 1102-1103)
2. `os.makedirs(sentinel_dir, exist_ok=True)` ensures .staging/ exists before triage-data.json write
3. Use `O_NOFOLLOW` for security (prevent symlink attacks)
4. Atomic write: tmp file + os.replace (prevents partial reads)
5. Fail-open: if file write fails, fall back to inline <triage_data>
