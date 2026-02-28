# Memory Save UI Noise Problem

## Problem
When claude-memory's Stop hook triggers, the memory save process produces extensive visible output:
1. Stop hook triage output with full `<triage_data>` JSON (20+ lines)
2. Task subagent spawning for draft/verify (multiple agents)
3. Multiple Bash calls (memory_candidate.py, memory_draft.py, memory_write.py, memory_enforce.py)
4. Intermediate read/write operations on staging files
5. Error messages and retries

## Impact
- User must scroll past 50-100+ lines of memory operations to see original conversation
- If memory save is verbose enough, /compact triggers and earlier conversation context is lost permanently
- Breaks flow — user's mental model is "session ending" but sees a wall of internal operations

## Current Architecture
- Stop hook (command type) returns `{"decision": "block", "reason": "..."}` with full triage_data JSON
- SKILL.md instructs the agent to parse triage_data, spawn Phase 1 (draft) subagents, Phase 2 (verify) subagents, then Phase 3 (save) — all visible in the main agent's output
- Each phase involves multiple tool calls (Read, Write, Bash) that are shown to the user

## Desired State
- Memory save happens with minimal/no visible output
- User sees at most a brief "Memory saved: <title>" confirmation
- No JSON, no intermediate steps, no subagent output visible
- Main conversation context is preserved (no /compact trigger from save noise)

## Research Angles
1. Claude Code hook API — can stop hooks produce less output?
2. Background agents/subagents — can save happen in background?
3. SessionEnd hooks — can save be deferred to after conversation?
4. Custom agent architecture — single consolidated save agent
5. Hook output suppression mechanisms
6. Alternative save orchestration patterns
