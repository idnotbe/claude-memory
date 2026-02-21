# UX/Cost Pragmatist Analysis: Memory Retrieval Architecture Redesign

**Author:** UX/Cost Pragmatist
**Date:** 2026-02-22
**Status:** Complete

---

## Executive Summary

The current retrieval architecture works but has three pragmatic flaws that limit real-world adoption:

1. **The LLM judge requires a separate ANTHROPIC_API_KEY** that Claude Max/Team users (the primary audience) do not have. This makes the highest-precision retrieval path inaccessible to most users.
2. **The hook fires on every prompt** including simple greetings, adding latency even when no memories match. With BM25 alone this is ~100ms (acceptable), but with the judge enabled it's 1-3s per prompt (unacceptable for interactive coding).
3. **Auto-injection is invisible.** Users never see what memories were injected or why, making the system impossible to debug when it injects irrelevant context or misses relevant context.

**Bottom-line recommendation:** Keep lightweight BM25 auto-inject for high-confidence matches only. Replace the API-key-dependent judge with a confidence-tiered output: inject high-confidence results directly, emit a visible nudge for medium/low confidence, and let Claude's agentic capabilities handle on-demand search. Deprecate the hook-side LLM judge entirely.

---

## Per-Question Analysis

### Q1: Can Claude Code be made to autonomously search memories?

**Current state:** No autonomous search exists. Two paths only: (1) hook auto-injects on every prompt, (2) user explicitly invokes `/memory:search`.

#### Option A: Instruct Claude to use `/memory:search` when needed

| Dimension | Assessment |
|-----------|------------|
| **Latency** | Zero added latency on the hook path. Search cost (~200ms + subagent) paid only when Claude decides to search. |
| **Cost** | Uses Claude Code API tokens (included in subscription). No separate billing. |
| **UX** | User sees Claude actively searching -- transparent and debuggable. |
| **Reliability** | **Key risk.** Claude's compliance with "search when needed" instructions varies. Gemini's analysis suggests a directive nudge ("you MUST use memory:search if you lack context") works reliably with agentic models, but this is unverified empirically. |
| **Config burden** | None. No API key. Instruction-only change. |
| **Implementation** | ~10 LOC: add instruction to SKILL.md or CLAUDE.md. Very low effort. |

#### Option B: Hook runs search engine, lets Claude decide

This is the current architecture. The hook runs the search, outputs results, and Claude receives them passively.

| Dimension | Assessment |
|-----------|------------|
| **Latency** | ~100ms BM25 on every prompt. Paid unconditionally. |
| **Cost** | Zero API cost (stdlib only). Token cost from injected context (~50-150 tokens per prompt). |
| **UX** | Silent. User cannot see, audit, or control what was injected. |
| **Reliability** | Deterministic -- always fires, always outputs. No dependency on Claude behavior. |
| **Implementation** | Already implemented. |

#### Pragmatic recommendation for Q1

**Hybrid approach: Auto-inject high-confidence + directive nudge for the rest.**

The hook already runs BM25. Instead of injecting all matches silently, tier the output:
- **High confidence (>=75% of best score):** Inject directly (current behavior, proven reliable)
- **Medium/low confidence:** Emit a visible nudge like `<memory_nudge>Found 2 potentially relevant memories about "JWT auth". Use /memory:search JWT if context would help.</memory_nudge>`
- **No match:** Exit silently (no wasted tokens)

This is Option A + Option B combined. High-confidence injection is deterministic (no reliability risk). The nudge covers the gap where BM25 is uncertain, and Claude can act on it.

**Implementation effort:** ~30-50 LOC change to `_output_results()` and `main()` in `memory_retrieve.py`. Low.

---

### Q2: Is the on-demand judge intentionally run in a subagent to save main context window?

**Answer: Yes, and it's a good design decision.**

Evidence from `skills/memory-search/SKILL.md:122`:
```
Spawn a Task subagent with subagent_type=Explore and model=haiku
```

#### Cost analysis

| Judge Location | Tokens consumed from main context | API cost | Latency |
|---------------|-----------------------------------|----------|---------|
| **Main context (no subagent)** | ~500-800 tokens for judge prompt + response | 0 (included in session) | ~1-2s |
| **Subagent (current)** | ~50 tokens (subagent result summary) | 0 (included in session) | ~3-5s |
| **Hook-side API call** | ~50 tokens (filtered results) | ~$0.001-0.003 per call (haiku) | ~1-3s |

**Main context pollution is the real cost**, not API dollars. A judge prompt with 15 candidates, conversation context, and system instructions consumes 500-800 tokens of the 200K context window. Over a long coding session (100+ exchanges), this compounds:
- 100 prompts * 700 tokens = 70K tokens consumed by judge prompts alone
- That's 35% of the context window spent on relevance filtering, not actual work

The subagent approach isolates this cost. The ~3-5s latency is acceptable because the user explicitly initiated the search.

**Pragmatic recommendation for Q2:** Keep the subagent pattern for on-demand search. The context window savings justify the latency. Do NOT move the judge into the main context.

---

### Q3: Can the UserPromptSubmit hook use Claude's own LLM instead of separate API?

**Answer: No, and we should stop trying.**

#### Technical constraint (hard)

From `hooks/hooks.json:43-52` and CLAUDE.md:
> Hook scripts (type: "command") run as standalone Python subprocesses. They CANNOT access Claude Code's Task tool.

This is not a workaround-able limitation. The hook subprocess has no channel to Claude's inference except stdout text injection. It cannot:
- Call the Task tool
- Spawn a subagent
- Access Claude's model weights
- Use the conversation's OAuth tokens

#### The alternatives evaluated

| Alternative | Feasibility | Latency | API Key Needed | Verdict |
|------------|-------------|---------|----------------|---------|
| Direct Anthropic API (current) | Works | +1-3s/prompt | YES | Inaccessible to most users |
| Hook outputs "please judge these" prompt for Claude | Works (stdout) | +0ms hook, +~2s Claude thinking | No | Pollutes main context with judge reasoning |
| Hook just outputs BM25 results, no judge | Works | +0ms | No | Already the default behavior |
| Hook outputs nudge, Claude searches on-demand | Works | +0ms hook, +3-5s if Claude searches | No | Best cost/UX tradeoff |

#### Pragmatic recommendation for Q3

**Drop the hook-side judge entirely.** Three supporting arguments:

1. **The API key barrier is a dealbreaker.** The target audience (Claude Max/Team users) authenticates via OAuth. They don't have `ANTHROPIC_API_KEY`. Requiring a separate billing account for a precision feature is hostile UX. From `memory_retrieve.py:386-388`:
   ```python
   if judge_cfg.get("enabled", False) and not os.environ.get("ANTHROPIC_API_KEY"):
       print("[INFO] LLM judge enabled but ANTHROPIC_API_KEY not set. "
             "Using BM25-only retrieval.", file=sys.stderr)
   ```
   This warning message is the hook admitting the feature doesn't work for most users.

2. **BM25 precision at ~65-75% is acceptable for 3 injected results.** With `max_inject=3`, a 70% precision rate means ~0.9 irrelevant results per prompt. These consume ~50-100 tokens each. The main model (opus/sonnet) easily ignores low-confidence irrelevant context. From rd-08-final-plan.md: "memories are 0.3-0.75% of the 200K context window."

3. **The on-demand search path already has a key-free judge.** When precision matters (user explicitly searching), the `/memory:search` skill uses a Task subagent judge at zero extra API cost. The architecture already has the right judge in the right place.

**Cost savings from dropping hook judge:**
- Eliminates ~$0.001-0.003 per prompt * ~100 prompts/day = ~$3-9/month in API costs
- Eliminates 1-3s latency penalty on every prompt
- Eliminates ANTHROPIC_API_KEY as a setup requirement
- Eliminates 363 LOC in `memory_judge.py` from the critical path (reduces attack surface)

---

### Q4: If Claude Code (via subagent) IS the judge, do we need pre-defined judge criteria?

**Answer: Yes, but lighter criteria than current.**

#### The case for keeping criteria

Without criteria, judge behavior changes across:
- Model versions (haiku 4.5 vs future haiku 5.0)
- Context window fullness (early session vs late session)
- Prompt phrasing ("find memories about auth" vs "auth")

The on-demand search judge in SKILL.md already uses lenient criteria:
```
Which of these memories are RELATED to the user's query? Be inclusive --
a memory qualifies if it is about a related topic, technology, or concept,
even if the connection is indirect.
```

This is the right level: light guidance without over-constraining Claude's judgment.

#### The case against strict criteria (for on-demand)

The hook-side judge (`memory_judge.py`) uses strict criteria with explicit qualification/disqualification rules. This makes sense for silent injection (high-precision requirement) but is unnecessarily restrictive for user-initiated search where broader recall is preferred.

#### Pragmatic recommendation for Q4

**Keep light criteria for on-demand judge. No criteria needed for auto-inject (no judge in that path).**

If the hook judge is dropped per Q3 recommendation:
- Auto-inject: BM25 only, no judge, no criteria needed
- On-demand: Subagent judge with current lenient SKILL.md criteria (already implemented, working well)

The SKILL.md criteria serve as a **behavioral contract** that ensures consistent output across model versions. Keep them, but don't add more complexity. The current ~10-line prompt is sufficient.

---

### Q5: What is the optimal architecture?

#### Proposed architecture: "Tiered Inject + Agentic Pull"

```
User types prompt
    |
    v
[UserPromptSubmit Hook] (15s timeout, typically <200ms)
    |
    +-- Prompt < 10 chars? -> exit (no latency)
    +-- No index? -> exit
    +-- FTS5 BM25 search (~100ms)
    |
    +-- HIGH confidence results (>=75% of best score)
    |       -> Inject directly as <memory-context> (current format)
    |       -> ~50-150 tokens, deterministic, reliable
    |
    +-- MEDIUM/LOW confidence results
    |       -> Emit <memory_nudge> with topic summary
    |       -> ~20-40 tokens: "Found memories about: auth, JWT. Use /memory:search if helpful."
    |       -> Claude decides whether to act
    |
    +-- No results -> exit silently (0 tokens)

Claude receives injected context + optional nudge
    |
    +-- High-confidence memories: uses them directly (proven behavior)
    +-- Nudge present: evaluates whether to search
    |       -> If context needed: invokes /memory:search (Task subagent judge, no API key)
    |       -> If not needed: ignores nudge (costs only ~20 tokens)
    +-- No nudge: proceeds normally (zero overhead)
```

#### Why this architecture wins on every pragmatic dimension

| Dimension | Current (BM25 + optional API judge) | Proposed (Tiered inject + agentic pull) |
|-----------|-------------------------------------|----------------------------------------|
| **Latency (common case)** | ~100ms (no judge) / ~1-3s (with judge) | ~100ms always |
| **Latency (search needed)** | N/A (no autonomous search) | ~3-5s when Claude decides to search |
| **API cost** | $3-9/month if judge enabled | $0 (uses subscription tokens) |
| **API key required** | Yes (for judge) | No |
| **Precision (auto-inject)** | ~65-75% (BM25) / ~85-90% (with judge) | ~80-85% (high-confidence filter) |
| **Recall (autonomous)** | 0% (no autonomous search) | Variable (depends on Claude acting on nudge) |
| **Transparency** | Invisible | Nudges are visible; searches are visible |
| **Context window cost** | ~50-150 tokens/prompt (always) | ~50-100 tokens high-conf + ~20 tokens nudge (when applicable) |
| **Config complexity** | 8 judge config keys | 0 new config keys |
| **Implementation effort** | Already built (363 LOC judge) | ~50 LOC change to retrieve.py + SKILL.md instruction |
| **Maintenance surface** | memory_judge.py + API versioning + key management | BM25 only (stdlib) |

#### What we lose

1. **Judge precision on auto-inject (~85-90% -> ~80-85%).** Mitigated by only injecting high-confidence results and letting Claude pull the rest on-demand.
2. **Deterministic recall for medium-confidence matches.** Current system always injects top-3. Proposed system injects high-confidence only and nudges for the rest. If Claude ignores the nudge, those memories are lost. Mitigated by the fact that medium-confidence matches are often false positives anyway (~25-35% of the time per BM25 precision data).
3. **The existing judge code (363 LOC) becomes dead code for auto-inject.** It remains useful for the on-demand search subagent judge if ever needed directly. Alternatively, deprecate and remove.

#### What we gain

1. **Zero API key requirement.** Every user benefits from day one, no setup.
2. **Autonomous search capability (new).** Claude can now decide to search memories -- a capability that doesn't exist today. This addresses the gap identified in `temp/final-analysis.md` section "Path 3: NOT IMPLEMENTED."
3. **Transparency.** Users see when memories are relevant. The nudge is visible. The search action is visible.
4. **Lower latency.** No judge overhead on every prompt. Search latency only paid when needed.
5. **Simpler configuration.** Remove 8 judge-related config keys from the auto-inject path.

---

## External Model Opinions

### Codex (OpenAI) Opinion

**Recommendation: Option C (hook emits suggestion signal + on-demand search), with tweak.**

Key findings from Codex's code-level analysis:
- Verified hook judge hard-requires `ANTHROPIC_API_KEY` at `memory_retrieve.py:369-371`
- Verified on-demand skill judge is Task-based/no-key at `SKILL.md:116`
- Benchmark confirms BM25 is fast: 5 tests passed in 0.11s for 500-doc corpus
- Noted README timeout mismatch (10s documented vs 15s actual in `hooks.json:50`)

Codex's specific recommendation:
> "Keep deterministic BM25 auto-inject for high-confidence matches, use stronger 'search suggestion' flow for low-confidence/no-match cases. This gives best developer UX/cost balance: low always-on latency, no extra mandatory billing credential, and better precision/recall when users explicitly request memory search."

**Assessment:** Closely aligned with my recommendation. Codex independently arrived at the same tiered approach.

### Gemini (Google) Opinion

**Recommendation: Replace heavy auto-inject with BM25 nudge. Push toward "agentic pull."**

Key insights from Gemini:
1. **"Silent auto-injection feels magical when it works, but infuriating when it fails."** Developers prefer predictable, transparent systems.
2. **"Claude will use /memory:search when nudged, but ONLY if the nudge is phrased as a directive, not just an observation."** Passive hints get ignored; explicit instructions work.
3. **Progressive disclosure pattern from Cursor/Copilot:** Show a compact indicator of available context, let the user/agent expand it.
4. **Proposed "Context Pinning" concept:** A `/memory:pin` command for core architectural docs that should always be injected. Interesting idea for a future iteration.

Gemini's nudge format suggestion:
```xml
<memory_nudge>
Found 3 project memories matching 'JWT'.
If you lack context to complete the user's request safely, you MUST use the
`memory:search` tool to read them before proceeding.
</memory_nudge>
```

**Assessment:** Gemini pushes further toward nudge-only than I recommend. I disagree with eliminating high-confidence auto-inject entirely -- deterministic injection for strong matches provides a reliability floor that pure nudging cannot guarantee. But the directive nudge phrasing insight is valuable.

### Consensus across models

All three perspectives (mine, Codex, Gemini) agree on:
1. **Drop the hook-side LLM judge.** The API key requirement is a dealbreaker.
2. **Keep BM25 as the always-on retrieval engine.** Fast, free, good enough.
3. **Use nudge/suggestion for uncertain matches.** Let Claude decide.
4. **On-demand search via subagent is the right pattern.** No API key, full context.

Disagreement is only on the inject-vs-nudge balance:
- Codex: Inject high-confidence, nudge low-confidence (same as my recommendation)
- Gemini: Nudge everything, inject nothing (more radical, unproven)
- Me: Inject high-confidence, nudge medium/low (middle ground)

---

## Vibe-Check Results

The vibe-check identified three important corrections to my initial thinking:

1. **Status Quo Bias:** I was anchoring on "keep auto-inject, improve it" without questioning whether silent injection is the right paradigm. The vibe-check correctly pushed me to consider transparency as a first-class requirement.

2. **Untested Assumption:** My position that "nudge is risky because Claude is unpredictable" was an assumption, not evidence. The vibe-check pointed out this is the most critical assumption to test before building anything. Gemini's response partially addresses this -- agentic models respond well to directive nudges.

3. **False Dichotomy:** I was framing "auto-inject vs nudge" as binary. The tiered approach (high-confidence inject + medium/low nudge) emerged from the vibe-check pushing me past this false dichotomy.

---

## Final Pragmatic Recommendation

### Immediate changes (low effort, high impact)

1. **Deprecate the hook-side LLM judge.** Change default config to remove judge-related keys from the auto-inject path. Keep `memory_judge.py` for potential future use but remove it from the hook's critical path. (~20 LOC config change)

2. **Add confidence-tiered output to the hook.** High-confidence results inject directly. Medium/low results emit a `<memory_nudge>` with topic summary and directive instruction. (~30-50 LOC in `memory_retrieve.py`)

3. **Add autonomous search instruction to SKILL.md or CLAUDE.md.** A single instruction telling Claude to use `/memory:search` when it encounters a nudge or when it needs project context. (~5-10 lines of instruction)

### Future considerations (higher effort, test first)

4. **Measure nudge compliance rate.** Before investing further, test: does Claude actually invoke `/memory:search` when it receives a nudge? Run 20-30 manual tests across different prompt types. If compliance is >80%, the architecture works. If <50%, fall back to injecting top-3 always.

5. **Evaluate "context pinning" concept.** Gemini's idea of `/memory:pin` for always-injected core documents is interesting but should be validated against real user workflows before implementing.

6. **Consider reducing hook timeout from 15s to 5s.** With no judge in the path, BM25 completes in <200ms. A 15s timeout wastes budget that should fail fast. (1-line change in `hooks.json`)

### What NOT to do

- Do NOT try to bridge hooks to Claude's Task tool. The subprocess boundary is a hard constraint. Work with it, not against it.
- Do NOT build a new judge mechanism for the hook path. The ROI is negative when the on-demand path already has a working subagent judge.
- Do NOT make the nudge passive. "You have memories about auth" will be ignored. "You MUST search if you lack context" will be followed.
- Do NOT remove `memory_judge.py` entirely. It has value as a module for the on-demand search path if the SKILL.md subagent approach ever needs to be replaced.
