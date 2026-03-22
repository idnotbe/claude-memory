# Eliminate All Popups — Master Briefing

## Goal
ZERO user confirmations during auto-capture memory save flow. 3 popup sources remain.

## Popup Sources

| # | Source | Root Cause | Fix Strategy |
|---|--------|-----------|-------------|
| P1 | Phase 0 `python3 -c` intent cleanup | Guardian PreToolUse:Bash detects `os.remove` in interpreter payload | Replace with `--action cleanup-intents` in memory_write.py |
| P2 | Haiku save subagent using heredoc | Guardian PreToolUse:Bash detects heredoc body | Add `--action write-save-result-direct` + strengthen prompt |
| P3 | Write tool to `.claude/memory/.staging/*` | Claude Code hardcoded `.claude/` protected dir check (NOT bypassable by hooks) | Move staging to `/tmp/.claude-memory-staging-<project-hash>/` |

## Phase 3 Decision: Skip Option C, Go Directly to Option B

**Reason**: The action plan's P3 root cause clearly states: "A hook returning `permissionDecision: 'allow'` does NOT bypass it." The existing `memory_write_guard.py` already returns `permissionDecision: "allow"` for staging files via PreToolUse:Write — and popups still occur. Option C (PermissionRequest hook) doesn't exist as a standard hook event. No point investigating.

**Option B**: Move staging from `.claude/memory/.staging/` to `/tmp/.claude-memory-staging-<project-hash>/`.

## Key Files to Modify

| File | Phase | Changes |
|------|-------|---------|
| hooks/scripts/memory_write.py | P1+P2 | Add `cleanup-intents` action, add `write-save-result-direct` action |
| skills/memory-management/SKILL.md | P1+P2+P3 | Phase 0 script call, Phase 3 direct save-result, ALL staging path refs |
| hooks/scripts/memory_triage.py | P3 | staging_dir → /tmp/ path with project hash |
| hooks/scripts/memory_write_guard.py | P3 | Remove/update staging auto-approve logic |
| hooks/scripts/memory_staging_guard.py | P3 | Update pattern to guard new /tmp/ path |
| hooks/scripts/memory_validate_hook.py | P3 | Update staging exclusion to new path |
| hooks/scripts/memory_draft.py | P3 | Update staging path refs if any |
| hooks/scripts/memory_candidate.py | P3 | Update staging path refs if any |
| agents/memory-drafter.md | P3 | Update staging path in instructions |
| tests/test_regression_popups.py | P4 | Update + add new regression tests |
| tests/ (new) | P4 | test_cleanup_intents, test_write_save_result_direct, test_staging_path |
| CLAUDE.md | P3 | Update staging path documentation |

## Staging Path Migration Details (Phase 3 — Option B)

**New path**: `/tmp/.claude-memory-staging-<project-hash>/`
- `project-hash` = deterministic hash of the project's memory root path (e.g., `hashlib.sha256(os.path.realpath(cwd).encode()).hexdigest()[:12]`)
- This avoids collisions between different projects using the plugin

**Security requirements (from V-R2 findings)**:
- Use `os.O_NOFOLLOW` for all file creates in staging (symlink attack defense)
- Use `os.path.realpath()` + `relative_to()` for containment checks
- Set `0o700` permissions on staging directory
- Validate filename patterns before accepting

**Scripts that reference `.claude/memory/.staging/`** (from grep):
1. `memory_triage.py` — writes context files + triage-data.json + sentinel
2. `memory_write.py` — cleanup-staging, write-save-result
3. `memory_write_guard.py` — auto-approve logic for staging files
4. `memory_staging_guard.py` — blocks Bash writes to staging
5. `memory_validate_hook.py` — skips staging files from validation
6. `memory_retrieve.py` — may reference staging (check)
7. SKILL.md — ~50 lines of path references
8. agents/memory-drafter.md — staging paths in instructions
9. CLAUDE.md — documentation

## Teammate Structure

| Teammate | Scope | Isolation |
|----------|-------|-----------|
| impl-p1p2 | Phase 1 + Phase 2 (memory_write.py changes + SKILL.md P0/P3 sections) | worktree |
| impl-p3 | Phase 3 (staging migration across all scripts + SKILL.md path updates) | worktree |
| impl-tests | Phase 4 (regression tests, after P1/P2/P3 merge) | main |
| verify-r1-a | Verification Round 1: correctness + edge cases | — |
| verify-r1-b | Verification Round 1: security + operational | — |
| verify-r2-a | Verification Round 2: adversarial + cross-model clink | — |
| verify-r2-b | Verification Round 2: holistic + integration | — |

## Shared Helper: Staging Path Function

All scripts should use a shared function for computing the staging path. Suggested implementation:

```python
import hashlib
import os

def get_staging_dir(cwd: str = "") -> str:
    """Get deterministic /tmp/ staging directory for the current project."""
    if not cwd:
        cwd = os.getcwd()
    project_hash = hashlib.sha256(os.path.realpath(cwd).encode()).hexdigest()[:12]
    return f"/tmp/.claude-memory-staging-{project_hash}"
```

This should be placed in a shared location (e.g., a new `memory_staging.py` utility module or added to `memory_write.py` and imported by others).

## Constraints

- Never break existing tests (run pytest after changes)
- All staging file I/O must use O_NOFOLLOW
- The memory_drafter agent only has Read+Write tools (no Bash) — if staging moves to /tmp/, the drafter's Write tool usage for intent-*.json must still work at the new path
- SKILL.md Write tool calls for staging (Phase 1.5 Steps 2, 4, 5; Phase 3 Step 3) must be updated to use new paths
- memory_write_guard.py already auto-approves /tmp/.memory-* paths — may need to extend for new /tmp/.claude-memory-staging-* paths
