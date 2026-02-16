# Category Description Feature -- Implementation Plan

## Goal
Add a `description` field to category config so LLM can accurately classify content
into categories using title + description, and retrieve memories with better context.

## Current State
- `memory-config.default.json` has categories with: enabled, folder, auto_capture, retention_days
- No description field exists -- category semantics are implicit from the key name
- `memory_triage.py` uses hardcoded keyword patterns (doesn't reference config category names)
- `memory_retrieve.py` matches against index.md entries (title + tags), outputs matched memories
- `SKILL.md` has a hardcoded category table with "What It Captures" column

## Changes Required

### 1. Config Schema (`assets/memory-config.default.json`)
Add `description` field to each category:
```json
"decision": {
  "enabled": true,
  "folder": "decisions",
  "description": "Architectural and technical choices with rationale (why X over Y)",
  "auto_capture": true,
  "retention_days": 0
}
```

### 2. Triage Hook (`hooks/scripts/memory_triage.py`)
- Load category descriptions from config via `load_config()`
- Add descriptions to the `<triage_data>` JSON block (new field per category entry)
- Include description in context files written to `/tmp/` so subagents know what the category means
- Backward compatible: missing description = empty string

### 3. Retrieval Hook (`hooks/scripts/memory_retrieve.py`)
- Load category descriptions from config
- Include descriptions in `<memory-context>` output (so AI understands what each category is)
- Use description tokens for additional scoring (lower weight than title/tags)
- Backward compatible: missing description = no extra scoring

### 4. SKILL.md Updates
- Update category table to note descriptions come from config
- Update subagent instructions to reference category descriptions

### 5. CLAUDE.md Updates
- Document the new `description` field in config architecture

### 6. JSON Schema (`assets/schemas/`)
- No changes needed -- descriptions are config-level, not per-memory-file

## Backward Compatibility
- All changes must be backward compatible
- Missing `description` field = empty string (no behavioral change)
- Existing configs without descriptions continue to work identically

## Test Plan (TDD - RED first)
### Triage tests:
- `test_load_config_reads_descriptions`: Config with descriptions parsed correctly
- `test_load_config_missing_descriptions`: Falls back to empty string
- `test_context_file_includes_description`: Context files include category description
- `test_triage_data_includes_description`: JSON output includes description field
- `test_block_message_includes_description`: Human-readable message includes description

### Retrieval tests:
- `test_retrieval_loads_descriptions`: Config descriptions loaded correctly
- `test_retrieval_output_includes_descriptions`: Output context includes category descriptions
- `test_description_tokens_boost_score`: Description keywords contribute to scoring
- `test_retrieval_no_description_backward_compat`: Works without descriptions

## File Impact
| File | Change Type |
|------|------------|
| assets/memory-config.default.json | Add description field |
| hooks/scripts/memory_triage.py | Load + output descriptions |
| hooks/scripts/memory_retrieve.py | Load + score + output descriptions |
| skills/memory-management/SKILL.md | Doc update |
| CLAUDE.md | Doc update |
| tests/test_memory_triage.py | NEW: triage tests |
| tests/test_memory_retrieve.py | Add description tests |
