# S3 Correctness Review

## Summary

Session 3 delivers a well-structured extraction of FTS5 search logic into a shared engine module with clean separation between IO-free core functions and IO-bound CLI/hook wrappers. The S2 deferred fixes (M2, L1, L2) are correctly implemented. However, the SKILL.md documentation has significant contract mismatches with the actual CLI: an undocumented flag (`--include-retired`) that crashes on use, and a completely wrong output schema. There are also data integrity issues in the FTS5 tag round-trip for multi-word tags, and a retired-entry filtering gap in CLI auto mode.

## Severity Ratings
- CRITICAL: F1 (`--include-retired` flag documented but not implemented -- runtime crash)
- HIGH: F2 (SKILL.md output schema does not match actual CLI output), F3 (multi-word tags corrupted in FTS5 round-trip)
- MEDIUM: F4 (CLI auto mode does not filter retired entries), F5 (score_with_body fail-open on unreadable files), F6 (build_fts_index rejects list-type tags)
- LOW: F7 (STOP_WORDS divergence with stale comment), F8 (custom `--root` silently drops all results), F9 (inconsistent all-stopwords behavior between hook and CLI)

## Detailed Findings

### F1: `--include-retired` Flag Documented But Not Implemented
- **Severity**: CRITICAL
- **File(s)**: `skills/memory-search/SKILL.md` lines 50-63, `hooks/scripts/memory_search_engine.py` lines 383-401 (argparse definition)
- **Description**: SKILL.md documents `--include-retired` as a flag in the "Flags" table (line 50) and shows usage examples (lines 55-63, line 129). However, argparse in `main()` does not define this argument. The flag `--include-retired` does not exist in the CLI.
- **Expected Behavior**: `--include-retired` should be accepted by argparse and passed to `_cli_load_entries` to skip retired/archived filtering.
- **Actual Behavior**: Running `python3 memory_search_engine.py --query "test" --root .claude/memory --include-retired` raises `error: unrecognized arguments: --include-retired` and exits with code 2. The SKILL.md instructs the LLM agent to use this flag, causing guaranteed runtime failures when searching retired memories.
- **Recommendation**: Either (a) implement the `--include-retired` flag in argparse and pass it to `_cli_load_entries`, or (b) remove all references to the flag from SKILL.md. Option (a) is strongly preferred since the feature is useful.
- **Cross-verification**: Gemini clink confirmed this is a runtime crash. The integration implementer's own report (temp/s3-integration-output.md line 34) explicitly flagged this as a "Known Gap" for reviewers.

### F2: SKILL.md Output Schema Does Not Match CLI Output
- **Severity**: HIGH
- **File(s)**: `skills/memory-search/SKILL.md` lines 67-95, `hooks/scripts/memory_search_engine.py` lines 416-432
- **Description**: SKILL.md documents the JSON output format with specific field names and structures that do not match the actual CLI output.
  - SKILL.md says `total_results` at top level; CLI outputs `result_count`
  - SKILL.md says `mode` is absent; CLI outputs `mode`
  - SKILL.md says each result has `status`, `snippet`, `updated_at` fields; CLI has none of these
  - SKILL.md omits `score`; CLI outputs `score`
  - The entire "Parsing Results" section (lines 67-103) and "Presenting Results" section (lines 104-133) reference non-existent fields
- **Expected Behavior**: SKILL.md should document the actual output format or the CLI should be extended to produce the documented format.
- **Actual Behavior**: An LLM agent following SKILL.md parsing instructions will attempt to read `status`, `snippet`, and `updated_at` from results that do not contain these keys. This causes silent data loss or hallucinated values.
- **Recommendation**: Synchronize SKILL.md with actual output. The actual CLI format is: `{"query": "...", "mode": "...", "result_count": N, "results": [{"title": "...", "category": "...", "path": "...", "tags": [...], "score": -N.NNN}]}`. Either update SKILL.md to match, or extend the CLI to output the additional fields.

### F3: Multi-Word Tags Corrupted in FTS5 Round-Trip
- **Severity**: HIGH
- **File(s)**: `hooks/scripts/memory_search_engine.py` lines 178-179, 193, 246
- **Description**: Tags are serialized into the FTS5 `tags` column via `" ".join(tags_set)` (line 178/193). When results are read back in `query_fts`, tags are reconstructed via `tags_str.split()` (line 246), which splits on all whitespace. This destroys multi-word tags.
  - Example: Tag `"rate limit"` is joined to string `"rate limit auth"`, then split back to `{"rate", "limit", "auth"}` -- the original tag is lost.
  - Tags with spaces are possible: `memory_write.py` line 320 replaces commas with spaces in tag sanitization, creating multi-word tags like `"rate limit"`.
- **Expected Behavior**: Tags should survive the FTS5 round-trip without data loss.
- **Actual Behavior**: Multi-word tags are split into separate words. This corrupts tag metadata in both CLI output and hook output (`_output_results` line 267-268 in memory_retrieve.py).
- **Recommendation**: Use a delimiter that cannot appear in tags for serialization (e.g., `","` or `"|"`). Reconstruct with matching `split(",")` or `split("|")`. Since tags are comma-split from index lines but write-side replaces commas with spaces, a pipe `|` delimiter is safest.
- **Note on impact**: For FTS5 *search* purposes, the tag splitting is actually harmless (each word is still indexed). The corruption only affects the cosmetic tag metadata in output. However, this could cause confusion when users see incorrect tags in search results.

### F4: CLI Auto Mode Does Not Filter Retired Entries
- **Severity**: MEDIUM
- **File(s)**: `hooks/scripts/memory_search_engine.py` lines 308-346 (`_cli_load_entries`)
- **Description**: The retired-entry filter (`data.get("record_status") == "retired"`) is only applied inside the `if mode == "search":` block (line 334). In `auto` mode, entries stream directly from `index.md` without any retired check. Additionally, the `archived` status is never checked in either mode.
- **Expected Behavior**: Retired (and archived) entries should be excluded from results in all CLI modes unless `--include-retired` is specified.
- **Actual Behavior**: CLI auto mode returns retired entries if they are still present in `index.md`. While `index.md` should not contain retired entries after a rebuild, a stale index can include them.
- **Recommendation**: Either (a) read JSON files in auto mode too for retired check (more correct but slower), or (b) document the limitation that auto mode trusts index.md and does not check retired status. Option (a) is safer. Also add check for `"archived"` status alongside `"retired"`.

### F5: score_with_body Fail-Open on Unreadable JSON Files
- **Severity**: MEDIUM
- **File(s)**: `hooks/scripts/memory_retrieve.py` lines 204-213
- **Description**: When a JSON file cannot be read (FileNotFoundError, JSONDecodeError, OSError), `score_with_body` sets `body_bonus = 0` and continues, treating the entry as NOT retired. The comment explicitly says "assume not retired, no body bonus" (line 211). This is a conscious fail-open design.
- **Expected Behavior**: Entries with unreadable JSON files should not be assumed active, since their retired status is unknown.
- **Actual Behavior**: An unreadable file that IS retired will be included in results because its retired flag cannot be checked. Under the M2 fix's intent to check ALL entries for retired status, this is a gap.
- **Recommendation**: Consider fail-closed behavior: exclude entries whose JSON cannot be read. The risk of a false negative (missing a valid entry due to transient I/O failure) is lower than the risk of injecting a retired entry into context. At minimum, add a stderr warning when a file is unreadable in this context.
- **Note**: This is a deliberate design choice and has been present since before S3. The S3 M2 fix expanded the loop to check all entries but preserved the fail-open semantics. Codex clink also flagged this.

### F6: build_fts_index Rejects List-Type Tags
- **Severity**: MEDIUM
- **File(s)**: `hooks/scripts/memory_search_engine.py` lines 177-179, 192-194
- **Description**: `build_fts_index` handles tags that are `set` (via `" ".join()`) or `str` (passthrough), but NOT `list`. The check is `isinstance(e["tags"], set)` with an else fallback to `e.get("tags", "")`. If tags is a `list`, the fallback returns the list object, which SQLite cannot bind, raising `InterfaceError: Error binding parameter 2: type 'list' is not supported`.
  - Currently not triggered because `parse_index_line` in `memory_search_engine.py` returns tags as `set`.
  - BUT `memory_candidate.py`'s `parse_index_line` returns tags as `list` (line 109). If anyone ever calls `build_fts_index` with candidate-parsed entries, it will crash.
  - This is a fragile API contract -- a public function that silently fails for a reasonable input type.
- **Expected Behavior**: `build_fts_index` should accept any iterable of strings for tags.
- **Actual Behavior**: Crashes with `InterfaceError` when tags is a list.
- **Recommendation**: Broaden the check: `" ".join(e["tags"]) if isinstance(e.get("tags"), (set, list, tuple)) else e.get("tags", "")`.

### F7: STOP_WORDS Divergence and Stale Comment
- **Severity**: LOW
- **File(s)**: `hooks/scripts/memory_candidate.py` line 22, `hooks/scripts/memory_search_engine.py` lines 27-40
- **Description**: `memory_candidate.py` has 87 stop words; `memory_search_engine.py` has 91 (added `'as'`, `'am'`, `'us'`, `'vs'` in S3 for the 2-char token minimum). The comment in `memory_candidate.py` line 22 says "Same stop words as memory_retrieve.py" which is now stale -- retrieve imports from search_engine which has 4 additional words.
- **Expected Behavior**: Comment should accurately reflect the relationship.
- **Actual Behavior**: Comment is misleading. However, the CLAUDE.md tokenizer note (line 49) correctly documents the intentional divergence in token length thresholds, so the STOP_WORDS difference is consistent with the 3-char minimum in candidate (the 4 extra words are all 2-char, which candidate would filter by length anyway).
- **Recommendation**: Update the comment to: "Stop words for candidate scoring. Subset of memory_search_engine.py STOP_WORDS; 2-char words omitted since this tokenizer uses len(w) > 2 minimum."

### F8: Custom `--root` Path Silently Drops All Results
- **Severity**: LOW
- **File(s)**: `hooks/scripts/memory_search_engine.py` line 329
- **Description**: `_cli_load_entries` derives `project_root` as `memory_root.parent.parent`. This assumes `--root` always points to a `.claude/memory` path structure. If a user passes `--root /some/custom/path`, then `project_root = /some`, and index paths like `.claude/memory/decisions/foo.json` resolve to `/some/.claude/memory/decisions/foo.json`, which fails the containment check against `memory_root_resolved = /some/custom/path`. All entries are silently dropped.
- **Expected Behavior**: Either validate the `--root` path structure or derive project_root from the actual index path prefix.
- **Actual Behavior**: All entries silently filtered out with no error message.
- **Recommendation**: Validate that `memory_root` ends with `.claude/memory` (or at least warn). Alternatively, accept `--project-root` as a separate argument and derive paths from that.

### F9: Inconsistent All-Stopwords Query Behavior
- **Severity**: LOW
- **File(s)**: `hooks/scripts/memory_retrieve.py` lines 383-384, `hooks/scripts/memory_search_engine.py` lines 373-375
- **Description**: When all query tokens are stop words and no FTS query can be built:
  - Hook path: exits silently with code 0, no output (line 384)
  - CLI path: `build_fts_query` returns `None`, `cli_search` returns `[]`, main() outputs `{"query": "...", "mode": "...", "result_count": 0, "results": []}` (or "No results found." in text mode)
  - The hook exits without the "No matching memories" hint, which is correct (meaningless query). But the CLI outputs a normal empty-results JSON.
- **Expected Behavior**: Both paths should handle meaningless queries consistently.
- **Actual Behavior**: Slightly different UX but not functionally broken. The hook's silent exit is intentional and correct. The CLI's normal empty output is also reasonable.
- **Recommendation**: No action needed. This is acceptable divergence -- hook and CLI serve different contexts.

## S2 Deferred Fix Verification

### M2 (retired beyond top_k): PASS
**Evidence**: `score_with_body()` in `memory_retrieve.py` lines 199-220 now loops over ALL entries in `initial` (post-containment filter at line 194-197) to check retired status, not just `top_k_paths`. The loop at line 202 iterates `for result in initial:` with no slice limit. Retired entries are marked with `_retired = True` (line 207) and filtered at line 220. Body extraction is still limited to `initial[:top_k_paths]` (line 224) for performance. The M2 fix is correctly implemented.

**Caveat**: The `initial` list itself is limited to `query_fts(conn, fts_query, limit=top_k_paths * 3)` (line 184), so at most `3 * top_k_paths` entries are checked. If there are more than ~30 matching entries and retired ones rank beyond this limit, they could still slip through. This is an acceptable tradeoff given the FTS5 limit.

### L1 (double-read): PASS
**Evidence**: In `memory_retrieve.py` `main()`, index entries are parsed once at lines 349-356 into `entries: list[dict]`. The FTS5 path at line 370 calls `build_fts_index(entries)` with these pre-parsed entries. The legacy path at lines 405-415 also iterates over the same `entries` list. No second read of `index.md` occurs. The comment at line 348 explicitly notes "L1 fix: eliminates double-read of index.md".

### L2 (coupled format): PASS
**Evidence**: `build_fts_index` in `memory_search_engine.py` lines 159-198 accepts `entries: list[dict]` as its first argument. No file path or IO is performed. The function signature is `build_fts_index(entries: list[dict], include_body: bool = False)`. The old `build_fts_index_from_index(index_path)` no longer exists. Both the hook (memory_retrieve.py line 370) and CLI (`_cli_load_entries` + `cli_search` line 369) pass pre-parsed entry dicts. The decoupling is clean.

## Cross-File Consistency

### Import Symbols (Criterion 14): PASS
`memory_retrieve.py` lines 24-36 imports exactly: `BODY_FIELDS`, `CATEGORY_PRIORITY`, `HAS_FTS5`, `STOP_WORDS`, `apply_threshold`, `build_fts_index`, `build_fts_query`, `extract_body_text`, `parse_index_line`, `query_fts`, `tokenize`. All of these are defined in `memory_search_engine.py`. No unused imports, no missing imports.

### STOP_WORDS Duplication (Criterion 15): INTENTIONAL
`memory_candidate.py` has its own `STOP_WORDS` with 87 entries. This is intentional because: (a) `memory_candidate.py` is stdlib-only and should not import from `memory_search_engine.py`, (b) the 4 missing words (`as`, `am`, `us`, `vs`) are all 2-char and would be filtered by candidate's `len(w) > 2` anyway. However, the comment "Same stop words as memory_retrieve.py" is now stale (see F7).

### parse_index_line Duplication (Criterion 16): INTENTIONAL, DIFFERENT RETURN TYPES
- `memory_search_engine.py` returns: `{"category": str, "title": str, "path": str, "tags": set[str], "raw": str}`
- `memory_candidate.py` returns: `{"category_display": str, "title": str, "path": str, "tags": list[str]}`
- Key differences: `category` vs `category_display` naming, `set` vs `list` for tags, `raw` field present only in engine. These are intentionally different because they serve different consumers. The engine's `set` tags enable O(1) lookups in scoring; the candidate's `list` tags preserve insertion order for display.

## Self-Critique

**Arguments against my findings:**

1. *F1 may be low severity because LLMs can adapt.* Counter: No. Argparse will hard-exit with code 2 before any output. The LLM receives an error message, not search results. The SKILL.md explicitly instructs using this flag, making it a guaranteed failure path.

2. *F2 may be mitigated by LLM flexibility.* Partially true -- LLMs can parse unexpected JSON structures. But the SKILL.md instructs specific field extraction (`status`, `snippet`, `updated_at`) which will fail. The LLM may hallucinate these fields or present incomplete results.

3. *F3 multi-word tags may be rare in practice.* True -- most tags are single words like "auth", "jwt", "docker". The `memory_write.py` sanitization replaces commas with spaces (creating "rate limit" from "rate,limit"), but this is an unusual input pattern. However, rare does not mean impossible, and the fix is simple.

4. *F4 auto mode trusting index.md for retired status is by design.* Possible -- the index rebuild process filters inactive entries, so a fresh index should not contain retired entries. However, the docstring says "filters retired entries" without qualifying that this only applies to search mode.

5. *F5 fail-open is a reasonable design choice.* Yes -- failing closed could cause valid entries to disappear during transient I/O issues. The existing comment acknowledges this tradeoff. However, the M2 fix's explicit goal was to check ALL entries for retired status, and fail-open contradicts that goal.

6. *F6 list tags may never be passed to build_fts_index.* Currently true -- all callers use `parse_index_line` from the engine which returns sets. But the function is exported as a public API and the type annotation says `list[dict]` not `list[EngineEntry]`. Defensive coding should handle this.

7. *F8 custom root path is an unlikely use case.* True -- the `--root` flag's help text says "Path to .claude/memory directory" which implies the standard path. But the code should either validate this or handle non-standard paths gracefully.

**Synthesis:** Findings F1 and F2 are the highest priority because they represent a broken contract between SKILL.md and the CLI -- the skill will not function correctly as documented. F3 is a data integrity issue that should be fixed but has limited practical impact. F4-F9 are design improvements.
