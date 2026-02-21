# Fix Infrastructure/Sanitization Bugs - Output Report

## Status: COMPLETE

All 3 bugs (B1, B3, B4) fixed. Both files pass `py_compile`.

## Changes Made

### B1: _sanitize_title() Truncation Order Bug (memory_retrieve.py lines 198-202)
**Fix**: Swapped truncation before XML escaping to prevent mid-entity cuts.

Before:
```python
title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', '&quot;')
title = title.strip()[:120]
```

After:
```python
title = title.strip()[:120]
title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', '&quot;')
```

### B3: grace_period_days Type Confusion (memory_index.py lines 216-220)
**Fix**: Added type coercion with try/except to handle string config values.

Before:
```python
grace_period_days = config.get("delete", {}).get("grace_period_days", 30)
```

After:
```python
raw_gpd = config.get("delete", {}).get("grace_period_days", 30)
try:
    grace_period_days = max(0, int(raw_gpd))
except (ValueError, TypeError):
    grace_period_days = 30
```

### B4: Index Rebuild Doesn't Sanitize Titles (memory_index.py lines 89-99, 117)
**Fix**: Added `_sanitize_index_title()` helper before `rebuild_index()`. Uses `" ".join(title.split())` to collapse whitespace including newlines (line-format safety), strips ` -> ` and `#tags:` injection markers, and truncates to 120 chars.

New helper:
```python
def _sanitize_index_title(title: str) -> str:
    """Sanitize title for safe inclusion in index.md lines."""
    title = " ".join(title.split())
    title = title.replace(" -> ", " - ")
    title = title.replace("#tags:", "")
    return title[:120]
```

Usage in rebuild_index():
```python
line = f"- [{m['display']}] {_sanitize_index_title(m['title'])} -> {m['path']}"
```

## Review Notes
- Gemini confirmed B1 and B3 correct.
- Gemini flagged B4 as incomplete in original spec (missing newline sanitization). Enhanced to use `" ".join(title.split())` which handles all whitespace including `\n`, `\t`, `\r`.
- codex-cli hit usage limits; gemini review was sufficient.

## Files Modified
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py` (lines 198-202)
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_index.py` (lines 89-99, 116-220)

## Verification
```
python3 -m py_compile hooks/scripts/memory_retrieve.py  # OK
python3 -m py_compile hooks/scripts/memory_index.py     # OK
```
