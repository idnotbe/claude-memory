# Research Process Notes: claude-mem Architecture Rationale

**Date:** 2026-02-20
**Task:** Research WHY claude-mem chose its specific architecture

## Sources Consulted

### Primary Sources (Official Documentation)
1. **Architecture Evolution page** - https://docs.claude-mem.ai/architecture-evolution
   - Most valuable single source. Documents v1 through v5+ evolution with explicit rationale.
2. **Progressive Disclosure page** - https://docs.claude-mem.ai/progressive-disclosure
   - Philosophy document explaining WHY the 3-layer pattern was chosen.
3. **Context Engineering page** - https://docs.claude-mem.ai/context-engineering
   - Design principles document. Explains "just-in-time context" rationale.
4. **Search Architecture page** - https://docs.claude-mem.ai/architecture/search-architecture
   - Documents MCP tool design and 3-layer workflow.
5. **Hooks Architecture page** - https://docs.claude-mem.ai/hooks-architecture
   - Explains WHY recency-based SessionStart injection.

### GitHub Sources
6. **CHANGELOG.md** (1,453 lines) - Version history from v10.3.1 back to early versions
7. **PR #480** - "Documentation: Update to MCP Architecture and 3-Layer Workflow" (merged 2025-12-29)
8. **PR #78** - "v5.4.0: Skill-Based Search Migration & Progressive Disclosure Pattern" (merged 2025-11-09)
9. **PR #111** - "feat: Add ROI tracking with discovery_tokens" (merged 2025-11-16)
10. **Issue #103** - Token cost metrics display request
11. **Issue #104** - Discovery costs display request
12. **Issue #707** - SQLite-only backend mode (reveals Chroma resource costs)
13. **docs/SESSION_ID_ARCHITECTURE.md** - Dual session ID design rationale
14. **docs/reports/** - Bug investigation reports revealing architectural pain points

### Third-Party Sources
15. **DeepWiki** - https://deepwiki.com/thedotmack/claude-mem - Automated analysis
16. **NPM registry** - claude-mem@10.3.1, 88 versions published
17. **Prior research** - `/home/idnotbe/projects/claude-memory/research/retrieval-improvement/01-research-claude-mem-retrieval.md`

## Key Findings

### 1. Architecture Evolution is DOCUMENTED
The architecture-evolution page on docs.claude-mem.ai explicitly documents the journey from v1-v2 (naive dump) through v3 (compression breakthrough) to v4 (production-ready) to v5 (user experience). This is the authoritative source.

### 2. No Formal ADRs
There are no Architecture Decision Records in the repo. Instead, rationale is embedded in:
- The docs site (architecture-evolution, progressive-disclosure, context-engineering pages)
- PR descriptions (especially #78, #480, #111)
- Issue descriptions (#103, #104)
- The CHANGELOG.md

### 3. FTS5 Status Clarification
From the prior research file (01-research-claude-mem-retrieval.md): "FTS5 virtual tables exist but are deprecated and unused -- scheduled for removal in v7.0.0". However, the official docs still reference FTS5 as part of the database layer. The CHANGELOG entry for v10.0.8 mentions "Cross-Platform Embedding Fix" removing native binary dependencies but doesn't explicitly deprecate FTS5. The architecture-evolution page says "FTS5 full-text search" was added in v4, and the search architecture combines it with Chroma in a hybrid approach. My assessment: FTS5 exists in the schema but the active search path uses Chroma for semantic queries; FTS5 serves as fallback/legacy for keyword-only paths.

### 4. MCP Architecture Underwent Two Major Transitions
- v5.4.0 (Nov 2025): Moved FROM MCP tools TO skill-based HTTP API search (saving ~2,250 tokens/session)
- v6+ (Dec 2025): Moved BACK TO simplified MCP tools (4 tools instead of 9), removing skill-based search entirely. Achieved 88% code reduction.

### 5. Token Economics is Central to Design Philosophy
Issues #103 and #104, PR #111, and the progressive-disclosure page all reveal that token economics is the PRIMARY design driver. The system was designed around the insight that context windows are finite budgets with n-squared attention costs.

## Self-Critique

### What I'm confident about (CONFIRMED):
- The evolution from v1-v5+ is well-documented on the official docs site
- Token economics as the primary design driver (multiple sources confirm)
- Progressive disclosure rationale (dedicated docs page + PRs)
- Recency-based SessionStart injection rationale (hooks-architecture page)
- Two MCP transitions (PR #78 and PR #480 provide dates and rationale)

### What requires inference (INFERRED):
- Exact reasoning for FTS5's current status -- docs are slightly contradictory
- Whether the author (thedotmack) had prior experience with RAG systems that informed the "context pollution" insight
- Whether the architecture-evolution page was written retrospectively or contemporaneously with each version
- The specific moment ChromaDB was first integrated (CHANGELOG is very long, couldn't read all 1,453 lines)

### What I could NOT find:
- Blog posts by thedotmack explaining rationale outside the docs
- Hacker News discussions specifically about claude-mem architecture
- The user's referenced "documentation about why claude-mem's architecture evolved" -- the architecture-evolution page on docs.claude-mem.ai appears to be exactly this

## Cross-Validation Results

### Gemini (via pal clink) -- PASSED
All 4 key conclusions confirmed:
1. Recency-based SessionStart: Confirmed. Speed (15s hook timeout), no query at session start, ChromaDB reliability issues.
2. 3-layer MCP token economics: Confirmed. Quadratic attention cost, ~5k total vs ~25k+ for loading everything.
3. FTS5 deprecation: Confirmed. Dead code after skill-based search replaced by MCP tools. Scheduled removal in v7.0.0.
4. Architecture evolution timeline: Confirmed. v1-v2 naive -> v3 compression -> v4 progressive disclosure -> v5.4 skills -> v6+ simplified MCP.

Gemini summary: "The architecture is defined by a 'speed-first' boot sequence (recency) and a 'cost-aware' retrieval loop (progressive disclosure), driven explicitly by the quadratic cost of attention in large contexts."

### Codex (via pal clink) -- UNAVAILABLE
Codex hit usage limits and could not validate. Not a concern given Gemini's thorough confirmation.
