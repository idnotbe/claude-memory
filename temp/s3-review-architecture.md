# S3 Architecture Review

## Summary

The Session 3 refactoring successfully extracts shared FTS5 search logic into a clean, IO-free core module (`memory_search_engine.py`) with well-drawn module boundaries and no circular dependencies. However, the parallel implementation process introduced a **critical contract mismatch** between the SKILL.md documentation and the engine's actual CLI interface -- the skill documents a flag (`--include-retired`) and an output schema (with `snippet`, `status`, `updated_at`, `total_results`) that do not exist in the engine. This will cause runtime failures when the LLM invokes search via the skill.

## Severity Ratings
- CRITICAL: SKILL.md / engine contract mismatch (flag + schema)
- HIGH: none
- MEDIUM: Stale legacy command file creates conflicting guidance; missing CLI contract tests
- LOW: `_check_path_containment` duplication; `memory_candidate.py` constant duplication; `sys.path.insert(0, ...)` stdlib shadowing risk (theoretical)

## Detailed Findings

### 1. SKILL.md / Engine Contract Mismatch
- **Severity**: CRITICAL
- **File(s)**: `skills/memory-search/SKILL.md` (lines 50, 55, 62, 72-95, 128, 144), `hooks/scripts/memory_search_engine.py` (lines 385-432)
- **Description**: The skill documentation and the engine implementation were developed in parallel and never reconciled. There are three distinct sub-issues:
  - **(a) Missing `--include-retired` flag.** SKILL.md documents this flag at 5 locations (flags table, example section, zero-results suggestions). The engine's argparse does not define it. Running with `--include-retired` produces `error: unrecognized arguments`. This is a runtime-breaking failure for the "search retired memories" flow.
  - **(b) Output schema divergence.** SKILL.md documents a response with fields `total_results`, `snippet`, `status`, `updated_at`. The engine actually outputs `result_count` (not `total_results`), `score`, and does not include `snippet`, `status`, or `updated_at`. An LLM parsing the response per the skill's schema will either fail to find expected fields or hallucinate their values.
  - **(c) Error output schema divergence.** SKILL.md documents error output as `{"error": "...", "query": "..."}`. The engine outputs `{"error": "...", "path": "..."}` (directory not found) or `{"error": "...", "results": []}` (FTS5 unavailable). Neither includes `query`.
- **Recommendation**: Choose one of:
  - (A) Update `memory_search_engine.py` to match SKILL.md: add `--include-retired` argparse flag, modify `_cli_load_entries` to conditionally skip the retired filter, add `snippet`/`status`/`updated_at` fields to JSON output, rename `result_count` to `total_results`, include `query` in error output.
  - (B) Update `SKILL.md` to match the engine: remove `--include-retired` references, document the actual output schema with `result_count`/`score`, remove `snippet`/`status`/`updated_at` field documentation, fix error output schema.
  - Option (A) is preferred as it delivers the intended functionality.

### 2. Stale Legacy Command File Creates Conflicting Guidance
- **Severity**: MEDIUM
- **File(s)**: `commands/memory-search.md`, `README.md` (lines 148, 155-156), `.claude-plugin/plugin.json`
- **Description**: The old `commands/memory-search.md` file still exists on disk (intentionally kept per implementer report) but is unregistered from `plugin.json`. It describes a completely different search approach (Glob+Grep fallback, manual index scanning) with different scoring rules. Meanwhile, `README.md` still references `/memory:search` with the old semantics (lines 148, 155-156). This creates three conflicting search interface descriptions in the repository: the old command file, README, and the new SKILL.md.
- **Recommendation**: Delete `commands/memory-search.md` or add a prominent deprecation header pointing to the skill. Update README.md to reflect the new FTS5-based search skill. A single canonical search interface reduces user and maintainer confusion.

### 3. No CLI Contract Tests
- **Severity**: MEDIUM
- **File(s)**: `tests/test_v2_adversarial_fts5.py`
- **Description**: The existing tests cover the engine's internal library functions (tokenizer, FTS5 index, query builder) but there are no tests for the CLI interface: argparse flags, JSON output schema, error output format. This is what allowed the SKILL.md/engine drift to go undetected. The `s3-integration-output.md` report explicitly identified the `--include-retired` gap but it was never addressed.
- **Recommendation**: Add subprocess-level tests that invoke `memory_search_engine.py` as a CLI tool and validate: (a) accepted flags match SKILL.md documentation, (b) JSON output keys match documented schema, (c) error output format is consistent.

### 4. `_check_path_containment` Duplication
- **Severity**: LOW
- **File(s)**: `hooks/scripts/memory_search_engine.py` (line 296), `hooks/scripts/memory_retrieve.py` (line 160)
- **Description**: Identical 6-line path containment function exists in both files. The implementer argues "don't over-DRY security-critical code" to keep each file self-contained. This is a defensible position -- the function is trivial and unlikely to diverge. However, if a vulnerability is found in the containment logic (e.g., symlink bypass), patching one copy and missing the other creates a real security gap.
- **Recommendation**: Accept current state. The function is already importable from the engine module. If it ever needs patching, the reviewer should note both copies. Adding a test that verifies both copies behave identically would be a cheap safety net.

### 5. `memory_candidate.py` Constant Duplication
- **Severity**: LOW
- **File(s)**: `hooks/scripts/memory_candidate.py` (lines 22-33, 78-81), `hooks/scripts/memory_search_engine.py` (lines 27-40, 53-56)
- **Description**: `memory_candidate.py` duplicates `STOP_WORDS` and `_INDEX_RE` from the engine. The tokenizer difference (3+ chars vs 2+ chars) is intentional and well-documented (CLAUDE.md tokenizer note, inline comment at candidate.py line 71-74). However, `STOP_WORDS` and `_INDEX_RE` are format invariants -- if the index format changes, three files must be updated in lockstep.
- **Recommendation**: Accept current state. `memory_candidate.py` deliberately avoids external dependencies ("No external dependencies (stdlib only)"). Introducing a shared constants module would add coupling for minimal benefit given the stability of these constants. The CLAUDE.md tokenizer note adequately documents the intentional difference.

### 6. `sys.path.insert(0, ...)` Import Pattern
- **Severity**: LOW
- **File(s)**: `hooks/scripts/memory_retrieve.py` (line 22)
- **Description**: Prepending `hooks/scripts/` to `sys.path` ahead of stdlib modules could theoretically shadow standard library modules if a file named `json.py`, `os.py`, etc. were created in that directory. However, this pattern is already used by `memory_draft.py` and `memory_validate_hook.py` (established convention), the directory contains only `memory_*.py` files (no stdlib name collisions), and `sys.path.append()` would risk the opposite problem: a global `memory_search_engine` package shadowing the local sibling module.
- **Recommendation**: Accept current state. The `insert(0, ...)` pattern is appropriate here because the hook runs from arbitrary cwd and must guarantee the sibling module is found first. Document the convention if not already done.

## Architecture Strengths

1. **Clean IO-free core.** The core search functions (`build_fts_index`, `build_fts_query`, `query_fts`, `apply_threshold`, `tokenize`, `parse_index_line`) are pure functions with no file I/O, making them testable and reusable across both the hook and CLI contexts. This is textbook good design.

2. **Excellent decoupling via `build_fts_index(entries: list[dict])`.** The L2 fix replaced a file-coupled function with a data-coupled one. Both callers (hook and CLI) can prepare entries differently (hook reads index once and parses, CLI reads index + JSON bodies) then feed the same builder. This is the most impactful architectural improvement in Session 3.

3. **No circular dependencies.** The dependency graph is strictly one-directional: `memory_retrieve.py` imports from `memory_search_engine.py`. The engine imports nothing from retrieve. `memory_candidate.py` remains fully independent.

4. **M2 fix correctly broadens retired-entry checking.** `score_with_body()` now checks retired status on all path-contained FTS5 results, not just the top-K. The performance cost (~20 small JSON reads) is well within the 10-second hook timeout. This closes a real gap where retired entries could appear in results.

5. **Single index read (L1 fix).** Eliminating the double-read of `index.md` is a clean performance improvement that also simplifies the control flow.

6. **Preserved legacy fallback.** The keyword scoring path (`score_entry`, `score_description`, `check_recency`) is fully preserved for environments where FTS5 is unavailable. The `HAS_FTS5` flag at module load makes the fallback seamless.

7. **Security-aware design.** Title sanitization, path containment checks, FTS5 query injection prevention (parameterized queries, alphanumeric-only tokens), and max_inject clamping are all preserved through the refactoring.

8. **Appropriate `score_with_body()` placement.** Keeping this function in `memory_retrieve.py` rather than the engine is correct -- it is tightly coupled to the hook's path resolution logic and recency checking, which the CLI does not need (CLI uses full-body FTS5 tables instead).

## Self-Critique

**Arguments against my findings:**

1. *"The SKILL.md/engine mismatch is just a documentation bug, not an architecture issue."* Counter: In a plugin where the SKILL.md is the contract that the LLM agent uses to invoke the tool, documentation IS the interface. A wrong SKILL.md is functionally equivalent to a broken API. The LLM will construct a command with `--include-retired` and it will crash with an argparse error. This is not a cosmetic issue.

2. *"Rating the stale command file as MEDIUM is too harsh -- it's unregistered."* Counter: The file still exists and the README still references it. A developer reading the repo will see conflicting instructions. More importantly, Claude Code may have cached the old command definition from prior sessions. However, the plugin.json correctly unregisters it, so the runtime impact is minimal. MEDIUM is appropriate.

3. *"Recommending shared constants for memory_candidate.py contradicts my own LOW rating."* Fair point. My recommendation says "accept current state" precisely because the independence argument is valid. The tokenizer note in CLAUDE.md is sufficient documentation. If I had recommended extracting shared constants, that would have been inconsistent with rating it LOW. The finding is correctly calibrated.

4. *"I should have rated _check_path_containment duplication higher given it's security-critical code."* There is a valid argument for MEDIUM here. Gemini CLI rated it HIGH. However, the function is 4 lines of trivial code (`resolve().relative_to()` wrapped in try/except), both copies are identical, and the risk of divergence is low given that neither copy has been modified since creation. The implementer's "don't over-DRY security code" argument has merit in that a single import point creates a single point of failure if the import mechanism breaks. LOW is defensible.

**Synthesis:** The CRITICAL finding is unambiguously correct and confirmed by all three external reviewers (vibe-check, Gemini CLI, Codex CLI). The MEDIUM findings reflect real maintenance risks but not immediate runtime failures. The LOW findings are genuine architectural observations but acceptable given the project's constraints (stdlib-only dependency goal for candidate.py, established `sys.path.insert` convention).

## External Review Summary

| Reviewer | Key Agreement | Key Disagreement |
|----------|---------------|-------------------|
| Vibe-check (Claude self) | Confirmed schema mismatch is umbrella finding; raised error output schema gap | Suggested `project_root = memory_root.parent.parent` as separate finding (I folded it into general observations -- it's an established convention across 3 files) |
| Gemini CLI (codereviewer) | Confirmed SKILL.md contract is Critical; agreed M2 fix is correct | Rated `_check_path_containment` duplication as High and recommended consolidation; I disagree and rate LOW. Suggested splitting engine into core + CLI files -- over-engineering for current scale. |
| Codex CLI (codereviewer) | Confirmed findings #1+#2 as High; identified missing CLI contract tests and stale command file | Suggested adding a versioned JSON contract -- good idea but overkill for single-consumer (SKILL.md) use case at current scale. |
