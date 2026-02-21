# V1 Practical Implementation Verification

**Verifier:** V1-Practical Agent
**Date:** 2026-02-22
**Scope:** Implementation feasibility, LOC estimates, risk, backwards compatibility, hidden dependencies

---

## 1. LOC Estimate Verification

### Action #1: Absolute Floor in `confidence_label()` -- Synthesis: ~15 LOC

**Verdict: UNDERESTIMATE (realistic: 20-35 LOC code, 35-65 with tests)**

Current function (`memory_retrieve.py:161-174`) is 14 lines. Adding an absolute floor requires:

1. New parameter `abs_floor: float = 0.0` (optional, backwards-compatible) -- 1 LOC
2. Read `abs_floor` from config in `main()` -- ~5 LOC (parse, validate, clamp)
3. Apply floor check: if `abs(score) < abs_floor`, downgrade to "medium" or below -- ~3-5 LOC
4. Pass `abs_floor` through `_output_results()` into `confidence_label()` -- ~3 LOC (signature + callsite changes)
5. Config default in `memory-config.default.json` -- 1 LOC

Total code changes: ~15-20 LOC is plausible for a minimal implementation if `abs_floor` is optional with default `0.0`.

**However**, 15 LOC is achievable ONLY if:
- `abs_floor` is an optional parameter defaulting to `0.0` (preserving all existing 2-arg call sites)
- No config validation beyond basic clamp
- No interaction with `apply_threshold()`'s 25% noise floor (see Critical Finding below)

**Critical Finding (Gemini):** `apply_threshold()` in `memory_search_engine.py:261-289` has its own hardcoded 25% relative noise floor. If the best result has a massive outlier BM25 score, `apply_threshold()` discards weaker results BEFORE `confidence_label()` ever sees them. The absolute floor in `confidence_label()` only affects *display* (output format), not *selection* (which results make it through). This means Action #1 is less impactful than the synthesis implies -- it affects confidence labeling but not the result set. This may be intentional (the synthesis says "분류" = classification, not filtering), but should be stated explicitly.

**Test impact:**
- `TestConfidenceLabel` (test_memory_retrieve.py:493-562): 17 tests. Will NOT break if `abs_floor` defaults to `0.0` (existing behavior preserved).
- `test_single_result_always_high` (line 535) and `test_all_same_score_all_high` (line 539): These WILL break if a nonzero default is chosen and the absolute score is below the floor. The synthesis specifically mentions these lines as needing regression tests.

### Action #2: Tiered Output in `_output_results()` -- Synthesis: ~30-50 LOC

**Verdict: PLAUSIBLE BUT TIGHT (realistic: 40-80 LOC code, 80-150 with tests)**

Current `_output_results()` (`memory_retrieve.py:262-301`) is 40 lines. Splitting it requires:

1. Compute confidence per entry (already done at line 299) -- 0 LOC
2. Branch: HIGH entries -> current `<result>` format -- ~5 LOC (if/else wrapper)
3. Branch: MEDIUM entries -> new `<memory-compact>` format (title+path only) -- ~10-15 LOC
4. Add conditional directive text after compact entries -- ~5 LOC
5. Handle edge case: all results are MEDIUM/LOW -> need hint or empty container -- ~5-10 LOC
6. Config parsing for `retrieval.output_mode` ("full"/"tiered") -- ~5 LOC
7. Guard: if output_mode == "full", skip tiering entirely -- ~3 LOC

Total code changes: 30-50 LOC is achievable for a minimal implementation. 40-60 LOC is more realistic.

**Hidden complexity (Codex):** Tests currently assert that LOW-confidence results still appear as `<result confidence="low">`. Silencing LOW results or changing MEDIUM to `<memory-compact>` breaks the output contract. Affected tests:
- `test_confidence_label_in_output` (line 618): asserts `confidence="low"` is present
- `test_no_score_defaults_low` (line 649): asserts `confidence="low"` exists
- `test_output_results_captures_all_paths` (test_v2_adversarial_fts5.py:1063): asserts `<result>` format
- `test_output_results_description_injection` (test_v2_adversarial_fts5.py:1079): asserts on `_output_results` output format
- `test_result_element_format` (line 658): asserts specific `<result ...>` pattern

Estimated test updates: 5-8 test methods need modification/addition.

### Action #3: 0-Result Hint Format -- Synthesis: ~5 LOC

**Verdict: ACCURATE but incomplete count**

The synthesis references lines 458 and 495. However, there are actually **3** occurrences of the hint string:
- Line 458: FTS5 path, valid query but no results
- Line 495: Legacy path, no entries scored
- Line 560: Legacy path, no results survived deep check

Changing format from `<!-- ... -->` to `<memory-note>...</memory-note>`: 3 line replacements = **3 LOC** (or ~6 LOC if extracted to a helper function, which is recommended since Action #2 may introduce a 4th path).

**Test impact:** No existing tests assert on the HTML comment string. Zero test breakage.

---

## 2. Backwards Compatibility of Config Changes

**Verdict: SAFE -- fully backwards-compatible**

Both new config keys use Python's `dict.get()` with safe defaults (`memory_retrieve.py:353-384`):

```python
# Existing pattern (line 356-360):
raw_inject = retrieval.get("max_inject", 3)
```

New keys would follow the same pattern:
- `retrieval.get("output_mode", "tiered")` -- missing key -> default "tiered"
- `retrieval.get("confidence_abs_floor", 0.0)` -- missing key -> default 0.0 (current behavior)

Existing users' `memory-config.json` files will NOT break. The config parser never uses strict dict indexing (`config["key"]`), always `.get()` with defaults.

**One concern (Gemini):** The name "full" for the rollback mode is misleading. Current behavior does NOT inject full memory body -- it injects title+path+tags in `<result>` elements. Recommend naming the modes `"legacy"` / `"tiered"` rather than `"full"` / `"tiered"`.

---

## 3. Implementation Order

**Verdict: CORRECT -- #1 before #2 before #3**

1. **Action #1 (absolute floor)** MUST come first because it defines the confidence semantics that Action #2 consumes. Without the floor, `confidence_label()` will mark weak-but-only results as "high" (since ratio=1.0 for single results), and the tiered output will inject them as full results even when they are weak matches.

2. **Action #2 (tiered output)** depends on #1 for correct confidence labels to drive the tiering logic.

3. **Action #3 (hint format)** is independent in theory, but should come after #2 because #2 may introduce a new "all results were medium/low and got compacted/silenced" path that also needs a hint. Centralizing hint emission in a helper (recommended by Codex) avoids duplicate strings.

---

## 4. Hidden Dependencies

### 4.1 Test Files

| File | Affected by | Breakage count |
|------|-------------|----------------|
| `tests/test_memory_retrieve.py` | #1 (if nonzero default), #2 | 0-2 for #1, 5+ for #2 |
| `tests/test_v2_adversarial_fts5.py` | #2 | 2 tests |
| `tests/test_arch_fixes.py` | None | 0 |

### 4.2 Index Format

No changes required. All 3 actions operate on the output side (stdout formatting), not on index parsing.

### 4.3 `memory_search_engine.py`

**Synthesis claims changes are scoped to `memory_retrieve.py` only. This is partially correct:**

- `confidence_label()` is only in `memory_retrieve.py` -- CORRECT
- `_output_results()` is only in `memory_retrieve.py` -- CORRECT
- `apply_threshold()` is in `memory_search_engine.py` -- this is NOT modified by any of the 3 actions

**But:** The `apply_threshold()` 25% noise floor (`memory_search_engine.py:283-288`) pre-filters results before `confidence_label()` sees them. The absolute floor in `confidence_label()` is a second, independent threshold on a different dimension (absolute magnitude vs. relative ratio). They do not conflict, but they also do not coordinate. This is acceptable for Phase 1 but should be documented.

### 4.4 SKILL.md

The `skills/memory-search/SKILL.md` references result format (`title`, `category`, `path`, `tags`, `snippet`). The proposed changes only affect the auto-inject output format (what `_output_results()` prints to stdout), NOT the CLI search output format (`cli_search()` in `memory_search_engine.py`). No SKILL.md changes needed.

### 4.5 CLI Search Path (`memory_search_engine.py:cli_search`)

NOT affected. The CLI uses its own output path (`cli_search` -> JSON output). The tiered output only applies to the hook's auto-inject path.

---

## 5. Rollback Plan Verification

**Synthesis claim:** "config change 1건으로 현행 복원" (single config change restores current behavior)

**Verdict: PARTIALLY CORRECT**

- For Action #2 (tiered output): Setting `retrieval.output_mode` to `"full"` (or `"legacy"`) would restore current behavior IF the implementation properly gates ALL tiering logic behind this flag. This is realistic -- a single `if output_mode == "full": [current code]` guard would work.

- For Action #1 (absolute floor): Setting `retrieval.confidence_abs_floor` to `0.0` restores current behavior (no absolute filtering). This is a second config change, not covered by the "1건" claim.

- For Action #3 (hint format): No config-based rollback. Would require code revert. But this is trivially reversible.

**Net assessment:** Rollback requires **2 config changes** (output_mode + abs_floor), not 1. The synthesis oversimplifies. However, both are safe, simple changes.

---

## 6. Deferred Items Effort Estimates

### Spatial Binding (Creative's Proposal 4)

**Synthesis: "Schema change needed, migration cost evaluation required"**

**Verdict: SIGNIFICANTLY UNDERESTIMATED**

- Requires adding a `context_paths` or `bindings` field to the memory JSON schema
- Pydantic models in `memory_write.py` must be updated (schema source of truth)
- JSON schema in `assets/schemas/` must be updated
- ALL existing memory files need migration (backfill script)
- `memory_search_engine.py` needs new tokenization/indexing for file paths
- `memory_retrieve.py` needs path-aware scoring
- Estimated: 200-400 LOC + migration script + tests. Not a simple Phase 2 feature.

### Working Memory (Creative's Proposal 3)

**Synthesis: "Behavioral consistency verification needed"**

**Verdict: HIGH RISK, correctly deferred**

Gemini's analysis is spot-on: promote/demote couples retrieval to LLM active agency. If Claude forgets to demote, working memory bloats permanently. This is not a code complexity issue but a behavioral reliability issue. Should be reclassified from "deferred feature" to "experimental/research" status.

### Temporal Decay

**Synthesis: deferred**

**Verdict: Surprisingly feasible (~5-10 LOC)**

`score_with_body()` already caches parsed JSON (`result["_data"]`), which contains `updated_at`. Computing an exponential decay modifier (`math.exp(-age_days / half_life)`) and multiplying into the body_bonus is trivial. However, calibrating the half_life parameter requires measurement data (Phase 2f measurement gate).

---

## 7. Summary Assessment

| Aspect | Synthesis Claim | Verification Result |
|--------|----------------|---------------------|
| Action #1 LOC | ~15 | 15-20 code (achievable), 35+ with tests |
| Action #2 LOC | ~30-50 | 40-60 code (tight end), 80+ with tests |
| Action #3 LOC | ~5 | ~3-6 (accurate, but 3 occurrences not 2) |
| Config backwards-compat | Yes | Confirmed safe |
| Implementation order | #1 -> #2 -> #3 | Confirmed correct |
| Rollback | 1 config change | 2 config changes needed |
| Deferred: Spatial Binding | Schema change | Major effort (200-400 LOC + migration) |
| Deferred: Working Memory | Verify behavioral consistency | High risk, experimental status recommended |
| Deferred: Temporal Decay | Needs measurement data | Trivially implementable (~5-10 LOC) |

### Key Findings Unique to This Review

1. **3 hint occurrences, not 2.** Lines 458, 495, AND 560. Extract to helper.
2. **`apply_threshold()` noise floor is independent.** The absolute floor in `confidence_label()` affects labeling, not selection. Both Codex and Gemini flagged this interaction.
3. **"full" naming is misleading.** Rename to "legacy" or "flat" per Gemini.
4. **Test breakage for Action #2 is substantial.** 5-8 tests need updating across 2 test files.
5. **Rollback is 2 config changes, not 1.** Both `output_mode` and `abs_floor`.

### Overall Verdict

The synthesis report is **directionally sound** with **accurate but slightly optimistic** LOC estimates. The 3 immediate actions are feasible, low-risk, and correctly ordered. The deferred items are correctly deferred but their effort is underestimated (Spatial Binding especially). Implementation can proceed with the noted corrections.

---

## External Verification Sources

- **Codex (OpenAI):** Confirmed LOC estimates are low-end. Identified test_v2_adversarial_fts5.py impact. Recommended helper function for hint centralization. Confirmed dependency order.
- **Gemini (Google):** Found critical scoping issue with `apply_threshold()` noise floor. Flagged "full" naming confusion. Confirmed config backwards-compatibility. Flagged Working Memory behavioral risk.
