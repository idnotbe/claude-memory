# Creative Alternatives Analysis: Memory Retrieval Architecture

**Analyst:** Creative Alternatives Explorer
**Date:** 2026-02-22
**Status:** Complete

---

## Executive Summary

This analysis goes beyond the 5 stated design questions to propose unconventional retrieval architectures. After consulting Gemini 3.1 Pro, Codex (OpenAI), and vibe-check validation, I present 5 creative proposals ranked by feasibility-to-impact ratio, plus 3 honorable mentions. The key insight: **the best creative solution is incremental, not revolutionary** -- a confidence-gated hybrid that naturally creates an autonomous search pathway for Claude.

---

## Proposal 1: Confidence-Gated Hybrid Routing (RECOMMENDED)

### Concept
Instead of binary "inject or don't inject," use BM25 confidence scores to dynamically choose the injection strategy per prompt.

### How It Works

```
UserPromptSubmit hook runs BM25 (as today)
  |
  |-- HIGH confidence (BM25 ratio >= 0.75 of best): Full auto-inject
  |     (Current behavior: title + path + tags in <memory-context>)
  |
  |-- MEDIUM confidence (BM25 ratio 0.40-0.75): Lightweight hint
  |     Output: "<memory-hint>Potentially relevant: [Decision: JWT auth],
  |              [Constraint: API rate limits]. Use /memory:search for details.</memory-hint>"
  |
  |-- LOW confidence (ratio < 0.40) or no matches: Silent (no injection)
```

### Technical Implementation
- **Changes to `memory_retrieve.py`:** ~30 LOC. The `confidence_label()` function already computes high/medium/low brackets. Route output through a new `_output_hints()` function for medium-confidence results.
- **New skill:** `/memory:read <path>` -- trivial skill (~20 lines of SKILL.md) that reads a specific memory JSON file and presents its content. This lets Claude follow up on hints without full search overhead.
- **No new dependencies, no schema changes, no new files beyond one SKILL.md.**

### Why This Works
1. **Solves the autonomy gap:** Medium-confidence hints teach Claude when to search. Claude sees titles and can decide whether to invoke `/memory:search` or `/memory:read`.
2. **Reduces context pollution:** Only high-confidence results consume full injection tokens. Medium results are ~50 tokens instead of ~200.
3. **Backwards compatible:** High-confidence behavior is identical to current system.
4. **No API key required:** Pure BM25 scoring, no LLM needed.

### Cognitive Science Parallel
This mirrors human "tip of the tongue" phenomenon -- you know you know something relevant, but you need to actively recall it. The hint is the "feeling of knowing."

### Pros
- Minimal implementation effort (~50 LOC total)
- Zero new infrastructure
- Incremental deployment (can ship behind a config flag)
- Naturally teaches Claude to use /memory:search
- Preserves all existing security hardening

### Cons
- BM25 thresholds are domain-agnostic; may need per-workspace tuning
- Medium-confidence hints could become "wallpaper" if Claude ignores them
- Does not address spatial/contextual retrieval (see Proposal 3)

### Risk Assessment: LOW
- Worst case: medium-confidence hints are ignored (equivalent to current "no inject" behavior)
- Codex critique: "reminder text does not mean behavior change" -- mitigated by providing `/memory:read` skill for easy follow-up (lower friction than `/memory:search`)

### Implementation Estimate
- 1 session, ~50 LOC changes to memory_retrieve.py + 1 new SKILL.md file

---

## Proposal 2: Progressive Disclosure with Autonomous Read-Back

### Concept
Hook injects lightweight "summary cards" (title + category + confidence) for ALL matches above threshold. Add a `/memory:read <path>` skill. Claude autonomously decides which memories to expand.

### How It Works

```
Hook output (always lightweight):
<memory-cards source=".claude/memory/">
  <card category="decision" confidence="high" path=".claude/memory/decisions/jwt-auth.json">
    JWT authentication decision #tags:auth,jwt
  </card>
  <card category="constraint" confidence="medium" path=".claude/memory/constraints/rate-limits.json">
    API rate limit constraints #tags:api,limits
  </card>
</memory-cards>

Claude sees cards -> reads relevant ones via /memory:read -> acts on full content
```

### Technical Implementation
- **Changes to `memory_retrieve.py`:** Replace `_output_results()` with `_output_cards()` (~40 LOC)
- **New skill:** `/memory:read <path>` reads one memory JSON and presents formatted content
- **Config:** New `retrieval.output_mode` setting: `"full"` (current) | `"cards"` (new) | `"hybrid"` (Proposal 1)

### Why This Differs from Proposal 1
Proposal 1 uses confidence to GATE between full inject vs. hint. This proposal ALWAYS outputs cards (even for high confidence) and delegates ALL reading to Claude. More aggressive token savings, but adds latency.

### Pros
- Maximum token efficiency (cards are ~30 tokens vs ~200 for full results)
- Claude has full agency over what to read
- Can surface more candidates (5-8 cards vs 3 full results)
- Clean separation: hook does ranking, Claude does relevance judgment

### Cons
- **Latency penalty:** Claude must invoke a skill to read any memory, adding 1+ turn
- **Behavioral reliability:** Claude may not consistently read cards (Codex critique)
- **Critical memories missed:** If Claude skips a constraint card, the constraint is not enforced
- Higher complexity than Proposal 1

### Risk Assessment: MEDIUM
- The latency concern is real: if Claude needs a constraint to avoid a mistake, it must read the card BEFORE acting. No guarantee it will.

### Gemini Opinion
"Drastically reduces token usage... but introduces an extra turn/latency if Claude decides it does need the memory." Recommended combining with spatial binding.

### Implementation Estimate
- 1-2 sessions, ~80 LOC + 1 SKILL.md

---

## Proposal 3: Working Memory + Long-Term Memory (Cognitive Architecture)

### Concept
Maintain a small `working_memory.md` file that is always injected (O(1) read, no search). Claude manages it actively via `/memory:promote` and `/memory:demote` skills. FTS5 remains for deep recall via `/memory:search`.

### How It Works

```
Session flow:
1. UserPromptSubmit hook reads .claude/memory/working_memory.md (static file, ~20 lines)
2. Always injects contents (no search overhead)
3. Claude can /memory:promote <path> to add a memory to working set
4. Claude can /memory:demote <title> to remove from working set
5. /memory:search still available for deep recall

working_memory.md format:
---
auto_populated: [last session summary path]
manual: [user-promoted items]
capacity: 5 items max
---
[Rendered content of active working memory items]
```

### Technical Implementation
- **New file:** `.claude/memory/working_memory.md` (generated/managed)
- **Hook change:** `memory_retrieve.py` reads this file instead of running FTS5 (~simpler, faster)
- **New skills:** `/memory:promote` and `/memory:demote` (~40 LOC each in SKILL.md)
- **Auto-population:** Stop hook (triage) could auto-add last session summary to working memory
- **Capacity enforcement:** Working memory capped at 5 items (~500 tokens max)

### Cognitive Science Parallel
Direct analog to Baddeley's Working Memory model. Humans maintain ~4-7 items in working memory while long-term memory requires active retrieval. The "promote/demote" cycle mirrors rehearsal.

### Pros
- O(1) retrieval: no search on every prompt
- Predictable token cost per session (capped at ~500 tokens)
- Claude is fully aware of what it "knows" (explicit working set)
- Elegant cognitive architecture parallel

### Cons
- **Self-management reliability:** LLMs are inconsistent at proactively managing state files. Claude may forget to promote relevant memories or demote stale ones.
- **Cold start problem:** New sessions start with only last session summary. If Claude needs a constraint from 5 sessions ago, it must actively search.
- **Two new skills to implement and document**
- **Schema addition:** working_memory.md is a new file format to maintain

### Risk Assessment: MEDIUM-HIGH
- The biggest risk is behavioral: will Claude actually use promote/demote consistently?
- Vibe-check flagged this: "betting on consistent agent behavior that may not materialize"

### Gemini Opinion
"Claude actively gardens its own immediate context. It is hyper-aware of what is in its working memory. Zero Python search overhead." But warned: "If it forgets to demote items, working memory becomes bloated."

### Codex Critique
Not directly addressed, but the "authority ambiguity" concern from their memory agent critique applies here too -- Claude becomes responsible for memory management on top of its primary task.

### Implementation Estimate
- 2-3 sessions, ~200 LOC + 2 new SKILL.md files + working_memory.md format

---

## Proposal 4: Spatial/Environmental Context Binding

### Concept
Tag memories with file paths, directories, and git branches. Hook retrieves based on the current working environment (CWD, git status, recently modified files) rather than prompt text analysis.

### How It Works

```
Memory write (enhanced schema):
{
  "title": "Auth middleware must validate JWT",
  "category": "constraint",
  "spatial_bindings": {
    "directories": ["src/auth/", "src/middleware/"],
    "files": ["src/auth/jwt.ts"],
    "branches": ["feature/auth-*"]
  },
  ...
}

UserPromptSubmit hook:
1. Read CWD from hook input
2. Run `git status --porcelain` (or read from hook input)
3. Check git branch name
4. Match memories by spatial_bindings intersection with current context
5. Inject spatially-matched memories (no FTS5 needed)
```

### Technical Implementation
- **Schema change:** Add `spatial_bindings` field to memory JSON schema
- **Hook change:** New matching logic in `memory_retrieve.py` (~60 LOC)
- **Write change:** Triage hook or SKILL.md must extract spatial context during memory creation
- **Index change:** Index.md would need spatial metadata or a separate spatial index

### Cognitive Science Parallel
Context-dependent memory (Godden & Baddeley, 1975): memories are easier to recall in the same environment where they were encoded. "When you walk into the kitchen, you remember you need milk."

### Pros
- Zero NLP overhead at retrieval time (pure path/string matching)
- Extremely high precision for location-specific rules
- Complements text-based search (different signal, not competing)
- Natural fit for constraints ("always X when editing files in Y")

### Cons
- **Schema migration required:** Existing memories lack spatial bindings
- **Not all memories are spatial:** Global preferences ("use semicolons") and abstract decisions ("chose PostgreSQL over MongoDB") have no meaningful directory binding
- **Requires spatial context at write time:** Triage hook must capture file/directory context during memory creation
- **Git dependency:** Branch matching requires git CLI access from hook

### Risk Assessment: MEDIUM
- Schema migration is the main blocker
- Partial coverage (spatial + text-based needed together)

### Gemini Opinion
"Zero FTS/NLP overhead. Extremely high precision for codebase rules." Recommended as complement to Progressive Disclosure, not standalone. "Does not work for global, non-spatial preferences."

### Codex Critique
Not directly evaluated, but the "narrow coverage" concern aligns with their general critique that partial solutions look incomplete to users.

### Implementation Estimate
- 2-3 sessions, ~150 LOC + schema changes + spatial index

---

## Proposal 5: Asynchronous Memory Digest (Moonshot)

### Concept
On every memory write, trigger a background process to rewrite a compressed `memory_digest.md`. This static file is always injected -- O(1) read, zero search latency, complete coverage of all memories.

### How It Works

```
Write-time pipeline:
memory_write.py saves JSON
  -> triggers digest regeneration
  -> LLM (via Task subagent or API) reads ALL active memories
  -> compresses into dense bullet points (~500-1000 tokens)
  -> writes .claude/memory/memory_digest.md

Read-time (every prompt):
Hook reads memory_digest.md -> injects as context
(No FTS5, no scoring, no search at all)
```

### Technical Implementation
- **New script:** `memory_digest.py` -- reads all active memories, generates compressed summary
- **Hook change:** `memory_retrieve.py` replaced with trivial file reader (~10 LOC)
- **Trigger:** PostToolUse hook on memory writes, or integrated into memory_write.py
- **LLM requirement:** Digest generation requires LLM access (Task subagent in skill, or API call)

### Cognitive Science Parallel
Sleep consolidation: the brain compresses daily episodic memories into stable semantic knowledge during sleep. The digest is the "consolidated" form of all memories.

### Pros
- O(1) retrieval with zero runtime search
- Claude always has the full "picture" of all memories
- No precision/recall tradeoff (everything is summarized)
- Digest can be tailored for token efficiency

### Cons
- **Lossy compression:** At scale (100+ memories), critical details will be lost
- **LLM dependency for digest generation:** Requires either API key or Task subagent
- **Staleness between writes:** Digest is only current as of last memory write
- **Catastrophic forgetting:** LLM summarization naturally drops details that seem unimportant but may be critical
- **Cost:** Regenerating digest on every write is expensive for frequent writers

### Risk Assessment: HIGH
- The lossiness problem is fundamental and gets worse with scale
- Requires LLM access for digest generation (breaks "no API key" constraint unless done via Task subagent)

### Gemini Opinion
"O(1) retrieval time. No runtime FTS needed. Claude always has the full picture." But: "As the number of memories scales into the hundreds, the LLM will struggle to compress them all into a small digest without catastrophic forgetting."

### Implementation Estimate
- 3-4 sessions, ~300 LOC + new script + LLM integration

---

## Honorable Mentions (Not Ranked)

### A. Doc2Query / Memory Compiler
**Concept:** At write time, use an LLM to generate "the questions this memory answers" and store them as searchable metadata. At read time, match user prompt against pre-generated questions instead of raw content.

**Verdict:** Interesting IR technique (recognized as "Doc2Query" by Gemini), but still requires BM25 at read time -- you cannot do strict hash lookup because query space is infinite. Improves recall but adds write-time LLM dependency. Better as an enhancement to FTS5 indexing than a standalone architecture.

### B. CLAUDE.md Integration
**Concept:** Compile the most critical memories (constraints, global preferences) directly into CLAUDE.md or a `.claude/user_memory.md` that Claude Code loads natively.

**Verdict:** Maximum leverage (zero latency, Claude treats it as system instructions), but causes **git churn** if CLAUDE.md is tracked. Only viable for a tiny, strictly-gated subset. Gemini suggested exploring whether Claude Code supports loading additional `.claude/*.md` files beyond `CLAUDE.md` -- if so, this becomes viable for a small "always-on" memory tier.

### C. Federated Category Routing
**Concept:** Route queries to category-specific mini-indexes based on prompt intent classification. "How do I deploy?" goes to runbooks only.

**Verdict:** Intent classification without an LLM is too brittle. User prompts frequently cross category boundaries. Better implemented as **soft category boosting** within the existing single FTS5 index (which the current `CATEGORY_PRIORITY` dict already partially does).

---

## External Model Opinions Summary

### Gemini 3.1 Pro (via pal clink)
- **Top recommendation:** Hybrid of Progressive Disclosure + Environmental Binding
- **Key insight:** "The constraint that hooks run as Python subprocesses without LLM access means eager auto-injection must rely on fast, cheap methods. Conversely, because skills CAN trigger Claude tools, you can shift the heavy lifting to the LLM."
- **Novel contribution:** Identified the Doc2Query pattern as a recognized IR technique, validated Working Memory cognitive architecture

### Codex / OpenAI (via pal clink)
- **Stance:** Ruthlessly critical of all 6 options. "All six have serious failure modes."
- **Key insight:** "Immediate next steps: instrument real usage, build replay benchmark, and A/B minimal changes before introducing heavy architectures."
- **Most damning critiques:**
  - Summary Cards: "title-only retrieval over-rewards catchy but vague titles"
  - Progressive Disclosure: "reminder text does not mean behavior change"
  - Two-tier: "recency bias masquerades as relevance"
  - Skill-first: "no proactive guardrails -- Claude misses critical constraints unless explicitly asked"
  - Memory agent: "authority ambiguity... trust collapses fast"
- **Missing data flagged:** No measured precision/recall by query class; unknown `/memory:search` invocation rates after reminders; unknown p95 latency budget

### Vibe-Check (Self-Assessment)
- **Verdict:** Adjusted ranking. Promoted Progressive Disclosure (#4 -> #2) as natural complement to Confidence-Gated Hybrid. Demoted Working Memory (#2 -> #3) due to self-management reliability concerns.
- **Key warning:** "Complex Solution Bias -- proposals #2, #3, and #5 each introduce new subsystems when the core problem can be largely solved by tuning what the hook already outputs."
- **Pattern flag:** Feature Creep potential with cognitive architecture proposal

---

## Ranked Recommendations

### Phase 1: Ship Immediately (1-2 sessions)

| Rank | Proposal | Effort | Risk | Impact |
|------|----------|--------|------|--------|
| 1 | Confidence-Gated Hybrid | ~50 LOC | Low | High -- solves autonomy gap, reduces noise |
| 2 | Progressive Disclosure + /memory:read | ~80 LOC | Medium | Medium -- token savings, Claude agency |

**Recommended:** Implement Proposal 1 first. If data shows Claude consistently ignores medium-confidence hints, upgrade to Proposal 2's card format. The two are composable -- #1 is a subset of #2.

### Phase 2: Explore After Data Collection (2-3 sessions each)

| Rank | Proposal | Effort | Risk | Impact |
|------|----------|--------|------|--------|
| 3 | Working Memory Cognitive Architecture | ~200 LOC | Medium-High | High if reliable |
| 4 | Spatial/Environmental Binding | ~150 LOC + schema | Medium | Medium (complements text search) |

**Recommended:** Implement only after Phase 1 is shipped and usage data is collected. Working Memory is the most architecturally elegant but depends on Claude behavioral consistency. Spatial Binding is a natural complement to any text-based approach.

### Phase 3: Future Research

| Rank | Proposal | Effort | Risk | Impact |
|------|----------|--------|------|--------|
| 5 | Asynchronous Memory Digest | ~300 LOC | High | High if lossiness solved |

**Recommended:** Only pursue if memory corpus regularly exceeds ~50 entries and token budget is a critical constraint. The lossy compression problem makes this a research project, not a feature.

---

## Key Insight: The Creative Answer Is Restraint

The most creative insight from this analysis is counterintuitive: **the best architecture change is the smallest one.** The current system already has a solid FTS5 BM25 engine, confidence labeling, and a search skill. The missing piece is not a new architecture -- it is a **routing layer** that connects the existing pieces intelligently.

Confidence-Gated Hybrid (Proposal 1) adds this routing layer with ~50 lines of code, no new dependencies, no schema changes, and no behavioral reliability risks. It is the creative answer precisely because it resists the temptation to build something new when tuning something existing is sufficient.

The ambitious proposals (#3 Working Memory, #4 Spatial Binding, #5 Digest) are genuinely interesting architectures that deserve exploration -- but only after the simple fix is shipped and measured.

---

## Appendix: Comparison Matrix

| Dimension | Current | P1: Confidence-Gated | P2: Progressive Cards | P3: Working Memory | P4: Spatial | P5: Digest |
|-----------|---------|----------------------|----------------------|-------------------|-------------|------------|
| Autonomy gap | No | Solved (hints) | Solved (cards) | Partial (cold start) | No | N/A |
| Token cost/prompt | ~200-600 | ~100-400 | ~50-150 + reads | ~500 fixed | Variable | ~500-1000 fixed |
| Latency | ~100ms | ~100ms | ~100ms + read turns | ~5ms | ~50ms | ~5ms |
| Precision | ~65-75% | ~70-80% (noise reduction) | Claude-judged | N/A (no search) | Very high (narrow) | N/A (always on) |
| API key needed | No (unless judge) | No | No | No | No | Yes (for digest gen) |
| New LOC | 0 | ~50 | ~80 | ~200 | ~150 | ~300 |
| Schema changes | None | None | None | New file format | New field | New file format |
| Risk | Baseline | Low | Medium | Medium-High | Medium | High |
