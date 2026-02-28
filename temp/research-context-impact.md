# Context Window Impact & /compact Interaction Research

**Date:** 2026-02-28
**Researcher:** context-researcher (Task #4)
**Status:** Complete — cross-validated with Gemini via PAL clink

---

## 1. How /compact Works in Claude Code

### Trigger Conditions

Auto-compact fires automatically when context utilization reaches **~80–95% of the 200K token window** (approximately 160K–190K tokens consumed). The exact threshold has shifted across versions:

- Pre-2026: ~77–83.5% utilization
- As of early 2026: a ~33K token buffer (16.5%) is reserved, so auto-compact fires around **167K tokens used**
- Override: `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` env var (values 1–100) controls the threshold percentage

### What Gets Preserved vs Dropped

Auto-compact works by summarizing the conversation, not truncating it:

**Typically preserved:**
- Recent code modifications and file changes
- Project structure and architectural decisions
- Current task objectives and ongoing context
- Established coding patterns and naming conventions

**Gets summarized/condensed:**
- Detailed explanations no longer immediately relevant
- Resolved debugging sessions
- Exploratory discussions without code outcomes
- Historical conversation context no longer needed for current work

**Critical implication:** Memory-saving orchestration boilerplate (subagent return values with JSON drafts, verification reports) gets treated as conversation history. After /compact, the original user conversation it was interleaved with may be summarized away, but the memory-saving noise itself also consumes significant pre-compact context.

### Manual vs Auto

- `/compact` or `Ctrl+K` triggers manual compaction
- Since v2.0.64, compaction is instant (no waiting)
- `SessionStart` hook fires with `source: "compact"` after compaction, allowing hooks to re-inject context

---

## 2. Token Cost Estimates for the Memory Save Process

### Stop Hook Output — Critical Finding

**Stdout from Stop hooks (exit 0) is NOT added to Claude's context.** It only appears in verbose mode (Ctrl+O).

**BUT:** When the Stop hook returns `{"decision": "block", "reason": "..."}`, the `reason` string IS fed back to Claude as a system message/continuation prompt. This is the entry point for context bloat.

In `memory_triage.py`, the `reason` field contains the full `<triage_data>` JSON payload with matched categories, scores, and context file paths. This immediately consumes context.

### Phase-by-Phase Token Estimates

| Phase | Operation | Tokens Added to Main Context |
|-------|-----------|------------------------------|
| Stop hook block | `reason` field with `<triage_data>` JSON | ~500–1,000 tokens |
| Phase 1 prompt | Agent reads SKILL.md + spawns drafting subagents | ~200–500 tokens (instructions) |
| Phase 1 per-category | Each Task subagent return value (JSON draft) | ~500–2,000 tokens each |
| Phase 2 per-category | Each verification subagent return value | ~300–1,000 tokens each |
| Phase 3 saves | Bash calls, read/write ops visible in main thread | ~100–300 tokens each |

**1-category save estimate:**
- Triage block: ~750 tokens
- 1 drafting subagent return: ~1,000 tokens
- 1 verification subagent return: ~700 tokens
- Phase 3 (2–3 Bash calls): ~400 tokens
- **Total: ~2,850 tokens**

**3-category save estimate:**
- Triage block: ~750 tokens
- 3 drafting subagent returns (parallel): ~3,000 tokens
- 3 verification subagent returns: ~2,100 tokens
- Phase 3 (6–9 Bash calls): ~1,200 tokens
- **Total: ~7,050 tokens** (conservative; could reach 10–20K with verbose outputs)

### Subagent Overhead (API Billing Side)

Each Task subagent spawned also incurs ~20K tokens of overhead (base system prompt + tools initialization) on the backend, though this does NOT directly consume the main agent's context window — it affects cost, not main-context size.

---

## 3. Subagent Context Isolation

### What IS Isolated (stays in subagent's own context)

- Internal reasoning / chain-of-thought
- Tool calls made by the subagent (Read, Grep, Bash, etc.)
- Intermediate file reads and writes
- Error messages and retries within the subagent
- The subagent's full working context (~200K tokens, separate window)

### What IS NOT Isolated (injected into main context)

- The **final return value** (string output) of the subagent
- This return value is directly added to the main agent's conversational history
- For memory-save subagents, this includes full JSON memory drafts and verification reports

### run_in_background Parameter

- Background subagents run concurrently while the main agent continues
- The context impact is the same: return values still inject into main context when the subagent completes
- The difference is operational (non-blocking) not token-related
- Background subagents may report results after the main agent has moved on, but results still accumulate in context

---

## 4. Which Approaches Actually Reduce Context Consumption

### Does NOT reduce main-context consumption

- Making hook stdout shorter (it goes to verbose mode, not context)
- Using `run_in_background=true` (return values still inject on completion)
- Using fewer Tool calls inside subagents (those stay in subagent context anyway)
- Reducing Phase 3 Bash call count (these are relatively cheap, ~100 tokens each)

### DOES reduce main-context consumption

1. **Eliminate the `{"decision": "block", "reason": "..."}` pattern entirely**
   - Move the entire save pipeline OUT of the main agent's orchestration
   - The Stop hook should not cause the main agent to orchestrate anything

2. **Replace multi-phase Task subagents with a single Python script**
   - `memory_write.py` + `memory_draft.py` + `memory_enforce.py` called directly from the Stop hook command
   - Zero subagent return values injected into main context
   - Hook runs async (or sync), outputs nothing to main context on exit 0

3. **Use a single consolidated subagent that returns only a brief summary**
   - Instead of 6 subagents (3 draft + 3 verify) each returning JSON, one agent handles everything internally and returns "Saved: Decision [active]" (30 tokens)
   - Reduces return-value token injection from ~7K to ~50 tokens

4. **Use an async command hook**
   - `"async": true` in hook config causes hook to run in background without blocking
   - The hook stdout never reaches main context (already the case for exit 0)
   - No `{"decision": "block", "reason": "..."}` needed — the Stop proceeds normally
   - **Limitation:** Cannot prevent Claude from stopping; cannot inject continuation logic

5. **Move to a `SessionEnd` hook**
   - Fires after the session ends; no context cost to the main conversation
   - Cannot be blocked (PostToolUse-style: no decision control)
   - Risk: if session crashes, no save occurs

---

## 5. Key Architectural Insight (Validated by Gemini)

The root cause of context bloat is **not** hook output visibility. It is the `{"decision": "block", "reason": "..."}` pattern that forces the main agent to become the orchestrator of the save pipeline.

**Current flow (context-heavy):**
```
Stop hook → reason injects into main context → main agent reads SKILL.md →
main agent spawns Task subagents → each subagent return value injects into main context →
main agent runs Bash saves → total: 7K–20K tokens added to main context per save
```

**Ideal flow (zero main-context cost):**
```
Stop hook (async command) → Python script does all work directly →
exits 0 with brief stdout (verbose only) → main agent never involved →
total: 0 tokens added to main context
```

The architectural fix is to eliminate the main agent's role in memory orchestration. The stop hook should execute a self-contained Python pipeline, not delegate to the main agent via the `block + reason` mechanism.

---

## 6. Recommendations for Context-Preserving Save Strategies

**Ranked by context savings (best first):**

1. **Full Python pipeline in Stop hook command** (async=true)
   - Stop hook runs a standalone Python script that calls draft/write/enforce directly
   - No main agent involvement, no subagent return values, zero context cost
   - Hook runs async so it doesn't even block the Stop
   - Risk: no LLM judgment for complex memory content; quality depends on script heuristics

2. **Single consolidated "memory-save" subagent** returning minimal output
   - Stop hook blocks, but spawns ONE subagent that handles all categories internally
   - Subagent returns a single line: "Saved N memories: [title1], [title2]"
   - Context cost: ~750 (triage block) + ~100 (one return) = ~850 tokens vs current 7K–20K
   - Preserves LLM judgment for content quality

3. **SessionEnd hook for deferred save**
   - Context cost: zero (fires after session ends)
   - Risk: session crash = lost save; no blocking ability

4. **PreCompact hook to save before /compact fires**
   - Fires before compaction occurs
   - Can run a quick save to preserve important decisions before context is summarized
   - No decision control (cannot block compaction itself)
   - Complementary strategy, not a replacement

---

## Sources

- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks) — Stop hook stdout behavior, exit code semantics, decision control
- [Claude Code Auto-Compact FAQ](https://claudelog.com/faqs/what-is-claude-code-auto-compact/) — compaction behavior and preservation
- [Context Buffer Management](https://claudefa.st/blog/guide/mechanics/context-buffer-management) — 33K token buffer, threshold mechanics
- [Understanding Auto-Compact](https://lalatenduswain.medium.com/understanding-context-left-until-auto-compact-0-in-claude-cli-b7f6e43a62dc) — token threshold details
- [Configurable Threshold Issue](https://github.com/anthropics/claude-code/issues/23711) — CLAUDE_AUTOCOMPACT_PCT_OVERRIDE
- [Subagents Context Management](https://www.richsnapp.com/article/2025/10-05-context-management-with-subagents-in-claude-code) — isolation and return value injection
- [Claude Code Sub-agents Docs](https://code.claude.com/docs/en/sub-agents) — context isolation fundamentals
- Cross-validated with Gemini 3.1 Pro via PAL clink — all 5 conclusions confirmed
