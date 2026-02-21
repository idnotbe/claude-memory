# claude-mem Retrieval Mechanism -- Detailed Analysis

**Date:** 2026-02-20
**Repository:** https://github.com/thedotmack/claude-mem (v6.5.0)
**Focus:** Retrieval architecture only (not capture, storage, or UI)

---

## 1. Exact Retrieval Flow

claude-mem uses a **dual-path retrieval system**: passive context injection via hooks AND on-demand search via MCP tools. There is no single linear "keyword -> vector -> rerank" pipeline. Instead, the system has two distinct retrieval surfaces:

### Path A: Passive Context Injection (SessionStart Hook)

Triggered automatically when a session starts or is cleared/compacted:

```
SessionStart hook fires
    |
    v
context-generator script runs via Worker HTTP API
    |
    v
Queries SQLite for recent observations + session summaries
    |
    v
Calculates "token economics" (discovery vs read costs)
    |
    v
Builds progressive context: header + timeline + most-recent summary + prior messages + footer
    |
    v
Injected into session via hook command stdout
```

This path does NOT use vector search. It is purely recency-based, pulling the most recent relevant data from SQLite.

### Path B: On-Demand Search (MCP Tools)

The LLM explicitly calls MCP tools when it needs to search memory. The flow through the SearchOrchestrator follows this decision tree:

```
search(query, filters) called via MCP
    |
    v
SearchOrchestrator.normalizeParams()
    |
    v
Has query text?
  NO  --> SQLiteSearchStrategy (filter-only: date, project, type)
          Returns results ordered by created_at_epoch (no relevance scoring)
  YES --> Is ChromaDB available?
            YES --> ChromaSearchStrategy
                    1. Query Chroma for semantic matches (vector search)
                    2. Filter by 90-day recency window
                    3. Categorize results by doc_type (observation/session/prompt)
                    4. Hydrate full records from SQLite
                    Did Chroma succeed?
                      YES --> Return results (even if 0 matches)
                      NO  --> Fallback to SQLite (drops query text, filter-only)
            NO  --> Return empty results
```

For specialized queries (`findByConcept`, `findByType`, `findByFile`), a **HybridSearchStrategy** is used when Chroma is available:

```
1. SQLite metadata filter (get all IDs matching concept/type/file criteria)
2. Chroma semantic ranking (vector search using the concept/type/file as query)
3. Intersection: keep only IDs from step 1, ordered by Chroma's rank
4. Hydrate from SQLite in semantic rank order
```

**Key point:** There is no explicit "reranking" step. ChromaDB's vector distance IS the ranking. The hybrid strategy uses intersection to combine metadata precision with semantic ordering, but does not apply a separate reranker model.

---

## 2. Hooks vs. MCP Tools for Retrieval

**Both.** claude-mem uses hooks AND MCP tools for retrieval, serving different purposes:

### Hooks (Passive/Automatic)

| Hook | Retrieval Role |
|------|---------------|
| `SessionStart` | Injects recent context via `context-generator` script. SQLite-based, no vector search. Runs on every session start/clear/compact. |
| `UserPromptSubmit` | Runs `session-init` on every user prompt. Ensures Worker service is running. Does NOT inject search results (unlike claude-memory's keyword retrieval hook). |

### MCP Tools (Active/On-Demand)

The MCP server exposes 5 tools. The LLM decides when and how to call them:

| Tool | Purpose |
|------|---------|
| `__IMPORTANT` | Returns the 3-layer workflow instructions (meta-tool, no actual search) |
| `search(query, ...)` | Compact index with IDs, titles, dates (~50-100 tokens/result) |
| `timeline(anchor, ...)` | Chronological context around a specific observation ID |
| `get_observations(ids)` | Full details for selected IDs only (~500-1000 tokens/result) |
| `save_memory(text, ...)` | Manual memory creation (not retrieval) |

**Critical difference from claude-memory:** claude-mem does NOT use a `UserPromptSubmit` hook for keyword-based automatic retrieval. Instead, it relies on the LLM to proactively call the `search` MCP tool when it needs past context. The SessionStart hook provides a baseline context dump, but ongoing retrieval is entirely MCP-tool-driven.

---

## 3. Progressive Disclosure Mechanism

The 3-layer progressive disclosure is enforced through MCP tool design, not through code logic:

### Layer 1: Discovery (search)
- Returns a compact table: ID, title, subtitle, date, type
- ~50-100 tokens per result
- The LLM reads this index and decides what looks relevant

### Layer 2: Context (timeline)
- Returns chronological context around a specific observation
- Anchored by observation ID or auto-found via query
- Shows what was happening before/after a specific memory
- Medium token cost

### Layer 3: Full Detail (get_observations)
- Batch-fetches complete observation records for selected IDs
- ~500-1000 tokens per result
- Only called for the few IDs the LLM selected from layers 1-2

### Enforcement
The `__IMPORTANT` tool encodes the workflow as its response text. When the LLM calls any tool or lists available tools, it sees this instruction. This is a behavioral enforcement mechanism -- there is no code that prevents the LLM from calling `get_observations` directly, but the `__IMPORTANT` tool's description strongly discourages it.

### Token Economics
claude-mem tracks "discovery_tokens" per observation (the cost of showing it in the search index). The context generator calculates and displays token economics in the SessionStart injection, making the LLM aware of retrieval costs.

---

## 4. ChromaDB Vector Search Implementation

### Connection Architecture
- ChromaDB runs as a **separate Python subprocess** via `uvx chroma-mcp`
- Communicates over **MCP stdio protocol** (JSON-RPC), not HTTP
- Managed by `ChromaMcpManager` which handles connection lifecycle, reconnect backoff, and orphan detection
- Data persists at `~/.claude-mem/chroma/`

### Embedding Model
- Managed entirely by `chroma-mcp` -- claude-mem does NOT specify or control the embedding model
- chroma-mcp uses its default embedding function (likely `all-MiniLM-L6-v2` or similar sentence-transformer)
- No OpenAI API key required -- local embeddings only

### Document Granularity (Sub-Document Splitting)
Each observation/summary is split into multiple Chroma documents by semantic field:

- **Observations:** separate documents for `narrative`, `text`, and each individual `fact`
- **Session summaries:** separate documents for `request`, `investigated`, `learned`, `completed`, `next_steps`, `notes`
- **User prompts:** single document per prompt

Each sub-document carries metadata: `sqlite_id`, `doc_type`, `project`, `created_at_epoch`, `field_type`.

### Query Flow (ChromaSearchStrategy.search)
```typescript
// 1. Build where filter (doc_type + project scoping)
const whereFilter = this.buildWhereFilter(searchType, project);

// 2. Vector search -- query Chroma with natural language
const chromaResults = await this.chromaSync.queryChroma(
    query,
    SEARCH_CONSTANTS.CHROMA_BATCH_SIZE,  // ~100
    whereFilter
);

// 3. Filter by recency (90-day cutoff)
const recentItems = this.filterByRecency(chromaResults);

// 4. Categorize by doc_type
const categorized = this.categorizeByDocType(recentItems, ...);

// 5. Hydrate from SQLite
const observations = this.sessionStore.getObservationsByIds(categorized.obsIds, options);
```

### Deduplication
Since each observation produces multiple Chroma documents, results are deduplicated by `sqlite_id`. The `ChromaSync.queryChroma()` method returns deduplicated IDs, keeping the best-ranked distance per original record.

### Project Scoping
Project filtering is applied at the Chroma `where` clause level (not post-hoc) to prevent larger projects from dominating the top-N results before SQLite filtering takes effect.

---

## 5. Scoring and Ranking

### Primary: ChromaDB Vector Distance
- **Distance metric:** Managed by chroma-mcp (likely cosine distance, the ChromaDB default)
- **No custom scoring function** -- relies entirely on ChromaDB's built-in distance calculation
- Results are ordered by vector distance (closest = most relevant)

### Recency Filter (Not a Score)
- Hard 90-day cutoff: `Date.now() - SEARCH_CONSTANTS.RECENCY_WINDOW_MS`
- Applied AFTER vector search, not as a scoring component
- Binary: results older than 90 days are dropped entirely, not downweighted

### Hybrid Intersection Ranking
For `findByConcept`, `findByType`, `findByFile`:
```typescript
private intersectWithRanking(metadataIds: number[], chromaIds: number[]): number[] {
    const metadataSet = new Set(metadataIds);
    const rankedIds: number[] = [];
    for (const chromaId of chromaIds) {
        if (metadataSet.has(chromaId) && !rankedIds.includes(chromaId)) {
            rankedIds.push(chromaId);
        }
    }
    return rankedIds;
}
```
This preserves Chroma's semantic ordering while restricting to the SQLite-filtered candidate set. It is an intersection, not a fusion -- there is no combined score.

### SQLite Fallback (No Relevance Scoring)
- When Chroma is unavailable or query text is absent
- Results ordered by `created_at_epoch` (newest first)
- No TF-IDF, BM25, or any text relevance scoring
- FTS5 virtual tables exist but are **deprecated and unused** -- scheduled for removal in v7.0.0

### What claude-mem Does NOT Have
- No BM25/TF-IDF scoring
- No recency decay curve (hard cutoff only, no exponential decay)
- No field-level scoring weights (title match vs body match)
- No cross-encoder or separate reranking model
- No score fusion (RRF, linear combination, etc.)
- No keyword search at all in the active retrieval path (FTS5 is dead code)

---

## Summary Comparison: claude-mem vs. claude-memory

| Aspect | claude-mem | claude-memory |
|--------|-----------|---------------|
| **Retrieval trigger** | MCP tools (LLM-initiated) + SessionStart hook | UserPromptSubmit hook (automatic) |
| **Search method** | ChromaDB vector embeddings | Keyword matching (substring) |
| **Scoring** | Vector distance (cosine) | Keyword frequency + recency boost |
| **Recency handling** | Hard 90-day cutoff | Configurable injection limit |
| **Progressive disclosure** | 3-layer MCP tool pattern | Single-shot injection |
| **Dependencies** | Bun, ChromaDB, chroma-mcp, uv/uvx | stdlib Python only |
| **Fallback** | Chroma -> SQLite (date-only) -> empty | N/A (single path) |
| **Token awareness** | Tracks discovery_tokens per entry | None |

---

## Sources

- Research file: `/home/idnotbe/projects/claude-memory/temp/research-claude-mem.md`
- Source: [SearchOrchestrator.ts](https://github.com/thedotmack/claude-mem/blob/main/src/services/worker/search/SearchOrchestrator.ts)
- Source: [ChromaSearchStrategy.ts](https://github.com/thedotmack/claude-mem/blob/main/src/services/worker/search/strategies/ChromaSearchStrategy.ts)
- Source: [HybridSearchStrategy.ts](https://github.com/thedotmack/claude-mem/blob/main/src/services/worker/search/strategies/HybridSearchStrategy.ts)
- Source: [mcp-server.ts](https://github.com/thedotmack/claude-mem/blob/main/src/servers/mcp-server.ts)
- Source: [hooks.json](https://github.com/thedotmack/claude-mem/blob/main/plugin/hooks/hooks.json)
- DeepWiki: [thedotmack/claude-mem](https://deepwiki.com/thedotmack/claude-mem)
