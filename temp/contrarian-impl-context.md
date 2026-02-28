# V2 Contrarian Findings Implementation Context

**Date:** 2026-02-28
**Source:** `temp/v2-contrarian-review.md` (222 lines, 8 findings)
**Action Plan:** `action-plans/plan-memory-save-noise-reduction.md`

---

## Scope: 5 Findings to Implement

### Finding 2: Orphan Crash Recovery (memory_retrieve.py)
**Problem:** If Phase 2 subagent crashes (OOM, timeout), `triage-data.json` + `context-*.txt` + `.triage-handled` persist, but no `last-save-result.json` or `.triage-pending.json` exists. User gets zero feedback.

**Implementation:**
- In `memory_retrieve.py` `main()`, BEFORE line 422 (before `if len(user_prompt.strip()) < 10:`)
- After config loading (~line 420), insert orphan detection
- Check: `triage-data.json` exists AND `last-save-result.json` does NOT exist AND `.triage-pending.json` does NOT exist
- If file is >5 min old (not mid-save): print `<memory-note>` notification
- This is forward-compatible: triage-data.json won't exist until Phase 1 of the action plan is implemented

### Finding 3: Noise Estimate Correction (plan only — already done)
The action plan table was already updated to show per-category-count estimates. No code change needed.

### Finding 4: Cross-Project Confirmation Limitation
**Problem:** `last-save-result.json` in `.claude/memory/.staging/` is project-local. If user saves in Project-X then opens Project-Y, confirmation never displays.

**Options:**
- (a) Move to global path `~/.claude/last-save-result.json` + include project path in JSON
- (b) Document as known limitation

**Decision:** Implement option (a) — global path with project disambiguation. This is more robust.
- Write to `~/.claude/last-save-result.json` (includes `project` field with cwd)
- Read from global path in memory_retrieve.py
- If project in result matches current project, show detailed confirmation
- If project differs, show brief note: "Memories saved in project: <name>"

### Finding 5: Agent Hook Lifecycle (plan only — already done)
Phase 5a in the action plan was already clarified with correct lifecycle model. No code change.

### Finding 8: /memory:save Fresh Save Resume
**Problem:** `/memory:save` has no implementation path for resuming from pending state. SKILL.md doesn't know how to skip Phase 0 and reuse existing context files.

**Implementation:** In SKILL.md, add a pre-Phase 0 check:
- If `.staging/.triage-pending.json` exists OR orphaned `triage-data.json` exists:
  - Clean up ALL stale staging files (triage-data.json, context-*.txt, .triage-handled, .triage-pending.json)
  - Proceed with normal fresh triage → save pipeline
  - Do NOT attempt to resume from stale context
- Rationale: Pre-existing context files' staleness is uncertain; session_summary can't be regenerated without original transcript

---

## Key File Locations

| File | Lines | What to change |
|------|-------|---------------|
| `hooks/scripts/memory_retrieve.py` | Before line 422 | Orphan detection, save confirmation (global path), pending detection |
| `skills/memory-management/SKILL.md` | Before Phase 0 (~line 38) | Fresh save pre-check, staging cleanup |
| `tests/test_memory_retrieve.py` | New tests | Orphan detection, global result file handling |

## Current memory_retrieve.py Structure (lines 408-430)

```python
# Line 412: memory_root = Path(cwd) / ".claude" / "memory"
# Lines 414-420: Config loading from memory-config.json
# Line 422: if len(user_prompt.strip()) < 10:  # Short prompt check
# Line 429: sys.exit(0)  # Early exit for short prompts
# Line 431+: Index loading, search, etc.
```

**INSERT POINT: Between line 420 (config loading end) and line 422 (short prompt check)**

All new code (orphan detection, save confirmation, pending detection) must go here so it fires for ALL prompts, including short ones.

## Important Constraints

1. All staging paths use `memory_root / ".staging" / "filename"`
2. Global result path: `~/.claude/last-save-result.json`
3. Use `<memory-note>` tags for user-facing output (consistent with existing pattern)
4. Fail-open: any read errors → silently skip (don't crash the hook)
5. Import `time` for staleness checks (already imported in memory_retrieve.py)
6. Must be backwards-compatible: code is harmless when staging files don't exist yet
