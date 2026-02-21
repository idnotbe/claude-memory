# Feasibility Review: Retrieval Architecture Proposal v2.0

**Reviewer:** pragmatist (senior developer)
**Date:** 2026-02-20
**Verdict:** Proposal is sound in direction but over-engineered in scope. Recommend a compressed 2-phase plan.

---

## 1. Effort Estimation (Realistic, Not Optimistic)

### Phase 0: Evaluation Benchmark
| Metric | Proposal Claim | Realistic Estimate |
|--------|---------------|-------------------|
| LOC | ~200 | ~250-350 (test corpus creation is the hidden cost) |
| Coding hours | Not stated | 4-6 hours |
| Testing hours | N/A | 2 hours (testing the test framework) |

**Hidden complexity:** Creating 25+ realistic test queries with expected results requires deep knowledge of what memories exist. You need a test corpus of ~30 JSON files across 6 categories, each with realistic content. That's 30 files * ~40 lines each = ~1200 lines of test data, not counted in the "200 LOC" estimate. However, conftest.py already has factory functions for all 6 categories, so the fixtures are partially in place.

**Verdict:** Useful but not prerequisite. You can validate FTS5 improvement with 5-10 queries manually. A formal benchmark framework is nice-to-have, not blocking.

### Phase 0.5: Body Content in Keyword System (CONDITIONAL)
| Metric | Proposal Claim | Realistic Estimate |
|--------|---------------|-------------------|
| LOC | ~50 | ~40-60 (accurate) |
| Coding hours | Not stated | 1-2 hours |
| Testing hours | N/A | 1 hour |

**Hidden complexity:** None. This is genuinely simple -- read JSON files for top-scored candidates, extract text fields, add bonus points. The current system already does a "deep check" of top 20 candidates (reads JSON for recency/retired status). Extending that to also read body content is minimal.

**Verdict:** This is the highest bang-for-buck change in the entire proposal. The proposal marks it "conditional" but it should be the FIRST thing done, unconditionally.

### Phase 1: FTS5 BM25 Engine
| Metric | Proposal Claim | Realistic Estimate |
|--------|---------------|-------------------|
| LOC (implementation) | ~300 | ~150-200 (the FTS5 core is ~50-80 LOC; the rest is plumbing) |
| LOC (tests) | ~200 | ~200-300 (FTS5 path + fallback path + edge cases) |
| Coding hours | Not stated | 8-12 hours (including debugging threshold calibration) |
| Testing hours | Not stated | 4-6 hours |
| Total effort | Not stated | 2-3 focused days |

**Hidden complexity the proposal underestimates:**

1. **Prefix matching regression.** Verified on this WSL2 system: FTS5 porter stemmer handles `test->testing` but does NOT handle `auth->authentication`. The current system DOES handle this via explicit prefix matching. The proposal does not mention this regression at all. Fix: append `*` wildcard to query tokens (e.g., `auth*`). This works but changes the query construction logic and has implications for scoring (wildcard matches may score differently than exact matches in BM25).

2. **Threshold calibration.** The proposal acknowledges this needs empirical tuning but waves it away as "Phase 0 will handle it." In practice, BM25 score distributions vary wildly with corpus composition. Getting the absolute minimum (0.5) and relative cutoff (0.6) right will require iterating. Expect 2-4 hours of tuning alone.

3. **Two code paths to maintain.** The FTS5 path + keyword fallback means every change to retrieval logic must be tested twice. The proposal says the fallback is "minimal" but it still doubles the testing surface.

4. **Body extraction per-category mapping.** The `BODY_FIELDS` dict (6 categories * 5-7 fields each) is ~30 lines but it's a maintenance burden: every schema change requires updating this mapping. And if a field is missed, those memories become invisible to body search.

**Verdict:** Feasible but the proposal's LOC estimates are accurate for the FTS5 core and overstated for total effort (500 -> 350-500 when you include the fallback path and all the plumbing). The real cost is not LOC but calibration time.

### Phase 2: On-Demand Search Skill
| Metric | Proposal Claim | Realistic Estimate |
|--------|---------------|-------------------|
| LOC (skill definition) | ~150 | ~80-120 (skill YAML + instructions) |
| LOC (engine extraction) | ~100 | ~60-100 (extract shared module) |
| Coding hours | Not stated | 3-4 hours |
| Testing hours | Not stated | 2 hours (manual testing; skill testing is hard to automate) |

**Hidden complexity:**
- Skill trigger reliability is a known problem (67% in claude-mem). The proposal mitigates this with diverse trigger words and a hook-injected reminder, which is sensible.
- Extracting the shared engine from `memory_retrieve.py` into a separate module is a refactor that touches the hook's import path. Not complex but must be done carefully.

**Verdict:** Independently valuable. Can ship before or after Phase 1. The skill file is just a markdown file with instructions; the hard part is extracting the shared engine.

### Phase 3: Transcript Context
| Metric | Proposal Claim | Realistic Estimate |
|--------|---------------|-------------------|
| LOC | ~80 | ~60-80 (accurate) |
| Coding hours | Not stated | 2-3 hours |
| Testing hours | Not stated | 2 hours (needs mock transcript JSONL files) |

**Hidden complexity:**
- The JSONL transcript format is an internal Claude Code format. It WILL break in a future update with zero warning. The proposal handles this with graceful degradation, which is correct.
- The "only for short prompts" restriction (<= 3 tokens) is well-reasoned and avoids the query dilution trap.

**Verdict:** Low effort, moderate value. The restriction to short prompts limits its impact. Most of the time, users type enough tokens that transcript context won't fire.

---

## 2. Incremental Delivery

### Can each phase be shipped independently?
| Phase | Independent? | Real Dependencies |
|-------|-------------|-------------------|
| 0 (Benchmark) | Yes | None |
| 0.5 (Body content) | Yes | None |
| 1 (FTS5) | Yes | None (but benefits from Phase 0 validation) |
| 2 (Search skill) | Partially | Needs shared engine, so either Phase 0.5 or Phase 1 must be done first to have something worth searching |
| 3 (Transcript) | Yes | None |

**Real dependency chain:** 0.5 is strictly independent. Phase 1 is independent. Phase 2 depends on having a search engine worth exposing (either enhanced keyword or FTS5). Phase 3 is independent.

### Minimum Viable Improvement (1-day effort)
**Phase 0.5: Body content in the existing keyword system.** ~40-60 LOC change to `memory_retrieve.py`. The current deep-check already reads JSON files for recency; extend it to also tokenize body content and add a score bonus. This is the single change with the highest value-to-effort ratio in the entire proposal.

### Maximum Bang-for-Buck Single Change
Same answer: body content indexing. Both external model consultations (Gemini 3.1 Pro and Gemini 3.0 Pro) agree this is the highest-leverage improvement, and one explicitly called it "foundational and non-negotiable."

---

## 3. Cost-Benefit Per Component

| Component | Implementation Cost | Expected Benefit | Worth It? |
|-----------|-------------------|-----------------|-----------|
| **FTS5 engine** | 2-3 days (including threshold calibration) | BM25 ranking replaces flat scoring; IDF weighting; stemming | YES, but only after body content is proven valuable |
| **Body extraction** | 2-4 hours | Indexes the actual content, not just metadata; highest single-change improvement | ABSOLUTELY YES -- do this first |
| **Transcript context** | 3-5 hours | Helps with pronoun references ("fix that"); only fires on short prompts | MARGINAL -- defer to v2 |
| **Search skill** | 4-6 hours | Fills recall gap when auto-inject misses; user can explicitly search | YES -- high user-facing value |
| **Eval framework** | 6-8 hours (including test corpus) | Enables measurement-driven improvement | NICE-TO-HAVE -- not blocking |
| **Config changes** | 1-2 hours | Tune thresholds, enable/disable features | NECESSARY for Phase 1 |
| **Fallback engine** | 2-3 hours (testing only) | Safety net for rare environments without FTS5 | PROBABLY NOT WORTH IT (see below) |

### On the Fallback Engine
The proposal builds a dual-engine system (FTS5 primary + keyword fallback). Gemini 3.1 Pro said "just disable retrieval if FTS5 is missing." I partially agree. FTS5 is available on every modern Python 3 on Linux/macOS/WSL2. Building and maintaining a fallback doubles the testing surface for an event that will essentially never happen. My recommendation: check for FTS5 at startup, fail loudly with a clear error message if missing, skip the fallback engine entirely. If a user reports FTS5 unavailable, deal with it then.

---

## 4. Simplest Version That Delivers Value

### The "Weekend Project" Version (1 day)

**Step 1 (2 hours):** Add body content scoring to the existing keyword system.
- In `memory_retrieve.py`, extend the deep-check loop (lines 330-358) to also extract body text from the JSON files it's already reading.
- Add a body match bonus: 1 point per keyword match, capped at 3.
- This is literally 20-30 lines of code added to the existing scoring flow.

**Step 2 (4 hours):** Replace the keyword scorer with FTS5 BM25.
- Build in-memory FTS5 table from JSON files.
- Use `token*` wildcards for prefix matching (preserves current behavior).
- Use `bm25(table, 5.0, 3.0, 1.0)` for column-weighted ranking.
- Keep existing output format, security model, and sanitization.
- The core FTS5 engine is ~80 LOC.

**Step 3 (2 hours):** Add basic threshold filtering.
- Start with a simple absolute score cutoff (tune later).
- Cap auto-inject at 3 results (down from current 5).

Total: ~8 hours, ~120-150 LOC change, single file (`memory_retrieve.py`).

### What to defer to v2
- Eval benchmark framework (Phase 0) -- validate by hand first
- Transcript context (Phase 3) -- marginal value, format stability risk
- On-demand search skill (Phase 2) -- valuable but not urgent
- Fallback engine -- not needed
- Config proliferation (all the new config keys) -- hardcode sensible defaults

---

## 5. Code Reuse Analysis

### What can be reused from current `memory_retrieve.py` (399 LOC)
| Component | Lines | Reuse? |
|-----------|-------|--------|
| `STOP_WORDS` constant | 10 | YES -- used for query tokenization in both systems |
| `CATEGORY_PRIORITY` | 8 | YES -- tiebreaker logic unchanged |
| `tokenize()` | 7 | YES -- query tokenization |
| `parse_index_line()` | 16 | NO -- FTS5 reads JSON directly, not index.md |
| `score_entry()` | 24 | NO -- replaced by FTS5 BM25 |
| `score_description()` | 20 | NO -- replaced by FTS5 body content |
| `check_recency()` | 28 | MAYBE -- could be replaced by FTS5 filter on updated_at |
| `_sanitize_title()` | 12 | YES -- output sanitization unchanged |
| `main()` (hook orchestration) | 180 | PARTIAL -- input parsing, config reading, output formatting reusable; scoring loop replaced |

**Summary:** ~50% of the code is reusable (constants, tokenization, sanitization, I/O). ~50% is replaced (scoring, index parsing, deep-check loop).

### What must be rewritten
- The scoring pipeline (score_entry, score_description, deep-check) -> FTS5 build + query
- Index reading (parse_index_line loop) -> JSON file reading + body extraction
- Result sorting -> BM25 ordering + threshold filtering

### Shared modules to extract
If Phase 2 (search skill) is implemented, extract into `memory_search_engine.py`:
- `build_fts_index(memories) -> Connection`
- `extract_body(data) -> str`
- `tokenize_for_query(text) -> list[str]`
- `build_fts_query(tokens) -> str`
- `search(conn, query, mode) -> list[Result]`

This extraction is ~100 LOC and cleanly separates the engine from the hook/skill interface.

---

## 6. Test Strategy

### What tests are needed

| Test Area | Priority | LOC Est. | Notes |
|-----------|----------|----------|-------|
| FTS5 table creation + population | High | ~30 | Verify schema, porter stemmer, column weights |
| Query construction (tokenize + build) | High | ~40 | Wildcard suffixes, FTS5 reserved word escaping, stop words |
| BM25 scoring behavior | High | ~50 | Verify column weights affect ranking; title match > body match |
| Threshold filtering | High | ~40 | Absolute minimum, relative cutoff, empty results |
| Body extraction per category | Medium | ~60 | All 6 categories, missing fields, truncation at 2000 chars |
| Prefix matching via wildcards | High | ~20 | Verify `auth*` matches `authentication` |
| Stemming behavior | Medium | ~20 | Verify `test` matches `testing` |
| Integration (hook end-to-end) | High | ~60 | Existing integration tests need updating for FTS5 output |
| Fallback path (if kept) | Low | ~40 | Only if dual-engine is implemented |

### How to test FTS5 specifically
```python
@pytest.fixture
def fts_conn():
    """Build a test FTS5 index with known documents."""
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE VIRTUAL TABLE mems USING fts5(title, tags, body, tokenize='porter unicode61')")
    conn.execute("INSERT INTO mems VALUES ('JWT authentication', 'auth jwt', 'chose JWT for stateless auth')")
    conn.execute("INSERT INTO mems VALUES ('Redis cache setup', 'redis cache', 'configured Redis for session caching')")
    return conn
```
This is simple because FTS5 is in-memory and requires no cleanup.

### Current test files that need updating
- `tests/test_memory_retrieve.py` (482 LOC) -- Most tests test the keyword scoring functions that will be replaced. The integration tests (`TestRetrieveIntegration`) should still pass if the output format is unchanged.
- `tests/conftest.py` (327 LOC) -- Factory functions are fine; may need a new `build_fts_test_corpus()` helper.

### How to test the on-demand search skill
Skills are markdown files interpreted by the LLM. They cannot be unit-tested. Testing approach:
1. Test the shared search engine module directly (unit tests).
2. Test the skill trigger words by checking the YAML frontmatter parsing.
3. Manual testing of skill invocation in Claude Code sessions.

---

## 7. Migration Path Reality Check

### Phase 0 -> Phase 1 -> Phase 2 -> Phase 3: Can we really ship independently?

**Phase 0 (Benchmark):** Yes. Pure addition, no production code changes. But it's also skippable -- you can validate with manual testing.

**Phase 0.5 (Body content):** Yes. A small additive change to `memory_retrieve.py`. Fully backward compatible. Can be shipped and reverted independently.

**Phase 1 (FTS5):** Yes, with caveats. This is a rewrite of the scoring core. The output format is identical, so downstream consumers don't notice. But the internal behavior changes (different ranking, different threshold semantics). This is the riskiest phase.

**Phase 2 (Search skill):** Yes, if the shared engine is extracted. This is purely additive (new skill file, new shared module). Does not change the hook behavior.

**Phase 3 (Transcript):** Yes. An additive feature with an enable/disable config flag. Can be shipped and disabled independently.

### What breaks if we skip a phase?
| Skipped Phase | Impact |
|--------------|--------|
| 0 (Benchmark) | No baseline metrics. You fly blind on whether changes helped. Acceptable for a personal project. |
| 0.5 (Body content) | If going straight to Phase 1: no impact (Phase 1 includes body indexing). If not doing Phase 1: you lose the single highest-leverage improvement. |
| 1 (FTS5) | You keep the keyword system. Phase 2 skill works with either engine. Phase 3 enriches queries for either engine. |
| 2 (Search skill) | Users have no way to explicitly search memories. Auto-inject is the only path. |
| 3 (Transcript) | Short/ambiguous prompts like "fix that" will not benefit from conversation context. |

### Rollback plan for each phase
- **Phase 0:** Delete `eval/` directory. Zero production impact.
- **Phase 0.5:** Revert the ~40 LOC change to `memory_retrieve.py`.
- **Phase 1:** Set `match_strategy: "title_tags"` in config. The proposal's config-based kill switch is well designed. Alternatively, git revert.
- **Phase 2:** Delete the skill file and shared module. No hook impact.
- **Phase 3:** Set `transcript_context.enabled: false` in config.

### Users with existing `memory-config.json`
Not an issue. All new config keys have embedded defaults. Missing keys fall back to defaults. The only behavioral change is the new `match_strategy` key which defaults to `"fts5_bm25"`. Users who want the old behavior set `"title_tags"`. This is well handled in the proposal.

---

## 8. Implementation Order Recommendation

The proposal recommends: Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 (skip 0.5).

### My recommended order (value/effort ratio):

**1. Body content scoring in existing system (Phase 0.5)**
- Effort: 2-4 hours
- Value: Highest single-change improvement
- Risk: Near zero
- Why first: Validates the body-content hypothesis with minimal investment. If this alone brings precision from ~40% to ~55%, it changes the calculus on whether FTS5 is even worth it.

**2. FTS5 BM25 engine (Phase 1, simplified)**
- Effort: 1-2 days (not 3)
- Value: BM25 ranking + IDF weighting
- Risk: Medium (core rewrite)
- Simplifications:
  - No fallback engine. Check for FTS5, error if missing.
  - No new config proliferation. Hardcode column weights (5.0, 3.0, 1.0) and thresholds.
  - Use `token*` wildcards to preserve prefix matching behavior.
  - No transcript context (defer to later).

**3. On-demand search skill (Phase 2)**
- Effort: 4-6 hours
- Value: High user-facing value; fills recall gap
- Risk: Low
- Why third: Requires FTS5 engine to be worth exposing. The skill is just a thin wrapper over the search engine.

**4. Transcript context (Phase 3) -- DEFER**
- Effort: 3-5 hours
- Value: Marginal (only fires on short prompts)
- Risk: Format stability concern
- Why defer: The benefit is narrow (pronoun resolution for <3-token prompts) and the JSONL transcript format dependency is a maintenance liability. Wait to see if users actually need this.

**5. Evaluation framework (Phase 0) -- DEFER**
- Effort: 6-8 hours
- Value: Enables measurement
- Risk: None
- Why defer: For a personal project with one user, manual testing with 5-10 queries is sufficient. Build a formal benchmark when/if the project gets other users.

### Compressed Schedule

| Day | Task | Deliverable |
|-----|------|------------|
| Day 1, morning | Phase 0.5: body content scoring | Enhanced keyword retrieval with body matching |
| Day 1, afternoon | Validate improvement manually with 5-10 queries | Confidence that body content helps |
| Day 2 | Phase 1: FTS5 core engine (simplified, no fallback) | BM25-ranked retrieval |
| Day 3, morning | Phase 1: threshold calibration + testing | Tuned auto-inject thresholds |
| Day 3, afternoon | Phase 2: search skill + shared engine extraction | `/memory:search` available |

Total: **3 focused days** for a complete retrieval upgrade. Versus the proposal's implicit 5-7 days across 5 phases.

---

## 9. Critical Issues Found

### Issue 1: Prefix Matching Regression (SEVERITY: HIGH)
**The proposal does not address the fact that FTS5 porter stemmer does not do prefix matching.**

Verified on this system:
- `auth` does NOT match `authentication` in FTS5 with porter tokenizer
- `auth*` DOES match (wildcard syntax)
- The current keyword system DOES handle `auth->authentication` via explicit prefix matching (lines 116-123 of `memory_retrieve.py`)

The proposal's `build_fts_query()` function (Section 2) joins tokens with OR but does NOT append `*` wildcards. This means switching to FTS5 will actually REGRESS prefix matching behavior compared to the current system.

**Fix:** Append `*` to all query tokens: `safe_tokens.append(f'{token}*')` instead of `safe_tokens.append(token)`. This preserves prefix matching behavior while also getting stemming benefits. Need to verify BM25 scoring works correctly with wildcard terms.

### Issue 2: BM25 Score Magnitudes Are Tiny (SEVERITY: MEDIUM)
In my testing, BM25 scores for a 500-document corpus were in the range of -0.000001 to -0.000004. The proposal's `MIN_SCORE_ABS = 0.5` threshold would filter out EVERYTHING. This is because BM25 scores scale with corpus statistics, and a small corpus produces very small absolute scores.

The relative cutoff (0.6 of best) is fine, but the absolute minimum needs empirical calibration, not a hardcoded 0.5. The proposal acknowledges this ("starting points to be tuned empirically") but presents 0.5 as a reasonable default. It's not -- it would reject all results.

**Fix:** Either drop the absolute minimum entirely (rely on relative cutoff only) or calibrate against real data. The proposal's Phase 0 benchmark is designed to catch this, but since I recommend deferring Phase 0, this needs to be caught during Phase 1 implementation.

**UPDATE:** The tiny scores I observed may be due to my synthetic test data (random word soup vs. real structured memories). Real memories with more focused content may produce higher absolute scores. Still, the 0.5 default is risky and should be validated.

### Issue 3: External Model Disagreement (SEVERITY: INFORMATIONAL)
I consulted two external models:
- **Gemini 3.1 Pro (via clink):** "Absolutely do FTS5. Core engine is ~50-80 LOC. You MUST use wildcard suffixes for prefix matching."
- **Gemini 3.0 Pro (via chat):** "Don't rewrite to FTS5 at all. Just add weighted scoring to existing Python code. FTS5 is over-engineering for 500 docs."

Both agree on one thing: **body content indexing is the highest-priority change regardless of engine choice.** The disagreement is on whether FTS5 is worth the engine swap.

My position: FTS5 IS worth it because:
1. It provides IDF weighting (common words like "fix" and "bug" score lower than rare terms like "jwt" or "pydantic") -- this is hard to replicate in Python without essentially reimplementing BM25.
2. The implementation is genuinely small (~80 LOC core).
3. It eliminates the need to maintain custom scoring heuristics.
4. But ONLY if we also add `*` wildcards to preserve prefix matching.

### Issue 4: Proposal LOC Estimates Are Inflated (SEVERITY: LOW)
The proposal claims ~1030 LOC across all phases. Realistic estimates:
- Phase 0: ~250-350 LOC (including test corpus) -- close to claimed 200
- Phase 0.5: ~40-60 LOC -- matches claimed 50
- Phase 1: ~150-200 LOC implementation + ~200-300 tests -- vs claimed 500
- Phase 2: ~80-120 skill + ~60-100 engine extraction -- vs claimed 250
- Phase 3: ~60-80 LOC -- matches claimed 80

Total realistic: ~600-900 LOC. Not dramatically different, but the proposal pads Phase 1 and Phase 2 estimates.

---

## 10. Summary Verdict

The architecture proposal is **sound in direction but over-scoped for a personal project**. The core insight (FTS5 BM25 with body content) is correct and well-researched. The phased delivery plan is reasonable. The security model is maintained.

**What I'd ship:**
1. Body content scoring (1 afternoon)
2. Simplified FTS5 engine with wildcard prefix matching, no fallback (1 day)
3. Search skill (1 afternoon)

**What I'd defer:**
- Evaluation benchmark framework (test manually)
- Transcript context (marginal value, format risk)
- Fallback keyword engine (FTS5 is available everywhere that matters)
- Config key proliferation (hardcode sensible defaults)

**What the proposal gets right:**
- In-memory FTS5, no disk cache (correct decision)
- Body content as highest-leverage improvement (correct)
- Dual-path retrieval (auto-inject + on-demand) (correct)
- Progressive disclosure in search results (correct)
- Skill over MCP for on-demand search (correct given constraints)
- Security model preservation (correct)

**What the proposal gets wrong or misses:**
- Prefix matching regression with porter stemmer (critical gap)
- BM25 absolute score threshold likely miscalibrated for small corpus
- Fallback engine is over-engineering (not worth the maintenance cost)
- Phase ordering (body content should be first, not conditional)
- LOC estimates padded for Phases 1 and 2
- Transcript context value is overstated for the narrow trigger condition (<= 3 tokens)

---

## Appendix: Benchmark Results (This WSL2 System)

```
FTS5 availability: YES (porter + unicode61 tokenize)
Porter stemming: test->testing YES, auth->authentication NO (need auth*)
BM25 scoring: Works, negative scores, column weights functional

500 synthetic documents:
  JSON file read (500 files): 12.2ms
  FTS5 build (in-memory): 22.9ms
  FTS5 query: 0.9ms avg
  Python keyword scan: 3.6ms avg
  FTS5 total (build + query): 23.8ms

Query speed: FTS5 is 4x faster than Python keyword scan per query.
Total time including build: FTS5 is ~37ms, Python keyword is ~16ms (Python wins for single query because no build overhead).
For the hook use case (single query per invocation), the build overhead is the dominant cost. Both are well within the 100ms budget.
```
