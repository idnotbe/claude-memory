# Minimal Fix Analysis

## Noise Sources Breakdown

Looking at the actual user screenshot, the noise comes from 3 distinct sources:

### Source 1: Stop Hook Reason (~20-30 visible lines)
```
Stop hook error: The following items should be saved...
- [SESSION_SUMMARY] (description) metrics (score: 1.00)
Use the memory-management skill...
<triage_data>
{ "categories": [...], "parallel_config": {...} }   ← ~20 lines of JSON
</triage_data>
```
**Root cause**: `format_block_message()` inlines the entire triage_data JSON in the reason field.
**Minimal fix**: Write triage_data to a staging file, reference it by path in the reason. The reason becomes 3 lines instead of 25+.

### Source 2: Phase 1/2 Subagent Spawn Lines (~2-4 lines each)
```
● Task(Draft session_summary memory) Haiku 4.5
  ⎿  Done (5 tool uses · 76.8k tokens · 22s)
```
**Assessment**: This is actually MINIMAL noise. Subagent internals are already hidden (context-isolated). Just the spawn/complete line is shown. This is acceptable.

### Source 3: Phase 3 Save Operations (~30-50 visible lines)
```
● Read 1 file
● Write(.claude/memory/.staging/new-info-...)    ← error
● Bash(python3 memory_candidate.py ...)           ← output shown
● Read 1 file
● Bash(python3 memory_draft.py ...)               ← output shown
● Read 1 file
● Bash(md5sum ...)                                ← output shown
● Bash(python3 memory_write.py ...)               ← output shown
● Bash(python3 memory_enforce.py ...)             ← output shown
```
**Root cause**: The MAIN agent performs Phase 3 save operations directly, each producing visible tool call output.
**Minimal fix**: Move Phase 3 into a SINGLE foreground subagent that does all the saving internally.

### Source 4: Error Handling / Retries (variable)
The user screenshot shows "subagent misinterpreted the veto" and multiple retries. This is the WORST noise — unpredictable and very verbose.
**Root cause**: Complex multi-step flow with error-prone hand-offs.
**Minimal fix**: Consolidate the entire pipeline into a single agent that handles errors internally.

## Minimal Fix Summary

Two changes that would eliminate ~80% of visible noise:

### Fix A: Externalize triage_data (Python change)
- In `format_block_message()`: write triage_data to `.staging/triage-data.json`
- Return reason as: "Save 1 memory (session_summary). Triage data: .claude/memory/.staging/triage-data.json"
- SKILL.md reads triage file instead of parsing inline JSON
- **Effort**: ~20 lines of Python change
- **Impact**: Eliminates ~20 lines of visible JSON

### Fix B: Single Consolidated Save Agent
- After Phase 1/2 subagents complete (already context-isolated), spawn ONE foreground subagent for Phase 3
- This subagent reads all draft files, does verification, and executes ALL save operations internally
- Main agent sees only: "Task(Save memories) → Done (8 tool uses · 40k tokens · 15s)"
- **Effort**: SKILL.md restructure + possibly a dedicated .claude/agents/ save agent
- **Impact**: Eliminates ~30-50 lines of tool call output + error handling noise

### Combined Effect
Before: ~70-100+ visible lines
After Fix A+B: ~8-12 visible lines (hook message + 2-3 subagent spawn/complete lines)

## Token Context Impact
- Fix A: Saves ~500 tokens from reason field in main context
- Fix B: Saves ~2000-3000 tokens from Phase 3 operations
- Net: Main context sees ~3000 fewer tokens per save cycle
- This delay /compact by roughly 1.5-2% of context window capacity
