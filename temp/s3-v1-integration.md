# S3 V1 Integration Verification

**Verifier:** Integration Tester (Round 1)
**Date:** 2026-02-21
**Files examined:** memory_search_engine.py, memory_retrieve.py, SKILL.md, plugin.json, CLAUDE.md, memory_candidate.py
**External reviewers:** Gemini CLI (codereviewer), Codex CLI (codereviewer)

---

## Check Results

### Import Chain: PASS
### SKILL.md <-> CLI Contract: CONDITIONAL PASS (2 minor issues)
### Plugin Manifest: PASS
### CLAUDE.md Accuracy: PASS
### Data Flow: CONDITIONAL PASS (1 medium issue)
### S2 Fixes: [M2: PASS] [L1: PASS] [L2: PASS]

---

## Detailed Findings

### 1. Import Chain Verification: PASS

**What was checked:** `memory_retrieve.py` lines 22-36 import 11 symbols from `memory_search_engine.py` via `sys.path.insert(0, str(Path(__file__).resolve().parent))`.

**Imported symbols (all 11 verified to exist in engine):**
- Constants: `BODY_FIELDS`, `CATEGORY_PRIORITY`, `HAS_FTS5`, `STOP_WORDS`
- Functions: `apply_threshold`, `build_fts_index`, `build_fts_query`, `extract_body_text`, `parse_index_line`, `query_fts`, `tokenize`

**sys.path.insert(0) safety:** The pattern uses `Path(__file__).resolve().parent` which resolves symlinks to the canonical installation directory. The `hooks/scripts/` directory contains only `memory_*.py` files -- no stdlib name collisions exist. The `insert(0, ...)` pattern is established convention in this codebase (also used by `memory_draft.py` and `memory_validate_hook.py`). Gemini CLI flagged this as theoretically risky (a file named `json.py` in the same directory would shadow stdlib), but this is a theoretical concern with no practical risk given the controlled file naming in the directory.

**No unused imports, no missing imports.** All 11 symbols are referenced in the retrieve hook code.

### 2. SKILL.md <-> CLI Contract: CONDITIONAL PASS

**Critical issues from reviews (all now FIXED):**
- `--include-retired` flag: NOW IMPLEMENTED in argparse (line 437) and wired to `_cli_load_entries`
- Output schema: NOW MATCHES SKILL.md -- `total_results`, `status`, `snippet`, `updated_at` fields all present in JSON output (lines 464-475)
- Error output: NOW includes `query` field (lines 450-451, 456)
- Title sanitization: NOW applied via `_sanitize_cli_title()` (line 468)
- `--max-results` clamping: NOW clamped to [1, 30] (lines 446-447)
- Shell quoting: SKILL.md Rule 5 NOW uses single quotes with proper `'\''` escaping guidance (line 159)

**Remaining issues:**

**I1: Example command uses double quotes (MEDIUM)**
- **File:** `skills/memory-search/SKILL.md` line 38
- **Description:** The example command template at line 38 shows `--query "<user query>"` using double quotes, which contradicts Rule 5 (line 159) that mandates single quotes. The second example at line 58 also uses double quotes: `--query "<user query>"`. An LLM agent may copy the example format rather than the rule, re-opening the shell expansion vulnerability that Rule 5 was designed to close.
- **Gemini CLI corroboration:** Rated this as Critical, noting that double quotes allow `$(...)`, backtick, and `$VAR` expansion.
- **Recommendation:** Change example commands to use single quotes: `--query '<user query>'`

**I2: `--format` flag undocumented in SKILL.md (LOW)**
- **File:** `hooks/scripts/memory_search_engine.py` line 439
- **Description:** The engine argparse defines `--format` with choices `["json", "text"]` defaulting to `"json"`. SKILL.md does not document this flag. Since JSON is the default and is what SKILL.md expects, this is harmless -- the SKILL.md correctly omits a flag whose default behavior is what the agent needs.
- **Gemini CLI assessment:** Confirmed this is correct and harmless: "Omitting default CLI flags from agent instructions saves tokens and reduces invocation errors."
- **Recommendation:** No action needed.

**All flags in SKILL.md verified against engine argparse:**
| SKILL.md Flag | Engine argparse | Match? |
|--------------|----------------|--------|
| `--query "<terms>"` | `--query/-q required=True` | YES |
| `--root <path>` | `--root/-r required=True` | YES |
| `--mode search` | `--mode/-m choices=["auto","search"]` | YES |
| `--include-retired` | `--include-retired action="store_true"` | YES |
| `--max-results N` | `--max-results/-n type=int` | YES |
| (not documented) | `--format/-f choices=["json","text"]` | N/A (default OK) |

### 3. Plugin Manifest: PASS

**Verified:**
- `./skills/memory-search` is registered in `.claude-plugin/plugin.json` skills array (line 16)
- `./commands/memory-search.md` is NOT in the commands array (only `memory.md`, `memory-config.md`, `memory-save.md` are registered)
- `skills/memory-search/SKILL.md` EXISTS on disk at the expected path (verified via `ls`)
- The old `commands/memory-search.md` file still EXISTS on disk but is unregistered

**Note on stale command file (LOW):**
The legacy `commands/memory-search.md` describes a completely different search approach (Glob+Grep fallback, manual index scanning, different scoring rules). While it is correctly unregistered from `plugin.json`, its presence on disk could confuse LLM agents that discover files by scanning directories. Both Gemini and Codex reviewers flagged this as a cleanup item.

### 4. CLAUDE.md Accuracy: PASS

All Session 3 updates to CLAUDE.md verified against actual code:

| CLAUDE.md Claim | Verified Against | Status |
|----------------|-----------------|--------|
| Key Files table lists `memory_search_engine.py` as "Shared FTS5 engine, CLI search interface" with deps "stdlib + sqlite3" | Engine file header, imports | ACCURATE |
| Key Files table lists `memory_retrieve.py` as "FTS5 BM25 retrieval hook, injects context (fallback: legacy keyword)" with deps "stdlib + memory_search_engine" | Retrieve hook code (FTS5 path lines 365-384, legacy path lines 386-466) | ACCURATE |
| Architecture table UserPromptSubmit row says "FTS5 BM25 keyword matcher injects relevant memories (fallback: legacy keyword)" | Code confirms FTS5 primary path with `HAS_FTS5` fallback | ACCURATE |
| Security Considerations #5: "FTS5 query injection -- Prevented: alphanumeric + `_.-` only, all tokens quoted. In-memory database. Parameterized queries." | `build_fts_query()` line 216: `re.sub(r'[^a-z0-9_.\-]', '', ...)`, line 221-223: tokens wrapped in `"..."`, `query_fts()` line 241-242: `MATCH ?` parameterized, line 170: `sqlite3.connect(":memory:")` | ACCURATE |
| Quick Smoke Check includes `memory_search_engine.py` compile check and runtime search | Lines 130, 138 | ACCURATE |
| Tokenizer note: candidate uses `len(w) > 2`, engine/retrieve uses `len(w) > 1` | `memory_candidate.py` line 92: `len(word) > 2`, `memory_search_engine.py` line 100: `len(w) > 1` | ACCURATE |

**Codex CLI corroboration:** Confirmed all 6 points accurate.

### 5. Data Flow Tracing: CONDITIONAL PASS

**Trace 1: Hook auto-inject path (user prompt -> context injection)**

```
User prompt (stdin JSON)
  -> main() parses hook_input
  -> index.md read ONCE (L1 fix, lines 349-356)
  -> parse_index_line() from engine -> entries list[dict]
  -> tokenize() from engine (compound, legacy=False) -> prompt_tokens
  -> build_fts_query() from engine -> fts_query string
  -> build_fts_index(entries) from engine (L2 fix: data-coupled, not file-coupled)
  -> score_with_body() [in retrieve.py]
    -> query_fts() from engine -> initial ranked results
    -> path containment on ALL entries (security)
    -> retired check on ALL entries (M2 fix) -- BUT only checks "retired", NOT "archived"
    -> body extraction for top-K only (performance)
    -> apply_threshold() from engine -> final results
  -> _output_results() -> XML context to stdout
```

**Trace 2: CLI search path (skill invocation -> JSON output)**

```
python3 memory_search_engine.py --query "..." --root .claude/memory --mode search
  -> argparse -> main()
  -> cli_search()
    -> _cli_load_entries() reads index.md, reads JSON files for body
      -> Filters retired AND archived entries (status check, line 349)
    -> build_fts_index(entries, include_body=True) -> FTS5 with body column
    -> tokenize() -> prompt tokens
    -> build_fts_query() -> fts_query
    -> query_fts() -> results
    -> apply_threshold(mode="search") -> capped results
    -> Enriches with status/snippet/updated_at
  -> JSON output to stdout
```

**I3: Archived status filtering inconsistency (MEDIUM)**
- **Files:** `memory_retrieve.py` line 206, `memory_search_engine.py` line 349
- **Description:** The hook path (`score_with_body()`) checks only for `record_status == "retired"` (line 206) when filtering entries. It does NOT check for `"archived"`. The CLI path (`_cli_load_entries()`) checks for both `("retired", "archived")` (line 349). This means an archived memory that is still present in `index.md` could be auto-injected into context by the hook but would be excluded from CLI search results. The inconsistency means the same query can produce different result sets from the two paths.
- **Codex CLI corroboration:** Confirmed this with a controlled repro: "hook returned archived entry; CLI --mode search returned 0 results."
- **Recommendation:** Add `"archived"` to the retired check in `score_with_body()` at line 206: `if data.get("record_status") in ("retired", "archived"):`. Also add `"archived"` to the legacy path `check_recency()` function at line 122.

**Note on intentional hook/CLI divergence (not a bug):**
The hook and CLI use different body-matching strategies by design. The hook does title+tags FTS5 first, then applies body bonus only to top-K candidates (performance-optimized for hook timeout). The CLI search mode builds a full-body FTS5 index for comprehensive search. This means body-only matches appear in CLI but not hook results. This is an intentional precision/latency tradeoff, not a bug. CLAUDE.md should arguably document this difference explicitly.

### 6. S2 Deferred Fix Verification

**M2 (Retired entries beyond top_k_paths): PASS**

Evidence: `score_with_body()` in `memory_retrieve.py` lines 199-220:
- Line 202: `for result in initial:` -- iterates ALL path-contained entries, no slice limit
- Line 206-207: Checks `record_status == "retired"` and marks `_retired = True`
- Line 220: `initial = [r for r in initial if not r.get("_retired")]` -- filters all retired
- Line 224: Body extraction limited to `initial[:top_k_paths]` (performance, not filtering)
- The `initial` list is bounded by `query_fts(conn, fts_query, limit=top_k_paths * 3)` at line 184, which is an acceptable upstream limit.

**Caveat:** Only checks `"retired"`, not `"archived"` (see I3 above). The M2 fix's intent was specifically about retired entries, so this is PASS for M2 but creates the I3 issue.

**L1 (Single index.md read): PASS**

Evidence: `memory_retrieve.py` `main()`:
- Lines 349-356: Index parsed once into `entries: list[dict]`
- Line 370: FTS5 path uses `build_fts_index(entries)` -- no re-read
- Lines 405-415: Legacy path iterates same `entries` list -- no re-read
- Line 348 comment: "L1 fix: eliminates double-read of index.md"
- No other `index_path.read_text()` or `open(index_path)` calls exist in `main()`.

**L2 (build_fts_index accepts list[dict] not file path): PASS**

Evidence: `memory_search_engine.py` line 159:
- Signature: `def build_fts_index(entries: list[dict], include_body: bool = False) -> "sqlite3.Connection":`
- No file path parameter, no IO operations inside the function
- Hook caller (line 370): `build_fts_index(entries)` -- passes pre-parsed entries
- CLI caller (line 399): `build_fts_index(entries, include_body=include_body)` -- passes pre-parsed entries
- The old `build_fts_index_from_index(index_path)` no longer exists

---

## Issues Found

### Remaining Issues (sorted by severity)

| # | Severity | Issue | File(s) | Status |
|---|----------|-------|---------|--------|
| I1 | MEDIUM | SKILL.md example commands use double quotes contradicting Rule 5 single-quote mandate | `skills/memory-search/SKILL.md:38,58` | OPEN |
| I3 | MEDIUM | Hook checks only `"retired"`, CLI checks `"retired"+"archived"` -- archived entries leak through hook | `memory_retrieve.py:206`, `memory_search_engine.py:349` | OPEN |
| I2 | LOW | `--format` flag in engine not documented in SKILL.md | `memory_search_engine.py:439` | ACCEPTABLE (default=json is correct) |
| I4 | LOW | Multi-word tags corrupted in FTS5 round-trip (`" ".join()` then `.split()`) | `memory_search_engine.py:179,193,246` | OPEN (cosmetic; search still works) |
| I5 | LOW | Stale `commands/memory-search.md` exists on disk (unregistered but discoverable) | `commands/memory-search.md` | OPEN (cleanup item) |
| I6 | LOW | `memory_candidate.py` comment "Same stop words as memory_retrieve.py" is stale | `memory_candidate.py:22` | OPEN (documentation) |

### Issues Fixed Since Reviews

All CRITICAL and HIGH issues from the three review reports have been resolved in the current code:
- `--include-retired` flag implemented (was CRITICAL in architecture + correctness reviews)
- Output schema synchronized (was HIGH in correctness review)
- CLI title sanitization added via `_sanitize_cli_title()` (was MEDIUM in security review)
- Shell quoting guidance switched to single quotes (was HIGH in security review)
- `--max-results` clamping added (was LOW in security review)
- Error output includes `query` field (was HIGH in correctness review)

---

## Self-Critique

**Arguments against my findings:**

1. *I1 (example quoting) is not a real risk because the LLM reads Rule 5 and follows it.* Counter: LLMs pattern-match from examples at least as often as from rules. The contradiction creates ambiguity. A simple fix (change `"` to `'` in examples) eliminates the ambiguity entirely. The cost of fixing is near-zero.

2. *I3 (archived leak) is not a real risk because archived entries should not be in index.md.* Partially valid -- `memory_index.py` rebuild filters inactive entries, so a fresh index should not contain archived entries. However, a stale index (e.g., after a manual edit or failed rebuild) could include them, and the hook would inject them into context. The same argument about stale index was explicitly rejected for retired entries (that is why M2 fix was implemented), so consistency demands the same treatment for archived.

3. *I4 (multi-word tag round-trip) is rare in practice.* True -- most tags are single words. But the fix is simple (use comma or pipe delimiter instead of space) and prevents a class of data corruption. The correctness review also rated this HIGH, though I rate it LOW because the search functionality itself is unaffected (individual tag words are still indexed).

4. *I should have rated I1 higher given the shell injection context.* Fair point. The security review rated the original double-quote guidance as HIGH. My MEDIUM rating accounts for Rule 5 already being fixed (the rule text is correct; only the examples are wrong). If an LLM follows the rule, it is safe. The example contradiction reduces confidence but does not guarantee exploitation.

**Synthesis:** The integration is fundamentally sound. The S2 deferred fixes are correctly implemented. The SKILL.md/CLI contract is synchronized. The remaining issues are two MEDIUM items (example quoting, archived filtering) and four LOW items that represent cleanup/hardening opportunities rather than functional gaps.

---

## External Review Summary

| Reviewer | Key Findings | Agreement with My Analysis |
|----------|-------------|---------------------------|
| Gemini CLI | Example quoting contradiction (Critical), multi-word tag corruption (High), stale command file (Medium), sys.path.insert safety (Low) | Agrees on I1, I4, I5. Rates I1 higher than I do. Confirmed SKILL.md/CLI contract now holds. |
| Codex CLI | Archived filtering inconsistency (Medium), hook/CLI body-matching divergence (Low), CLAUDE.md accuracy (all 6 points PASS), plugin.json registration (PASS) | Agrees on I3 with empirical repro. Confirmed all CLAUDE.md claims accurate. Notes body-matching divergence as intentional design. |

---

## Verdict: CONDITIONAL PASS

The integration is correct and functional. All critical and high-severity issues from the S3 review cycle have been fixed. The S2 deferred fixes (M2, L1, L2) are correctly implemented. The SKILL.md/CLI contract is synchronized. CLAUDE.md accurately reflects the current codebase.

**Conditions for full PASS:**
1. Fix SKILL.md example commands to use single quotes (I1) -- prevents shell expansion ambiguity
2. Add `"archived"` to hook retired-entry check (I3) -- aligns hook/CLI filtering behavior

**Recommended but not blocking:**
- Fix multi-word tag round-trip (I4)
- Delete stale `commands/memory-search.md` (I5)
- Update stale comment in `memory_candidate.py` (I6)
