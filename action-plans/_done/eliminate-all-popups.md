---
status: done
progress: "All 4 phases complete. P1: cleanup-intents action. P2: write-save-result-direct action. P3: staging moved to /tmp/. P4: 37 regression tests. 2 rounds of verification with security hardening (symlink squat defense). 1198 tests pass."
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

### Phase 1: Fix P1 — Replace python3 -c with Script Action [v]
- [v] **Step 1.1**: Add `--action cleanup-intents` to `memory_write.py`. Implementation: `glob.glob(staging_dir + '/intent-*.json')` → `os.remove()` each. Return JSON status.
- [v] **Step 1.2**: Update SKILL.md Phase 0 Step 0. Replace inline `python3 -c "import glob,os..."` with `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action cleanup-intents --staging-dir .claude/memory/.staging`.
- [v] **Step 1.3**: Update Rule 0 to explicitly forbid `python3 -c` for ALL file operations (not just `.claude` paths).
- [v] **Step 1.4**: Add test: `test_cleanup_intents_action` — verify cleanup-intents removes intent-*.json, doesn't remove other staging files.

### Phase 2: Fix P2 — Prevent Haiku Heredoc [v]
- [v] **Step 2.1**: Strengthen SKILL.md Phase 3 save subagent prompt. Add: "CRITICAL: Using heredoc (<<) or cat with redirect will trigger a permission popup and block the save. You MUST use Write tool for file content and python3 scripts for commands."
- [v] **Step 2.2**: Add `--action write-save-result-direct` to `memory_write.py` that takes the result JSON via `--categories` and `--titles` CLI args instead of requiring a file. This eliminates the need for the subagent to write a JSON file at all.
- [v] **Step 2.3**: Update SKILL.md Phase 3 save subagent prompt to use the new direct action instead of the Write-then-Bash two-step.
- [v] **Step 2.4**: Add test: `test_write_save_result_direct` — verify direct action works.

### Phase 3: Fix P3 — Eliminate Write Tool for Staging Files [v]

The `.claude/` protected directory check is a platform limitation. Three workaround options evaluated:

**Option C (INVESTIGATED — PermissionRequest hook)**
- ~~Investigated: PermissionRequest hook does not bypass `.claude/` protected directory checks. Proceeded to Option B.~~

**Option B (IMPLEMENTED): Move staging outside .claude/**
- [v] **Step 3.1**: Move staging from `.claude/memory/.staging/` to `/tmp/.claude-memory-staging-<project-hash>/`
- [v] **Step 3.2**: Create staging dir in `memory_triage.py` with deterministic hash via `memory_staging_utils.py`. O_NOFOLLOW used on most staging file creates (symlink attack defense).
- [v] **Step 3.3**: Updated all 8 scripts handling staging paths + SKILL.md + `agents/memory-drafter.md`.
- [v] **Step 3.4**: Updated `memory_write_guard.py` — added `/tmp/` staging auto-approve; legacy `.staging/` auto-approve retained as compatibility code.
- [v] **Step 3.5**: Updated `memory_staging_guard.py` to guard new `/tmp/` path.
- [v] **Step 3.6**: N/A — `/tmp/` paths don't need `.gitignore` exclusion.

**Option A (FALLBACK): Not needed**
- ~~Option B succeeded. Option A was not implemented.~~

### Phase 4: Regression Tests [v]
- [v] **Step 4.1**: `test_zero_write_tool_calls_for_staging` — verify SKILL.md never instructs Write tool for `.staging/` paths
- [v] **Step 4.2**: `test_no_python3_c_in_skill` — verify SKILL.md has zero `python3 -c` commands
- [v] **Step 4.3**: `test_no_heredoc_in_skill` — verify SKILL.md save subagent prompt forbids `<<`
- [v] **Step 4.4**: `test_cleanup_intents_deterministic` — verify new action works
- [v] Verification: 2 independent rounds

## Files Changed

| File | Changes |
|------|---------|
| hooks/scripts/memory_write.py | cleanup-intents action, write-save-result-direct action |
| hooks/scripts/memory_staging_utils.py | New shared staging path utility (deterministic `/tmp/` staging dir) |
| hooks/scripts/memory_triage.py | Staging output moved to `/tmp/`, O_NOFOLLOW on file creates |
| hooks/scripts/memory_draft.py | Staging reads/writes updated to `/tmp/` paths |
| hooks/scripts/memory_write_guard.py | Added `/tmp/` staging auto-approve; legacy `.staging/` auto-approve retained |
| hooks/scripts/memory_staging_guard.py | Updated to guard `/tmp/` staging path |
| hooks/scripts/memory_validate_hook.py | Updated staging exclusion to `/tmp/` paths |
| hooks/scripts/memory_retrieve.py | Updated staging path references |
| skills/memory-management/SKILL.md | Phase 0 script call, `/tmp/` staging paths, Phase 3 direct save-result, heredoc warning |
| agents/memory-drafter.md | Write to `/tmp/` staging instead of `.claude/memory/.staging/` |
| tests/ | 37 regression tests in `test_regression_popups.py` + unit tests across 4 files |

## Decision Log

| Decision | Rationale |
|----------|-----------|
| `/tmp/` staging over `.claude/` staging (Option B) | Platform limitation: `.claude/` protected directory cannot be bypassed by hooks or settings. `/tmp/` avoids this entirely. |
| Write tool to `/tmp/` staging (drafter) | Drafter still uses Write tool — `/tmp/` paths avoid `.claude/` protected directory checks, preserving simple architecture |
| Direct CLI args for save-result | Eliminates the Write-then-Bash two-step that haiku models break |
| O_NOFOLLOW on staging file creates | `/tmp/` is a shared directory; symlink squatting defense required (V-R2 finding) |

## Implementation Notes (added 2026-03-22)

- **Option B chosen** (move staging to `/tmp/`) to bypass Claude Code's hardcoded `.claude/` protected directory checks. Option C (PermissionRequest hook) investigated first but cannot override the platform-level check. Option A (route all writes through Python) was not needed.
- **Staging path:** `/tmp/.claude-memory-staging-<project-hash>/` via deterministic hash in `memory_staging_utils.py`
- **8 scripts handling staging paths updated:** `memory_triage.py`, `memory_write.py`, `memory_draft.py`, `memory_staging_utils.py`, `memory_write_guard.py`, `memory_retrieve.py`, `memory_validate_hook.py`, `memory_staging_guard.py`
- **Security hardening:** O_NOFOLLOW on most staging file creates for symlink squatting defense. Exception: `write_save_result()` uses `atomic_write_text()` (mkstemp + rename), relying on O_EXCL rather than O_NOFOLLOW.
- **Legacy `.staging/` auto-approve** in `memory_write_guard.py` retained as compatibility code (low-priority cleanup)
- **Known follow-up issues** discovered during progress audit:
  - macOS: `/tmp` → `/private/tmp` resolution breaks `startswith("/tmp/")` validation gates
  - Triage fallback: `_run_triage()` catches `ensure_staging_dir()` failure but reuses rejected path via `get_staging_dir()`
  - `validate_staging_dir()` lacks `S_ISDIR` check on existing paths
- **Audit trail:** See `temp/audit-synthesis.md`, `temp/cross-model-analysis.md` for full records
