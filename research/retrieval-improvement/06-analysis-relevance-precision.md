# Analysis: Keyword Matching Relevance Risk & Precision Strategies

**Date:** 2026-02-20
**Context:** User's critical concern about irrelevant info injection

---

## The User's Core Argument

> "in the case of the auto insert of the information, the info should be 100% related / correct to the claude code's context. so i thought vector embedding or llm judgment are must. but you recommended simple keyword matching. it has a lot of risks that claude-memory inserts irrelevant info to claude code."

**This concern is valid and well-founded.** The final report underweighted this risk.

---

## Current System: How Bad Is It?

### Concrete False Positive Example

User prompt: "how to fix the authentication bug in the login page"

Tokenized: `{fix, authentication, bug, login, page}`

Matching memories (assuming tags shown in parentheses):
| Memory Title | Score | Breakdown | Actually Relevant? |
|---|---|---|---|
| "JWT authentication token refresh flow" (tags: auth, jwt) | 3 | authentication=title+2, auth prefix+1 | Maybe |
| "Login page CSS grid layout" | 4 | login=title+2, page=title+2 | **NO** |
| "API authentication middleware setup" | 2 | authentication=title+2 | Maybe |
| "Fix database connection pool bug" | 4 | fix=title+2, bug=title+2 | **NO** |
| "Login rate limiting configuration" | 2 | login=title+2 | **NO** |

*Note: "JWT authentication token refresh flow" scores 3, not 4 -- "auth" tag is a prefix match (+1), not an exact match (+3), because the prompt word is "authentication" not "auth". "token" in the title does not match any prompt word.*

**Result:** 3 out of 5 injected memories are irrelevant. ~60% false positive rate (estimated, not measured -- see caveat below).

### Why This Happens

1. **No semantic understanding**: "fix" in "fix the auth bug" ≠ "fix" in "fix database pool". Keyword matching can't distinguish.
2. **No body content**: Index only has title + tags. Two memories about "login" could be about completely different things.
3. **Low threshold**: Score ≥ 1 is enough for injection. A single 4-char prefix match qualifies.
4. **No negative signals**: No way to say "this matched keywords but is clearly wrong topic."

### Cost of False Positives

| Cost | Impact |
|---|---|
| Context window waste | 200-500 tokens per irrelevant memory × 3 = 600-1500 wasted tokens |
| Claude confusion | Claude may try to apply irrelevant info to current task |
| User trust erosion | User sees irrelevant injections → disables retrieval entirely |
| Worse than no injection | Random context is worse than no context (polluted reasoning) |

---

## Can Keyword Matching Be Made Precise Enough?

### With Current System: NO (score_entry is too coarse)

The flat scoring (title=+2, tag=+3, prefix=+1) can't distinguish "weakly related" from "highly relevant."

### With BM25 + Body Content: PARTIALLY

BM25 improvements:
- **IDF weighting**: rare terms ("pydantic") matter more than common ones ("fix", "bug")
- **Body tokens**: more signal to distinguish "login auth" from "login CSS"
- **Field weighting**: tag match (4x) > title match (3x) > body match (1x)

But BM25 still can't understand:
- "fix the auth bug" is about debugging, not about setting up auth
- "login page" in the context of frontend vs backend
- Intent (learning vs fixing vs refactoring)

### Estimated Precision After BM25 (rough estimates, not measured)

> **Caveat:** All precision numbers in this table are directional rough estimates based on constructed examples, NOT measured values from real usage data. An evaluation framework (Phase 0) is required before any precision claims can be validated.

| Scenario | Current (est.) | BM25 (est.) | Vector/LLM (est.) |
|---|---|---|---|
| General query ("auth bug") | ~40% | ~60% | ~80-85% |
| Specific query ("pydantic v2 migration") | ~70% | ~85% | ~90% |
| Ambiguous query ("fix the bug") | ~20% | ~30% | ~50% |
| **Average** | **~40%** | **~55-60%** | **~75-85%** |

**Conclusion: BM25 likely improves precision over naive keywords, but the specific improvement magnitude is unmeasured and will depend heavily on the actual query distribution and memory corpus.**

---

## Honest Assessment of Alternatives

### Vector Embeddings (Best Precision, Worst Feasibility)

- Precision: ~80-85% (understands semantic similarity)
- But: 500MB+ dependency, 2-5s cold start on WSL2, violates stdlib constraint
- **Verdict: Technically best, practically impossible within current constraints**

### LLM-as-Judge (Excellent Precision, Network Dependency)

- Precision: ~85-90% (LLM understands intent)
- But: requires API call per retrieval, fails offline, privacy concern
- **Verdict: Best precision available, but dependency on network is real**
- **Insight: Claude Code itself IS an LLM — can we use it instead of an external API?**

### High-Threshold Keyword + Manual Search (Pragmatic Hybrid)

**This is the approach I recommend:**

- Auto-inject: Only when confidence is VERY high (precision-optimized)
- Manual search: Skill/command for explicit deeper search
- Result: Near-zero false positive auto-injection + full recall on demand

---

## Recommended Approach: Precision-First Hybrid

### Tier 1: Conservative Auto-Inject (Hook, Higher Threshold)

> **Threshold analysis (verified against `score_entry()` math):**
> - Max score from a single keyword: 5 (title+2 AND tag+3) or 6 with description bonus, 8 with all bonuses
> - Threshold 6 requires 2+ distinct keyword matches in most cases (single-keyword only reaches 6 if tag+title+description or tag+title+recency)
> - Threshold 3-4 eliminates worst false positives (single-prefix matches score only 1) while preserving single-keyword exact matches
> - **Recommended starting threshold: 4** (eliminates low-quality matches, preserves title+tag or 2-title matches)

```
Only inject when:
- Score >= 4 (current minimum is effectively 1)
- Cap at max_inject=3 (not 5)
```

Effect: Eliminates the worst false positives (single prefix match = 1 point, single title match = 2 points) while preserving reasonably confident matches.

Trade-off: Will miss some relevant memories (lower recall), but that's acceptable because...

### Tier 2: On-Demand Search (Skill or MCP)

When Claude thinks memory might be relevant but nothing was auto-injected:
- `/memory-search query` — explicit search with lower threshold
- Returns more candidates, Claude applies its own judgment
- Claude (the LLM) acts as the reranker — it can understand context

**This is the "LLM-as-Judge" approach WITHOUT external API dependency!**

Claude Code itself is the LLM. When it explicitly searches memories, it reads the results and applies its own judgment about relevance. This is far better than blindly injecting via hook.

### Tier 3: Conversation Context (Proposed, Not Yet Implemented)

Hooks already receive `transcript_path` (confirmed in code -- `memory_triage.py` uses it, but `memory_retrieve.py` does NOT). Adding transcript parsing to the retrieval hook would provide:
- Richer matching signal from conversation context (not just the single prompt)
- Ability to understand "we're debugging auth" from multiple recent messages
- Potential for keyword matching to become more precise with more context

> **Important:** This is a proposed enhancement, not a current capability. The retrieval hook currently uses ONLY `user_prompt` (line 218 of `memory_retrieve.py`). The JSONL transcript format is also not a stable API (acknowledged in `01-research-claude-code-context.md`), so an implementation should include graceful degradation if parsing fails.

---

## Comparison: Current vs Proposed Hybrid

| Aspect | Current (est.) | BM25 Only (est.) | Precision-First Hybrid (est.) |
|---|---|---|---|
| Auto-inject precision | ~40% | ~60% | improved (higher threshold, unmeasured) |
| Recall (auto) | ~50% | ~65% | lower (intentionally conservative) |
| Recall (total with manual) | ~50% | ~65% | higher (manual search fills gap, unmeasured) |
| False positive cost | High | Medium | Lower |
| User trust | Low | Medium | Higher |
| Complexity | Low | Medium | Medium |

> **Note:** Specific precision/recall percentages for the Hybrid approach are unmeasured estimates. The directional improvement (higher threshold = higher precision, lower recall) is certain; the specific magnitudes require measurement via the Phase 0 evaluation framework.

---

## Configuration Design

```json
{
  "retrieval": {
    "enabled": true,
    "auto_inject": {
      "enabled": true,
      "min_score": 4,
      "max_inject": 3
    },
    "manual_search": {
      "enabled": true,
      "min_score": 2,
      "max_results": 10
    }
  }
}
```

Users who prefer recall over precision can lower `min_score` to 2-3. Users who want maximum precision can raise it to 5-6 (note: threshold 6 typically requires 2+ distinct keyword matches). Users who want zero false positives can set `auto_inject.enabled: false` and use only manual search.

---

## Key Insight: The User Is Right

The user's intuition is correct:

1. **Auto-injection demands high precision** — irrelevant context is worse than no context
2. **Keyword matching alone can't achieve high precision** — but it CAN with a high enough threshold (at the cost of recall)
3. **The recall gap can be filled by manual search** — where Claude itself acts as the LLM-as-Judge
4. **This hybrid approach achieves LLM-quality relevance** without external API dependencies

The final report's mistake was treating retrieval as a single system. It should be TWO systems:
- **Passive** (hook): optimized for PRECISION (only inject when very confident)
- **Active** (skill/MCP): optimized for RECALL (let Claude judge relevance)

---

## Revised Phase 0.5 Recommendation

Instead of the "boring fix" (body tokens + synonyms + deeper deep-check + cwd scoring), I recommend:

1. **Raise injection threshold to 4** (immediate, 1 config change -- eliminates single-prefix-match false positives)
2. **Add body tokens to index** (improves both precision and recall)
3. **Create `/memory-search` skill** (fills the recall gap -- note: effectiveness is unvalidated, see claude-mem's experience abandoning skill-based search in v5.4.0->v6+)
4. **Add `auto_inject.min_score` config** (user control)
5. **(Future) Add transcript_path parsing to retrieval hook** (proposed, requires implementation)

This addresses the user's concern directly while staying within stdlib-only constraints.
