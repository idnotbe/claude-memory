# Research: claude-mem (thedotmack/claude-mem) -- Memory Retrieval Architecture

**Date:** 2026-02-20 (updated)
**Repository:** https://github.com/thedotmack/claude-mem
**Version analyzed:** v6.5.0
**License:** AGPL-3.0 (ragtime/ subdirectory under PolyForm Noncommercial 1.0.0)

---

## Executive Summary

claude-mem is a sophisticated memory plugin for Claude Code that combines **ChromaDB vector search** (semantic embeddings) with **SQLite structured filtering** in a hybrid architecture. It auto-captures tool observations, compresses them semantically, and reinjects relevant information into future sessions. The retrieval system follows a 3-layer progressive disclosure pattern to minimize token waste (~10x savings claimed). The system runs a persistent HTTP worker service (Bun on port 37777) with an MCP server wrapper, and communicates with ChromaDB via a separate `chroma-mcp` subprocess managed through MCP stdio protocol. FTS5 (SQLite full-text search) was the original search mechanism but has been deprecated in favor of Chroma vector search, with FTS5 tables maintained only for backward compatibility.

---

## Storage Mechanism

### Primary Store: SQLite
- **Runtime:** Bun's built-in `bun:sqlite` (not the `better-sqlite3` npm package)
- **Location:** `~/.claude-mem/` data directory
- **WAL mode** enabled for concurrent read/write performance
- **Tables:**
  - `observations` -- tool execution results with fields: `id`, `title`, `subtitle`, `narrative`, `text`, `facts` (JSON array), `concepts` (JSON array), `files_read` (JSON array), `files_modified` (JSON array), `type`, `project`, `created_at`, `created_at_epoch`, `discovery_tokens`
  - `session_summaries` -- compressed session data with: `id`, `memory_session_id`, `request`, `investigated`, `learned`, `completed`, `next_steps`, `notes`, `files_read`, `files_edited`, `project`, `created_at_epoch`, `discovery_tokens`
  - `user_prompts` -- user input history with: `id`, `content_session_id`, `prompt_number`, `prompt_text`, `created_at`, `created_at_epoch`
  - `sdk_sessions` -- session metadata linking `content_session_id` to `project`
  - FTS5 virtual tables: `observations_fts`, `session_summaries_fts` (deprecated, maintained for backward compat, TODO remove in v7.0.0)

### Vector Store: ChromaDB (via chroma-mcp)
- **Location:** `~/.claude-mem/chroma/` (local persistent mode)
- **Connection:** MCP stdio protocol to `uvx chroma-mcp` subprocess (not an HTTP server, not a direct npm dependency)
- **Embedding model:** Managed entirely by chroma-mcp -- claude-mem does NOT specify or control the embedding model. chroma-mcp uses its default embedding function (likely `all-MiniLM-L6-v2` or similar, handled internally)
- **Document granularity:** Each observation is split into multiple Chroma documents by semantic field:
  - Observations: separate docs for `narrative`, `text`, and individual `facts`
  - Summaries: separate docs for `request`, `investigated`, `learned`, `completed`, `next_steps`, `notes`
  - Prompts: single document per prompt
- **Metadata per document:** `sqlite_id`, `doc_type` (observation/session_summary/user_prompt), `project`, `created_at_epoch`, `field_type`
- **Collection naming:** Sanitized per Chroma rules: `[a-zA-Z0-9._-]`, 3-512 chars, prefixed `cm__`
- **Deduplication:** Results are deduplicated by `sqlite_id`, keeping the best-ranked distance per document

### How Data Flows In
1. **PostToolUse hook** captures tool execution results as observations
2. **Stop hook** triggers session summarization
3. Both are processed by the Worker HTTP API, stored in SQLite, and synced to ChromaDB via `ChromaSync`

---

## Retrieval Mechanism (Primary Focus)

### Architecture Overview

The retrieval system has 4 layers:

```
MCP Server (thin wrapper, stdio JSON-RPC)
    |
    v
Worker HTTP API (Bun, port 37777)
    |
    v
SearchOrchestrator (strategy pattern)
    |
    +---> ChromaSearchStrategy (semantic, primary)
    +---> SQLiteSearchStrategy (filter-only, fallback)
    +---> HybridSearchStrategy (metadata filter + semantic ranking)
```

### 3-Layer Progressive Disclosure Pattern (MCP Tools)

The MCP server exposes 5 tools, with `__IMPORTANT` enforcing a workflow discipline:

1. **`search(query, limit, project, type, obs_type, dateStart, dateEnd, offset, orderBy)`** -- Returns a compact index table with IDs, titles, dates (~50-100 tokens per result). This is the discovery layer.

2. **`timeline(anchor=ID, query, depth_before, depth_after, project)`** -- Returns chronological context around a specific observation. Anchored by ID or auto-found via query.

3. **`get_observations(ids=[])`** -- Batch fetches full details for selected IDs only (~500-1000 tokens per result). POST to `/api/observations/batch`.

4. **`save_memory(text, title, project)`** -- Manual memory save for semantic search.

5. **`__IMPORTANT`** -- A "tool" that returns the 3-layer workflow instructions, ensuring the LLM always follows the protocol.

**Token savings mechanism:** By showing only compact index first (50-100 tokens), then context (medium), then full details (500-1000 tokens) only for filtered IDs, the system achieves ~10x token savings vs. fetching all details upfront.

### Context Injection (SessionStart Hook)

On session start, the `context-generator` script:
1. Loads config via `ContextConfigLoader`
2. Queries the database for recent observations and session summaries
3. Calculates "token economics" (discovery vs. read costs)
4. Builds a progressive context output with: header, timeline, optional most-recent summary, prior messages, footer with economics
5. This context is injected into the session via the `SessionStart` hook command output

### Search Strategy Selection (SearchOrchestrator)

The orchestrator implements a decision tree:

```
Has query text?
  NO  --> SQLiteSearchStrategy (filter-only: date, project, type, concepts, files)
  YES --> Is Chroma available?
            YES --> ChromaSearchStrategy (vector semantic search)
                    Did Chroma succeed?
                      YES --> Return results (even if 0 matches)
                      NO  --> Fallback to SQLite (without query text)
            NO  --> Return empty results
```

For specialized operations (findByConcept, findByType, findByFile), the `HybridSearchStrategy` is used when Chroma is available:

```
1. SQLite metadata filter (get all IDs matching criteria)
2. Chroma semantic ranking (rank by relevance)
3. Intersection (keep only IDs in both sets, ordered by Chroma rank)
4. Hydrate from SQLite in semantic rank order
```

---

## Scoring/Ranking Details

### ChromaDB Vector Scoring
- **Distance metric:** Managed by chroma-mcp (likely cosine distance, the ChromaDB default)
- **Batch size:** `SEARCH_CONSTANTS.CHROMA_BATCH_SIZE` (appears to be ~100 based on context)
- **Recency window:** 90-day cutoff (`SEARCH_CONSTANTS.RECENCY_WINDOW_MS`) -- results older than 90 days are filtered out AFTER vector search
- **Project scoping:** Applied at the Chroma `where` clause level to prevent larger projects from dominating top-N results before SQLite filtering
- **Deduplication:** Per `sqlite_id`, keeping the best distance score when multiple sub-documents (narrative, facts, etc.) match

### Hybrid Ranking (intersectWithRanking)
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
This preserves Chroma's semantic ranking order while restricting to SQLite's metadata-filtered candidate set.

### SQLite Fallback Scoring
- No relevance scoring -- results ordered by `created_at_epoch` (newest first by default)
- Supports `date_desc`, `date_asc` ordering
- FTS5 `rank` ordering was available but is now deprecated/unused

### FTS5 (Deprecated)
- Virtual tables still exist: `observations_fts`, `session_summaries_fts`
- Indexed fields for observations: `title`, `subtitle`, `narrative`, `text`, `facts`, `concepts`
- Indexed fields for summaries: `request`, `investigated`, `learned`, `completed`, `next_steps`, `notes`
- Insert/update/delete triggers still fire to keep FTS5 tables synchronized
- **Not used for any search queries** -- all text search goes through Chroma
- Scheduled for removal in v7.0.0

---

## Dependencies

### Runtime Dependencies
- **Bun** -- JavaScript runtime (auto-installed), used for SQLite and HTTP server
- **Node.js >= 18** -- For plugin scripts and MCP server
- **uv/uvx** -- Python package manager (auto-installed), runs `chroma-mcp` subprocess
- **chroma-mcp** -- Python MCP server providing ChromaDB access with built-in embeddings
- **SQLite 3** -- Bundled with Bun
- **@modelcontextprotocol/sdk** -- MCP protocol client/server
- **@anthropic-ai/claude-agent-sdk** -- Claude agent integration
- **express** -- HTTP framework (for Worker API)
- **react/react-dom** -- Web viewer UI
- **zod-to-json-schema** -- Schema validation
- **handlebars** -- Templating

### NOT Required (by design)
- No `chromadb` npm package (delegated to chroma-mcp)
- No ONNX/WASM embedding dependencies (handled by chroma-mcp's Python environment)
- No OpenAI API key for embeddings (chroma-mcp uses local embeddings by default)

### Infrastructure
- Worker HTTP API on port 37777 (configurable)
- MCP server on stdio (JSON-RPC)
- chroma-mcp subprocess on stdio (spawned via `uvx`)
- Persistent SQLite database in `~/.claude-mem/`
- Persistent Chroma data in `~/.claude-mem/chroma/`

---

## Architecture Decisions and Tradeoffs

### 1. Chroma via MCP subprocess (not in-process)
**Decision:** Run chroma-mcp as a separate Python subprocess via uvx, communicating over MCP stdio protocol.
**Tradeoff:** Adds process management complexity (connection timeouts, reconnect backoff, orphan detection) but eliminates ONNX/WASM dependency hell in the Node.js environment. The embedding model lives entirely in the Python process.

### 2. FTS5 deprecated in favor of vector search
**Decision:** FTS5 tables are maintained but no longer used for queries. All text search goes through ChromaDB.
**Tradeoff:** Loses the zero-dependency simplicity of FTS5 but gains semantic understanding (synonyms, paraphrases, conceptual similarity). The FTS5 infrastructure is dead weight until v7.0.0 removes it.

### 3. Progressive disclosure (3-layer search)
**Decision:** Force a search-then-filter-then-fetch workflow via MCP tool design.
**Tradeoff:** More tool calls per search, but ~10x token savings. The `__IMPORTANT` tool is a clever hack to ensure the LLM follows the protocol.

### 4. 90-day recency window
**Decision:** Hard-filter vector search results to the last 90 days.
**Tradeoff:** Prevents retrieval of older memories even if semantically relevant. Good for active projects, potentially lossy for long-lived codebases.

### 5. Sub-document granularity in Chroma
**Decision:** Split each observation into multiple Chroma documents (narrative, text, individual facts).
**Tradeoff:** Better embedding quality (shorter, focused text per embedding) but requires deduplication by `sqlite_id` on retrieval.

### 6. Bun runtime
**Decision:** Use Bun for the worker service (SQLite, HTTP, process management).
**Tradeoff:** Fast startup and built-in SQLite, but adds a runtime dependency beyond Node.js.

### 7. Worker HTTP API as intermediary
**Decision:** MCP server is a thin wrapper; all logic lives in the Worker HTTP API.
**Tradeoff:** Enables the Web Viewer UI and multiple access points (MCP, HTTP, CLI) but adds an HTTP hop.

---

## Key Takeaways for Improving a Keyword-Only Retrieval System

### 1. Progressive Disclosure is the Highest-Impact Pattern
claude-mem's 3-layer approach (index -> context -> detail) is architecture-independent. A keyword-only system can implement this same pattern:
- Return compact summaries first (title, date, category, score)
- Let the LLM decide which entries to expand
- Fetch full content only for selected entries
- This reduces token waste dramatically regardless of search quality

### 2. Sub-Document Indexing Improves Match Quality
claude-mem splits observations into sub-documents (narrative, facts, etc.) before indexing. For a keyword system, this translates to:
- Index title, body, tags, and metadata separately
- Score matches in title higher than matches in body
- Consider a "best field" scoring approach where the highest-scoring field determines the document score

### 3. Recency Weighting is Critical
The 90-day hard cutoff is blunt but effective. For keyword search, consider:
- Exponential decay factor on recency (newer = higher boost)
- Configurable decay rate per category (constraints decay slower than session summaries)
- Combination: `final_score = keyword_score * recency_boost`

### 4. Metadata Filtering Before Text Search
The hybrid strategy's "filter then rank" pattern works for keyword search too:
- First filter by category, date range, status, tags
- Then apply keyword scoring within the filtered set
- This dramatically reduces false positives and improves relevance

### 5. Graceful Degradation Matters
claude-mem falls back from Chroma -> SQLite -> empty results. A keyword system should:
- Have a primary search path (keyword matching)
- Fall back to broader matches (stemming, prefix matching) if no results
- Always return something useful (e.g., most recent entries in the category)

### 6. Consider Lightweight Embeddings as an Enhancement (Not Replacement)
claude-mem's journey: FTS5 -> ChromaDB shows the value of semantic search. For a keyword-only system that wants to stay dependency-light:
- BM25 scoring (TF-IDF variant) can be implemented in pure Python with no external deps
- Sentence-transformers embeddings could be an optional enhancement behind a feature flag
- The hybrid approach (metadata filter + semantic rerank) is the sweet spot

### 7. Token Economics Tracking
claude-mem tracks "discovery tokens" vs "read tokens" per observation. For a keyword system:
- Estimate the token cost of each memory entry
- Budget injection tokens per session (e.g., max 2000 tokens)
- Prioritize high-score entries that fit within the budget
- Show the LLM what was injected and what was omitted

### 8. Project Scoping at Query Time
claude-mem scopes vector queries by project to prevent cross-project noise. For keyword search:
- Always scope to the current project/directory
- Consider a "global" vs "project-local" memory distinction
- Inject project-scoped results first, then global results if budget remains

### 9. Concept/Tag-Based Retrieval Complements Keyword Search
claude-mem's `findByConcept` uses JSON array search in SQLite. For keyword search:
- Structured tags provide high-precision retrieval independent of text matching
- Tags can be auto-generated during write (category, key concepts, file paths)
- Tag-based lookup as a parallel retrieval path alongside keyword scoring

### 10. The `__IMPORTANT` Tool Pattern
Encoding workflow instructions as a tool is a creative way to ensure the LLM follows a protocol. For any memory system:
- Document the retrieval workflow explicitly in system prompts
- Consider exposing "meta-tools" that return usage instructions
- The 3-layer pattern is universally applicable regardless of backend

---

## Source Files Examined

| File | Role |
|------|------|
| `src/servers/mcp-server.ts` | MCP tool definitions, thin HTTP wrapper |
| `src/services/worker/search/SearchOrchestrator.ts` | Strategy selection, fallback logic |
| `src/services/worker/search/strategies/ChromaSearchStrategy.ts` | ChromaDB semantic search, recency filter, hydration |
| `src/services/worker/search/strategies/HybridSearchStrategy.ts` | Metadata filter + semantic ranking intersection |
| `src/services/worker/search/strategies/SQLiteSearchStrategy.ts` | Filter-only fallback |
| `src/services/worker/search/ResultFormatter.ts` | Result formatting, token estimation |
| `src/services/sqlite/SessionSearch.ts` | SQLite queries, FTS5 (deprecated), filter building |
| `src/services/sync/ChromaMcpManager.ts` | chroma-mcp subprocess management via MCP stdio |
| `src/services/sync/ChromaSync.ts` | Chroma document sync, query, deduplication |
| `src/services/context/ContextBuilder.ts` | Session context generation, progressive disclosure |
| `src/services/context/TokenCalculator.ts` | Token economics calculation |
| `plugin/hooks/hooks.json` | Hook definitions (SessionStart, UserPromptSubmit, PostToolUse, Stop) |
