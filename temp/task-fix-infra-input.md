# Fix Infrastructure/Sanitization Bugs - Input Brief

## Your Task
Fix 3 infrastructure bugs across two files:
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_index.py`

## Issues

### B1: _sanitize_title() Truncation Order Bug (MEDIUM)
**Location**: memory_retrieve.py lines 192-194
**Problem**: XML escaping happens at line 192, THEN truncation at line 194. A title of 120 `&` chars becomes 600 chars of `&amp;...`, then gets truncated mid-entity.
**Current code**:
```python
# Line 192: XML escape first
title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', '&quot;')
# Line 194: Truncate after
title = title.strip()[:120]
```
**Fix**: Swap the order - truncate first, then escape:
```python
title = title.strip()[:120]
title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', '&quot;')
```

### B3: grace_period_days Type Confusion (LOW)
**Location**: memory_index.py line 203
**Problem**: If config has `"grace_period_days": "30"` (string), the comparison `age_days >= grace_period_days` raises TypeError because you can't compare int >= str.
**Current code**:
```python
grace_period_days = config.get("delete", {}).get("grace_period_days", 30)
```
**Fix**: Add type coercion:
```python
raw_gpd = config.get("delete", {}).get("grace_period_days", 30)
try:
    grace_period_days = max(0, int(raw_gpd))
except (ValueError, TypeError):
    grace_period_days = 30
```

### B4: Index Rebuild Doesn't Sanitize Titles (MEDIUM)
**Location**: memory_index.py line 104
**Problem**: `rebuild_index()` reads titles from JSON and writes them directly to index.md without sanitization. If write-side sanitization is bypassed (manual JSON edit), crafted titles containing ` -> ` or `#tags:` corrupt index parsing.
**Current code**:
```python
line = f"- [{m['display']}] {m['title']} -> {m['path']}"
```
**Fix**: Add a sanitize function to memory_index.py (same logic as memory_retrieve.py's but simpler - just handle index-format injection):
```python
def _sanitize_index_title(title: str) -> str:
    """Sanitize title for safe inclusion in index.md lines."""
    title = title.replace(" -> ", " - ")
    title = title.replace("#tags:", "")
    return title.strip()[:120]
```
Then use it: `line = f"- [{m['display']}] {_sanitize_index_title(m['title'])} -> {m['path']}"`

## Important Notes
- Read files FIRST before making any changes
- Make minimal, focused changes
- After fixing, write output to `/home/idnotbe/projects/claude-memory/temp/task-fix-infra-output.md`
- Use vibe-check skill before finalizing
- Use pal mcp clink to get codex/gemini opinions
- Spawn subagents for review
