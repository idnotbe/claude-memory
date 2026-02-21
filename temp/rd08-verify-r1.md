# Verification Round 1: Multi-Perspective Check

**Document:** `research/rd-08-final-plan.md` (1332 lines)
**Verifier:** V1 Lead Agent
**Date:** 2026-02-21
**Scope:** Post-R4 whole-document verification (R4 fixes applied, checking integration correctness + internal consistency + implementability + remaining risks)

---

## Overall Verdict: VERIFIED WITH CAVEATS

The document is internally consistent, implementable, and ready for development. All 18 R4 fixes were correctly applied. The 3 remaining issues found are all LOW severity and do not block implementation. The plan has been through 4+ rigorous review rounds; further document-level review would yield diminishing returns. The recommended next step is to begin implementation at Session 1.

**Confidence: HIGH** (full document read, cross-referenced against 6 source files + 3 review summaries, external model verification via Gemini 3.1 Pro)

---

## R4 Fix Application Verification

All 18 changes from `temp/rd08-r4-writer-summary.md` were verified as correctly applied:

| Fix | Applied? | Location Verified |
|-----|----------|-------------------|
| H1: FTS5 schema (remove id/updated_at) | YES | Lines 234-262 |
| H2: score_with_body() user_prompt param | YES | Lines 270-298 |
| M1: CATEGORY_PRIORITY uppercase | YES | Lines 98-102 |
| M2: Redundant set() removed | YES | Line 288 |
| M3: CamelCase blind spot in Risk Matrix | YES | Line 1174 |
| L1: Test factory coverage note | YES | Line 1081 |
| L2: Line reference 29->28 | YES | Line 359 |
| A1: main() pseudocode added | YES | Lines 303-317 |
| A2: score_description() fate decided | YES | Lines 156-158 (Decision #8) |
| G1: Config migration subsection | YES | Lines 1225-1231 |
| G2: Tokenizer sync tracking | YES | Line 1066 |
| G3: sys.path import pattern | YES | Lines 337-343 |
| I1: Skill vs command decision | YES | Lines 347, 1062 |
| I2: CLAUDE.md update scope expanded | YES | Line 1065 |
| E1: Session 4 estimate 10-12 hrs | YES | Lines 1074, 1122, 1136 |
| E2: Measurement gate prerequisite | YES | Line 1091 |
| Header metadata updated | YES | Lines 3, 5, 6 |
| R4 audit trail row | YES | Line 1319 |

---

## Subagent A: Consistency Auditor

### LOC Totals

| Metric | Claimed | Calculated | Match? |
|--------|---------|------------|--------|
| Mandatory LOC (S1-S6) | ~470-510 | 80+220+100+20+70+0 = 490 | YES |
| Full LOC (S1-S9) | ~990-1030 | 490+170+280+70 = 1010 | YES |
| Mandatory time (S1-S6) | ~3-4 days | Sum of hrs: 4-6+6-8+4-6+1-2+10-12+3-4 = 28-38 hrs | YES (at ~8-10 hrs/day) |

### Session Order Consistency

The session order `S1 -> S2 -> S3 -> S5 -> S4 -> S6 -> S7 -> S8 -> S9` appears consistently in:
- Line 24 (exec summary note)
- Lines 1001-1002 (Section A)
- Lines 1007 (dependency graph)
- Lines 1130-1140 (Schedule table, S5 listed before S4)
- Line 1145 (closing note)

All consistent. No contradictions.

### Cross-Reference Checks

| Claim in Plan | Source File | Match? |
|---------------|------------|--------|
| `parse_index_line()` returns `category, title, path, tags, raw` | memory_retrieve.py:72-90 | YES |
| CATEGORY_PRIORITY uses uppercase keys | memory_retrieve.py:38-45 | YES |
| `_TOKEN_RE = re.compile(r"[a-z0-9]+")` | memory_retrieve.py:54 | YES |
| `score_description` imported at line 28 of test_adversarial | test_adversarial_descriptions.py:28 | YES |
| UserPromptSubmit hook timeout = 10s | hooks.json:51 | YES |
| Current `max_inject` default = 5 | memory-config.default.json:51 | YES |
| Current `match_strategy` = "title_tags" | memory-config.default.json:52 | YES |
| plugin.json skills array = `["./skills/memory-management"]` | .claude-plugin/plugin.json:15-17 | YES |
| plugin.json commands includes `./commands/memory-search.md` | .claude-plugin/plugin.json:12 | YES |
| `commands/memory-search.md` exists | Glob confirmed | YES |

### Inconsistencies Found

**LOW-1: Risk Matrix "test rewrite" row says "8-10 hours" but Session 4 was updated to 10-12 hours**
- Location: Line 1159 mitigation text: "Budget 8-10 hours (Session 4)"
- Should be: "Budget 10-12 hours (Session 4)" to match the R4-corrected estimate
- Impact: Cosmetic. The actual session checklist and schedule table are both correct at 10-12 hours. Only the risk matrix mitigation text is stale.

**LOW-2: Executive Summary total (~850-1000 LOC, ~4-5 days) doesn't match either schedule total**
- Location: Line 22
- Mandatory: ~470-510 LOC, ~3-4 days. Full: ~990-1030 LOC, ~5-6 days.
- The exec summary range falls between the two but matches neither exactly.
- Impact: The detailed Schedule table (lines 1130-1143) is clearly authoritative. The exec summary was likely written in an earlier round. A developer would use the schedule table, not the exec summary, for planning.

**LOW-3: main() pseudocode uses `match_strategy=` keyword but `apply_threshold()` signature uses `mode=`**
- Location: Line 311 (`apply_threshold(scored, match_strategy="fts5_bm25")`) vs Line 89 (`def apply_threshold(results, mode="auto")`)
- Impact: Negligible. This is explicitly labeled as pseudocode, and the actual function definition with correct signature is 220 lines above.

---

## Subagent B: Fresh Eyes Implementer

Assessment: **Can follow the plan.** A developer reading ONLY rd-08-final-plan.md (without the review files) would be able to implement the system.

### Strengths
1. **Session checklists are actionable.** Each session has concrete checkboxes that can be completed independently. The `[R4-fix]` markers clearly distinguish new items from original ones.
2. **Code samples are copy-paste-ready** (post-R4 fixes). The FTS5 table creation, smart wildcard function, body extraction, and threshold logic are all syntactically correct Python.
3. **Dependency graph is clear.** The visual dependency chain (lines 1005-1014) makes session ordering unambiguous.
4. **Fallback path is well-specified.** A developer knows exactly what happens when FTS5 is unavailable.
5. **Decision #8 (score_description fate)** resolves the ambiguity. The developer doesn't need to make this architectural call.

### Potential Confusion Points
1. **main() restructuring** (Session 2) is pseudocode-level. The actual main() in memory_retrieve.py is ~190 LOC with 11 exit paths. The pseudocode covers the branching logic but the developer will need to study the current main() carefully to understand where each piece fits. This was flagged in R4 practical review and the pseudocode was added; it's adequate for an experienced developer.
2. **"~100 LOC net new" for Session 3** -- the note explains that moved code isn't counted, but a developer might initially wonder where the 100 LOC comes from when the extraction involves more lines of code movement. The parenthetical "~70-90 Python + ~50 skill markdown" clarifies this.
3. **Phase 2d validation gate** is embedded in the Session 4 checklist (lines 1083-1088) rather than being a separate session. This is fine -- it's clearly marked as "REQUIRED gate" -- but a developer might initially think Session 4 is "just tests" and skip the validation steps.

### Verdict
An experienced Python developer familiar with this codebase could follow the plan without needing to consult the review files. The plan is self-contained for implementation purposes.

---

## Subagent C: Adversarial Skeptic

### Ways the Plan Could Fail

**1. FTS5 Breaks (Handled)**
The plan has a mandatory fallback path (Decision #7, ~15 LOC). If FTS5 is unavailable, the system reverts to the existing keyword scorer. The fallback is tested in Session 4. This is a well-mitigated risk.

**2. Measurement Gate Shows Poor Results (Handled)**
If FTS5 BM25 precision < 80% at Session 6, the plan proceeds to the judge layer (Phase 3). If precision is clearly above 80%, Phase 3 is skipped. The gate has a known statistical weakness (expanded from 20 to 40-50 queries, still a directional check, not precise). This is explicitly acknowledged in the plan. The escape hatch is well-defined.

**3. Test Coverage Insufficient (Mitigated)**
Session 4 at 10-12 hours is the tightest part of the plan. The R4 fix suggests potentially splitting into 4a/4b. The biggest risk is that FTS5-specific tests reveal edge cases not covered by the plan (e.g., FTS5 behavior differences across SQLite versions). Mitigation: the performance benchmark (500 docs < 100ms) provides a concrete gate.

**4. score_description() Preservation Creates Dead Code (Accepted)**
Decision #8 keeps `score_description()` for the fallback path but it's dead code in the FTS5 path. This is explicitly a maintenance tradeoff: slightly more code to maintain vs. avoiding an import cascade. Reasonable for a personal project.

**5. CamelCase Blind Spot (Acknowledged)**
The plan acknowledges this limitation (Risk Matrix line 1174) but doesn't solve it. In mixed-convention codebases, camelCase identifiers won't be found by snake_case queries. The mitigation (prefer snake_case in titles, add variants to tags) is documentation-level, not code-level. This is a real precision gap but bounded -- most of this plugin's users likely use it for Python projects where snake_case is dominant.

**6. Config Migration Silent Upgrade (Minor Risk)**
The plan defaults to `fts5_bm25` when `match_strategy` is absent (line 1229). Existing users get FTS5 automatically. If FTS5 has a bug, they'd see different behavior with no obvious cause. Mitigation: the plan specifies stderr output for FTS5 fallback, and users can explicitly set `"title_tags"` to revert.

### Weakest Assumptions
1. **"500 docs < 100ms"** -- Reasonable for in-memory FTS5, but includes Python interpreter startup (~20-40ms) per invocation. The plan acknowledges this. If startup becomes a concern, persistent index.db is listed as a future enhancement.
2. **"42% of tests break"** -- This is an estimate that was revised across R3 (originally 42%, Track C said 60-63%, meta-critique corrected back). The actual breakage will only be known during Session 4. The 10-12 hour budget provides margin.

### Overall Risk Assessment
No showstopper risks remain. The plan's layered approach (FTS5 first, measure, then optionally add judge) means each phase can be validated independently before proceeding. The fallback paths are well-specified. The main risk is Session 4 taking longer than estimated, which is a scheduling risk, not an architectural risk.

---

## Cross-Model Verification (Gemini 3.1 Pro via pal clink)

Two claims verified that had NOT been checked in prior rounds:

**Claim 1: FTS5 query injection prevention**
- Plan claim (line 985): "FTS5 query injection prevented: alphanumeric + `_.-` only, all tokens quoted" + "Parameterized queries (`MATCH ?`) prevent SQL injection"
- Gemini verdict: **ACCURATE** with important nuance: Parameterized queries prevent SQL injection only. FTS5 syntax injection prevention comes from the sanitization + quoting layer. The two defenses work together. A user who strips sanitization but keeps `MATCH ?` would still be vulnerable to FTS5 syntax injection (column filters, boolean operators).
- Impact: The plan's security model is sound but the wording slightly conflates the two defense layers. An implementer should understand that both sanitization AND parameterization are required.

**Claim 2: ThreadPoolExecutor parallelization for dual judge**
- Plan claim (line 921): "Use `concurrent.futures.ThreadPoolExecutor` to parallelize the two calls (~1.2s instead of ~2.5s sequential)"
- Gemini verdict: **ACCURATE**. Python releases the GIL during I/O-bound operations like `urllib.request.urlopen`. ThreadPoolExecutor effectively parallelizes network wait times. The ~50% latency reduction for two concurrent I/O calls is realistic.

---

## Vibe Check Outcome

**Assessment: Proportionate.** After 4 prior rounds of review with 6+ specialists, the marginal value of finding NEW design issues is very low. This V1 check correctly focused on:
1. Verifying all R4 fixes were applied correctly (they were -- all 18/18)
2. Checking internal consistency after 4 rounds of edits (found 3 LOW issues)
3. Assessing implementability from a fresh perspective (adequate)
4. Confirming no remaining blocking risks (none found)

The plan has received thorough, multi-perspective review. The remaining LOW issues are cosmetic and do not affect implementation correctness. Further document-level review would be diminishing returns. The next high-value activity is starting implementation.

---

## Remaining Issues Summary

| # | Severity | Issue | Location | Fix Effort |
|---|----------|-------|----------|------------|
| LOW-1 | LOW | Risk Matrix says "8-10 hours" for Session 4; should be "10-12 hours" | Line 1159 | 1 min |
| LOW-2 | LOW | Exec summary LOC/time range (~850-1000, ~4-5 days) doesn't match either schedule total | Line 22 | 2 min |
| LOW-3 | LOW | Pseudocode uses `match_strategy=` keyword but function uses `mode=` | Line 311 vs Line 89 | N/A (pseudocode) |

**Recommendation:** Fix LOW-1 and LOW-2 during Session 1 warm-up (trivial edits). LOW-3 can be ignored (pseudocode is not copy-pasted). No blocking issues.

---

## Verification Metadata

| Dimension | Method | Result |
|-----------|--------|--------|
| R4 fix application | Line-by-line verification against writer summary | 18/18 applied correctly |
| LOC totals | Arithmetic check | Consistent |
| Session ordering | 5-location cross-check | Consistent |
| Source file cross-refs | 10 claims verified against actual source files | All match |
| External model verification | Gemini 3.1 Pro via pal clink (2 claims) | Both confirmed |
| Vibe check | pal challenge self-assessment | Proportionate |
