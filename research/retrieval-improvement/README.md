# Retrieval Improvement Research — Conclusions

Consolidated conclusions from the retrieval improvement investigation. Process/working files remain in `temp/`.

**Dates:** 2026-02-19 ~ 2026-02-20
**Method:** 10-agent team (initial) + 8-agent team (update), 4 verification rounds each, Gemini cross-validation

---

## Files

| File | Description |
|------|-------------|
| [01-research-claude-code-context.md](01-research-claude-code-context.md) | Claude Code context access findings. `transcript_path` gives hooks full conversation. OTel confirmed. |
| [01-research-claude-mem-retrieval.md](01-research-claude-mem-retrieval.md) | claude-mem retrieval architecture findings. Dual-path: hook (recency) + MCP (vector). No keyword search. |
| [02-research-claude-mem-rationale.md](02-research-claude-mem-rationale.md) | claude-mem architecture rationale and evolution. Why recency-based hooks, 3-layer MCP, FTS5 deprecation, structural enforcement vs behavioral guidance. |
| [06-analysis-relevance-precision.md](06-analysis-relevance-precision.md) | Keyword matching precision analysis (estimated ~40%). Precision-First Hybrid architecture proposal. |

---

## Key Conclusions

1. **Keyword matching precision is estimated ~40%** (rough estimate, not measured) — current auto-injection has high false positive risk
2. **`transcript_path`** gives hooks access to full conversation context (confirmed in `memory_triage.py`; NOT yet used in `memory_retrieve.py` — proposal, not implementation)
3. **claude-mem uses no keyword search** — pure vector (ChromaDB) via MCP tools, recency via hook
4. **claude-mem chose recency for hooks because**: SessionStart에 쿼리 없음, ChromaDB 의존성 회피, sub-ms 속도, 의미 검색은 MCP로 defer
5. **MCP의 구조적 강제**: 파라미터 필수화로 LLM 워크플로우를 강제. Hook+Script는 저장/자동검색에서 같은 역할. MCP는 능동 검색(multi-step LLM 선택)에서만 필요
6. **Recommended: Precision-First Hybrid** — conservative auto-inject (threshold 4) + `/memory-search` skill (proposed)
7. **Evaluation framework required first** — no measurement = no confidence in any change

## Revised Roadmap

| Phase | Effort | Key Change |
|-------|--------|------------|
| 0: Eval Framework | 2h | 20 test queries, precision@5 / recall@5 |
| 0.5: Precision-First | 12h | higher threshold (4) + body tokens + `/memory-search` skill (proposed) + transcript context (future) |
| 1: BM25 (if needed) | 3-4d | IDF weighting + stemming + field scoring |
| 2: Inverted Index (if needed) | 5-7d | O(1) lookup + tiered output |

## Process Files (in temp/)

The following temp/ files contain the detailed research process that produced these conclusions:

| Category | Files in temp/ |
|----------|---------------|
| Initial team report | `00-final-report.md` (superseded, conclusions reflected in above files) |
| Q&A session | `06-qa-consolidated-answers.md` (7 questions answered, conclusions reflected in above files) |
| Research | `research-claude-mem.md`, `research-internal-synthesis.md`, `research-claude-mem-rationale-process.md` |
| Prior investigations | `retrieval-investigation-main.md`, `retrieval-flow-analysis.md`, `retrieval-architecture-critique.md`, `retrieval-security-analysis.md`, `retrieval-scoring-analysis.md`, `retrieval-complete-investigation.md`, `retrieval-cross-verification.md` |
| Alternatives design | `retrieval-alternatives.md` (60KB, 7 alternatives) |
| Reviews | `review-practical.md`, `review-theoretical.md`, `review-accuracy-v2.md`, `review-critical-v2.md` |
| Verification R1 | `verification-r1-completeness.md`, `verification-r1-feasibility.md`, `verify1-functional-v2.md`, `verify1-holistic-v2.md` |
| Verification R2 | `verification-r2-adversarial.md`, `verification-r2-comparative.md`, `verify2-independent-v2.md`, `verify2-crosscheck-v2.md` |
| Working memory | `qa-working-memory.md`, `writer-working-v2.md`, `team-orchestration-v2.md` |
