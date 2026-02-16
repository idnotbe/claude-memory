# Verification Round 1: Correctness Review

**Reviewer:** reviewer-correctness
**Date:** 2026-02-16
**Scope:** Parallel per-category LLM triage implementation
**Files reviewed:**
- `hooks/scripts/memory_triage.py` (882 lines)
- `skills/memory-management/SKILL.md` (213 lines)
- `assets/memory-config.default.json` (77 lines)
- `hooks/scripts/memory_candidate.py` (cross-reference for CLI interface)
- `hooks/scripts/memory_write.py` (cross-reference for CLI interface)

**Cross-validation:** Gemini 3 Pro via pal clink (codereviewer role)
**Vibe check:** Completed

---

## Aspect 1: Config Parsing Correctness

**Verdict: PASS**

`load_config()` (memory_triage.py:485-538) and `_parse_parallel_config()` (memory_triage.py:551-588) are correct.

### Tests executed (all passed):
1. Valid input with all fields specified
2. Invalid model values (`"gpt4"`, `"claude"`) silently fall back to defaults
3. Case-insensitive model matching (`"HAIKU"` -> `"haiku"` via `.lower()`)
4. Non-dict input (string, None, int) returns full defaults
5. Unknown category keys in `category_models` are silently ignored
6. Bool coercion for `enabled` (0 -> False, `"yes"` -> True, `""` -> False)
7. No config file -> full defaults
8. Config without `parallel` section -> parallel defaults
9. `max_messages` clamped to [10, 200] range
10. Thresholds clamped to [0.0, 1.0] range; invalid types keep defaults
11. Corrupt JSON config file -> full defaults

### Notable design choices:
- `_deep_copy_parallel_defaults()` prevents shared mutable state (memory_triage.py:541-548) -- good practice
- `default_model` is parsed before `category_models` (memory_triage.py:567-570) but is NOT used as fallback within `_parse_parallel_config` -- the fallback happens in SKILL.md orchestration (`config.category_models[category] or default_model`)
- Model validation uses a fixed allowlist `VALID_MODELS = {"haiku", "sonnet", "opus"}` (memory_triage.py:466)

---

## Aspect 2: Context File Generation

**Verdict: PASS**

`write_context_files()` (memory_triage.py:645-700) and supporting functions are correct.

### Tests executed (all passed):
1. `_find_match_line_indices()` correctly identifies lines matching primary patterns
2. Unknown categories return empty index list
3. `_extract_context_excerpt()` extracts correct +/-N window around matches
4. Overlapping windows are merged (no duplicate content, no `---` separator)
5. Non-overlapping windows are separated by `---` markers
6. Edge cases at start/end of file are handled (window clips to bounds)
7. Empty inputs (no lines, no indices) return empty string
8. Duplicate match indices are deduplicated via `sorted(set(...))`
9. Text category context files include: category name, score, transcript excerpts, key snippets
10. SESSION_SUMMARY context files include: activity metrics (tool_uses, distinct_tools, exchanges) -- no text excerpts

### Design notes:
- Context window is 10 lines (memory_triage.py:596), distinct from the 4-line co-occurrence scoring window
- `OSError` on file write is silently caught (memory_triage.py:696-698) -- acceptable since context files are non-critical

---

## Aspect 3: Structured Output Format

**Verdict: PASS**

`format_block_message()` (memory_triage.py:727-793) produces valid JSON within `<triage_data>` tags.

### Tests executed (all passed):
1. Human-readable message is present and starts with expected text
2. `<triage_data>` JSON block is parseable and round-trips correctly
3. Category entries include `category`, `score`, and optional `context_file`
4. `context_file` is absent when category has no context path (not set to null)
5. `parallel_config` structure includes `enabled`, `category_models`, `verification_model`, `default_model`
6. Snippet sanitization escapes HTML (`<script>` -> `&lt;script&gt;`)
7. Control characters are stripped from snippets
8. Multi-category output produces valid JSON with correct count
9. Scores are rounded to 4 decimal places via `round(r["score"], 4)` (memory_triage.py:762)

---

## Aspect 4: SKILL.md Orchestration Flow

**Verdict: PASS (with MAJOR caveat on casing -- see Issue #1)**

The 4-phase flow (Parse -> Draft -> Verify -> Save) is logically correct.

### Phase-by-phase analysis:

**Phase 0 (Parse):** Correctly instructs extraction of `<triage_data>` JSON and config loading.

**Phase 1 (Parallel Drafting):**
- Subagent instructions are numbered 1-6 with clear stop conditions
- Step 3 explicitly names the fields to check (`vetoes`, `pre_action`, `candidate`)
- Step 4 applies CUD resolution with safety defaults inline ("prefer UPDATE over DELETE")
- Step 5 distinguishes CREATE/UPDATE (full JSON) from DELETE (action JSON) output format
- Step 6 requires action report with justification
- Line 43 uses `category.lower()` for model lookup -- mitigates casing issue
- Lines 49-51 have explicit lowercase instruction

**Phase 2 (Verification):**
- BLOCK vs ADVISORY severity levels are clearly defined
- Schema validation failure = BLOCK; content quality = ADVISORY
- Parallel spawning of all verification subagents

**Phase 3 (Save):**
- Main agent applies CUD resolution table as final arbiter
- OCC (hash-based) for updates
- Session rolling window enforcement after session_summary creation

### CUD Resolution Table:
- 8 rows cover all combinations
- VETO -> obey (mechanical invariant)
- NOOP -> NOOP (no target)
- CREATE+DELETE -> NOOP (contradictory signals) -- correct safety default
- UPDATE_OR_DELETE+CREATE -> CREATE (subagent semantic override) -- documented rationale

---

## Aspect 5: Backwards Compatibility

**Verdict: PASS**

### Tests executed (all passed):
1. No config file at all -> full defaults (enabled, parallel enabled)
2. Config with no `triage` section -> defaults
3. Config with `triage` but no `parallel` -> parallel defaults applied
4. `triage` as non-dict value -> defaults
5. `parallel.enabled=false` preserves the full parallel config structure
6. Human-readable stderr message format is unchanged (backwards-compatible header + instruction line)
7. `<triage_data>` block is appended after the human-readable portion (old consumers unaffected)

---

## Aspect 6: File Path Consistency

**Verdict: PASS (with MINOR note)**

### Tests executed (all passed):
1. Context file paths use pattern `/tmp/.memory-triage-context-{CATEGORY}.txt` (UPPERCASE)
2. `format_block_message()` `context_file` values match `write_context_files()` output paths exactly
3. Context files (input to subagents) and draft files (output from subagents) are distinct file sets with distinct naming patterns

### Note:
- Context files use UPPERCASE category: `/tmp/.memory-triage-context-DECISION.txt`
- Draft files per SKILL.md template use `<category>`: `/tmp/.memory-draft-<category>-<pid>.json`
- The actual casing of draft files depends on what the subagent uses -- if it uses the UPPERCASE name from triage_data, the draft would be `/tmp/.memory-draft-DECISION-12345.json`
- This is cosmetic, not functional, since Phase 2/3 reference draft paths from Phase 1 subagent output

---

## Issues Found

### Issue #1: Category Name Casing Mismatch (MAJOR)

**Severity: MAJOR**
**Location:** memory_triage.py:758-766 (triage_data construction), SKILL.md:43,49-51 (mitigation)

**Description:**
The triage hook outputs UPPERCASE category names in `<triage_data>` JSON (e.g., `"category": "DECISION"`). Downstream CLI tools strictly require lowercase:
- `memory_candidate.py --category` (line 197-198): `choices=list(CATEGORY_FOLDERS.keys())` = lowercase only
- `memory_write.py --category` (line 1237): `choices=list(CATEGORY_FOLDERS.keys())` = lowercase only
- `config.category_models` keys: lowercase (`"decision"`, `"runbook"`, etc.)

**Mitigation present:** SKILL.md lines 43 and 49-51 explicitly instruct lowercase normalization. Line 43 uses `category.lower()` syntax in the model lookup pseudocode.

**Residual risk:** Relying on LLM compliance for mechanical data transformation is brittle. A haiku subagent may forget to lowercase when constructing the `memory_candidate.py` command, causing an argparse error. The fix at the source (emitting lowercase in triage_data) would eliminate this class of failure entirely.

**Recommended fix:** In `format_block_message()`, use `category.lower()` when building the triage_data dict:
```python
# memory_triage.py:759
entry = {
    "category": category.lower(),  # normalize for downstream CLI tools
    "score": round(r["score"], 4),
}
```
Also normalize the context file path (memory_triage.py:663):
```python
path = f"/tmp/.memory-triage-context-{category.lower()}.txt"
```
The human-readable portion (lines 738-748) can continue using UPPERCASE for readability.

**Cross-validated by:** Gemini 3 Pro (pal clink) -- rated HIGH SEVERITY, same fix recommendation.

### Issue #2: Context File Path Uses UPPERCASE Category (MINOR)

**Severity: MINOR**
**Location:** memory_triage.py:663

**Description:**
Context files are written as `/tmp/.memory-triage-context-DECISION.txt` (UPPERCASE). This works because the exact path is passed through triage_data's `context_file` field, so subagents read it correctly regardless. However, if Issue #1 is fixed by lowering category names in triage_data, the context file path and category name would be inconsistent unless this is also lowered.

**Recommended fix:** Apply `.lower()` alongside Issue #1 fix.

### Issue #3: Empty results guard in format_block_message (INFO)

**Severity: INFO**
**Location:** memory_triage.py:727-793

**Description:**
`format_block_message()` does not guard against an empty `results` list. In practice this cannot happen because `main()` only calls it when `results` is non-empty (line 863: `if results:`). But as a standalone function, calling it with `results=[]` would produce a valid but content-free message. Defense-in-depth only; no action required.

---

## Summary Table

| Aspect | Verdict | Issues |
|--------|---------|--------|
| 1. Config parsing correctness | PASS | None |
| 2. Context file generation | PASS | None |
| 3. Structured output format | PASS | None |
| 4. SKILL.md orchestration flow | PASS | Issue #1 (MAJOR) |
| 5. Backwards compatibility | PASS | None |
| 6. File path consistency | PASS | Issue #2 (MINOR) |

**Overall: PASS with 1 MAJOR, 1 MINOR, 1 INFO issue**

The implementation is fundamentally sound. Config parsing is defensive with proper clamping and validation. Context file generation correctly handles window merging, edge cases, and the SESSION_SUMMARY special case. Structured output produces valid JSON. Backwards compatibility is fully preserved. The single actionable finding is the UPPERCASE/lowercase category name mismatch (Issue #1), which has a documented mitigation in SKILL.md but would be more reliably fixed at the source with a one-line change.

---

## Methodology

- Direct Python execution of all new functions with crafted inputs
- 33 individual test cases across 6 aspects
- Cross-validation with Gemini 3 Pro (pal clink, codereviewer role)
- Vibe check for metacognitive review of methodology
- Compile check: `python3 -m py_compile` passed
- Existing test suite: 9 tests in test_memory_write_guard.py confirmed passing (full suite collection timeout)
