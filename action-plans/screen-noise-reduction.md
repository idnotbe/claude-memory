---
status: not-started
progress: "Not started"
---

# Screen Noise Reduction — Action Plan

**V-R1/R2 NOTE**: Gemini and holistic reviewer recommend SKIPPING this plan's SKILL.md changes and fast-tracking architecture-simplification.md instead. The architecture rewrite natively resolves screen noise. Only Phase 1 Step 1.3 (triage message verbosity) is independent and should proceed regardless. Other SKILL.md changes here would be throwaway work.

Each auto-capture save produces ~26 visible tool call outputs. With re-fire loop (fixed in separate plan), this balloons to ~78+. Even after re-fire fix, the base ~26 items are excessive. User sees: triage block message, skill load, ~20 intermediate tool calls, and final summary. Only ~3 items are useful.

## Noise Inventory (Single Fire)

| # | Output Item | Useful? | Approach |
|---|-------------|---------|----------|
| 1 | Triage block message (categories + scores) | Yes | Keep but shorten |
| 2 | `<triage_data>` JSON or `<triage_data_file>` tag | Machine-only | Remove from visible output |
| 3 | Skill loading "Successfully loaded skill" | No | Platform control |
| 4 | Phase 0: python3 cleanup + output | No | Absorbed by script (Phase 1 of popup fix plan) |
| 5-8 | Phase 0: triage-data read, config read | No | Consolidate |
| 9-10 | Phase 1: Agent subagent spawn + completion | Low | Background |
| 11-16 | Phase 1.5: intent reads, new-info writes, candidate runs, draft runs | No | Consolidate into fewer Bash calls |
| 14 | CUD resolution reasoning | No | Suppress in SKILL.md |
| 17-18 | Phase 2: verification subagent spawn + completion | Low | Optional / background |
| 19-25 | Phase 3: command building, save subagent, writes, cleanup | No | Single subagent already |
| 26 | Final summary "Saved: session_summary (create)" | Yes | Keep |

## Phases

### Phase 1: Quick Wins (SKILL.md changes only) [ ]
- [ ] **Step 1.1**: Suppress CUD resolution reasoning. Add to SKILL.md: "Do NOT output CUD resolution reasoning. Silently resolve and proceed."
- [ ] **Step 1.2**: Suppress Phase 1.5 intermediate status. Add: "Do NOT narrate Phase 1.5 steps. Silently collect intents, run candidates, resolve CUDs, and assemble drafts."
- [ ] **Step 1.3**: Reduce triage block message verbosity. In `memory_triage.py:format_block_message()`, remove `<triage_data>` inline JSON from visible output. Keep only `<triage_data_file>` reference (machine-readable).
- [ ] **Step 1.4**: Add final-only output rule: "After Phase 3, output ONLY the save summary line. No intermediate status messages."

### Phase 2: Consolidate Tool Calls [ ]
- [ ] **Step 2.1**: Phase 1.5 consolidation: combine multiple independent Bash calls (candidate.py runs) into a single Bash call with `;` separators. Currently each category spawns a separate Bash call.
- [ ] **Step 2.2**: Phase 1.5 file writes: if using script-based staging writes (from popup fix plan), combine multiple write-staging calls into a single Bash call.
- [ ] **Step 2.3**: Phase 3 save: already uses single subagent. Ensure subagent combines ALL commands into 1-2 Bash calls max.

### Phase 3: Reduce Subagent Visibility [ ]
- [ ] **Step 3.1**: Run Phase 1 drafter subagents with `run_in_background: true` if Claude Code supports this for Agent tools. This hides their tool calls from main output.
- [ ] **Step 3.2**: Make Phase 2 verification optional (config flag `triage.parallel.verification_enabled`, default: true). When disabled, skip verification subagents entirely (significant noise reduction).
- [ ] **Step 3.3**: Consider eliminating Phase 2 verification for session_summary category (low risk, high frequency). Keep verification only for decision and constraint (high value, low frequency).

### Phase 4: Tests [ ]
- [ ] **Step 4.1**: `test_no_cud_narration_in_skill` — verify SKILL.md suppresses CUD reasoning
- [ ] **Step 4.2**: `test_triage_message_no_inline_json` — verify inline `<triage_data>` is not in block message when file path is available
- [ ] Verification: 1 round

## Metrics

Target: < 10 visible items per save flow (currently ~26).
- Triage message (shortened): 1
- Skill load: 1 (platform, can't control)
- Background drafter: 1 spawn notice
- Save summary: 1
- Total: ~4 visible items

## Files Changed

| File | Changes |
|------|---------|
| skills/memory-management/SKILL.md | Suppress CUD narration, intermediate status, final-only output rule |
| hooks/scripts/memory_triage.py | Remove inline `<triage_data>` from block message |
| tests/ | New regression tests |
