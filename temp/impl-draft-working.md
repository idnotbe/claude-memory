# memory_draft.py Implementation Working Notes

## Status: In Progress

## Understanding

### What memory_draft.py does:
- Assembles complete schema-compliant memory JSON from a partial input file
- Two modes: CREATE (new memory) and UPDATE (modify existing)
- Validates with Pydantic models from memory_write.py
- Outputs draft to `.claude/memory/.staging/draft-<category>-<timestamp>.json`

### Key imports from memory_write.py:
- `slugify` (line 233): kebab-case slug from text
- `now_utc` (line 229): ISO 8601 UTC timestamp
- `build_memory_model` (line 189): dynamic Pydantic model per category
- `CONTENT_MODELS` (line 159): maps category -> content Pydantic model
- `CATEGORY_FOLDERS` (line 58): maps category -> folder name
- `ChangeEntry` (line 173): Pydantic model for changes[] entries

### Input file format (what LLM writes):
```json
{
  "title": "...",
  "tags": ["..."],
  "confidence": 0.8,
  "related_files": ["..."],
  "change_summary": "...",
  "content": { /* category-specific */ }
}
```

### Auto-populated fields:
- schema_version: "1.0"
- category: from --category arg
- id: slugified from title
- created_at: now (CREATE) / preserved (UPDATE)
- updated_at: now
- record_status: "active"
- changes: [{"date": today, "summary": change_summary}]
- times_updated: 0 (CREATE) / existing+1 (UPDATE)

### Security: input path must be in .claude/memory/.staging/ or /tmp/

### For UPDATE:
- Read existing from --candidate-file
- Preserve: created_at, schema_version, category, id
- Tags: union (deduplicated)
- Changes: append new entry
- Content: shallow merge (existing, overlay with new)

## Design Decisions
- Keep merge logic MINIMAL -- memory_write.py does final enforcement
- Same venv bootstrap as memory_write.py
- Import from memory_write.py via sys.path manipulation
