# claude-mem Architecture Rationale and Evolution

**Date:** 2026-02-20
**Repository:** https://github.com/thedotmack/claude-mem (v10.3.1 as of research date)
**Official Docs:** https://docs.claude-mem.ai/
**Focus:** WHY the architecture was designed this way, not just WHAT it does

---

## Evidence Classification

Throughout this document:
- **[CONFIRMED]** = Directly stated in official documentation, PR descriptions, or issue tracker
- **[INFERRED]** = Reasoned from available evidence but not explicitly stated by the author

---

## 1. Why Recency-Based Hook Injection (Not Semantic/Vector) for SessionStart

### The Decision
**[CONFIRMED]** The SessionStart hook injects context using a purely recency-based approach: recent observations (configurable, default 50) and recent session summaries (last 10), ordered by creation time. No vector search, no keyword matching.

### The Rationale

**[CONFIRMED]** Four explicit reasons from the [hooks architecture documentation](https://docs.claude-mem.ai/hooks-architecture):

1. **Speed**: Recency queries use SQLite indexed columns (`created_at_epoch`). Sub-millisecond response time. Hook timeouts vary by type (600s command, 30s prompt, 60s agent per official docs), but the injection path should still be fast and deterministic for responsiveness.

2. **Relevance heuristic**: Recent context is most likely relevant for session continuity. If you were working on authentication yesterday, you probably want that context today. This is a heuristic, not a guarantee, but it works well for the common case.

3. **Simplicity**: Avoids requiring ChromaDB to be running for basic functionality. ChromaDB has caused significant operational issues (35GB RAM usage per [issue #707](https://github.com/thedotmack/claude-mem/issues/707), segfaults on Linux per [issue #1110](https://github.com/thedotmack/claude-mem/issues/1110), spawn storms per [PR changelog v10.0.3](https://github.com/thedotmack/claude-mem/blob/main/CHANGELOG.md)). Making the baseline injection path depend on ChromaDB would make the entire system fragile.

4. **Deferred complexity**: Expensive semantic operations are deferred to on-demand MCP tool calls, where the LLM can make informed decisions about what to search for. The SessionStart hook provides a "good enough" baseline; the LLM can then actively search for anything specific it needs.

### Trade-offs Considered

**[CONFIRMED]** From the [architecture evolution page](https://docs.claude-mem.ai/architecture-evolution):
- v1-v2 loaded ALL observations at SessionStart (~35,000 tokens, 1.4% relevance). This was catastrophically wasteful.
- v3 added AI compression (10:1 to 100:1 ratios) but still loaded all compressed observations upfront.
- v4 introduced progressive disclosure: show an index first (~800 tokens), fetch 2-3 relevant observations on-demand (~300 tokens). This reduced context waste by 87%.

**[INFERRED]** Semantic injection at SessionStart was likely considered and rejected because:
- It would require a query to search against, but at session start there is no user query yet
- Running ChromaDB adds latency and failure modes to every session start
- The "recent is relevant" heuristic is good enough for the cold-start problem; once the user provides a prompt, the LLM can use MCP tools for targeted semantic search

---

## 2. Why 3-Layered MCP Architecture (search -> timeline -> get_observations)

### The Decision
**[CONFIRMED]** claude-mem implements a 3-layer progressive disclosure pattern:
1. **Layer 1 (search)**: Returns compact index with IDs, titles, dates, types (~50-100 tokens/result)
2. **Layer 2 (timeline)**: Returns chronological context around a specific observation
3. **Layer 3 (get_observations)**: Returns full observation details (~500-1000 tokens/result)

### The Rationale

**[CONFIRMED]** From the [progressive disclosure documentation](https://docs.claude-mem.ai/progressive-disclosure) and [context engineering page](https://docs.claude-mem.ai/context-engineering):

**Token economics is the primary design driver.** The core insight:
> "Every token attends to every other token (n-squared relationships), creating quadratic computational relationships."

This means context pollution is expensive not just linearly but quadratically. Loading 35,000 tokens of memory when only 2,000 are relevant wastes attention capacity for the remaining 33,000 tokens across every subsequent generation step.

**The math, from PR #111 and issue #104:**
- Loading 15 compressed observations: ~5,000 tokens
- Original work those observations represent: ~167,000 tokens
- Savings: 97% reduction from reuse
- But only if you load the RIGHT 15 observations, not all 500+

**Progressive disclosure solves the selection problem:**
- Layer 1 costs ~50-100 tokens per result. Scanning 50 results costs ~3,750 tokens.
- The LLM reads the index and selects 2-3 relevant items.
- Layer 3 fetches only those items: ~1,500 tokens.
- Total: ~5,250 tokens for targeted, relevant context.
- Alternative (load everything): 50+ observations * ~500 tokens = 25,000+ tokens.

**[CONFIRMED]** From the progressive disclosure page: "The system cannot know task relevance better than the agent possesses current context. Pre-fetching assumes the system understands the goal; progressive disclosure respects agent intelligence."

### Evolution of Search Architecture

**[CONFIRMED]** The search architecture went through three major phases:

1. **v4-v5.3 (Oct-Nov 2025)**: 9+ MCP tools with overlapping purposes (~2,500 tokens in tool definitions alone). This was the initial implementation.

2. **v5.4.0 (Nov 2025, PR #78)**: Migrated FROM MCP tools TO skill-based HTTP API search. Achieved ~2,250 token savings per session. The 10 search operations were accessed via `claude-mem:search` skill with progressive disclosure (frontmatter ~250 tokens, full instructions ~2,500 tokens loaded on-demand).

3. **v6+ (Dec 2025, PR #480)**: Migrated BACK TO simplified MCP tools (4 tools instead of 9+). Eliminated ~5,150 lines of code (88% reduction). Achieved 50-75% token savings through forced efficient patterns. The insight was that "progressive disclosure is enforced by tool design itself" -- structuring the MCP tools as a 3-layer workflow makes wasteful retrieval structurally difficult rather than relying on agent discipline.

**[INFERRED]** The skill-based approach (v5.4.0) was likely abandoned because:
- Skills add cognitive overhead for the LLM (understanding when to invoke the skill vs. using MCP tools directly)
- MCP tools are a native protocol that the LLM already understands
- The simplified 4-tool MCP design achieved the same token efficiency with less abstraction

---

## 3. Why Keyword Search (FTS5) Was Deprecated

### The Status

**[CONFIRMED]** FTS5 virtual tables exist in the SQLite schema. They were added in v4 as part of the "production-ready" database redesign.

**[CONFIRMED]** From the prior research file (01-research-claude-mem-retrieval.md, based on source code analysis): "FTS5 virtual tables exist but are deprecated and unused -- scheduled for removal in v7.0.0" and "No BM25/TF-IDF scoring, no keyword search at all in the active retrieval path (FTS5 is dead code)."

**[CONFIRMED]** The active search path uses:
- ChromaDB vector search when available (semantic queries)
- SQLite date-ordered queries as fallback (no text relevance scoring)
- FTS5 is not called in either path

### The Rationale

**[CONFIRMED]** From the architecture-evolution page: v5.0.0 introduced "Hybrid Search" combining "SQLite FTS5 for keyword matching with Chroma vector database for semantic search, maintaining graceful degradation if Chroma unavailable."

**[INFERRED]** FTS5 was effectively deprecated (though not yet removed from the schema) because:
1. ChromaDB's vector search subsumes FTS5's functionality -- semantic search finds keyword matches AND conceptual matches
2. The SearchOrchestrator decision tree (documented in 01-research-claude-mem-retrieval.md) routes text queries to ChromaDB when available, and falls back to date-ordered SQLite (not FTS5) when ChromaDB is unavailable
3. Maintaining FTS5 indexes adds write overhead for every observation insertion with no query-path consumer
4. The skill-based search (v5.4.0) briefly used FTS5 via HTTP API endpoints, but when skills were replaced by MCP tools (v6+), those endpoints were removed

**[CONFIRMED]** The CHANGELOG entry for Windows (v9.0.0 area): "Chroma temporarily disabled on Windows... Keyword search and all other memory features continue to work" -- suggesting that when Chroma is unavailable, the system falls back to basic SQLite queries, not FTS5 keyword search.

### Was FTS5 Ever Active?

**[CONFIRMED]** Yes. PR #78 (v5.4.0, Nov 2025) introduced 10 search operations including "Search observations (full-text)", "Search session summaries (full-text)", "Search user prompts (full-text)" -- these used FTS5 via HTTP API endpoints on the worker service. When the skill-based search was replaced by simplified MCP tools (Dec 2025), these FTS5-backed endpoints lost their consumer.

---

## 4. Architecture Evolution Timeline

### v1-v2 (Aug-Sep 2025): Naive Dump
**[CONFIRMED]** Raw tool outputs dumped into storage. ~35,000 tokens loaded per session, 1.4% relevance. "The concept proved valuable but the implementation wasted tokens catastrophically."

### v3 (Oct 2025): AI Compression Breakthrough
**[CONFIRMED]** Introduced Claude Agent SDK for background compression. 10:1 to 100:1 compression ratios. Key problems discovered:
- Still loaded all observations upfront despite compression
- Session ID management broke (SDK generates new IDs each turn)
- Aggressive cleanup interrupted in-progress summaries

### v4 (Oct 2025): Production-Ready
**[CONFIRMED]** Five-hook system (SessionStart, UserPromptSubmit, PostToolUse, Summary, SessionEnd). Database redesigned with structured fields, FTS5, rich metadata. Worker service as single long-running async session. Progressive disclosure index at SessionStart.

Key architectural insights:
- Progressive disclosure: show index first, fetch on demand
- Session ID volatility: track via system initialization messages
- Graceful cleanup: mark complete, let workers finish naturally
- Single long-running session per Claude Code session

### v5.0.0 (Nov 2025): Hybrid Search
**[CONFIRMED]** Combined SQLite FTS5 with ChromaDB vector search. Graceful degradation if Chroma unavailable.

### v5.4.0 (Nov 2025, PR #78): Skill-Based Search
**[CONFIRMED]** Migrated from 9+ MCP tools to skill-based HTTP API search. ~2,250 token savings per session. 10 search operations via `claude-mem:search` skill.

### v5.5.0 (Nov 2025): Skill Rename
**[CONFIRMED]** Renamed "search" to "mem-search". Increased effectiveness from 67% to 100% through enhanced trigger mechanisms.

### v6+ (Dec 2025, PR #480): MCP Simplification
**[CONFIRMED]** Returned to MCP tools but simplified from 9+ to 4. Eliminated ~5,150 lines of code (88% reduction). 3-layer workflow pattern enforced structurally.

### v10.0.7-10.3.1 (Feb 2026): Chroma Infrastructure Hardening
**[CONFIRMED]** Rapid iteration on Chroma reliability: HTTP server architecture (v10.0.7), WASM embeddings (v10.0.8), spawn storm prevention (v10.0.3/10.0.4), backfill fixes (v10.2.4), chroma-mcp MCP connection replacing WASM (v10.3.0).

### npm Version Count
**[CONFIRMED]** 88 versions published to npm as of research date, indicating very active development over ~6 months.

---

## 5. Design Philosophy Summary

**[CONFIRMED]** From multiple official sources, claude-mem's architecture is built on these principles:

1. **Context is a finite budget**: Every token costs attention. Waste is quadratic, not linear.

2. **Progressive everything**: Show metadata before details. Let the agent decide what's relevant. Make retrieval costs visible.

3. **Speed at the edges, intelligence in the middle**: Hooks must be fast and deterministic. Expensive AI processing happens asynchronously in the worker service.

4. **Graceful degradation over hard dependencies**: Core functionality (capture + recency-based injection) works without ChromaDB. Semantic search is an enhancement, not a requirement.

5. **Structural enforcement over behavioral guidance**: The 3-layer MCP workflow makes wasteful retrieval structurally difficult. You cannot get full observation details without first getting IDs from the search layer.

6. **Token economics as ROI**: Track and display the cost of discovery vs. the cost of reuse. Make the value proposition visible (PR #111, issues #103, #104).

---

## 6. Structural Enforcement의 적용 범위: MCP vs Hook vs Script

### 핵심 질문
MCP의 파라미터 강제가 LLM 행동을 구조적으로 제약한다면, 모든 경로(저장/검색)에 MCP를 써야 하는가?

### 답: 아니다 — 구조적 강제의 수단은 경로마다 다르다

구조적 강제가 필요한 곳은 **LLM이 선택을 하는 지점**이다. LLM이 관여하지 않는 지점에서는 일반 스크립트로 충분하다.

| 경로 | LLM 선택 지점 | 강제 수단 | 비고 |
|------|-------------|----------|------|
| **저장 (Write)** | 무엇을 저장할지, 어떻게 쓸지 | Hook(결정론적 트리거) + Script(Pydantic 스키마 강제) | LLM이 내용을 작성하지만, 스크립트가 포맷을 강제 |
| **자동 검색 (Auto-retrieve)** | 없음 (완전 결정론적) | Hook + Script (keyword matching) | LLM 판단 불필요 — 스크립트가 전부 처리 |
| **능동 검색 (On-demand)** | 무엇을 검색할지, 어떤 결과를 선택할지 | **MCP tool** (파라미터 강제) | LLM이 multi-step 선택을 해야 하므로 MCP가 적합 |

### claude-memory의 현재 구조는 이미 올바르다

claude-memory의 저장 경로:
```
Stop hook (결정론적 트리거)
  → memory_triage.py (결정론적 분류)
    → LLM이 내용 작성 (여기서 LLM 판단 개입)
      → memory_write.py (Pydantic 스키마로 포맷 강제)
```

Hook이 미리 정의된 스크립트를 호출하는 것 자체가 구조적 강제다. MCP의 파라미터 강제와 목적은 같지만 수단이 다를 뿐:
- **Hook + Script**: "이 이벤트가 발생하면 이 코드를 실행한다" (트리거 강제)
- **MCP tool**: "이 파라미터를 넘겨야만 다음 단계로 갈 수 있다" (워크플로우 강제)

### MCP가 필요한 곳은 능동 검색뿐

MCP의 구조적 강제가 진가를 발하는 곳은 **LLM이 multi-step 선택을 해야 하는 검색 경로**다:
1. `search(query)` → ID 목록 반환 (LLM이 query를 선택)
2. `get_observations(ids)` → ID 필수 (LLM이 관련 항목을 선택)

이 워크플로우에서 LLM이 "전부 다 가져오기"를 할 수 없게 API 구조로 막는 것이 MCP의 장점이다.

반면, 저장 경로에서는 Hook + Script가 이미 같은 역할을 하고 있으므로 MCP가 불필요하다.

### claude-memory에 대한 시사점

현재 claude-memory에 없는 것은 **능동 검색 경로**(Tier 2)뿐이다. 이것을 구현할 때:
- **Skill**: LLM에게 "이렇게 검색하세요"라고 지시 → LLM이 안 따를 수 있음
- **MCP tool**: API 구조로 워크플로우 강제 → LLM이 건너뛸 수 없음
- **현실적 판단**: claude-memory는 stdlib-only 제약이 있으므로, MCP 서버 운영보다는 skill + script 조합이 적합. 단, skill 지시의 단순함이 중요 (claude-mem의 v5.4.0에서 skill effectiveness가 67%였던 교훈)

---

## Sources

### Official Documentation
- [Architecture Evolution](https://docs.claude-mem.ai/architecture-evolution)
- [Progressive Disclosure](https://docs.claude-mem.ai/progressive-disclosure)
- [Context Engineering](https://docs.claude-mem.ai/context-engineering)
- [Search Architecture](https://docs.claude-mem.ai/architecture/search-architecture)
- [Hooks Architecture](https://docs.claude-mem.ai/hooks-architecture)
- [Architecture Overview](https://docs.claude-mem.ai/architecture/overview)

### GitHub
- [Repository](https://github.com/thedotmack/claude-mem)
- [CHANGELOG.md](https://github.com/thedotmack/claude-mem/blob/main/CHANGELOG.md)
- [PR #480 - MCP Architecture Documentation](https://github.com/thedotmack/claude-mem/pull/480) (merged 2025-12-29)
- [PR #78 - Skill-Based Search Migration](https://github.com/thedotmack/claude-mem/pull/78) (merged 2025-11-09)
- [PR #111 - ROI Tracking with discovery_tokens](https://github.com/thedotmack/claude-mem/pull/111) (merged 2025-11-16)
- [Issue #103 - Token cost metrics display](https://github.com/thedotmack/claude-mem/issues/103)
- [Issue #104 - Discovery costs display](https://github.com/thedotmack/claude-mem/issues/104)
- [Issue #707 - SQLite-only backend mode](https://github.com/thedotmack/claude-mem/issues/707)
- [Issue #1110 - ChromaDB segfaults on Linux](https://github.com/thedotmack/claude-mem/issues/1110)
- [docs/SESSION_ID_ARCHITECTURE.md](https://github.com/thedotmack/claude-mem/blob/main/docs/SESSION_ID_ARCHITECTURE.md)

### Third-Party Analysis
- [DeepWiki: thedotmack/claude-mem](https://deepwiki.com/thedotmack/claude-mem)
- [NPM: claude-mem](https://www.npmjs.com/package/claude-mem) (v10.3.1, 88 versions)

### Prior Research
- `/home/idnotbe/projects/claude-memory/research/retrieval-improvement/01-research-claude-mem-retrieval.md`
