# V2 Integration Review - Output Report

**Reviewer:** v2-integration
**Date:** 2026-02-20
**Files Reviewed:** memory_retrieve.py, memory_index.py, CLAUDE.md, SKILL.md, hooks.json, all tests/

**External validation:** ops project impact (task-ops-output.md), V1 correctness/security (PASS)

---

## Overall Verdict: PASS (with 3 stale tests to fix and 2 tech debt items to track)

All 12 fixes are correctly integrated. Cross-file format consistency holds. Documentation is accurate. Ops impact is understood. Three test failures are pre-existing stale tests (written before B2/C1 fixes, now reflecting outdated assumptions) — they require test updates, not code changes.

---

## 1. Cross-File Format Consistency

### 1.1 Index Line Format: CONSISTENT

`memory_index.py` writes index lines as:
```
- [CATEGORY_DISPLAY] sanitized_title -> path #tags:tag1,tag2
```

`memory_retrieve.py` parses with `_INDEX_RE`:
```python
r"^-\s+\[([A-Z_]+)\]\s+(.+?)\s+->\s+(\S+)(?:\s+#tags:(.+))?$"
```

Verification:
- `_sanitize_index_title()` (index.py) collapses whitespace and strips ` -> ` and `#tags:` markers. The `_INDEX_RE` regex in retrieve.py uses non-greedy `(.+?)` for the title group and requires `\s+->\s+` for the delimiter. These are compatible: a title cannot contain ` -> ` after sanitization, so the regex unambiguously identifies the path.
- The `#tags:` suffix in index lines uses raw tag values (no XML escaping). The retrieve.py output layer applies `html.escape()` to tags (A1 fix) at print time. This is the correct layering: raw tags in storage, escaped at output boundary. **No conflict.**
- `validate_index()` and `health_report()` in index.py parse index lines using `line.split(" -> ", 1)[1]` and `.split(" #tags:")[0]` — these correctly handle the enriched format with tags.

**Cross-file format: CONSISTENT.**

### 1.2 Title Sanitization Approach: COMPATIBLE

| Layer | Function | What It Does |
|-------|----------|--------------|
| Write (memory_write.py) | `auto_fix()` | Strips `[\x00-\x1f\x7f]`, replaces ` -> `, strips `#tags:` |
| Index rebuild (memory_index.py) | `_sanitize_index_title()` | Collapses all whitespace (incl. `\n`), strips ` -> ` and `#tags:`, truncates 120 |
| Retrieval output (memory_retrieve.py) | `_sanitize_title()` | Strips `[\x00-\x1f\x7f]`, strips BiDi/Unicode, strips ` -> ` and `#tags:`, truncates 120, XML-escapes |

These layers are complementary, not contradictory. The retrieve-side `_sanitize_title()` is the most thorough (adds BiDi stripping, XML escaping). The index-rebuild layer adds whitespace collapse (handles `\n` in titles). The write-side is first defense.

**One known gap (documented in V1 security):** `_sanitize_index_title()` does not strip null bytes (`\x00`). However, retrieve.py's `_sanitize_title()` strips them on read. This is defense-in-depth; null bytes in index.md have no exploitable path to LLM context.

**Sanitization approach: COMPATIBLE. Defense-in-depth chain intact.**

### 1.3 Category Names and Folder Mappings: CONSISTENT

`memory_index.py` `CATEGORY_FOLDERS` and `CATEGORY_DISPLAY` are the authoritative mapping:
```python
CATEGORY_FOLDERS = { "session_summary": "sessions", "decision": "decisions", ... }
CATEGORY_DISPLAY = { "session_summary": "SESSION_SUMMARY", "decision": "DECISION", ... }
```

`memory_retrieve.py` uses `CATEGORY_PRIORITY`:
```python
CATEGORY_PRIORITY = { "DECISION": 1, "CONSTRAINT": 2, "PREFERENCE": 3, "RUNBOOK": 4, "TECH_DEBT": 5, "SESSION_SUMMARY": 6 }
```

Both use the same 6 categories. `CATEGORY_DISPLAY` maps lowercase→UPPERCASE matching `CATEGORY_PRIORITY` keys. **Consistent.**

---

## 2. Documentation Alignment

### 2.1 CLAUDE.md: ACCURATE

CLAUDE.md correctly describes:
- The v5.0.0 architecture (1 Stop hook, UserPromptSubmit retrieval, PreToolUse/PostToolUse Write guards)
- The 4-phase consolidation flow reference to SKILL.md
- Security considerations (prompt injection, max_inject clamping, config manipulation, index format fragility)
- The defense-in-depth chain: "memory_write.py auto-fix sanitizes titles on write, memory_retrieve.py re-sanitizes on read"

**One minor documentation gap:** The Security Considerations section mentions "Remaining gap: memory_index.py rebuilds index from JSON without re-sanitizing (trusts write-side sanitization)." After fix B4, this is now partially addressed — `_sanitize_index_title()` was added. The remaining gap (null bytes not stripped in indexer, BiDi chars not stripped) is still valid but narrower. CLAUDE.md could be updated to reflect this improvement, but it is not incorrect.

**Also not documented:** The new behaviors introduced by the 12 fixes:
- A1: Tags XML-escaped in output (new security mitigation)
- A2: Path containment validation (new security mitigation)
- A3: cat_key sanitization (new security mitigation)
- A4: Path XML-escaped in output (new security mitigation)
- B4: `_sanitize_index_title()` added to index rebuild (partial gap closure)

These are internal implementation details; CLAUDE.md does not need to enumerate every fix. The Security Considerations section accurately describes the overall defense-in-depth posture at a conceptual level. CLAUDE.md is accurate and does not need mandatory updates.

**Recommended (optional) update:** The Security Considerations item 1 could note that B4 partially closes the index rebuild sanitization gap.

### 2.2 SKILL.md: NOT AFFECTED

The 12 fixes are entirely in memory_retrieve.py and memory_index.py. SKILL.md describes the orchestration flow, memory JSON format, and agent instructions for memory_candidate.py, memory_write.py, and the 4-phase consolidation process. None of the modified functionality is referenced in SKILL.md.

**SKILL.md does not require updates.**

### 2.3 hooks.json: NOT AFFECTED

hooks.json defines hook bindings (Stop, PreToolUse:Write, PostToolUse:Write, UserPromptSubmit). No hook entries were modified. The `memory_retrieve.py` binding is unchanged. **hooks.json does not require updates.**

---

## 3. Test Coverage Analysis

### 3.1 Current Test Suite: 432 PASSING, 3 FAILING, 10 XPASSED

The 10 xpassed tests are pre-fix tests that are now passing because the fixes have been applied (expected behavior).

### 3.2 The 3 Failing Tests: Stale Test Assertions (Not Code Bugs)

**FAILED test_memory_retrieve.py::TestTokenize::test_excludes_short_words**
```python
tokens = tokenize("go to db mx")
assert "db" not in tokens  # 2 chars -- FAILS because C1 fix allows 2-char tokens
```
- Root cause: Fix C1 changed `len(word) > 2` to `len(word) > 1`, enabling 2-char tokens. Test was written pre-fix expecting old behavior.
- Resolution: Update test to reflect new behavior (`db` IS now expected in tokens, `go` is still filtered by STOP_WORDS).

**FAILED test_adversarial_descriptions.py::TestScoringExploitation::test_score_description_single_prefix_floors_to_zero**
```python
prompt_words = {"arch"}  # prefix of "architectural"
score = score_description(prompt_words, description_tokens)
# Test asserts int(0.5) = 0, but B2 fix uses int(0.5 + 0.5) = 1
assert score == 0  -- FAILS
```
- Root cause: Fix B2 changed `int(score)` (floor) to `int(score + 0.5)` (round-half-up). Test was written for floor behavior.
- Resolution: Update test to expect `score == 1` (or use `>= 0`), or document that 0.5-point prefix match rounds up to 1.

**FAILED test_adversarial_descriptions.py::TestScoringExploitation::test_score_description_one_exact_one_prefix**
```python
prompt_words = {"architectural", "rati"}  # rati is prefix of rationale
# Test asserts 1.0 + 0.5 = int(1.5) = 1, but B2 gives int(1.5 + 0.5) = int(2.0) = 2
assert score == 1  -- FAILS
```
- Root cause: Same B2 round-half-up change.
- Resolution: Update test to expect `score == 2`.

**All 3 failures are stale test assertions caused by B2 (score_description rounding) and C1 (2-char token) fixes. They are not regressions — the code behavior is correct; the tests need updating.**

### 3.3 New Behavior Coverage Gaps

The 12 fixes introduce behaviors not explicitly covered by targeted tests:

| Fix | New Behavior | Existing Test Coverage | Gap? |
|-----|-------------|----------------------|------|
| A1 | Tag XML escaping | test_arch_fixes Issue5 (partial) | Partial — no test for malicious tag content in integration output |
| A2 | Path containment (traversal check) | None explicit | **GAP**: No test for `../../../../etc/passwd` in index entry |
| A3 | cat_key sanitization in desc attr | test_adversarial_descriptions.py (partial) | Partial — _sanitize_title tested, not desc attr XML structure |
| A4 | Path XML escaping | None explicit | **GAP**: No test for crafted path with XML chars in output |
| B1 | Truncation before XML escape | test_arch_fixes Issue5 truncation test | Covered (truncation to 120) but not specifically the order |
| B2 | round-half-up scoring | test_adversarial_descriptions (now stale) | Needs updated test |
| B3 | grace_period_days int() cast | test_memory_index.py TestGC.test_gc_custom_grace_period | Partially covered |
| B4 | _sanitize_index_title() | test_memory_index.py TestRebuild (indirect) | Indirect only; no explicit test for injection in rebuild |
| C1 | 2-char tokens allowed | test_memory_retrieve.py (now stale) | Needs updated test |
| C2 | Description flooding fix | TestDescriptionScoring (partial) | Partial; no explicit flood test |
| C3 | Reverse prefix matching | test_memory_retrieve.py TestScoreEntry (prefix tests) | Forward prefix covered; no reverse prefix test |
| C4 | Comment-only | N/A | N/A |

**New tests recommended (prioritized):**

1. **A2 path traversal**: `test_path_traversal_blocked_in_retrieval(tmp_path)` — inject `../../etc/passwd` path in index, verify not output
2. **A1 tag XML injection end-to-end**: `test_malicious_tag_blocked_in_output(tmp_path)` — use tag `</memory-context>`, verify output has escaped version
3. **B4 title injection in rebuild**: `test_rebuild_sanitizes_injection_title(tmp_path)` — write JSON with `\n` or ` -> ` in title, verify index line is single-line and sanitized
4. **C3 reverse prefix**: `test_reverse_prefix_match_on_entry()` — prompt word `authentication` matches `auth` tag (len>=4 guard)
5. **C2 description flood guard**: `test_description_flood_guard()` — entries with 0 text score don't appear even when category description matches

---

## 4. V1 Non-Blocking Items: Track as Tech Debt

### Item 1: B4 Null Byte Gap (V1 Security LOW warning)
- `_sanitize_index_title()` in memory_index.py does not strip null bytes (`[\x00-\x1f\x7f]`)
- Impact: LOW — downstream `_sanitize_title()` in retrieve.py strips null bytes before LLM context
- Recommendation: Add as tech debt item. Fix: add `re.sub(r'[\x00-\x1f\x7f]', '', title)` to `_sanitize_index_title()` before the whitespace collapse.

### Item 2: B4 Tags Not Sanitized in Index Rebuild (V1 Correctness observation)
- `rebuild_index()` writes raw tag strings to index.md without sanitization
- Impact: LOW — tags are schema-validated by Pydantic at write time; A1 fix (html.escape) sanitizes tags at retrieval output time
- Recommendation: Track as tech debt. Consider adding tag sanitization in index rebuild as defense-in-depth.

Both items are non-blocking for deployment. They represent defense-in-depth gaps, not exploitable vulnerabilities.

---

## 5. Ops Impact Alignment

The ops investigation findings are consistent with actual code changes:

- **A2 absolute path finding**: ops index.md line 16 has an absolute path that will be skipped by the containment check. Code confirms this: `file_path.resolve().relative_to(memory_root_resolved)` raises ValueError for absolute paths pointing outside memory root. **Action required**: rebuild ops index after deployment.
- **All other ops findings**: Correctly assessed as no-ops or transparent improvements. No config changes needed for ops. Existing ops data is schema-compatible.
- The ops "pre-existing state" finding (phase1 session retirement incomplete due to Guardian regex bug) is unrelated to the current fixes. Confirmed not a regression.

**Ops findings align with actual code changes.**

---

## 6. Summary Table

| Check | Result |
|-------|--------|
| Cross-file index format consistency | PASS |
| Title sanitization approach compatibility | PASS |
| Category names/folder mapping consistency | PASS |
| CLAUDE.md accuracy | PASS (minor enhancement opportunity) |
| SKILL.md alignment | PASS (no updates needed) |
| hooks.json alignment | PASS (no updates needed) |
| Compile check (both files) | PASS |
| Test suite (existing) | PASS (432/435 pass; 3 failures are stale test assertions) |
| Stale test failures are code bugs? | NO — tests need updating to match correct new behavior |
| xpassed tests (pre-fix tests now passing) | 10 xpassed — expected, confirms fixes work |
| Ops impact understood | PASS |
| V1 non-blocking items tracked | 2 items recommended as tech debt |

---

## Recommended Actions (Non-Blocking)

1. **Fix 3 stale tests** (medium priority):
   - `TestTokenize.test_excludes_short_words`: update to expect `db` IN tokens (C1 fix)
   - `test_score_description_single_prefix_floors_to_zero`: update to expect score == 1 (B2 fix)
   - `test_score_description_one_exact_one_prefix`: update to expect score == 2 (B2 fix)

2. **Add 5 new tests** (medium priority, see section 3.3 above)

3. **Rebuild ops index** after deployment (one-liner, see ops report)

4. **Track 2 tech debt items** (low priority):
   - B4-null: Add null byte stripping to `_sanitize_index_title()`
   - B4-tags: Add tag sanitization in `rebuild_index()`

5. **Optional CLAUDE.md update**: Note that B4 partially addresses the index rebuild gap in Security Considerations item 1

---

## Final Verdict: PASS

All 12 fixes are correctly implemented and properly integrated. Cross-file consistency is verified. Documentation is accurate. Ops impact is understood. The 3 test failures are stale assertions from pre-fix tests, not indicators of code bugs. The 10 xpassed pre-fix tests confirm the fixes are effective. The plugin is ready for deployment with the above non-blocking recommendations tracked.
