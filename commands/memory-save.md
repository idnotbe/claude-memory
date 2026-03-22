---
name: memory:save
description: Manually save a memory to a specific category
arguments:
  - name: category
    description: Category name (session_summary, decision, runbook, constraint, tech_debt, preference)
    required: true
  - name: content
    description: What to remember (natural language description)
    required: true
---

**Examples:**
```
/memory:save decision "We chose Vitest over Jest for speed and ESM support"
/memory:save preference "Always use single quotes and 2-space indentation"
/memory:save runbook "Docker build fails with OOM -- fix: increase Docker memory to 4GB"
/memory:save constraint "Discourse Managed Pro does not allow custom plugins"
```

Save a memory manually:

1. Read `.claude/memory/memory-config.json` to validate the category exists
2. If category is invalid, list available categories and ask user to choose
3. Generate a descriptive kebab-case slug from the content (this becomes both the filename and the `id` field)
4. Create the JSON object with full schema:
   - schema_version: "1.0"
   - category: the selected category
   - id: kebab-case slug matching the filename (without .json)
   - title: human-readable title (max 120 chars)
   - created_at / updated_at: current ISO 8601 UTC timestamp
   - tags: extracted keywords (minimum 1, maximum 12)
   - record_status: "active"
   - changes: []
   - times_updated: 0
   - related_files: [] (populate if relevant files are mentioned)
   - confidence: 0.7-0.9 (0.9+ only for explicitly confirmed facts)
   - content: structured per the category schema
5. Write the JSON to `/tmp/.memory-write-pending.json`
6. Call: `python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write.py --action create --category <cat> --target <memory_root>/<folder>/<slug>.json --input /tmp/.memory-write-pending.json`
   - memory_write.py handles schema validation, atomic writes, and index.md updates
7. Confirm: show the filename created and a brief summary

The content argument is natural language. Structure it into the appropriate
JSON schema for the category. Ask the user for missing required fields
(e.g., for a decision: what were the alternatives? why was this chosen?).

**Category folder mapping**:
| Category | Folder |
|----------|--------|
| session_summary | sessions/ |
| decision | decisions/ |
| runbook | runbooks/ |
| constraint | constraints/ |
| tech_debt | tech-debt/ |
| preference | preferences/ |
