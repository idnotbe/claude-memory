# Retrieval Improvement: Final Consolidated Report

> **UPDATE (2026-02-20):** This report's recommendations have been **SUPERSEDED** by findings in [06-analysis-relevance-precision.md](06-analysis-relevance-precision.md) and [06-qa-consolidated-answers.md](06-qa-consolidated-answers.md).
>
> **Critical Corrections:**
> 1.  **Constraint Removed:** `transcript_path` grants hooks full conversation access (invalidating the "single prompt" constraint).
> 2.  **New Recommendation:** "Precision-First Hybrid" (High-threshold auto-inject + `/memory-search` skill) replaces the pure "Boring Fix".
> 3.  **Architecture:** Hook + Skill hybrid is viable for interactive search.
>
> *Read this report for the detailed analysis of the 7 alternatives, but refer to [06-analysis-relevance-precision.md](06-analysis-relevance-precision.md) for the final implementation plan.*

**Date:** 2026-02-20
**Team:** retrieval-improvement (10 agents, 4 verification rounds)
**Documents synthesized:** 9 files (2 research + 1 design + 2 reviews + 2 R1 verifications + 2 R2 verifications)
**Total analysis volume:** ~250KB across all documents

---

## Executive Summary

The claude-memory plugin's retrieval system uses keyword-only matching (~400 LOC, stdlib Python) with no semantic understanding. This investigation designed 7 fundamentally different alternatives, subjected them to practical, theoretical, adversarial, and comparative reviews, and cross-validated with Gemini 3 Pro/Flash at each stage.

**Top-line finding:** BM25 scoring with body content indexing and stemming (Alternative 1) is the consensus recommendation across all reviewers, supported by 30 years of IR literature. However, the adversarial review makes a compelling case that a simpler "boring fix" (body tokens + 30 synonym pairs + deeper deep-check + cwd scoring) may capture 60-70% of the improvement at 20% of the cost.

**Critical meta-finding:** No evaluation framework exists to measure retrieval quality. ALL precision/recall estimates across all documents are educated guesses. Building a benchmark (20 test queries with expected results) should precede any implementation.

---

## The 7 Alternatives (Summary)

| # | Alternative | Core Mechanism | Dependencies | Feasibility | Quality | Consensus |
|---|---|---|---|---|---|---|
| 1 | **BM25 + Stemming + Body Indexing** | Statistical keyword scoring with IDF weighting | stdlib only | 9/10 -> 7/10* | High | **IMPLEMENT** |
| 2 | **Local Embedding Vectors** | Transformer bi-encoder + cosine similarity | torch/ONNX (500MB+) | 1/10 | Very High | **REJECT** |
| 3 | **LLM-as-Judge Reranking** | External API call for intelligent reranking | Network + API key | 3/10 | Excellent (when working) | **REJECT AS DEFAULT** |
| 4 | **TF-IDF Vectors + RRF Fusion** | Sparse vector cosine + keyword RRF blend | stdlib only | 8/10 -> 6/10* | Good | **OPTIONAL ADD-ON** |
| 5 | **Progressive Disclosure + Smart Index** | Inverted index + tiered output + token budgeting | stdlib only | 8/10 -> 6/10* | Good (architectural) | **PARTIAL IMPLEMENT** |
| 6 | **Concept Graph + Spreading Activation** | Co-occurrence graph with query expansion | stdlib only | 6/10 -> 4/10* | Moderate | **DEFER** |
| 7 | **Quantized Static Word Vectors** | GloVe 50d int8 vectors, mean-of-vectors cosine | stdlib + 500KB binary | 7/10 -> 3/10* | Low (OOV problem) | **REJECT** |

*Scores adjusted after adversarial review (right-arrow shows pre -> post adversarial adjustment)

---

## Scoring Across All Reviewers

| Alternative | Practical | Theoretical | Feasibility | Adversarial | Comparative | **Median** |
|---|---|---|---|---|---|---|
| Alt 1 (BM25) | 9/10 | 7/10 | 9/10 | 7/10 | 8/10 | **8/10** |
| Alt 2 (Embeddings) | 2/10 | 9/10 | 1/10 | N/A (rejected) | 2/10 | **2/10** |
| Alt 3 (LLM-as-Judge) | N/A* | N/A* | 3/10 | 3/10 | 3/10 | **3/10** |
| Alt 4 (TF-IDF Vectors) | N/A* | N/A* | 8/10 | 6/10 | 5/10 | **6/10** |
| Alt 5 (Progressive) | 7/10* | 6/10* | 8/10 | 6/10 | 7/10 | **7/10** |
| Alt 6 (Concept Graph) | 5/10* | 5/10* | 6/10 | 4/10 | 4/10 | **5/10** |
| Alt 7 (Static Vectors) | N/A* | N/A* | 7/10 | 3/10 | 3/10 | **3/10** |

*N/A or approximate: practical and theoretical reviews covered a different set of 6 alternatives (documented inconsistency from R1 completeness check). Scores marked with * are from reviews that used different numbering.

---

## Key Findings Across All Reviews

### Points of Universal Agreement

1. **stdlib-only constraint is sacrosanct.** All reviewers agree that any alternative requiring non-stdlib dependencies for the retrieval hook is infeasible. This eliminates Alt 2 (embeddings) and effectively eliminates Alt 3 (network dependency) as defaults.

2. **Body content indexing is the single highest-impact change.** Currently, memory bodies are not searched at all. Every reviewer independently identified this as the #1 weakness. Alt 1 and Alt 5 both address this.

3. **IDF weighting provides meaningful discrimination.** The current flat scoring (title=+2, tag=+3) treats all terms equally. IDF weighting makes rare terms matter more. All reviewers agree this is the second highest-impact change.

4. **600-entry scale makes linear scan adequate.** No alternative needs sophisticated indexing for speed. The inverted index (Alt 5) saves ~8ms at 600 entries -- negligible. Its value is code cleanliness and body content inclusion, not performance.

5. **claude-mem's architecture is instructive but not portable.** The ChromaDB + SQLite + progressive disclosure MCP architecture works because claude-mem has a persistent server and interactive tools. claude-memory's hook architecture cannot replicate this.

### Points of Significant Disagreement

1. **Stemmer scope.** The theoretical review argues the S-stemmer is adequate (covers ~80% of technical English suffixes). The adversarial review argues it introduces harmful false positives ("testing"/"test", "running"/"run"). **Resolution:** Implement with a small blocklist (10-20 words) and measure impact with the evaluation framework.

2. **Synonym table vs. trigram matching.** The practical review recommends trigram matching over a static dictionary. The adversarial review argues trigrams have their own noise problems. The theoretical review prefers bidirectional dictionary expansion. **Resolution:** Start with a small dictionary (30 pairs); evaluate trigram matching as a future enhancement.

3. **Progressive disclosure value.** The comparative review notes that claude-mem's progressive disclosure works because it's interactive (MCP tools), while claude-memory's hook-based version is passive and unreliable. The feasibility review is more optimistic, scoring it 8/10. **Resolution:** Extract the inverted index as a standalone improvement; defer tiered output until Claude's behavior with tiered context is empirically tested.

4. **TF-IDF vector value.** The feasibility review scores Alt 4 at 8/10. The adversarial and comparative reviews argue it's marginal over BM25 (highly correlated signals). **Resolution:** Implement as an optional RRF add-on in Phase 3 only if Phase 1 BM25 measurements show insufficient recall.

5. **Alt 7 (Static Vectors) viability.** The feasibility review gives 7/10. The adversarial review gives 3/10 (OOV problem is catastrophic for technical content). The comparative review gives 3/10 (obsolete since 2018). **Resolution:** Reject for now. The OOV problem makes mean-of-GloVe-vectors nearly useless for developer tooling.

6. **"Boring fix" sufficiency.** The adversarial review proposes a minimal fix (body tokens + 30 synonyms + deeper deep-check + cwd scoring, 8 hours) that may capture 60-70% of the quality improvement. Other reviewers did not evaluate this. **Resolution:** Implement the boring fix first, measure, then decide on BM25.

---

## Document Suite Issues

### Critical: Cross-Document Inconsistency (R1 Finding)

The practical and theoretical reviews analyzed a **different set of 6 alternatives** than the main document's 7. Two alternatives (LLM-as-Judge, Static Word Vectors) have zero practical/theoretical review coverage. Two alternatives from the reviews (SQLite FTS5, TF-IDF Cluster Routing) were dropped from the main document without explanation.

**Impact on recommendations:** Alt 3 and Alt 7 recommendations are based on incomplete analysis (feasibility + adversarial + comparative only, no practical/theoretical engineering review). This is acceptable because both are recommended for rejection/deferral, so the missing reviews wouldn't change the outcome.

### Moderate: Optimistic Bias

The architect (who designed the alternatives) and the feasibility reviewer both show optimistic bias:
- Timeline estimates are consistently 1-2 days shorter than what practical engineering experience suggests
- Feasibility scores trend 1-2 points higher than adversarial/comparative scores
- Quality claims ("significantly improved recall") are not grounded in measurable benchmarks

The adversarial and comparative reviews provide useful correction, bringing scores closer to realistic expectations.

---

## Recommended Implementation Roadmap

### Phase 0: Evaluation Framework (MANDATORY, ~2 hours)

**Rationale:** All subsequent decisions should be data-driven.

**Deliverables:**
- 20 test queries with 3-5 expected relevant memories each
- Automated script: run retrieval, measure precision@5 and recall@5
- Baseline measurement of current system

**This phase is non-negotiable.** Without it, we cannot distinguish "Alt X improved retrieval" from "Alt X changed retrieval."

### Phase 0.5: "Boring Fix" (~8 hours, 0 new files)

**Rationale:** The adversarial review makes a compelling case that simple changes address the top weaknesses.

**Changes:**
1. Add `#body:token1,...,token15` to index.md lines (write-time extraction of top 15 body tokens by TF)
2. Add 30 hardcoded synonym pairs in `memory_retrieve.py` (auth/authentication, db/database, k8s/kubernetes, etc.)
3. Raise `_DEEP_CHECK_LIMIT` from 20 to 30
4. Use `cwd` as a scoring signal (boost entries mentioning directory components of the working path)

**Measure:** Run evaluation framework. Compare precision@5 and recall@5 to baseline.

**Decision gate:** If recall@5 improves by >40% (relative), consider whether further improvement is needed.

### Phase 1: BM25 Scoring (~3-4 days, +1 new file: stats.json)

**Rationale:** If the boring fix is insufficient, BM25 is the consensus best-available improvement.

**Changes:**
1. S-stemmer with 15-word blocklist
2. BM25 scoring with field weights (title=3x, tags=4x, body=1.5x)
3. stats.json for IDF weights (rebuilt on every write + `--rebuild`)
4. Intent-based category boosting
5. Graceful degradation if stats.json is missing/stale

**Measure:** Run evaluation framework. Compare to boring fix baseline.

**Decision gate:** If recall@5 > 60% and precision@5 > 70%, stop here (sufficient for most use cases).

### Phase 2: Inverted Index + Output Enhancement (~5-7 days, +1-2 new files)

**Rationale:** If Phase 1 is deployed and users request more candidates or better information density.

**Changes:**
1. Inverted index for O(1) lookup and body content inclusion
2. Token-budgeted output (show more candidates within a token limit)
3. Optional tiered output (behind config flag, default off)
4. Gist store (only if tiered output proves useful in testing)

**Decision gate:** Empirically test Claude's behavior with tiered output before enabling by default.

### Phase 3+: Optional (only if earlier phases prove insufficient)

- **Alt 4 (TF-IDF Vectors):** Implement as RRF add-on to Phase 1. Binary format for vectors.
- **Alt 6 (Concept Graph):** Only after 100+ memories accumulated. Hub dampening required from day one.
- **Alt 3 (LLM-as-Judge):** Only as explicit opt-in with clear user consent for API calls.

---

## Total Resource Estimates

| Phase | Effort | New Files | New LOC | Dependencies |
|---|---|---|---|---|
| Phase 0 (Eval Framework) | 2 hours | 1 (test script) | ~100 | 0 |
| Phase 0.5 (Boring Fix) | 8 hours | 0 | ~80 | 0 |
| Phase 1 (BM25) | 3-4 days | 1 (stats.json) | ~300 | 0 |
| Phase 2 (Inverted Index) | 5-7 days | 1-2 (inv. index, gist store) | ~250 | 0 |
| Phase 3+ (Optional) | 4-7 days each | 1-3 per phase | ~200 each | 0 |
| **Total (Phases 0-2)** | **~7-10 days** | **2-3** | **~730** | **0** |

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| BM25 provides marginal improvement at 600-entry scale | Medium | Medium | Evaluation framework detects this early |
| Stemmer false positives degrade precision | Medium | Low | Blocklist + measurement |
| stats.json corruption/staleness | Low | Medium | Graceful degradation + rebuild tooling |
| Derived artifacts drift (multiple files out of sync) | Medium | Medium | Atomic updates under flock + `--rebuild` command |
| Claude ignores tiered output format | Medium | Medium | Default to flat output; tiered is opt-in |
| Write-path latency accumulation (Phases 1+2) | Low | Low | Budget: keep cumulative additional write latency <200ms |
| Evaluation framework queries don't represent real usage | Medium | High | Start with 20 queries, expand as real query logs are collected |

---

## Rejected Alternatives (with rationale)

| Alternative | Rejection Rationale |
|---|---|
| **Alt 2: Local Embeddings** | Violates stdlib-only constraint. Cold start (2-5s) on WSL2. 500MB+ dependency footprint. Unanimous rejection across all reviewers. |
| **Alt 3: LLM-as-Judge (as default)** | Network dependency (fails offline). Privacy concern (sends data to external API). Recall ceiling limited by keyword pre-filter. Acceptable as explicit opt-in only. |
| **Alt 7: Static Word Vectors** | OOV problem catastrophic for technical content (pydantic, kubectl, jwt = all OOV). Mean-of-vectors composition is obsolete since 2018. 500KB binary asset for negligible quality gain. |
| **SQLite FTS5** (from reviews, not in main doc) | Adds implicit SQLite file management. Production-quality BM25 is available via stdlib-only implementation. The practical review's "ephemeral in-memory FTS5" idea is interesting but adds unnecessary complexity when BM25 is implementable in ~200 LOC. |
| **TF-IDF Cluster Routing** (from reviews, not in main doc) | K-Means clustering "solves a problem that doesn't exist" at 600-entry scale (theoretical review). Cluster assignment is another derived artifact to maintain. |

---

## Open Questions

1. **Can `cwd` be a useful scoring signal?** The hook receives `cwd` but currently ignores it. If the user is working in `backend/auth/`, should auth-related memories be boosted? Needs experimentation.

2. ~~**Should the plugin migrate to MCP tools for retrieval?**~~ **PARTIALLY ANSWERED (Q&A Q3).** A Hook + Skill hybrid achieves interactive search without a separate MCP server process. Skills use existing Claude Code tools (Read, Grep, etc.) and let Claude act as the LLM-as-Judge for relevance. MCP remains an option but is not required. See [06-qa-consolidated-answers.md](06-qa-consolidated-answers.md) Q3.

3. ~~**Is there a way to access conversation context in the hook?**~~ **ANSWERED (Q&A Q4-Q5).** YES -- all hooks receive `transcript_path`, a path to the full conversation JSONL file. The retrieval hook can read recent messages to extract topic keywords, dramatically improving matching precision. See [01-research-claude-code-context.md](01-research-claude-code-context.md) Section 3 and [06-qa-consolidated-answers.md](06-qa-consolidated-answers.md) Q4-Q5.

4. **Should body fingerprint tokens use TF or TF-IDF selection?** The main document says TF-IDF but the detailed description implies TF. The theoretical review argues TF-IDF is strictly better (selects discriminative terms rather than frequent ones). Resolution: use TF-IDF for body fingerprint selection.

---

## Appendix: Document Inventory

| Document | Size | Author | Role |
|---|---|---|---|
| `temp/research-claude-mem.md` | 16KB | researcher-external | claude-mem architecture analysis |
| `temp/research-internal-synthesis.md` | 18KB | researcher-internal | Current system weakness synthesis |
| `temp/retrieval-alternatives.md` | 61KB | architect | 7 alternative designs |
| `temp/review-practical.md` | 38KB | critic-practical | Engineering feasibility review |
| `temp/review-theoretical.md` | 37KB | critic-theoretical | IR theory review |
| `temp/verification-r1-completeness.md` | 23KB | verifier-r1-completeness | Completeness + accuracy check |
| `temp/verification-r1-feasibility.md` | 36KB | verifier-r1-feasibility | Feasibility + integration check |
| `temp/verification-r2-adversarial.md` | ~20KB | verifier-r2-adversarial | Adversarial attack + failure modes |
| `temp/verification-r2-comparative.md` | ~18KB | verifier-r2-comparative | State-of-art comparison |
| `temp/retrieval-final-report.md` | this file | team-lead | Consolidated findings + recommendation |

---

## Conclusion

The claude-memory retrieval system can be significantly improved within its stdlib-only constraint. The recommended path is incremental and measurement-driven:

1. **Build the evaluation framework first** (2 hours). No measurement = no confidence.
2. **Apply the boring fix** (8 hours). Body tokens + synonyms + deeper deep-check + cwd scoring.
3. **Upgrade to BM25 if needed** (3-4 days). IDF weighting + stemming + field-weighted scoring.
4. **Add architectural improvements if needed** (5-7 days). Inverted index + tiered output.

Each phase should demonstrate measurable improvement before the next phase is started. The full 5-phase roadmap from the alternatives document is sound but likely over-engineered -- Phase 1 alone may provide sufficient retrieval quality for the 600-entry scale.

The fundamental quality ceiling for stdlib-only retrieval is ~60-70% precision / ~50-60% recall (approximate, based on IR literature for BM25 on small corpora). Breaking through this ceiling requires dense retrieval (embeddings), which requires either relaxing the stdlib constraint or adopting a persistent subprocess architecture (like claude-mem). This is a future architectural decision, not a retrieval scoring decision.

---

*Final report completed 2026-02-20. Synthesized from 9 analysis documents produced by 10 agents across 4 review phases.*

---

## Q&A Corrections Addendum

*Added 2026-02-20 following a 7-question user Q&A session. Full answers in [06-qa-consolidated-answers.md](06-qa-consolidated-answers.md). Precision analysis and revised architecture in [06-analysis-relevance-precision.md](06-analysis-relevance-precision.md).*

### Correction 1: transcript_path Removes the #1 Constraint

This report identified the "single-prompt limitation" as the **#1 architectural constraint** (Open Question #3). The Q&A session found this constraint does not exist: all hooks receive `transcript_path`, a path to the full conversation JSONL file. The retrieval hook can read recent messages to extract conversation-level topic keywords, which makes even keyword matching far more precise.

**Impact:** The feasibility ceiling for conversation-context-aware retrieval moves from "impossible without Claude Code protocol changes" to "implementable now, ~5-20ms latency for recent-N-messages parsing." This changes the cost-benefit analysis for every alternative.

### Correction 2: Precision-First Hybrid Replaces "Boring Fix"

The report recommended Phase 0.5 as a "boring fix" (body tokens + synonyms + deeper deep-check + cwd scoring). The Q&A session's precision analysis ([06-analysis](06-analysis-relevance-precision.md)) found that the current system has ~40% precision with a high false positive cost. The revised Phase 0.5 recommendation is the **Precision-First Hybrid**:

- **Tier 1 (Hook, automatic):** Higher-threshold auto-injection (min_score 4, max_inject 3). Threshold analysis: single-keyword max score is 5 (title+tag), threshold 4 eliminates single-prefix-match false positives while preserving confident matches.
- **Tier 2 (Skill, on-demand, proposed):** `/memory-search` skill for explicit search. Claude itself acts as LLM-as-Judge for relevance. Not yet implemented or validated.
- **Tier 3 (Config):** User-controllable `auto_inject.enabled`, `auto_inject.min_score` settings.
- **Future:** transcript_path parsing in retrieval hook (proposed enhancement -- currently used only by triage hook, not by retrieval hook).

### Correction 3: Hook + Skill Hybrid (Not Just MCP)

The report's Open Question #2 asked about migrating to MCP tools. The Q&A session found that an **agentic skill** achieves the same interactive search capability without a separate server process. Skills use Claude Code's existing tools and let Claude apply its own judgment to search results. This is functionally equivalent to claude-mem's MCP approach but with zero additional infrastructure.

### Summary of Changes to Roadmap

| Phase | Original Recommendation | Revised Recommendation |
|-------|------------------------|----------------------|
| 0.5 | "Boring fix" (body tokens + synonyms + deeper deep-check + cwd) | Precision-First Hybrid (transcript context + high threshold + body tokens + `/memory-search` skill) |
| 0.5 effort | 8 hours | 12 hours |
| Architecture | Hook-only (passive injection) | Hook + Skill (passive + active) |
| Key signal | user_prompt only | user_prompt (transcript context proposed, not yet implemented) |
