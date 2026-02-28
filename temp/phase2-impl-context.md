# Phase 2: Fix B — Phase 3 Single Task Subagent Implementation Context

## Goal
Move Phase 3 save operations from the main agent into a single foreground Task subagent. The main agent performs CUD resolution (2-3 lines), then spawns ONE Task subagent that executes all save commands (30-50 lines hidden). This reduces visible noise from ~30-50 lines to ~3 lines.

## Pre-requisite: 5-min Subagent Isolation Test
Before implementing, verify that Task subagent tool calls don't appear in the main transcript. Quick test:
- Spawn a Task subagent that runs `echo "ISOLATION_MARKER"` via Bash
- Check if the echo output appears in the main conversation
- If NOT isolated: Phase 2's noise reduction drops from 85% to 60% — still worth doing but expectations must be calibrated

## Current Architecture (SKILL.md Phase 3, lines 209-263)
Main agent directly executes:
1. CUD resolution (decision table)
2. For each verified draft: `memory_write.py --action create/update/retire ...`
3. `memory_enforce.py --category session_summary` (if applicable)
4. Staging cleanup: `rm -f .staging/triage-data.json .staging/context-*.txt ...`
5. Result file write: `~/.claude/last-save-result.json`

All Bash calls visible in main transcript → 30-50+ lines of noise.

## Target Architecture
```
Main Agent:
  1. Collect Phase 1/2 results
  2. Apply CUD resolution table → produce action list
  3. Spawn ONE Task subagent with the pre-computed action list
  4. Output brief summary from Task return value

Task Subagent (invisible to user):
  1. Execute each command in order
  2. Run memory_enforce.py if session_summary was created
  3. Clean staging files
  4. Write result file (~/.claude/last-save-result.json)
  5. Return summary: {categories_saved, titles, errors}
```

## Key Design Decisions

### CUD Resolution stays on Main Agent
- CUD decisions require Phase 1/2 context (which main agent has)
- Prevents subagent hallucination on CUD judgment
- CUD decision output is ~2-3 lines (minimal noise)

### Commands passed in Task prompt, not via file
- Main agent includes exact commands in Task prompt
- No additional file I/O overhead
- Commands include absolute paths (CLAUDE_PLUGIN_ROOT resolved by main agent)

### Error Handling
On subagent failure/timeout:
1. Main agent detects error from Task return
2. Write `.staging/.triage-pending.json` sentinel:
   ```json
   {
     "timestamp": "ISO 8601 UTC",
     "categories": ["decision", "runbook"],
     "reason": "subagent_timeout"
   }
   ```
3. Preserve staging files (don't delete triage-data.json, context-*.txt)
4. Phase 4's memory_retrieve.py pending detection handles the rest

### Post-save Result File
The Task subagent writes the result file as the last operation:
```bash
mkdir -p "$HOME/.claude"
cat > "$HOME/.claude/.last-save-result.tmp" <<'__MEMORY_SAVE_RESULT_EOF__'
{...json...}
__MEMORY_SAVE_RESULT_EOF__
mv -f "$HOME/.claude/.last-save-result.tmp" "$HOME/.claude/last-save-result.json"
```

## SKILL.md Changes Required

### Phase 3 Section (lines 209-263) — Full Rewrite
Replace "Phase 3: Save (Main Agent)" with "Phase 3: Save (Subagent)"

New content:
```markdown
### Phase 3: Save (Subagent)

The main agent performs CUD resolution, then delegates execution to a Task subagent.

**Step 1: CUD Resolution (Main Agent)**
Collect all Phase 1 (Draft) and Phase 2 (Verify) results. Apply the CUD Verification Rules table to determine the final action for each category:
- For each category: state the CUD resolution (CREATE/UPDATE/RETIRE/NOOP) and one-line justification.
- Build the list of exact commands to run.

**Step 2: Spawn Save Subagent**
Spawn ONE foreground Task subagent (model: haiku) with the pre-computed command list:

```
Task(
  model: "haiku",
  subagent_type: "general-purpose",
  prompt: "Execute these memory save commands in order. For each command, run it via Bash and report the result. After ALL commands complete, clean up staging and write the result file.

Commands:
1. python3 \"<plugin_root>/hooks/scripts/memory_write.py\" --action <action> --category <cat> --target <path> --input <draft> [--hash <md5>]
[... more commands ...]
N. python3 \"<plugin_root>/hooks/scripts/memory_enforce.py\" --category session_summary

Cleanup (after all commands):
rm -f .claude/memory/.staging/triage-data.json .claude/memory/.staging/context-*.txt .claude/memory/.staging/.triage-handled .claude/memory/.staging/.triage-pending.json

Result file (after cleanup):
mkdir -p \"$HOME/.claude\"
cat > \"$HOME/.claude/.last-save-result.tmp\" <<'__MEMORY_SAVE_RESULT_EOF__'
{JSON with saved_at, project, categories, titles, errors}
__MEMORY_SAVE_RESULT_EOF__
mv -f \"$HOME/.claude/.last-save-result.tmp\" \"$HOME/.claude/last-save-result.json\"

Return a summary: which categories saved, which failed, any errors."
)
```

**Step 3: Error Handling**
If the Task subagent fails or times out:
- Write `.staging/.triage-pending.json`:
  ```json
  {"timestamp": "ISO 8601 UTC", "categories": [...], "reason": "subagent_error"}
  ```
- Do NOT delete staging files (preserve for retry)
- The next session's UserPromptSubmit hook will detect the pending sentinel
```

### Draft Path Validation
Keep existing draft path validation note in the subagent prompt.

### venv Bootstrap
Note: `memory_write.py` uses `os.execv()` to re-exec under plugin .venv. This works in subagents since they have Bash access.

## Test Considerations
- Phase 2 changes are SKILL.md instructions (agent behavior), not Python code
- Testing is primarily integration/e2e:
  - Verify full save flow works with subagent
  - Verify error handling creates pending sentinel
  - Verify staging cleanup happens
  - Verify result file is written correctly
- Some tests from Phase 3/4 depend on Phase 2 implementation (marked as "Phase 2 의존" in action plan)

## Files to Modify
| File | Change |
|------|--------|
| skills/memory-management/SKILL.md | Rewrite Phase 3 section (lines 209-263) |
| SKILL.md Post-save section | Already exists (lines 235-263), integrate into subagent prompt |

## Rollback
Revert SKILL.md Phase 3 to main agent execution. Phase 1 changes are independent and stay.
