# Phase 0: Agent Hook Research — Claude Code `type: "agent"` Hooks

## Summary

Agent hooks (`type: "agent"`) are fully supported for Stop events. They spawn an isolated subagent with multi-turn tool access to verify conditions before returning an `ok`/`reason` decision. This research covers schema, isolation, return format, `$ARGUMENTS`, timeout, and filesystem access.

---

## 1. Does `type: "agent"` Work for Stop Hooks?

**Yes.** Agent hooks support the following events (same set as prompt hooks):

- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `PermissionRequest`
- `Stop`
- `SubagentStop`
- `TaskCompleted`
- `UserPromptSubmit`

Events that only support `type: "command"` (NOT agent/prompt):
`ConfigChange`, `Notification`, `PreCompact`, `SessionEnd`, `SessionStart`, `SubagentStart`, `TeammateIdle`, `WorktreeCreate`, `WorktreeRemove`

### Schema

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "agent",
            "prompt": "Your verification instructions here. $ARGUMENTS",
            "model": "optional-model-id",
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

| Field     | Required | Description                                                                 |
|-----------|----------|-----------------------------------------------------------------------------|
| `type`    | yes      | Must be `"agent"`                                                           |
| `prompt`  | yes      | Prompt for the subagent. `$ARGUMENTS` is replaced with hook input JSON      |
| `model`   | no       | Model to use. Defaults to "a fast model" (likely Haiku)                     |
| `timeout` | no       | Seconds before canceling. Default: **60s** (vs 30s for prompt, 600s for command) |

---

## 2. Subagent Tool Isolation

The agent hook spawns an **isolated subagent**. Key characteristics:

- **Up to 50 tool-use turns** (multi-turn, not single-shot like prompt hooks)
- **Tools available**: Read, Grep, Glob (confirmed in docs). The docs say "tools like Read, Grep, and Glob" — notably, the docs do NOT explicitly list Bash, Write, or Edit for agent hook subagents, though the example in the docs says "Run the test suite and check the results" which implies Bash access
- **Isolated context**: The subagent has its own context window, separate from the main agent's transcript
- **No main transcript access**: The agent hook subagent cannot see the full main conversation. It receives only the hook input JSON (via `$ARGUMENTS`) and the prompt
- **No decision overlap with main agent**: The subagent's tool calls do NOT appear in the main transcript

### What the Subagent Receives

The subagent gets:
1. The `prompt` text (with `$ARGUMENTS` expanded)
2. The hook's JSON input on stdin (same as command hooks receive), which for Stop includes:

```json
{
  "session_id": "abc123",
  "transcript_path": "~/.claude/projects/.../session.jsonl",
  "cwd": "/path/to/project",
  "permission_mode": "default",
  "hook_event_name": "Stop",
  "stop_hook_active": true,
  "last_assistant_message": "I've completed the refactoring..."
}
```

**Critical field**: `transcript_path` — the subagent CAN read the main transcript file from disk using its Read tool, even though it doesn't have it in its context. This is the key mechanism for giving the agent hook access to conversation history.

---

## 3. Return Schema

Agent hooks use the **same return schema as prompt hooks** — NOT the command hook `decision: "block"` pattern:

```json
{
  "ok": true
}
```

or

```json
{
  "ok": false,
  "reason": "Explanation of why the action should be blocked"
}
```

| Field    | Description                                                    |
|----------|----------------------------------------------------------------|
| `ok`     | `true` = allow the action, `false` = block/continue           |
| `reason` | Required when `ok` is false. Shown to Claude as next instruction |

For Stop hooks specifically:
- `ok: true` → Claude stops (allows the stop)
- `ok: false` → Claude continues working, receives `reason` as feedback

This is different from command hooks which use:
- `decision: "block"` with `reason` (top-level JSON output)
- Or exit code 2 with stderr message

---

## 4. `$ARGUMENTS` for Agent Hooks

**Yes, `$ARGUMENTS` works for agent hooks.** It is a placeholder in the `prompt` field that gets replaced with the hook's JSON input data.

From the docs: _"Use `$ARGUMENTS` as a placeholder for the hook input JSON. If `$ARGUMENTS` is not present, input JSON is appended to the prompt."_

This means:
- If you include `$ARGUMENTS` in the prompt, it gets replaced with the JSON
- If you omit `$ARGUMENTS`, the JSON is appended to the end of the prompt
- Either way, the subagent receives the hook context

Example:
```json
{
  "type": "agent",
  "prompt": "Verify work is complete. Context: $ARGUMENTS"
}
```

---

## 5. Timeout Constraints

| Hook Type | Default Timeout | Max Timeout |
|-----------|----------------|-------------|
| command   | 600s (10 min)  | Not documented |
| prompt    | 30s            | Not documented |
| agent     | **60s**        | Not documented |

The agent hook default of 60s is quite short for complex verification. Override with `"timeout": 120` or higher.

Agent hooks also have a **50-turn limit** on tool use. After 50 turns, the subagent must return its decision.

---

## 6. Filesystem Access

**Yes, the agent hook subagent can access the filesystem.** It has tools like Read, Grep, and Glob that operate on the filesystem.

### `$CLAUDE_PLUGIN_ROOT`

`$CLAUDE_PLUGIN_ROOT` is a shell environment variable set for **command** hooks. For agent hooks, the subagent does NOT receive shell environment variables directly. However:

- The subagent receives `cwd` in its input JSON
- The subagent can Read files at any absolute path
- If you embed `$CLAUDE_PLUGIN_ROOT` in the `prompt` string in hooks.json, it will be expanded by the shell when Claude Code processes the hook configuration (since hooks.json is a JSON file processed by Claude Code, not a shell script — this needs verification)

**Important**: The `transcript_path` field in the hook input gives the subagent a path to the conversation transcript file, which it can Read to analyze the full session history.

---

## 7. Key Implications for claude-memory Plugin

### Current Architecture (command hook)
The current Stop hook uses `type: "command"` with `memory_triage.py`, which:
- Reads transcript from `transcript_path`
- Performs keyword heuristic triage
- Outputs structured `<triage_data>` JSON + context files
- The main agent then processes the triage output

### Agent Hook Alternative
An agent hook Stop could:
- Receive `transcript_path` and `last_assistant_message` in `$ARGUMENTS`
- Use Read to access the transcript
- Use Read/Grep/Glob to access existing memories and config
- Make intelligent triage decisions using LLM judgment
- Return `ok: true` to allow stopping (after writing context files to disk)
- OR return `ok: false, reason: "..."` to force the main agent to continue (not useful for memory capture)

### Limitations to Consider
1. **No Write/Edit**: Agent hooks may not have Write/Edit tools, meaning they likely cannot write files to disk. This is a critical limitation — the current architecture depends on writing context files to `.staging/`
2. **No Bash**: If the subagent cannot run Bash, it cannot invoke `memory_write.py`
3. **60s default timeout**: May be insufficient for complex triage across 6 categories
4. **50-turn limit**: Should be sufficient for reading/analyzing, but tight if the subagent needs to do extensive file exploration
5. **Isolation is a feature**: The subagent cannot pollute the main agent's context with triage noise — this is actually desirable

### Recommended Experiment
To verify tool availability, create a minimal agent hook and observe what tools the subagent actually has access to:

```json
{
  "Stop": [
    {
      "hooks": [
        {
          "type": "agent",
          "prompt": "List what tools you have available. Then try to: 1) Read the file at $ARGUMENTS transcript_path, 2) Write a test file to /tmp/agent-hook-test.txt, 3) Run 'echo hello' via Bash. Report what worked and what didn't. Return {\"ok\": true}.",
          "timeout": 30
        }
      ]
    }
  ]
}
```

---

## Sources

- [Hooks reference — Claude Code Docs](https://code.claude.com/docs/en/hooks) — Primary reference for all hook types, events, schemas
- [Automate workflows with hooks — Claude Code Docs](https://code.claude.com/docs/en/hooks-guide) — Guide with examples including agent hooks
- [Hook development SKILL.md — GitHub](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md) — Plugin development reference
- [Feature Request: Invoke Subagents from Hooks — GitHub Issue #4783](https://github.com/anthropics/claude-code/issues/4783)
- [Feature Request: Allow Hooks to Bridge Context Between Sub-Agents — GitHub Issue #5812](https://github.com/anthropics/claude-code/issues/5812)
