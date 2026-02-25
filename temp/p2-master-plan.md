# Plan #2 Master Coordination

## Team Structure

### Phase 1-2: Logger Module (Sequential)
- **Architect**: Phase 1 (스키마 계약) + Phase 2 (memory_logger.py 구현)
- Output: `temp/p2-logger-schema.md`, `hooks/scripts/memory_logger.py`

### Phase 3-4: Pipeline Instrumentation (After Phase 2)
- **Instrumenter**: Phase 3 (신규 계측) + Phase 4 (기존 마이그레이션)
- Modifies: memory_retrieve.py, memory_judge.py, memory_search_engine.py, memory_triage.py

### Phase 5: Tests
- **Tester**: test_memory_logger.py + performance benchmark + regression check

### Phase 6: Documentation
- **Documenter**: CLAUDE.md, memory-config.default.json updates

### Verification (2 rounds)
- **V1**: correctness + security reviewer
- **V2**: adversarial + fresh-eyes reviewer

## Key Constraints
- All logging errors: fail-open (never block hook execution)
- p95 emit_event() < 5ms
- stdlib only (no external deps)
- Atomic append: os.open(O_APPEND|O_CREAT|O_WRONLY|O_NOFOLLOW) + os.write()
- Lazy import with e.name scoping
- logging.enabled default false
- info level: no titles (secret residue prevention)
- schema_version: 1 in every event
- results[] max 20 entries
- .last_cleanup 24h gate for retention cleanup

## Session Progress
- [ ] Phase 1-2: Logger module (Architect)
- [ ] Phase 3-4: Instrumentation (Instrumenter)
- [ ] Phase 5: Tests (Tester)
- [ ] Phase 6: Docs (Documenter)
- [ ] V1: Correctness + security
- [ ] V2: Adversarial + fresh-eyes
