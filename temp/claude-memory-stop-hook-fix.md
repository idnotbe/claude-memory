# claude-memory Stop Hook JSON Validation Fix

## Problem

```
Ran 9 stop hooks
  Stop hook error: JSON validation failed   (x6)
```

Every session end triggers 6 "JSON validation failed" errors from the claude-memory plugin.

## Root Cause

`hooks/hooks.json` has 6 prompt-type Stop hooks (SESSION_SUMMARY, DECISION, RUNBOOK, CONSTRAINT, TECH_DEBT, PREFERENCE). Each prompt asks the LLM to return JSON with **extra top-level fields**:

```json
{"ok": false, "reason": "...", "lifecycle_event": "resolved", "cud_recommendation": "CREATE"}
```

Claude Code's prompt hook schema only allows **two fields**:

```json
{"ok": true}
{"ok": false, "reason": "string"}
```

Extra fields (`lifecycle_event`, `cud_recommendation`) cause strict JSON schema validation failure (`additionalProperties: false`).

**Confirmed by**: Claude Opus 4.6, Codex 5.3, Gemini 3 Pro -- all 3 models agree on this diagnosis.

## Why guardian Works but claude-memory Fails

claude-code-guardian's Stop hook uses `command` type. claude-memory uses `prompt` type. This is the key difference.

| | claude-code-guardian | claude-memory |
|---|---|---|
| **hook type** | `command` | `prompt` |
| **how it works** | Runs Python script (`auto_commit.py`), script controls exact JSON output | Sends prompt to LLM (Sonnet), Claude Code validates the LLM's response |
| **JSON validation** | Script outputs exactly `{"ok": true}` -- developer has full control | LLM generates response, Claude Code validates against `{ok, reason}` schema |
| **failure risk** | Low -- deterministic output | High -- LLM may add extra fields if prompted to do so |

Guardian's hook (correct pattern):
```json
{ "type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/auto_commit.py\"" }
```

claude-memory's hooks (failing pattern):
```json
{ "type": "prompt", "model": "sonnet", "prompt": "... Include lifecycle_event and cud_recommendation fields ..." }
```

**Lesson**: `prompt` type hooks MUST only request `{ok, reason}` in the JSON response. Any extra fields will be rejected by Claude Code's strict schema validation. If you need additional metadata, embed it inside the `reason` string.

## Fix

In all 6 Stop hook prompts, replace the "extra fields" instruction block with an inline format that embeds the metadata **inside the `reason` string**.

### What to change in each of the 6 Stop hook prompts

**DELETE this block** (appears identically in all 6):

```
Also output lifecycle_event and cud_recommendation:
- lifecycle_event: "resolved"|"removed"|"reversed"|"superseded"|"deprecated"|null
- cud_recommendation: "CREATE"|"UPDATE"|"DELETE"
  - CREATE: This is new information not previously saved.
  - UPDATE: This modifies, corrects, or extends something previously saved.
  - DELETE: A previously saved item is now resolved/removed/deprecated.
Include these fields in your JSON response alongside ok and reason.

Respond with valid JSON only. No other text.
```

**REPLACE with this block**:

```
When responding with ok=false, include CUD and lifecycle metadata in the reason string using this prefix format:
[CUD:<action>|EVENT:<event>] <your reason text>
- CUD action: CREATE (new info), UPDATE (modifies existing), or DELETE (resolved/removed/deprecated)
- EVENT: resolved, removed, reversed, superseded, deprecated, or none
- Check .claude/memory/index.md to determine if CREATE vs UPDATE vs DELETE is appropriate.
Example: {"ok": false, "reason": "[CUD:CREATE|EVENT:none] Save a SESSION_SUMMARY memory capturing: implemented user auth."}

IMPORTANT: Respond with valid JSON only. No markdown code blocks. No extra text. No extra fields beyond ok and reason.
```

### Affected hooks (all 6 in `hooks/hooks.json` under `hooks.Stop[]`)

| Index | statusMessage | Category |
|-------|--------------|----------|
| 0 | "Checking for session summary..." | SESSION_SUMMARY |
| 1 | "Checking for decisions..." | DECISION |
| 2 | "Checking for runbook entries..." | RUNBOOK |
| 3 | "Checking for constraints..." | CONSTRAINT |
| 4 | "Checking for tech debt..." | TECH_DEBT |
| 5 | "Checking for preferences..." | PREFERENCE |

### Other hooks (NOT affected -- do not modify)

- `PreToolUse` (Write guard) -- command type, no JSON schema issue
- `PostToolUse` (Write validate) -- command type, no JSON schema issue
- `UserPromptSubmit` (memory retrieve) -- command type, no JSON schema issue

## Downstream Impact

- `lifecycle_event` is consumed by `memory_candidate.py` via `--lifecycle-event` CLI arg. The main agent reads `[EVENT:xxx]` from the reason string and passes it downstream. No code change needed in `memory_candidate.py` since the main agent interprets the reason.
- `cud_recommendation` is not consumed by any Python code. It's documentation-level metadata the main agent uses to decide CREATE vs UPDATE vs DELETE actions.

## Verification

After applying the fix, start a new session and do some meaningful work, then stop. Expected result:
- No more "JSON validation failed" errors
- Stop hooks should either pass silently (`{"ok": true}`) or block with a reason containing `[CUD:...|EVENT:...]` prefix

## Quick Command

To apply the fix programmatically from the claude-memory project root:

```bash
python3 -c "
import json

with open('hooks/hooks.json') as f:
    data = json.load(f)

old_block = '\n\nAlso output lifecycle_event and cud_recommendation:\n- lifecycle_event: \"resolved\"|\"removed\"|\"reversed\"|\"superseded\"|\"deprecated\"|null\n- cud_recommendation: \"CREATE\"|\"UPDATE\"|\"DELETE\"\n  - CREATE: This is new information not previously saved.\n  - UPDATE: This modifies, corrects, or extends something previously saved.\n  - DELETE: A previously saved item is now resolved/removed/deprecated.\nInclude these fields in your JSON response alongside ok and reason.\n\nRespond with valid JSON only. No other text.'

new_block = '\n\nWhen responding with ok=false, include CUD and lifecycle metadata in the reason string using this prefix format:\n[CUD:<action>|EVENT:<event>] <your reason text>\n- CUD action: CREATE (new info), UPDATE (modifies existing), or DELETE (resolved/removed/deprecated)\n- EVENT: resolved, removed, reversed, superseded, deprecated, or none\n- Check .claude/memory/index.md to determine if CREATE vs UPDATE vs DELETE is appropriate.\nExample: {\"ok\": false, \"reason\": \"[CUD:CREATE|EVENT:none] Save a SESSION_SUMMARY memory capturing: implemented user auth.\"}\n\nIMPORTANT: Respond with valid JSON only. No markdown code blocks. No extra text. No extra fields beyond ok and reason.'

count = 0
for stop_hook in data['hooks']['Stop']:
    for hook in stop_hook['hooks']:
        if hook['type'] == 'prompt' and old_block in hook['prompt']:
            hook['prompt'] = hook['prompt'].replace(old_block, new_block)
            count += 1

with open('hooks/hooks.json', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')

print(f'Fixed {count}/6 Stop hook prompts')
"
```
