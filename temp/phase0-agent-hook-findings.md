# Phase 0: Agent Hook Findings

**Date:** 2026-02-28
**Status:** Partial — docs reviewed, empirical test pending (requires separate session)

## Confirmed from Official Docs (code.claude.com/docs/en/hooks)

### 1. `type: "agent"` IS supported for Stop hooks
- Events supporting all 3 types (command, prompt, agent): `Stop`, `SubagentStop`, `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `UserPromptSubmit`, `TaskCompleted`
- `SessionStart`, `SessionEnd`, `Notification`, etc. are command-only

### 2. Agent Hook Mechanics
- Spawns a **subagent** with tool access (Read, Grep, Glob — "like" these, non-exhaustive)
- Up to **50 turns** of tool use
- Default timeout: **60 seconds** (configurable)
- Example in docs: "Run the test suite" — implies Bash access

### 3. Return Schema
- `{ "ok": true }` → allows stop (session exits)
- `{ "ok": false, "reason": "..." }` → blocks stop (reason becomes Claude's next instruction)
- Same as prompt hooks

### 4. $ARGUMENTS
- Available via `$ARGUMENTS` placeholder in prompt
- Hook input JSON is injected (same as command hooks receive via stdin)

### 5. Configuration Example (from docs)
```json
{
  "type": "agent",
  "prompt": "Verify that all unit tests pass. Run the test suite and check the results. $ARGUMENTS",
  "timeout": 120
}
```

## CRITICAL UNKNOWN: Subagent Isolation
**NOT documented.** The docs do not explicitly state whether agent hook subagent tool calls appear in the parent session's transcript.

This is THE question Phase 0 was designed to answer. Without empirical testing, we cannot determine:
- Whether the agent hook approach achieves zero noise
- Whether Phase 5a is viable

## Why Empirical Test Can't Run in Current Session
1. Hooks are loaded at session start — changes to hooks.json require restart
2. Stop hooks fire when session ends — can't observe results from within same session
3. Need separate Claude Code session with modified hooks.json

## Prepared Experiment Configs
See `temp/phase0-experiment-configs.md` for 4 ready-to-run experiment configurations.

## Decision: Skip to Phase 1
Per action plan: "Fix A+B를 먼저 구현하고 실험을 나중에 진행해도 무방"
- Phase 0 experiment requires manual testing in separate sessions
- Fix A+B (Phase 1+2) are the primary path regardless of Phase 0 results
- Phase 0 results only determine Phase 5a viability (optional enhancement)

**Proceed to Phase 1 now. Phase 0 experiment can be run later.**
