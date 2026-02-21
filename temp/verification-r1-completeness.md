# Verification Round 1: Completeness Check

**Verifier:** Claude Opus 4.6 (primary) + Gemini 3 Pro Preview (cross-check)
**Date:** 2026-02-20
**Documents verified:**
1. `retrieval-alternatives.md` (main alternatives document, 7 alternatives)
2. `review-practical.md` (practical engineering review, 6 alternatives)
3. `review-theoretical.md` (theoretical IR review, 6 alternatives)
4. `research-claude-mem.md` (external research on claude-mem)
5. `research-internal-synthesis.md` (internal analysis of current system)

---

## Overall Completeness Score: 6/10

The main alternatives document is individually strong (would score 8/10 alone), but the document suite as a whole suffers from a critical consistency failure between the main document and its supporting reviews. Two proposed alternatives have zero review coverage, and the reviews analyze alternatives that were subsequently dropped from the main document without explanation.

---

## 1. Distinctness of Alternatives

**Verdict: PASS -- all 7 alternatives are genuinely distinct.**

The 7 alternatives in the main document represent 5 fundamentally different approach categories:

| Category | Alternatives | Core Mechanism |
|---|---|---|
| **Lexical/Probabilistic** | Alt 1 (BM25), Alt 5 (Progressive Disclosure) | Keyword scoring with statistical term weighting |
| **Sparse Vector** | Alt 4 (TF-IDF Vectors) | Sparse bag-of-words vector cosine similarity |
| **Dense Vector** | Alt 2 (Transformer Embeddings), Alt 7 (Static GloVe) | Dense vector cosine similarity |
| **Graph/Structural** | Alt 6 (Concept Graph) | Co-occurrence graph with spreading activation |
| **Agentic/Orchestration** | Alt 3 (LLM-as-Judge) | External LLM reasoning for relevance judgment |

Alt 1 and Alt 5 share a lexical foundation but are meaningfully distinct: Alt 1 improves the *scoring algorithm* while Alt 5 restructures the *output architecture* (tiered disclosure, inverted index, token budgeting). Alt 2 and Alt 7 both use dense vectors but differ fundamentally in quality (384-dim learned vs. 50-dim static), dependencies (500MB+ vs. 500KB), and operational characteristics (cold start vs. instant).

No alternative is a trivial variation of another.

---

## 2. Minimum Distinct Approaches

**Verdict: PASS -- at least 5 fundamentally different approaches identified (exceeds the 4 required).**

1. **Statistical keyword matching** (BM25/IDF-weighted term scoring)
2. **Sparse vector similarity** (TF-IDF cosine)
3. **Dense vector similarity** (learned embeddings or static word vectors)
4. **Graph traversal** (spreading activation on co-occurrence)
5. **LLM-mediated selection** (agentic reranking)

Plus a 6th architectural approach in Alt 5 (progressive disclosure / information architecture) that is orthogonal to the scoring mechanism.

---

## 3. Missing Alternatives

**Verdict: PARTIAL FAIL -- several notable approaches are absent or only mentioned in passing.**

### Missing from main document but analyzed in reviews:

| Missing Alternative | Where Discussed | Impact |
|---|---|---|
| **SQLite FTS5** | review-practical.md (Alt 6), review-theoretical.md (Alt 6) | A production-quality BM25 implementation using stdlib `sqlite3`. Distinct from hand-rolled BM25 (Alt 1) due to built-in phrase queries, porter tokenizer, and structured filtering. Dropped from main doc without explanation. |
| **TF-IDF Cluster Routing (K-Means)** | review-practical.md (Alt 5), review-theoretical.md (Alt 5) | Fundamentally different from Alt 4 (TF-IDF Vectors with RRF): uses K-Means hard clustering for candidate pre-filtering rather than full-corpus cosine similarity. Dropped from main doc without explanation. |

### Genuinely missing (not discussed anywhere):

| Missing Alternative | Rationale for Inclusion | Severity |
|---|---|---|
| **Fuzzy String Matching / N-gram Matching** | Stdlib-friendly (`difflib.SequenceMatcher` or character trigrams). Handles typos and near-misses. The practical review suggests trigram matching as a modification to Alt 1 but it is never developed as a standalone approach. | Low -- better as an enhancement to Alt 1 than standalone |
| **Structured Query / Faceted Filtering** | Parsing structured query syntax (e.g., `tag:python category:runbook since:2026-01`) as a retrieval paradigm. The current system treats the prompt as a flat bag of words. SQLite FTS5 (in reviews) partially addresses this. | Low -- niche use case for this plugin |
| **Active Learning / Relevance Feedback** | The Gemini brainstorm appendix mentions "Anti-Memories" (negative indexing based on feedback) but no alternative proposes a systematic feedback mechanism where retrieval quality improves based on which memories the user actually used. | Medium -- this is the most natural "next frontier" after improving keyword matching |
| **Prompt-Aware Caching / Memoization** | Cache retrieval results keyed by prompt token sets. Identical or highly similar prompts (common in iterative development) could skip retrieval entirely. Zero-cost for cache hits. | Low -- optimization, not a retrieval approach |
| **Neural Sparse Retrieval (SPLADE)** | Learned sparse representations that expand terms based on trained weights. Would require model dependencies (similar to Alt 2). | Low -- violates stdlib constraint |

### Assessment:
The genuinely missing alternatives are either (a) niche, (b) better characterized as enhancements to existing alternatives, or (c) violate constraints. The most significant gap is the **relevance feedback / active learning** concept, which is the natural evolution of any retrieval system but was only briefly mentioned in the appendix. For the current constraints and scale, the 7 proposed alternatives cover the viable design space well.

---

## 4. Technical Accuracy

**Verdict: PASS with minor notes.**

### Verified as accurate:

- **BM25 formula** (Alt 1, line 91): Okapi BM25 formula is correctly stated. k1=1.2, b=0.75 are standard defaults. The field-weighting approach is a valid simplification of BM25F.
- **IDF formula** (theoretical review, line 26): Correctly uses the Robertson IDF variant with +1 smoothing.
- **TF-IDF cosine similarity** (Alt 4, lines 443-451): Sparse vector implementation is correct. The shared-keys optimization is the standard efficient approach.
- **Reciprocal Rank Fusion** (Alt 4, line 455): Formula `alpha/(k + rank)` with k=60 matches the standard RRF formulation from Cormack et al. (2009).
- **Spreading activation** (Alt 6, lines 726-731): Two-hop traversal with 0.5 decay is a standard configuration. The energy propagation model is correctly described.
- **GloVe quantization** (Alt 7, lines 840-841): int8 quantization via `round(float_val * 127 / max_abs_val)` is standard practice for static vector compression.
- **S-stemmer suffixes** (Alt 1, lines 83-85): The described suffix stripping rules are a reasonable simplification.

### Minor technical notes:

1. **Alt 1 BM25 field weighting** (line 93): The formula shows additive field-weighted BM25 scores (`3.0*BM25(title) + 4.0*BM25(tags) + ...`). This is a simplification of BM25F which computes weighted term frequency *before* applying the BM25 saturation function. The additive approach works but can over-weight entries that match in multiple fields. The theoretical review correctly identifies this (line 30: "an acceptable approximation at this corpus size").

2. **Alt 1 body token selection** (line 79): The main document says "top 15 most discriminative body tokens using TF-IDF scoring." However, step 1 in the detailed description says "top 15 most discriminative body tokens" without specifying TF-IDF selection in the index line description. The theoretical review (lines 36-37) correctly flags that TF-based selection would be suboptimal vs. TF-IDF selection. The internal synthesis (Section 7, I1) describes "top 10-15 most frequent non-stop-word tokens" -- which is TF, not TF-IDF. There is inconsistency about whether the selection criterion is TF or TF-IDF.

3. **Alt 7 cosine similarity claim** (line 855): "600 x 50 = 30,000 integer multiplications. Under 1ms in Python." This is plausible but slightly optimistic. Python integer multiplication in a loop has overhead of ~50-100ns per operation, so 30,000 operations would be ~1.5-3ms. Still fast, but "under 1ms" is borderline.

4. **Alt 4 vectors.json size estimate** (line 462): "~600 entries x ~40 terms x ~20 bytes = ~480KB." The 20 bytes per term-weight pair is reasonable for JSON encoding (`"term": 0.1234` = ~18 chars), but JSON overhead (braces, quotes, commas) will push this closer to 600-800KB. Not wrong, but optimistic.

---

## 5. Pros/Cons Balance

**Verdict: PASS -- generally balanced and fair.**

### Well-balanced areas:
- Alt 1 (BM25) fairly acknowledges that it remains "fundamentally keyword-based" despite improvements.
- Alt 2 (Embeddings) is honestly assessed as having "massive dependency footprint" despite best quality.
- Alt 3 (LLM-as-Judge) correctly identifies the network dependency, latency unpredictability, cost, and privacy concerns alongside its quality advantages.
- Alt 6 (Concept Graph) appropriately flags the cold start problem and hub node issue.

### Slight biases detected:

1. **Alt 1 is slightly favored.** It receives the most positive framing ("Best overall value", "Recommended for immediate implementation") with 5 pros and 5 cons, but its cons are milder in tone than other alternatives' cons. The synonym table maintenance burden (con 2) is described as "incomplete" but the practical review (lines 38-42) calls it "a maintenance trap." The main document's characterization is more charitable.

2. **Alt 5 (Progressive Disclosure) may be over-valued.** The main document ranks it 2nd overall, but the tiered output fundamentally does not improve *scoring quality* -- it improves *information density per token*. The comparison table row for "Precision" says "Moderate (same scoring + tiers)" which is honest, but the ranking narrative implies more scoring improvement than the tiers actually provide.

3. **Alt 3 (LLM-as-Judge) is slightly under-valued in the main doc.** The recall ceiling limitation (bounded by keyword pre-filter) is correctly identified, but the main document does not adequately discuss how combining Alt 3 with Alt 1 for candidate generation would dramatically improve the recall ceiling. The theoretical review makes this point (lines 220-221) but the main document's ranking places it 6th without noting this synergy in the ranking rationale.

---

## 6. Comparison Table Accuracy

**Verdict: PASS -- table accurately reflects the 7 alternatives in the main document.**

Spot-checked values:
- Dependencies: All correctly listed (stdlib, torch, API key, etc.)
- Latency ranges: Consistent with detailed sections
- Privacy column: Correctly flags Alt 3 as "Reduced (API sends data)", all others as "Full (local)"
- Body content indexed: Correctly notes each approach's body coverage
- New derived artifacts counts: Verified correct for each alternative

One minor note: The "Impl complexity (LOC)" for Alt 1 shows "~320" but the detailed section says "~200 new/modified lines in memory_retrieve.py, ~80 lines in memory_write.py, ~40 lines in memory_index.py" = ~320 total. Consistent.

---

## 7. Cross-Document Consistency

**Verdict: CRITICAL FAILURE.**

This is the most significant finding. The reviews analyze a **different set of alternatives** than the main document.

### Mapping between documents:

| Main Document (retrieval-alternatives.md) | Practical Review (review-practical.md) | Theoretical Review (review-theoretical.md) |
|---|---|---|
| Alt 1: BM25 + Stemming + Body Indexing | Alt 1: BM25 + Inverted Index | Alt 1: BM25 + Inverted Index |
| Alt 2: Local Embedding Vector Search | Alt 3: Local Embedding + Cross-Encoder | Alt 3: Local Embedding + Cross-Encoder |
| Alt 3: LLM-as-Judge | **NOT REVIEWED** | **NOT REVIEWED** |
| Alt 4: Hybrid TF-IDF Vectors (RRF) | *Not present* (Review Alt 5 is K-Means Clustering, a different approach) | *Not present* (Review Alt 5 is K-Means Clustering) |
| Alt 5: Progressive Disclosure | Alt 4: Progressive Disclosure | Alt 4: Progressive Disclosure |
| Alt 6: Concept Graph | Alt 2: Concept Graph | Alt 2: Concept Graph |
| Alt 7: Static Word Vectors (GloVe) | **NOT REVIEWED** | **NOT REVIEWED** |
| *Not in main doc* | Alt 5: TF-IDF Cluster Routing (K-Means) | Alt 5: TF-IDF Cluster Routing (K-Means) |
| *Not in main doc* | Alt 6: SQLite FTS5 | Alt 6: SQLite FTS5 |

### Impact:
- **Alt 3 (LLM-as-Judge)** has zero practical or theoretical review. This is a significant gap because it introduces unique concerns (network dependency, cost, privacy) that need independent evaluation.
- **Alt 7 (Static Word Vectors)** has zero practical or theoretical review. This approach's OOV problem and quality limitations for technical content need independent evaluation.
- **Alt 4 (Hybrid TF-IDF Vectors)** in the main doc is substantively different from the "TF-IDF" alternative reviewed (K-Means Cluster Routing). One uses RRF rank fusion; the other uses hard cluster routing. These are fundamentally different retrieval architectures.
- **SQLite FTS5** is thoroughly reviewed (practical score 6/10, theoretical score 7/10) but absent from the main alternatives document. The practical review even provides a creative modification (in-memory ephemeral FTS5 index) that addresses the persistence concerns. This analysis is wasted if not reflected in the main document.
- The reviews reference "Gemini 2.5 Flash" analysis as a cross-validation source, but the main document references "Gemini 3 Pro" brainstorm. Different external inputs fed into different documents.

### Root cause assessment:
The main document appears to have been revised after the reviews were written. Alternatives were added (LLM-as-Judge, Static Word Vectors), modified (TF-IDF Vectors replaced K-Means Clustering), and removed (SQLite FTS5) without updating the reviews. The numbering mismatch further confirms that the documents evolved independently.

---

## 8. Architectural Constraints Consideration

**Verdict: PASS -- constraints are well-considered throughout.**

All documents correctly account for:
- **10-second hook timeout**: Latency budgets are analyzed for each alternative. Alt 2's cold start (2-5s) and Alt 3's network latency (up to 3s) are correctly flagged as concerns.
- **stdlib-only constraint**: Clearly distinguished between "hard constraint" (retrieval hook) and "relaxed" (write scripts can use pydantic venv). Alt 2 is correctly identified as violating this constraint.
- **600-entry ceiling**: Multiple documents correctly note that this makes linear scan feasible, reducing the need for sophisticated indexing. The theoretical review explicitly notes that cluster routing (Alt 5 in reviews) "solves a problem that doesn't exist" at this scale.
- **Hook input limitation** (user_prompt + cwd only): The single-prompt context limitation is well-documented in the internal synthesis (Section 4.2) and correctly noted as a persistent architectural limitation.
- **Exit code convention**: Mentioned in the constraints table but not deeply analyzed. All alternatives correctly describe fallback behavior that exits 0.

One minor gap: None of the documents discuss the **concurrent execution** constraint -- what happens when multiple UserPromptSubmit hooks fire simultaneously? This matters for approaches that write derived artifacts (inverted index, vectors, graph) because concurrent writes could corrupt them. The internal synthesis mentions this for index rebuilds (Section 5.6) but the alternatives don't address it for their new artifacts.

---

## Factual Errors Found

| Location | Error | Severity |
|---|---|---|
| Main doc line 85 | S-stemmer examples show "configuring" -> "configur" but a simple suffix-stripping S-stemmer would produce "configur" by stripping "-ing". The example for "deployments" -> "deploy" implies stripping both "-ment" and "-s", which requires two passes. Not wrong per se, but the stemmer implementation would need to handle compound suffixes. | Low |
| Main doc line 121-122 | "Precision: High" and "Recall: Significantly improved" for Alt 1. The theoretical review more conservatively estimates "~60-70% precision / ~50% recall" (line 42). The main document's qualitative labels overstate the improvement vs. the quantitative estimates in the review. | Low |
| Main doc line 855 | "Under 1ms in Python" for 30,000 integer multiplications. More realistically 1.5-3ms in CPython due to loop overhead. Still fast, but the claim is slightly optimistic. | Low |
| Internal synthesis Section 4.10 | Notes tokenization inconsistency between memory_retrieve.py (len > 1) and memory_candidate.py (len > 2). This is flagged as remaining but the main alternatives document does not account for this inconsistency when proposing changes to the retrieval pipeline. | Low |
| Reviews (both) | Reviews analyze "Alt 5: TF-IDF Cluster Routing" and "Alt 6: SQLite FTS5" which do not appear in the main alternatives document. The reviews are analyzing a stale version of the alternatives. | Critical |

---

## Gaps in Analysis

### Critical Gaps:

1. **Two alternatives have zero review coverage** (LLM-as-Judge, Static Word Vectors). Any decision-making based on this document suite has blind spots for these two approaches.

2. **No end-to-end evaluation framework.** The documents propose alternatives and estimate precision/recall qualitatively, but there is no proposed method for actually measuring retrieval quality. Without a benchmark (e.g., a set of test queries with expected relevant memories), the precision/recall estimates are educated guesses. The theoretical review acknowledges this for Alt 4/Progressive Disclosure ("No offline evaluation possible") but the same limitation applies to all alternatives.

3. **Combination/ensemble analysis is thin.** The main document recommends combining Alt 1 + Alt 5 + Alt 6 but does not analyze the interaction effects. Does BM25 + progressive disclosure + concept graph expansion produce compounding benefits or diminishing returns? The theoretical review notes the Alt 1 + Alt 4 synergy (line 220) but this analysis is not developed into a concrete architecture.

### Moderate Gaps:

4. **Migration/rollback strategy.** Each alternative describes an integration plan but none describe how to rollback if the new system produces worse results. What happens to derived artifacts (stats.json, vectors.json, concept_graph.json) if the user downgrades?

5. **Multi-project memory interactions.** The internal synthesis mentions project scoping (research-claude-mem.md Section 8: "Project Scoping at Query Time") but none of the alternatives address how project-scoped retrieval would work with the proposed improvements.

6. **Write-path latency impact.** Several alternatives add write-time computation (body fingerprints, TF-IDF vectors, graph edges, embeddings). The cumulative write-path latency when multiple alternatives are combined is not analyzed.

7. **Memory growth patterns.** The 600-entry ceiling is noted but the alternatives don't discuss behavior as the corpus approaches this ceiling. At 580 entries, the inverted index, concept graph, and TF-IDF vectors are all at their largest. What are the storage and latency characteristics at max capacity?

---

## Recommendations for Improvement

### Priority 1 (Must fix):
1. **Update the reviews to match the main document's alternatives.** The practical and theoretical reviews must evaluate all 7 alternatives from the main document, especially LLM-as-Judge (Alt 3) and Static Word Vectors (Alt 7). Alternatively, re-sync the main document to match the reviews and add the missing alternatives as appendix entries.
2. **Align numbering across all documents.** Use consistent identifiers (e.g., "Alt-BM25", "Alt-LLM", "Alt-GRAPH") rather than numbered alternatives to prevent cross-reference confusion.
3. **Add a "rejected alternatives" appendix** to the main document that covers SQLite FTS5 and TF-IDF Cluster Routing with reasons for exclusion. This preserves the review analysis and explains the editorial decisions.

### Priority 2 (Should fix):
4. **Propose an evaluation methodology.** Even a small benchmark (10-20 test queries with expected relevant memories) would ground the precision/recall estimates in measurable results.
5. **Develop the combination analysis.** The recommended roadmap (Alt 1 -> Alt 5 -> Alt 6) needs an architecture diagram showing how the three approaches compose at the code level.
6. **Add relevance feedback as a future-work section.** It is the most natural "next step" after improving keyword matching and was only briefly mentioned in the Gemini brainstorm appendix ("Anti-Memories").

### Priority 3 (Nice to have):
7. **Add write-path latency budget analysis** for the recommended combination (Alt 1 + Alt 5 + Alt 6).
8. **Address concurrent access** for all new derived artifacts.
9. **Discuss rollback strategies** for each phase of the implementation roadmap.

---

## Gemini 3 Pro Cross-Check Summary

Gemini 3 Pro Preview independently confirmed:
- All 7 alternatives are distinct, representing 4+ fundamental categories.
- Technical details (BM25, TF-IDF, RRF, GloVe quantization, spreading activation) are accurate.
- Pros/cons are balanced and fair.
- The comparison table accurately reflects the main document's alternatives.
- **Critical consistency failure** between the main document and reviews (independently identified the same mapping mismatches documented above).

Gemini additionally flagged:
- **Fuzzy string matching (Levenshtein/trigram)** as a missing stdlib-friendly technique (assessed: better as an Alt 1 enhancement than standalone).
- **Tag-based faceted filtering** as a missing structured query approach (assessed: low priority for this plugin's use case).
- **Local cross-encoder re-ranking** as a missing middle ground between Alt 2 and Alt 3 (assessed: would violate stdlib constraint).

---

## Final Assessment

| Dimension | Score | Notes |
|---|---|---|
| **Distinctness of alternatives** | 9/10 | All 7 are genuinely distinct |
| **Coverage of approach space** | 7/10 | Good coverage; minor gaps in fuzzy matching and relevance feedback |
| **Technical accuracy** | 9/10 | All formulas and algorithms are correct; minor optimistic estimates |
| **Pros/cons balance** | 8/10 | Generally fair; slight Alt 1 favoritism |
| **Comparison table accuracy** | 9/10 | Accurately reflects the main document |
| **Cross-document consistency** | 3/10 | Critical failure: reviews analyze different alternatives |
| **Constraint consideration** | 8/10 | Well-handled; minor gap on concurrent access |
| **Analysis depth** | 7/10 | Missing evaluation framework and combination analysis |
| **OVERALL** | **6/10** | Strong individual documents undermined by cross-document inconsistency |

The main alternatives document is a high-quality technical analysis. The practical and theoretical reviews are individually excellent. But the document suite fails as a coherent decision-making package because the reviews do not cover the same alternatives as the main document, creating blind spots and wasted analysis.

---

*Verification completed 2026-02-20. Cross-checked with Gemini 3 Pro Preview.*
