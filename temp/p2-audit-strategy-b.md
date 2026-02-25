# Plan #2 Audit Strategy B: Behavioral & Operational Audit

**Strategist:** Strategy Architect B
**Date:** 2026-02-25
**Scope:** Bug/error/improvement discovery in the Plan #2 logging infrastructure
**Constraint:** Find what V1+V2 static code reviews structurally CANNOT catch

---

## Guiding Principle

Static code review answers "does the code look correct?" This audit answers "does the code BEHAVE correctly when actually used?" The V1+V2 reviews verified signatures, control flow, and security patterns. They could NOT verify: (a) what exact bytes land on disk at runtime, (b) whether the data dicts passed at call sites satisfy the schema contract, (c) whether the instrumentation silently fails in common real-world configurations, or (d) whether the logging has observable side-effects on the host pipeline's correctness/performance.

---

## Strategy: Three-Tier Prioritized Audit

### TIER 1: Integration Data Contract Verification (HIGH priority, HIGH yield)

**What this finds that static review cannot:**
Static review can verify that `emit_event()` accepts the right parameter types. It CANNOT verify that the specific `data` dict constructed at each of the ~12 call sites across 4 files contains the keys promised by the plan's event type schema table (Section 4 of the plan). This is a cross-file, cross-document verification that requires tracing actual runtime data flow.

#### Action 1.1: Call-Site Schema Audit (est. 45 min)
For each `emit_event()` call site, extract the `data` dict keys and cross-reference against the plan's schema spec (plan section "3. Log Entry Schema" and "4. Event Type Taxonomy"):

| Call Site | File:Line | event_type | Expected data keys (per plan) | Actual data keys (per code) | Gap? |
|-----------|-----------|------------|-------------------------------|----------------------------|------|
| FTS5 search results | retrieve.py:~471 | retrieval.search | query_tokens, engine, candidates_found, candidates_post_threshold, results[] | ? | ? |
| Judge filtering | retrieve.py:~519 | retrieval.search | candidates_post_judge, judge_active | ? | ? |
| Final injection (FTS5) | retrieve.py:~533 | retrieval.inject | injected_count, results[] | ? | ? |
| Skip events (x4) | retrieve.py:~333,359,379,419 | retrieval.skip | reason, (variable) | ? | ? |
| FTS5 unavailable | retrieve.py:~560 | retrieval.search | engine, reason | ? | ? |
| Final injection (legacy) | retrieve.py:~678 | retrieval.inject | injected_count, engine, results[] | ? | ? |
| Judge evaluate (parallel) | judge.py:~368 | judge.evaluate | candidate_count, model, batch_count, mode, accepted/rejected | ? | ? |
| Judge error (x3) | judge.py:~383,400,413 | judge.error | error_type, message, fallback, candidate_count, model | ? | ? |
| Judge evaluate (seq) | judge.py:~426 | judge.evaluate | (same as parallel) | ? | ? |
| CLI search | search_engine.py:~500 | search.query | fts_query, token_count, result_count, top_score | ? | ? |
| Triage score | triage.py:~1000 | triage.score | text_len, exchanges, tool_uses, triggered[] | ? | ? |

**Bug category:** Schema drift between plan spec and implementation. DEFERRED items (D-01 through D-05) are known gaps; this audit looks for UNKNOWN gaps.

**Minimum viable version:** Manual table fill-in by reading each call site and the plan side-by-side. This is the single highest-value audit action.

#### Action 1.2: Config Loading Race Check (est. 20 min)
**Specific bug hypothesis:** In `memory_retrieve.py`, the early `retrieval.skip` events (lines ~333, ~359) pass `config=None` because the config file hasn't been loaded yet at that point in the execution flow. Since `parse_logging_config(None)` returns `{"enabled": False, ...}`, these skip events are NEVER logged even when logging is enabled.

Trace the execution path:
1. Line 329: `_session_id` extracted
2. Line 332-338: First `emit_event("retrieval.skip", ...)` with `config=None`
3. Line 358-362: Second skip event, also `config=None`
4. Line 370-376: Config file is loaded into `_raw_config`
5. Line 379-383: Third skip event -- now uses `_raw_config` (correct)

**Verify:** Do lines 333 and 361 constitute a real bug? These events fire when the prompt is too short or when the index doesn't exist. If logging is enabled, a user would expect to see these events in their logs. The fact that they silently disappear is a behavioral bug that no static review would flag because each line in isolation looks correct.

**Cost-benefit:** Very high. 20 minutes to trace, potentially reveals a real data completeness bug.

#### Action 1.3: results[] Field Completeness for PoC #5 (est. 30 min)
Plan #3 PoC #5 (BM25 precision) requires `retrieval.search` results to contain: `path`, `score`, `raw_bm25`, `body_bonus`, `confidence`. PoC #7 requires `matched_tokens` (already DEFERRED as D-05).

**Verify at the call site (retrieve.py:~476-481):**
- Does `r.get("raw_bm25", r.get("score", 0))` correctly capture the raw BM25 score BEFORE body_bonus is applied? Trace the data flow through `score_with_body()`:
  - Line 267: `r["raw_bm25"] = r["score"]` (captures pre-body score)
  - Line 268: `r["score"] = r["score"] - r.get("body_bonus", 0)` (modifies score)
  - So at the call site, `r.get("raw_bm25")` should have the pre-body value and `r.get("score")` the post-body value.
- But is `body_bonus` always present? For entries beyond `top_k_paths` (line 262-263), `_data` is popped but `body_bonus` may not be set if the entry had a file-read failure. Check line 240: yes, `body_bonus` is set to 0 on failure. But line 262-263 only calls `pop("_data", None)` without setting `body_bonus`. So entries beyond `top_k_paths` that DIDN'T have file-read failures have `_data` set from line 245 but `body_bonus` is never set.

**Bug hypothesis:** Entries between `top_k_paths` and the end of `initial` list that were NOT retired and DID NOT have file-read failures will have `_data` cached but `body_bonus` never explicitly set. When these entries survive `apply_threshold()` and reach the logging call site, `r.get("body_bonus", 0)` returns 0, which is correct but misleading -- it hides the fact that body analysis was SKIPPED, not that the body had zero matches.

---

### TIER 2: Behavioral Verification (MEDIUM priority, validates assumptions)

#### Action 2.1: End-to-End Data Flow Trace (est. 40 min)
Write a single integration test (or execute manually) that traces the COMPLETE pipeline:

1. Create a minimal memory corpus (2-3 JSON memory files + index.md)
2. Set `logging.enabled: true` in a test config
3. Pipe a hook_input JSON into `memory_retrieve.py` via stdin
4. Read the resulting JSONL file(s) from `{memory_root}/logs/`
5. Parse each line and verify:
   - Valid JSON (parseable by `json.loads`)
   - `schema_version == 1`
   - `timestamp` matches filename date
   - `event_type` matches subdirectory name
   - `data` dict contains expected keys for that event type
   - `duration_ms` is a positive finite number
   - `session_id` is non-empty (derived from transcript_path in hook_input)

**Why this matters:** The existing 52 tests call `emit_event()` directly with synthetic data. They never test the actual data dicts constructed by the consumer scripts. This single test would catch every schema drift issue in one shot.

**Minimum viable version:** A shell script that sets up a temp directory, creates minimal fixtures, runs `python3 memory_retrieve.py < hook_input.json`, then checks `logs/` contents with `python3 -c "import json; ..."`.

#### Action 2.2: Cleanup Latency Under Accumulated Logs (est. 20 min)
The p95 benchmark test (test #24) runs against a clean directory. In production, after 14+ days of logging, the `cleanup_old_logs()` call inside `emit_event()` will scan potentially hundreds of files. The time-gate (24h) prevents this from running on every call, but the FIRST call after the 24h window will pay the full scan cost.

**Test:** Create a temp directory with 14 subdirectories (one per event category) each containing 14 .jsonl files. Run `emit_event()` once without a `.last_cleanup` file. Measure latency. Verify it stays under 5ms (or at least doesn't blow the 15s hook timeout).

**Bug hypothesis (weak):** Unlikely to be a real issue at the expected scale (< 100 files), but worth a quick sanity check since the plan claims "14 days of JSONL < 1MB."

#### Action 2.3: Verify Lazy Import Fallback Behavior (est. 15 min)
The lazy import pattern with `e.name` scoping is used in all 4 consumer scripts. Test that:
1. When `memory_logger.py` is missing, the noop fallback activates (consumer scripts work normally)
2. When `memory_logger.py` exists but has a syntax error, the `SyntaxError` catch activates
3. When `memory_logger.py` imports a missing third-party module (hypothetical transitive dependency), the `ImportError` is re-raised (fail-fast)

The existing tests don't test the import fallback in the CONSUMER scripts -- they only test `memory_logger.py` directly. The fallback code is duplicated across 4 files, so if any copy has a typo, it won't be caught.

**Minimum viable version:** In a temp directory, create a test script that does `sys.path.insert(0, ...)` to a directory WITHOUT `memory_logger.py`, then imports each consumer module and verifies it works. Then create a broken `memory_logger.py` that `import nonexistent_module` and verify the ImportError propagates.

#### Action 2.4: Concurrent Append with Realistic Payloads (est. 15 min)
The existing concurrent test (test #23) uses 8 threads x 50 writes with 100-byte payloads. Real `retrieval.search` events with 20 results could reach 2-4KB.

**Gemini 3.1 Pro flag:** POSIX `O_APPEND` atomicity is guaranteed only up to `PIPE_BUF` (typically 4KB on Linux, 512 bytes on older systems). The plan explicitly targets < 4KB entries, but:
- What if someone sets `_MAX_RESULTS = 50` in a fork?
- What if `data.query_tokens` contains extremely long compound tokens?

**Test:** Run the concurrent test with payloads sized at exactly 4096 bytes. If any lines are corrupt (interleaved), the atomic append assumption is violated.

**Assessment:** LOW risk in practice. Claude Code runs hooks sequentially within a session. Cross-session concurrency on the same file is possible but rare. The `_MAX_RESULTS = 20` cap + compact JSON (`separators=(",",":")`) keeps entries well under 4KB.

---

### TIER 3: Operational & Design-Level Checks (LOW priority, easy wins)

#### Action 3.1: Operational Workflow Smoke Test (est. 10 min)
Manual checklist:
- [ ] Set `logging.enabled: true` in `memory-config.json` -- does logging start?
- [ ] Set `logging.level: "debug"` -- do debug events appear?
- [ ] Set `logging.level: "error"` -- do info events get filtered out?
- [ ] Set `logging.enabled: false` -- does logging stop? Are existing log files preserved?
- [ ] Set `logging.retention_days: 0` -- does cleanup stop?
- [ ] Delete `memory-config.json` entirely -- does the system fall back to disabled?
- [ ] Run `cat logs/retrieval/*.jsonl | python3 -c "import sys,json; [json.loads(l) for l in sys.stdin]"` -- are all lines valid?
- [ ] Run `jq . logs/retrieval/2026-02-25.jsonl` -- does jq parse every line?

**Why:** No automated test verifies the actual user workflow. This 10-minute manual test catches config key typos, path resolution bugs, and format issues that only manifest with a real project layout.

#### Action 3.2: Silent Truncation Metadata (est. 5 min, DESIGN SUGGESTION)
**From Gemini 3.1 Pro analysis:** When `results[]` is truncated from N to 20, the downstream analyst loses the original count. This skews precision/recall calculations.

**Check:** Does the current truncation (memory_logger.py:256-260) record the original count? Answer: No. The shallow copy replaces `results` with the truncated version and discards the original length.

**Suggestion:** Add `_original_results_count: len(results)` and `_truncated: True` to the data dict when truncation occurs. This is a 3-line enhancement that significantly improves analytics accuracy. Note: This overlaps with DEFERRED D-03 (global payload size limit) but is a distinct concern (metadata preservation vs. size capping).

#### Action 3.3: Non-Deterministic Set Serialization (est. 5 min, DESIGN NOTE)
**From Gemini 3.1 Pro analysis:** `json.dumps(default=str)` converts Python `set` objects to strings like `"{'a', 'b'}"`. The order is non-deterministic across runs.

**Check:** Do any call sites pass `set` objects inside the `data` dict? The `tags` field in index entries is a `set`, but the logging call sites (retrieve.py:~476-481) construct new dicts with explicit key access (`r.get("score")`, `r["path"]`), not raw entry dicts. The `query_tokens` field is a `list` (from `list(tokenize(...))`).

**Assessment:** The existing code likely does NOT pass sets into `emit_event()` data dicts. But the `default=str` fallback means any future caller could accidentally pass a set and get non-deterministic output. The fix (custom serializer converting sets to sorted lists) is a good defensive improvement but not a current bug.

#### Action 3.4: Windows O_NOFOLLOW TOCTOU (est. 5 min, DESIGN NOTE)
**From Gemini 3.1 Pro analysis:** On Windows, `O_NOFOLLOW` resolves to 0, creating a TOCTOU gap in `.last_cleanup` handling.

**Assessment:** Claude Code currently runs on macOS and Linux only. The plugin is not distributed for Windows. This is a theoretical risk worth documenting but not an actionable bug for the current audit. If Windows support is added, the `.last_cleanup` symlink check (memory_logger.py:122-126) + O_NOFOLLOW fallback should be revisited.

#### Action 3.5: triage.score Event Missing All-Category Scores (est. 5 min)
**Check:** The `triage.score` event (triage.py:~1000-1010) only logs TRIGGERED categories (those exceeding threshold). For post-hoc analysis of threshold tuning, you also need the scores of categories that did NOT trigger.

**Is this a bug or a design choice?** The plan says "triage.score: triage category scores" which could mean either "scores that triggered" or "all category scores." If the intent is threshold tuning, logging all 6 scores (with a `triggered: true/false` flag) would be far more useful.

**Assessment:** This is a data completeness gap that reduces the value of triage logs for threshold tuning analysis. It's not a bug per se -- the code does what it implements -- but it may not do what the downstream consumer (Plan #3 analysis) needs.

---

## Priority Ordering

| Priority | Action | Est. Time | Bug Type |
|----------|--------|-----------|----------|
| 1 | 1.2 Config loading race | 20 min | Data completeness bug (skip events never logged) |
| 2 | 1.1 Call-site schema audit | 45 min | Schema drift (plan vs implementation) |
| 3 | 1.3 results[] field completeness | 30 min | PoC #5 data quality (body_bonus correctness) |
| 4 | 2.1 End-to-end data flow trace | 40 min | Integration validation (bytes on disk) |
| 5 | 2.3 Lazy import fallback | 15 min | Regression safety (4 duplicated fallbacks) |
| 6 | 3.5 Missing non-triggered scores | 5 min | Data completeness (threshold tuning) |
| 7 | 3.2 Silent truncation metadata | 5 min | Analytics accuracy (design improvement) |
| 8 | 2.2 Cleanup latency | 20 min | Performance assumption validation |
| 9 | 3.1 Operational smoke test | 10 min | User workflow validation |
| 10 | 2.4 Concurrent large payloads | 15 min | Atomicity assumption stress test |
| 11 | 3.3 Set serialization | 5 min | Future-proofing (not current bug) |
| 12 | 3.4 Windows TOCTOU | 5 min | Documentation note (not current platform) |

**Total estimated time:** ~3.5 hours for complete audit, ~1.5 hours for Tier 1 only.

---

## Cross-Reference: Inputs Incorporated

### From Vibe-Check Analysis
- Adopted: Sharper prioritization (3 tiers instead of 6 parallel approaches)
- Adopted: Focus on integration surface (call sites) over logger module
- Adopted: Config loading race as highest-priority check
- Adopted: "What does 'bug' mean?" -- defined tiers: data completeness, schema drift, performance, design
- Adjusted: Reduced scope of behavioral testing to "one good trace per event category"

### From Gemini 3.1 Pro Analysis
- Adopted (as Action 3.2): Silent truncation skews analytics -- needs `_original_results_count`
- Assessed (Action 3.3): Set serialization -- verified NOT a current bug, but good defensive fix
- Assessed (Action 3.4): Windows TOCTOU -- not actionable for current platforms
- Assessed (Action 2.4): Large payload atomicity -- low risk given `_MAX_RESULTS` cap
- Assessed but REJECTED: "Thread starvation from blocking I/O" -- this is a subprocess script (not a long-lived daemon), and the hook has a 15s timeout. Blocking I/O on a hung filesystem would trigger the timeout, which is the correct fail-safe. Moving to a background thread would add complexity without benefit for a short-lived process.
- Assessed but REJECTED: "Unbounded volume growth" -- already tracked as DEFERRED D-03. The plan explicitly targets < 1MB for 14 days. A logging storm from a consumer bug is an extreme edge case for a single-user plugin.

---

## Self-Critique

### Strengths of this strategy
1. **Laser-focused on integration surface** -- the ~12 call sites where `emit_event()` is invoked with real data are the highest-risk area that static review structurally misses.
2. **Concrete and actionable** -- every action has a specific file, line number, and bug hypothesis. No vague "review for issues."
3. **Calibrated cost-benefit** -- estimated times are realistic for single-person execution, and priority ordering reflects actual bug severity.
4. **Incorporates external perspectives** -- synthesizes Gemini's ops-focused analysis with vibe-check's strategic critique, adopting useful insights and explicitly rejecting inapplicable ones with reasoning.

### Weaknesses of this strategy
1. **Assumes plan document is ground truth** -- Action 1.1 compares code against the plan spec, but what if the plan spec itself has errors? This strategy doesn't independently validate whether the planned schema actually serves PoC #3's needs.
2. **Limited cross-script interaction testing** -- Actions focus on individual call sites. The strategy doesn't test the scenario where retrieve.py calls judge.py, and BOTH emit events with potentially conflicting session_ids or timestamps. (However, this is unlikely to be a real issue since session_id is passed through.)
3. **No negative testing of the consumer scripts** -- The strategy verifies happy-path data flow but doesn't test what the consumer scripts emit when they encounter errors (e.g., corrupt index, missing JSON files). The error paths in consumer scripts may construct malformed `data` dicts.
4. **Manual table-filling (Action 1.1) is tedious** -- Could be partially automated with AST analysis (`ast.parse` to extract `emit_event` call kwargs), but the automation itself would take 30-60 min to build, which exceeds the manual verification time.
5. **Scope boundary unclear for "improvements" vs "bugs"** -- Actions 3.2, 3.3, 3.5 are improvements/design suggestions, not bugs. Including them risks scope creep. However, they were explicitly requested in the audit scope ("bugs, errors, and improvements").
