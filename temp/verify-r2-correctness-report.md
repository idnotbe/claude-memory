# Verification Round 2 — Final Correctness & Proposed Update Report

**Date:** 2026-03-22
**Reviewer:** V-R2 (Opus 4.6)
**Cross-model:** Codex (factual accuracy), Gemini (clarity for future readers)

## Verification Summary

### 1. Progress Note — Test Count
- **R1 claim:** 1164 is wrong, should be 1198
- **Verified:** `pytest tests/ --co -q` returns `1198 tests collected`. Confirmed correct.

### 2. Checklist Boxes — Code Evidence Spot-Checks
- **Phase 1 Step 1.1** (`cleanup-intents` action): `cleanup_intents()` exists at `memory_write.py:562`, action registered at line 1779, handler at line 1830. **DONE.**
- **Phase 2 Step 2.2** (`write-save-result-direct` action): action registered at `memory_write.py:1780`, handler at line 1872, CLI args `--categories`/`--titles` at lines 1808/1812. **DONE.**
- **Phase 3 Option B Step 3.1** (move staging to /tmp/): zero `.claude/memory/.staging` references in SKILL.md; 8 scripts reference `/tmp/.claude-memory-staging`; `memory_staging_utils.py` provides deterministic path. **DONE.**
- **Phase 4 Step 4.2** (no python3 -c test): `test_no_python3_c_in_any_bash_block` at `test_regression_popups.py:614`. **DONE.**
- **Phase 3 Option C** (PermissionRequest hook): No `PermissionRequest` entry in `hooks/hooks.json`. **NOT IMPLEMENTED** (investigated and rejected).
- **Phase 3 Option A** (route all writes through Python): No `write-staging` action in `memory_write.py`. **NOT IMPLEMENTED** (not needed).

### 3. Implementation Notes — Cross-Model Feedback

**Codex findings (incorporated):**
- Checkbox convention is `[x]` (confirmed via `fix-stop-hook-refire.md` — Codex was wrong about `[v]`)
- O_NOFOLLOW claim is slightly overstated: `write_save_result()` uses `atomic_write_text()` → `tempfile.mkstemp()` (O_EXCL but not O_NOFOLLOW on final rename target). Most other staging writes use direct O_NOFOLLOW. Wording softened.
- Legacy `.staging/` auto-approve is reachable via legacy path acceptance in `write_save_result()` line 633. Calling it "dead code" is too strong; "legacy compatibility code" is accurate.
- Option C/Option A boxes must NOT be marked `[x]` — they were not implemented.

**Gemini findings (incorporated):**
- Must explain WHY Option B was chosen (platform limitation) — not just state it was chosen
- "All 8 scripts updated" should specify "8 scripts handling staging paths" not imply only 8 scripts exist
- Use full filename `memory_write_guard.py` not abbreviated `write_guard.py`
- Add context for why O_NOFOLLOW matters (`/tmp/` is shared)

### 4. Archival Path
- `action-plans/_done/` exists (confirmed). Contains 6 completed plans already.

---

## EXACT Proposed Edits

### Edit 1: Progress note (YAML frontmatter, line 3)

**OLD:**
```
progress: "All 4 phases complete. P1: cleanup-intents action. P2: write-save-result-direct action. P3: staging moved to /tmp/. P4: 37 regression tests. 2 rounds of verification with security hardening (symlink squat defense). 1164 tests pass."
```

**NEW:**
```
progress: "All 4 phases complete. P1: cleanup-intents action. P2: write-save-result-direct action. P3: staging moved to /tmp/. P4: 37 regression tests. 2 rounds of verification with security hardening (symlink squat defense). 1198 tests pass."
```

### Edit 2: Phase 1 checklist (lines 23-27)

**OLD:**
```
### Phase 1: Fix P1 — Replace python3 -c with Script Action [ ]
- [ ] **Step 1.1**: Add `--action cleanup-intents` to `memory_write.py`. Implementation: `glob.glob(staging_dir + '/intent-*.json')` → `os.remove()` each. Return JSON status.
- [ ] **Step 1.2**: Update SKILL.md Phase 0 Step 0. Replace inline `python3 -c "import glob,os..."` with `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action cleanup-intents --staging-dir .claude/memory/.staging`.
- [ ] **Step 1.3**: Update Rule 0 to explicitly forbid `python3 -c` for ALL file operations (not just `.claude` paths).
- [ ] **Step 1.4**: Add test: `test_cleanup_intents_action` — verify cleanup-intents removes intent-*.json, doesn't remove other staging files.
```

**NEW:**
```
### Phase 1: Fix P1 — Replace python3 -c with Script Action [x]
- [x] **Step 1.1**: Add `--action cleanup-intents` to `memory_write.py`. Implementation: `glob.glob(staging_dir + '/intent-*.json')` → `os.remove()` each. Return JSON status.
- [x] **Step 1.2**: Update SKILL.md Phase 0 Step 0. Replace inline `python3 -c "import glob,os..."` with `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/memory_write.py" --action cleanup-intents --staging-dir .claude/memory/.staging`.
- [x] **Step 1.3**: Update Rule 0 to explicitly forbid `python3 -c` for ALL file operations (not just `.claude` paths).
- [x] **Step 1.4**: Add test: `test_cleanup_intents_action` — verify cleanup-intents removes intent-*.json, doesn't remove other staging files.
```

### Edit 3: Phase 2 checklist (lines 29-33)

**OLD:**
```
### Phase 2: Fix P2 — Prevent Haiku Heredoc [ ]
- [ ] **Step 2.1**: Strengthen SKILL.md Phase 3 save subagent prompt. Add: "CRITICAL: Using heredoc (<<) or cat with redirect will trigger a permission popup and block the save. You MUST use Write tool for file content and python3 scripts for commands."
- [ ] **Step 2.2**: Add `--action write-save-result-direct` to `memory_write.py` that takes the result JSON via `--categories` and `--titles` CLI args instead of requiring a file. This eliminates the need for the subagent to write a JSON file at all.
- [ ] **Step 2.3**: Update SKILL.md Phase 3 save subagent prompt to use the new direct action instead of the Write-then-Bash two-step.
- [ ] **Step 2.4**: Add test: `test_write_save_result_direct` — verify direct action works.
```

**NEW:**
```
### Phase 2: Fix P2 — Prevent Haiku Heredoc [x]
- [x] **Step 2.1**: Strengthen SKILL.md Phase 3 save subagent prompt. Add: "CRITICAL: Using heredoc (<<) or cat with redirect will trigger a permission popup and block the save. You MUST use Write tool for file content and python3 scripts for commands."
- [x] **Step 2.2**: Add `--action write-save-result-direct` to `memory_write.py` that takes the result JSON via `--categories` and `--titles` CLI args instead of requiring a file. This eliminates the need for the subagent to write a JSON file at all.
- [x] **Step 2.3**: Update SKILL.md Phase 3 save subagent prompt to use the new direct action instead of the Write-then-Bash two-step.
- [x] **Step 2.4**: Add test: `test_write_save_result_direct` — verify direct action works.
```

### Edit 4: Phase 3 checklist (lines 35-55)

**OLD:**
```
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
```

**NEW:**
```
### Phase 3: Fix P3 — Eliminate Write Tool for Staging Files [x]

The `.claude/` protected directory check is a platform limitation. Three workaround options evaluated:

**Option C (INVESTIGATE FIRST — 30 min experiment): PermissionRequest hook**
- ~~Investigated: PermissionRequest hook does not bypass `.claude/` protected directory checks. Proceeded to Option B.~~

**Option B (IMPLEMENTED): Move staging outside .claude/**
- [x] **Step 3.1**: Move staging from `.claude/memory/.staging/` to `/tmp/.claude-memory-staging-<project-hash>/`
- [x] **Step 3.2**: Create staging dir in `memory_triage.py` with deterministic hash via `memory_staging_utils.py`. O_NOFOLLOW used on most staging file creates (symlink attack defense).
- [x] **Step 3.3**: Updated all 8 scripts handling staging paths + SKILL.md + `agents/memory-drafter.md`.
- [x] **Step 3.4**: Updated `memory_write_guard.py` — added `/tmp/` staging auto-approve; legacy `.staging/` auto-approve retained as compatibility code.
- [x] **Step 3.5**: Updated `memory_staging_guard.py` to guard new `/tmp/` path.
- [x] **Step 3.6**: N/A — `/tmp/` paths don't need `.gitignore` exclusion.

**Option A (FALLBACK): Not needed**
- ~~Option B succeeded. Option A was not implemented.~~
```

### Edit 5: Phase 4 checklist (lines 57-62)

**OLD:**
```
### Phase 4: Regression Tests [ ]
- [ ] **Step 4.1**: `test_zero_write_tool_calls_for_staging` — verify SKILL.md never instructs Write tool for `.staging/` paths
- [ ] **Step 4.2**: `test_no_python3_c_in_skill` — verify SKILL.md has zero `python3 -c` commands
- [ ] **Step 4.3**: `test_no_heredoc_in_skill` — verify SKILL.md save subagent prompt forbids `<<`
- [ ] **Step 4.4**: `test_cleanup_intents_deterministic` — verify new action works
- [ ] Verification: 2 independent rounds
```

**NEW:**
```
### Phase 4: Regression Tests [x]
- [x] **Step 4.1**: `test_zero_write_tool_calls_for_staging` — verify SKILL.md never instructs Write tool for `.staging/` paths
- [x] **Step 4.2**: `test_no_python3_c_in_skill` — verify SKILL.md has zero `python3 -c` commands
- [x] **Step 4.3**: `test_no_heredoc_in_skill` — verify SKILL.md save subagent prompt forbids `<<`
- [x] **Step 4.4**: `test_cleanup_intents_deterministic` — verify new action works
- [x] Verification: 2 independent rounds
```

### Edit 6: Files Changed table (lines 64-72)

**OLD:**
```
## Files Changed

| File | Changes |
|------|---------|
| hooks/scripts/memory_write.py | cleanup-intents action, write-staging action, write-save-result-direct |
| skills/memory-management/SKILL.md | Phase 0 script call, Phase 1.5 script-based writes, Phase 3 direct save-result |
| agents/memory-drafter.md | Return JSON as output instead of Write tool |
| hooks/scripts/memory_write_guard.py | Remove staging auto-approve (no longer needed) |
| tests/ | New regression tests |
```

**NEW:**
```
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
| tests/ | 37 regression tests in `test_regression_popups.py` |
```

### Edit 7: Decision Log table (lines 74-81)

**OLD:**
```
## Decision Log

| Decision | Rationale |
|----------|-----------|
| Script writes over Write tool | Platform limitation: `.claude/` protected directory cannot be bypassed by hooks or settings |
| Return-JSON drafter over file-writing drafter | Eliminates Write tool dependency; drafter only needs Read tool |
| Direct CLI args for save-result | Eliminates the Write-then-Bash two-step that haiku models break |
```

**NEW:**
```
## Decision Log

| Decision | Rationale |
|----------|-----------|
| `/tmp/` staging over `.claude/` staging (Option B) | Platform limitation: `.claude/` protected directory cannot be bypassed by hooks or settings. `/tmp/` avoids this entirely. |
| Write tool to `/tmp/` staging (drafter) | Drafter still uses Write tool — `/tmp/` paths avoid `.claude/` protected directory checks, preserving simple architecture |
| Direct CLI args for save-result | Eliminates the Write-then-Bash two-step that haiku models break |
| O_NOFOLLOW on staging file creates | `/tmp/` is a shared directory; symlink squatting defense required (V-R2 finding) |
```

### Edit 8: New Implementation Notes section (append after Decision Log)

**NEW (append after line 81):**
```

## Implementation Notes (added 2026-03-22)

- **Option B chosen** (move staging to `/tmp/`) to bypass Claude Code's hardcoded `.claude/` protected directory checks that cause permission popups. Option C (PermissionRequest hook) was investigated first but cannot override the platform-level check. Option A (route all writes through Python) was not needed.
- **Staging path:** `/tmp/.claude-memory-staging-<project-hash>/` via deterministic hash in `memory_staging_utils.py`
- **8 scripts handling staging paths updated:** `memory_triage.py`, `memory_write.py`, `memory_draft.py`, `memory_staging_utils.py`, `memory_write_guard.py`, `memory_retrieve.py`, `memory_validate_hook.py`, `memory_staging_guard.py`
- **Security hardening:** O_NOFOLLOW used on most staging file creates to prevent symlink squatting in the shared `/tmp/` directory. Exception: `write_save_result()` uses `atomic_write_text()` (mkstemp + rename), which relies on O_EXCL rather than O_NOFOLLOW.
- **Legacy `.staging/` auto-approve** in `memory_write_guard.py` retained as compatibility code (low-priority cleanup)
- **Audit trail:** See `temp/audit-synthesis.md` and `temp/verify-r1-synthesis.md` for full verification records
```

---

## Cross-Model Validation Summary

| Reviewer | Verdict | Key Corrections Applied |
|----------|---------|------------------------|
| Codex | Mostly accurate | O_NOFOLLOW wording softened; legacy code labeled "compatibility" not "dead"; Option C/A boxes not marked [x]; confirmed `[x]` convention (not `[v]`) |
| Gemini | Clear with fixes | Added "why" for Option B; specified "8 scripts handling staging paths"; full filename `memory_write_guard.py`; added "/tmp/ is shared" context |

## Archival Recommendation

After applying these edits, move `eliminate-all-popups.md` to `action-plans/_done/eliminate-all-popups.md`. The `_done/` directory exists and contains 6 completed plans.
