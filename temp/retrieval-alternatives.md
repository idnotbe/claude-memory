# Retrieval Improvement Alternatives for claude-memory

**Date:** 2026-02-20
**Status:** Design document -- 7 fundamentally different retrieval architectures
**Input sources:** research-claude-mem.md (ChromaDB hybrid architecture), research-internal-synthesis.md (current keyword weaknesses), memory_retrieve.py (current implementation), Gemini 3 Pro brainstorm session

---

## Current Baseline

The current retrieval system is a stdlib-only Python script (~400 LOC) running as a UserPromptSubmit hook with a 10-second timeout. It receives only `user_prompt` + `cwd`, parses a flat `index.md` file, and performs two-pass keyword scoring (title + tags in Pass 1, JSON deep-check for top 20 in Pass 2). It has zero semantic understanding, does not index body content, and uses hard-coded scoring weights.

**Key metrics of the current system:**
- Latency: ~50-200ms (mostly Pass 2 JSON I/O)
- Precision: High for exact keyword matches, zero for synonyms/paraphrases
- Recall: Low -- misses body-relevant entries, morphological variants, conceptual relations
- Dependencies: stdlib only
- Scale ceiling: ~600 entries (6 categories x 100 max)

---

## Constraints (apply to all alternatives)

| Constraint | Value |
|---|---|
| Hook timeout | 10 seconds hard limit |
| Hook input | `user_prompt` + `cwd` only (no conversation history) |
| Core dependency rule | stdlib-only for retrieval script (pydantic v2 for write scripts only) |
| Max entries | ~600 (6 categories x 100) |
| Plugin environment | Cannot modify Claude Code hook protocol |
| Output format | stdout text injected into Claude context |
| Exit code | Must exit 0 even on "no results" |

---

## Alternative 1: Enhanced Keyword (BM25 + Stemming + Body Indexing)

### One-line summary
Maximize keyword search quality through BM25 scoring, lightweight stemming, body content fingerprints, and IDF-weighted term importance -- all in pure stdlib Python.

### Architecture

```
                           WRITE TIME                              READ TIME (Hook)
                    ========================               =========================

  memory_write.py                                          stdin: {user_prompt, cwd}
       |                                                            |
       v                                                            v
  [JSON memory file]                                       tokenize + stem(prompt)
       |                                                            |
       v                                                            v
  extract_body_fingerprint()                              load index.md + stats.json
  compute_term_freqs()                                              |
       |                                                            v
       v                                                   +-----------------+
  update index.md:                                         | BM25 Scoring    |
    - [CAT] title -> path                                  |  field-weighted |
      #tags:t1,t2                                          |  IDF from stats |
      #body:b1,b2,...,b15                                  |  stem matching  |
       |                                                   +-----------------+
       v                                                            |
  update stats.json:                                                v
    - doc_count: N                                         Pass 2: deep check
    - avg_doc_len: L                                       (recency, retired)
    - idf: {token: score}                                           |
                                                                    v
                                                           top max_inject results
                                                                    |
                                                                    v
                                                           stdout: <memory-context>
```

### Step-by-step description

1. **Write-time preprocessing (memory_write.py changes):**
   - When a memory is created/updated, extract the top 15 most discriminative body tokens using TF-IDF scoring against the global corpus.
   - Store these as `#body:token1,token2,...,token15` suffix on the index line.
   - Maintain a sidecar `stats.json` file: `{doc_count, avg_doc_len, idf: {token: float}}`.
   - Rebuild `stats.json` during index rebuild operations.

2. **Lightweight S-stemmer (~25 lines):**
   - Strip common English suffixes: `-s`, `-es`, `-ing`, `-ed`, `-ly`, `-tion`/`-sion` normalization, `-ment`, `-ness`.
   - Applied to both prompt tokens and index tokens at match time.
   - Examples: `configuring` -> `configur`, `deployments` -> `deploy`, `migrations` -> `migrat`.
   - Not linguistically perfect but covers ~80% of morphological variation in technical English.

3. **BM25 scoring with field weights:**
   - Replace the current flat point system with BM25 (Okapi variant):
     ```
     score(q, d) = SUM_over_terms[ IDF(t) * (tf(t,d) * (k1+1)) / (tf(t,d) + k1 * (1 - b + b * |d|/avgdl)) ]
     ```
   - Field-weighted: `score = 3.0*BM25(title) + 4.0*BM25(tags) + 1.5*BM25(body_fingerprint) + 0.5*BM25(category_desc)`
   - IDF loaded from `stats.json` -- rare terms like `idempotency` score much higher than common terms like `config`.
   - Parameters: `k1=1.2`, `b=0.75` (standard BM25 defaults).

4. **Intent-based category boosting:**
   - Detect intent keywords in prompt to dynamically adjust category priority:
     - error/fail/crash/broken/fix -> boost RUNBOOK by 1.5x
     - why/decide/choose/alternative -> boost DECISION by 1.5x
     - goal/summary/session/progress -> boost SESSION_SUMMARY by 1.5x
   - Simple keyword-set lookup, ~20 lines.

5. **Synonym micro-table (~50 entries):**
   - Static bidirectional mapping of common technical synonyms:
     ```python
     SYNONYMS = {"auth": "authentication", "db": "database", "config": "configuration", ...}
     ```
   - Expand prompt tokens before matching: if user types `auth`, also match against `authentication`.

### Dependencies required
- **None** -- pure stdlib Python. All algorithms are arithmetic on strings and numbers.

### Implementation complexity
- **LOC:** ~200 new/modified lines in `memory_retrieve.py`, ~80 lines in `memory_write.py` (fingerprint extraction), ~40 lines in `memory_index.py` (stats rebuild).
- **Effort:** 2-3 days. Low risk, incremental.
- **New files:** `stats.json` (sidecar, ~5-20KB).

### Expected performance
- **Precision:** High. BM25 IDF weighting naturally promotes rare, discriminative terms. Field weighting prevents body noise from drowning title matches.
- **Recall:** Significantly improved. Body fingerprints surface content-relevant entries invisible to current system. Stemming catches morphological variants. Synonym table handles the top 50 paraphrase gaps.
- **Latency:** ~60-250ms. Slightly slower than current (IDF lookup + stemming), but well within timeout.

### Pros
1. Zero new dependencies -- preserves the stdlib-only constraint exactly.
2. Fully incremental -- can be deployed one feature at a time (stemming first, then BM25, then body fingerprints).
3. Deterministic and auditable -- no model drift, no opaque embedding spaces.
4. IDF weighting is the single highest-impact change: makes rare terms matter and common terms noise.
5. Body fingerprints solve the "relevant body, generic title" problem without reading JSON at query time.

### Cons
1. Still fundamentally keyword-based -- no true semantic understanding. "rate limiting" will never match "throttling" unless explicitly in the synonym table.
2. Synonym table is manually maintained and will always be incomplete.
3. BM25 parameters (k1, b, field weights) need tuning and there is no automatic feedback loop.
4. `stats.json` introduces a new derived artifact that can become stale (same problem as `index.md`).
5. Stemming can introduce false positives: "mining" and "mine" stem similarly but are often unrelated in tech contexts.

### Integration plan
1. Add stemmer function to `memory_retrieve.py` (standalone, testable).
2. Add `#body:` fingerprint extraction to `memory_write.py` create/update paths.
3. Add `stats.json` generation to `memory_index.py --rebuild`.
4. Modify `score_entry()` to use BM25 with field weights.
5. Add intent-based category boosting.
6. Add synonym expansion.
7. Update tests for each component.

### Risk assessment
- **Low risk.** Each component is independently testable and reversible. The worst case for any single component is slightly degraded precision (false positives from aggressive stemming), which is easily tunable. No architectural changes required.

---

## Alternative 2: Local Embedding Vector Search

### One-line summary
Add sentence-transformers for dense vector embeddings with pre-computed vectors stored alongside memories, enabling true semantic search (synonyms, paraphrases, conceptual similarity).

### Architecture

```
                    WRITE TIME                                READ TIME (Hook)
             =======================                   =========================

  memory_write.py                                      stdin: {user_prompt, cwd}
       |                                                        |
       v                                                        v
  [JSON memory file]                                   load embeddings.bin
       |                                               (~600 x 384 floats = 900KB)
       v                                                        |
  embed_memory()                                                v
  (sentence-transformers                               embed_prompt()
   all-MiniLM-L6-v2)                                   (sentence-transformers
       |                                                all-MiniLM-L6-v2)
       v                                                        |
  append to                                                     v
  embeddings.bin:                                      cosine_similarity(
    {id -> 384-dim vector}                               prompt_vec,
       |                                                 all_memory_vecs)
       v                                                        |
  FAISS index rebuild                                           v
  (optional, for >1000)                                top-K nearest neighbors
                                                                |
                                                                v
                                                       load JSON for top-K
                                                       (title, tags, snippet)
                                                                |
                                                                v
                                                       stdout: <memory-context>
```

### Step-by-step description

1. **Embedding model selection:**
   - Use `all-MiniLM-L6-v2` via sentence-transformers (384 dimensions, ~80MB model).
   - Alternatively, `all-MiniLM-L12-v2` for slightly better quality (same dimensions, ~120MB model).
   - Model loaded once at write time. At read time, loaded from disk cache.

2. **Write-time embedding:**
   - When a memory is created/updated, compute embedding of `title + " " + tags_joined + " " + body_text`.
   - Store the 384-dim float32 vector in `embeddings.bin` (a simple binary file: `{id_hash: vector}`).
   - Total storage: 600 entries x 384 dims x 4 bytes = ~921KB.

3. **Read-time retrieval:**
   - Load `embeddings.bin` into memory (fast -- under 1ms for 900KB).
   - Embed the user prompt using the same model.
   - Compute cosine similarity against all 600 vectors.
   - Return top-K nearest neighbors.

4. **FAISS integration (optional):**
   - At 600 entries, brute-force cosine similarity is fast enough (~5ms in numpy).
   - FAISS would only be needed if the dataset grew beyond ~5000 entries.
   - Could use `faiss.IndexFlatIP` (inner product on normalized vectors) for exact search.

5. **Cold start handling:**
   - First invocation after model download: ~2-5 seconds for model loading.
   - Subsequent invocations: ~200-500ms (model in OS disk cache).
   - If model loading exceeds 7 seconds, fall back to keyword search.

### Dependencies required
- `sentence-transformers` (which pulls in `torch`, `transformers`, `numpy`)
- `faiss-cpu` (optional, for large-scale indexing)
- Total: ~500MB-2GB additional disk space for model + torch
- Requires venv (like `memory_write.py` already does for pydantic)

### Implementation complexity
- **LOC:** ~150 new lines for embedding/search logic, ~50 lines for fallback.
- **Effort:** 3-5 days including venv setup and testing.
- **New files:** `embeddings.bin` (~1MB), model cache (~80-120MB).

### Expected performance
- **Precision:** Very high. Semantic similarity captures meaning, not just surface tokens.
- **Recall:** Excellent. "rate limiting" matches "throttling policy". "container build" matches "Dockerfile configuration".
- **Latency:** 200-500ms typical (model cached), 2-5 seconds cold start. Within timeout but with less headroom.

### Pros
1. True semantic understanding -- the most significant quality improvement possible.
2. No synonym table maintenance -- embeddings capture semantic relationships automatically.
3. Robust to paraphrasing, abbreviations, and terminology variation.
4. Industry-proven approach (ChromaDB, Pinecone, etc. all use this pattern).

### Cons
1. Massive dependency footprint (~500MB-2GB for torch + model). Violates the "stdlib-only" constraint.
2. Cold start latency (2-5s) consumes most of the 10-second timeout budget.
3. Model drift risk -- different model versions may change similarity scores.
4. Opaque scoring -- harder to audit why a particular memory was or was not retrieved.
5. Requires venv management for the retrieval script (currently only write scripts use venv).
6. GPU not available in typical Claude Code environments; CPU inference is slower.

### Integration plan
1. Extend venv bootstrap to support retrieval script (currently only write/validate scripts).
2. Add embedding computation to `memory_write.py` create/update flow.
3. Create `memory_embed.py` for batch embedding (initial migration, rebuild).
4. Modify `memory_retrieve.py` to load embeddings and compute similarity.
5. Add fallback to keyword search when model loading fails or times out.
6. Add `embeddings.bin` management to `memory_index.py --rebuild`.

### Risk assessment
- **Medium-high risk.** The dependency footprint is the biggest concern. torch installation fails on some platforms. The cold start problem means the first retrieval after a system restart may fall back to keyword search. Model loading time is the primary latency bottleneck.

---

## Alternative 3: LLM-as-Judge Retrieval

### One-line summary
Use a fast LLM (Claude Haiku or Gemini Flash) to rerank keyword-retrieved candidates, combining deterministic pre-filtering with intelligent relevance judgment.

### Architecture

```
                           READ TIME (Hook)
                    ============================

  stdin: {user_prompt, cwd}
           |
           v
  +-------------------+
  | Pass 1: Keyword   |    (current system, broadened)
  | Pre-filter         |
  | top 15 candidates  |
  +-------------------+
           |
           v
  +-------------------+
  | Build Rerank      |    Compact: title + tags + 1-line gist
  | Payload           |    (~100 tokens per candidate)
  | (~1500 tokens)    |
  +-------------------+
           |
           v
  +-------------------+
  | LLM API Call      |    urllib.request (stdlib)
  | Claude Haiku /    |    socket timeout: 3 seconds
  | Gemini Flash      |    "Given this prompt, rank these
  |                   |     memories by relevance. Return
  |                   |     JSON: [id1, id2, id3, ...]"
  +-------------------+
           |
           |--- timeout/error ---> fallback to keyword ranking
           |
           v
  +-------------------+
  | Reorder by LLM    |
  | judgment           |
  +-------------------+
           |
           v
  top max_inject results
           |
           v
  stdout: <memory-context>
```

### Step-by-step description

1. **Pass 1 -- Broadened keyword pre-filter:**
   - Run the current keyword scoring but with a wider net: return top 15 candidates (not top 5).
   - Goal: high recall, acceptable precision. Let the LLM handle precision.

2. **Build rerank payload:**
   - For each of the 15 candidates, construct a compact representation:
     ```
     [1] "Use pydantic v2 for validation" #tags:pydantic,validation,schema (DECISION, 2026-02-15)
     [2] "Fix WSL path resolution in hooks" #tags:wsl,hooks,path (RUNBOOK, 2026-02-18)
     ...
     ```
   - Total: ~100 tokens per candidate = ~1500 tokens payload.

3. **LLM API call via stdlib urllib:**
   - Use `urllib.request` (stdlib) to call Claude Haiku or Gemini Flash API.
   - API key read from environment variable or config file.
   - Socket timeout: 3 seconds (leaves 7 seconds for keyword pre-filter + response parsing).
   - Prompt: "User asked: '{user_prompt}'. Which of these memories are most relevant? Return a JSON array of IDs ordered by relevance, max 5."
   - Parse JSON response to get ordered list of IDs.

4. **Fallback:**
   - If the LLM call fails (timeout, API error, invalid response), fall back to keyword ranking.
   - The system degrades gracefully to the current behavior.

5. **Gist generation (write-time):**
   - Add a `gist` field to memory JSON: a one-sentence summary (<200 chars) generated at write time.
   - This makes the rerank payload more informative without reading full body content.

### Dependencies required
- **stdlib only** for the HTTP call (`urllib.request`).
- **External service:** Claude Haiku or Gemini Flash API (requires API key and network access).
- Optional: `gist` field generation at write time (uses the writing LLM, no new deps).

### Implementation complexity
- **LOC:** ~120 new lines for LLM call + payload construction + fallback, ~30 lines for gist generation at write time.
- **Effort:** 2-3 days.
- **New files:** None (modifications to existing scripts).

### Expected performance
- **Precision:** Excellent. LLM understands semantic relevance, context, intent.
- **Recall:** Limited by keyword pre-filter (Pass 1 must surface the candidate for the LLM to see it).
- **Latency:** 500ms-3000ms (keyword pre-filter ~100ms + LLM call ~400-2500ms). Unpredictable.

### Pros
1. Best possible relevance judgment -- LLM understands meaning, intent, and context.
2. Stdlib-only for the client code (urllib.request).
3. Graceful fallback -- degrades to keyword search on any failure.
4. No local model to maintain, no embeddings to store.
5. Can leverage the LLM's understanding of technical concepts without a synonym table.

### Cons
1. **Network dependency** -- fails entirely in offline environments.
2. **Latency unpredictability** -- LLM response times vary (200ms to 3000ms+).
3. **Cost** -- every user prompt triggers an API call (~1500 input tokens + ~50 output tokens per prompt).
4. **API key management** -- requires secure storage and rotation.
5. **Recall ceiling** -- limited by keyword pre-filter. If the relevant memory does not surface in the top 15 keyword candidates, the LLM never sees it.
6. **Privacy concern** -- user prompts and memory titles are sent to an external API.
7. **Rate limiting** -- high-frequency prompts could hit API rate limits.

### Integration plan
1. Add `gist` field to memory JSON schema (optional field, generated at write time).
2. Add gist generation to `memory_write.py` create/update flow.
3. Add LLM rerank function to `memory_retrieve.py` with urllib-based API call.
4. Add API key configuration to `memory-config.json`.
5. Add timeout and fallback logic.
6. Add config toggle: `retrieval.llm_rerank.enabled` (default false).

### Risk assessment
- **Medium risk.** The network dependency and cost are the primary concerns. The 3-second socket timeout means the hook could use up to 3.5 seconds on the LLM call alone, leaving limited headroom. API key management adds operational complexity. Privacy-conscious users may refuse to send memory titles to external APIs.

---

## Alternative 4: Hybrid Keyword + Lightweight Embeddings (TF-IDF Vectors)

### One-line summary
Combine keyword scoring with TF-IDF vector cosine similarity for semantic-like matching, using only stdlib Python and pre-computed sparse vectors -- no deep learning, no external dependencies.

### Architecture

```
              WRITE TIME                                READ TIME (Hook)
       =======================                   =========================

  memory_write.py                                stdin: {user_prompt, cwd}
       |                                                  |
       v                                                  v
  [JSON memory file]                             tokenize + stem(prompt)
       |                                                  |
       v                                                  v
  compute_tfidf_vector()                         load vectors.json + vocab.json
  for title+tags+body                            (~600 sparse vecs, ~200KB)
       |                                                  |
       v                                                  v
  store in vectors.json:                         +------------------+
    {id: {term: tfidf_weight}}                   | Dual Scoring     |
    (sparse representation)                      |                  |
       |                                         | keyword_score    |
       v                                         |   (current algo  |
  update vocab.json:                             |    + stemming)   |
    {term: idf_weight}                           |                  |
    doc_count: N                                 | vector_score     |
                                                 |   (cosine sim    |
                                                 |    of TF-IDF     |
                                                 |    vectors)      |
                                                 +------------------+
                                                          |
                                                          v
                                                 Reciprocal Rank Fusion:
                                                 score = a/rank_kw + b/rank_vec
                                                          |
                                                          v
                                                 top max_inject results
                                                          |
                                                          v
                                                 stdout: <memory-context>
```

### Step-by-step description

1. **Write-time TF-IDF vector computation:**
   - For each memory, tokenize `title + tags + body_text` with stemming.
   - Compute term frequency (TF) for each token in the document.
   - Compute inverse document frequency (IDF) from the global corpus.
   - Store sparse TF-IDF vector: `{token: tfidf_weight}` (only non-zero entries).
   - Maintain `vocab.json`: `{token: idf_weight, "_meta": {doc_count, avg_doc_len}}`.

2. **Read-time dual scoring:**
   - **Keyword score:** Enhanced version of current scoring (with stemming, body tokens, etc.).
   - **Vector score:** Compute TF-IDF vector for the prompt, then cosine similarity against all 600 stored vectors.
   - Cosine similarity in pure Python with sparse vectors:
     ```python
     def cosine_sim(v1: dict, v2: dict) -> float:
         shared_keys = set(v1) & set(v2)
         dot = sum(v1[k] * v2[k] for k in shared_keys)
         norm1 = sum(v ** 2 for v in v1.values()) ** 0.5
         norm2 = sum(v ** 2 for v in v2.values()) ** 0.5
         return dot / (norm1 * norm2) if norm1 and norm2 else 0.0
     ```

3. **Reciprocal Rank Fusion (RRF):**
   - Rank entries independently by keyword score and vector score.
   - Combine using RRF: `final_score = alpha / (k + rank_keyword) + beta / (k + rank_vector)`
   - Parameters: `k=60` (standard RRF constant), `alpha=1.0`, `beta=0.8`.
   - This naturally handles the "keyword finds exact matches, vectors find semantic matches" duality.

4. **Sparse vector optimization:**
   - Only store terms with TF-IDF > threshold (e.g., 0.01) to keep vectors compact.
   - Typical memory entry: 20-50 non-zero terms.
   - Total `vectors.json` size: ~600 entries x ~40 terms x ~20 bytes = ~480KB.
   - Load time: <50ms.

### Dependencies required
- **None** -- pure stdlib Python. TF-IDF is arithmetic on term frequencies. Cosine similarity is dot products.

### Implementation complexity
- **LOC:** ~180 new lines for TF-IDF computation + cosine similarity + RRF, ~60 lines in write path.
- **Effort:** 3-4 days.
- **New files:** `vectors.json` (~200-500KB), `vocab.json` (~50KB).

### Expected performance
- **Precision:** Good. Keyword scoring handles exact matches. TF-IDF vectors add a "soft match" signal that catches related terms.
- **Recall:** Significantly improved over pure keyword. TF-IDF vectors capture term co-occurrence patterns (entries about "database" and "migration" will have similar vector profiles).
- **Latency:** ~100-300ms. Sparse vector cosine similarity for 600 entries is fast.

### Pros
1. Zero external dependencies -- pure stdlib Python math.
2. Combines the strengths of keyword matching (precision for exact terms) with vector similarity (recall for related terms).
3. RRF is a proven fusion technique that does not require weight tuning.
4. Sparse vectors are compact and fast to compute.
5. Body content is naturally included in the TF-IDF vector without modifying the index format.
6. Deterministic -- same input always produces same output.

### Cons
1. TF-IDF vectors are "bags of words" -- they do not capture word order or phrase semantics. "rate limiting" and "limiting rate" have identical vectors.
2. No true synonym understanding -- "throttling" and "rate limiting" will not have similar vectors unless they co-occur with similar terms.
3. Sparse vector storage grows linearly with vocabulary size and entry count.
4. `vectors.json` is another derived artifact that can become stale.
5. Cosine similarity on sparse vectors in pure Python is slower than numpy (but still fast enough for 600 entries).
6. TF-IDF quality degrades with very small corpora (<50 entries) where IDF statistics are unreliable.

### Integration plan
1. Add stemmer (shared with Alternative 1).
2. Add TF-IDF vector computation to `memory_write.py`.
3. Add `vocab.json` and `vectors.json` generation to `memory_index.py --rebuild`.
4. Add cosine similarity + RRF to `memory_retrieve.py`.
5. Add config: `retrieval.match_strategy: "hybrid_tfidf"` to enable.

### Risk assessment
- **Low risk.** The approach is mathematically well-understood and has no external dependencies. The worst case is that TF-IDF vectors add noise to the ranking, which RRF mitigates (keyword ranking still dominates for exact matches). The derived artifacts (`vectors.json`, `vocab.json`) follow the same pattern as `index.md` and can be rebuilt.

---

## Alternative 5: Progressive Disclosure + Smart Index

### One-line summary
Restructure the retrieval architecture around a multi-layer progressive disclosure pattern with an inverted index, tiered output (gist vs. full content), token budgeting, and smart index structures -- inspired by claude-mem's 3-layer pattern.

### Architecture

```
              WRITE TIME                                READ TIME (Hook)
       =======================                   ===================================

  memory_write.py                                stdin: {user_prompt, cwd}
       |                                                  |
       v                                                  v
  [JSON memory file]                             tokenize + stem(prompt)
       |                                                  |
       +------+------+                                    v
       |      |      |                           +-------------------+
       v      v      v                           | Inverted Index    |
  inverted   gist   index.md                     | Lookup            |
  _index     _store  (unchanged)                 | O(1) per term     |
  .json      .json                               | {term -> [ids]}   |
       |      |      |                           +-------------------+
       v      v      v                                    |
                                                          v
  inverted_index.json:                           Candidate set (union of
    {"auth": ["id1","id5"],                       term postings lists)
     "deploy": ["id2","id3"], ...}                        |
                                                          v
  gist_store.json:                               +-------------------+
    {"id1": {"gist": "...",                      | Score + Tier      |
             "token_cost": 45},                  | Assignment        |
     "id2": {...}, ...}                          +-------------------+
                                                          |
                                                  +-------+-------+
                                                  |               |
                                                  v               v
                                           Tier 1: FULL     Tier 2: GIST
                                           (score > high)   (score > low)
                                           Read JSON body   Use gist from
                                           ~500 tokens ea   gist_store.json
                                                             ~50 tokens ea
                                                  |               |
                                                  +-------+-------+
                                                          |
                                                          v
                                                 Token Budget Check:
                                                 total <= max_tokens
                                                 (default 2000)
                                                          |
                                                          v
                                                 stdout: <memory-context>
                                                   Full entries first,
                                                   then gist summaries,
                                                   then "also relevant:"
                                                   title-only list
```

### Step-by-step description

1. **Inverted index construction (write-time):**
   - Build `inverted_index.json`: maps each stemmed token to a list of memory IDs that contain it.
   - Includes tokens from title, tags, and body content.
   - Updated incrementally on create/update/retire.
   - Rebuilt fully during `memory_index.py --rebuild`.
   - Lookup is O(1) per query term instead of O(N) linear scan.

2. **Gist store (write-time):**
   - Generate a one-sentence gist (< 200 chars) for each memory at write time.
   - Store in `gist_store.json`: `{id: {gist, token_cost, category, updated_at}}`.
   - Gist is the LLM-generated summary of the memory's key content.
   - Token cost is an estimate of the full body's token count.

3. **Three-tier output:**
   - **Tier 1 (Full content):** Score > high threshold. Read full JSON body. ~500-1000 tokens per entry.
   - **Tier 2 (Gist):** Score > low threshold but below Tier 1. Show gist from `gist_store.json`. ~50-100 tokens per entry.
   - **Tier 3 (Title-only):** Score > minimum threshold. Show only `[CATEGORY] title #tags`. ~20 tokens per entry.
   - The LLM consuming the context can decide which gist entries are worth fetching via a follow-up.

4. **Token budgeting:**
   - Configure `retrieval.max_tokens: 2000` (default).
   - Fill the budget greedily: Tier 1 entries first, then Tier 2, then Tier 3.
   - Estimate tokens per entry from `gist_store.json` metadata.
   - This maximizes information density per context token.

5. **Output format enhancement:**
   ```xml
   <memory-context source=".claude/memory/" budget="2000/2000 tokens">
     <full-entries>
       <entry category="RUNBOOK" title="Fix WSL path resolution" path="..." score="12">
         trigger: WSL paths resolve differently...
         steps: 1. Check if running under WSL...
       </entry>
     </full-entries>
     <gist-entries>
       <entry category="DECISION" title="Use pydantic v2"
              gist="Chose pydantic v2 over attrs for memory validation due to JSON schema generation."
              score="8" />
     </gist-entries>
     <also-relevant>
       - [CONSTRAINT] Python stdlib only for hooks
       - [TECH_DEBT] Index rebuild performance
     </also-relevant>
   </memory-context>
   ```

### Dependencies required
- **None** -- pure stdlib Python.
- Gist generation requires the writing LLM (already available at write time via SKILL.md orchestration).

### Implementation complexity
- **LOC:** ~250 new lines for inverted index, gist store, tiered output, token budgeting.
- **Effort:** 4-6 days.
- **New files:** `inverted_index.json` (~50-100KB), `gist_store.json` (~60-120KB).

### Expected performance
- **Precision:** Moderate improvement. Inverted index does not change scoring quality, but tiered output ensures the LLM sees more candidates with less token waste.
- **Recall:** Significantly improved. Inverted index includes body tokens. More candidates shown (gist tier) within the same token budget.
- **Latency:** ~30-100ms. Inverted index lookup is O(query_terms), not O(entries). Fastest of all alternatives.
- **Information density:** ~3-5x more memories surfaced per token compared to current system.

### Pros
1. Zero external dependencies -- pure stdlib Python.
2. Dramatically better information-per-token ratio (the LLM sees 15-20 potentially relevant memories instead of 5).
3. Inverted index is the fastest possible lookup structure for keyword search.
4. Token budgeting prevents context overflow while maximizing utility.
5. The architecture naturally supports future scoring improvements (swap scoring algorithm independently).
6. Gist tier lets the LLM make informed decisions about which memories to explore further.

### Cons
1. More complex architecture with more derived artifacts to maintain.
2. Gist generation adds complexity to the write path (LLM must generate a good one-sentence summary).
3. Tiered output format changes the XML structure that Claude expects (may need SKILL.md updates).
4. Inverted index + gist store + index.md = three derived artifacts that can drift.
5. Does not solve the semantic gap -- still keyword-based scoring within the inverted index.
6. Token cost estimation is approximate (no tiktoken dependency).

### Integration plan
1. Add gist field generation to `memory_write.py` / SKILL.md write orchestration.
2. Add inverted index construction to `memory_index.py --rebuild` and incremental updates in write path.
3. Modify `memory_retrieve.py` for inverted index lookup, tiered scoring, token budgeting.
4. Update output format with tiered XML structure.
5. Add `retrieval.max_tokens` and tier thresholds to config.
6. Update SKILL.md to document the new output format.

### Risk assessment
- **Medium risk.** The architecture is more complex, with three derived artifacts instead of one. Gist quality depends on the writing LLM's summarization ability. The tiered output format change may affect how Claude interprets the injected context (needs testing with real prompts). However, each component is independently testable and the fallback path (flat output) is trivial.

---

## Alternative 6: Graph-Based Concept Retrieval

### One-line summary
Build a concept co-occurrence graph from memory entries, then use spreading activation to expand query terms through learned project-specific semantic relationships.

### Architecture

```
              WRITE TIME                                READ TIME (Hook)
       =======================                   ===================================

  memory_write.py                                stdin: {user_prompt, cwd}
       |                                                  |
       v                                                  v
  [JSON memory file]                             tokenize + stem(prompt)
       |                                         = "active nodes"
       v                                                  |
  extract concepts                                        v
  (title, tags, body                             +--------------------+
   key terms)                                    | Load concept       |
       |                                         | graph.json         |
       v                                         +--------------------+
  update concept_graph.json:                              |
    {"auth": {                                            v
       "jwt": 8,                                 +--------------------+
       "token": 6,                               | Spreading          |
       "login": 5,                               | Activation         |
       "middleware": 3},                          | (2 hops max)       |
     "deploy": {                                 +--------------------+
       "docker": 7,                                       |
       "ci": 4,                                  active: {auth}
       "kubernetes": 3},                         hop 1:  {jwt: 0.8, token: 0.6,
     ...}                                                 login: 0.5, middleware: 0.3}
       |                                         hop 2:  {bearer: 0.3, session: 0.2}
       v                                                  |
  update memory_concepts.json:                            v
    {"id1": ["auth","jwt","middleware"],          +--------------------+
     "id2": ["deploy","docker","ci"],            | Expanded Query     |
     ...}                                        | = original terms   |
                                                 |   + activated      |
                                                 |   concepts         |
                                                 +--------------------+
                                                          |
                                                          v
                                                 Score entries using
                                                 expanded query terms
                                                 (keyword match with
                                                  activation weights)
                                                          |
                                                          v
                                                 top max_inject results
                                                          |
                                                          v
                                                 stdout: <memory-context>
```

### Step-by-step description

1. **Concept extraction (write-time):**
   - For each memory, extract key concepts from title, tags, and body.
   - Concepts are stemmed tokens that appear in the entry (deduplicated).
   - Store per-entry concept list in `memory_concepts.json`.

2. **Graph construction (write-time, incremental):**
   - For every pair of concepts that co-occur in the same memory entry, increment the edge weight.
   - `concept_graph.json` is an adjacency list: `{concept: {neighbor: weight, ...}}`.
   - Normalize edge weights by the maximum weight to get values in [0, 1].
   - Example: if `auth` and `jwt` co-occur in 8 memories, the edge weight is 8 (normalized to ~0.8).

3. **Spreading activation (read-time):**
   - Start with prompt tokens as "active nodes" with activation 1.0.
   - **Hop 1:** For each active node, look up neighbors in the graph. Each neighbor receives `activation * edge_weight * decay` (decay = 0.5).
   - **Hop 2:** For each newly activated node, spread again with `decay^2 = 0.25`.
   - Stop after 2 hops (diminishing returns, keeps it fast).
   - Result: an expanded set of concepts with activation weights.

4. **Expanded query scoring:**
   - Score each memory entry using the expanded concept set.
   - Original prompt terms: weight 1.0 (standard keyword scoring).
   - Hop-1 activated concepts: weight 0.5 (partial credit for related concepts).
   - Hop-2 activated concepts: weight 0.25 (weak boost for distantly related concepts).
   - This effectively performs query expansion using the project's own semantic relationships.

5. **Graph maintenance:**
   - Incremental: on memory create/update, add edges for new concept pairs, increment existing edges.
   - On memory retire/archive, decrement edges (but do not remove -- old relationships may still be valid).
   - Full rebuild: recompute from all active memories during `memory_index.py --rebuild`.

### Dependencies required
- **None** -- pure stdlib Python. The graph is a dictionary of dictionaries.

### Implementation complexity
- **LOC:** ~200 new lines for graph construction + spreading activation + expanded query scoring.
- **Effort:** 3-5 days.
- **New files:** `concept_graph.json` (~20-100KB), `memory_concepts.json` (~30KB).

### Expected performance
- **Precision:** Moderate. Graph-based expansion can introduce noise (distantly related concepts may not be relevant). The 2-hop limit and decay factor mitigate this.
- **Recall:** Significantly improved for domain-specific relationships. If your project consistently pairs `auth` with `jwt`, querying for `auth` will automatically boost `jwt`-related memories even if the user did not mention `jwt`.
- **Latency:** ~80-200ms. Graph lookup is O(degree) per active node. With 2 hops and typical degree ~10, this is ~200 operations.

### Pros
1. Zero external dependencies -- pure stdlib Python.
2. Learns project-specific semantic relationships from the data itself (not a generic synonym table).
3. Automatically adapts as new memories are added -- the graph evolves with the project.
4. Captures relationships that no pre-built synonym table or embedding model would know (e.g., in this project, `hook` is strongly related to `triage` and `retrieval`).
5. Query expansion is transparent and auditable (can log which concepts were activated and why).
6. Synergistic with keyword scoring -- it enhances the query, not the scoring algorithm.

### Cons
1. Requires sufficient data to build meaningful relationships (~30+ memories before the graph is useful).
2. Concept co-occurrence is a crude proxy for semantic relatedness. Co-occurrence does not imply relevance (e.g., `import` and `json` co-occur frequently but the relationship is trivial).
3. Graph can become noisy with high-frequency "hub" concepts that connect everything.
4. Spreading activation can amplify irrelevant concepts if the graph has strong but misleading edges.
5. Two more derived artifacts to maintain and keep in sync.
6. Cold start problem: with <20 memories, the graph is too sparse to be useful.

### Integration plan
1. Add concept extraction to `memory_write.py` create/update flow.
2. Add graph construction to `memory_index.py --rebuild` and incremental updates.
3. Add spreading activation to `memory_retrieve.py` as a query expansion step before scoring.
4. Add graph pruning (remove edges below threshold weight) to prevent noise.
5. Add config: `retrieval.graph_expansion.enabled`, `retrieval.graph_expansion.max_hops`, `retrieval.graph_expansion.decay`.

### Risk assessment
- **Medium risk.** The primary risk is noise from weak or misleading graph edges. Hub concepts (like `python` or `config`) may activate too many unrelated concepts. Mitigation: edge weight thresholding (only follow edges with weight >= 3), hub penalty (reduce activation strength for high-degree nodes), and the decay factor. The cold start problem means this alternative provides no value for new installations until enough memories are accumulated.

---

## Alternative 7 (Bonus): Quantized Static Word Vectors

### One-line summary
Ship a compact, quantized set of static word vectors (GloVe-derived, 50 dimensions, 10K vocabulary, int8 quantized) as a binary asset, enabling "poor man's embeddings" with cosine similarity in pure Python.

### Architecture

```
              ASSET (shipped with plugin)           READ TIME (Hook)
       ====================================   ===================================

  vocab.bin:                                   stdin: {user_prompt, cwd}
    10,000 words x 50 dims x 1 byte                    |
    = 500KB binary file                                 v
    (GloVe 6B 50d, filtered to top 10K,       tokenize(prompt)
     quantized int8: [-127, 127])                       |
                                                        v
              WRITE TIME                       +-------------------+
       =======================                 | Load vocab.bin    |
                                               | (500KB, <10ms)    |
  memory_write.py                              +-------------------+
       |                                                |
       v                                                v
  [JSON memory file]                           compute mean_vector(prompt)
       |                                       = average of word vectors
       v                                       for all prompt tokens
  compute mean_vector(                                  |
    title + tags + body)                                v
       |                                       +-------------------+
       v                                       | Load vectors.idx  |
  store in vectors.idx:                        | (600 x 50 bytes   |
    {id: base64(50 int8 values)}               |  = 30KB)          |
    (~50 bytes per entry)                      +-------------------+
                                                        |
                                                        v
                                               cosine_sim(prompt_vec,
                                                 each entry_vec)
                                               600 x 50 int multiplies
                                               = 30,000 ops (~1ms)
                                                        |
                                                        v
                                               Rank Fusion with keyword score
                                                        |
                                                        v
                                               top max_inject results
                                                        |
                                                        v
                                               stdout: <memory-context>
```

### Step-by-step description

1. **Asset preparation (one-time, offline):**
   - Download GloVe 6B 50d embeddings (822MB uncompressed).
   - Filter to top 10,000 most common English words + ~500 technical terms (programming, DevOps, etc.).
   - Quantize float32 vectors to int8: `int8_val = round(float_val * 127 / max_abs_val)`.
   - Store as binary: 10,000 x 50 = 500,000 bytes (500KB).
   - Ship as `assets/vocab.bin` with the plugin.

2. **Write-time vector computation:**
   - Tokenize memory `title + tags + body`.
   - Look up each token in vocab.bin. Skip tokens not in vocabulary (OOV).
   - Compute mean vector: element-wise average of all matching word vectors.
   - Store the 50-byte int8 vector in `vectors.idx` (a compact JSON or binary file).

3. **Read-time similarity search:**
   - Load `vocab.bin` (500KB, <10ms).
   - Load `vectors.idx` (30KB for 600 entries, <1ms).
   - Compute mean vector for the prompt.
   - Compute cosine similarity (dot product of int8 vectors) against all 600 entry vectors.
   - Performance: 600 x 50 = 30,000 integer multiplications. Under 1ms in Python.

4. **Rank fusion with keyword score:**
   - Same RRF approach as Alternative 4, but using static word vectors instead of TF-IDF vectors.
   - `final_score = alpha / (k + rank_keyword) + beta / (k + rank_vector)`

### Dependencies required
- **None at runtime** -- pure stdlib Python. The vocab.bin is a shipped asset.
- **One-time offline dependency:** Script to generate vocab.bin from GloVe (numpy for quantization, but only at build time).

### Implementation complexity
- **LOC:** ~120 lines for vector loading + similarity computation + RRF.
- **Effort:** 2-3 days (plus one-time asset generation).
- **New files:** `assets/vocab.bin` (~500KB), `vectors.idx` (~30KB).

### Expected performance
- **Precision:** Moderate. Static word vectors capture broad semantic relationships but miss domain-specific nuances and multi-word phrases.
- **Recall:** Good. "database" and "SQL" will have similar vectors. "deploy" and "deployment" will be close. Basic synonym matching works.
- **Latency:** ~15-50ms total. Extremely fast -- binary file loads + integer arithmetic.

### Pros
1. True semantic similarity with zero runtime dependencies.
2. Incredibly fast -- integer arithmetic on 50-dimensional vectors.
3. The 500KB binary asset is small enough to ship with the plugin.
4. No model loading, no cold start, no GPU needed.
5. Captures broad semantic relationships (synonyms, related concepts).
6. Deterministic -- same vectors always produce same similarities.

### Cons
1. Static word vectors do not understand phrases or word order ("rate limiting" = "limiting rate").
2. 50 dimensions is low quality compared to transformer embeddings (384-768 dims).
3. OOV (out-of-vocabulary) problem: technical jargon, project-specific terms, acronyms will not have vectors.
4. The 10K vocabulary will miss many programming terms. Expanding the vocabulary increases the asset size.
5. Mean-of-vectors is a crude sentence representation -- loses information about which words actually co-occur.
6. Requires a one-time offline build step to generate vocab.bin (not fully self-contained).
7. The 500KB asset is small but non-trivial for a plugin that currently has zero binary assets.

### Integration plan
1. Build vocab.bin offline (one-time, include build script in `tools/`).
2. Add vector computation to `memory_write.py` create/update flow.
3. Add `vectors.idx` generation to `memory_index.py --rebuild`.
4. Add vector loading and cosine similarity to `memory_retrieve.py`.
5. Add RRF fusion with keyword score.

### Risk assessment
- **Low-medium risk.** The approach is simple and fast, with well-understood limitations. The main risk is that the 50-dimensional int8 vectors may not capture enough nuance for technical content. The OOV problem is the most likely source of retrieval failures. Mitigation: graceful fallback to keyword scoring when no vectors are available for query terms.

---

## Comparison Table

| Dimension | Alt 1: Enhanced Keyword | Alt 2: Local Embeddings | Alt 3: LLM-as-Judge | Alt 4: Hybrid TF-IDF | Alt 5: Progressive Disclosure | Alt 6: Concept Graph | Alt 7: Static Vectors |
|---|---|---|---|---|---|---|---|
| **Dependencies** | None (stdlib) | sentence-transformers, torch (~1GB) | None (stdlib urllib) + API key | None (stdlib) | None (stdlib) | None (stdlib) | None (stdlib) + 500KB asset |
| **Latency (typical)** | 60-250ms | 200-500ms (warm), 2-5s (cold) | 500-3000ms (network) | 100-300ms | 30-100ms | 80-200ms | 15-50ms |
| **Latency (worst)** | 400ms | 5-8s (cold start) | 10s (timeout) | 500ms | 200ms | 400ms | 100ms |
| **Precision** | High (exact) | Very High (semantic) | Excellent (LLM judgment) | Good (hybrid) | Moderate (same scoring + tiers) | Moderate (expansion noise) | Moderate (coarse vectors) |
| **Recall** | Moderate+ (stemming + body) | Excellent (semantic) | Limited by pre-filter | Significantly improved | Significantly improved (body index + more shown) | Significantly improved (expansion) | Good (broad synonyms) |
| **Semantic understanding** | None (keyword + synonyms) | Full (dense embeddings) | Full (LLM reasoning) | Partial (term overlap) | None (keyword) | Partial (co-occurrence) | Partial (word-level) |
| **Offline capability** | Full | Full | None (requires API) | Full | Full | Full | Full |
| **New derived artifacts** | 1 (stats.json) | 1 (embeddings.bin) | 0 | 2 (vectors.json, vocab.json) | 2 (inverted_index.json, gist_store.json) | 2 (concept_graph.json, memory_concepts.json) | 1 (vectors.idx) |
| **Shipped assets** | 0 | 0 (downloaded) | 0 | 0 | 0 | 0 | 1 (vocab.bin, 500KB) |
| **Impl complexity (LOC)** | ~320 | ~200 | ~150 | ~240 | ~250 | ~200 | ~120 |
| **Impl effort (days)** | 2-3 | 3-5 | 2-3 | 3-4 | 4-6 | 3-5 | 2-3 |
| **Cold start** | None | 2-5s model load | None | None | None | Needs ~30+ memories | None |
| **Body content indexed** | Yes (fingerprints) | Yes (full embedding) | Partial (gist in payload) | Yes (TF-IDF vectors) | Yes (inverted index) | Yes (concept extraction) | Yes (mean vector) |
| **Auditable** | Fully | Partially (opaque vectors) | Partially (LLM reasoning) | Partially | Fully | Fully (graph is inspectable) | Partially |
| **Privacy** | Full (local) | Full (local) | Reduced (API sends data) | Full (local) | Full (local) | Full (local) | Full (local) |

---

## Recommended Ranking

### Tier 1: Recommended for Implementation

**1st: Alternative 1 (Enhanced Keyword) -- Best overall value**
- Rationale: Highest impact-to-effort ratio. Zero new dependencies, fully incremental, addresses the top 3 weaknesses (no body indexing, no stemming, no IDF weighting) with proven algorithms. Can be deployed feature-by-feature. Forms the foundation that other alternatives build upon.
- When: Immediately. This should be the first improvement shipped.

**2nd: Alternative 5 (Progressive Disclosure) -- Best architecture improvement**
- Rationale: The tiered output pattern is the most impactful architectural change. Showing 15-20 memories (as gists) within the same token budget as 5 full memories means the LLM has dramatically more information to work with. The inverted index is a strict speed improvement. Can be combined with Alternative 1's scoring improvements.
- When: After Alternative 1 is stable. The tiered output format change requires SKILL.md updates and testing with real Claude sessions.

### Tier 2: Strong Candidates for Phase 2

**3rd: Alternative 6 (Concept Graph) -- Best "learned semantics" approach**
- Rationale: The only alternative that learns project-specific semantic relationships from the data itself. A manually maintained synonym table (in Alt 1) will always be incomplete; the concept graph adapts automatically. Combines well with Alt 1 + Alt 5 as a query expansion layer.
- When: After 50+ memories are accumulated. Not useful for new installations.

**4th: Alternative 4 (Hybrid TF-IDF) -- Solid middle ground**
- Rationale: Brings genuine vector similarity without any dependencies. RRF fusion is elegant and well-proven. However, TF-IDF vectors in a small corpus (600 entries) have limited discriminative power, and the approach overlaps heavily with Alt 1 (both use IDF, stemming, body indexing).
- When: Consider if Alt 1 alone does not provide sufficient recall improvement.

### Tier 3: Specialized / High-Risk

**5th: Alternative 7 (Static Vectors) -- Best for lightweight semantic search**
- Rationale: Clever approach that provides genuine word-level semantic similarity with no runtime dependencies. The 500KB asset is acceptable. However, the OOV problem is significant for technical content, and 50-dimensional int8 vectors provide only coarse similarity. Better suited as a scoring signal within Alt 1 than as a standalone approach.
- When: Consider as an optional enhancement to Alt 1 if synonym table maintenance becomes burdensome.

**6th: Alternative 3 (LLM-as-Judge) -- Best quality, worst practicality**
- Rationale: Produces the best relevance judgments by far (an LLM understanding context beats any keyword/vector approach). However, the network dependency, cost, latency unpredictability, and privacy concerns make it unsuitable as the primary retrieval mechanism. Better suited as an optional "premium" mode behind a feature flag.
- When: Only if a user explicitly opts in and provides an API key. Never as default.

**7th: Alternative 2 (Local Embeddings) -- Best quality but impractical**
- Rationale: True semantic search quality is unmatched. However, the ~1GB dependency footprint, cold start latency (2-5s consuming half the timeout), and the requirement to extend venv to the retrieval script make this disproportionately complex for a plugin. The quality gain over Alt 4 + Alt 6 + Alt 7 combined does not justify the operational cost.
- When: Only if the plugin evolves into a standalone service (like claude-mem) rather than a hook-based plugin.

---

## Best Choice For...

### Minimal dependencies (zero new deps, stdlib only)
**Alternative 1: Enhanced Keyword.** Zero dependencies, zero new binary assets, incremental deployment. Every feature (stemming, BM25, body fingerprints) works independently.

### Best retrieval quality
**Alternative 1 + 5 + 6 combined.** Enhanced keyword scoring (Alt 1) provides the precision floor. Progressive disclosure (Alt 5) maximizes information density. Concept graph (Alt 6) adds learned semantic expansion. Together they cover exact matches, body content, tiered output, and project-specific semantic relationships -- all in pure stdlib Python.

### Fastest to implement
**Alternative 1: Enhanced Keyword.** 2-3 days for the core features (stemmer, body fingerprints, BM25). Each feature is a standalone function with clear test cases. The stemmer alone (1 day) provides the single biggest recall improvement.

### Best single "bang for the buck" feature
**Body content fingerprints** (from Alternative 1). Adding `#body:token1,token2,...,token15` to index lines solves the "relevant body, generic title" problem that the internal synthesis document identifies as weakness 4.3. It requires ~40 lines of code in the write path and ~10 lines in the scoring path.

---

## Recommended Implementation Roadmap

```
Phase 1 (Week 1):  Alternative 1 core
                    - Stemmer function
                    - Body fingerprints in index lines
                    - BM25 scoring with IDF stats
                    - Intent-based category boosting
                    - Synonym micro-table (50 entries)
                    - Tests for all new functions

Phase 2 (Week 2):  Alternative 5 core
                    - Inverted index construction
                    - Gist field generation at write time
                    - Tiered output (full/gist/title-only)
                    - Token budgeting
                    - Tests for tiered output

Phase 3 (Week 3+): Alternative 6 (when data permits)
                    - Concept extraction at write time
                    - Graph construction and maintenance
                    - Spreading activation query expansion
                    - Graph pruning and hub penalty
                    - Integration tests with real memory data

Optional:           Alternative 7 as scoring signal
                    - vocab.bin generation (offline)
                    - Vector scoring as additional RRF input
                    - Useful for reducing synonym table maintenance
```

---

## Appendix: Gemini 3 Pro Creative Ideas (Summary)

Key creative ideas from the Gemini brainstorm session that influenced this document:

1. **"Significant Terms Fingerprint"** -- Index the top-N most discriminative body terms by TF-IDF, not just any body terms. This filters out noise tokens that appear in every document.

2. **"Bag of GloVe" with int8 quantization** -- Ship pre-quantized word vectors as a binary asset. 50 dimensions x int8 = 50 bytes per entry. Cosine similarity in pure Python is 30,000 integer multiplications for 600 entries (~1ms).

3. **"Anti-Memories" (negative indexing)** -- Track which memories are frequently retrieved but not useful (e.g., via future feedback mechanism). Add "not relevant for: [terms]" annotations to reduce false positives. (Not included in the main alternatives but worth noting for future work.)

4. **"Spreading Activation" on tag co-occurrence** -- The concept graph approach (Alternative 6) was directly inspired by this idea. The key insight: use the project's own data to learn that `auth` implies `jwt` in this specific codebase.

5. **"Context Window Arbitrage"** -- The tiered output approach (Alternative 5) maximizes useful information per token. Show 20 gists for the token cost of 2 full entries. The consuming LLM is smart enough to extract value from compressed summaries.

6. **"600 is small data"** -- The fundamental insight that enables pure-Python implementations of algorithms that normally require compiled libraries. O(N^2) with N=600 is 360,000 operations -- trivial for modern CPUs even in interpreted Python.
