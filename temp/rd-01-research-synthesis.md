# Research Synthesis: Retrieval Architecture Redesign

**Date:** 2026-02-20
**Author:** synthesizer (research analyst)
**Inputs:** 10 research files + 2 external model consultations (Gemini 3.1 Pro, Gemini 2.5 Pro)
**Purpose:** Sole input for the architecture phase

---

## 1. claude-mem Retrieval: What Works and Why

### Dual-Path Architecture (Hook + MCP)
claude-mem separates retrieval into two completely independent paths:

- **Passive (SessionStart hook):** Recency-based injection. Pulls last N observations from SQLite ordered by `created_at_epoch`. No vector search, no keywords. Rationale: at session start there is no user query to search against, so "recent is relevant" is a reasonable heuristic.

- **Active (MCP tools):** LLM-initiated search via 4 MCP tools in a 3-layer progressive disclosure pattern:
  1. `search(query)` -- compact index (~50-100 tokens/result)
  2. `timeline(anchor)` -- chronological context around a result
  3. `get_observations(ids)` -- full details (~500-1000 tokens/result)

The LLM decides *when* and *what* to search. The API structure enforces progressive disclosure -- you cannot get full details without first getting IDs from the search layer.

### Progressive Disclosure
The key insight: "Context pollution is quadratic, not linear." Every injected token attends to every other token, so wasted context has compounding cost. claude-mem's 3-layer pattern reduced context waste by 87% compared to the v1-v3 "dump everything" approach.

**Token economics** (confirmed from claude-mem docs):
- Scanning 50 search results: ~3,750 tokens
- Fetching 2-3 relevant results: ~1,500 tokens
- Total: ~5,250 tokens for targeted context
- Alternative (load all 50): ~25,000+ tokens

### Structural Enforcement Over Behavioral Guidance
claude-mem's v5.4 tried skill-based search (67% effectiveness). v6 returned to MCP tools (100% effectiveness). The lesson: MCP tool parameters structurally constrain the LLM's behavior -- it *cannot* skip the discovery step. Skills rely on the LLM following instructions, which is not guaranteed.

### Design Decisions Worth Noting
- ChromaDB vector distance is the SOLE ranking signal. No BM25, no TF-IDF, no custom scoring.
- FTS5 was built, shipped, and then effectively deprecated. It became dead code when MCP tools replaced the skill-based search that consumed FTS5 endpoints.
- 90-day recency cutoff is binary (hard drop, not decay). Applied after vector search, not as a scoring factor.
- Sub-document splitting: each memory is split into multiple Chroma documents by semantic field (narrative, facts, etc.), then deduplicated by `sqlite_id` at query time.

---

## 2. claude-mem Retrieval: What Failed and Lessons

### FTS5 Was Built and Abandoned
FTS5 was introduced in v5.0.0 as part of a "hybrid search" combining keyword + vector. By v6+ (Dec 2025), the FTS5 query path had no consumer. The virtual tables exist but are dead code. Lesson: **building both keyword and vector search is wasted effort when vectors subsume keywords.** For us (no vectors), BM25 IS the primary engine, not a fallback.

### Process Leaks Are Structural, Not Bugs
8 independent leak incidents across 3 months. The architecture treats local processes as cloud microservices without orchestration infrastructure. Gemini 2.5 Pro named this the "Local Distributed System Fallacy." Issue #1185 (chroma-mcp 500-700% CPU) remains open as of Feb 2026. Lesson: **any architecture requiring persistent processes will eventually leak on local machines without supervisors.**

### Skill-to-MCP Migration
The skill-based search (v5.4) achieved only 67% effectiveness -- the LLM did not always invoke the skill when it should have. MCP tools achieved 100% because they are structurally available in the tool list. Lesson for us: **if we build an on-demand search path, MCP tools are more reliable than skills, but skills are feasible within our stdlib constraint.**

### Over-Engineering Timeline
- v1-v2: dumped everything (35k tokens, 1.4% relevance)
- v3: AI compression (10:1 ratio, still loaded everything)
- v4: progressive disclosure (87% reduction)
- v5.0: hybrid search (FTS5 + Chroma)
- v5.4: skill-based search (2,250 token savings but 67% effectiveness)
- v6: simplified MCP (4 tools instead of 9+, eliminated 5,150 LOC)
- v10.x: 10 releases in 3 days for Chroma infrastructure hardening

Lesson: **simpler architectures win in the long run.** 88 npm versions in 6 months indicates constant firefighting.

---

## 3. claude-memory Current State: Honest Assessment

### Score: 4/10 for Retrieval Quality

| Aspect | Rating | Detail |
|--------|--------|--------|
| Precision | 2/10 | ~40% estimated (unmeasured). 3 of 5 injected memories likely irrelevant. |
| Recall | 3/10 | Title+tag-only matching misses body content entirely. |
| Ranking quality | 3/10 | Flat scoring (title=2, tag=3, prefix=1) cannot distinguish "weakly related" from "highly relevant." |
| Token efficiency | 5/10 | Single-shot injection (no progressive disclosure). Fixed max_inject cap. |
| Configurability | 6/10 | max_inject clamped to [0,20], category priorities, stop words. |
| Robustness | 7/10 | Path containment, retired exclusion, sanitization, recency bonus. |

### What Works
- **Security model is strong:** Write guard, title sanitization (write + retrieval side), path traversal prevention, XML escaping. This is better than claude-mem.
- **Category priority ordering:** DECISION > CONSTRAINT > PREFERENCE > RUNBOOK > TECH_DEBT > SESSION_SUMMARY. Sensible default.
- **Recency bonus:** Deep-checking top 20 candidates against JSON files for recency and retired status.
- **Defense-in-depth sanitization:** Title sanitized on write (memory_write.py), re-sanitized on read (memory_retrieve.py). Gap: memory_index.py rebuild trusts write-side sanitization.
- **Graceful degradation:** If index.md missing, attempts rebuild. If no matches, exits silently.

### What Does Not Work
- **Title+tag only matching is fundamentally insufficient.** Body content (the actual memory substance) is not indexed. Two memories about "login" in different contexts score identically.
- **No IDF weighting.** Common words like "fix" and "bug" have the same weight as rare, discriminating terms like "pydantic" or "jwt".
- **Prefix matching is a blunt instrument.** "auth" matching "authentication" is good; "cat" matching "category" is noise (mitigated by 4-char minimum, but still produces false positives).
- **Single-shot injection wastes context.** All matched memories are injected at once, no progressive disclosure, no token budget awareness.
- **No on-demand search path.** If auto-injection misses, the user has no way to search memories (except manually reading files).
- **No transcript context.** Hook receives `transcript_path` but retrieval uses ONLY `user_prompt`. Pronoun references ("fix that") and topic continuity are lost.

### What Is Dangerous
- **Current auto-injection is probably net-negative.** At ~40% precision with max_inject=5, roughly 3 irrelevant memories pollute Claude's context on every prompt. Multiple analyses agree this actively degrades reasoning.
- **No measurement infrastructure.** All precision numbers are estimates. There is no benchmark, no evaluation framework, no way to know if changes help or hurt.
- **Config manipulation surface.** memory-config.json is read without integrity checks. A malicious config can disable retrieval entirely or set max_inject to extreme values.

---

## 4. Design Patterns: Adopt vs Avoid

### Patterns to Adopt (Adapted to Our Constraints)

| Pattern | Source | Adaptation |
|---------|--------|------------|
| **Dual-path retrieval** | claude-mem | Conservative auto-inject (hook) + on-demand search (skill/command). Different thresholds for each. |
| **Progressive disclosure** | claude-mem | For on-demand path: return titles/categories first, let LLM select which to read in full. Not feasible for auto-inject (hook has one shot). |
| **High auto-inject threshold** | Analysis consensus | Set min_score high enough that only "slam dunk" matches are injected. Missing relevant results is acceptable because on-demand search fills the gap. |
| **Body content indexing** | Gemini 2.5 Pro | "Foundational and non-negotiable." Title+tag matching leaves the most valuable signal on the floor. |
| **BM25 via FTS5** | All external opinions | In-memory sqlite3 FTS5 with Porter stemming and column weights (title 5x, tags 3x, body 1x). Rebuild per invocation. |
| **Transcript context (limited)** | claude-mem (modified) | Parse last 2-3 turns from transcript_path for richer query context. NOT the full transcript (topic drift risk). |
| **Recency as filter, not ranking** | claude-mem | Hard cutoff (configurable days) rather than decay curve. Simpler, less prone to parameter tuning. |

### Patterns to Avoid

| Pattern | Source | Why Avoid |
|---------|--------|-----------|
| **Persistent background processes** | claude-mem | "Local Distributed System Fallacy." Leaks, zombies, port conflicts. |
| **Vector embeddings** | claude-mem | Requires ChromaDB/ONNX runtime. Has caused segfaults, 35GB RAM usage, CPU spikes. Incompatible with our constraints. |
| **Building both keyword AND vector** | claude-mem v5.0 | FTS5 became dead code once vectors subsumed it. Pick one engine and optimize it. |
| **Skill-based search (as sole path)** | claude-mem v5.4 | 67% effectiveness -- LLM does not always invoke skills. Use as supplement, not primary. |
| **Loading all memories upfront** | claude-mem v1-v3 | 35k tokens, 1.4% relevance. Wasteful. |
| **Manual synonym maps** | Analysis option | "Brittle, high-maintenance solution" (Gemini 2.5 Pro). LLM-driven query expansion is strictly superior. |
| **Full transcript as query** | Naive approach | Topic drift destroys BM25 accuracy. Dilutes signal with conversational filler. |

---

## 5. Zero-Base Analysis: Ideal Retrieval for Our Constraints

### Given Constraints
- stdlib-only Python (pydantic only for writes)
- No daemons, no network calls, no background processes
- JSON files on disk (~100-500 memories typical, 1000 max)
- WSL2 Linux target
- Hook-based architecture (UserPromptSubmit for retrieval)

### Ideal Architecture from Scratch

#### Engine: In-Memory FTS5 with BM25

```
UserPromptSubmit hook fires
    |
    v
Read hook input JSON (user_prompt, transcript_path, cwd)
    |
    v
Extract query context:
  - Current prompt tokens
  - Last 2-3 turns from transcript_path (for pronoun resolution, topic continuity)
  - Concatenate into search query
    |
    v
Build in-memory SQLite FTS5 table:
  - Load all JSON memory files (or use cached index)
  - Columns: title (5x weight), tags (3x weight), body (1x weight), category
  - Tokenizer: porter (handles pluralization, suffixes)
    |
    v
Query FTS5 with BM25 ranking:
  - MATCH query against FTS5 table
  - ORDER BY bm25(table, 5.0, 3.0, 1.0) (column weights)
  - Filter: record_status = 'active', within recency window
  - Apply category priority as tiebreaker
    |
    v
Apply auto-inject threshold:
  - If top result's BM25 score > threshold: inject top N
  - If no results pass threshold: inject nothing (silent exit)
    |
    v
Output with existing security model:
  - Title sanitization, XML escaping, path containment
  - <memory-context> wrapper with category descriptions
```

#### On-Demand Search Path (Skill)

```
/memory:search query triggered by user/LLM
    |
    v
Same FTS5 engine, lower threshold
    |
    v
Return compact results (title, category, score, path)
    |
    v
LLM reads results, decides which to read in full
    |
    v
LLM reads selected JSON files directly (Read tool)
```

This is a 2-layer progressive disclosure: compact index -> full file. The LLM acts as the re-ranker/judge.

#### FTS5 Availability Fallback

```python
def is_fts5_available():
    try:
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE VIRTUAL TABLE test USING fts5(content);")
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False
```

If FTS5 unavailable: fall back to improved keyword matching (current system with body content + IDF-like weighting). This is a gracefully degraded experience, not a full BM25 implementation.

#### Performance Budget

For 500 JSON files at ~2KB average:
- File I/O: ~5-10ms (largely cached by OS)
- FTS5 index build: ~2-5ms (in-memory, C-level optimized)
- Query: <1ms
- **Total: ~10-20ms** (well within hook timeout)

For the first invocation per session, consider caching the index as a temp file to avoid re-reading all JSON files. On subsequent prompts in the same session, only re-read if index.md mtime has changed.

#### Approaches Neither Project Has Tried

1. **Concept co-occurrence matrix.** Build a sparse matrix of which terms co-occur across memory files. If "auth" and "login" frequently appear in the same memories, boost "login" matches when the query contains "auth." Pure Python, no ML, captures domain-specific term relationships. Downside: cold-start with few memories, maintenance overhead.

2. **Category-aware query routing.** Instead of searching all memories, first classify the prompt into likely categories (DECISION? RUNBOOK? CONSTRAINT?) based on linguistic markers, then search only within those categories. Reduces noise from irrelevant categories.

3. **Inverted file path index.** Index `related_files` paths from memories. When Claude is working in a file, auto-retrieve memories that reference that file. This is a high-precision signal that keyword matching cannot provide. The `cwd` and recent tool_input paths are available from the hook context.

4. **Session continuity linking.** When a session_summary references decisions or constraints, create explicit links. On retrieval, if a session_summary matches, also surface linked decisions/constraints. Graph-like traversal within JSON files.

### Precision Estimates (Cross-Validated)

| Approach | Precision (est.) | Source Agreement |
|----------|-----------------|------------------|
| Current keyword (title+tag) | ~40% | All sources agree |
| + Body content indexing | ~50% | Gemini 2.5 Pro (high confidence) |
| + BM25/FTS5 (replacing keyword) | ~60-65% | Gemini 3.1 Pro: 65-75%, Gemini 2.5 Pro: 65-75%, prior analysis: 55-60% |
| + Transcript context (2-3 turns) | ~65-70% | Gemini 3.1 Pro (moderate confidence) |
| + High threshold (precision-first) | ~75-80% auto-inject precision | Consensus (with lower recall, compensated by on-demand) |
| Theoretical ceiling without vectors | ~70-75% overall | All sources agree on ceiling |

**Note:** All numbers remain estimates. Phase 0 (evaluation benchmark) is prerequisite to validating any of these.

---

## 6. Open Questions for Architecture Phase

### Must-Decide Questions

1. **FTS5 as hard dependency or optional enhancement?** FTS5 is available on most Linux/WSL2 Python builds, but not guaranteed. Should the architecture require FTS5 (with a hard error if missing) or gracefully degrade to improved keyword matching?

2. **Index caching strategy.** Rebuild FTS5 in-memory on every UserPromptSubmit, or cache to a temp SQLite file and invalidate on index.md mtime change? Tradeoff: freshness vs. latency.

3. **On-demand search: skill vs MCP tool?** Skills are simpler (no server process) but have 67% effectiveness issue (claude-mem lesson). MCP tools are more reliable but require a running server (violates our constraints). A skill with very clear trigger instructions is the likely answer, but the architect should validate this.

4. **Transcript parsing stability.** The JSONL transcript format is not a stable API. Should we parse it (high reward, breakage risk) or skip it (safer, lower retrieval quality)?

5. **Body content format for FTS5.** Memory JSON has structured content (different schemas per category). Should we concatenate all text fields into a single searchable body, or use separate FTS5 columns per content field?

6. **Auto-inject threshold calibration.** What BM25 score threshold for auto-injection? This depends on the score distribution, which depends on the corpus. Requires empirical tuning via the Phase 0 benchmark.

7. **File path matching.** Should `related_files` in memories be matched against the current file context (cwd, recent tool inputs)? This is a high-precision signal but adds complexity.

### Nice-to-Know Questions

8. **Query expansion by LLM.** For the on-demand path, should the skill instruct Claude to expand its query with synonyms before searching? Gemini 3.1 Pro strongly recommends this. Adds no infra cost but relies on LLM following skill instructions.

9. **Category-aware routing.** Is it worth classifying the prompt into likely categories before searching? Reduces search space and noise, but adds a classification step.

10. **Evaluation benchmark design.** What should the 20+ test queries look like? Need representative distribution across categories, ambiguity levels, and query types (specific vs general vs follow-up).

---

## External Opinion Summary

### Gemini 3.1 Pro (via pal clink)

**Core recommendation:** FTS5 with Porter stemming, column weights (title 5x, tags 3x, body 1x), dual-path retrieval, transcript context limited to last 2-3 turns.

**Key opinions:**
- "FTS5 is definitively the best stdlib-only approach"
- Precision ceiling: ~65-75%
- "Do not reinvent the wheel with TF-IDF, n-grams, or Jaccard -- FTS5 already does this better"
- LLM-driven query expansion for on-demand search is the best way to bridge the semantic gap
- Full transcript as query will cause "topic drift" -- extract only last 2-3 turns
- Auto-inject should only fire for "slam dunk" matches, max 1-2 injections

### Gemini 2.5 Pro (via pal chat)

**Core recommendation:** Body content indexing is the single highest-leverage improvement, even before BM25. BM25/FTS5 is second. Transcript context is third.

**Key opinions:**
- Precision ceiling: ~65-75% (agrees with 3.1 Pro)
- "Body content indexing is foundational and non-negotiable"
- Synonym maps are "brittle, high-maintenance" -- advises against
- FTS5 availability risk on WSL2/Linux is "very low"
- Pure-Python BM25 fallback would be "significantly slower" but feasible
- Suggests runtime FTS5 availability check with graceful degradation
- "BM25 via FTS5 is the right destination. You are not missing a secret, simpler, more powerful alternative."

### Codex 5.3
Unavailable (quota exhausted). Single external model validation only.

### My Assessment vs External Opinions

| Topic | My Initial View | External Consensus | Final Position |
|-------|----------------|-------------------|----------------|
| BM25/FTS5 as engine | Yes, best option | Strong agreement | **Confirmed** |
| Body content indexing | Important | "Non-negotiable" (Gemini 2.5) | **Elevated to #1 priority** |
| Synonym maps | Worth considering | "Brittle, avoid" (both) | **Dropped** |
| Transcript context | Important | "Last 2-3 turns only" (both) | **Confirmed with scope limit** |
| Precision ceiling | ~60% | ~65-75% (both) | **Revised upward to ~65-70%** |
| On-demand search | Necessary | Strong agreement | **Confirmed** |
| FTS5 availability risk | Moderate concern | "Very low" (Gemini 2.5) | **Downgraded, but keep fallback** |

### Key Disagreement
The prior research (06-analysis-relevance-precision.md) estimated BM25 precision at ~55-60%. Both external models estimate ~65-75%. The difference likely stems from the external models assuming body content indexing (which the prior analysis did not explicitly include). With body content + BM25, ~65-70% is a reasonable estimate.

---

## Summary for the Architect

**The retrieval redesign has one clear path forward:**

1. **Engine:** Replace keyword matching with FTS5 BM25. In-memory, rebuilt per invocation. Column weights: title 5x, tags 3x, body 1x. Porter stemmer. Fallback to improved keyword matching if FTS5 unavailable.

2. **Body content:** Index the actual memory content, not just title and tags. This is the single highest-leverage change according to all sources.

3. **Dual path:** Conservative auto-inject (high threshold, max 2-3) + on-demand search (lower threshold, up to 10 results). The on-demand path uses progressive disclosure: return compact results, LLM selects which to read in full.

4. **Transcript context:** Parse last 2-3 turns from transcript_path for richer query context. Graceful degradation if parsing fails.

5. **No synonym maps.** LLM-driven query expansion for the on-demand path is strictly superior.

6. **Phase 0 first.** Build a 20+ query evaluation benchmark before any implementation. You cannot improve what you cannot measure.

**Expected outcome:** Precision improvement from ~40% to ~65-70%. Auto-inject precision (with high threshold) estimated ~75-80%. Combined with on-demand search, effective recall should approach ~80%+.

**Hard ceiling:** ~70-75% precision without vectors or LLM-as-judge. This is an architectural constraint of the stdlib-only, zero-infrastructure design. The gap to claude-mem's ~80-85% is real but acceptable given the reliability and portability tradeoffs.
