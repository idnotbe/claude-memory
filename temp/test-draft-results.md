# Test Results: memory_draft.py, --new-info-file, Phase 1 Integration

## Summary

**67 new tests written, all passing.** Full suite: 502 passed, 10 xpassed, 0 failed.

Test file: `tests/test_memory_draft.py`

## Test Coverage

### 1. Unit Tests: `assemble_create` (17 tests)
- Parametrized CREATE for all 6 categories -- validates against Pydantic schema
- Auto-populates: schema_version, category, id, timestamps, record_status, times_updated
- Slugified ID from title
- Change entry from change_summary
- Optional fields (related_files, confidence) preserved or defaulted to None
- UTC ISO timestamps

### 2. Unit Tests: `assemble_update` (14 tests)
- Preserves immutable fields: created_at, schema_version, category, id
- Increments times_updated
- Appends change entry to existing changes
- Unions tags (existing + new, deduplicated)
- Unions related_files
- Shallow-merges content (new keys overlay existing)
- Preserves record_status from existing
- Refreshes updated_at
- Parametrized UPDATE for all 6 categories -- validates against Pydantic schema

### 3. Unit Tests: Input Validation (9 tests)
- Valid staging path accepted
- Valid /tmp/ path accepted
- Arbitrary paths rejected
- `..` path components rejected
- Required fields check (title, tags, content, change_summary)
- Candidate path: must exist, must be .json, must be within .claude/memory/

### 4. CLI Tests: memory_draft.py CREATE (9 tests)
- Parametrized CLI CREATE for all 6 categories via subprocess
- Invalid content field (wrong enum value) fails validation
- Missing required input fields fails with INPUT_ERROR
- Invalid JSON file fails gracefully

### 5. CLI Tests: memory_draft.py UPDATE (3 tests)
- Successful UPDATE preserves immutable fields, increments times_updated
- Missing --candidate-file for update fails
- Nonexistent candidate file fails

### 6. CLI Tests: Path Security (2 tests)
- Input outside .staging/ and /tmp/ rejected with SECURITY_ERROR
- `..` in input path rejected with SECURITY_ERROR

### 7. Edge Cases (6 tests)
- Empty tags list (valid -- memory_write auto_fix handles)
- Very long title slugified to <= 80 chars
- Unicode title handled by slugify
- UPDATE with None changes array
- UPDATE with None times_updated
- Concurrent draft filenames unique (PID in filename)

### 8. `--new-info-file` Tests (5 tests)
- File-based produces same structural output as inline
- Content with ".env" string works (Guardian bypass validation)
- Nonexistent file errors gracefully
- --new-info-file takes precedence over --new-info
- At least one of --new-info or --new-info-file required

### 9. Integration Tests: Full Phase 1 Pipeline (2 tests)
- **CREATE pipeline**: new-info file -> memory_candidate.py -> memory_draft.py -> memory_write.py -> verify final file + index
- **UPDATE pipeline**: existing memory -> candidate match -> partial input -> draft update -> verify immutable fields preserved, tags unioned, times_updated incremented

## Test Execution

```
$ pytest tests/test_memory_draft.py -v
67 passed in 4.48s

$ pytest tests/ -v
502 passed, 10 xpassed in 33.44s
```
