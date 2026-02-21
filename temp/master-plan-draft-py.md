# Master Plan: memory_draft.py + --new-info-file + SKILL.md Update

## Task Summary
From `/home/idnotbe/projects/ops/temp/claude-memory-prompt.md`:
1. **CREATE** `hooks/scripts/memory_draft.py` - Assembles complete schema-compliant JSON from partial input
2. **MODIFY** `hooks/scripts/memory_candidate.py` - Add `--new-info-file` argument
3. **MODIFY** `skills/memory-management/SKILL.md` - Update Phase 1 instructions for new flow

## Key Design Decisions
- memory_draft.py is ASSEMBLY only; memory_write.py does ENFORCEMENT
- LLMs write partial JSON via Write tool (bypasses Guardian bash scanning)
- memory_draft.py imports from memory_write.py (slugify, now_utc, build_memory_model, CONTENT_MODELS, CATEGORY_FOLDERS, ChangeEntry)
- Input paths restricted to `.claude/memory/.staging/` or `/tmp/`
- Same venv bootstrap pattern as memory_write.py

## Team Structure

### Phase 1: Implementation (parallel, worktrees)
- **impl-draft** - Creates memory_draft.py
- **impl-candidate** - Modifies memory_candidate.py
- **impl-skill** - Updates SKILL.md

### Phase 2: Multi-Perspective Review (parallel)
- **reviewer-correctness** - Logic, bugs, spec compliance
- **reviewer-security** - Injection vectors, path traversal, trust boundaries
- **reviewer-integration** - Compatibility with existing pipeline, edge cases

### Phase 3: Testing
- **tester** - Unit + integration tests

### Phase 4: Verification Round 1 (parallel, diverse)
- **verifier-r1-code** - Code-level verification
- **verifier-r1-design** - Design/architecture verification

### Phase 5: Verification Round 2 (parallel, diverse)
- **verifier-r2-adversarial** - Adversarial testing mindset
- **verifier-r2-practical** - Practical/real-world usage verification

## File Communication Protocol
- Input specs: this file + original prompt at `/home/idnotbe/projects/ops/temp/claude-memory-prompt.md`
- Implementation outputs: worktree branches merged to working branch
- Review outputs: `temp/review-draft-<perspective>.md`
- Verification outputs: `temp/verify-draft-r<N>-<perspective>.md`
- Test outputs: `temp/test-draft-results.md`

## Critical Reference Files
- `hooks/scripts/memory_write.py` - Source of imports (slugify, now_utc, build_memory_model, etc.)
- `hooks/scripts/memory_candidate.py` - File to modify (add --new-info-file)
- `skills/memory-management/SKILL.md` - File to modify (Phase 1 instructions)
- `hooks/hooks.json` - Hook configuration (no changes needed)

## Progress Tracking
- [x] Phase 1: Implementation
  - [x] memory_draft.py created (332 lines)
  - [x] memory_candidate.py modified (+19 lines)
  - [x] SKILL.md updated (+81/-23 lines)
- [x] Phase 2: Reviews complete (correctness PASS, security PASS+1fix, integration PASS)
- [x] Phase 3: Tests written and passing (67 new, 502 total, 0 failures)
- [x] Phase 4: Verification Round 1 complete (code PASS, design PASS)
- [x] Phase 5: Verification Round 2 complete (adversarial PASS+1fix, practical PASS)

## Fixes Applied During Reviews
1. **Security**: Added --candidate-file path containment check in memory_draft.py (from R2 security review)
2. **Dead code**: Removed unused CONTENT_MODELS import in memory_draft.py (from R1 code verification)
3. **Unicode**: Added Unicode Cf category stripping in memory_write.py auto_fix() (from R2 adversarial)

## Team Members (11 agents total)
| Agent | Role | Phase |
|-------|------|-------|
| impl-draft | memory_draft.py creation | 1 |
| impl-candidate | memory_candidate.py modification | 1 |
| impl-skill | SKILL.md update | 1 |
| reviewer-correctness | Logic/spec review | 2 |
| reviewer-security | Security review | 2 |
| reviewer-integration | Integration review | 2 |
| tester | Tests (67 new) | 3 |
| verifier-r1-code | Code-level verification | 4 |
| verifier-r1-design | Design-level verification | 4 |
| verifier-r2-adversarial | Adversarial verification | 5 |
| verifier-r2-practical | Practical verification | 5 |

## Status: COMPLETED
