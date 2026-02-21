# Staging Path Fix - Team Working Memory

## Issue
`commands/memory-save.md` (lines 39-40) instructs writing to `/tmp/.memory-write-pending.json`,
but `hooks/scripts/memory_write.py` `_read_input()` (line ~1181) enforces:
```python
in_staging = "/.claude/memory/.staging/" in resolved
```
This rejects any input not in `.claude/memory/.staging/`.

## Root Cause
Path validation was tightened in memory_write.py to only accept `.staging/` inputs,
but the `/memory:save` command template wasn't updated to match.

## Files Affected
1. **PRIMARY**: `commands/memory-save.md` - Lines 39-40 reference `/tmp/.memory-write-pending.json`
2. **SECONDARY**: `MEMORY-CONSOLIDATION-PROPOSAL.md` - Multiple `/tmp/` references (design doc, lower priority)
3. **REFERENCE (correct)**: `skills/memory-management/SKILL.md` - Already uses `.claude/memory/.staging/draft-*.json` (line 99)

## Correct Pattern (from SKILL.md line 99)
```
.claude/memory/.staging/draft-<category>-<pid>.json
```

## Fix Plan
1. Update `commands/memory-save.md` lines 39-40:
   - Change `/tmp/.memory-write-pending.json` → `.claude/memory/.staging/.memory-write-pending.json`
   - Update the `--input` argument in the command on line 40 to match
2. Consider whether MEMORY-CONSOLIDATION-PROPOSAL.md needs updating (design doc)

## Deployment
ops project loads plugin from `~/projects/claude-memory` via plugin-dirs.
Fixing source = fixing ops. No separate deployment needed.

## Team Members & Roles
- **team-lead** (me): Orchestration, task management
- **implementer**: Makes the code changes
- **reviewer-security**: Security-focused review
- **reviewer-consistency**: Cross-file consistency review
- **verifier-r1-functional**: Round 1 verification - functional correctness
- **verifier-r1-adversarial**: Round 1 verification - adversarial/edge cases
- **verifier-r2-integration**: Round 2 verification - integration testing
- **verifier-r2-completeness**: Round 2 verification - completeness audit

## Status Log
- [x] Implementation - DONE. Lines 39-40 updated. Gemini validated. Vibe check passed.
- [x] Security Review - DONE. APPROVED. No new vulnerabilities. Strict improvement (project-local vs /tmp/).
- [x] Consistency Review - DONE. APPROVED. Found stale /tmp/ refs in README.md, memory_write.py docstring, write guard dead code, TEST-PLAN.md. All flagged as follow-up (out of scope).
- [x] Verification Round 1 - Functional - DONE. PASS. E2E flow verified. All validation gates pass.
- [x] Verification Round 1 - Adversarial - DONE. PASS. No exploitable edge cases found.
- [x] Verification Round 2 - Integration - DONE. PASS. All py_compile pass, tests pass, git diff confirmed, ops auto-deploys.
- [x] Verification Round 2 - Completeness - DONE. PASS. Exhaustive /tmp/ grep classified. 2 lines in 1 file confirmed. CLAUDE.md clean.

## FINAL STATUS: ALL CHECKS PASSED - FIX IS COMPLETE

## Key Findings Across All Reviews
1. The fix is correct and minimal (2 lines in 1 file)
2. Different naming conventions (.memory-write-pending vs draft-<cat>-<pid>) are intentional
3. Stale /tmp/ references exist in docs/dead code but are out of scope
4. Pre-existing substring check weakness noted (future improvement: use Path.relative_to())
5. ops deployment is automatic via plugin-dirs symlink
