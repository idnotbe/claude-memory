# Research: Background Agent/Subagent Patterns for Silent Execution

**Date:** 2026-02-28
**Researcher:** background-agent-researcher
**Task:** Research background agent patterns for making claude-memory's save pipeline silent

---

## Executive Summary

Background agents and subagents in Claude Code do NOT solve the UI noise problem. Despite documentation suggesting context isolation, multiple bugs and architectural limitations mean subagent tool calls are visible to the user and their transcripts pollute the parent context window. The correct solution is to move file writes entirely out of the LLM tool loop and into deterministic Python hooks.

---

## Research Findings

### 1. How Background Agents Work

**What the documentation says:**
- Subagents run in their own context window with custom system prompts and independent permissions
- `background: true` in subagent frontmatter lets them run concurrently while the main agent continues
- Background subagents pre-approve permissions, then auto-deny anything not pre-approved
- Results return to the main conversation when the subagent completes

**What actually happens (vs. documented behavior):**

| Expected | Actual |
|----------|--------|
| Only final summary returned to parent | Full execution transcript dumped to parent (Bug #18351) |
| Subagent tool calls isolated from parent context | Tool calls leak directly to parent context (Bug #14118) |
| Silent operation visible only to subagent | Tool executions (Bash, Write) surface in main terminal UI |
| Cheaper model (Haiku) saves costs | All tool calls billed at parent model rate due to context leakage |

### 2. The Context Isolation Reality

**GitHub Issue #14118 (Background Subagent Context Leakage):**
> "When subagents run in background mode, their full internal transcripts are returned to the parent agent instead of just the final summary. 16 background subagents resulted in 5.4 MB of context dumps (94% of parent context). Per-agent overhead: 267-468 KB each."

**GitHub Issue #18351 (Parallel Agent Transcript Dump):**
> Parallel subagents (like the current Phase 1/Phase 2 pattern) frequently dump their entire JSONL execution transcripts back to the parent, which can instantly trigger `/compact` and destroy conversation history.

**Conclusion:** Subagent context isolation is currently broken in Claude Code. Both foreground and background modes expose subagent tool calls in the user's UI.

### 3. Does `background: true` Hide Operations from User?

**Answer: No.**

Setting a task/subagent to background execution only frees the parent agent to continue processing other tasks. The subagent's tool executions (Bash, Write), stdout, and permission requests still interleave into the main terminal UI.

Pressing `Ctrl+B` to background a task:
- Allows the main conversation to continue
- Does NOT suppress tool call display to user
- Results in interleaved output from both main agent and background subagent

### 4. Single Background Save Agent vs. Current 4-Agent Pattern

**Question:** If we spawn ONE background Task agent to handle all 4 phases, does it minimize visible output?

**Answer:** Marginally better, but not silently. Analysis:

**Current pattern (4 parallel agents = 12+ subagent calls total):**
- 6 drafting agents (Phase 1) × visible tool calls each
- 6 verification agents (Phase 2) × visible tool calls each
- Multiplies UI noise by number of agents
- Bug #18351 is more likely to trigger with parallel agents

**Single consolidated save agent:**
- Serializes the output, so noise isn't multiplied
- Reduces orchestrator overhead
- Still generates visible tool logs for every Bash/Write call
- The user still sees all intermediate steps

**Verdict:** Single agent is better than 4 parallel agents (reduces noise multiplication), but it's still not silent.

### 5. Can a Background Agent Access `.claude/memory/`?

**Answer: Yes**, with caveats:
- Background subagents inherit tool permissions from the parent conversation
- They can call Bash, Write, Read, Edit tools (if not restricted)
- Pre-approval happens before the subagent starts (upfront permission prompt)
- The PreToolUse write guard hook would still fire and block direct writes

**Key constraint:** The existing PreToolUse Write guard (`memory_write_guard.py`) would need to be aware that the background subagent is a trusted caller, not a user-initiated write.

### 6. `isolation: "worktree"` Analysis

**What it does:** Creates a temporary git worktree copy of the repository for the subagent to work in. The worktree is cleaned up if the subagent makes no changes.

**For the memory save use case:**
- Memory is stored in `.claude/memory/` which is NOT in the git repo (typically .gitignored)
- A worktree isolation would NOT isolate the memory directory
- Changes to `.claude/memory/` would happen in the real directory regardless
- This provides no benefit for the noise problem

**Verdict:** `isolation: "worktree"` is irrelevant to the memory save problem.

### 7. Teammate Spawning vs. Subagent Spawning: UI Visibility

**Subagents (Task tool):**
- Same session, same UI
- Tool calls visible to user immediately
- Results injected back into main context

**Agent Teams (separate sessions):**
- Run in separate claude instances
- Communicate via SendMessage tool
- Completely separate UI contexts
- Could theoretically be silent, but requires:
  - External orchestration
  - No shared context with current session
  - Manual result retrieval

**For the memory save use case:** Agent teams are architecturally too complex. They're designed for long-running parallel workflows, not session-end callbacks.

---

## Architectural Proposals

### Option A: Hook-Driven Silent Save (RECOMMENDED)

Move file operations entirely out of the LLM tool loop.

**Architecture:**
1. **Stop hook (existing):** Runs `memory_triage.py` → outputs `<triage_data>` JSON
2. **Main agent:** Generates memory content as structured JSON text output (no tool calls for file writes)
   - Output format: `<memory_draft category="decision">{"title": "...", "content": {...}}</memory_draft>`
3. **New Python hook:** `Stop` hook `type: command` script that:
   - Reads the conversation transcript
   - Parses `<memory_draft>` blocks from agent's text output
   - Calls `memory_write.py` directly (Python import, no subprocess)
   - Exits with 0 (silent success)

**Visibility:** Zero. Python hooks running as `type: command` produce no user-visible output if they exit 0 with nothing on stdout.

**Pros:**
- Completely silent
- No context bloat
- Works with existing `memory_write.py` infrastructure
- No permission prompts

**Cons:**
- Stop hook output is limited (currently used for `{"decision": "block"}`)
- Requires parsing transcript from hook (hook receives transcript as JSON via stdin)
- Two Stop hooks needed (triage + save), or combined into one
- LLM must reliably output structured JSON in text (not tool calls)

### Option B: Single Consolidated Background Save Agent (PARTIAL IMPROVEMENT)

Replace 4-phase multi-agent orchestration with a single Task subagent.

**Architecture:**
```
Stop hook → single Task(model=haiku, prompt="do ALL phases in sequence") → saves
```

**Visibility:** Still visible, but less noisy than current 4-agent parallel pattern.

**Pros:**
- Simpler to implement (SKILL.md change only)
- Reduces parallel noise multiplication
- Avoids Bug #18351 (parallel agent transcript dump)

**Cons:**
- User still sees all tool calls
- Results still injected into main context
- Doesn't solve the fundamental problem

### Option C: External Process via Bash Background

Spawn a background shell process to handle saves without it being a Task agent.

**Architecture:**
```bash
# In Stop hook or skill:
nohup python3 memory_write.py --batch-mode ... > /dev/null 2>&1 &
```

**Visibility:** Zero if stdout/stderr redirected. The Bash tool call itself is visible but brief.

**Pros:**
- Single visible Bash call (brief)
- All subsequent work is silent
- Python script has full access to memory directory

**Cons:**
- Race condition: process may outlive the session
- No error feedback to the agent
- Bash hook guard may block heredoc writes in the spawned process
- Reliability concerns (process orphaning)

### Option D: Hybrid - LLM Drafts in Text, Hook Writes Files

Similar to Option A but using the current triage/skill architecture.

**Architecture:**
1. Stop hook triggers SKILL.md (current behavior)
2. SKILL.md instructs agent to write memory JSON in text output only (no Bash/Write tools)
3. Agent outputs `<memory_draft>` XML blocks in its stop message
4. A second `Stop` hook (registered after the SKILL.md hook) parses the agent's output and calls `memory_write.py`

**Visibility:** Only the agent's text output (brief summary). No tool calls visible.

**Key challenge:** Claude Code's Stop hook flow: the agent's response to the `{"decision": "block"}` hook is itself the "stop" output. A second Stop hook would need to process this response. This requires understanding the hook execution order and whether hooks can chain.

---

## Cross-Validation (Gemini 3.1 Pro)

Gemini's analysis confirmed all key findings:

> "Claude Code's Task subagents currently suffer from a broken delegation chain (Issues #14118, #27108, #18351). `background: true` does not suppress UI noise, and subagent tool calls bypass the orchestrator, directly polluting both the user's terminal and the parent's context window."

> "To achieve a completely silent, zero-UI-noise save process, you must move the file system operations out of the LLM's tool loop and into deterministic Python hooks."

Gemini's recommended architecture (Hook-Driven) matches Option A above.

---

## Conclusions

### Key Findings:
1. **Background agents do NOT hide output** - `background: true` only allows concurrent execution, not silent execution
2. **Subagent context isolation is broken** - Bugs #14118, #18351, #27108 document transcript leakage to parent context
3. **Parallel agents worsen the problem** - Each additional parallel agent multiplies context bloat risk
4. **`isolation: "worktree"` is irrelevant** - Doesn't affect `.claude/memory/` (not in git)
5. **Agent teams are overkill** - Designed for long-running parallel work, not session-end callbacks
6. **The only reliable solution** is to move file writes out of the LLM tool loop entirely

### Recommendation:
**Option A (Hook-Driven Silent Save)** is the correct architectural direction. The LLM should generate memory content as structured text output, and a Python hook should perform the actual file I/O silently. This requires:
1. Modifying SKILL.md to output `<memory_draft>` XML instead of using Write/Bash tools
2. A new Python hook that parses draft output from the agent's text and calls `memory_write.py`
3. Potentially rearchitecting the Stop hook flow to support this pattern

---

## Sources

- [Claude Code Subagents Documentation](https://code.claude.com/docs/en/sub-agents)
- [GitHub Issue #14118: Background subagent tool calls exposed in parent context](https://github.com/anthropics/claude-code/issues/14118)
- [GitHub Issue #9905: Feature Request - Background Agent Execution](https://github.com/anthropics/claude-code/issues/9905)
- [DEV Community: The Task Tool](https://dev.to/bhaidar/the-task-tool-claude-codes-agent-orchestration-system-4bf2)
- [Claude Code Async Workflows Guide](https://claudefa.st/blog/guide/agents/async-workflows)
- Gemini 3.1 Pro cross-validation (via PAL clink tool)
