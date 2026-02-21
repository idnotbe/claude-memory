# Practical Engineering Review: Retrieval Alternatives

**Date:** 2026-02-20
**Reviewer:** Claude Opus 4.6 (practical engineering perspective)
**Cross-validated with:** Gemini 3 Pro Preview (independent assessment via PAL clink)
**Source document:** temp/retrieval-alternatives.md
**Reference implementation:** hooks/scripts/memory_retrieve.py (~399 LOC, stdlib-only)

---

## Evaluation Framework

Each alternative is evaluated on seven axes that matter in production:

| Axis | What It Measures |
|------|-----------------|
| Implementation cost | Realistic dev hours including testing, edge cases, and integration (not whiteboard estimates) |
| Runtime performance | Latency, memory footprint, cold/warm start behavior under the 10-second hook timeout |
| Dependency management | Packaging friction, cross-platform issues, version conflicts, install-time failures |
| Maintenance burden | 12-month cost of keeping it working as the codebase and data evolve |
| Integration friction | How much existing code must change, how many new failure surfaces are introduced |
| Operational concerns | Debuggability, failure modes, observability, recovery procedures |
| Migration path | Effort to move from the current system, backward compatibility, rollback safety |

**Scoring:** 1-10 on overall practicality (10 = deploy tomorrow with confidence, 1 = research project).

**Current system baseline:** The existing `memory_retrieve.py` is ~399 LOC of pure stdlib Python. It tokenizes the user prompt, scores index entries via exact word match (2pts), exact tag match (3pts), and prefix match (1pt), applies category description boosting, deep-checks the top 20 for recency/retired status, and outputs XML. Latency is ~50ms for 600 entries. It has zero semantic understanding but is rock-solid operationally.

---

## Alternative 1: BM25 + Inverted Index (Enhanced Keyword)

### Implementation Cost: 20-30 hours realistic

The proposal says "2-3 focused sessions" and ~250 LOC. That is the optimistic case for the core algorithm. Add realistic time for:

- **Inverted index builder** with correct handling of create/update/retire/archive lifecycle events (~4-6h). The index must be rebuilt atomically (partial writes corrupt retrieval). The current code already has `add_to_index`/`remove_from_index`/`update_index_entry` functions with flock-based locking; adding `index.inv.json` doubles the write-side surface area.
- **S-stemmer edge cases** (~2-3h). The 15-line stemmer is a good start, but it will produce incorrect stems that cause false matches or missed matches. "running" -> "runn" (wrong), "flies" does not match the `ies` rule if len < 5. Testing and tuning the stemmer for the actual corpus of technical terms is real work.
- **Synonym table curation** (~4-6h initial, then ongoing). 200 technical synonym groups is a substantial content effort. Examples: does "k8s" map to "kubernetes"? Does "db" map to "database"? Does "auth" map to both "authentication" and "authorization"? Every synonym pair is a judgment call.
- **BM25 parameter tuning** (~3-4h). The k1 and b parameters in BM25 need tuning for this specific corpus (short titles, few tags, limited body tokens). Default k1=1.2, b=0.75 may not work well for documents with average length of ~10 tokens.
- **Integration testing** against the existing test suite (~3-4h). The test files in `tests/` need new cases for BM25 scoring, stemming, and synonym expansion.

Total: 20-30 hours is realistic. Gemini agrees at 20-30h.

### Runtime Performance

- **Latency:** ~15ms for posting list lookup is credible. Loading `index.inv.json` (~200KB) from disk adds ~5-10ms on cold start. In practice, the hook process starts fresh each invocation (no persistent cache), so every call pays the JSON parse cost. Realistic: **20-30ms**, which is still excellent.
- **Memory:** ~200KB index in memory is negligible.
- **Write-time overhead:** Rebuilding the inverted index on every `memory_write.py` call adds ~50-100ms. Acceptable since writes are infrequent.

### Dependency Management

**None.** This is the strongest property. Zero new dependencies means zero new failure modes from packaging. The synonym table is a static JSON file, not a dependency.

### Maintenance Burden (12 months)

**Low.** The BM25 formula is stable (it has not changed in 30 years). The main maintenance items:
- Synonym table updates when users report "X doesn't match Y" (~1h/quarter)
- Stemmer corrections for domain-specific terms (~1h/quarter)
- Index format versioning if schema evolves

This is manageable. Gemini correctly identifies the synonym list as the only "living" part.

### Integration Friction

**Low.** The integration plan is clean:
1. `memory_write.py` gains a call to rebuild `index.inv.json` after CUD operations
2. `memory_retrieve.py` replaces `score_entry()` and `score_description()` with BM25 scorer
3. `index.md` remains for human readability (no breaking change)
4. Falls back to current keyword scoring if `index.inv.json` is missing

The existing `parse_index_line()`, `check_recency()`, `_sanitize_title()`, and the entire output format remain unchanged. The security properties (path containment, title sanitization, max_inject clamping) are unaffected.

### Operational Concerns

**Index drift** is the primary failure mode (Gemini flags this correctly). If `index.inv.json` gets out of sync with the actual JSON files, retrieval returns stale results. Mitigations:
- Rebuild on every write (same as `index.md` today)
- Add `--rebuild-inv` to `memory_index.py` for manual recovery
- Validate `index.inv.json` mtime against `index.md` mtime as a staleness check

**Debugging** is good. BM25 scores are decomposable: you can log which terms matched, their IDF weights, and field multipliers. This is strictly better than the current opaque integer scoring.

### Migration Path

**Trivial.** Build the new system alongside the old one. If `index.inv.json` exists, use BM25; otherwise, fall back to current scoring. Zero-downtime migration. Rollback = delete `index.inv.json`.

### Deal-Breakers

**None.**

### Practicality Score: 9/10

The boring, correct engineering choice. Proven algorithm, zero dependencies, clean integration, good debuggability. The only reason it is not 10/10 is the synonym table curation effort and the fact that it still cannot handle paraphrases.

**Gemini score: 9/10.** Full agreement.

---

## Alternative 2: Concept Graph with Spreading Activation

### Implementation Cost: 40-60 hours realistic

The proposal says "2-3 sessions" and ~300 LOC. This is significantly underestimated. The code is straightforward; the **tuning** is where time disappears:

- **Graph builder** (~8-10h). Edge construction from shared tags, file refs, temporal proximity, and same-category requires careful weight calibration. The file_ref extractor (regex-based path detection in body text) is inherently noisy -- paths like `./src/index.ts` vs `/home/user/src/index.ts` vs `src/index.ts` need normalization.
- **Spreading activation tuning** (~15-20h). This is where projects like this die. The decay factor (0.5), activation threshold (0.1), and number of iterations (2) are hyperparameters that interact non-linearly. Changing the decay from 0.5 to 0.4 can dramatically alter which nodes surface. You will spend weeks running experiments, looking at results, and asking "why did it return that?" Gemini estimates 40-60h and specifically calls out tuning as the time sink. Correct.
- **Hub node handling** (~4-6h). Common tags like "bug", "refactor", "api" create hub nodes that spread activation everywhere. You need a dampening strategy (e.g., IDF-weighted edge strengths, max fan-out limits). This is additional complexity not addressed in the proposal.
- **Testing** (~6-8h). Graph-based retrieval is hard to test because the expected results depend on the graph structure, which depends on all the memories. You need synthetic graph fixtures.

### Runtime Performance

- **Latency:** ~30ms for graph traversal with 600 nodes and sparse edges is plausible. The adjacency list lookup is O(degree) per node, and 2 iterations with a threshold cutoff limit the expansion.
- **Memory:** ~100KB graph JSON is fine.
- **Write-time overhead:** Full graph rebuild on every write is more expensive than inverted index rebuild because it requires comparing every pair of memories for shared tags/files. For 600 entries: 600*599/2 = ~180K pair comparisons. At even 0.01ms per comparison, that is ~1.8s. This may need optimization (incremental graph updates instead of full rebuild).

### Dependency Management

**None.** Pure stdlib. Same advantage as Alt 1.

### Maintenance Burden (12 months)

**High.** This is where the graph approach hurts:
- Weight tuning is never "done" -- as the corpus evolves, optimal weights shift
- "Why did it retrieve that?" debugging requires tracing activation paths through the graph, which is non-trivial
- File reference extraction regex needs updates as project structures change
- Hub node dampening requires ongoing attention as popular tags emerge

Gemini rates maintenance as High. I agree.

### Integration Friction

**Medium.** The graph adds a new data artifact (`graph.json`) and a new module (`graph_builder.py`). The write path must trigger graph rebuilds. The retrieval path gains a post-scoring spreading activation phase. The existing keyword scoring remains as the seed mechanism, so the change is additive rather than replacing.

However, the interaction between keyword seed scores and graph activation scores creates a combined scoring formula that is harder to reason about than either alone.

### Operational Concerns

**Hub explosion** is the critical failure mode. A memory tagged with 5 common tags connects to potentially dozens of other memories, spreading activation indiscriminately. When a user queries "fix the bug in authentication", the "bug" hub activates half the graph.

**Debugging opacity** is the second concern. When a user asks "why was this memory retrieved?", you need to explain: "It was retrieved because memory A matched your keywords, and memory A shares tags 'api' and 'auth' with memory B, and memory B was created within 1 hour of memory C, so activation propagated through A -> B -> C." This is not something you can log concisely.

**Graph corruption** from a failed write (crash mid-rebuild) leaves retrieval in a degraded state. The fallback to keyword-only is clean, but the user loses the graph benefit until the next successful rebuild.

### Migration Path

**Medium.** The graph must be built from scratch by analyzing all existing memories. This is a one-time batch operation that reads all JSON files, extracts tags/file refs/timestamps, and constructs the adjacency list. Takes ~5-10 seconds for 600 entries. Not difficult, but it is an additional install/upgrade step.

### Deal-Breakers

**No hard deal-breakers**, but the tuning burden is a soft deal-breaker for a small team. If you do not have time to iterate on activation parameters for 2-3 weeks, the graph will underperform a well-tuned BM25. The hub node problem is unaddressed in the proposal and will produce visibly wrong results for users with common tags.

### Practicality Score: 5/10

Interesting idea, but the tuning effort and debugging opacity are significant practical costs. The graph provides a genuinely different signal (structural relationships), but for 600 entries, the marginal improvement over BM25+synonyms is unlikely to justify the complexity.

**Gemini score: 6/10.** Close agreement; I am slightly more pessimistic due to the write-time rebuild cost.

---

## Alternative 3: Local Embedding + Cross-Encoder Re-ranking

### Implementation Cost: 60-80+ hours realistic

The proposal says "4-5 sessions" and ~400 LOC. The code is the easy part. The real cost:

- **Packaging and cross-platform testing** (~20-30h). Getting `onnxruntime` to work reliably on macOS ARM (M1/M2/M3), macOS Intel, Linux x86_64 (glibc), Linux ARM64, and WSL2 is a matrix of pain. Each platform may need a different wheel. `tokenizers` has Rust binaries that also vary by platform.
- **Model management** (~10-15h). Where do the 22MB model files live? How are they downloaded? What happens offline? What happens when the model version updates? This is infrastructure work.
- **Venv management** (~5-8h). The plugin already has one venv for pydantic. Adding onnxruntime/numpy/tokenizers to it (or creating a second venv) adds complexity to the bootstrap flow.
- **Cold start optimization** (~5-8h). ONNX model loading takes 1-2s on first call. The hook process dies after each invocation (no persistent cache). Every call to the retrieval hook pays this cost unless you implement a model server (which is a whole additional project).
- **Embedding migration** (~3-5h). Generating embeddings for 600 existing entries requires batch processing with proper error handling.

### Runtime Performance

- **Cold start: 1.5-2s.** This is the killer. The hook has a 10-second timeout, and spending 1.5-2s just loading the model leaves only 8s for everything else. In practice, users will perceive a delay on every prompt.
- **Warm start: ~300ms.** But there is no warm start -- the hook process is short-lived. Unless you implement a persistent model server or use `mmap` tricks, every invocation is cold.
- **Memory:** ONNX model in memory: ~100MB. For a CLI plugin, this is heavy.
- **The cross-encoder re-ranking** adds another ~800ms for 10 pairs. With the model loading overhead, this easily pushes total latency to 2-3s. The "optional" qualifier is essential -- in practice, you will always disable it.

### Dependency Management

**Severe.** This is the strongest negative signal:

- `onnxruntime` is a C++ library with Python bindings. It ships platform-specific wheels. On platforms without pre-built wheels (e.g., Linux ARM with musl libc), installation fails.
- `numpy` is generally available but can conflict with system numpy on some Linux distros.
- `tokenizers` is a Rust library with Python bindings. Same platform matrix issues as onnxruntime.
- Total additional disk: ~60MB of model files + ~50MB of wheels = ~110MB for a "memory plugin." This is disproportionate.
- The plugin currently works on any machine with Python 3.8+ and stdlib. This alternative requires a build toolchain for native extensions.

Gemini's assessment: "Operational suicide for a client-side plugin without a dedicated installer." Harsh but accurate.

### Maintenance Burden (12 months)

**Very High.**
- Every Python minor version bump (3.11 -> 3.12 -> 3.13) risks breaking onnxruntime wheel compatibility
- Every onnxruntime release may require re-testing the entire platform matrix
- Model updates require re-generating all embeddings
- Users will file issues about installation failures on unusual platforms

### Integration Friction

**High.** The retrieval hook must be restructured to:
1. Attempt to load ONNX model (with timeout/fallback)
2. Run dense retrieval in parallel with (or before) keyword retrieval
3. Implement RRF fusion
4. Handle the case where ONNX is unavailable gracefully

The write path must generate embeddings at write time, adding another dependency to `memory_write.py` (which already bootstraps a venv for pydantic).

### Operational Concerns

- **Segfaults** from native library issues are the #1 failure mode. Unlike Python exceptions, these produce no useful error message.
- **Silent degradation:** If the model fails to load, the system falls back to keyword-only, but the user has no indication that they are getting degraded retrieval.
- **Embedding drift:** If you update the ONNX model, old embeddings are incompatible. You must regenerate all embeddings, which requires all memory files to be accessible.

### Migration Path

**Hard.** Requires:
1. Installing onnxruntime + numpy + tokenizers in the plugin venv
2. Downloading model files (~40MB)
3. Generating embeddings for all existing memories (~30-60s for 600 entries)
4. Modifying both the write and retrieval paths

Rollback: delete embeddings.bin and embedding_meta.json, remove ONNX deps. The system falls back to keyword-only.

### Deal-Breakers

**YES: Two deal-breakers.**

1. **Violates the stdlib-only constraint** for hook scripts. This is a hard project constraint documented in CLAUDE.md. The retrieval hook (`UserPromptSubmit`) is specifically required to be stdlib-only.
2. **Cold start latency of 1.5-2s** on every prompt submission is a UX degradation that users will notice and complain about. There is no mitigation within the hook protocol (no persistent processes).

### Practicality Score: 2/10

The retrieval quality would be excellent, but the operational costs are prohibitive for a client-side plugin. This is the right architecture for a server-side system with a dedicated model server, persistent processes, and controlled deployment. It is the wrong architecture for a Claude Code plugin that runs on user machines.

**Gemini score: 2/10.** Full agreement. "Operational suicide" is apt.

---

## Alternative 4: Progressive Disclosure with LLM-Mediated Selection

### Implementation Cost: 10-15 hours realistic

The proposal says "1 session" and ~100 LOC. This is almost right:

- **Output format change** (~3-4h). Reformatting the output from full `<memory-context>` entries to compact `<memory-index>` entries with file paths is straightforward.
- **Instruction engineering** (~4-6h). The instruction block that tells Claude to Read relevant files needs careful iteration. "Use Read to load any that seem relevant" is vague. You need to test how different Claude models (Haiku, Sonnet, Opus) respond to the instruction.
- **Threshold lowering + config** (~2-3h). Adding `retrieval.mode: "progressive"` config flag and adjusting the scoring threshold.
- **Testing** (~2-3h). Testing output format changes against existing tests.

### Runtime Performance

The hook itself is fast (~40ms), but the **end-to-end latency** includes Claude's decision-making:
- Claude reads the compact index: ~0.5s (it is in the context, no tool call needed)
- Claude decides which entries to Read: ~1-2s (LLM inference time)
- Claude makes Read tool calls: ~0.5-1s per file (filesystem read + tool round-trip)
- If Claude reads 3-5 files: **total 2-6s additional latency** before responding to the user's actual question.

This is significant. The user asks a question and waits 3-8s longer than before because Claude is reading memory files. Gemini correctly identifies this as "UX latency" that makes the system "feel sluggish."

**Token cost:** ~200-300 tokens for the compact index (good). But reading 3-5 full memory JSON files adds ~500-2000 tokens each = ~1500-10000 tokens of context consumption. The net token savings depend on how many files Claude reads vs. the current max_inject of 5.

### Dependency Management

**None.** The change is entirely in what the hook outputs.

### Maintenance Burden (12 months)

**Medium**, but the risk profile is unusual:
- The code itself is trivial to maintain
- The **behavioral dependency on Claude's model** is the risk. If a future model update makes Claude less likely to follow the "Read these files" instruction, retrieval silently degrades. You cannot test for this in CI.
- Different Claude models (Haiku vs Opus) may behave differently with the instruction, requiring per-model tuning of the instruction text.

### Integration Friction

**Low** for the hook change itself. But there is a conceptual shift: the retrieval hook no longer provides complete context -- it provides a menu. This means:
- The SKILL.md orchestration must account for the possibility that Claude will (or will not) read memory files
- Other tools/hooks that assume memories are already in context will be wrong
- The user cannot see which memories were actually loaded (invisible intermediate step)

### Operational Concerns

- **Non-determinism** is the primary concern. The same prompt with the same memories may retrieve different content on different runs because Claude's selection varies. This makes debugging "why didn't it remember X?" extremely difficult.
- **Claude ignoring the instruction** is a real failure mode. If the compact index is injected but Claude proceeds to answer without reading any files, the user gets no memory context at all. Unlike the current system, which always injects content, Progressive Disclosure depends on Claude's cooperation.
- **Hallucination risk:** Claude sees titles like "Fix Docker build OOM error" and may fabricate the content instead of reading the file. This is especially likely with faster/smaller models.
- **Invisible to the user:** The current system prints `<memory-context>` which the user can see in the conversation. With Progressive Disclosure, the index is injected, but whether Claude reads the files is invisible.
- **API cost:** Read tool calls consume API tokens. For users on metered plans, this is a visible cost increase.

### Migration Path

**Trivial.** Change the output format of `memory_retrieve.py`. The existing scoring logic, index parsing, and security measures all remain. Add a config flag to switch between "inject" and "progressive" modes. Rollback = flip the config flag.

### Deal-Breakers

**No hard deal-breakers**, but two significant concerns:

1. **UX latency** (2-6s additional per prompt) is a meaningful degradation for a plugin that is supposed to be invisible. Users will feel the slowness.
2. **Behavioral dependency on Claude model** means retrieval quality is outside the plugin developer's control. A model regression silently breaks retrieval with no way to detect or fix it from the plugin side.

### Practicality Score: 6/10

The implementation is trivially easy, but the operational model is fragile. You are trading algorithmic complexity for behavioral unpredictability. For a personal-use plugin where you can tolerate variability, this is fine. For a plugin distributed to users who expect consistent behavior, the non-determinism and latency are real costs.

**Gemini score: 7/10.** Slight disagreement -- I am more pessimistic about the latency impact and non-determinism. Gemini underweights the "Claude ignoring the instruction" failure mode.

---

## Alternative 5: TF-IDF Cluster Routing with Intent Detection

### Implementation Cost: 30-40 hours realistic

The proposal says "3-4 sessions" and ~350 LOC. Realistic additions:

- **Pure-Python K-Means** (~10-12h). K-Means is conceptually simple but implementing it correctly in pure Python (convergence detection, empty cluster handling, initialization strategy) takes careful work. Without numpy, all vector operations are slow Python loops.
- **TF-IDF vectorizer** (~6-8h). Building the vocabulary, computing IDF weights, and vectorizing documents is straightforward but verbose in stdlib Python. Sparse vector representation using dicts is needed to keep memory reasonable.
- **Intent detector** (~4-6h). Pattern matching for intent keywords is easy. Tuning the category boost multipliers is another hyperparameter exercise.
- **Integration + testing** (~8-12h). The cluster routing adds a new retrieval path that must be tested with various query types and corpus shapes.

### Runtime Performance

- **Latency:** ~20ms for 20 centroid comparisons + within-cluster keyword scoring. Credible and fast.
- **Write-time cost:** Full re-clustering on every write is expensive. K-Means on 600 entries with ~100-dimensional TF-IDF vectors requires ~10-20 iterations, each computing 600 x 20 distances. In pure Python: ~2-5 seconds. This is too slow for every write. You need incremental assignment (assign new entry to nearest cluster) with periodic full re-clustering.
- **Memory:** ~50KB for cluster data. Negligible.

### Dependency Management

**None.** Pure stdlib. But the pure-Python K-Means will be noticeably slower than a numpy-based implementation, which creates pressure to add numpy as a dependency later.

### Maintenance Burden (12 months)

**High.** Cluster-based systems require ongoing attention:
- Cluster quality degrades as entries are added/removed unevenly (cluster drift)
- K=20 may need adjustment as the corpus grows (K=20 for 600 entries = 30/cluster, but K=20 for 200 entries = 10/cluster, some of which will be empty)
- The intent detector's keyword lists need updates as usage patterns evolve
- K-Means initialization sensitivity means different runs of the same rebuild can produce different clusters, making results appear inconsistent

### Integration Friction

**Medium.** The retrieval path gains a two-stage process: (1) route to clusters, (2) score within clusters. The existing keyword scoring is demoted to within-cluster scoring. This is a significant change to the retrieval flow.

The cluster data file (`clusters.json`) is a new artifact that must be maintained alongside `index.md` and the proposed `index.inv.json` from Alt 1.

### Operational Concerns

**Recall fragility** is the critical issue, and Gemini nails this: "If the intent detector or centroid routing misclassifies the query into Cluster A, but the answer is in Cluster B, you get zero recall."

With only 600 entries and 20 clusters, the statistical basis for clustering is weak. Clusters may not correspond to meaningful topics. A cluster might contain a mix of "auth" and "deployment" memories that happened to share some TF-IDF features, making the cluster label misleading.

**Hard routing failure mode:** The proposal routes to top-3 clusters. If the answer is in cluster #4 (just barely missed), it is invisible. This is a cliff-edge failure: recall goes from "found" to "impossible" with no graceful degradation. The proposal mitigates this with "also include any global keyword match with score > threshold", but this partially defeats the purpose of cluster routing.

**Debugging:** "Why didn't it find memory X?" -> "Because memory X is in cluster 7 (labeled 'auth, session, jwt') and your query was routed to clusters 3 ('database, migration'), 9 ('api, endpoint'), and 14 ('deploy, docker'). Cluster 7 was the 4th closest centroid." This is not actionable for a user.

### Migration Path

**Medium.** Requires a one-time batch clustering of all existing memories. The clustering takes ~5-10s in pure Python. Not difficult, but adds a post-install step.

### Deal-Breakers

**Soft deal-breaker: Recall fragility on small datasets.** 600 entries is not enough for meaningful clustering. The IR literature generally recommends clustering for 10K+ documents. At 600, you are better off searching everything (which is what BM25 inverted index does).

Gemini scores this 4/10 and says "Over-engineered for 600 items; introduces brittle failure points." That is exactly right.

### Practicality Score: 4/10

The intent detection component has standalone value and could be extracted into the existing system without the clustering machinery. The clustering itself is the wrong tool for this dataset size.

**Gemini score: 4/10.** Full agreement.

---

## Alternative 6: Hybrid Sparse-Dense with SQLite FTS5

### Implementation Cost: 30-40 hours realistic

The proposal says "4-5 sessions" and ~500 LOC. I estimate slightly less because SQLite's stdlib support handles much of the heavy lifting:

- **Schema + migration** (~6-8h). Defining the SQLite schema, creating FTS5 virtual tables, and writing the JSON-to-SQLite migration script.
- **FTS5 query builder** (~6-8h). Translating user prompts into FTS5 MATCH syntax, handling special characters, configuring BM25 weights.
- **Write integration** (~6-8h). Modifying `memory_write.py` to maintain both JSON files and SQLite DB (dual-write for backward compatibility).
- **Retrieval integration** (~6-8h). Modifying `memory_retrieve.py` to query SQLite instead of parsing index.md.
- **Concurrency handling** (~3-5h). WAL mode setup, connection management, timeout handling.
- **Testing** (~5-8h). Testing concurrent read/write, migration, FTS5 queries.

### Runtime Performance

- **Latency:** ~10ms for FTS5 BM25 queries. SQLite FTS5 is highly optimized C code; this is the fastest option.
- **Write-time:** SQLite INSERT + FTS5 index update is ~1-2ms per entry. Dramatically faster than rebuilding a JSON inverted index.
- **Memory:** SQLite uses memory-mapped I/O. For a 2MB database, the OS handles caching efficiently.
- **Concurrent access:** WAL mode allows simultaneous readers and writers. This is strictly better than the current flat-file approach where `memory_write.py` and `memory_retrieve.py` can race on `index.md`.

### Dependency Management

**Low but with a caveat.** `sqlite3` is part of the Python stdlib. However:

- **FTS5 availability is NOT guaranteed.** FTS5 is a compile-time option for SQLite. The CPython source includes FTS5 in its default build, but:
  - Custom Python builds (conda, pyenv with custom flags) may lack it
  - Some minimal Linux distros ship SQLite without FTS5
  - Older Python versions (3.7, 3.8) may have SQLite builds without FTS5

You can detect FTS5 availability at runtime:
```python
import sqlite3
conn = sqlite3.connect(":memory:")
try:
    conn.execute("CREATE VIRTUAL TABLE test USING fts5(content)")
    has_fts5 = True
except sqlite3.OperationalError:
    has_fts5 = False
```

If FTS5 is missing, the system must fall back gracefully. This is doable but adds a code path to maintain.

### Maintenance Burden (12 months)

**Low-Medium.** Once the schema is stable:
- SQLite itself is zero-maintenance (it is the most deployed database in the world)
- Schema evolution requires migration scripts, but for a plugin with one table this is manageable
- FTS5 tuning (field weights) is a one-time exercise

The dual-write approach (JSON + SQLite) doubles the write-side maintenance but provides safety.

### Integration Friction

**High.** This is the most architecturally disruptive alternative:
- Replaces the flat-file index paradigm with a database paradigm
- `index.md` becomes a derived artifact (generated from SQLite for human readability)
- All scripts that currently read `index.md` must be updated or replaced
- `memory_candidate.py` parses `index.md` for candidate selection -- this must be ported to SQL queries
- `memory_index.py` rebuilds `index.md` from JSON files -- this concept changes entirely

The proposal says "keep `index.md` as a derived artifact," which means maintaining two parallel systems during transition.

### Operational Concerns

- **Database locking** on WSL/NFS: SQLite locking semantics can fail on network filesystems. The `.claude/memory/` directory is local, so this should not be an issue, but WSL file system quirks have caused SQLite issues before.
- **Database corruption:** Extremely rare with SQLite, but a corrupted `memory.db` loses the entire retrieval index. The JSON files are the source of truth, so recovery is possible via re-migration, but the user experiences degraded service until then.
- **Human readability lost:** `index.md` is greppable from the command line. `memory.db` requires `sqlite3` CLI or a viewer. For a developer-facing plugin, this is a meaningful loss.
- **Debugging:** SQL queries are inspectable (`EXPLAIN QUERY PLAN`), and FTS5 match details can be extracted. This is actually better than the current system for debugging.

### Migration Path

**Medium-High.** The migration requires:
1. Running a one-time script to import all JSON files into SQLite
2. Dual-writing to both JSON and SQLite during the transition period
3. Updating `memory_retrieve.py`, `memory_candidate.py`, and `memory_index.py`
4. Testing on all target platforms for FTS5 availability

Rollback: delete `memory.db` and revert to `index.md`-based retrieval. Clean but requires reverting multiple files.

### Deal-Breakers

**Soft deal-breaker: FTS5 platform guarantee.** You cannot guarantee FTS5 is available on every user's Python installation. The fallback is necessary but means some users get the full FTS5 experience while others get keyword-only, creating inconsistent behavior across installations.

**Soft deal-breaker: Architectural disruption.** This is really a v6.0 change, not a v5.x incremental improvement. It touches too many files and changes too many assumptions.

### Practicality Score: 6/10

Excellent technology choice if you are building from scratch. Too disruptive as an incremental improvement to the current system. The FTS5 platform risk is manageable but adds a support burden. Best suited for a major version where the flat-file assumption is deliberately abandoned.

**Gemini score: 8/10.** Disagreement here -- Gemini is more optimistic. I weight the integration disruption and FTS5 platform risk more heavily because this is a plugin distributed to end users, not a server you control.

---

## Consolidated Comparison

| Dimension | Alt 1: BM25 | Alt 2: Graph | Alt 3: Embeddings | Alt 4: Progressive | Alt 5: Clusters | Alt 6: SQLite |
|-----------|:-----------:|:------------:|:------------------:|:------------------:|:---------------:|:-------------:|
| Impl. hours (realistic) | 20-30 | 40-60 | 60-80+ | 10-15 | 30-40 | 30-40 |
| Runtime latency | 20-30ms | 30-50ms | 1.5-2s (cold) | 40ms + 2-6s UX | 20ms | 10ms |
| New dependencies | None | None | onnxruntime+numpy+tokenizers | None | None | None (FTS5 caveat) |
| Maintenance (12mo) | Low | High | Very High | Medium | High | Low-Medium |
| Integration disruption | Low | Medium | High | Low | Medium | High |
| Debugging ease | Good | Poor | Poor | Poor (non-deterministic) | Medium | Good |
| Failure modes | Index drift | Hub explosion | Segfaults, missing libs | Claude ignores instruction | Routing misses | DB lock, missing FTS5 |
| Rollback difficulty | Trivial | Easy | Medium | Trivial | Easy | Medium |
| **Practicality Score** | **9/10** | **5/10** | **2/10** | **6/10** | **4/10** | **6/10** |

---

## Final Ranking (Most to Least Practical)

### 1st: Alternative 1 -- BM25 + Inverted Index (9/10)

**Why it wins:** Zero dependencies, proven algorithm, clean integration, good debuggability, low maintenance. It directly addresses the two biggest weaknesses of the current system (no body search, no morphological matching) without introducing new failure classes. The synonym table is the only ongoing work. Both Claude Opus 4.6 and Gemini 3 Pro rank this first.

**Recommended approach:** Implement this first. Use it as the foundation for any future enhancements.

### 2nd: Alternative 4 -- Progressive Disclosure (6/10)

**Why it is second:** Trivial to implement and provides semantic understanding for free (via Claude's intelligence). But the UX latency (2-6s per prompt) and behavioral dependency on Claude's model cooperation are real operational concerns. Best used as an optional mode alongside direct injection, not as a replacement.

**Caveat:** This ranks second on implementation ease but has a lower ceiling than BM25 for consistent, predictable behavior.

### 3rd (tie): Alternative 6 -- SQLite FTS5 (6/10)

**Why it ties for third:** Technically excellent (FTS5 BM25 is better than hand-rolled BM25), but too architecturally disruptive for a v5.x release. The FTS5 platform risk is manageable but adds a support burden. Best reserved for a v6.0 major version where the flat-file assumption is deliberately replaced.

### 4th: Alternative 2 -- Concept Graph (5/10)

**Why it falls here:** The structural relationship signal is genuinely unique and valuable, but the tuning burden and debugging opacity make it impractical as a primary retrieval mechanism. The write-time graph rebuild cost (potentially seconds in pure Python for 600 entries) is a hidden expense. Best considered as an optional add-on to BM25, not a standalone alternative.

### 5th: Alternative 5 -- TF-IDF Clusters (4/10)

**Why it is near the bottom:** Clustering is the wrong tool for 600 entries. The recall fragility from hard routing (miss cluster #4 by a hair, get zero results) is a fundamental design flaw at this scale. The intent detection component has standalone value and should be extracted into the existing system without the clustering machinery.

### 6th: Alternative 3 -- Local Embeddings (2/10)

**Why it is last:** Two hard deal-breakers (stdlib-only constraint violation, cold start latency) and a severe dependency management burden. The retrieval quality would be best-in-class, but the operational cost is prohibitive for a client-side plugin. If the plugin ever moves to a server-side architecture with persistent processes, revisit this.

---

## Cross-Model Consensus

| Alternative | Claude Opus 4.6 | Gemini 3 Pro | Delta | Notes |
|-------------|:---------------:|:------------:|:-----:|-------|
| Alt 1: BM25 | 9 | 9 | 0 | Full agreement. Clear winner. |
| Alt 2: Graph | 5 | 6 | -1 | Gemini slightly more optimistic; I weight write-time rebuild cost more |
| Alt 3: Embeddings | 2 | 2 | 0 | Full agreement. Deal-breakers are obvious. |
| Alt 4: Progressive | 6 | 7 | -1 | I weight UX latency and non-determinism more heavily |
| Alt 5: Clusters | 4 | 4 | 0 | Full agreement. Wrong tool for dataset size. |
| Alt 6: SQLite | 6 | 8 | -2 | Biggest disagreement. I weight integration disruption and FTS5 platform risk more for a distributed plugin |

The largest disagreement is on Alt 6 (SQLite FTS5). Gemini evaluates it as a strong #2 because SQLite's technology is excellent. My lower score reflects the practical reality that this is a plugin running on diverse user machines where FTS5 availability cannot be guaranteed, and the architectural disruption affects 3+ scripts beyond just the retrieval hook.

---

## Actionable Recommendation

Implement **Alternative 1 (BM25 + Inverted Index)** as the v5.1 retrieval upgrade. It is the highest-value, lowest-risk improvement available. After it is stable and tested, consider adding **Alternative 4 (Progressive Disclosure)** as an optional retrieval mode for users who want Claude-mediated selection.

Do not invest in Alternatives 3 or 5. Extract the intent detection keywords from Alternative 5 into the existing scoring as a lightweight enhancement (no clustering needed). Keep Alternative 6 in mind for a future v6.0 major version.

---

*Review complete. Cross-validated with Gemini 3 Pro Preview via PAL clink.*
