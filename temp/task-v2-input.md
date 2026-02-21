# Verification Round 2 - Input Brief

## Context
All 12 fixes passed V1 review (correctness + security). Now verify functionally and integration-wise.

## V1 Results (read for context)
- `/home/idnotbe/projects/claude-memory/temp/task-v1-correctness-output.md` - PASS
- `/home/idnotbe/projects/claude-memory/temp/task-v1-security-output.md` - PASS

## Fix Reports
- `/home/idnotbe/projects/claude-memory/temp/task-fix-security-output.md`
- `/home/idnotbe/projects/claude-memory/temp/task-fix-algorithm-output.md`
- `/home/idnotbe/projects/claude-memory/temp/task-fix-infra-output.md`

## Files Modified
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_index.py`

## Functional Verification
1. Run `pytest tests/ -v` - do existing tests still pass?
2. Run `python3 -m py_compile` on both files
3. Test edge cases manually if needed (crafted inputs, boundary values)
4. Check that the scoring changes (B2, C1, C2, C3) produce expected results for sample inputs

## Integration Verification
1. Cross-file consistency: Do memory_retrieve.py and memory_index.py agree on index format?
2. Do the fixes align with CLAUDE.md documentation? Does CLAUDE.md need updates?
3. Do the fixes align with SKILL.md? Any skill instructions affected?
4. Are tests in tests/ covering the new behaviors? Any new tests needed?
5. Ops impact: Read `/home/idnotbe/projects/claude-memory/temp/task-ops-output.md` for ops findings

## V1 Non-blocking Observations to Track
- B4: null bytes not stripped in `_sanitize_index_title()` (v1-security LOW warning)
- B4: tags not sanitized in index rebuild (v1-correctness observation)

## Output
- Functional: `/home/idnotbe/projects/claude-memory/temp/task-v2-functional-output.md`
- Integration: `/home/idnotbe/projects/claude-memory/temp/task-v2-integration-output.md`
