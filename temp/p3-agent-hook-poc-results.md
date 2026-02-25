# Agent Hook PoC Results

**Date:** 2026-02-26
**Branch:** `feat/agent-hook-poc`
**Scope:** Analysis-only PoC -- no production hooks modified, no live executions

---

## Executive Summary

Agent hooks (`type: "agent"`) are a fully supported Claude Code hook handler type, documented alongside `command` and `prompt` hooks. They spawn a subagent with multi-turn tool access (Read, Grep, Glob, Bash) for up to 50 turns. However, a critical finding from this PoC is that **UserPromptSubmit hooks support `additionalContext` injection via `hookSpecificOutput` JSON**, which means context injection is not limited to command hook stdout. This opens a viable hybrid architecture path.

---

## Key Findings: Answers to the 4 Questions

### Question A: What is the real-world latency of agent hooks?

**Answer: Expected 2-15 seconds for typical verification tasks, 60s default timeout.**

- **Default timeout:** 60 seconds (vs. 600s for command, 30s for prompt hooks).
- **Mechanism:** Agent hooks spawn a subagent that can use tools for up to 50 turns. Actual execution time depends on the number of tool calls and model inference time.
- **Latency composition:**
  - Model inference per turn: ~0.5-2s (Haiku), ~1-4s (Sonnet)
  - Tool execution per turn: ~0.1-1s (Read/Grep/Glob are local and fast)
  - Typical simple verification (1-3 turns): 2-8 seconds
  - Complex codebase inspection (5-10 turns): 5-15 seconds
- **For memory retrieval context:** A BM25 search + file reads + relevance assessment could realistically complete in 3-10 seconds with a Haiku agent, but this adds significant latency vs. the current ~0.5-1s command hook approach.
- **Important caveat:** No live measurements were taken. These estimates are derived from documented timeout defaults, known model latency characteristics, and the tool execution overhead of Read/Grep/Glob.

### Question B: Can agent hooks inject context beyond `{ok: true/false, reason: "..."}`?

**Answer: YES -- via TWO mechanisms, with an important recent discovery.**

**Mechanism 1: `additionalContext` via `hookSpecificOutput` (JSON output)**

The TypeScript SDK type definitions and official documentation confirm that `UserPromptSubmit` hooks can return `additionalContext`:

```typescript
type SyncHookJSONOutput = {
  // ... other fields ...
  hookSpecificOutput?:
    | { hookEventName: 'PreToolUse'; permissionDecision?: ...; }
    | { hookEventName: 'UserPromptSubmit'; additionalContext?: string; }
    | { hookEventName: 'SessionStart'; additionalContext?: string; }
    | { hookEventName: 'PostToolUse'; additionalContext?: string; };
}
```

From the official hooks reference (code.claude.com/docs/en/hooks):

> **UserPromptSubmit decision control:** There are two ways to add context to the conversation on exit code 0:
> - **Plain text stdout**: any non-JSON text written to stdout is added as context
> - **JSON with `additionalContext`**: use the JSON format below for more control. The `additionalContext` field is added more discretely.
>
> Plain stdout is shown as hook output in the transcript. The `additionalContext` field is added more discretely.

**Mechanism 2: Plain text stdout (command hooks only)**

For `UserPromptSubmit` and `SessionStart` events specifically, stdout from command hooks is added as context that Claude can see and act on. This is the current mechanism used by `memory_retrieve.py`.

**Critical distinction:**

| Mechanism | Hook Type | Visibility | Where Documented |
|-----------|-----------|------------|-----------------|
| Plain stdout | command only | Shown in transcript as hook output | Exit code output section |
| `additionalContext` JSON | command, prompt, agent | "Added more discretely" | UserPromptSubmit decision control |
| `systemMessage` JSON | all types | "Warning message shown to the user" | JSON output section |

**For agent hooks specifically:** The agent hook spawns a subagent that returns `{ "ok": true/false, "reason": "..." }`. However, this is the subagent's internal decision format. The hook infrastructure processes this and can produce `hookSpecificOutput` with `additionalContext`. The key question is whether the agent hook's response schema allows passing `additionalContext` through.

**Current evidence suggests:** Agent hooks follow the same response schema as prompt hooks (`{ "ok": true/false, "reason": "..." }`), and the `additionalContext` field is processed at the hook infrastructure level, not the handler level. This means:
- **Command hooks:** Can inject context via stdout OR `additionalContext` JSON.
- **Prompt/Agent hooks:** The LLM returns `{ "ok": true/false }`, and the hook infrastructure processes it. Whether `additionalContext` can be included in the response is not explicitly documented for prompt/agent types -- their documented response schema is limited to `ok` and `reason`.

**Conclusion for Q.B:** Context injection IS possible from UserPromptSubmit hooks via `additionalContext`, but this mechanism is most clearly supported for **command hooks** returning JSON. For agent hooks, the primary output is the `ok/false` decision. A hybrid approach (command hook for injection + agent hook for judgment) is the safer architectural path.

### Question C: Does `type: "agent"` in plugin hooks/hooks.json work properly?

**Answer: YES -- confirmed by official documentation.**

From the official hooks reference:

> **Hook handler fields:** Each object in the inner `hooks` array is a hook handler: the shell command, LLM prompt, or agent that runs when the matcher matches. There are three types:
> - Command hooks (`type: "command"`): run a shell command.
> - Prompt hooks (`type: "prompt"`): send a prompt to a Claude model for single-turn evaluation.
> - Agent hooks (`type: "agent"`): spawn a subagent that can use tools like Read, Grep, and Glob.

Events that support all three hook types (`command`, `prompt`, and `agent`):
- `PermissionRequest`
- `PostToolUse`
- `PostToolUseFailure`
- `PreToolUse`
- `Stop`
- `SubagentStop`
- `TaskCompleted`
- **`UserPromptSubmit`** (relevant for memory retrieval)

Events that ONLY support `type: "command"`:
- `ConfigChange`, `Notification`, `PreCompact`, `SessionEnd`, `SessionStart`, `SubagentStart`, `TeammateIdle`, `WorktreeCreate`, `WorktreeRemove`

The plugin `hooks/hooks.json` format is documented as supporting all three handler types. The plugin-dev SKILL.md in the claude-code repo explicitly shows `type: "prompt"` and `type: "command"` in plugin hooks, and the hooks reference confirms agent type is valid anywhere prompt type is valid.

### Question D: Is hybrid approach possible (command hook for injection + agent hook for judgment in sequence)?

**Answer: YES -- hooks run in parallel by default, but architectural design matters.**

**Parallel execution model:**

From the official documentation:

> All matching hooks run **in parallel**... Hooks don't see each other's output. Non-deterministic ordering. Design for independence.

This means if we define both a command hook and an agent hook for UserPromptSubmit:

```json
{
  "UserPromptSubmit": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "command",
          "command": "python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_retrieve.py",
          "timeout": 15
        },
        {
          "type": "agent",
          "prompt": "Evaluate the relevance of retrieved memories...",
          "timeout": 60
        }
      ]
    }
  ]
}
```

Both would fire **simultaneously** on every user prompt. They cannot communicate -- the agent hook cannot see the command hook's output, and vice versa.

**Three viable hybrid architectures:**

**Architecture A: Parallel Independent (Both fire, no coordination)**
- Command hook: BM25 search + inject all results via stdout
- Agent hook: independently reads memory files + evaluates relevance, returns ok/false
- Problem: Agent hook cannot filter the command hook's already-injected results. The agent hook's verdict arrives after or simultaneously with the injection. If the agent returns `ok: false`, the prompt might be blocked entirely (not the intent).

**Architecture B: Command Hook Only with `additionalContext` JSON (Current approach, enhanced)**
- Single command hook: runs BM25 search, runs judge internally (current LLM judge via API), returns JSON with `additionalContext` containing filtered results.
- This is essentially the current architecture with the judge layer (`memory_judge.py`).
- No agent hook needed. The command hook handles both search and judgment.

**Architecture C: Agent Hook as Sole Handler (Replace command hook)**
- Single agent hook: spawns a subagent that runs BM25 search via Bash tool, reads memory files via Read tool, evaluates relevance, and returns `ok: true` with context.
- The subagent would use Bash to run `memory_search_engine.py --query "..." --root .claude/memory` and then Read to inspect top results.
- Problem: The agent's return value is `{ "ok": true/false }`, not arbitrary context. The `reason` field is only shown when `ok: false`. Context injection from agent hooks is not clearly documented.

**Recommendation:** Architecture B (current approach with command hook + internal judge) remains the most reliable. The `additionalContext` JSON mechanism could be adopted for cleaner context injection (replacing raw stdout), but this is an incremental improvement, not an architectural shift.

---

## PoC Hook Configuration (Not Activated)

The following hooks.json snippet shows what an agent hook configuration would look like for UserPromptSubmit. This is provided for documentation only and is NOT applied to the real hooks/hooks.json.

### Sample: Agent Hook for Memory Relevance Verification

```json
{
  "description": "PoC: Agent hook for memory relevance verification (NOT ACTIVE)",
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_retrieve.py\"",
            "timeout": 15,
            "statusMessage": "Retrieving relevant memories..."
          },
          {
            "type": "agent",
            "prompt": "You are a memory relevance verifier for a coding assistant plugin. The user just submitted a prompt. Your task:\n\n1. Run: python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_search_engine.py --query '<extract key terms from user prompt>' --root .claude/memory --mode search\n2. For each result, Read the JSON file to check: Is it actually relevant to the user's current task?\n3. If the search results are relevant, return {\"ok\": true}. If the search results are noise (false positives), return {\"ok\": false, \"reason\": \"Memory results are not relevant to this prompt\"}.\n\nUser prompt: $ARGUMENTS",
            "model": "haiku",
            "timeout": 30,
            "statusMessage": "Verifying memory relevance..."
          }
        ]
      }
    ]
  }
}
```

**Why this design won't work well:**
- Both hooks fire in parallel. The agent hook cannot filter results from the command hook.
- If the agent returns `ok: false`, it might block the entire prompt processing (unintended side effect).
- The agent adds ~5-15s latency to every prompt submission.

### Sample: Agent Hook as Sole Retrieval Handler (Alternative)

```json
{
  "description": "PoC: Agent-only memory retrieval (NOT ACTIVE)",
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "agent",
            "prompt": "You are a memory retrieval agent for a coding assistant. The user submitted a prompt.\n\n1. Extract key terms from the user's prompt\n2. Run: python3 $CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_search_engine.py --query '<terms>' --root .claude/memory --mode search\n3. For each result path, use Read to inspect the JSON file\n4. Evaluate relevance: Is this memory directly useful for the current task?\n5. Return {\"ok\": true} if you found relevant memories, or {\"ok\": true} if no relevant memories exist (allow prompt to proceed either way)\n\nDo NOT return ok:false -- this would block the user's prompt.\n\nUser prompt context: $ARGUMENTS",
            "model": "haiku",
            "timeout": 30,
            "statusMessage": "Searching memories..."
          }
        ]
      }
    ]
  }
}
```

**Why this design won't work well:**
- Agent hook's return value is `{ "ok": true/false }`, not context injection.
- The subagent's tool calls (Read, Bash) are visible in its own transcript but don't inject into the main conversation's context.
- The `reason` field in `{ "ok": false, "reason": "..." }` is shown to Claude, but `ok: false` on UserPromptSubmit blocks the prompt entirely.
- No documented mechanism for agent hooks to inject arbitrary context into the main conversation.

### Sample: Command Hook with `additionalContext` JSON (Recommended Evolution)

```json
{
  "description": "Enhanced: Command hook with additionalContext JSON (recommended next step)",
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_retrieve.py\"",
            "timeout": 15,
            "statusMessage": "Retrieving relevant memories..."
          }
        ]
      }
    ]
  }
}
```

With `memory_retrieve.py` modified to output JSON instead of plain text:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "UserPromptSubmit",
    "additionalContext": "<memory-context source=\".claude/memory/\">...</memory-context>"
  }
}
```

**Advantages of this approach:**
- `additionalContext` is "added more discretely" than plain stdout (per official docs)
- Structured JSON output allows richer control (e.g., `decision: "block"` if needed)
- No architectural change needed -- just modify the output format of `memory_retrieve.py`
- Compatible with the existing command hook timeout (15s)

---

## Detailed Analysis

### Agent Hook Architecture

```
User submits prompt
    |
    v
Claude Code hook infrastructure
    |
    +-- matcher: "*" matches all prompts
    |
    +-- For each matching hook handler (in parallel):
    |     |
    |     +-- type: "command" -> subprocess, stdin/stdout
    |     +-- type: "prompt" -> single LLM call, {ok, reason}
    |     +-- type: "agent" -> subagent with tools, up to 50 turns, {ok, reason}
    |
    v
Results aggregated:
    - command hook stdout -> added to context (UserPromptSubmit/SessionStart only)
    - all hooks: JSON output -> processed for decision/additionalContext
    - any hook returns ok:false/decision:block -> blocks the prompt
```

### What Agent Hooks CAN Do

1. **Multi-turn verification:** Read files, search code, run scripts before returning a decision.
2. **Codebase-aware judgment:** The subagent can inspect actual file contents, not just hook input metadata.
3. **Complex logic:** Up to 50 turns of reasoning, tool use, and evaluation.
4. **Model selection:** `model` field allows specifying which Claude model runs the subagent (default: fast model, likely Haiku).

### What Agent Hooks CANNOT Do (for Memory Retrieval)

1. **Direct context injection:** Agent hooks return `{ "ok": true/false }`, not arbitrary text for context. The `reason` field is only processed when `ok: false`.
2. **Coordination with other hooks:** Hooks run in parallel and cannot see each other's output.
3. **Fast execution:** Even simple agent hooks add 2-15s latency due to model inference + tool calls.
4. **Streaming results:** The subagent must complete all turns before the decision is processed.

### Comparison: Current vs. Agent Hook Approach

| Aspect | Current (command hook) | Agent Hook Alternative |
|--------|----------------------|----------------------|
| Latency | ~0.5-1s (Python + BM25) | ~2-15s (model inference + tools) |
| Context injection | stdout -> automatic | Not clearly supported |
| Judgment quality | Deterministic BM25 + optional LLM judge | LLM-native evaluation |
| Reliability | High (stdlib only, no API calls) | Medium (depends on model availability) |
| Token cost | 0 (or ~100 tokens for judge) | ~500-2000 tokens per invocation |
| Failure mode | Graceful (exit 0, no output) | Subagent timeout/error -> hook failure |

### The `additionalContext` Discovery

The most significant finding of this PoC is the `additionalContext` field in `hookSpecificOutput` for UserPromptSubmit. This was not previously documented in the project's analysis (see `temp/agent-hook-verification.md`).

**Previous understanding (from `temp/agent-hook-verification.md`):**
> Command hook: stdout text -> Claude context injection. This is the current method.
> Agent hook: Binary decision (ok/false) return. ok=false returns reason to Claude but this is a "block reason" not "injection context."

**Updated understanding:**
- Command hooks for UserPromptSubmit can return JSON with `hookSpecificOutput.additionalContext` for discrete context injection.
- This is separate from stdout injection (which is shown in the transcript).
- `additionalContext` is "added more discretely" -- meaning it goes into Claude's context without appearing as visible hook output in the transcript.
- This mechanism works for command hooks returning JSON with exit 0.
- For agent/prompt hooks, the response schema is `{ "ok": true/false, "reason": "..." }` -- `additionalContext` is not part of this schema.

### Practical Implications for claude-memory

1. **No immediate architectural change needed.** The current command hook approach is optimal for context injection. Agent hooks add latency without a clear injection mechanism.

2. **Future enhancement: `additionalContext` JSON output.** Modifying `memory_retrieve.py` to output JSON with `additionalContext` instead of plain text would make context injection more discrete (not shown in transcript). This is a low-risk, incremental improvement.

3. **Agent hooks for quality gates.** If a future use case requires deep codebase verification before injection (e.g., "verify the memory file still exists and is valid before injecting"), an agent hook could serve as a quality gate alongside the command hook. But this adds latency and complexity.

4. **The LLM judge layer (`memory_judge.py`) already serves the "judgment" role.** The current architecture embeds LLM judgment inside the command hook via API calls, achieving the same effect as an agent hook without the overhead of spawning a subagent.

---

## Recommendations

### Short-term (No Change)
- Keep current `type: "command"` hook for UserPromptSubmit.
- The `memory_judge.py` LLM-as-judge already provides the relevance filtering that an agent hook would offer.
- No latency regression, no token cost increase.

### Medium-term (Incremental Improvement)
- Consider migrating `memory_retrieve.py` output from plain text stdout to JSON with `additionalContext`. Benefits:
  - More discrete context injection (not shown as transcript hook output)
  - Structured output allows future extensions (e.g., `decision: "block"` for prompt filtering)
  - Compatible with existing command hook infrastructure
- Estimated effort: ~20 LOC change in `memory_retrieve.py` output formatting.

### Long-term (Architectural Option)
- If Claude Code adds richer agent hook output capabilities (e.g., `additionalContext` in agent hook responses), revisit the agent-only retrieval approach.
- Monitor Claude Code changelog for agent hook enhancements.

---

## References

- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks) -- Official documentation, UserPromptSubmit decision control, agent hook configuration
- [Claude Code Subagents Documentation](https://code.claude.com/docs/en/sub-agents) -- Subagent capabilities and configuration
- [Claude Code TypeScript SDK Reference](https://docs.claude.com/en/docs/claude-code/sdk/sdk-typescript#hookjsonoutput) -- `HookJSONOutput` type definition confirming `additionalContext` for UserPromptSubmit
- [Plugin Hook Development SKILL.md](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md) -- Plugin-specific hook format and event documentation
- `temp/agent-hook-verification.md` -- Previous independent verification (updated by this PoC)
- `hooks/hooks.json` -- Current production hook configuration
- `hooks/scripts/memory_retrieve.py` -- Current retrieval hook implementation
- `hooks/scripts/memory_judge.py` -- Current LLM judge implementation

---

## Gate E Checklist

| Question | Answer | Status |
|----------|--------|--------|
| Agent hook latency | 2-15s typical, 60s timeout | Documented |
| Context injection mechanism | `additionalContext` via JSON (command hooks); not available for agent hooks | Documented |
| Plugin `type: "agent"` compatibility | Supported for UserPromptSubmit and 7 other events | Documented |
| Hybrid approach feasibility | Parallel execution only; command+agent cannot coordinate sequentially | Documented |
| Branch created | `feat/agent-hook-poc` | Done |
| Production hooks modified | No | Confirmed |
| PoC hook config documented | 3 sample configurations provided | Done |
