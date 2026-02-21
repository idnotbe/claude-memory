# Fix Security Vulnerabilities - Input Brief

## Your Task
Fix 4 security issues in `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`.

## Issues

### A1: Tag XML Injection (HIGH)
**Location**: Line 356
**Problem**: Tags are output without XML escaping. A tag containing `</memory-context>` breaks the data boundary.
**Current code**:
```python
tags_str = f" #tags:{','.join(sorted(tags))}" if tags else ""
print(f"- [{entry['category']}] {safe_title} -> {entry['path']}{tags_str}")
```
**Fix**: XML-escape each tag before joining. Use the same approach as `_sanitize_title()` for XML chars: `&`, `<`, `>`, `"`.

### A2: Path Traversal in check_recency (MEDIUM)
**Location**: Lines 317-319
**Problem**: `entry["path"]` from index is joined with `project_root` without containment check. Crafted path like `../../../../etc/passwd` could read outside memory dir.
**Current code**:
```python
file_path = project_root / entry["path"]
is_retired, is_recent = check_recency(file_path)
```
**Fix**: Add containment validation like `memory_candidate.py:340-344`:
```python
resolved = file_path.resolve()
try:
    resolved.relative_to(memory_root.resolve())
except ValueError:
    continue  # Skip entries outside memory root
```

### A3: cat_key Unsanitized in Descriptions Attribute (LOW)
**Location**: Lines 346-350
**Problem**: `cat_key` values from config are inserted into the `descriptions=""` attribute without sanitization. Keys with `=` or `"` could inject attributes.
**Current code**:
```python
desc_parts.append(f"{cat_key}={safe_desc}")
```
**Fix**: Sanitize cat_key - strip non-alphanumeric chars except `_`:
```python
safe_key = re.sub(r'[^a-z_]', '', cat_key.lower())
```

### A4: Path Field Not XML-Escaped (LOW)
**Location**: Line 357
**Problem**: `entry["path"]` is output without XML escaping. While unlikely on Linux, technically paths can contain `<`.
**Fix**: Apply minimal XML escaping to path field.

## Important Notes
- Read the file FIRST before making any changes
- Make minimal, focused changes - don't refactor surrounding code
- Add comments explaining security fixes where non-obvious
- After fixing, write your output report to `/home/idnotbe/projects/claude-memory/temp/task-fix-security-output.md`
- Use vibe-check skill before finalizing to sanity-check your approach
- Use pal mcp clink to get a second opinion from codex/gemini on your fixes
- Spawn subagents for independent review of your changes
