# Research: Alternative Hook Architectures for 100% Error-Free Stop Hooks

**Researcher:** researcher-alternatives
**Date:** 2026-02-16
**Task:** Survey all possible approaches to implement Stop hooks that guarantee zero errors

---

## 1. Comparison Matrix

| # | Approach | Error Rate | Intelligence | Latency | Cost | Complexity | Feasibility |
|---|----------|-----------|-------------|---------|------|------------|-------------|
| 1 | Command hook + keyword heuristics | **0%** | Low-Medium | <100ms | $0 | Low | Proven |
| 2 | Command hook + external LLM API | **0%** (from CC's perspective) | High | 1-5s | $$ | Medium | Proven |
| 3 | Single prompt hook (reduce 6->1) | ~15-20% per invocation | High | 2-5s | $ (built-in) | Low | Unreliable |
| 4 | Agent-type hook | ~10-15% (same JSON issue) | Very High | 5-30s | $$ | Low | Unreliable |
| 5 | SessionEnd hook (command) | **0%** | Depends on sub-approach | <100ms-5s | Depends | Low-Medium | Proven |
| 6 | Deferred/async processing | **0%** | High | 0 (non-blocking) | $$ | Medium | Proven |
| 7 | Hybrid: Command triage + optional LLM | **0%** | Medium-High | 100ms-3s | $ | Medium | **Best** |
| 8 | Command hook + consensus (multi-LLM) | **0%** | Very High | 3-10s | $$$ | High | Overkill |

**Legend:** Error Rate = probability of "JSON validation failed" error from Claude Code's perspective. Cost = API/compute cost per session.

---

## 2. Detailed Analysis

### Approach 1: Command Hook + Keyword Heuristics (No LLM)

**How it works:**
Replace all 6 `type: "prompt"` Stop hooks with `type: "command"` hooks. Each runs a Python script that:
1. Reads `transcript_path` from stdin JSON
2. Parses the JSONL transcript file
3. Uses keyword/pattern matching (similar to existing `memory_retrieve.py`) to detect memory-worthy content
4. Outputs proper JSON to stdout (exit 0 to allow stop, exit 2 with JSON to block)

**Feasibility:** HIGH. Command hooks are the most reliable hook type in Claude Code. They always produce deterministic output. The plugin already has a keyword-matching engine in `memory_retrieve.py` that can be adapted.

**Reliability:** 100%. No LLM call = no JSON validation error. The Python script fully controls stdout/stderr and exit codes. Claude Code never needs to parse LLM-generated JSON.

**Intelligence:** LOW-MEDIUM. Keyword heuristics can detect:
- Decisions: patterns like "chose X because", "decided to", "went with"
- Runbooks: error messages + resolution patterns (stack traces, "fixed by")
- Tech debt: "TODO", "deferred", "will address later", "tech debt"
- Constraints: "limitation", "API limit", "cannot", "restricted"
- Preferences: "always use", "prefer", "convention", "standard"
- Session summaries: file modification counts, tool usage patterns

Limitation: Cannot understand semantic nuance. "We discussed using React but decided not to" vs "We decided to use React" require understanding, not just keyword matching.

**Performance:** Excellent. <100ms for transcript parsing + keyword matching. Zero network calls.

**Complexity:** LOW. Builds on existing `memory_retrieve.py` patterns. Single script, no dependencies.

**Key Insight:** This approach already exists implicitly in `memory_retrieve.py` for retrieval. Extending it to triage is natural.

---

### Approach 2: Command Hook + External LLM API

**How it works:**
Replace prompt hooks with command hooks that call a Python script. The script:
1. Reads `transcript_path` from stdin JSON
2. Extracts recent conversation content from the JSONL transcript
3. Calls an external LLM API (Gemini Flash, Claude Haiku, etc.) with a triage prompt
4. Parses the LLM response within the script (with retries and fallback)
5. Outputs proper JSON to stdout based on parsed result

**Feasibility:** HIGH. This is the approach Gemini recommended, and it's architecturally sound. The key insight is that **the Python script owns the JSON output**, not the LLM. Even if the LLM returns garbage, the script can fallback gracefully.

**Reliability:** 100% from Claude Code's perspective. The script always exits with valid JSON. Internal LLM call failures are handled with:
- JSON parsing with regex fallback
- Retry logic (2-3 attempts)
- Graceful degradation: if LLM fails, allow stop (exit 0)
- Timeout handling

**Intelligence:** HIGH. External LLM provides semantic understanding comparable to prompt hooks, but with full control over the prompt, context window, and response parsing.

**Performance:** 1-5 seconds depending on LLM provider. This is blocking (Stop hooks run synchronously unless `async: true` is set).

**Cost:**
- Gemini 2.0 Flash: ~$0.10/1M input tokens, ~$0.40/1M output. Per-session cost: ~$0.001-0.005
- Claude Haiku: ~$0.25/1M input, ~$1.25/1M output. Per-session cost: ~$0.005-0.02
- Local models (Ollama): $0 but slower

**Complexity:** MEDIUM. Requires:
- API key management (environment variable)
- HTTP client (urllib3 or requests, or stdlib urllib)
- Response parsing logic
- Error handling and retries
- Token management (transcript can be large -- need truncation strategy)

**Key Risk:** Requires an API key to be available in the environment. Not all users will have this configured.

**Critical Design Decision:** Should the script call ONE LLM for all 6 categories in a single prompt, or call the LLM 6 times? Single call is faster and cheaper. 6 calls gives category-specific analysis but is 6x slower/costlier.

---

### Approach 3: Single Prompt Hook (Reduce 6 to 1)

**How it works:**
Consolidate all 6 `type: "prompt"` Stop hooks into a single prompt hook that evaluates all categories at once.

**Feasibility:** MEDIUM. The hook configuration supports this. But it doesn't solve the root cause.

**Reliability:** ~80-85%. Still uses `type: "prompt"`, which has the same JSON validation issues:
- The internal prompt hook evaluation expects `{"ok": boolean, "reason": string}` format
- The LLM (Haiku by default) sometimes prepends `{` to valid JSON
- The LLM sometimes returns natural language instead of JSON
- Known bug: prompt-based Stop hooks sometimes don't receive conversation content (GitHub issue #11786)
- Another known bug: even when hooks return `{"ok": false}`, Claude Code doesn't always block/retry (v2.0.53+)

Reducing from 6 to 1 reduces error frequency by ~6x but doesn't reach 0%.

**Intelligence:** HIGH (when it works). Same LLM evaluation as current approach.

**Performance:** 2-5 seconds. Single LLM call instead of 6 parallel ones.

**Complexity:** LOW. Just merge 6 hook configs into 1.

**Verdict:** REJECTED. Does not achieve the 100% error-free requirement. The fundamental problem is that `type: "prompt"` hooks have inherent JSON validation fragility that cannot be fully mitigated from the user side.

---

### Approach 4: Agent-Type Hook

**How it works:**
Use `type: "agent"` hooks instead of `type: "prompt"`. Agent hooks spawn a subagent with tool access, allowing it to read files, run commands, and make decisions.

**Feasibility:** MEDIUM. Agent hooks are documented and supported for Stop events. The agent could:
- Read the transcript file
- Analyze conversation content
- Call `memory_write.py` directly
- Make nuanced decisions with tool access

**Reliability:** ~85-90%. Agent hooks still use the same `{"ok": boolean, "reason": string}` response schema as prompt hooks. The JSON validation issue persists, though agent models may be more reliable at following schemas.

Additional concerns:
- Agent hooks are slower (default timeout 60s, much heavier than prompt hooks)
- They consume significantly more tokens (full tool-use loop)
- The internal response parsing is the same broken mechanism

**Intelligence:** VERY HIGH. Full tool access means the agent can read files, check index, and make highly contextual decisions.

**Performance:** 5-30 seconds. Agent hooks run a full tool-use loop. Much heavier than a simple API call.

**Cost:** HIGH. Each agent invocation uses multiple API calls internally.

**Complexity:** LOW configuration, but HIGH token cost.

**Verdict:** REJECTED for primary approach. Same JSON validation bug applies. However, could be useful as a SECONDARY mechanism for complex cases if the JSON issue is fixed in a future Claude Code version.

---

### Approach 5: SessionEnd Hook

**How it works:**
Move memory triage from the Stop event to the SessionEnd event. SessionEnd fires when the session ends (user exits, /clear, etc.).

**Key differences from Stop:**
- SessionEnd **cannot block** -- it's fire-and-forget
- SessionEnd receives `reason` field (clear, logout, prompt_input_exit, other)
- SessionEnd hooks run as cleanup tasks
- Since they can't block, there's no need for `{"ok": boolean}` JSON -- just exit 0

**Feasibility:** HIGH for session summaries. SessionEnd is the natural place for "end of session" processing. However:
- Only `type: "command"` or `type: "prompt"` are supported
- Cannot prevent the user from leaving if memory saving fails
- No retry mechanism (session is ending)

**Reliability:** 100% for command-type SessionEnd hooks. Since they can't block, there's no JSON validation issue at all. The script just runs and either succeeds or fails silently.

**Intelligence:** Depends on sub-approach (can combine with heuristics or external LLM).

**Performance:** Non-blocking from the user's perspective (session is ending anyway).

**Limitation:** Only appropriate for SESSION_SUMMARY category. Other categories (decisions, runbooks, constraints, tech_debt, preferences) should be captured at Stop time because:
1. They need to block Claude to trigger memory writes
2. They're most relevant immediately after the action that created them
3. SessionEnd fires too late for real-time memory capture

**Verdict:** EXCELLENT for session summaries. NOT suitable as the sole mechanism for all 6 categories.

---

### Approach 6: Deferred/Async Processing

**How it works:**
At Stop time, save minimal context (transcript path, timestamp, session ID) to a queue file. Process the queue asynchronously:
- Option A: `async: true` on the Stop hook -- runs in background without blocking
- Option B: Process at next SessionStart
- Option C: Cron job / background daemon

**Feasibility:** HIGH. `async: true` is supported on command hooks since Claude Code 2.1.0+.

**With `async: true`:**
- Hook runs in background, doesn't block Claude Code
- Cannot use `decision: "block"` (async hooks can't control behavior)
- Script has full time to process without timeout pressure
- Can call external LLMs without latency concern

**Without `async: true` (next session start):**
- Save a "pending triage" marker at Stop time (instant, <10ms)
- At next SessionStart, a hook reads the previous session's transcript and processes it
- Zero latency impact at Stop time
- Full intelligence at SessionStart (can use LLM calls without time pressure)

**Reliability:** 100% from Claude Code's perspective. Async hooks don't need JSON responses. Deferred processing has no interaction with Claude Code's JSON validator.

**Intelligence:** HIGH (when using LLM for deferred processing).

**Performance:** Zero latency at Stop time (either async or deferred).

**Limitation:**
- Cannot block Claude from stopping (no real-time intervention)
- Memory is not available until next session (if deferred)
- `async: true` hooks can't inject context back into the session

**Verdict:** GOOD for session summaries and non-urgent categories. Not suitable if blocking is needed.

---

### Approach 7: Hybrid Command Triage (RECOMMENDED)

**How it works:**
A single `type: "command"` Stop hook runs a Python triage script that:
1. Reads transcript_path from stdin JSON
2. Checks `stop_hook_active` to prevent infinite loops
3. Parses the JSONL transcript to extract recent conversation
4. Runs a fast heuristic pass (keywords, patterns) for each of the 6 categories
5. For categories where heuristics find strong signals, calls `memory_write.py` directly
6. For ambiguous cases, optionally calls an external LLM API (if API key is available)
7. If any memory needs saving, exits 2 with `{"decision": "block", "reason": "Saving N memories: [categories]"}`
8. Otherwise, exits 0 (allow stop)

**Architecture:**
```
Stop hook (command) -> memory_triage.py
  |
  +-> Read transcript (JSONL parse)
  +-> Heuristic pass (fast, deterministic)
  |     |-> Strong signal? -> memory_write.py (direct call)
  |     |-> Weak/no signal? -> Skip or LLM (if available)
  +-> Optional LLM pass (Gemini Flash / Haiku API)
  |     |-> Parse response (with fallback)
  |     |-> If memory needed -> memory_write.py
  +-> Output JSON decision
       |-> Exit 0 (allow stop) or Exit 2 (block: save memories)
```

**Feasibility:** HIGH. All components exist or are straightforward to build:
- Transcript parsing: stdlib JSON/JSONL reading
- Heuristics: adapt from `memory_retrieve.py`
- External LLM: optional, graceful degradation
- `memory_write.py`: already exists and is battle-tested

**Reliability:** 100%. The Python script always controls the exit code and stdout. No LLM touches Claude Code's JSON parser.

**Intelligence:** MEDIUM-HIGH. Heuristics catch obvious cases (80% of memories). Optional LLM catches nuanced cases. Graceful degradation means LLM unavailability doesn't cause errors.

**Performance:**
- Heuristic-only: <200ms
- With LLM: 1-5s (but only when heuristics find ambiguous signals)
- Can be made async for non-blocking: add `"async": true` (but loses blocking ability)

**Cost:** $0 for heuristic-only. $0.001-0.005 per session with optional LLM.

**Complexity:** MEDIUM. Requires:
- New `memory_triage.py` script (~300-500 LOC)
- Transcript parser
- Category-specific heuristics
- Optional LLM integration layer

**Key Advantage:** This is the ONLY approach that achieves all three goals simultaneously:
1. 100% error-free (command hook)
2. Intelligent triage (heuristics + optional LLM)
3. Can block Claude to trigger memory writes (exit 2 mechanism)

---

### Approach 8: Command Hook + Multi-LLM Consensus

**How it works:**
Command hook calls a Python script that queries 2-3 LLM providers (Gemini Flash, Claude Haiku, GPT-4o-mini) and uses majority vote for each memory category.

**Feasibility:** HIGH technically, but OVERKILL for this use case.

**Reliability:** 100% from Claude Code's perspective (same as Approach 2).

**Intelligence:** VERY HIGH. Consensus reduces individual model hallucination.

**Performance:** 3-10 seconds (parallel API calls, wait for slowest).

**Cost:** 3x the cost of single-LLM approach. $0.003-0.015 per session.

**Complexity:** HIGH. Multiple API keys, response normalization, voting logic.

**Verdict:** Not recommended. The marginal intelligence gain over single-LLM doesn't justify the complexity and cost.

---

## 3. Critical Findings from Research

### 3.1 Known Bugs Affecting Prompt Hooks

1. **GitHub #11786**: Prompt-based Stop hooks receive only metadata, not conversation content. The LLM gets `transcript_path` but cannot read the file. Even when "fixed" in v2.0.53, blocking doesn't work reliably.

2. **GitHub #8564**: Stop hooks sometimes receive stale `transcript_path` pointing to an outdated transcript file. Workaround: find the most recently modified `.jsonl` file.

3. **GitHub #3046**: After `/clear`, the transcript file referenced by the hook may not exist.

4. **Community feedback (issue #11786 comment by @kierr)**: The internal prompt hook evaluation uses a hidden system prompt that expects `{"ok": boolean, "reason": string}`. The documented `{"decision": "approve"|"block"}` format is WRONG/outdated. There's also a known bug where Claude prepends `{` to valid JSON, producing invalid JSON.

### 3.2 Command Hooks Are Rock-Solid

Command hooks have NONE of these issues because:
- They run your script directly
- You control stdout completely
- Exit codes are deterministic
- No LLM is involved in the hook evaluation itself

### 3.3 Transcript Access

Command hooks CAN access the conversation via:
- `transcript_path` field in stdin JSON (JSONL format)
- Can read the file directly from the filesystem
- Workaround for stale paths: scan for most recently modified `.jsonl` file in project dir

### 3.4 The `async: true` Option

Available since Claude Code 2.1.0+. Allows hooks to run in the background:
- Only works with `type: "command"` hooks
- Cannot block actions (decision fields are ignored)
- Great for logging, notifications, and non-blocking processing

### 3.5 SessionEnd Event

- Cannot block session termination
- Receives `reason` field indicating why session ended
- Receives `transcript_path` with the complete session transcript
- Ideal for final session summary processing

### 3.6 claude-mem Architecture Reference

The `claude-mem` plugin (thedotmack/claude-mem) uses a similar architecture:
- Command hooks with exit 0 (never blocks, prevents cascading errors)
- Background worker process for heavy lifting
- All hook errors are absorbed (exit 0) to prevent UX issues
- This philosophy aligns with our needs: the hook layer should be ultra-reliable

---

## 4. Recommended Approaches (Ranked)

### Rank 1: Hybrid Command Triage (Approach 7)

**Recommended as primary architecture.**

- Single `type: "command"` Stop hook running `memory_triage.py`
- Fast heuristic pass for all 6 categories
- Optional external LLM for ambiguous cases (graceful degradation)
- Can block Claude (exit 2) when memory needs saving
- Separate `SessionEnd` command hook for session summary (Approach 5 integration)
- 100% error-free, medium-high intelligence, reasonable performance

### Rank 2: Command Hook + External LLM API (Approach 2)

**Recommended as the "maximum intelligence" variant.**

- Same architecture as Rank 1 but always uses external LLM (no heuristic-only fast path)
- Better for users who have API keys configured and want maximum triage quality
- Can be offered as a "premium mode" configuration option
- 100% error-free, high intelligence, 1-5s latency

### Rank 3: Command Hook + Heuristics Only (Approach 1)

**Recommended as the "zero-dependency" fallback.**

- Keyword/pattern matching only, no external LLM
- Works without any API keys
- Fastest performance (<100ms)
- Lower intelligence but handles 80% of clear-cut cases
- 100% error-free, immediate, no cost

### Implementation Strategy

The recommended implementation combines all three in a single `memory_triage.py` script with tiered behavior:

```
Tier 1 (always): Heuristic pass -- catches obvious signals
Tier 2 (if API key available): LLM pass for ambiguous cases
Tier 3 (fallback): If LLM fails, use heuristic result only
```

Configuration in `memory-config.json`:
```json
{
  "triage": {
    "mode": "hybrid",       // "heuristic" | "llm" | "hybrid"
    "llm_provider": "gemini-flash",
    "llm_fallback": "heuristic",
    "timeout_ms": 5000
  }
}
```

### hooks.json Change

```json
{
  "Stop": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_triage.py\"",
          "timeout": 15,
          "statusMessage": "Evaluating session for memories..."
        }
      ]
    }
  ],
  "SessionEnd": [
    {
      "matcher": "*",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_session_end.py\"",
          "timeout": 30,
          "statusMessage": "Saving session summary..."
        }
      ]
    }
  ]
}
```

This replaces 6 unreliable prompt hooks with 1 reliable command hook + 1 SessionEnd hook.

---

## 5. Self-Critique

### What could be wrong with this analysis:

1. **Heuristic intelligence may be overestimated.** Keyword matching for "decisions" and "preferences" is harder than for "runbooks" (which have clear error patterns). The 80% catch rate is an estimate.

2. **Transcript parsing has edge cases.** The JSONL format may vary across Claude Code versions. The `/clear` bug (#3046) and stale path bug (#8564) need defensive handling.

3. **External LLM dependency.** If the user doesn't have Gemini/Anthropic API keys, the hybrid approach degrades to heuristic-only. This may not be acceptable for all users.

4. **Blocking behavior trade-off.** Using exit 2 to block Claude and trigger memory writes is powerful but has UX implications -- the user sees "memory evaluation" status messages and potential delays. The `claude-mem` approach of never blocking (always exit 0) is more user-friendly but less reliable for ensuring memories are saved.

5. **Single hook vs multiple.** Consolidating 6 hooks into 1 means a single failure blocks all categories. However, since the script is deterministic (no LLM), this risk is minimal.

6. **Async consideration.** If the script is made async, it can't block Claude. This means memory writes happen in the background and may not complete before the next user prompt. For most use cases this is fine, but for critical memories it could be a problem.

### Mitigations:

- For edge case 2: Use defensive JSONL parsing with try/except per line; implement the "most recent .jsonl" workaround
- For edge case 3: Make LLM optional and clearly documented
- For edge case 4: Make blocking configurable (`"blocking": true/false` in config)
- For edge case 6: Use synchronous by default; offer async as opt-in

---

## Sources

- [Claude Code Hooks Reference](https://docs.claude.com/en/docs/claude-code/hooks)
- [Claude Code Hooks Guide](https://docs.claude.com/en/docs/claude-code/hooks-guide)
- [GitHub Issue #11786: Prompt-based Stop hooks regression](https://github.com/anthropics/claude-code/issues/11786)
- [GitHub Issue #8564: Stale transcript path in Stop hooks](https://github.com/anthropics/claude-code/issues/8564)
- [GitHub Issue #3046: /clear breaks transcript file](https://github.com/anthropics/claude-code/issues/3046)
- [thedotmack/claude-mem](https://github.com/thedotmack/claude-mem) -- Reference architecture
- [Claude Code Hook Development SKILL.md](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/hook-development/SKILL.md)
- Gemini 3 Pro analysis (via pal clink) -- confirmed Hybrid Command Triage as recommended approach
