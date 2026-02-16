# Documentation Improvement Master Plan

## Objective
Compare implementation vs documentation, identify gaps, create user scenarios, and improve documentation accordingly. Implementation must NOT be changed.

## Project Root
`/home/idnotbe/projects/claude-memory`

## Key Files to Analyze

### Implementation Files
- `hooks/scripts/memory_triage.py` - Stop hook: keyword triage
- `hooks/scripts/memory_retrieve.py` - Keyword-based retrieval
- `hooks/scripts/memory_index.py` - Index rebuild/validate/query
- `hooks/scripts/memory_candidate.py` - ACE candidate selection
- `hooks/scripts/memory_write.py` - Schema-enforced CRUD
- `hooks/scripts/memory_write_guard.py` - PreToolUse guard
- `hooks/scripts/memory_validate_hook.py` - PostToolUse validation
- `hooks/hooks.json` - Hook configuration
- `.claude-plugin/plugin.json` - Plugin manifest
- `assets/memory-config.default.json` - Default config
- `assets/schemas/*.schema.json` - JSON schemas (6 categories)

### Documentation Files
- `README.md` - User-facing documentation
- `CLAUDE.md` - Development guide
- `skills/memory-management/SKILL.md` - Memory management skill
- `commands/memory.md` - /memory command
- `commands/memory-save.md` - /memory-save command
- `commands/memory-search.md` - /memory-search command
- `commands/memory-config.md` - /memory-config command
- `TEST-PLAN.md` - Test plan
- `MEMORY-CONSOLIDATION-PROPOSAL.md` - Consolidation proposal

## Phases

### Phase 1: Analysis (parallel)
- **impl-analyst**: Read ALL implementation files, catalog every feature, behavior, CLI arg, config option, error path
- **doc-analyst**: Read ALL documentation files, catalog every documented feature, instruction, example

Output: `temp/10-impl-analysis.md`, `temp/10-doc-analysis.md`

### Phase 2: Gap Analysis & Scenarios (parallel, after Phase 1)
- **gap-analyst**: Compare Phase 1 outputs, identify documentation gaps
- **scenario-writer**: Create comprehensive user scenarios

Output: `temp/10-gap-analysis.md`, `temp/10-user-scenarios.md`

### Phase 3: Documentation Updates (after Phase 2)
- **doc-writer**: Update docs based on gaps and scenarios

Output: Direct file edits + `temp/10-doc-changes-log.md`

### Phase 4: Verification Round 1 (parallel, after Phase 3)
- **v1-correctness**: Verify docs match implementation exactly
- **v1-usability**: Verify docs serve all user scenarios
- **v1-completeness**: Verify no gaps remain

Output: `temp/10-v1-correctness.md`, `temp/10-v1-usability.md`, `temp/10-v1-completeness.md`

### Phase 5: Verification Round 2 (parallel, after Phase 4 fixes)
- **v2-fresh-reviewer**: Independent fresh review
- **v2-adversarial**: Try to find remaining problems
- **v2-integration**: End-to-end walkthrough

Output: `temp/10-v2-fresh.md`, `temp/10-v2-adversarial.md`, `temp/10-v2-integration.md`

## Coordination Rules
1. All inter-teammate communication via file links in temp/
2. Each teammate uses vibe-check skill and pal MCP clink independently
3. Each teammate spawns subagents for deep analysis
4. No implementation changes allowed - documentation only
