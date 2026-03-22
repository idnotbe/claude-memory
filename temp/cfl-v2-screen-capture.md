# CFL v2: Claude Code Screen/TUI Capture Research

**Date**: 2026-03-22
**Purpose**: Comprehensive research on capturing Claude Code's full TUI/screen output for the closed feedback loop
**Cross-model validation**: Codex 5.3, Gemini 3.1 Pro

---

## 1. The Problem Statement

Claude Code's TUI renders information that does NOT appear in any programmatically accessible log:

- Hook stdout/stderr (the JSON a hook prints to stdout is consumed by Claude Code but not logged)
- User permission responses (when a user clicks Allow/Deny in a Guardian approval dialog)
- Hook status messages (e.g., "Evaluating session for memories...")
- Progress spinners and status bar content
- Stop hook injected messages (the text bubbles shown after hook fires)

The transcript JSONL and stream-json output both have gaps. This document catalogs every capture mechanism, its capabilities, and limitations.

---

## 2. Existing Data Sources

### 2.1 Transcript JSONL (`~/.claude/projects/*/UUID.jsonl`)

**Location**: `~/.claude/projects/-home-idnotbe-projects-ops/<session-uuid>.jsonl`

**Event types observed**:
| Type | Contains | Missing |
|------|----------|---------|
| `user` | User messages, tool_result content | - |
| `assistant` | Model responses, tool_use requests | - |
| `progress` | `hook_progress` with hookEvent, hookName, command | Hook stdout/stderr, hook JSON output, decision reason |
| `queue-operation` | Enqueue/remove with content (task descriptions, user input) | User's allow/deny response |
| `file-history-snapshot` | File backup metadata | - |
| `system` | System messages | - |

**Key finding**: `hook_progress` events show that a hook ran, but NOT what it returned. The hook's JSON output (`{"hookSpecificOutput": {"permissionDecision": "deny", ...}}`) is consumed by Claude Code internally and discarded.

**Example hook_progress event**:
```json
{
  "type": "progress",
  "data": {
    "type": "hook_progress",
    "hookEvent": "PreToolUse",
    "hookName": "PreToolUse:Bash",
    "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/bash_guardian.py\""
  },
  "toolUseID": "toolu_01WZQbHQac5RhszKYzhjWXJ9"
}
```

### 2.2 Stream-JSON Output (`claude -p --output-format stream-json --verbose`)

**Requirements**: `--verbose` flag is REQUIRED with `--output-format stream-json` (verified on v2.1.81).

**Events emitted**:
| Event | Data |
|-------|------|
| `system/init` | Full session config: tools, plugins, MCP servers, model, permission_mode, agents, skills |
| `assistant` | Model messages with content blocks (text, tool_use) |
| `rate_limit_event` | Rate limit status, reset time |
| `result/success` | Duration, cost, usage, `permission_denials[]`, stop_reason |

**Key finding**: Stream-JSON does NOT include:
- `hook_progress` events
- Hook execution details
- Permission dialog interactions
- Status bar / spinner content

**The `permission_denials` array** in the `result` event exists but was empty in all test sessions. Its exact population conditions are unclear.

**Important**: `-p` mode (non-interactive) skips permission dialogs entirely. Tools are either auto-allowed or auto-denied based on `--permission-mode`. So this mode fundamentally cannot capture interactive approval flows.

### 2.3 Guardian's Own Log (`.claude/guardian/guardian.log`)

**Location**: `<project>/.claude/guardian/guardian.log`

**Format**: Timestamped text log with ALLOW/DENY/ASK decisions.

**Example**:
```
2026-03-22T14:08:00 [WARN] No regex timeout defense available.
2026-03-22T14:08:01 [ALLOW] python3 "/home/.../memory_write.py" ...
2026-03-22T14:07:40 [ALLOW] Write: ...ops/.claude/memory/.staging/intent-session_summary.json
```

**Contains**: Guardian's allow/deny decisions with truncated paths
**Missing**: User's response to "ask" prompts, hook execution timing, full context

### 2.4 Debug Mode (`--debug "hooks" --debug-file <path>`)

**Flags**:
- `--debug [filter]`: Enable debug mode, optional category filter (e.g., "hooks", "api,hooks", "!1p,!file")
- `--debug-file <path>`: Write debug logs to file (implicitly enables debug)
- `--debug-to-stderr`: Hidden flag (found in binary strings, not in `--help`)

**Expected content**: Hook registration, execution, and hook input/output JSON (per Anthropic docs). Not independently verified in this research due to auth constraints in `-p` mode.

### 2.5 Session Directories

**Location**: `~/.claude/projects/*/<session-uuid>/`

Contains:
- `tool-results/toolu_*.txt`: Large tool outputs that exceeded inline size limits
- File history snapshots

Does NOT contain: Hook decision logs, TUI state, permission responses.

---

## 3. Capture Mechanisms Investigated

### 3.1 `script` Command (Linux)

**Availability**: `/usr/bin/script` (present on this system)

**Usage**:
```bash
script -O out.log -T timing.log -m advanced -f -c 'claude ...'
# or simpler:
script -q -c "claude -p --verbose --output-format stream-json 'prompt'" output.log
```

**Capabilities**:
- Captures full PTY output including ANSI escape sequences
- Includes everything rendered to terminal
- Supports stdin/stdout/timing separation (`-I`, `-O`, `-T` flags)
- Can run non-interactively with `-c` flag

**Limitations**:
- Raw ANSI escape sequences mixed with content
- Requires post-processing through a terminal emulator library (e.g., Python `pyte`) to extract semantic content
- Fragile: breaks when Anthropic changes TUI layout/styling
- Not suitable for production data extraction

**Verdict**: Debugging tool only. Not for production feedback loops.

### 3.2 `tmux pipe-pane`

**Availability**: `/usr/bin/tmux` (present on this system)

**Usage**:
```bash
tmux pipe-pane -o 'cat >> ~/claude-session.log'
```

**Capabilities**:
- Captures pane output in real-time to a file
- Works with existing tmux workflow
- Can be enabled/disabled dynamically

**Limitations**: Same ANSI parsing issues as `script`.

**Verdict**: Good for ad-hoc debugging if already using tmux.

### 3.3 `asciinema` / `termtosvg` / `ttyrec`

**Availability**: None installed on this system.

**Capabilities**:
- asciinema: Records terminal sessions as `.cast` files (JSON-based), supports replay
- termtosvg: Produces SVG animations
- ttyrec: Raw terminal recording format

**Limitations**:
- Still raw terminal output, not structured data
- asciinema's `.cast` format is slightly easier to parse than raw ANSI
- All require installation

**Verdict**: Marginally better than `script` for archival, but same fundamental limitation.

### 3.4 `tee` in hooks.json Commands

**Source**: Gemini 3.1 Pro suggestion

**Usage**:
```json
"command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write_guard.py\" | tee -a /tmp/hook_decisions.jsonl"
```

**Capabilities**:
- Captures hook stdout (the JSON decision) before Claude Code consumes it
- Zero-infrastructure: just a pipe
- Structured JSON output, no ANSI parsing needed
- Per-hook granularity

**Limitations**:
- **Guardian compatibility risk**: Guardian's bash_guardian.py performs Layer 2 command decomposition on pipe chains. The `tee` pipe may trigger Guardian's compound command analysis, potentially causing false positive blocks or infinite recursion if Guardian inspects its own hook command.
- Only captures hook stdout, not the user's subsequent allow/deny response
- Does not capture hooks from OTHER plugins (only your own hooks.json)
- File management (rotation, cleanup) needed

**Verdict**: Promising for debugging, but needs Guardian compatibility testing before production use.

### 3.5 Hook-Internal Audit Logging

**Current state**: `memory_logger.py` already provides structured JSONL logging for the claude-memory plugin.

**Approach**: Each hook script writes its own decision to a structured audit log:
```python
# In each hook script, before printing the JSON decision:
import json, time
decision = {"hookSpecificOutput": {"permissionDecision": "allow", ...}}
audit_entry = {
    "timestamp": time.time(),
    "hook": "PreToolUse:Write",
    "session_id": os.environ.get("CLAUDE_SESSION_ID", ""),
    "tool_input": tool_input_summary,
    "decision": decision,
}
with open(audit_log_path, "a") as f:
    f.write(json.dumps(audit_entry) + "\n")
print(json.dumps(decision))  # Normal hook output
```

**Capabilities**:
- Full control over what's logged
- Structured, parseable output
- No external dependencies
- Already partially implemented via memory_logger.py
- Works regardless of Claude Code version or mode

**Limitations**:
- Only captures YOUR hooks' decisions, not other plugins'
- Cannot capture the user's manual allow/deny response to "ask" prompts
- Requires modifying each hook script

**Verdict**: RECOMMENDED primary approach. Highest reliability, lowest risk.

### 3.6 PermissionRequest Hook (Documented but Unverified)

**Source**: Codex 5.3 finding from Anthropic docs

**Concept**: A hook event type that fires when a permission dialog is about to be shown to the user. It receives `tool_name`, `tool_input`, `permission_suggestions` and can return `allow` or `deny` on behalf of the user.

**Capabilities (if available)**:
- Intercepts the exact moment before a permission dialog appears
- Can auto-decide, eliminating the dialog entirely
- Structured input/output

**Limitations**:
- **Version verification needed**: Not confirmed as a supported hook event type in the current hooks.json schema. May be SDK-only (for headless/API use), not available to plugin hooks.
- May conflict with Guardian's own PreToolUse hooks
- If it auto-decides, it changes the UX (user loses manual approval)

**Verdict**: Investigate further. If available as a hooks.json event type, this is the cleanest way to capture/control permission decisions. But likely SDK-only.

### 3.7 Notification Hook (Documented but Unverified)

**Source**: Codex 5.3 finding from Anthropic docs

**Concept**: Fires on `permission_prompt` and `elicitation_dialog` events with `message`, `title`, `notification_type`.

**Capabilities (if available)**:
- Captures dialog text in structured form
- Does NOT capture user's response (only the prompt shown)

**Verdict**: Same as PermissionRequest -- needs version/availability verification.

### 3.8 NODE_OPTIONS Monkey-Patching

**Source**: Gemini 3.1 Pro suggestion

**Usage**:
```bash
NODE_OPTIONS="--require ./spy.js" claude
```

**Capabilities**:
- Can intercept `child_process.spawn` to log all subprocess activity
- Can intercept `process.stdout.write` for raw output capture
- Deep visibility into Claude Code internals

**Limitations**:
- Extremely fragile: breaks on any Claude Code update
- Security concern: modifying a tool's runtime behavior
- May violate Claude Code's terms of service
- Native binary (v2.1.81) may not support Node.js injection

**Verdict**: DO NOT USE. Too fragile and risky for any use case.

### 3.9 BYO (Bring Your Own) Dialog via /dev/tty

**Source**: Gemini 3.1 Pro suggestion

**Concept**: Instead of returning `"permissionDecision": "ask"`, have the hook script directly prompt the user via `/dev/tty` and log the response.

**Limitations**:
- Bypasses Claude Code's native permission system
- Incompatible with `-p` (non-interactive) mode
- May conflict with Claude Code's TUI rendering (Ink/React-based)
- Would require increasing hook timeout to accommodate human response time
- Fundamentally changes the UX

**Verdict**: Creative but impractical. The Guardian plugin already handles this flow correctly through Claude Code's native mechanism.

### 3.10 Hidden CLI Flag: `--permission-prompt-tool`

**Source**: Codex 5.3 finding (confirmed present in binary, hidden from `--help`)

**Concept**: Accepts a tool name that handles permission prompts in headless/SDK mode.

**Relevance**: For headless flows only. Not applicable to interactive TUI capture.

---

## 4. What's On Screen vs What's In Logs

| Screen Element | Transcript JSONL | Stream-JSON | Guardian Log | Hook Audit |
|----------------|-----------------|-------------|--------------|------------|
| User input | Yes | No | No | No |
| Model response | Yes | Yes | No | No |
| Tool use request | Yes | Yes | No | No |
| Tool result | Yes | No | No | No |
| Hook running (spinner) | Yes (hook_progress) | No | No | No |
| Hook decision (allow/deny/ask) | **NO** | **NO** | Yes (own hooks only) | **YES** (if implemented) |
| Permission dialog text | **NO** | **NO** | Partial | **NO** |
| User approval response | **NO** | **NO** | **NO** | **NO** |
| Stop hook injected message | Yes (as user message) | No | No | **YES** (if implemented) |
| Status bar content | **NO** | **NO** | **NO** | **NO** |
| Memory triage output | Yes (as user message) | No | No | **YES** (already logged) |

---

## 5. Cross-Model Validation Summary

### Codex 5.3 Key Contributions
1. **Confirmed** `--verbose` is required for stream-json (runtime validated)
2. **Discovered** `PermissionRequest` and `Notification` hook types from official docs
3. **Found** hidden `--permission-prompt-tool` flag in binary
4. **Found** hidden `--debug-to-stderr` flag
5. **Validated** that `queue-operation` events are not reliable for permission tracking (used for generic queue operations)
6. **Recommended** building around PreToolUse + PermissionRequest + Notification rather than TUI scraping

### Gemini 3.1 Pro Key Contributions
1. **Proposed** `tee` pipe in hooks.json for zero-infrastructure hook stdout capture
2. **Confirmed** PostToolUse cannot capture denials (only fires on tool execution success)
3. **Warned** that PTY parsing via `pyte`/`libvterm` is fragile and will break on TUI changes
4. **Proposed** NODE_OPTIONS monkey-patching (creative but too risky)
5. **Proposed** BYO dialog via `/dev/tty` (creative but impractical)
6. **Correctly identified** Claude Code as likely Ink/React-based TUI with no DOM access

### Agreement Points (Both Models)
- Avoid TUI scraping for production use
- Hook-internal structured logging is the most reliable approach
- `script`/`tmux pipe-pane` are debugging tools only
- The user's manual allow/deny response is the hardest data to capture

### Disagreement Points
- Codex emphasized documented API surfaces (PermissionRequest, Notification hooks)
- Gemini emphasized pragmatic workarounds (tee, /dev/tty, NODE_OPTIONS)
- Neither could confirm PermissionRequest/Notification are available as plugin hook event types (vs SDK-only)

---

## 6. Vibe Check Summary

**Assessment**: Research is thorough but risks overtooling. The simplest solution is already partially in place.

**Pattern warnings**:
- Complex Solution Bias: Six capture mechanisms when hook-internal logging covers 90% of needs
- Scope drift: Original problem "screen info not in logs" has simplest fix: make hooks log more
- Guardian compatibility: `tee` pipe needs testing before recommendation

---

## 7. Recommended Approach

### Tier 1: Hook-Internal Audit Logging (IMPLEMENT NOW)

**Zero new infrastructure. Highest reliability.**

Each hook script should write structured audit entries to a JSONL file before printing its decision. The claude-memory plugin already has `memory_logger.py` for this pattern.

**What it captures**: Hook input, decision, reason, timing, session context.
**What it misses**: User's manual allow/deny response to "ask" prompts, other plugins' decisions.

### Tier 2: `tee` Pipe for Cross-Plugin Visibility (TEST FIRST)

Add `| tee -a <audit_log>` to hooks.json commands for hooks you control.

**Before deploying**: Verify that Guardian's bash_guardian.py Layer 2 command decomposition does not flag the pipe as suspicious. Test with a Guardian-enabled session.

### Tier 3: Terminal Recording for Debugging (AS-NEEDED)

```bash
script -O ~/claude-debug.log -T ~/claude-timing.log -m advanced -f -c 'claude'
```

Use only for ad-hoc debugging sessions where you need to see exactly what was rendered on screen.

### Tier 4: PermissionRequest/Notification Hooks (INVESTIGATE)

Verify whether these hook event types are available in the plugin hooks.json schema (not just SDK). If available, they provide the cleanest path to capturing permission dialog data.

### NOT Recommended
- NODE_OPTIONS monkey-patching (fragile, risky)
- BYO /dev/tty dialogs (UX conflict, mode incompatibility)
- Production reliance on ANSI terminal scraping (fragile)
- strace/ptrace (overkill, same raw data as `script`)

---

## 8. Implementation Priority for CFL

For the closed feedback loop in claude-memory:

1. **Immediate**: Ensure `memory_logger.py` captures all hook decisions (triage, retrieval, write guard, staging guard, validation) with sufficient detail for post-session analysis
2. **Short-term**: Add `--debug "hooks" --debug-file <path>` to automated/CI sessions to capture Claude Code's own hook debug output
3. **Medium-term**: Test `tee` approach with Guardian; if compatible, add to hooks.json
4. **Long-term**: Monitor Claude Code releases for PermissionRequest/Notification hook support in plugin context

---

## 9. References

- Claude Code CLI help: `claude --help` (v2.1.81)
- Hooks reference: https://code.claude.com/docs/en/hooks
- Headless SDK: https://docs.claude.com/en/docs/claude-code/sdk/sdk-headless
- SDK permissions: https://docs.claude.com/en/docs/claude-code/sdk/sdk-permissions
- Guardian plugin: `/home/idnotbe/projects/claude-code-guardian/`
- Memory plugin hooks: `/home/idnotbe/projects/claude-memory/hooks/hooks.json`
- Memory logger: `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_logger.py`
- Guardian utilities: `/home/idnotbe/projects/claude-code-guardian/hooks/scripts/_guardian_utils.py`
