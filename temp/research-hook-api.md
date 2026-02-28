# Research: Claude Code Hook API Output Control Mechanisms

**Task:** #1 — Research Claude Code hook API output control mechanisms
**Researcher:** hook-api-researcher
**Date:** 2026-02-28
**Sources:** Claude Code official docs (code.claude.com/docs/en/hooks), GitHub issues #4084, #10875, Gemini cross-validation

---

## 1. How Stop Hook Output Is Rendered in the UI

### The `reason` field

When a Stop hook returns `{"decision": "block", "reason": "..."}`:

- The `reason` field is **fed directly back to Claude as its next instruction**, not displayed as raw terminal output to the user in the traditional sense
- It appears as a **system-level block notification** in the UI (typically colored/styled differently from regular conversation text)
- Claude processes it and then begins executing tool calls, spawning subagents, etc. — all of which ARE visible in the transcript
- **The `reason` itself is NOT what causes UI noise** — the noise comes from Claude's subsequent tool calls in response to the reason

### The `statusMessage` field (hooks.json)

- `statusMessage` is displayed as a **temporary spinner message WHILE the hook is executing**
- It disappears completely when the hook exits
- It is **shown instead of** the default spinner text (not in addition to output)
- Example: `"statusMessage": "Evaluating session for memories..."` shows a spinner during hook execution, then vanishes

### Output streams

- **stdout** on exit 0: Only visible in verbose mode (Ctrl+O) unless `suppressOutput: true`
- **stderr** on exit 2: Fed back to Claude as an error message
- **stderr** on other non-zero exits: Shown in verbose mode only

---

## 2. Complete JSON Output Fields Reference

All hooks (including Stop) support these universal JSON output fields when exiting with code 0:

| Field | Default | Description |
|-------|---------|-------------|
| `continue` | `true` | If `false`, Claude stops processing entirely. Takes precedence over event-specific decisions |
| `stopReason` | none | Message shown to the **user** when `continue` is `false`. NOT shown to Claude |
| `suppressOutput` | `false` | If `true`, hides hook's stdout from verbose mode (Ctrl+O). Does NOT suppress reason/decision rendering |
| `systemMessage` | none | Warning message shown to the user (rendered as a distinct UI element) |

Stop-hook-specific fields:

| Field | Description |
|-------|-------------|
| `decision` | `"block"` prevents Claude from stopping |
| `reason` | Required when `decision` is `"block"`. Tells Claude why it should continue |

---

## 3. Key Findings on Output Control

### Finding 1: `suppressOutput` does NOT reduce memory save noise

`suppressOutput: true` only hides the hook script's raw stdout from verbose mode. It does NOT:
- Suppress the `reason`/`stopReason` rendering
- Hide Claude's subsequent tool calls that execute in response to the reason
- Prevent subagent output from appearing in the transcript

**The root cause of memory save noise is not the hook output itself — it is Claude's tool execution in response to the `reason` prompt.**

### Finding 2: Short `reason` is fully functional

The `reason` can be a single short line referencing a file path:
```json
{
  "decision": "block",
  "reason": "Memory triage triggered. Context files in .claude/memory/.staging/. Use memory-management skill."
}
```

Claude will act on this just like any other instruction. A short reason + context files (already written by triage.py) is the optimal current approach. The 20+ line `<triage_data>` JSON in the current reason is unnecessary — Claude only needs to know where to find the data.

### Finding 3: Stop hooks do NOT support `async: true`

- `async: true` is only available for `type: "command"` hooks
- For `Stop` hooks, async is **meaningless** because:
  - An async hook cannot return a `decision` (the action has already proceeded)
  - The entire purpose of a Stop hook is to block Claude and provide a reason to continue
- Stop hook MUST be synchronous to be effective

### Finding 4: No silent data injection mechanism from Stop hooks

There is **no way** to pass structured data to Claude from a Stop hook without Claude acting on it (and those actions being visible). Options:

| Mechanism | What user sees | Suitable for noise reduction? |
|-----------|---------------|-------------------------------|
| `reason` (short) | Small notification text | Yes — minimal |
| `reason` (long JSON) | Full JSON in notification | No — current problem |
| `additionalContext` | Not shown in terminal | Potentially — but NOT documented for Stop hooks |
| File-based (context files) | Nothing from hook itself | Yes — data hidden in files |
| `systemMessage` | Warning notification | Partial — user-facing only |

**`additionalContext` caveat:** Gemini cross-validation confirmed this field works for `UserPromptSubmit` and `SessionStart` hooks for discrete context injection. For Stop hooks, it is not documented and may be ignored — the `reason` field is the primary mechanism.

### Finding 5: `statusMessage` in hooks.json — what it does

- Shown in the UI as a spinner text while the hook runs
- Replaces the default spinner text
- Completely disappears after hook exits
- Has no effect on what Claude receives or what's logged to transcript
- No way to set persistent status messages from hooks

---

## 4. Why Current Architecture Is Noisy

The current `memory_triage.py` produces noise in two places:

1. **The `reason` field** contains a 20+ line block with `<triage_data>` JSON embedded — this appears as a block notification in the UI
2. **Claude's subsequent execution** in response to the reason spawns Task subagents, reads context files, writes memory files — all visible

The hook API offers no mechanism to make Claude's response to a Stop hook invisible. The only levers are:
- Reduce the `reason` content (minimize notification size)
- Reduce what Claude does in response (fewer/simpler tool calls)

---

## 5. Specific Recommendations for Minimizing Save Noise

### Recommendation 1: Shorten the `reason` to a single line

Replace the current multi-line `<triage_data>` JSON blob in the reason with:
```
"Memory save triggered [DECISION,RUNBOOK]. Read .claude/memory/.staging/context-*.txt for context."
```

The structured triage data is **already written to context files** by `write_context_files()`. The reason doesn't need to duplicate it — it just needs to tell Claude where to look.

**Impact:** The UI notification shrinks from 20+ lines to 1-2 lines.

### Recommendation 2: Do NOT use `suppressOutput` to fix this problem

It doesn't help with the core issue. The noise is Claude's tool calls, not hook stdout.

### Recommendation 3: Consider SessionEnd for deferred saves (research task #3)

`SessionEnd` hook fires when the session ends. It:
- Cannot block termination
- Cannot inject content into Claude's context
- Can only run side-effect commands

This means a SessionEnd hook could run Python to save memories without any Claude agent involvement — no tool calls, no transcript noise. Trade-off: no LLM-assisted memory drafting.

### Recommendation 4: Single-turn save instruction

Rather than spawning Phase 1 + Phase 2 + Phase 3 subagents (each visible), restructure SKILL.md to do all saves in a single consolidated call with minimal tool use. The fewer tool calls, the less transcript noise.

### Recommendation 5: `async: true` PostToolUse pattern (not Stop)

For true background processing, the only viable hook-based approach is using async PostToolUse hooks that enqueue work to be done silently. But this architecture requires a separate process/daemon to handle the queue — more complex than Stop hooks.

---

## 6. Hook API Summary Table for Stop Hooks

| Feature | Supported | Notes |
|---------|-----------|-------|
| `decision: "block"` | Yes | Only blocking value |
| `reason` field | Yes | Shown to Claude as instruction |
| `suppressOutput` | Yes | Only hides hook stdout, not reason |
| `systemMessage` | Yes | Shows to user as warning, not Claude |
| `continue: false` | Yes | Stops Claude entirely, no memory save |
| `stopReason` | Yes | Shown to user when `continue: false` |
| `async: true` | No | Cannot be used with decision control |
| `additionalContext` | Unknown | Not documented for Stop hooks |
| Background execution | No | Stop hooks must be synchronous |

---

## 7. Cross-Model Validation Results (Gemini)

Gemini cross-validated all 5 key conclusions:

1. **Short reason is functional** — Yes, confirmed. Claude treats it as an instruction.
2. **`suppressOutput` scope** — Confirmed only covers hook stdout, NOT reason/subsequent tool calls.
3. **`additionalContext` for discrete injection** — Confirmed for `UserPromptSubmit`/`SessionStart`. Unverified for Stop hooks (likely ignored; file-based approach safer).
4. **UI rendering differences** — Confirmed: `statusMessage` = temporary spinner, `systemMessage` = warning notification, `reason` = system block notification (colored), conversation text = markdown stream.
5. **Alternative approaches** — Gemini recommended: short file-pointer reason + optimized SKILL.md, or direct API calls from background hook process.

---

## Sources

- [Hooks reference - Claude Code Docs](https://code.claude.com/docs/en/hooks)
- [Claude Code async hooks article](https://blog.devgenius.io/claude-code-async-hooks-what-they-are-and-when-to-use-them-61b21cd71aad)
- [Hook Output Visibility Issue #4084](https://github.com/anthropics/claude-code/issues/4084) — resolved: `systemMessage` is the display mechanism
- [Plugin Hooks JSON Output Not Captured #10875](https://github.com/anthropics/claude-code/issues/10875) — plugin hook output parsing bug (resolved)
- [Claude Code Hooks: Complete Guide](https://claudefa.st/blog/tools/hooks/hooks-guide)
- Gemini 3.1 Pro cross-validation (via PAL clink)
