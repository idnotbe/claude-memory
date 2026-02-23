# Root File Cleanup Working Memory

## Task
Analyze root-level files and decide: delete, move, or keep.

## Final Decision (3-model consensus + vibe check)

| File | Action | Reasoning |
|------|--------|-----------|
| test_bug6.py | **DELETE** | Ad-hoc debug. Nested-tags edge case: memory_judge.py:182-185 has isinstance defense; Pydantic blocks malformed tags at write. No crash risk. Port unnecessary. |
| test_context.py | **DELETE** | Ad-hoc debug. Side effect (writes files). Pytest collection risk. Coverage exists in test_memory_judge.py. |
| test_fix.py | **DELETE** | Standalone snippet, no project imports. Not a real test. |
| test_transcript.jsonl | **DELETE** | Generated artifact from test_context.py. |
| TEST-PLAN.md | **MOVE → plans/** | Planning doc, plans/ dir exists. Update refs in CLAUDE.md + README.md. |

## Model Opinions

### Codex (o4-mini via pal clink)
- test_bug6.py: Port first, then delete (unique point: regression value)
- test_context.py, test_fix.py, test_transcript.jsonl: DELETE
- TEST-PLAN.md: MOVE to plans/
- Extra insight: pytest collection executes root test_*.py bodies = side-effect risk

### Gemini (gemini-3-pro)
- All 4 ad-hoc files: DELETE
- TEST-PLAN.md: MOVE to plans/
- Note: "port if edge case is critical"

### My (Opus 4.6) assessment
- All 4 ad-hoc files: DELETE (after verifying test_bug6.py edge case — VERIFIED: not needed)
- TEST-PLAN.md: MOVE to plans/

## Vibe Check Result
- Plan: SOLID (3-model convergence)
- Recommendation: Proceed with minor adjustment (verified nested-tags coverage)
- Pattern watch: No concerning patterns detected

## References to Update
- CLAUDE.md:88 — "See TEST-PLAN.md" → "See plans/TEST-PLAN.md"
- README.md:442 — "See `TEST-PLAN.md`" → "See `plans/TEST-PLAN.md`"

## Execution Plan
1. `git rm` the 4 ad-hoc files
2. `git mv TEST-PLAN.md plans/TEST-PLAN.md`
3. Update CLAUDE.md and README.md references
4. Verification Round 1 (subagent)
5. Verification Round 2 (independent subagent)

## Verification
- [x] Round 1 — ALL PASSED (files removed, refs updated, audio kept, no stray refs)
- [x] Round 2 — ALL PASSED (independent confirm: git status clean, no root test_*.py, plans/TEST-PLAN.md 198 lines, all refs correct, audio files intact)

## Status: COMPLETE
Note: CLAUDE.md and README.md edits need staging before commit (not yet committed per user's instructions).
