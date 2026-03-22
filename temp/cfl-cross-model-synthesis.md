# Cross-Model Synthesis: Closed Feedback Loop Design

## Models Consulted
- **Opus 4.6** (self/vibe-check): Directionally strong, risk of over-engineering, focus on minimal viable loop first
- **Codex 5.3** (planner role): Most thorough. Reviewed actual ops logs, found promotion is the real gap, not observability. 5-phase plan.
- **Gemini 3.1 Pro** (planner role): PTY harness critical insight, "Shadow Loop" concept, global telemetry bridge.

## Universal Agreement (All 3 Models)
1. **Direction is correct** but risk of building too much too early
2. **`claude --print` hook behavior needs validation** — may not trigger Stop hooks in non-interactive mode
3. **prd.json should NOT be mutable source of truth** — immutable reqs + derived status views
4. **Deterministic oracles primary; LLM judging for explanation only** — not pass/fail
5. **Workspace/memory isolation per test run** is critical to prevent contamination
6. **Pytest requirement markers** are the right approach for Tier 1 verification
7. **Start simple** → evidence collection → promotion → traceability → auto-fix (graduated phases)

## Unique Insights by Model

### Codex 5.3 (Strongest Overall Analysis)
- **Key finding**: Real ops logs (2026-03-21/22) already contain actionable data. The analyzer found high findings for CONSTRAINT/PREFERENCE never triggering + perf regression.
- **Core insight**: Missing piece is PROMOTION from repo B → repo A, not raw observability.
- **Scenario registry concept**: ids + prompts + repo target + expected/forbidden signals + requirement ids
- **Evidence contract**: Stable schema for scenario runs so failures are replayable across plugin/Claude versions
- **5-phase plan**: Evidence Contract → Minimal Loop → Cross-Repo Promotion → Req Traceability → Optional Ralph Loop
- **Key risk**: Cross-run memory contamination makes results meaningless

### Gemini 3.1 Pro (Critical Infrastructure Insights)
- **PTY/pexpect harness** instead of `claude --print` — hooks may not fire in non-interactive mode
- **"Shadow Loop"** concept: Generate .patch files for review instead of autonomous fixing (safer)
- **Global telemetry bridge**: Plugin writes to `~/.claude/plugins/claude-memory-logs/telemetry.jsonl` regardless of repo
- **Drop prd.json entirely**: Use pytest JSON reporters mapped to markdown PRD dynamically
- **Blast radius risk**: If test loop modifies globally installed plugin, bad fix breaks production (repo B) instantly

### Opus 4.6 (Vibe Check)
- Two-tier req verification is the right framing
- Complex solution bias warning — research doc doesn't need the same rigor as production code
- Scope creep risk: separate loop mechanism, req verification, and test mapping as distinct concerns

## Key Disagreements / Tensions

| Topic | Codex | Gemini | Resolution |
|-------|-------|--------|------------|
| Live verification method | `claude -p` (validated it works locally) | pexpect PTY (hooks may not fire) | **Test both**. Spike first. |
| prd.json | Keep as derived artifact | Drop entirely | **Derived artifact** — generate from pytest results |
| Auto-fix | Phase 5 after signals stable | Shadow Loop (patches only) | **Shadow Loop first**, optional auto-fix later |
| Telemetry source | Per-repo logs already exist | Global telemetry bridge | **Per-repo logs + cross-repo exporter** |
| Primary loop location | Repo B → Repo A promotion | Repo A isolated E2E runs | **Both** — Tier 1 in Repo A, Tier 2 can target either |
