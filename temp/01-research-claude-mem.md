# Research: claude-mem Architecture Analysis

## Executive Summary

claude-mem (v10.1.0, 28K+ GitHub stars) is a Claude Code plugin for persistent memory across sessions. Its **most critical architectural decision** is using `type: "command"` for ALL hooks -- including Stop hooks. This completely avoids the JSON validation errors that plague our `type: "prompt"` Stop hooks. However, claude-mem introduces significant complexity (Bun daemon, SQLite, Chroma, SDK subprocess spawning) that has led to severe memory leak issues ($183/day API waste, 65GB RAM from 280 orphaned processes).

---

## 1. Hook Architecture: How claude-mem Handles Stop Hooks

### Hook Configuration (plugin/hooks/hooks.json)

claude-mem uses **5 lifecycle hook events** with 6 hook scripts, ALL using `type: "command"`:

```json
{
  "Stop": [
    {
      "hooks": [
        {
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/scripts/bun-runner.js\" \"${CLAUDE_PLUGIN_ROOT}/scripts/worker-service.cjs\" start",
          "timeout": 60
        },
        {
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/scripts/bun-runner.js\" \"${CLAUDE_PLUGIN_ROOT}/scripts/worker-service.cjs\" hook claude-code summarize",
          "timeout": 120
        },
        {
          "type": "command",
          "command": "node \"${CLAUDE_PLUGIN_ROOT}/scripts/bun-runner.js\" \"${CLAUDE_PLUGIN_ROOT}/scripts/worker-service.cjs\" hook claude-code session-complete",
          "timeout": 30
        }
      ]
    }
  ]
}
```

**Key observation:** The Stop hook uses **3 sequential command hooks** in a single matcher group:
1. Ensure worker daemon is running (start if needed)
2. Send summarize request via HTTP to worker
3. Mark session as complete (cleanup)

### Why `type: "command"` Avoids JSON Validation Errors

When a hook uses `type: "command"`:
- Claude Code executes the command directly (shell/subprocess)
- The command's **stdout** is the hook's output
- The command's **exit code** determines success/failure:
  - Exit 0: success, stdout added to context (for SessionStart/UserPromptSubmit)
  - Exit 2: blocking error, stderr shown to user
  - Other non-zero: stderr shown in verbose mode only
- **No LLM call is involved**, so no JSON validation of LLM output occurs

When a hook uses `type: "prompt"`:
- Claude Code internally calls an LLM with the prompt
- The LLM response must conform to Claude Code's expected JSON structure
- If the LLM responds with natural language, markdown, or any non-conforming format, **JSON validation fails**
- This is our exact problem: 6 prompt hooks x JSON validation failure = 6 errors per stop

### claude-mem's Hook Output Format

For non-context hooks (Stop, PostToolUse), claude-mem outputs:
```json
{"continue": true, "suppressOutput": true}
```

For context hooks (SessionStart), it outputs:
```json
{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}
```

Source: `src/cli/adapters/claude-code.ts` and `src/hooks/hook-response.ts`

---

## 2. Data Flow: How the Stop Hook Works

### Step-by-Step Execution

1. **Claude Code fires Stop event** with stdin payload containing `{session_id, transcript_path, cwd}`

2. **bun-runner.js** launches the compiled worker-service.cjs with `hook claude-code summarize`

3. **hook-command.ts** orchestrates:
   - Reads JSON from stdin (self-delimiting parser, no EOF wait)
   - Selects claude-code adapter (normalizes input fields)
   - Dispatches to summarize handler

4. **summarize.ts** handler:
   - Calls `ensureWorkerRunning()` to verify daemon is alive
   - Extracts last assistant message from transcript file (local file read, no LLM)
   - Sends HTTP POST to `http://127.0.0.1:37777/api/sessions/summarize`
   - Returns `{continue: true, suppressOutput: true}`

5. **Worker daemon** (running separately) receives the HTTP request and:
   - Queues the summarization work
   - Uses Claude SDK (spawns a Claude subprocess) for AI-powered summarization
   - Stores results in SQLite database

### Critical Insight: Separation of Hook Execution from AI Processing

The hook itself is **fast and deterministic** -- it just reads a local file and makes an HTTP call. The AI processing (summarization via Claude SDK) happens **asynchronously in the worker daemon**, completely decoupled from the hook lifecycle. This means:

- The hook always returns quickly (within the 120s timeout)
- The hook always outputs valid JSON
- AI processing errors don't cascade to hook errors
- If the worker is down, the hook degrades gracefully (returns success, skips processing)

---

## 3. Memory Leak Issue: Root Cause Analysis

### The Problem (Issues #1089, #1090)

The worker daemon spawns Claude CLI subprocesses via the Agent SDK for AI-powered summarization. These subprocesses were never properly terminated:

**Issue #1089:** After ~17 hours, 48 orphaned processes consuming ~2.3GB RAM
**Issue #1090:** 280 orphaned processes consuming ~65GB RAM, $183/day in unintended API spend

### Root Causes (from ProcessRegistry.ts documentation)

1. **SDK's SpawnedProcess interface hides subprocess PIDs** -- can't track what was spawned
2. **deleteSession() doesn't verify subprocess exit** before cleanup
3. **abort() is fire-and-forget** with no confirmation that processes actually died
4. **Same session ID resumed dozens of times in parallel** without killing previous instances

### Fix Attempted (v10.0.8)

Added `ProcessRegistry.ts` with:
- PID tracking via SDK's `spawnClaudeCodeProcess` option
- Session-to-process mapping
- Exit verification with timeout + SIGKILL escalation
- Concurrency pool with configurable `CLAUDE_MEM_MAX_CONCURRENT_AGENTS` (default: 2)
- Safety net orphan reaper running every 5 minutes

**Status:** Fix deployed in v10.0.8 (Feb 16, 2026) but issues #1089 and #1090 are still open.

### Other Stop Hook Issues

**Issue #1060:** "Failed with non-blocking status code: 46" -- caused by a build artifact (unterminated string literal in bundled worker-service.cjs). This is a build/packaging issue, not an architectural one.

**Issue #1042:** Race condition reading package.json during shutdown -- ENOENT error in stop hooks.

---

## 4. Strengths Worth Adopting

### 4.1 `type: "command"` for Stop Hooks (CRITICAL)

The single most important pattern. By using command hooks, claude-mem completely eliminates the JSON validation error class. The hook outputs deterministic JSON, not LLM-generated text.

**Applicability to our project:** Direct. Switch our 6 `type: "prompt"` Stop hooks to `type: "command"`. This is the fundamental fix.

### 4.2 Graceful Degradation Pattern

Every handler follows the same pattern:
```typescript
const workerReady = await ensureWorkerRunning();
if (!workerReady) {
  return { continue: true, suppressOutput: true, exitCode: 0 };
}
```

And in hook-command.ts, transport errors (ECONNREFUSED, timeout, etc.) exit 0 (graceful) while client bugs (4xx, TypeError) exit 2 (blocking).

**Applicability:** Excellent pattern. Our command scripts should always exit 0 and output `{continue: true}` on failure, rather than crashing.

### 4.3 Stdin Reading Without EOF Wait

claude-mem's `stdin-reader.ts` solves a real problem: Claude Code doesn't close stdin after writing hook input, so `stdin.on('end')` never fires. Their solution: try to parse accumulated input as JSON after each chunk (JSON is self-delimiting).

**Applicability:** Important if we process stdin in command hooks. Python equivalent: read stdin with a timeout, try `json.loads()` incrementally.

### 4.4 Single Hook Entry Point with Internal Routing

Instead of 6 separate Stop hooks, claude-mem uses 1 Stop hook group with 3 sequential commands that route through a single code path (hook-command.ts -> handler dispatch).

**Applicability:** We could consolidate our 6 category-specific Stop hooks into a single command hook that runs a Python triage script handling all categories internally.

### 4.5 Transcript Parsing for Context

The `extractLastMessage()` function reads the transcript JSONL file to get conversation content without requiring `type: "prompt"` access to context. This is how `type: "command"` hooks can still reason about conversation content.

**Applicability:** Critical pattern. If we switch to `type: "command"`, we can read the transcript file (path provided via stdin's `transcript_path` field) to get conversation context for memory triage.

---

## 5. Weaknesses to Avoid

### 5.1 Persistent Worker Daemon (HIGH RISK)

The daemon architecture introduces:
- Process lifecycle management complexity
- Memory leak risk from subprocess spawning
- Port conflicts
- State management across sessions
- Startup reliability issues (issue #1062: Claude Code hangs on startup)

**Our advantage:** We use simple Python scripts that spawn, execute, and exit. Zero state management, zero leak risk.

### 5.2 AI Subprocess Spawning (CRITICAL RISK)

Spawning full Claude CLI subprocesses for summarization is the direct cause of the memory leak. Each subprocess consumes ~45MB RSS and API tokens continuously.

**Better alternative:** If AI processing is needed, make a direct API call (e.g., `requests.post()` to Anthropic API with Haiku model) within the Python script itself. This is bounded, synchronous, and self-cleaning.

### 5.3 Complex Runtime Dependencies

claude-mem requires: Bun, Node.js, esbuild (build), SQLite (bun:sqlite), Chroma vector DB, onnxruntime. This creates a fragile dependency chain with platform-specific failures (Windows Git Bash hangs, ONNX binary resolution failures, Chroma server crashes).

**Our advantage:** stdlib-only Python scripts with optional pydantic. Much simpler.

### 5.4 No Conversation Context in Stop Hook Decision

claude-mem's Stop hook doesn't decide *whether* to save -- it always sends the last assistant message to the worker. The AI triage happens in the worker daemon. If we want intelligent triage at hook time without a daemon, we need a different approach.

---

## 6. Applicable Patterns for Our Fix

### Recommended Architecture: "Command Hook + Local Triage"

Based on claude-mem analysis, the optimal approach for our project:

```
Stop Hook (type: "command")
    |
    v
Python triage script (memory_stop_triage.py)
    |
    ├── Read transcript_path from stdin JSON
    ├── Parse last N messages from transcript JSONL
    ├── Apply keyword/pattern matching per category
    │   (session_summary, decision, runbook, constraint, tech_debt, preference)
    ├── If matches found:
    │   ├── Option A: Write staging file for next session to process
    │   └── Option B: Direct API call to fast model (Haiku) for summarization
    ├── Output: {"continue": true, "suppressOutput": true}
    └── Exit 0 (always, even on error)
```

### Key Design Decisions

1. **Single command hook** replaces 6 prompt hooks -- eliminates all JSON validation errors
2. **Read transcript file** for conversation context (like claude-mem's transcript-parser.ts)
3. **Local pattern matching** for triage (like our existing memory_candidate.py)
4. **No daemon** -- script runs and exits, zero leak risk
5. **Always exit 0** -- graceful degradation on any error
6. **Optional LLM call** -- if needed, direct API call within script (not subprocess spawn)

### Comparison Table

| Aspect | Our Current | claude-mem | Proposed |
|--------|-------------|------------|----------|
| Hook type | `prompt` | `command` | `command` |
| JSON validation risk | HIGH | NONE | NONE |
| Hook count (Stop) | 6 parallel | 3 sequential | 1 |
| AI processing | In-hook (LLM) | Daemon (SDK) | Optional (API call) |
| Memory leak risk | None | SEVERE | None |
| Complexity | Low | Very High | Low-Medium |
| Dependencies | Python stdlib | Bun+Node+SQLite+Chroma | Python stdlib |
| Conversation access | Via $ARGUMENTS | Via transcript_path | Via transcript_path |
| Failure mode | JSON errors | Daemon crashes, leaks | Silent skip |

---

## 7. Critical Question Answers

### Q: How does claude-mem handle the Stop hook?
**A:** Three sequential `type: "command"` hooks: (1) ensure worker running, (2) HTTP POST to worker with last assistant message extracted from transcript file, (3) session cleanup. No LLM call in the hook itself.

### Q: Does it avoid JSON validation issues?
**A:** Yes, completely. By using `type: "command"`, the hook outputs deterministic JSON (`{continue: true, suppressOutput: true}`), never LLM-generated text. JSON validation errors are structurally impossible.

### Q: What is their approach to memory triage/categorization?
**A:** No category-based triage at hook time. The Stop hook sends the raw last assistant message to the worker daemon, which uses Claude SDK agents for AI-powered observation/summarization. Categories emerge from the AI processing, not from the hook structure.

### Q: What causes the memory leak issue?
**A:** The worker daemon spawns Claude CLI subprocesses (via Agent SDK) for AI summarization. These processes were never terminated because: (a) SDK hides subprocess PIDs, (b) session cleanup didn't verify process exit, (c) abort was fire-and-forget. Processes accumulated over days (280 processes, 65GB RAM, $183/day API spend). Partially fixed in v10.0.8 with ProcessRegistry.

### Q: What patterns should we adopt while avoiding the memory leak?
**A:** Adopt: `type: "command"` hooks, graceful degradation (always exit 0), transcript file reading for context, single consolidated hook. Avoid: daemon architecture, subprocess spawning, complex runtime dependencies. If AI processing is needed, use a direct bounded API call within the script, not a persistent daemon with subprocess spawning.

---

## 8. External Perspective (Gemini 3 Pro)

Gemini's analysis confirms:
- **Approach C (Hybrid)** offers the best reliability-to-complexity ratio
- The core issue is `type: "prompt"` interface, not LLM usage per se
- Two-stage triage recommended: fast keyword filter, then optional direct API call
- Avoid: daemon architecture, vector DBs, subprocess spawning for personal memory systems
- Single entry point script routing to category handlers is cleaner than 6 separate hooks

---

## Appendix: Key Source Files Analyzed

| File | Purpose |
|------|---------|
| `plugin/hooks/hooks.json` | Hook configuration -- all `type: "command"` |
| `src/cli/hook-command.ts` | Hook dispatcher with graceful degradation |
| `src/cli/handlers/summarize.ts` | Stop hook handler -- HTTP POST to worker |
| `src/cli/handlers/session-complete.ts` | Stop hook phase 2 -- session cleanup |
| `src/cli/adapters/claude-code.ts` | Formats output for Claude Code hooks |
| `src/cli/stdin-reader.ts` | Stdin reader with JSON self-delimiting parser |
| `src/cli/types.ts` | NormalizedHookInput, HookResult interfaces |
| `src/hooks/hook-response.ts` | Standard hook response constant |
| `src/shared/hook-constants.ts` | Exit codes and timeout constants |
| `src/shared/transcript-parser.ts` | Extracts messages from transcript JSONL |
| `src/services/worker/SDKAgent.ts` | AI agent spawning (memory leak source) |
| `src/services/worker/ProcessRegistry.ts` | Process tracking (memory leak fix) |
| GitHub Issues #1089, #1090 | Memory leak reports |
| GitHub Issue #1060 | Stop hook non-blocking error |
