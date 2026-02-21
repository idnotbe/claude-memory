# Practical Review: rd-08-final-plan.md

**Reviewer:** Practical Reviewer (agent)
**Date:** 2026-02-21
**Document:** `research/rd-08-final-plan.md` (~1297 lines)
**Writer summary:** `temp/rd08-writer-summary.md`
**Verdict:** PASS WITH ISSUES

**Implementability Score: 7.5/10**

Justification: The plan is well-structured, deeply verified, and the session checklists are actionable enough for an experienced developer to follow. The issues I found are all fixable without restructuring the plan. The main gaps are in transition/migration details and a few underspecified steps in Sessions 3-4. The plan excels at identifying risks and fallback paths.

---

## Summary of Findings

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Actionability | 0 | 1 | 2 | 1 |
| Gaps | 0 | 1 | 2 | 0 |
| Integration | 0 | 0 | 2 | 0 |
| Estimates | 0 | 0 | 1 | 1 |
| **Total** | **0** | **2** | **7** | **2** |

---

## Findings

### Actionability

#### A1 [HIGH] Session 2 main() rewrite scope is underspecified

**Section:** Session 2 checklist (line 1020-1031) and Phase 2a (lines 224-296)

**Issue:** The Session 2 checklist says to add `build_fts_index_from_index()`, `build_fts_query()`, `query_fts()`, `apply_threshold()`, `score_with_body()`, config branching, and FTS5 fallback. However, the actual integration into `main()` is not described. The current `memory_retrieve.py:main()` is ~190 LOC with 11 `sys.exit(0)` paths, a two-pass scoring pipeline (Pass 1: score_entry + score_description, Pass 2: deep check with recency/retired), and XML output formatting. The plan provides code samples for the individual functions but does not describe:

1. Where in `main()` the FTS5 path branches from the keyword path
2. Whether the existing two-pass pipeline is preserved for the fallback or simplified
3. How the `mode="auto"` parameter flows from `main()` to `apply_threshold()`
4. Whether `score_description()` is kept, removed, or made dead code in the FTS5 path

A developer following the Session 2 checklist would need to make significant architectural decisions about `main()` restructuring that the plan leaves implicit.

**Suggested fix:** Add a brief pseudocode outline of the modified `main()` flow showing the FTS5/fallback branch point and which existing functions are called in each path. Something like:
```
main():
  ... (existing early exits unchanged) ...
  if HAS_FTS5 and match_strategy == "fts5_bm25":
    conn = build_fts_index_from_index(index_path)
    fts_query = build_fts_query(prompt_words)  # uses _COMPOUND_TOKEN_RE
    scored = score_with_body(conn, fts_query, ...)
  else:
    # Legacy path: score_entry() + score_description() (unchanged)
    scored = legacy_keyword_scoring(entries, prompt_words, ...)
  ... (confidence annotations, judge, output) ...
```

---

#### A2 [MEDIUM] score_description() removal/retention is ambiguous

**Section:** Session 4 checklist (line 1050-1063), Phase 2c (lines 329-336)

**Issue:** The plan says "Remove/rewrite `TestDescriptionScoring` if `score_description` removed (or keep if preserved)" -- this leaves the implementer to decide a significant architectural question. Currently:

- `score_description()` is used in `memory_retrieve.py:314` (called from `main()`)
- It is imported unconditionally in `test_adversarial_descriptions.py:28` (line 28: `from memory_retrieve import ... score_description`)
- The plan's Phase 2c explicitly flags the import cascade risk (line 336) but says "keep `score_description` as a deprecated passthrough" OR "change to conditional import"

In the FTS5 path, `score_description()` is never called (FTS5 BM25 handles ranking). In the fallback path, it is needed. The plan should make a definitive call: preserve `score_description()` for the fallback path and clearly state it is dead code in the FTS5 path. This avoids the import cascade risk entirely and requires no test file changes for the import.

**Suggested fix:** Add to Session 2 checklist: "DECISION: `score_description()` is PRESERVED (called only in fallback path). No import changes needed in test files." This removes the conditional-import complexity from Session 4.

---

#### A3 [MEDIUM] 0-result hint injection placement needs more specificity

**Section:** Session 3 checklist (line 1041)

**Issue:** The checklist says "0-result hint injection in `memory_retrieve.py` (only at scoring exit points, not empty-index exits)" but doesn't specify the exact mechanism. Currently, `main()` exits silently with `sys.exit(0)` at lines 320 and 361 when scoring produces no results. The hint should be a `print()` before exit, but the plan doesn't show the exact output format (e.g., `<!-- Use /memory:search <topic> -->`  mentioned at line 314 uses a different format than the `<memory-context>` XML wrapper used for actual results).

Should the hint be inside `<memory-context>` tags or standalone? The current output always starts with `<memory-context ...>` -- a standalone hint comment outside this wrapper would be a format change that downstream consumers might not expect.

**Suggested fix:** Specify the exact output: `print("<!-- Tip: Use /memory:search <query> for broader search -->")` and confirm it goes OUTSIDE `<memory-context>` tags (since no memories are being injected).

---

#### A4 [LOW] Smart wildcard regex is untested for edge cases in the plan

**Section:** Phase 1a (line 168), Decision #3 (lines 61-76)

**Issue:** The `_COMPOUND_TOKEN_RE` regex `r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+"` has a subtle property: a token like `a_b` (3 chars) would be captured by the first alternative, but the `len(cleaned) > 1` check in `build_fts_query()` would keep it. Meanwhile, a single-char token `a` would be captured by the second alternative and filtered out. This seems correct, but tokens like `v2` would match the second alternative (no compound chars) and get wildcard treatment (`"v2"*`), which is probably desired. The plan's validation step (line 1016) lists test cases `user_id`, `React.FC`, `rate-limiting`, `v2.0` but doesn't include edge cases like `_private`, `.hidden`, `-flag` (leading special chars), which the regex's first alternative requires starting with `[a-z0-9]`.

**Suggested fix:** Add to Session 1d validation: test tokens with leading/trailing special chars: `_private`, `.env`, `-v`, `test_`. Verify they are handled gracefully (stripped or captured correctly).

---

### Gaps

#### G1 [HIGH] Config migration path for existing users is missing

**Section:** Configuration (lines 1171-1196), Phase 2a checklist (line 1028)

**Issue:** The plan changes defaults from `match_strategy: "title_tags"` (current default in `assets/memory-config.default.json`, line 52) to `match_strategy: "fts5_bm25"`. It also changes `max_inject` from 5 to 3. However:

1. Existing users who installed the plugin already have a `memory-config.json` in their `.claude/memory/` directory. This file is NOT overwritten by plugin updates -- it persists.
2. The plan's `memory-config.default.json` update (Session 2) only affects new installations.
3. Existing users will remain on `"title_tags"` with `max_inject: 5` forever unless they manually update their config or the code handles the missing `match_strategy` key gracefully.

The plan needs to specify:
- Does the code default to `"fts5_bm25"` when `match_strategy` is absent from the user's config? (This would silently upgrade existing users.)
- Or does the code default to `"title_tags"` for backward compatibility? (This means existing users never get FTS5 unless they manually opt in.)
- What about `max_inject` changing from 5 to 3? Should existing users with explicit `max_inject: 5` keep it?

**Suggested fix:** Add a "Config Migration" subsection specifying: (a) `match_strategy` defaults to `"fts5_bm25"` in code when absent from config (silent upgrade), (b) `max_inject` in code defaults to 3 when absent, but respects explicit user values, (c) document this in the upgrade notes. This is the simplest path that gives existing users FTS5 without breaking their explicit config choices.

---

#### G2 [MEDIUM] `memory_candidate.py` tokenizer inconsistency is acknowledged but has no session assignment

**Section:** Risk Matrix (line 1146)

**Issue:** The plan acknowledges that `memory_candidate.py` has its own tokenizer that won't be updated, but marks it as "ACKNOWLEDGED" with no session assignment. `memory_candidate.py` is used for ACE candidate selection (update/delete operations). If its tokenizer diverges from `memory_retrieve.py`'s new compound-preserving tokenizer, candidates for update may not match the same entries that retrieval finds. This is a consistency issue that could cause confusion when a memory appears in search results but isn't found as an update candidate.

**Suggested fix:** Add a low-priority item to Session 3 or post-ship: "Synchronize `memory_candidate.py` tokenizer with `memory_retrieve.py`'s `_LEGACY_TOKEN_RE` (both use the same simple tokenizer today, just ensure they stay in sync)." Since both currently use the legacy `[a-z0-9]+` pattern, this is a documentation/tracking item, not an urgent code change.

---

#### G3 [MEDIUM] `sys.path.insert(0, ...)` import pattern has a shadowing risk

**Section:** Phase 2b (line 317-319), Session 3 checklist (line 1040)

**Issue:** The plan specifies using `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))` for importing `memory_search_engine.py` from `memory_retrieve.py`. Cross-checked with Gemini 3.1 Pro via clink:

1. When Python runs a script via `python3 /path/to/script.py`, `sys.path[0]` is automatically set to the script's directory. So `import memory_search_engine` would work natively without any `sys.path` manipulation in the hook execution context.
2. `sys.path.insert(0, ...)` places the scripts directory at highest import priority, which could shadow stdlib modules if a file in `hooks/scripts/` shares a name with a stdlib module (e.g., `json.py`, `os.py`). This is unlikely but the pattern is unnecessarily risky.
3. `os.path.abspath(__file__)` doesn't resolve symlinks; `os.path.realpath(__file__)` would be more robust for symlinked plugin installations.

**Suggested fix:** Change the import path fix to either (a) remove it entirely (Python handles this automatically for script execution) and only add `sys.path.append(...)` for test execution, or (b) use `sys.path.insert(1, ...)` with `os.path.realpath(__file__)` to avoid stdlib shadowing. Note this also applies to the existing pattern in `conftest.py:13-14` and `tests/test_*.py` files.

---

### Integration

#### I1 [MEDIUM] Session 3 skill registration needs to account for existing command

**Section:** Session 3 checklist (lines 1037-1043), Phase 2b (line 324)

**Issue:** The plan says to "Reconcile with existing `commands/memory-search.md` (coexist or replace -- implementer decides during implementation)." But `commands/memory-search.md` already exists and is registered in `plugin.json` (line 12: `"./commands/memory-search.md"`). The new `skills/memory-search/SKILL.md` would register as a skill. These are different extension points in Claude Code:

- Commands are user-invocable via `/memory:search`
- Skills are agent-invocable instruction sets

The plan should make a definitive call. Since the existing `/memory:search` command already works as a user-invocable command, and the new skill would provide the FTS5-powered search, the most natural path is: **replace the command with the skill**, updating `plugin.json` to remove the command entry and add the skill entry. Leaving both creates confusion about which `/memory:search` runs.

**Suggested fix:** Decide in the plan: "Replace `commands/memory-search.md` with `skills/memory-search/SKILL.md`. Remove `./commands/memory-search.md` from plugin.json `commands` array, add `./skills/memory-search` to `skills` array. Keep the old command file in the repo but remove its registration." Alternatively, if both should coexist, explain why.

---

#### I2 [MEDIUM] CLAUDE.md update scope is underspecified

**Section:** Session 3 checklist (line 1042), Files Changed (line 1167)

**Issue:** The plan says "Update CLAUDE.md: Key Files table, Architecture section" but the current CLAUDE.md has detailed content about the retrieval system architecture (hook types, key files, security considerations, testing notes). The FTS5 upgrade changes:

- The Key Files table needs `memory_search_engine.py` and `memory_judge.py` (conditional)
- The Architecture hook table description of UserPromptSubmit needs updating (now FTS5-based, not keyword)
- The Security Considerations section needs FTS5 query injection prevention noted
- The Testing section needs FTS5-related test info
- The Quick Smoke Check section needs FTS5-specific checks

None of these are called out specifically. A developer following "Update CLAUDE.md" would likely miss some.

**Suggested fix:** Expand the Session 3 checklist item to: "Update CLAUDE.md: (1) Key Files table: add `memory_search_engine.py`, (2) Architecture: update UserPromptSubmit description to mention FTS5, (3) Security: add FTS5 query injection note, (4) Quick Smoke Check: add FTS5 query test command."

---

### Estimates

#### E1 [MEDIUM] Session 4 (tests + validation) at 8-10 hours may still be tight

**Section:** Session 4 checklist (lines 1050-1063), Schedule (line 1110)

**Issue:** Session 4 includes: (1) fix adversarial test imports, (2) update 6 TestScoreEntry tests, (3) remove/rewrite 5 TestDescriptionScoring tests, (4) update integration tests for new output format with `[confidence:*]`, (5) write new FTS5 tests (7 new test types listed), (6) add bulk memory fixture to conftest.py, (7) write performance benchmark, (8) run the Phase 2d validation gate (compile + full suite + 10+ manual queries + fallback verification).

That is a lot of scope. The 7 new test types alone (FTS5 index build, smart wildcard, body extraction, hybrid scoring, fallback, end-to-end, performance) could each take 30-60 minutes to write and debug. The estimate of 8-10 hours assumes everything goes smoothly. If the test infrastructure needs debugging (e.g., conftest fixtures don't play well with FTS5 in-memory databases, or the performance benchmark reveals issues), 12-14 hours is more realistic.

**Suggested fix:** Consider splitting Session 4 into two sub-sessions: 4a (fix existing tests + update for new format, ~4 hours) and 4b (write new FTS5 tests + benchmark + validation gate, ~6 hours). This gives a natural checkpoint and makes the scope feel less monolithic. Alternatively, keep the current scope but budget 10-12 hours instead of 8-10.

---

#### E2 [LOW] Session 6 (measurement gate) effort depends heavily on memory corpus size

**Section:** Session 6 checklist (lines 1065-1070)

**Issue:** The plan budgets 3-4 hours for 40-50 queries. This assumes the evaluator has a sufficiently large and diverse memory corpus to test against. If the corpus is small (e.g., <20 memories), many queries will trivially return 0-1 results, making precision measurement meaningless. The plan doesn't specify minimum corpus size requirements for the measurement gate to be valid.

**Suggested fix:** Add a prerequisite: "Ensure at least 50 active memories across 4+ categories before running the measurement gate. If corpus is smaller, use the bulk memory fixture from Session 4 to generate synthetic test memories."

---

## Positive Observations

1. **Session dependency graph is excellent.** The corrected session order (S5 before S4) with clear rationale for each edge is one of the strongest parts of the plan. A developer can understand exactly why sessions must be sequential.

2. **Dual tokenizer decision is well-motivated.** The 75% regression scenario (line 176-178) makes the case concretely. This was the most impactful R3 finding and it's well-integrated.

3. **FTS5 fallback is mandatory and well-specified.** The ~15 LOC try/except pattern (lines 143-153) is simple, testable, and prevents a total retrieval outage. Good engineering judgment.

4. **Risk matrix is comprehensive and honest.** The plan acknowledges the adversarial verifier's REJECT of the judge layer and keeps it as a contingency behind a measurement gate. This shows intellectual honesty and pragmatic decision-making.

5. **Performance target is realistic.** Cross-checked via Gemini 3.1 Pro (clink): in-memory FTS5 with 500 documents is comfortably under 100ms. Python interpreter startup (~20-40ms) is the main bottleneck, not FTS5 operations.

6. **Security preservation is explicitly tracked.** Path containment checks, title sanitization, and XML escaping are called out as MUST-preserve items in the session checklists. This is rare and valuable in a rewrite plan.

---

## Overall Assessment

The plan is well-researched, thoroughly verified, and actionable for an experienced developer. The main weaknesses are in transition details (config migration, score_description fate, CLAUDE.md update scope) rather than in the core technical architecture. The session checklists provide a solid roadmap but could be more prescriptive about `main()` restructuring in Session 2 and test splitting in Session 4.

No critical issues were found. The 2 high-severity findings (Session 2 main() rewrite scope and config migration) are both addressable with 1-2 paragraphs of additional specification.

**Recommendation: Proceed with implementation after addressing H1 (A1) and H2 (G1) findings.** The remaining medium/low findings can be addressed during implementation as they are clarification items, not structural problems.
