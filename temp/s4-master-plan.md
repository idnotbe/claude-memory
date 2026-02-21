# Session 4 (Phase 2c+2d) Master Plan -- Tests + Validation

## Status: IN PROGRESS
Started: 2026-02-21

## Pre-existing State
- **636 tests all passing** (19.84s)
- 12 test files + conftest.py in tests/
- Key source files: memory_retrieve.py, memory_search_engine.py, conftest.py

## Session 4 Tasks (from rd-08-final-plan.md lines 1107-1121)

### Phase 2c: Test Updates (~70 LOC new tests)

#### T1: Fix test_adversarial_descriptions.py import
- Line 29: `from memory_retrieve import ... score_description` -- hard import
- Need: change to conditional import (like test_memory_retrieve.py does it)
- test_memory_retrieve.py already has correct pattern at lines 31-34

#### T2: Update TestScoreEntry tests
- score_entry is preserved but behavior changes with new tokenizer
- Verify existing TestScoreEntry tests still semantically correct
- Current tests in test_memory_retrieve.py lines 91-130

#### T3: Remove/rewrite TestDescriptionScoring if score_description removed
- score_description EXISTS in memory_retrieve.py (lines 81-106) -- KEEP
- TestDescriptionScoring in test_memory_retrieve.py lines 345-411
- TestScoringExploitation in test_adversarial_descriptions.py lines 341-406
- Both test score_description -- verify they test current behavior

#### T4: Update integration tests for P3 XML format
- P3 format: `<result category="..." confidence="...">...</result>`
- NOT the old `[confidence:*]` inline format
- Check all integration tests that assert output format
- test_memory_retrieve.py TestRetrieveIntegration already uses `<result ` format
- test_arch_fixes.py also checks `<result ` format

#### T5: New FTS5 tests
- FTS5 index build/query
- Smart wildcard (compound vs single tokens)
- Body extraction
- Hybrid scoring (score_with_body)
- Fallback path (legacy keyword when FTS5 unavailable)

#### T6: Add bulk memory fixture to conftest.py
- 500-doc benchmark fixture (~20-30 LOC)
- For performance benchmark testing

#### T7: Update conftest.py test factories
- Cover all BODY_FIELDS paths:
  - session_summary: in_progress, blockers, key_changes
  - runbook: environment
  - tech_debt: acceptance_criteria
- Update existing make_*_memory() functions

#### T8: Performance benchmark
- 500 docs < 100ms for FTS5 index build + query

### Phase 2d: Validation Gate (REQUIRED)

#### V1: Compile check all scripts
```bash
python3 -m py_compile hooks/scripts/memory_retrieve.py
python3 -m py_compile hooks/scripts/memory_search_engine.py
# ... all other scripts
```

#### V2: Full test suite
```bash
pytest tests/ -v
```

#### V3: Manual test: 10+ queries across categories
#### V4: Verify no regression on existing memories
#### V5: Verify FTS5 fallback path with legacy tokenizer

## Team Structure

### Implementation Team (Phase 2c)
1. **test-fixer** -- Fix imports, update existing tests (T1-T4)
2. **fts5-test-writer** -- Write new FTS5 tests (T5)
3. **fixture-builder** -- Build bulk fixtures and update factories (T6-T7)
4. **benchmark-writer** -- Performance benchmark test (T8)

### Verification Round 1
5. **v1-correctness** -- Verify all changes are correct, no regressions
6. **v1-security** -- Verify security tests still comprehensive
7. **v1-integration** -- Run full suite, check integration

### Verification Round 2 (Independent)
8. **v2-adversarial** -- Try to break the tests, find gaps
9. **v2-independent** -- Fresh eyes review of all changes

## File Coordination
- Each teammate writes output to temp/s4-<name>-output.md
- Implementation teammates work on different files (no conflicts):
  - test-fixer: tests/test_adversarial_descriptions.py, tests/test_memory_retrieve.py
  - fts5-test-writer: tests/test_memory_retrieve.py (new class only, at end)
  - fixture-builder: tests/conftest.py
  - benchmark-writer: tests/test_memory_retrieve.py (new class only, at end)
- All teammates coordinate via task list + file links
