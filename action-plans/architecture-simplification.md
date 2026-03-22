---
status: not-started
progress: "Not started"
---

# Architecture Simplification — Action Plan

Current 5-phase save orchestration (Pre-Phase, Phase 0, 1, 1.5, 2, 3) with 3 subagent types (drafter, verifier, saver) is the root cause of screen noise, slow saves (17-28 min), high token cost, and complexity-driven bugs. This plan proposes collapsing to 3 phases with 1 subagent type.

## Current Architecture Problems

| Problem | Cause | Impact |
|---------|-------|--------|
| 17-28 min save time | 5 serial phases, 2 subagent waves (draft + verify), each with cold-start | User waits, re-fire loop triggered by TTL expiry |
| ~26 visible tool calls | Each phase has multiple Read/Write/Bash/Agent calls | Screen noise |
| 3 subagent types | memory-drafter (Agent), verifier (Agent), saver (Task) | Complex orchestration, model compliance issues (haiku heredoc) |
| Mixed execution models | Hook (deterministic) → Skill (LLM-interpreted) → Subagent (LLM) → Script (deterministic) | Inconsistent error handling, hard to debug |
| Verification always-on | Phase 2 verifier spawns for every category | Doubles subagent cost with marginal quality improvement |
| Phase 1.5 is LLM-orchestrated but deterministic | CUD resolution, candidate selection are mechanical rules executed by LLM reading SKILL.md | Unnecessary LLM hop, error-prone |

## Proposed Architecture: 3 Phases

```
CURRENT (5 phases, 3 subagent types, 17-28 min):
  Stop hook → SKILL.md → Pre-Phase cleanup
    → Phase 0 parse → Phase 1 draft (Agent×N)
    → Phase 1.5 CUD (main agent) → Phase 2 verify (Agent×N)
    → Phase 3 save (Task×1) → cleanup

PROPOSED (2 phases + setup, 1 subagent type, target 3-8 min):
  Stop hook → SKILL.md → SETUP (deterministic: parse triage, cleanup)
    → Phase 1 DRAFT (Agent×1 or Agent×N)
    → Phase 2 COMMIT (deterministic script)
```

**V-R1/R2 CRITICAL FIX**: Original design had DETECT running candidate selection before DRAFT, but candidate selection needs `new_info_summary` from drafters. Fixed: SETUP only parses triage data and cleans stale files. Candidate selection and CUD resolution move AFTER drafting into the COMMIT script.

### SETUP (deterministic, no LLM)
- Parse triage data (already done in hook)
- Clean stale intent files (`memory_write.py --action cleanup-intents`)
- Output: categories to process + config
- Lightweight: single script call, < 1s

### Phase 1: DRAFT (LLM, single subagent wave)
- **Option A**: Single drafter agent for ALL categories (Gemini suggestion: feed all context files to one agent, return JSON with all category intents). Lower latency, fewer cold-starts.
- **Option B**: Per-category drafter agents (current approach). Better isolation, parallel execution.
- Drafters return structured JSON (intent files)
- Verification is OPTIONAL (config flag `triage.parallel.verification_enabled`, default: true only for decision/constraint)

### Phase 2: COMMIT (deterministic, no LLM)
- Read intent files → run candidate selection → CUD resolution (all in one script)
- Draft assembly (`memory_draft.py`)
- Save (`memory_write.py`)
- Enforce (`memory_enforce.py`)
- Cleanup + result file
- Implementation: single Python script `memory_commit.py` or `memory_write.py --action commit-all`

## Phases of This Plan

### Phase 1: Design [ ]
- [ ] **Step 1.1**: Design `memory_detect.py` — input: triage-data.json path. Output: detection-result.json with per-category resolved actions and candidate info.
- [ ] **Step 1.2**: Design COMMIT script flow — input: list of draft paths + resolved actions. Output: save results. Single Bash call chaining memory_draft.py → memory_write.py → memory_enforce.py → cleanup.
- [ ] **Step 1.3**: Design verification opt-out config: `triage.parallel.verification_enabled` (default: true), `triage.parallel.verification_categories` (default: ["decision", "constraint"]).
- [ ] **Step 1.4**: Cross-model review of design (Codex + Gemini).

### Phase 2: Implement DETECT Script [ ]
- [ ] **Step 2.1**: Create `hooks/scripts/memory_detect.py` — absorbs Phase 0 cleanup + Phase 1.5 Steps 1-4 (intent collection, candidate selection, CUD resolution, draft assembly input).
- [ ] **Step 2.2**: Tests for memory_detect.py.

### Phase 3: Implement COMMIT Script [ ]
- [ ] **Step 3.1**: Create `hooks/scripts/memory_commit.py` or extend `memory_write.py` with `--action commit-drafts` — absorbs Phase 3 Steps 1-2 (save commands, cleanup, result file).
- [ ] **Step 3.2**: Tests for commit flow.

### Phase 4: Update SKILL.md [ ]
- [ ] **Step 4.1**: Rewrite SKILL.md to 3-phase flow. Dramatically simpler instructions.
- [ ] **Step 4.2**: Update CLAUDE.md architecture table.
- [ ] **Step 4.3**: Make verification conditional per config.

### Phase 5: Integration Testing [ ]
- [ ] **Step 5.1**: End-to-end test with 1-category save.
- [ ] **Step 5.2**: End-to-end test with multi-category save.
- [ ] **Step 5.3**: Performance benchmark: measure save time before/after.
- [ ] Verification: 2 independent rounds.

## Expected Improvements

| Metric | Current | Target |
|--------|---------|--------|
| Save time | 17-28 min | 3-8 min |
| Visible tool calls | ~26 | ~6-8 |
| Subagent spawns | 3-6 (draft + verify + save) | 1-2 (draft only) |
| Token cost | ~220k tokens/save | ~80k tokens/save |
| SKILL.md instructions | ~300 lines | ~100 lines |

## Dependencies

- fix-stop-hook-refire.md (P0, Phase 1 should complete first)
- eliminate-all-popups.md (P0, write-staging approach feeds into this)

## Risks

| Risk | Mitigation |
|------|------------|
| Removing verification reduces quality | Config flag; keep for high-value categories (decision, constraint) |
| DETECT script may miss edge cases in CUD resolution | Port exact same logic from SKILL.md; extensive test coverage |
| Breaking change to SKILL.md | Version the SKILL.md and test before deploying |

## Files Changed

| File | Changes |
|------|---------|
| hooks/scripts/memory_detect.py | NEW: absorbs Phase 0 + Phase 1.5 |
| hooks/scripts/memory_commit.py | NEW: absorbs Phase 3 |
| skills/memory-management/SKILL.md | Major rewrite to 3-phase flow |
| CLAUDE.md | Update architecture table |
| tests/ | New integration tests |
