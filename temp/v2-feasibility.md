# V2 Implementation Feasibility Report

Generated: 2026-02-28
Task: #14 — V2 Implementation feasibility check

---

## Check 1: Agent Hook for Stop Event

### Can `type: "agent"` be used with the `Stop` event?

**YES — confirmed buildable.**

From the official Claude Code hooks reference (https://docs.claude.com/en/docs/claude-code/hooks):

> Events that support all three hook types (`command`, `prompt`, and `agent`):
> * `Stop`
> * `SubagentStop`
> * `PreToolUse`, `PostToolUse`, `PostToolUseFailure`
> * `PermissionRequest`, `UserPromptSubmit`, `TaskCompleted`

The current hook in `hooks/hooks.json` (line 9) uses `"type": "command"`. Changing this to `"type": "agent"` is a 1-line edit.

### What fields does an agent hook support? Can it return `decision: "block"`?

**YES — same response schema as prompt hooks.**

From the docs:
> The response schema is the same as prompt hooks: `{ "ok": true }` to allow or `{ "ok": false, "reason": "..." }` to block.

This maps directly to the existing Stop hook decision control:
```json
{ "decision": "block", "reason": "..." }
```

The agent hook wraps this: `ok: false` → blocks stop, `ok: true` → allows stop.

### Does an agent hook have tool access?

**YES — full tool access (that's the point of `type: "agent"` vs `type: "prompt"`).**

From the docs example:
```json
{
  "type": "agent",
  "prompt": "Verify that all unit tests pass. Run the test suite and check the results. $ARGUMENTS",
  "timeout": 120
}
```

The agent spawned can run Bash, Read, Write, etc. This is the key property being tested: **whether memories saved by this subagent are isolated from the parent session's context window.**

### What is the timeout?

Default: **60 seconds** (vs 30 seconds for `type: "prompt"`).
Configurable via `timeout` field. Current `memory_triage.py` hook has `"timeout": 30`.

### Critical unknown: subagent isolation

The synthesis asks whether subagents spawned by an agent hook are isolated from the parent session. This is **not explicitly documented** in the public docs. The `type: "agent"` hook spawns an agentic verifier — whether its Tool calls appear in the parent transcript is unknown without empirical testing.

**Risk:** If the agent hook's subagent IS NOT isolated (its tool calls visible in parent context), then `type: "agent"` gains nothing over the current approach.

**Proposed test (10 minutes):** Change 1 line in `hooks/hooks.json`:
```diff
-  "type": "command",
-  "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_triage.py\"",
+  "type": "agent",
+  "prompt": "Check $ARGUMENTS. Always respond with {\"ok\": true}.",
```
Then observe whether the hook's activity appears in the parent session transcript.

### Code reference

- `hooks/hooks.json` line 9-11: current `type: "command"` hook definition
- Change needed: 1 line (`"type"`) + 1 line replacement (`"command"` → `"prompt"`)
- The existing `memory_triage.py` logic would need to be converted to a prompt describing what to check, OR kept as a command invoked within the agent hook's Bash tool.

---

## Check 2: Deferred Mode Implementation

### Can we detect pending saves in memory_retrieve.py?

**YES — highly feasible.**

`memory_retrieve.py` already reads `memory-config.json` and the memory root at startup (lines 411-420). Adding a check for pending-save files is trivial:

```python
# In main() of memory_retrieve.py, after loading _raw_config
pending_path = memory_root / ".staging" / ".triage-pending.json"
if pending_path.exists():
    try:
        pending = json.loads(pending_path.read_text())
        n_categories = len(pending.get("categories", []))
        if n_categories > 0:
            print(f"<memory-note>{n_categories} unsaved memories from last session. "
                  f"Use /memory:save to save them.</memory-note>")
    except (json.JSONDecodeError, OSError):
        pass
```

Insertion point: **after line 429** (after the short-prompt check and memory root loading).

### What is the exact format of the pending-saves notification?

Not yet defined — this is new functionality. The proposed format is a new file:
`.claude/memory/.staging/.triage-pending.json`

Content would mirror the existing triage_data structure:
```json
{
  "categories": [
    {"category": "decision", "score": 0.72, "context_file": "..."},
    {"category": "preference", "score": 0.61, "context_file": "..."}
  ],
  "parallel_config": {...},
  "saved_at": "2026-02-28T12:00:00Z"
}
```

This file would be written by `memory_triage.py` in "deferred mode" instead of blocking. Changes needed in `memory_triage.py`:

- `_run_triage()` line 1096-1132: Replace `set_stop_flag(cwd)` + `print(json.dumps({"decision": "block", ...}))` with writing `.triage-pending.json` + returning 0 (allow stop).
- After successful skill run: delete `.triage-pending.json` (cleanup).

### Are staging files auto-cleaned between sessions?

**NO — staging files are NOT automatically cleaned between sessions.**

Evidence:
1. The `.staging/` directory currently contains `.memory-write-pending.json` (created Feb 20, still present Feb 28 — 8 days old).
2. There is no cleanup code in any hook script that removes context files after session end.
3. `SessionEnd` hook type is not in `hooks/hooks.json`.
4. The sentinel file `.triage-handled` has a 5-minute TTL (`FLAG_TTL_SECONDS = 300`, line 49), but context files themselves have no TTL.

**This is actually a BENEFIT for deferred mode:** context files written during Session N persist into Session N+1, exactly what's needed.

### What happens if .staging/ is cleaned by session cleanup?

The staging directory is created with `os.makedirs(staging_dir, exist_ok=True)` (line 760 in `write_context_files`). If the directory were cleaned, `memory_retrieve.py` would simply not find `.triage-pending.json` and would show no notification — silent failure, no crash. This is acceptable behavior.

**Conclusion:** Deferred mode is fully buildable. The context files persist naturally, and detection in `memory_retrieve.py` is a ~15-line addition.

---

## Check 3: Foreground Single Task (Fix B)

### How would SKILL.md change to consolidate Phase 3 into a single Task subagent?

Current architecture (SKILL.md lines 47-186):
- **Phase 1:** N parallel Task subagents (one per triggered category) — each does candidate selection + drafting
- **Phase 2:** N parallel Task subagents — verification
- **Phase 3:** Main agent collects results and calls `memory_write.py` once per category

The "foreground single Task" proposal in the synthesis is about **consolidating all memory saves into one subagent** rather than having the main agent make multiple `memory_write.py` calls with visible tool call output.

**SKILL.md changes needed:**

Phase 3 currently runs in the **main agent** (lines 188-210). To move it to a single Task subagent:
1. Replace main-agent Phase 3 instructions with a Task subagent call containing all Phase 1/2 results
2. The subagent receives: list of verified draft files + CUD resolution table + memory_write.py invocations
3. Main agent waits for subagent completion, then reports summary

**Complexity:** Medium. Not a simple restructure — the CUD resolution table (lines 229-241) and the context about Phase 1/2 results needs to be passed as prompt context to the new subagent. This requires careful prompt engineering to avoid losing the dual-layer verification logic.

**Estimated SKILL.md lines changed:** Phase 3 section (lines 188-212) — ~25 lines replaced/added with subagent invocation pattern.

### Can a Task subagent call memory_write.py via Bash?

**YES — and the PreToolUse guard explicitly allows it.**

From `memory_write_guard.py` (line 53-58):
```python
# Allow writes to the .staging/ subdirectory (draft files, context files).
staging_segment = "/.claude/memory/.staging/"
if staging_segment in normalized:
    sys.exit(0)
```

The guard blocks **Write tool** calls to the memory directory but explicitly allows:
1. Writes to `.staging/` (draft JSON files)
2. Writes to `/tmp/` with specific prefixes

The `memory_write.py` script itself is called via **Bash**, which the staging_guard (`memory_staging_guard.py`) monitors — but that guard only blocks heredoc writes to `.staging/`, not Bash invocations of Python scripts.

**No guard changes needed.** Task subagents can call `memory_write.py` via Bash today.

---

## Check 4: Fix A (Externalize triage_data)

### How many lines need to change to write triage_data to a file instead of inline?

**Very few — approximately 8-12 lines in memory_triage.py.**

Current flow in `format_block_message()` (lines 870-955) and `_run_triage()` (line 1131):

```python
# Current (line 1131):
print(json.dumps({"decision": "block", "reason": message}))
```

Where `message` is a string containing the human-readable text + inline `<triage_data>` JSON block (lines 951-953 in `format_block_message()`).

**Fix A changes:**
1. In `_run_triage()` (around line 1117-1131), write `triage_data` dict to `.staging/triage-data.json` (atomic write, same pattern as context files).
2. In `format_block_message()` (line 951-953), remove the inline `<triage_data>` block OR add a reference to the file path:
   ```python
   lines.append(f"<triage_data_file>{triage_data_path}</triage_data_file>")
   ```
3. Update SKILL.md Phase 0 to read the file instead of parsing inline `<triage_data>`.

**Exact code changes:**
- `memory_triage.py` lines 950-953: Replace inline JSON embedding with file path reference (~4 lines changed)
- `memory_triage.py` lines 1117-1131: Add file write before `print()` call (~6 new lines)
- `SKILL.md` lines 39-40: Update Phase 0 instruction to read file instead of parsing inline block (~2 lines changed)

**Total:** ~8 lines changed in triage script + ~2 lines in SKILL.md. This is a **purely additive change** — the existing inline `<triage_data>` block can be kept as fallback during transition.

### Is this purely a Python change or does SKILL.md also need updating?

Both, but minimally. SKILL.md Phase 0 currently says:
> Extract the `<triage_data>` JSON block from the stop hook output.

This would change to:
> Read `<triage_data_file>` path from the stop hook output. Load JSON from that file.

**One sentence change in SKILL.md.**

---

## Summary: Feasibility Matrix

| Approach | Buildable? | Effort | Key Risk | Code Locations |
|----------|-----------|--------|----------|----------------|
| **Agent hook (Rank 1)** | YES — Stop supports `type: "agent"` | Low (2 lines in hooks.json) | Subagent isolation unknown — needs 10-min empirical test | `hooks/hooks.json` lines 9-11 |
| **Deferred mode (Rank 2)** | YES — fully buildable | Low (~25 lines total) | Context file staleness if user waits weeks | `memory_triage.py` lines 1096-1132; `memory_retrieve.py` after line 429 |
| **Fix A (externalize triage_data)** | YES | Very Low (~10 lines) | None — purely additive | `memory_triage.py` lines 950-953, 1117-1131; `SKILL.md` lines 39-40 |
| **Fix B (single Task subagent for saves)** | YES — guards allow it | Medium (~25 SKILL.md lines) | CUD resolution context passing complexity | `SKILL.md` lines 188-212 |

## Recommendation: Test Order

1. **Agent hook test (10 min):** Edit `hooks/hooks.json` line 9 (`"type": "agent"`). Observe whether tool calls appear in parent transcript. If isolated → implement agent hook as primary solution.

2. **If agent hook NOT isolated:** Implement deferred mode (Rank 2) + Fix A as dual-mode config. This requires:
   - `memory_triage.py`: ~20 lines to support `save_mode: "deferred"`
   - `memory_retrieve.py`: ~15 lines to detect `.triage-pending.json`
   - `SKILL.md`: 2 lines for Phase 0 update
   - `memory-config.json`: Add `save_mode` field (default: `"optimized"`)

3. **Fix B (single Task for saves):** Implement regardless of above — it reduces noise even in optimized mode.

---

## Important Note: SessionStart Hook Availability

The synthesis mentions a "SessionStart confirmation mechanism." Per official docs:

> `SessionStart`, `SessionEnd`, and `Notification` hooks are only available in the TypeScript SDK. **The Python SDK does not support these events** due to setup limitations.

However, `SessionStart` IS listed as a hook event in the Claude Code hooks reference (for `type: "command"` hooks). The Python SDK limitation refers to the agent SDK, not Claude Code's own hook system. For Claude Code plugins using `hooks.json`, `SessionStart` supports `type: "command"`.

This means a SessionStart hook to detect and notify about pending saves is buildable as a `type: "command"` hook calling a Python script — the same pattern used by all existing hooks.
