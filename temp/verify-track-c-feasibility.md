# Feasibility Analysis & Gap Report (Track C)

**Date:** 2026-02-21
**Scope:** Sessions 1-6 of rd-08-final-plan.md vs actual codebase
**Status:** RESEARCH ONLY (no code changes)

---

## Part A: Hidden Complexity Analysis

### 1. Session 1 LOC Estimate (80 LOC) -- REALISTIC WITH CAVEATS

**Plan breakdown:** tokenizer ~15 LOC, body extraction ~50 LOC, FTS5 check ~15 LOC = 80 LOC.

**Blast radius of tokenizer change:**

The current `_TOKEN_RE` regex at line 54 of `memory_retrieve.py`:
```python
_TOKEN_RE = re.compile(r"[a-z0-9]+")
```

is used by `tokenize()` (line 63), which is called from:

1. `score_entry()` (line 101): `title_tokens = tokenize(entry["title"])` -- tokenizes titles for scoring
2. `score_description()` (line 128): receives pre-tokenized sets, but callers tokenize descriptions at line 303: `desc_tokens_by_cat[cat_key.upper()] = tokenize(desc)`
3. `main()` (line 295): `prompt_words = tokenize(user_prompt)` -- tokenizes the user prompt

**Key insight:** The tokenizer change from `[a-z0-9]+` to `[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+` affects ALL three call sites. However, since Session 1 explicitly says "NO scoring integration with existing keyword system" (per R2 finding), the tokenizer change itself is just ~2 LOC (the regex + possibly adjusting the `len(word) > 1` guard in `tokenize()`). The existing `score_entry()` and `score_description()` will simply receive different token sets (e.g., `user_id` instead of `user` + `id`).

**Risk:** The new regex produces fewer, longer compound tokens. Existing keyword scoring may actually DEGRADE slightly with the new tokenizer since `score_entry()` does exact and prefix matching. Example: query "user settings" with the old tokenizer produces `{"user", "settings"}`. With the new tokenizer, it still produces `{"user", "settings"}` (no underscores). But a title "user_id management" would now tokenize to `{"user_id", "management"}` instead of `{"user", "id", "management"}`. The query token "user" would no longer exact-match the title token "user_id" -- it would fall through to prefix matching (1 point instead of 2 points). This is a **scoring regression on the keyword path** that exists between Session 1 and Session 2.

**Verdict:** 80 LOC is realistic for the code changes. But there's a transient regression in keyword scoring between Sessions 1 and 2. If sessions are done on different days, the system is briefly worse. The plan acknowledges this by saying "NO scoring integration" but does not call out the regression explicitly.

**Additional body extraction concern:** The `extract_body_text()` function (plan line 176-194) references `data.get("content", {})` and per-category field lists. Looking at conftest.py factories:
- `make_decision_memory()` (line 35): `content.decision` is a string, `content.rationale` is a list of strings, `content.alternatives` is a list of dicts. The `extract_body_text()` code handles all three cases (string, list of strings, list of dicts). This looks correct.
- `make_session_memory()` (line 157): `content.completed` is a list of strings, `content.next_actions` is a list of strings. Plan's `BODY_FIELDS["session_summary"]` includes these. Correct.
- `make_runbook_memory()` (line 176): `content.steps` is a list of strings. Correct.

No hidden complexity here -- the body extraction covers the actual schema shapes.

---

### 2. Session 2 LOC Estimate (200 LOC) -- UNDERESTIMATED BY ~40-60 LOC

**What's being replaced:**

| Function | Lines | Disposition |
|----------|-------|-------------|
| `score_entry()` (lines 93-125) | 32 LOC | Replaced by FTS5 |
| `score_description()` (lines 128-153) | 25 LOC | Removed entirely |
| Scoring loop in `main()` (lines 300-318) | 18 LOC | Replaced |
| Deep check loop in `main()` (lines 325-358) | 33 LOC | Partially replaced |
| Sort + top selection (lines 363-365) | 3 LOC | Replaced by `apply_threshold()` |
| **Total replaced** | **~111 LOC** | |

**What's being added (per plan):**

| Component | Estimated LOC |
|-----------|--------------|
| `build_fts_index_from_index()` | ~25 LOC |
| `build_fts_query()` (smart wildcard) | ~15 LOC |
| `query_fts()` | ~15 LOC |
| `apply_threshold()` | ~20 LOC |
| `score_with_body()` (hybrid scoring) | ~30 LOC |
| FTS5 fallback logic (HAS_FTS5 check) | ~15 LOC |
| Rewriting `main()` flow | ~40-60 LOC |
| **Total new code** | **~160-180 LOC** |

**The main() rewrite is the hidden complexity.** The current `main()` function (lines 208-394) is 186 LOC. The plan replaces the entire scoring pipeline (lines 300-365, ~65 LOC) but also needs to:

1. **Restructure the config parsing** (lines 247-275): The `match_strategy` config key needs to be read to decide between FTS5 and keyword fallback. This is ~5-10 new LOC.
2. **Restructure the entry loop**: Currently `main()` iterates over parsed index entries with `for entry in entries:` (line 307). With FTS5, this entire loop is replaced by `build_fts_index_from_index()` + `query_fts()`. But the deep check loop (lines 325-358) for recency bonus and retired exclusion still needs to run on FTS5 results. The plan doesn't mention preserving path containment checks (lines 334-337) -- these **must** be preserved for security.
3. **Output format change**: Lines 367-394 (output formatting) stay mostly the same, but the data structures change from `(score, priority, entry)` tuples to FTS5 result dicts. This requires rewriting the output loop.

**Verdict:** The plan says "~150-200 LOC rewrite" but the actual rewrite is closer to **220-260 LOC** when you count the `main()` restructuring, config reading for `match_strategy`, preserving security checks (path containment, retired exclusion), and bridging FTS5 result format to the output format. The plan's estimate is ~40-60 LOC short.

**Critical security note:** The current `main()` has path containment checks at lines 334-337 and 353-356:
```python
file_path.resolve().relative_to(memory_root_resolved)
```
The plan's pseudocode for `score_with_body()` reads JSON files at `memory_root / result["path"]` without any containment check. This is a **security regression** if the path field in index.md is malicious. Session 2 must explicitly preserve this check.

---

### 3. Session 3 -- memory_search_engine.py Extraction -- SIGNIFICANT REFACTORING EFFORT

The plan says Session 2a builds FTS5 into `memory_retrieve.py`, then Session 3 (2b) "extracts search logic into `hooks/scripts/memory_search_engine.py`".

**This is a non-trivial refactor.** After Session 2, the FTS5 engine code will be inline in `memory_retrieve.py`. Session 3 must:

1. **Extract these functions** to `memory_search_engine.py`:
   - `build_fts_index_from_index()`
   - `build_fts_query()`
   - `query_fts()`
   - `apply_threshold()`
   - `extract_body_text()`
   - `tokenize()` (shared between old and new)
   - `parse_index_line()` (shared)
   - `STOP_WORDS` (shared)
   - `BODY_FIELDS` (shared)
   - `HAS_FTS5` check (shared)

2. **Update imports** in `memory_retrieve.py` to use the shared module.

3. **Handle the import path** (R1-technical WARN):
   ```python
   sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
   from memory_search_engine import build_fts_index, query_fts
   ```

4. **Build the CLI interface** for `memory_search_engine.py` so it can be invoked standalone:
   ```bash
   python3 "$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_search_engine.py" \
       --query "authentication" --root "$MEMORY_ROOT" --mode search
   ```

**Estimated LOC for Session 3:**
- `memory_search_engine.py` (extracted + CLI): ~150-180 LOC (not "~80-120" as the plan states -- the plan forgets to count the shared constants, the CLI arg parsing, and the full-body search mode)
- `skills/memory-search/SKILL.md`: ~30-50 LOC
- Modifications to `memory_retrieve.py` imports: ~10-15 LOC
- 0-result hint injection in `memory_retrieve.py`: ~5-10 LOC
- **Total: ~195-255 LOC** vs plan's "~80-120 LOC"

**Verdict:** Session 3 is underestimated by ~100+ LOC. The plan's "~100 LOC" estimate (from the session plan header) or "~80-120 LOC" (from the rd-08 schedule) does not account for the shared constant extraction, CLI scaffolding, or the full-body search mode.

---

### 4. Session 4 -- Test Scope -- UNDERESTIMATED

**Exact test inventory from `test_memory_retrieve.py`:**

| Class | Method Count | Breaks? |
|-------|-------------|---------|
| `TestTokenize` (3 tests) | 3 | YES -- `test_extracts_meaningful_words` may break if tokenizer changes how compound tokens work |
| `TestParseIndexLine` (4 tests) | 4 | NO |
| `TestScoreEntry` (6 tests) | 6 | YES -- All 6 break (function replaced) |
| `TestCheckRecency` (5 tests) | 5 | NO (but may need updating if deep check changes) |
| `TestCategoryPriority` (1 test) | 1 | NO |
| `TestRetrieveIntegration` (7 tests) | 7 | PARTIAL -- 3-4 break (scoring behavior changes affect matching) |
| `TestDescriptionScoring` (5 tests) | 5 | YES -- All 5 break (function removed) |
| `TestRetrievalOutputIncludesDescriptions` (2 tests) | 2 | PARTIAL -- output format may change with confidence annotations |
| **Total: 33 tests** | | **~20-22 tests break (61-67%)** |

**The plan says 42%. The actual breakage is closer to 61-67%.** The plan only counted `TestScoreEntry` (6) + `TestDescriptionScoring` (5) + "1-2 integration tests" = ~12-13 out of 33 = ~36-39%. But integration tests (`TestRetrieveIntegration`) are more fragile than estimated:

- `test_matching_prompt_returns_memories` (line 218): Checks `"use-jwt" in stdout` -- may still pass with FTS5 but depends on scoring threshold.
- `test_category_priority_sorting` (line 245): Checks `DECISION` before `TECH_DEBT` in output -- depends on FTS5 scoring producing same relative order.
- `test_recency_bonus` (line 271): Checks `"recent-decision" in stdout` -- depends on how hybrid scoring handles recency. The plan replaces the recency bonus mechanism.
- `test_backward_compat_legacy_index` (line 306): Checks legacy index format works -- FTS5 parsing of index.md must handle both formats.

**Additional test files affected:**

- **`test_arch_fixes.py`**:
  - `TestIssue5TitleSanitization`: 12 tests -- These test `_sanitize_title()` which is UNCHANGED. **Safe.**
  - `TestIssue3MaxInjectClamp`: 11 tests -- These test max_inject clamping. Some check output format (`"- ["` prefix in stdout). **2-3 may break** if output format changes.
  - `TestIssue1IndexRebuild`: 7 tests -- These test index rebuild. **Safe** unless `main()` restructuring changes the rebuild trigger behavior.
  - `TestCrossIssueInteractions`: 5 tests -- `test_max_inject_limits_injection_surface` counts `"- ["` lines. **May break** with FTS5 threshold changes.
  - Total from test_arch_fixes.py: **~3-5 tests may break.**

- **`test_adversarial_descriptions.py`**:
  - `TestScoringExploitation`: 10 tests -- 8 tests call `score_description()` directly. **All 8 break** (function removed).
  - `TestRetrievalDescriptionInjection`: 5 tests -- Test `_sanitize_title()`. **Safe.**
  - `TestMaliciousDescriptions`: 14 parametrized tests on `_sanitize_title()`. **Safe.**
  - `TestSanitizationConsistency`: 6 parametrized tests. **Safe.**
  - Imports at line 28-30: `from memory_retrieve import tokenize, score_entry, score_description, _sanitize_title` -- `score_description` import **will fail** at module load, breaking the ENTIRE file (all 60+ parametrized tests) unless handled.
  - Total from test_adversarial_descriptions.py: **8 direct breaks + entire file fails due to import.**

**Revised breakage count across all retrieve-related test files:**

| File | Total Tests | Breaking |
|------|------------|---------|
| `test_memory_retrieve.py` | 33 | ~20-22 |
| `test_arch_fixes.py` | ~45 | ~3-5 |
| `test_adversarial_descriptions.py` | ~60+ | **ALL** (import fails) |
| **Total** | ~138 | **~83-87 (60-63%)** |

**This is a CRITICAL underestimate.** The plan budgets "4-6 hours" for test rewrite. With 83+ breaking tests across 3 files, this is closer to **8-12 hours**.

**The `test_adversarial_descriptions.py` import failure is particularly dangerous** because it imports `score_description` at module level (line 29). When `score_description` is removed from `memory_retrieve.py`, this file will fail to import entirely, causing ALL tests in the file to error out -- including the 50+ sanitization and security tests that are completely unrelated to scoring.

**Fix required:** Either keep a stub `score_description()` in `memory_retrieve.py` that raises `NotImplementedError`, or update the import in `test_adversarial_descriptions.py` to use conditional import (like `test_memory_retrieve.py` already does at lines 28-31).

---

### 5. Session 3 -- plugin.json Update -- MISSING

The current `plugin.json` at `.claude-plugin/plugin.json` (line 15-16):
```json
"skills": [
    "./skills/memory-management"
]
```

Session 3 creates `skills/memory-search/SKILL.md`. **The plan does NOT mention updating plugin.json to register the new skill.** Without this registration, Claude Code will not discover the `memory-search` skill.

However, there is already a `commands/memory-search.md` registered in plugin.json (line 13):
```json
"commands": [
    "./commands/memory.md",
    "./commands/memory-config.md",
    "./commands/memory-search.md",
    "./commands/memory-save.md"
]
```

**Decision point:** The plan creates a SKILL (`skills/memory-search/SKILL.md`) but there's already a COMMAND (`commands/memory-search.md`). These are different mechanisms:
- Commands: user-invoked via `/memory:search`, Claude follows the markdown instructions
- Skills: triggered automatically or manually, with globs/triggers for context

The plan needs to decide:
1. **Replace** the existing command with a skill (update plugin.json, remove/update `commands/memory-search.md`)
2. **Keep both** (add skill to plugin.json, both coexist)
3. **Update the existing command** instead of creating a new skill

This is an **architectural decision missing from the plan**.

---

## Part B: Gap Analysis

### 6. conftest.py Updates -- NEEDED

`build_enriched_index()` in `conftest.py` (lines 243-272) builds index.md content in the format:
```
- [DISPLAY] title -> path #tags:t1,t2
```

The FTS5 engine parses index.md using the existing `parse_index_line()` function from `memory_retrieve.py` (referenced in the plan at line 230). Since `parse_index_line()` is unchanged, the test fixture format remains compatible.

**However:** The FTS5 tests need new fixtures:
- Tests for `build_fts_index_from_index()` need index.md files with multiple entries across categories
- Tests for `score_with_body()` need actual JSON memory files (not just index entries)
- The 500-doc benchmark needs a fixture that generates 500 memory entries

The existing `conftest.py` factories (`make_decision_memory()`, etc.) are sufficient for individual entries. But **a new fixture for bulk generation is needed** (e.g., `make_bulk_memories(count=500)`). This is ~20-30 LOC in conftest.py not accounted for in the plan.

**Also:** The `build_enriched_index()` function uses `from memory_candidate import CATEGORY_DISPLAY` (line 253). If `parse_index_line()` is extracted to `memory_search_engine.py`, this import chain still works because `parse_index_line()` stays in `memory_retrieve.py` and is re-exported. No issue here.

---

### 7. memory_index.py Changes -- NOT NEEDED

The plan uses `index.md` as-is for FTS5 indexing. `memory_index.py`'s `rebuild_index()` function (lines 102-129) produces the standard format:
```
- [DISPLAY] title -> path #tags:t1,t2
```

This format is parsed by `parse_index_line()` which is already in `memory_retrieve.py`. The FTS5 engine reads index.md and parses it with this function. No changes to `memory_index.py` are needed.

**One concern:** `memory_index.py` does NOT include body content in the index. The plan handles this via the hybrid approach (read JSON for top-K candidates). This is correct and consistent.

**Minor concern:** `_sanitize_index_title()` in `memory_index.py` (lines 89-99) is a different function from `_sanitize_title()` in `memory_retrieve.py`. They have slightly different behavior (index version collapses whitespace; retrieve version strips control chars and escapes XML). The FTS5 engine will receive titles sanitized by the index version. This is fine for search purposes.

---

### 8. Config Migration -- PARTIALLY ADDRESSED

The plan changes two config values:
- `match_strategy`: `"title_tags"` -> `"fts5_bm25"`
- `max_inject`: `5` -> `3`

**Which session handles updating `memory-config.default.json`?**

Looking at the rd-08 "Files Changed" table (line 979):
```
assets/memory-config.default.json | Modify (add judge config) | 3
```

This says Phase 3 (judge module). But the FTS5 config changes (`match_strategy`, `max_inject`) are Phase 2 changes. **There's no session assigned to update `memory-config.default.json` for Phase 2 config changes.**

**Backward compatibility for existing users:**

Existing users have `memory-config.json` with `"match_strategy": "title_tags"`. The plan says (line 1009):
```
match_strategy: "fts5_bm25" (new default) or "title_tags" (legacy fallback)
```

This implies `memory_retrieve.py` must read `match_strategy` and branch:
- `"fts5_bm25"` -> use FTS5 engine
- `"title_tags"` -> use keyword fallback (preserved existing code)
- Missing key -> default to `"fts5_bm25"` (new default)

**This branching logic is not explicitly addressed in any session.** Session 2 builds the FTS5 engine, but does it preserve the keyword path behind a conditional? The plan mentions FTS5 fallback (Decision #7) for when FTS5 is **unavailable** (no sqlite3 extension), but not for when the user's config says `"title_tags"`. These are different scenarios:

1. FTS5 unavailable (runtime): Fall back to keyword scoring
2. Config says `"title_tags"` (user choice): Use keyword scoring intentionally

**Both paths must be preserved.** Session 2 must keep `score_entry()` and `score_description()` alive behind a conditional, or the `"title_tags"` config option becomes a lie. This is NOT addressed in the plan and adds ~10-15 LOC of conditional branching.

**Wait -- there's a contradiction.** The plan says Session 4 (2c) expects `score_entry()` tests to "break" because the function is "replaced by BM25." But if `"title_tags"` is a supported config option, the function must be preserved. Either:
- Remove `"title_tags"` support (breaking change for existing users), OR
- Keep `score_entry()` alive (tests don't break after all)

**Verdict:** This is an unresolved architectural decision that affects test count, LOC estimates, and backward compatibility.

---

### 9. Import Path Issue -- ADDRESSED BUT FRAGILE

The plan (line 293-296) specifies:
```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from memory_search_engine import build_fts_index, query_fts
```

This works because all hook scripts live in `hooks/scripts/`. The `sys.path.insert(0, ...)` adds the scripts directory to the Python path. Since `memory_search_engine.py` will live in the same directory, the import resolves.

**This is the same pattern already used in `conftest.py`** (lines 12-14):
```python
SCRIPTS_DIR = str(Path(__file__).parent.parent / "hooks" / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
```

**No additional complexity here.** The pattern is established and works.

**One concern:** When `memory_search_engine.py` is invoked as a standalone CLI (Session 3's `--query` mode), it doesn't need `sys.path` manipulation because it's the `__main__` module. But when imported from `memory_retrieve.py`, the path manipulation is needed. This dual-use (importable module + CLI) is a common Python pattern and the plan handles it correctly.

---

### 10. 0-Result Hint Injection -- ADDRESSED IN SESSION 3 BUT DETAILS MISSING

The plan (Session 2b description) says:
> Hook injects `<!-- Use /memory:search <topic> -->` when auto-inject returns 0 results

This requires modifying `memory_retrieve.py`'s `main()` function. Currently, when no results match, `main()` exits at line 319:
```python
if not scored:
    sys.exit(0)
```

The hint injection must change this to:
```python
if not scored:
    print("<!-- Use /memory:search <topic> for full-text search -->")
    sys.exit(0)
```

**This is ~3-5 LOC.** It should be done in Session 3 (after the search skill exists). The plan mentions it but doesn't assign it to a specific LOC count. It's trivial.

**However,** there's a subtlety: the current code has MULTIPLE exit points where 0 results are returned:
- Line 291: `if not entries: sys.exit(0)`
- Line 298: `if not prompt_words: sys.exit(0)`
- Line 319: `if not scored: sys.exit(0)`
- Line 360: `if not final: sys.exit(0)`

The hint should only appear at lines 319 and 360 (where scoring was attempted but found nothing), NOT at lines 291 or 298 (where the index is empty or the prompt is too short). This requires **4 exit points to be considered**, not just one.

---

## Part C: Completeness Check

### 11. Files Changed Table (rd-08 line 973) vs Session Coverage

| File | Action | Phase | Session | Covered? |
|------|--------|-------|---------|----------|
| `hooks/scripts/memory_retrieve.py` | Modify | 1, 2a, 3 | Sessions 1, 2, (7-9) | YES |
| `hooks/scripts/memory_search_engine.py` | Create | 2b | Session 3 | YES |
| `hooks/scripts/memory_judge.py` | Create | 3 | Sessions 7-9 (conditional) | YES |
| `hooks/hooks.json` | Modify (timeout 10->15) | 3 | Sessions 7-9 (conditional) | **PARTIALLY** -- only needed if judge is built. But no session explicitly handles this. |
| `assets/memory-config.default.json` | Modify | 3 | **MISSING** for Phase 2 changes | **GAP**: FTS5 config (`match_strategy`, `max_inject`) should be updated in Session 2, not deferred to Phase 3 |
| `skills/memory-search/SKILL.md` | Create | 2b, 3c | Session 3 | YES |
| `tests/test_memory_retrieve.py` | Rewrite | 2c | Session 4 | YES |
| `tests/test_memory_judge.py` | Create | 3b | Sessions 7-9 (conditional) | YES |
| `CLAUDE.md` | Update | 3 | **MISSING** | **GAP**: CLAUDE.md should be updated after Phase 2 to reflect the new architecture. No session explicitly handles this. |

**Missing from the Files Changed table:**

| File | Action Needed | Why |
|------|--------------|-----|
| `tests/test_adversarial_descriptions.py` | Modify imports | `score_description` import at line 29 will fail when function is removed |
| `tests/test_arch_fixes.py` | Possibly modify | Some tests check output format (`"- ["` prefix) |
| `tests/conftest.py` | Add bulk fixture | 500-doc benchmark needs bulk memory generation |
| `.claude-plugin/plugin.json` | Possibly modify | New skill registration (see finding #5) |
| `commands/memory-search.md` | Possibly modify or remove | Conflicts with new skill (see finding #5) |

---

### 12. Configuration Schema -- New Config Keys

**rd-08 Configuration Schema (line 989-1006):**

| Config Key | Current Default | New Default | Session |
|-----------|----------------|-------------|---------|
| `retrieval.max_inject` | `5` | `3` | **UNASSIGNED** |
| `retrieval.match_strategy` | `"title_tags"` | `"fts5_bm25"` | **UNASSIGNED** |
| `retrieval.judge.enabled` | N/A | `false` | Sessions 7-9 |
| `retrieval.judge.model` | N/A | `"claude-haiku-4-5-20251001"` | Sessions 7-9 |
| `retrieval.judge.timeout_per_call` | N/A | `3.0` | Sessions 7-9 |
| `retrieval.judge.fallback_top_k` | N/A | `2` | Sessions 7-9 |
| `retrieval.judge.candidate_pool_size` | N/A | `15` | Sessions 7-9 |
| `retrieval.judge.dual_verification` | N/A | `false` | Sessions 7-9 |
| `retrieval.judge.include_conversation_context` | N/A | `true` | Sessions 7-9 |
| `retrieval.judge.context_turns` | N/A | `5` | Sessions 7-9 |

**GAP:** The `retrieval.max_inject` and `retrieval.match_strategy` changes are Phase 2 changes. No session is assigned to update `memory-config.default.json` for these. The plan's Files Changed table says Phase 3, but Phase 2 code will read these keys. Without updating the default config, new installations will use `"title_tags"` (the old default) even after FTS5 is implemented, unless the code hardcodes `"fts5_bm25"` as the fallback default.

**Resolution:** Either:
1. Hardcode `"fts5_bm25"` as the default in `memory_retrieve.py` when `match_strategy` key is missing (code-level default), OR
2. Update `memory-config.default.json` in Session 2

The plan implies approach #1 (line 1009: "new default") but this is implicit, not explicit.

---

## Summary of Findings

### CRITICAL (blocks session completion)

| # | Finding | Impact | Session |
|---|---------|--------|---------|
| C1 | `test_adversarial_descriptions.py` imports `score_description` at module level -- entire file (60+ tests) fails when function removed | All adversarial security tests stop running | 4 |
| C2 | Backward compat for `match_strategy: "title_tags"` is unresolved -- if keyword path is removed, existing configs break silently | Existing user regression | 2 |

### HIGH (LOC estimates significantly wrong)

| # | Finding | Impact | Session |
|---|---------|--------|---------|
| H1 | Session 2 LOC underestimated by ~40-60 LOC (main() rewrite, security checks, config branching) | Session runs longer than planned | 2 |
| H2 | Session 3 LOC underestimated by ~100+ LOC (extraction refactor, CLI, full-body search mode) | Session runs longer than planned | 3 |
| H3 | Session 4 test breakage is 60-63%, not 42% (test_adversarial_descriptions.py import failure cascades to 60+ tests) | 8-12 hours, not 4-6 | 4 |
| H4 | plugin.json and commands/memory-search.md conflict with new skill -- architectural decision missing | Skill may not be discoverable | 3 |

### MEDIUM (missing items that need to be added)

| # | Finding | Impact | Session |
|---|---------|--------|---------|
| M1 | `memory-config.default.json` Phase 2 config update not assigned to any session | New installs use old defaults | 2 |
| M2 | CLAUDE.md update not assigned to any session | Documentation drift | 2-3 |
| M3 | conftest.py needs bulk memory fixture for 500-doc benchmark | Benchmark test won't run | 4 |
| M4 | Security: path containment check missing from plan's `score_with_body()` pseudocode | Path traversal regression | 2 |
| M5 | 0-result hint injection has 4 exit points, not 1 -- only 2 should trigger the hint | Incorrect hint on empty index | 3 |

### LOW (minor issues)

| # | Finding | Impact | Session |
|---|---------|--------|---------|
| L1 | Transient keyword scoring regression between Session 1 and Session 2 (new tokenizer + old scorer) | Brief quality dip | 1-2 |
| L2 | hooks.json timeout change (10->15s) only needed for judge, but plan lists it under Phase 3 which is correct | None (correctly placed) | 7-9 |
