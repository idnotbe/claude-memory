# Research: Alternative Architectures for Memory Save Noise Reduction

**Researcher:** alt-arch-researcher (Task #3)
**Date:** 2026-02-28
**Goal:** Evaluate alternative architectures for the memory save process to eliminate or minimize visible output during save operations.

---

## Background

The current architecture has the Stop hook block session termination with a `{"decision": "block", "reason": "..."}` JSON response. The `reason` field contains the full triage data (20+ lines of JSON), and Claude then executes SKILL.md instructions which spawn multiple Task subagents, read/write staging files, run `memory_*.py` scripts -- all visible to the user (50-100+ lines of output). This can trigger /compact and destroy conversation context.

---

## Key Facts From Hook API Research (2026-02-28)

### Available Hook Events

From the official Claude Code documentation (confirmed current as of Feb 2026):

| Event | Blockable? | LLM Access? | Notes |
|-------|-----------|-------------|-------|
| `SessionStart` | No | Yes (stdout → context) | Fires on startup/resume/clear/compact |
| `Stop` | **Yes** | **Yes** (reason → Claude) | Current mechanism |
| `SessionEnd` | **No** | No | Cannot block termination |
| `PreToolUse` | Yes | Yes | Per-tool |
| `PostToolUse` | No (already ran) | Yes | Cannot undo |
| `PreCompact` | No | No | Command-only |

### Stop Hook Block Behavior

When Stop hook returns `{"decision": "block", "reason": "..."}`:
- Claude receives the `reason` as an instruction and continues working
- The `reason` content becomes the next "turn" for Claude
- All subsequent tool calls, subagent spawning, and output ARE visible to the user
- There is NO built-in suppression of what Claude does in response to a block

### suppressOutput Field

The docs confirm `suppressOutput` exists as a JSON output field:
- `"suppressOutput": false` (default) -- hook stdout shown in verbose mode (Ctrl+O)
- `"suppressOutput": true` -- hides stdout from verbose mode
- **Critical limitation:** `suppressOutput` only hides the hook's own stdout from verbose mode. It does NOT suppress what Claude does afterward when it processes the block reason and executes SKILL.md.

### Async Hooks

`"async": true` on command hooks:
- Hook runs in background without blocking Claude
- Cannot return `decision` (no blocking capability)
- After completing, can inject `systemMessage` or `additionalContext` on next turn
- Only `type: "command"` supports async (not prompt or agent hooks)

### SessionEnd Hook (Confirmed Implemented)

The SessionEnd hook IS implemented in Claude Code (confirmed from current docs):
- Fires when session terminates
- Matchers: `clear`, `logout`, `prompt_input_exit`, `bypass_permissions_disabled`, `other`
- **Cannot block session termination** (non-blockable)
- Cannot return decision control
- Only supports `type: "command"` hooks
- Receives: `session_id`, `transcript_path`, `cwd`, `reason`
- **No LLM access**: hook runs as a shell command, no Claude model involved

---

## Alternative Architecture Analysis

### Alternative 1: SessionEnd Hook with External API Call

**Concept:** Remove the Stop hook entirely. Add a SessionEnd hook that calls the Claude API directly (via `urllib` or subprocess) to draft and save memories.

**How it works:**
1. Session ends normally (no block, no visible output)
2. SessionEnd hook fires (silently, no UI)
3. Hook script reads transcript, runs triage heuristics
4. If memories needed, calls Claude API directly (not Claude Code) to draft JSON
5. Runs `memory_write.py` to save
6. Done -- user never sees anything

**Feasibility: MEDIUM-LOW**

Limitations:
- SessionEnd cannot be blocked -- if the API call takes 10+ seconds, session terminates and the hook process is killed (or runs orphaned)
- No guarantee the hook completes before the process is reaped
- Requires API key to be available in the hook environment (security concern)
- Drafting quality depends on raw API call without SKILL.md context
- No way to confirm success to the user
- If session ends via Ctrl+C or kill signal, SessionEnd may not fire at all (only fires for `clear`, `logout`, `prompt_input_exit`, `bypass_permissions_disabled`, `other`)

**What changes:** Replace Stop hook with SessionEnd hook in hooks.json. Write a new `memory_session_end.py` that handles full pipeline including API call.

**Trade-offs:**
- Quality: LLM drafting preserved, but without SKILL.md tooling (no memory_candidate.py lookup)
- Noise: Zero visible output (ideal)
- Reliability: Poor -- race condition between session cleanup and API call completion
- User feedback: None (user cannot know if save succeeded)

**Verdict: Not viable as primary mechanism. Could serve as fallback.**

---

### Alternative 2: Deferred Save Pattern (External Watchdog)

**Concept:** Stop hook writes triage data to a sentinel file and returns block=allow (no block). An external process (cron, systemd timer, watchdog) picks up the sentinel file and does the actual save.

**How it works:**
1. Stop hook runs triage, writes results to `.claude/memory/.staging/deferred-save.json`
2. Stop hook exits without blocking (or with minimal block)
3. An external daemon polls for `deferred-save.json` and processes it
4. Daemon can call Claude API for drafting and run memory_write.py
5. On next session start, SessionStart hook can inject "N memories saved from last session"

**Feasibility: MEDIUM**

Requirements:
- External daemon must be set up by user (not zero-config)
- Daemon needs API key
- Race: user immediately starts new session before daemon runs? (acceptable)
- systemd user timer or launchd plist is OS-specific (not cross-platform)

**What changes:**
- `memory_triage.py`: add deferred mode that writes sentinel and exits (no block)
- New `memory_daemon.py`: watches for sentinel file, calls API, saves memories
- `hooks.json`: add SessionStart hook to inject "pending saves" notification
- User setup: systemd timer or similar per OS

**Trade-offs:**
- Quality: Good if LLM drafting can be done in daemon context
- Noise: Excellent (zero main session noise)
- Reliability: Medium (daemon could be killed, user might not have daemon running)
- Complexity: High (external process setup required)
- User feedback: Delivered in next session via SessionStart context injection

**Verdict: Viable but requires non-trivial user setup. Good for power users. Could be opt-in.**

---

### Alternative 3: Stop Hook Spawns Detached Process (API Direct Call)

**Concept:** Stop hook runs triage, then spawns a detached Python process via `subprocess.Popen` with `start_new_session=True`. The spawned process does drafting + saving. Stop hook exits immediately (no block or minimal output).

**How it works:**
1. Stop hook runs triage heuristics (fast, <100ms)
2. If memories needed, spawns: `python3 memory_save_async.py --triage-data /path/to/triage.json &`
3. Stop hook exits 0 (allows session to end normally OR blocks with 1-line message)
4. Detached process calls Claude API, drafts memories, runs memory_write.py
5. On next SessionStart, hook reads a "saves-pending" or "saves-completed" file and injects context

**Feasibility: HIGH**

This is the most technically sound "deferred" approach:
- `subprocess.Popen` with `start_new_session=True` creates a true daemon process
- Process continues after parent hook process exits
- API key needed in environment (can read from `~/.anthropic/api_key` or `ANTHROPIC_API_KEY`)
- Python's `subprocess` is stdlib -- no extra dependencies

Example code for Stop hook:
```python
import subprocess, sys, os

# Run triage...
if results:
    # Write triage context to file
    with open(sentinel_path, 'w') as f:
        json.dump(triage_data, f)

    # Spawn detached saver
    subprocess.Popen(
        [sys.executable, memory_save_async_path, "--sentinel", sentinel_path, "--cwd", cwd],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Allow session to stop (no block!)
    # OR: print minimal 1-line block with no JSON
    sys.exit(0)
```

**What changes:**
- `memory_triage.py`: add detached-process mode (write sentinel + spawn + exit 0)
- New `memory_save_async.py`: full save pipeline including API call and write
- `hooks.json`: add SessionStart hook to inject "N memories saved" context on next turn
- Config: `triage.save_mode = "async" | "inline"` (default: async)

**Trade-offs:**
- Quality: Full LLM drafting preserved (same API), minus SKILL.md tooling
- Noise: Minimal/zero (stop hook outputs nothing or 1 line)
- Reliability: High (process runs to completion, isolated from session)
- User feedback: Summary on next session start
- Security: API key must be accessible to subprocess

**Verdict: Best pure async approach. Highly feasible. Major trade-off: no interactive SKILL.md verification flow.**

---

### Alternative 4: Pre-computed Draft in Stop Hook Python Script

**Concept:** Do more in the Stop hook's Python script itself (which runs silently as a command hook). Use the Claude API inline within the hook script to draft memories. Block stop with a minimal 1-2 line message instead of full JSON.

**How it works:**
1. Stop hook runs triage (fast)
2. If memories needed, hook calls Claude API in-process to draft JSON
3. Hook runs `memory_write.py` to save (all in Python, no Claude Code tooling)
4. Hook returns `{"decision": "allow"}` OR blocks with 1-line: "Saved N memories."

**Feasibility: HIGH**

This is the "single-script does everything" approach. The hook script itself becomes the full save pipeline.

Key insight: The current Stop hook ALREADY runs Python. We can add API calls there.

**What changes:**
- `memory_triage.py`: extend to do full save pipeline (draft + write)
- Config: `triage.api_key_env = "ANTHROPIC_API_KEY"` (read from env)
- Remove dependency on SKILL.md for save (skill remains for manual invocation)
- Block message: short, no JSON: `"Saved 2 memories (DECISION, PREFERENCE). Session complete."`

**Trade-offs:**
- Quality: Good (LLM drafting preserved, but without candidate lookup for updates)
- Noise: Minimal (hook runs silently, only output is final 1-line block message, or nothing if we allow stop)
- Reliability: Good (synchronous, atomic save before stop)
- Simplicity: High (no external daemon needed)
- Limitation: The hook runs with a 30-second timeout (currently). Complex multi-category saves might timeout.

**Verdict: Strong candidate. Requires API key available in hook environment. Timeout is a risk for complex sessions.**

---

### Alternative 5: Minimal Notification Hook Pattern

**Concept:** Redesign the SKILL.md-driven flow to be radically quieter. Keep the current Stop hook mechanism but eliminate visible output from the save process.

**How it works:**
1. Stop hook blocks with minimal reason: `"Memory save needed. Call memory-management skill with silent mode."`
2. SKILL.md save process uses Task subagents but with `suppressOutput: true` on hooks
3. Main agent outputs nothing except a final 1-line summary

**Feasibility: LOW-MEDIUM**

The core problem: when Claude processes the block reason, everything it does (tool calls, subagent spawning, read operations) is visible in the main transcript. `suppressOutput` only affects hook output, not Claude's own actions.

There is no mechanism to make Claude's tool calls invisible to the user. The only ways to reduce output are:
1. Do the work outside Claude Code (Alternatives 1-4)
2. Use a subagent isolated from the main transcript (partial mitigation)
3. Reduce the number of steps (fewer tool calls = less output)

**What changes:**
- Rewrite SKILL.md to be maximally terse
- Reduce phases from 4 to 2 (combine draft+verify)
- Use single consolidated subagent instead of parallel agents per category
- Subagent output still appears but is more compact

**Trade-offs:**
- Quality: Preserved (same LLM verification)
- Noise: Reduced but not eliminated (still 20-40 lines instead of 50-100)
- Reliability: Same as current
- Complexity: Low (just rewrite SKILL.md)

**Verdict: Worthwhile as a companion to other approaches but doesn't solve the fundamental problem. Best as optimization on top of chosen primary approach.**

---

### Alternative 6: Agent Hook Type for Stop

**Concept:** Use `type: "agent"` for the Stop hook. Agent hooks spawn a subagent that runs the full save pipeline, returning `{"ok": true}` when done. This subagent runs in its OWN context, separate from the main conversation.

**How it works:**
1. Stop event fires
2. Agent hook spawns a dedicated save subagent (isolated context)
3. Subagent reads context files, drafts memories, saves them, returns `{"ok": true}`
4. Main conversation never sees the save operations (subagent is isolated)

**Feasibility: MEDIUM**

From the docs: Agent hooks "spawn a subagent that can read files, search code, and use other tools to verify conditions before returning a decision."

**Key question:** Do agent hook subagents' tool calls appear in the MAIN conversation transcript?

From reading SubagentStart/SubagentStop documentation: subagents have their OWN `agent_transcript_path` in a nested `subagents/` folder. This suggests subagent output may be isolated from the main transcript view.

However: the current SKILL.md uses regular Task subagents which DO appear in the main transcript. Agent hooks may behave differently -- they're spawned by the hook system, not by the main agent's Task tool.

**What changes:**
- Replace `type: "command"` Stop hook with `type: "agent"` Stop hook
- Write agent prompt that does full save pipeline
- Provide agent access to memory scripts and staging files

**Trade-offs:**
- Quality: Potentially excellent (full LLM + tool access)
- Noise: Potentially zero (if agent transcript is truly isolated)
- Reliability: 60-second default timeout (may need extension)
- Unknowns: Whether agent hook subagent output appears in main transcript (CRITICAL uncertainty)

**Verdict: Potentially the best solution IF agent hook subagent output is truly isolated from main transcript. Requires experimentation to confirm. Marked as HIGH-PRIORITY investigation target.**

---

## Summary: Feasibility Matrix

| Alternative | Noise Reduction | Quality | Reliability | Complexity | Recommended |
|------------|----------------|---------|-------------|------------|-------------|
| 1. SessionEnd + API | Excellent | Good | Poor (race) | Medium | No (unreliable) |
| 2. Deferred + Daemon | Excellent | Good | Medium | High | Optional/advanced |
| 3. Detached Process | Excellent | Good | High | Medium | Yes (async) |
| 4. Pre-computed in Hook | Excellent | Good | High | Medium | **Yes (primary)** |
| 5. Minimal Notification | Partial | Excellent | High | Low | Yes (companion) |
| 6. Agent Hook Type | Potentially Excellent | Excellent | Medium | Low | **Yes (investigate)** |

---

## Key Findings

### 1. SessionEnd is real but not viable as primary

SessionEnd exists and fires when session terminates. However, it cannot block termination, so any async work races against process cleanup. It's suitable only for lightweight cleanup (delete temp files, log stats), not for multi-second API calls. **Not viable as primary save mechanism.**

### 2. suppressOutput doesn't help with the core problem

The `suppressOutput` flag only hides the hook's own stdout from verbose mode. It does not suppress what Claude does in response to a Stop block. The user sees all of Claude's tool calls, subagent spawning, and output from SKILL.md execution. **Not a solution.**

### 3. The real opportunity: move work out of Claude Code entirely

Alternatives 3 (detached process) and 4 (pre-computed in hook) both do save work in Python, not in Claude Code's visible context. The hook script runs silently (no UI), calls the Claude API directly, and saves without involving the main agent at all. This eliminates ALL visible noise.

**Trade-off:** Losing SKILL.md's sophisticated verification flow (ACE candidate selection, update vs create decisions, multi-stage verification). But the resulting quality is still good -- just less curated.

### 4. Agent hook type is a dark horse candidate

If `type: "agent"` Stop hooks run in isolated subagent contexts (their own transcript), this would be the ideal solution: full LLM quality, zero noise. **Needs experimental validation.**

### 5. Hybrid approach is the pragmatic path

Best practical solution:
1. **Primary:** Rewrite save pipeline to run in the Stop hook Python script itself (Alternative 4), calling Claude API directly for drafting, no SKILL.md involvement
2. **Companion:** Optimize SKILL.md to be maximally terse for cases where manual invocation is needed (Alternative 5)
3. **Future:** Investigate agent hook isolation (Alternative 6)

---

## What Needs to Change in Current Pipeline

For Alternative 4 (pre-computed in hook):

1. **`memory_triage.py`**: After triage, instead of emitting a block with triage_data, call Claude API inline:
   - Use `urllib.request` (stdlib) to POST to Anthropic API
   - Prompt: "Draft a memory JSON for category X based on this context: [context file]"
   - Parse response, run `memory_write.py` for each category
   - Return `{"decision": "allow"}` with brief `systemMessage`: "Saved N memories."

2. **Config**: Add `triage.save_mode = "inline_api" | "skill"` (default: inline_api)
   - `inline_api`: hook does everything (new behavior, less noise)
   - `skill`: current behavior (SKILL.md-driven, more noise but more control)

3. **SKILL.md**: Keep for manual `/memory-management` invocations. No longer used by Stop hook in default config.

4. **`hooks.json`**: No changes needed. Same Stop hook, new behavior.

---

## Trade-offs Summary

| Dimension | Current (SKILL.md-driven) | Proposed (Inline API) |
|-----------|--------------------------|----------------------|
| Noise | 50-100+ lines visible | 0-2 lines visible |
| Quality | Excellent (multi-stage verify) | Good (single LLM call per category) |
| Update detection | Yes (ACE candidate selection) | Limited (no existing memory lookup) |
| /compact risk | High (lots of output) | None |
| API key requirement | No (uses Claude Code's API) | Yes (ANTHROPIC_API_KEY needed) |
| Timeout risk | Low (30s for triage only) | Medium (30s for triage + drafting + saving) |
| Manual override | Yes (SKILL.md) | Yes (SKILL.md) |

---

## Recommended Approaches

### Primary Recommendation: Alternative 4 (Inline API Save in Stop Hook)

**Rationale:** Eliminates ALL visible noise. Keeps save synchronous (completes before session ends). Preserves LLM drafting quality. No external daemon needed. Moderate complexity change.

**Risk:** 30-second timeout on stop hook may be insufficient for sessions with many categories. Mitigation: increase timeout in hooks.json, or defer multi-category saves to async mode.

### Secondary Recommendation: Alternative 6 (Agent Hook Investigation)

**Rationale:** If agent hook subagents are truly isolated from main transcript, this gives us LLM quality + full tool access + zero noise -- better than Alternative 4 on quality.

**Action needed:** Empirically test whether `type: "agent"` Stop hook subagent tool calls appear in main conversation view.

### Companion: Alternative 5 (Minimize SKILL.md output)

**Rationale:** Reduces noise even if primary approach isn't implemented. Should be done regardless as defensive measure.

---

## Cross-Validation (Gemini 3.1 Pro via clink)

All five key conclusions were validated as **accurate** by Gemini 3.1 Pro. Additional blind spots surfaced:

**Alternative 4 (Inline API):**
- **API Key Dependency**: Users who rely solely on Claude Code's internal OAuth (`claude login`) will not have `ANTHROPIC_API_KEY` available in hook environment. Requires explicit env var setup.
- **Timeout**: 30s hook timeout is tight for multi-category synchronous API calls. May need `"timeout": 120` in hooks.json.
- **No iterative tool access**: Raw API call cannot do `Read`/`Bash` tool calls to look up existing memories for update vs create decisions (loses ACE candidate selection).

**Alternative 6 (Agent Hook):**
- Confirmed: agent hook subagent tool calls run in isolated transcript (`.claude/subagents/`) -- not visible in main UI
- **BUT**: Main UI still blocks during subagent execution (user sees delay + spinner)
- Agent hook return format: must be `{"ok": true/false}` -- cannot inject confirmation text to main context
- **Tool hallucination risk**: agent uses LLM to decide which bash commands to run (less deterministic than Python script)

**Gemini's recommendation aligns with this research:**
- Approach 4 (inline Python API) for absolute zero noise
- Approach 6 (agent hook) for better LLM quality + native auth, but needs empirical validation of latency UX

---

## Sources

- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
- [Claude Code Hooks Guide](https://code.claude.com/docs/en/hooks-guide)
- [GitHub Issue #4318: SessionStart/SessionEnd Feature Request](https://github.com/anthropics/claude-code/issues/4318) -- confirms SessionEnd is now implemented (issue closed as done)
- [Async Hooks Article (Dev Genius, Jan 2026)](https://blog.devgenius.io/claude-code-async-hooks-what-they-are-and-when-to-use-them-61b21cd71aad)
- Cross-validation: Gemini 3.1 Pro via pal clink (2026-02-28, all conclusions confirmed accurate)
