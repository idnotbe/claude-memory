# Evaluator Working Notes -- Session 9

**Date:** 2026-02-22
**Task:** Qualitative precision evaluation (20-30 queries), BM25-only vs BM25+judge

## Approach

No real memory data exists in `.claude/memory/` (no index.md, no JSON files). Therefore:
1. Create synthetic memory corpus (~30-40 entries) covering all 6 categories
2. Build index.md and JSON files in a temp directory
3. Run actual BM25 queries via `memory_search_engine.py` CLI
4. For each query, analyze BM25 results and predict judge behavior based on JUDGE_SYSTEM prompt
5. Classify each query by outcome: judge-helps, judge-hurts, judge-neutral

## Synthetic Corpus Design

Realistic entries modeling a medium-complexity web app project with:
- Auth system (JWT, OAuth)
- Database (PostgreSQL, migrations)
- Frontend (React, TypeScript)
- CI/CD pipeline
- API design
- Caching (Redis)
- Testing strategy
- Deployment (Docker, K8s)

## Query Categories

1. **Direct topic matches** -- queries about topics that have dedicated memories
2. **Cross-domain queries** -- queries about topics where memories exist but in different contexts
3. **Ambiguous/vague queries** -- queries that match many entries superficially
4. **Technical identifiers** -- specific file names, function names, config keys
5. **Multi-word concepts** -- compound technical phrases
6. **Negative cases** -- queries about topics with no relevant memories
7. **Partial overlap** -- queries where some results are relevant, others are noise

## Progress

- [x] Design synthetic corpus (28 entries, 6 categories, realistic web app project)
- [x] Create temp directory with index.md + JSON files (via s9-eval-harness.py)
- [x] Design 25 queries across 7 categories
- [x] Run BM25 queries and record results (95 total results, 32 relevant)
- [x] Analyze judge behavior for each query (predicted per JUDGE_SYSTEM semantics)
- [x] Get external opinions (Codex 5.3 + Gemini 3 Pro)
- [x] Write evaluation report (temp/s9-eval-report.md)

## Key Findings

1. BM25 precision: 33.7% overall, 68% P@1, 0.71 MRR
2. Judge highest value: ambiguous (Q09-Q11) and negative (Q20-Q22) queries -- prevents false-positive injection
3. Judge lowest value: technical identifiers (Q12-Q15) -- BM25 already precise
4. Judge cannot fix: retrieval misses (Q08 "build speed" missing Jest/Vitest entry)
5. Judge risk: false-negative over-filtering on borderline-relevant results

## External Feedback Integration

### From Codex 5.3
- Missing query categories: paraphrase, anaphora, negation, typos, temporal
- Judge sees title/tags only (no body) -- could cause false negatives
- Harness mode=search differs from production mode=auto
- Quantified: P@1=68%, MRR=0.71, precision=33.7%

### From Gemini 3 Pro
- Corpus too small for reliable IDF (recommended 150-300 entries)
- Synthetic bias: vocabulary homogeneity, length uniformity, missing code snippets
- Suggested hybrid routing: skip judge on high-confidence BM25 matches
- Weight negative/ambiguous categories highest for auto-inject evaluation

## Artifacts

- `temp/s9-eval-harness.py` -- evaluation script with synthetic corpus + queries
- `temp/s9-eval-raw-results.json` -- raw BM25 query results
- `temp/s9-eval-report.md` -- final evaluation report
