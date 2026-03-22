---
status: done
progress: "All 4 phases complete. P1: cleanup-intents action. P2: write-save-result-direct action. P3: staging moved to /tmp/. P4: 37 regression tests. 2 rounds of verification with security hardening (symlink squat defense). 1164 tests pass."
---

# Eliminate All Permission Popups — Action Plan

Despite previous 6-phase fix, 3 distinct popup sources remain. Goal: ZERO user confirmations during auto-capture memory save flow.

## Popup Sources (from live session logs 2026-03-22)

| # | Source | Type | Count/Session |
|---|--------|------|---------------|
| P1 | Phase 0 `python3 -c` intent cleanup | Guardian PreToolUse:Bash | 1-2x |
| P2 | Haiku save subagent using heredoc `cat > file << 'DONE'` | Guardian PreToolUse:Bash | 0-1x |
| P3 | Write tool to `.claude/memory/.staging/*` files | Claude Code protected directory check | 4-6x |

### P3 Root Cause (NEW FINDING)
Claude Code has a **hardcoded protected directory system** for `.claude/` paths. It prompts for ALL writes to `.claude/` except `.claude/commands/`, `.claude/agents/`, `.claude/skills/`. `.claude/memory/` is NOT exempt. This check runs AFTER and INDEPENDENTLY of PreToolUse hooks. A hook returning `permissionDecision: "allow"` does NOT bypass it. Even `--dangerously-skip-permissions` does not bypass it (per GitHub issues #35646, #35718).

## Phases

### Phase 1: Fix P1 — Replace python3 -c with Script Action [ ]
- [ ] **Step 1.1**: Add `--action cleanup-intents` to `memory_write.py`. Implementation: `glob.glob(staging_dir + '/intent-*.json')` → `os.remove()` each. Return JSON status.
- [ ] **Step 1.2**: Update SKILL.md Phase 0 Step 0. Replace inline `python3 -c "import glob,os..."` with `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action cleanup-intents --staging-dir .claude/memory/.staging`.
- [ ] **Step 1.3**: Update Rule 0 to explicitly forbid `python3 -c` for ALL file operations (not just `.claude` paths).
- [ ] **Step 1.4**: Add test: `test_cleanup_intents_action` — verify cleanup-intents removes intent-*.json, doesn't remove other staging files.

### Phase 2: Fix P2 — Prevent Haiku Heredoc [ ]
- [ ] **Step 2.1**: Strengthen SKILL.md Phase 3 save subagent prompt. Add: "CRITICAL: Using heredoc (<<) or cat with redirect will trigger a permission popup and block the save. You MUST use Write tool for file content and python3 scripts for commands."
- [ ] **Step 2.2**: Add `--action write-save-result-direct` to `memory_write.py` that takes the result JSON via `--categories` and `--titles` CLI args instead of requiring a file. This eliminates the need for the subagent to write a JSON file at all.
- [ ] **Step 2.3**: Update SKILL.md Phase 3 save subagent prompt to use the new direct action instead of the Write-then-Bash two-step.
- [ ] **Step 2.4**: Add test: `test_write_save_result_direct` — verify direct action works.

### Phase 3: Fix P3 — Eliminate Write Tool for Staging Files [ ]

The `.claude/` protected directory check is a platform limitation. Three workaround options evaluated:

**Option C (INVESTIGATE FIRST — 30 min experiment): PermissionRequest hook**
- [ ] Add `PermissionRequest` hook matcher for Write tool
- [ ] Script checks if path is `.claude/memory/.staging/` and returns `behavior: "allow"`
- [ ] If this works: minimal change, preserves all existing architecture
- [ ] If it doesn't work: proceed to Option B

**Option B (RECOMMENDED per V-R1/R2): Move staging outside .claude/**
- [ ] **Step 3.1**: Move staging from `.claude/memory/.staging/` to `/tmp/.claude-memory-staging-<project-hash>/`
- [ ] **Step 3.2**: Create staging dir in `memory_triage.py` with `tempfile.mkdtemp()` or deterministic hash. Use `os.O_NOFOLLOW` for all file creates in staging (symlink attack defense, V-R2 finding).
- [ ] **Step 3.3**: Update all scripts that reference `.claude/memory/.staging/`: `memory_triage.py`, `memory_write.py`, `memory_write_guard.py`, `memory_staging_guard.py`, `memory_validate_hook.py`, `memory_retrieve.py`, SKILL.md (~50 lines of mechanical path updates).
- [ ] **Step 3.4**: Update `memory_write_guard.py` staging auto-approve logic to match new `/tmp/` paths.
- [ ] **Step 3.5**: Update `memory_staging_guard.py` to guard new path.
- [ ] **Step 3.6**: Add `.gitignore` exclusion if staging moves to project-level dir (N/A for /tmp/).
- [ ] This is conceptually simpler, respects platform security boundary, and preserves LLM's native Write tool usage (V-R1: Gemini, V-R2: holistic reviewer agree).

**Option A (FALLBACK): Route all staging writes through Python scripts**
- [ ] Only if both C and B fail. V-R2 adversarial reviewer flagged `write-staging` as overly broad — if used, must validate filename against `_STAGING_FILENAME_RE`, enforce `resolve().relative_to()`, and use `O_NOFOLLOW`.

### Phase 4: Regression Tests [ ]
- [ ] **Step 4.1**: `test_zero_write_tool_calls_for_staging` — verify SKILL.md never instructs Write tool for `.staging/` paths
- [ ] **Step 4.2**: `test_no_python3_c_in_skill` — verify SKILL.md has zero `python3 -c` commands
- [ ] **Step 4.3**: `test_no_heredoc_in_skill` — verify SKILL.md save subagent prompt forbids `<<`
- [ ] **Step 4.4**: `test_cleanup_intents_deterministic` — verify new action works
- [ ] Verification: 2 independent rounds

## Files Changed

| File | Changes |
|------|---------|
| hooks/scripts/memory_write.py | cleanup-intents action, write-staging action, write-save-result-direct |
| skills/memory-management/SKILL.md | Phase 0 script call, Phase 1.5 script-based writes, Phase 3 direct save-result |
| agents/memory-drafter.md | Return JSON as output instead of Write tool |
| hooks/scripts/memory_write_guard.py | Remove staging auto-approve (no longer needed) |
| tests/ | New regression tests |

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Script writes over Write tool | Platform limitation: `.claude/` protected directory cannot be bypassed by hooks or settings |
| Return-JSON drafter over file-writing drafter | Eliminates Write tool dependency; drafter only needs Read tool |
| Direct CLI args for save-result | Eliminates the Write-then-Bash two-step that haiku models break |
