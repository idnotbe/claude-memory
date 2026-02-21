# Verification Round 1 -- Feasibility Analysis

**Reviewer:** Claude Opus 4.6 (verification agent)
**Date:** 2026-02-20
**Cross-checked with:** Gemini 3 Pro Preview (via PAL clink)
**Inputs reviewed:**
- `/home/idnotbe/projects/claude-memory/temp/retrieval-alternatives.md` (7 alternatives)
- `/home/idnotbe/projects/claude-memory/temp/review-practical.md` (practical review)
- `/home/idnotbe/projects/claude-memory/CLAUDE.md` (architectural constraints)
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py` (current implementation, 399 LOC)
- `/home/idnotbe/projects/claude-memory/hooks/hooks.json` (hook configuration)
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_index.py` (index management)

---

## Hard Constraints (applied to every alternative)

| Constraint | Value | Source |
|---|---|---|
| Hook type | UserPromptSubmit (command type) | hooks.json |
| Hook timeout | **10 seconds** | hooks.json line 51 |
| Hook input | `{user_prompt, cwd}` on stdin (JSON) | memory_retrieve.py L211-219 |
| Core dependency rule | **stdlib-only** for retrieval script | CLAUDE.md Key Files table |
| Max entries | ~600 (6 categories x 100) | retrieval-alternatives.md |
| Runtime | `python3` (system default, no venv activation) | hooks.json command field |
| Output | stdout text injected into Claude context | memory_retrieve.py L385-394 |
| Exit code | Must exit 0 even on failure/no results | memory_retrieve.py (all early exits are sys.exit(0)) |
| Plugin environment | Cannot modify Claude Code hook protocol | CLAUDE.md |
| Write path | memory_write.py with flock-based index locking | CLAUDE.md, memory_write.py |

**Critical observation:** The retrieval hook runs as `python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_retrieve.py"` -- this is the system Python, NOT the plugin venv. Unlike `memory_write.py` which has a venv bootstrap (`os.execv` to `.venv/bin/python3`), the retrieval script has no such mechanism. Any alternative that requires non-stdlib dependencies would need to add a similar venv bootstrap to `memory_retrieve.py`, which itself consumes ~50-200ms and adds code complexity.

---

## Alternative 1: Enhanced Keyword (BM25 + Stemming + Body Indexing)

### Feasibility Score: 9/10

### Can it be implemented within the architecture?
**YES.** Every component is pure Python arithmetic and string operations. BM25 is `math.log()` + basic algebra. The S-stemmer is suffix stripping. Body fingerprints extend the existing index.md line format. stats.json is a new sidecar file following the same pattern as index.md. All read-side changes stay within `memory_retrieve.py`; all write-side changes stay within `memory_write.py` and `memory_index.py`.

### Will it stay under the 10-second timeout?
**YES, with massive headroom.** For 600 entries:
- Loading `stats.json` (~5-20KB): <5ms
- Stemming prompt tokens: <1ms
- BM25 scoring against index entries: <10ms (600 entries, arithmetic on small structures)
- Pass 2 JSON deep-check for top 20: ~50-200ms (same as current)
- **Total: ~60-250ms.** The 60-250ms claim in the proposal is realistic. Gemini 3 Pro confirms sub-millisecond for the BM25 math portion.

### Are dependency requirements realistic?
**YES. Zero new dependencies.** Everything is `math.log()`, `collections.Counter`, `json.load()`, and string operations. This is the proposal's strongest practical advantage.

### Are performance claims realistic?
**Mostly YES.**
- Precision improvement: Realistic. BM25 IDF naturally promotes rare terms, which is the single highest-impact scoring change.
- Recall improvement: Realistic for body fingerprints and stemming. The synonym table's recall improvement is overstated -- 50 entries will cover a tiny fraction of paraphrase space.
- Latency: Realistic. The bottleneck remains the Pass 2 JSON I/O, which is unchanged.

### Is migration viable?
**YES, fully backward compatible.** The key insight is that all new artifacts (`stats.json`, `#body:` suffix on index lines) are additive. Existing installations without these artifacts can degrade gracefully to the current keyword scoring. The `memory_index.py --rebuild` command can generate all new artifacts from existing JSON files.

### Hidden costs or complexities
1. **Synonym table maintenance** (flagged by practical review): The 50-entry table is small enough to ship once, but it will rot without a maintenance owner. The practical review's suggestion to replace it with character n-gram matching is sound and reduces this cost to zero.
2. **stats.json staleness:** If `memory_write.py` fails to update stats.json during a CUD operation (e.g., interrupted mid-write), the IDF weights become stale. Mitigation: stats.json is cheap to recompute from index.md (it is a derived artifact), and stale IDF still produces reasonable (not wrong) results.
3. **Index format change:** Adding `#body:token1,...,token15` to index lines means any code that parses `_INDEX_RE` must be updated. Currently, `memory_retrieve.py` and `memory_candidate.py` both parse index lines. The regex must be extended to capture the optional `#body:` suffix. This is ~5 LOC per file but easy to miss.
4. **Stemmer false positives:** "testing" -> "test" matching "test" tags is a real concern. The practical review's suggestion of a small blocklist (10-20 words) is the cheapest mitigation.

### Could it break existing functionality?
**Low risk.** If the `#body:` suffix or `stats.json` parsing fails, the system falls back to the current scoring (title + tags only). The existing `_INDEX_RE` regex does not match `#body:` (it only captures `#tags:`), so adding `#body:` would be ignored by old code -- the body tokens would be silently included in the title match group or dropped. This needs careful regex design to avoid regression.

### Realistic timeline estimate
**3-4 days** (not 2-3 as claimed). Breakdown:
- Day 1: Stemmer + BM25 scoring in memory_retrieve.py + unit tests
- Day 2: Body fingerprint extraction in memory_write.py + stats.json generation in memory_index.py
- Day 3: Index format extension (#body:), regex updates, integration tests
- Day 4: Intent-based category boosting + synonym table (or n-gram matching) + edge case testing

### Recommended modifications
1. **Replace synonym table with character trigram matching** (per practical review). Eliminates maintenance burden.
2. **Add stemmer blocklist** for known false positives (10-20 words).
3. **Design `#body:` suffix carefully** to be backward-compatible with existing `_INDEX_RE` regex. Consider a separate line or field rather than appending to the existing format.
4. **Make BM25 the default but keep the current scoring as a fallback** via `retrieval.match_strategy` config.

---

## Alternative 2: Local Embedding Vector Search

### Feasibility Score: 1/10

### Can it be implemented within the architecture?
**NO -- violates the stdlib-only constraint.** The retrieval hook runs under system Python without venv activation. sentence-transformers requires torch (~2GB), numpy, scipy, transformers, and huggingface-hub. Even if a venv bootstrap were added to `memory_retrieve.py` (like `memory_write.py` has for pydantic), the dependency stack is 100-1000x heavier than pydantic.

### Will it stay under the 10-second timeout?
**UNRELIABLE.** Cold start (torch import + model loading): 2-5 seconds on fast hardware, 5-8 seconds on slower hardware (WSL2 with I/O overhead, older laptops). The plugin targets WSL2 (per OS Version in environment), which is the worst case for disk I/O. Warm path (200-500ms) is acceptable but the cold start is the problem.

Gemini 3 Pro assessment: "HARD FAIL. Even if you forced a venv, torch is ~2GB and takes 2-5s to import (cold start), often consuming the entire 10s budget on slower disks."

### Are dependency requirements realistic?
**NO.** For a Claude Code plugin that currently ships as ~10KB of Python scripts, adding 500MB-2GB of dependencies is disproportionate. Cross-platform wheel availability is the support nightmare:
- ARM Linux: wheels often missing
- Alpine Linux (musl): no wheels
- macOS ARM: may conflict with system Python
- Windows ARM64: unsupported

### Show-stoppers
1. **Violates stdlib-only constraint** -- this is a hard architectural rule, not a preference.
2. **Cold start latency consumes 20-80% of the timeout budget.**
3. **2GB dependency footprint** for a ~10KB plugin.
4. **Cross-platform ONNX/torch wheel availability** generates unresolvable support burden.

### Realistic timeline estimate
**7-10 days** if attempted (not 3-5). Venv bootstrap extension, model download mechanism, embedding versioning, fallback path, cross-platform testing.

### Recommended modifications
**Defer entirely to a future version (v6.0+)** when the plugin has a proper installation/update mechanism. If semantic search is needed now, use Alternative 7 (static word vectors) as a lightweight substitute.

---

## Alternative 3: LLM-as-Judge Retrieval

### Feasibility Score: 3/10

### Can it be implemented within the architecture?
**PARTIALLY.** The stdlib `urllib.request` can make HTTP calls. The hook receives `user_prompt` on stdin. The pre-filter + rerank architecture is sound in theory. However, there are structural problems:

1. **No guaranteed network access.** The hook runs in the user's environment. Corporate proxies, firewalls, air-gapped networks, and offline development all break this.
2. **No guaranteed API key.** The hook has no interactive UI to prompt for configuration. If the key is missing or invalid, the system fails silently.
3. **The hook is synchronous and blocking.** While urllib waits for the API response, the entire 10-second timeout budget is consumed. There is no way to do the API call asynchronously within the hook.

### Will it stay under the 10-second timeout?
**UNRELIABLE.** Typical API latency for Claude Haiku: 500-2000ms. For Gemini Flash: 200-1000ms. But:
- Network stalls: 3-10 seconds (TCP retransmit timers)
- Cold TCP connection: +100-500ms (DNS + TLS handshake)
- API overload / rate limiting: 2-30 seconds
- With a 3-second socket timeout, the total budget is: ~100ms (keyword) + 3000ms (API) + ~100ms (parsing) = ~3.2 seconds typical, 10+ seconds worst case.

Gemini 3 Pro: "If the network stalls, the 10s timeout kills the process, resulting in *no memories* being retrieved."

### Are dependency requirements realistic?
**YES for the client code** (urllib.request is stdlib). **NO for the operational requirements** (API key management, network access, cost monitoring).

### Show-stoppers
1. **Network dependency makes it fail completely in offline/restricted environments.**
2. **Cost: every user prompt triggers an API call** (~1500 input + ~50 output tokens). At $0.25/MTok input for Haiku, 100 prompts/day = ~$0.04/day. Low individually but adds up and is a philosophical change (a free plugin now has marginal cost).
3. **Privacy: user prompts and memory titles are sent to an external API.** Many users (especially corporate) will refuse this.
4. **Recall is ceiling-limited by the keyword pre-filter.** If the relevant memory is not in the top 15 keyword results, the LLM never sees it. This means the semantic quality of the LLM judge is bottlenecked by the keyword system's recall.

### Hidden costs
- API key rotation and security (storing keys in config files is a security risk)
- Rate limiting handling (what happens when the user hits the API rate limit?)
- Error reporting (how does the user know the reranking failed vs. simply returned different results?)
- The fallback path is the *entire current system*, meaning you maintain two complete retrieval paths

### Realistic timeline estimate
**4-5 days** (not 2-3). API call + error handling + timeout management + config + fallback logic + testing across network conditions.

### Recommended modifications
1. **Never make this the default.** Only enable via explicit opt-in: `retrieval.llm_rerank.enabled: true`.
2. **Implement as a scoring signal, not a gatekeeper.** Use the LLM judgment to re-weight keyword scores (multiplier), not to replace them.
3. **Consider using the existing Claude Code session's API key** (if accessible via environment) rather than requiring a separate key. (Need to verify if `$ANTHROPIC_API_KEY` is available in the hook environment.)

---

## Alternative 4: Hybrid Keyword + TF-IDF Vectors

### Feasibility Score: 8/10

### Can it be implemented within the architecture?
**YES.** All components are pure Python arithmetic:
- TF-IDF computation: `math.log()`, `collections.Counter`, dictionary operations
- Cosine similarity on sparse vectors: dot product of two dicts (shared keys), normalization with `math.sqrt()`
- RRF fusion: simple arithmetic on rank positions

### Will it stay under the 10-second timeout?
**YES.** For 600 entries with sparse vectors (average ~40 non-zero terms each):
- Loading `vectors.json` (~200-500KB): <50ms
- Computing prompt TF-IDF vector: <1ms
- 600 cosine similarity computations in pure Python: ~20-50ms (sparse intersection on small dicts)
- RRF fusion: <1ms
- **Total: ~100-300ms.** The claim is realistic.

Gemini 3 Pro confirms: "Sparse dot product in pure Python is fast. 600 docs * ~1000 vocab size (sparse). Very fast."

### Are dependency requirements realistic?
**YES. Zero new dependencies.** Pure `math` and `dict` operations.

### Are performance claims realistic?
**Partially.**
- Latency: Realistic.
- Precision improvement: Modest. TF-IDF vectors are bags of words -- they add a "soft match" signal but do not understand phrases or context.
- Recall improvement: The claim that TF-IDF captures "term co-occurrence patterns" is **overstated**. TF-IDF vectors capture term presence, not co-occurrence. Two entries about "database" and "migration" will have similar vectors only if they share many of the same terms, not because the concepts are related. The real recall improvement comes from including body content in the vectors (which the current system does not index).

### Is migration viable?
**YES.** `vectors.json` and `vocab.json` are new derived artifacts. Existing installations without them degrade to keyword-only scoring. `memory_index.py --rebuild` can generate them from existing JSON files.

### Hidden costs or complexities
1. **vectors.json size at scale.** With 600 entries and ~40 terms each, `vectors.json` is ~480KB of JSON. JSON parsing of 480KB takes ~30-50ms in Python. This is acceptable but not negligible.
2. **TF-IDF quality with small corpora.** With <50 entries, IDF statistics are unreliable. A term appearing in 2 of 10 documents has IDF = log(10/2) = 1.6. A term appearing in 2 of 500 documents has IDF = log(500/2) = 5.5. The discriminative power of IDF improves with corpus size. For new installations, TF-IDF vectors add noise rather than signal.
3. **Heavy overlap with Alternative 1.** Both use IDF weighting, stemming, and body content. The difference is that Alt 1 uses BM25 (term-level scoring) while Alt 4 uses cosine similarity (document-level scoring). BM25 is generally considered superior for information retrieval. The RRF fusion adds value but the marginal improvement over Alt 1 alone may not justify the additional complexity (two scoring systems, two derived artifacts).
4. **Vocabulary management.** `vocab.json` must contain every term ever seen in any memory. As memories are created and retired, the vocabulary grows monotonically. Periodic pruning (removing terms from retired/archived entries) adds complexity to `memory_index.py --rebuild`.

### Could it break existing functionality?
**No.** All changes are additive. Fallback to keyword-only if `vectors.json` is missing.

### Realistic timeline estimate
**4-5 days** (not 3-4). Breakdown:
- Day 1: TF-IDF vector computation in memory_write.py + vocab.json management
- Day 2: Cosine similarity in memory_retrieve.py + RRF fusion
- Day 3: Integration with memory_index.py --rebuild + vocabulary pruning
- Day 4-5: Testing, edge cases (empty corpus, single entry, very long documents), performance benchmarking

### Recommended modifications
1. **Implement as an add-on to Alternative 1, not standalone.** Alt 1 provides the BM25 scoring foundation; Alt 4 adds the vector similarity signal via RRF. This is how the comparison table positions it: "Consider if Alt 1 alone does not provide sufficient recall improvement."
2. **Use a binary format for vectors** (Python `struct` + write to `.bin` file) instead of JSON to reduce load time from ~50ms to ~10ms.
3. **Add a minimum corpus size check.** If <30 entries, skip TF-IDF scoring and use keyword-only.

---

## Alternative 5: Progressive Disclosure + Smart Index

### Feasibility Score: 8/10

### Can it be implemented within the architecture?
**YES.** This is primarily an output format change + an inverted index data structure. Both are pure Python. The inverted index is a `dict[str, list[str]]` stored as JSON. The tiered output is string formatting. Token budgeting is arithmetic.

**However, there is a subtlety.** The gist generation at write time depends on the LLM that is doing the writing. The SKILL.md orchestration uses Task subagents for memory drafting. Adding a gist requirement means the subagent must generate a one-sentence summary, which is a SKILL.md change, not a Python change. This couples the retrieval improvement to the write orchestration.

### Will it stay under the 10-second timeout?
**YES, with the fastest latency of all alternatives.**
- Inverted index lookup: O(query_terms) with O(1) per term = <1ms for typical prompts
- Scoring within candidate set: same as current (~10-50ms for the candidate set, which is smaller than the full 600 entries)
- Token budgeting and tier assignment: <1ms
- **Total: ~30-100ms.** The claim is realistic for the hook itself.

**Caveat (from practical review):** The user-perceived latency may increase if Claude decides to make Read tool calls for entries shown as gists. Each Read call adds ~1-2 seconds. This is outside the hook's control but is a real UX concern.

### Are dependency requirements realistic?
**YES. Zero new dependencies.**

### Are performance claims realistic?
**Precision: claim is modest and accurate.** The inverted index does not change scoring quality -- it changes lookup speed (which was already fast enough at 600 entries).

**Recall: claim is accurate.** The inverted index includes body content tokens, and the tiered output shows more candidates (15-20 as gists vs. 5 as full entries) within the same token budget. The "3-5x more memories surfaced per token" claim is directionally correct.

**Information density: this is the real value.** Showing 5 full entries + 10 gists + 5 title-only entries gives the LLM dramatically more information than 5 full entries alone.

### Is migration viable?
**YES, with one caveat.** The output format change (tiered XML instead of flat list) changes what Claude sees. If existing SKILL.md instructions or user workflows depend on the specific output format, this could cause confusion. The mitigation is a config toggle (`retrieval.output_mode: "tiered" | "flat"`).

The inverted index and gist store are new derived artifacts that `memory_index.py --rebuild` can generate. No data migration needed.

### Hidden costs or complexities
1. **Gist quality is LLM-dependent.** If the write-time LLM generates a poor gist ("This memory is about stuff"), the tiered output is degraded. There is no automated quality check for gists.
2. **Three derived artifacts** (inverted_index.json, gist_store.json, index.md) that must stay in sync. Any write operation must update all three atomically. The current flock-based locking covers index.md; extending it to three files increases lock contention and complexity.
3. **Token cost estimation without tiktoken.** The proposal estimates token counts heuristically (e.g., chars / 4). This is imprecise -- a 200-character gist might be 40 or 80 tokens depending on vocabulary. The budget arithmetic may over- or under-allocate.
4. **Claude's behavior with tiered output is unpredictable.** The proposal assumes Claude will read the tiered format intelligently (prioritizing full entries, scanning gists, noting title-only entries). This depends on Claude's instruction-following for injected context, which varies across model versions.

### Could it break existing functionality?
**Potentially, if the output format change is not behind a config flag.** Any tooling or user expectations about the `<memory-context>` XML format would break. The safe path is to default to the current flat output and offer tiered output as opt-in.

### Realistic timeline estimate
**5-7 days** (not 4-6). Breakdown:
- Day 1: Inverted index construction in memory_index.py + incremental updates in memory_write.py
- Day 2: Gist field generation (SKILL.md changes + gist_store.json management)
- Day 3: Tiered output formatting in memory_retrieve.py + token budgeting
- Day 4: Config integration (output_mode toggle, tier thresholds, max_tokens)
- Day 5-6: Testing (inverted index correctness, gist quality, tiered output parsing, budget edge cases)
- Day 7: SKILL.md updates for the new output format + documentation

### Recommended modifications
1. **Decouple inverted index from gist store.** Implement the inverted index first (pure speed improvement + body content indexing) without gists. Add gists as a separate phase.
2. **Default to flat output** with tiered output as opt-in via `retrieval.output_mode: "tiered"`.
3. **Use simple heuristic for token estimation** (chars / 4, rounded up) and document the imprecision.
4. **Keep index.md as the canonical human-readable index.** inverted_index.json and gist_store.json are machine-readable caches, rebuildable from JSON files.

---

## Alternative 6: Graph-Based Concept Retrieval

### Feasibility Score: 6/10

### Can it be implemented within the architecture?
**YES.** The graph is `dict[str, dict[str, float]]` stored as JSON. Spreading activation is BFS with decay. All pure Python.

### Will it stay under the 10-second timeout?
**YES.** For a graph with ~500 concept nodes (derived from 600 entries) and average degree ~10:
- Load concept_graph.json (~20-100KB): <10ms
- Spreading activation (2 hops): ~500 nodes * 10 neighbors * 2 hops = ~10,000 operations. <5ms in Python.
- Expanded query scoring: same as current keyword scoring but with more query terms. <50ms.
- **Total: ~80-200ms.** The claim is realistic.

**Worst case:** If the graph becomes very dense (every concept connected to many others), spreading activation visits more nodes. With 500 nodes all connected to 50 neighbors: 500 * 50 * 2 = 50,000 operations. Still <50ms in pure Python. Well under budget.

### Are dependency requirements realistic?
**YES. Zero new dependencies.** The graph is a dictionary of dictionaries.

### Are performance claims realistic?
**Recall improvement: realistic but conditional.** The graph learns project-specific relationships (e.g., `auth` -> `jwt` in this codebase). This is genuinely useful for projects with rich, consistent tagging. However:
- With <30 memories, the graph is too sparse to learn meaningful relationships (acknowledged in the proposal).
- With poor tagging quality, the graph learns noise.

**Precision: overstated.** Spreading activation can amplify irrelevant concepts through hub nodes. The practical review identifies this as the critical unaddressed problem: a concept like `python` or `config` that appears in many memories becomes a "super-connector" that activates unrelated neighborhoods.

### Is migration viable?
**YES.** concept_graph.json and memory_concepts.json are new derived artifacts. Fallback to keyword-only if missing. `memory_index.py --rebuild` can generate them.

### Hidden costs or complexities
1. **Hub node problem (flagged by practical review, confirmed by Gemini).** High-degree nodes (common tags/concepts) spread activation energy into unrelated neighborhoods. Without dampening, a query about "python authentication" will activate everything tagged with "python" (which is everything). **This is not addressed in the proposal and is a show-stopper for naive implementation.** Mitigation: degree-based dampening (`energy / sqrt(degree)`), but this adds complexity and tuning parameters.
2. **Tuning hell.** The system has at least 4 tuning parameters:
   - Decay factor per hop (proposed 0.5)
   - Maximum hops (proposed 2)
   - Edge weight threshold (what minimum co-occurrence count to create an edge?)
   - Hub dampening factor
   Each parameter affects retrieval quality in non-obvious ways. There is no automated feedback loop to tune them.
3. **Graph staleness.** The graph must be updated on every memory create/update/retire. Incremental graph updates (add/remove edges for the changed entry) are conceptually simple but tricky to implement correctly when entries share many concepts.
4. **Cold start.** New installations with <20 memories have an effectively empty graph. The alternative provides zero value until sufficient memories are accumulated.
5. **Debugging difficulty.** "Why did memory X surface?" requires tracing activation flow through the graph. There is no visualization tool, and the activation trace is not human-readable.

### Could it break existing functionality?
**No, if implemented as a query expansion layer.** The graph expands the set of query terms before scoring. If the graph is empty or missing, scoring uses the original query terms (current behavior). The scoring algorithm itself is unchanged.

### Realistic timeline estimate
**5-7 days** (not 3-5). Breakdown:
- Day 1: Concept extraction from memory entries + concept_graph.json construction
- Day 2: Spreading activation algorithm + hub dampening
- Day 3: Expanded query scoring integration in memory_retrieve.py
- Day 4: Incremental graph updates in memory_write.py + rebuild in memory_index.py
- Day 5-6: Tuning (decay, hops, thresholds, dampening) + testing with synthetic data
- Day 7: Edge case testing (empty graph, hub nodes, very sparse graph)

### Recommended modifications
1. **Implement hub dampening from day one.** `propagated_energy = energy * edge_weight * decay / sqrt(node_degree)`. Non-negotiable.
2. **Use as a secondary signal only** (20-30% of final score). Never as the primary retrieval mechanism.
3. **Set minimum edge weight threshold** (co-occurrence count >= 3) to avoid noise from incidental co-occurrence.
4. **Add graph quality metrics** (average degree, max degree, clustering coefficient) to help diagnose degradation.
5. **Skip file reference extraction** (proposed in the concept extraction step). It is regex-fragile and not worth the false positives.

---

## Alternative 7: Quantized Static Word Vectors

### Feasibility Score: 7/10

### Can it be implemented within the architecture?
**YES.** Loading a binary file with `open(..., 'rb')` + `struct.unpack()` is stdlib. Cosine similarity on 50-dimensional int8 vectors is integer arithmetic. All pure Python.

Gemini 3 Pro confirms: "Load 500KB vocab.bin: open(..., 'rb') + struct.unpack (stdlib). Fast."

### Will it stay under the 10-second timeout?
**YES, with the best latency characteristics.**
- Loading vocab.bin (500KB): <10ms (binary read, no parsing)
- Loading vectors.idx (30KB for 600 entries): <5ms
- Computing mean vector for prompt: <1ms (average of ~10 word vectors)
- 600 cosine similarity computations (50-dim int8): 30,000 integer multiplications. <5ms in Python (even without numpy).
- RRF fusion: <1ms
- **Total: ~15-50ms.** The claim is realistic. This is the fastest alternative by a wide margin.

### Are dependency requirements realistic?
**YES at runtime (zero dependencies).** The vocab.bin is a shipped binary asset, loaded with stdlib `struct`.

**One-time build dependency:** Generating vocab.bin from GloVe requires numpy (for quantization). This is an offline step, not a runtime dependency. A build script in `tools/` handles this.

### Are performance claims realistic?
**Latency: realistic.** Binary loads + integer math is fast.

**Quality: overstated.** Mean-of-vectors (averaging word vectors for a document/query) is a crude sentence representation:
- Loses word order: "rate limiting" = "limiting rate"
- Loses compositionality: the meaning of "rate limiting" is not the average of "rate" and "limiting"
- OOV (out-of-vocabulary) problem: technical jargon, project-specific terms, acronyms will not have vectors. In a technical codebase, the majority of discriminative terms (e.g., "pydantic", "flock", "idnotbe") are OOV.
- 50 dimensions is very low quality compared to modern embeddings (384-768 dims)

Gemini 3 Pro: "Quality of 'averaged word vectors' is the main concern."

### Is migration viable?
**YES.** vectors.idx is a new derived artifact. vocab.bin is shipped with the plugin. No changes to existing data.

### Hidden costs or complexities
1. **OOV problem is severe for technical content.** A 10K-word GloVe vocabulary covers general English well but misses most programming terms. Examples of likely OOV: "pydantic", "pytest", "fastapi", "kubectl", "dockerfile", "webhook", "cron", "flock", "idempotent", "sharding". Expanding to 20K words helps but increases the asset to 1MB. Expanding to 50K words covers most technical terms but the asset becomes 2.5MB.
2. **The 500KB asset is a philosophical change.** The plugin currently ships zero binary assets. Adding a 500KB binary file (that users cannot inspect or understand) changes the plugin's character. Some users may object to opaque binary blobs.
3. **GloVe model selection and provenance.** Which GloVe model? 6B (trained on Wikipedia + Gigaword), 42B (trained on Common Crawl), or 840B? The 6B model is the smallest but has the weakest technical vocabulary. The 840B model has better coverage but is much larger to download and process.
4. **Mean vector quality degrades with short texts.** Memory titles are short (5-15 words). The mean vector of 5 words is highly sensitive to each individual word. One OOV word means 20% of the signal is lost.
5. **No way to update the vocabulary.** If the user's project introduces new technical terms (e.g., a custom library name), these terms will never have vectors. The vocabulary is frozen at build time.

### Could it break existing functionality?
**No.** All changes are additive. RRF fusion means keyword scoring still runs independently; the vector score is an additional signal.

### Realistic timeline estimate
**3-4 days** (not 2-3). Breakdown:
- Day 1: vocab.bin generation script (offline, numpy) + vector loading in memory_retrieve.py
- Day 2: Write-time mean vector computation in memory_write.py + vectors.idx management
- Day 3: Cosine similarity + RRF fusion in memory_retrieve.py + testing
- Day 4: OOV handling, edge cases (all-OOV query, empty vector), performance benchmarking

### Recommended modifications
1. **Expand vocabulary to 15-20K words** with explicit inclusion of ~500 programming/DevOps terms. Accept the 750KB-1MB asset size.
2. **Use as a secondary RRF signal** alongside Alt 1 (BM25), not as a standalone approach.
3. **Add OOV fallback:** If >50% of prompt tokens are OOV, skip vector scoring entirely and use keyword-only.
4. **Include the build script in `tools/build_vocab.py`** with documentation for how to regenerate with a different GloVe model.

---

## Cross-Source Consensus Matrix

| Alternative | My Score | Gemini 3 Pro Score | Practical Review Score | Consensus |
|---|---|---|---|---|
| Alt 1: Enhanced Keyword (BM25) | **9/10** | **10/10** | **8/10** | **STRONG CONSENSUS: IMPLEMENT** |
| Alt 2: Local Embeddings | **1/10** | **0/10** | **2/10** | **STRONG CONSENSUS: REJECT** |
| Alt 3: LLM-as-Judge | **3/10** | **3/10** | N/A (different numbering) | **CONSENSUS: REJECT AS DEFAULT** |
| Alt 4: Hybrid TF-IDF | **8/10** | **9/10** | N/A (different numbering) | **CONSENSUS: GOOD SECONDARY** |
| Alt 5: Progressive Disclosure | **8/10** | **10/10** | **7/10** (as Alt 4 in review) | **CONSENSUS: IMPLEMENT AS PHASE 2** |
| Alt 6: Concept Graph | **6/10** | **7/10** | **5/10** (as Alt 2 in review) | **CONSENSUS: DEFER (hub problem)** |
| Alt 7: Static Vectors | **7/10** | **8/10** | N/A (new proposal) | **CONSENSUS: VIABLE ADD-ON** |

### Key disagreements between sources:
1. **Alt 5 (Progressive Disclosure):** Gemini gives 10/10 (treating it as pure UX improvement), practical review gives 7/10 (flagging Claude behavior unpredictability and added latency from Read calls). I score 8/10 -- the inverted index is valuable, but gist generation and tiered output add complexity that Gemini underestimates.
2. **Alt 6 (Concept Graph):** Gemini gives 7/10, practical review gives 5/10 (flagging hub node problem and debugging difficulty). I score 6/10 -- feasible but the hub node problem is a real show-stopper that must be addressed before implementation.

---

## Show-Stoppers Summary

| Alternative | Show-Stopper | Severity | Mitigation |
|---|---|---|---|
| Alt 2 | Violates stdlib-only constraint | **Fatal** | None within current architecture |
| Alt 2 | Cold start latency (2-5s) on WSL2 | **Fatal** | None -- WSL2 is the target platform |
| Alt 3 | Network dependency (fails offline) | **Severe** | Fallback to keyword, but defeats the purpose |
| Alt 3 | Privacy concern (sends data to external API) | **Severe** | Cannot be mitigated; philosophical issue |
| Alt 6 | Hub node problem (unaddressed in proposal) | **Severe** | Add degree-based dampening (increases complexity) |
| Alt 5 | Claude behavior with tiered output is unpredictable | **Moderate** | Config toggle + testing across model versions |

---

## Recommended Implementation Order (Feasibility-Adjusted)

### Phase 1: Alternative 1 (BM25 + Stemming + Body Indexing)
- **Timeline:** 3-4 days
- **Risk:** Low
- **Value:** Highest impact-to-effort ratio
- **Modifications:** Replace synonym table with trigram matching. Add stemmer blocklist.

### Phase 2: Alternative 5 (Inverted Index + Tiered Output)
- **Timeline:** 5-7 days
- **Risk:** Medium (output format change, gist quality)
- **Value:** Best information density improvement
- **Modifications:** Decouple inverted index from gist store. Default to flat output. Implement inverted index first.

### Phase 3: Alternative 4 (TF-IDF Vector Scoring)
- **Timeline:** 4-5 days
- **Risk:** Low
- **Value:** Adds soft-match signal to BM25 scoring
- **Modifications:** Implement as RRF add-on to Phase 1. Binary format for vectors. Minimum corpus size check.

### Phase 4 (Optional): Alternative 7 (Static Word Vectors)
- **Timeline:** 3-4 days
- **Risk:** Low-medium (OOV problem)
- **Value:** Adds crude semantic similarity without model dependencies
- **Modifications:** Expand vocabulary to 15-20K. Use as secondary RRF signal. OOV fallback.

### Phase 5 (Conditional, after 50+ memories): Alternative 6 (Concept Graph)
- **Timeline:** 5-7 days
- **Risk:** Medium (hub nodes, tuning)
- **Value:** Learned project-specific semantic expansion
- **Modifications:** Hub dampening required. Secondary signal only (20-30%).

### Not Recommended: Alternative 2 (Local Embeddings), Alternative 3 (LLM-as-Judge)
- Alt 2: Infeasible within current architecture.
- Alt 3: Viable only as explicit opt-in premium feature, never as default.

---

## Total Implementation Budget

| Phase | Days | Cumulative LOC (approx) | Dependencies Added |
|---|---|---|---|
| Phase 1 (Alt 1) | 3-4 | +320 | 0 |
| Phase 2 (Alt 5) | 5-7 | +570 | 0 |
| Phase 3 (Alt 4) | 4-5 | +810 | 0 |
| Phase 4 (Alt 7) | 3-4 | +930 | 0 (500KB-1MB binary asset) |
| Phase 5 (Alt 6) | 5-7 | +1130 | 0 |
| **Total** | **20-27 days** | **~1130 new LOC** | **0 new Python deps** |

The full roadmap maintains the stdlib-only constraint throughout, adding approximately 1130 lines of new code across 5 phases. Each phase is independently valuable and testable. Phases 3-5 are optional and depend on whether earlier phases provide sufficient retrieval quality.

---

*Verification Round 1 complete. All feasibility scores cross-validated with Gemini 3 Pro Preview. Submitted for Round 2 review.*
