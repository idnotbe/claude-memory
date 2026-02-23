# Fresh-Eyes Review: plan-retrieval-confidence-and-output.md

**Reviewer:** reviewer-fresh
**Date:** 2026-02-22
**Verdict:** PASS WITH NOTES

---

## Summary

The plan is internally consistent in its core logic, well-structured with clear action ordering and rollback strategies, and would be implementable by an engineer familiar with the codebase. However, a first-time reader faces significant cognitive overhead from embedded historical debate, and there are a few numeric discrepancies and flow issues that could cause confusion.

---

## A. Internal Logic Consistency

### A1. ISSUE (MEDIUM): LOC Estimates Disagree Between Header and Breakdown

**Header (line 11):** `~60-80 LOC (code) + ~100-200 LOC (tests)`
**Detailed breakdown table (lines 452-460):**
- Code subtotal: `~66-105 LOC`
- Test subtotal: `~130-240 LOC`

Both ranges exceed the header estimates. The code upper bound is 105 vs 80 (31% higher). The test lower bound is 130 vs 100 (30% higher), and upper bound is 240 vs 200 (20% higher).

Additionally, Action #4 (Agent Hook PoC) is listed in the plan title ("Actions #1-#4") but has no LOC row in the breakdown table. This is presumably because it's on a separate branch, but the omission is not explained.

### A2. OK: Cluster Detection -- Disabled/Active Consistency

The cluster detection feature is consistently described as disabled throughout:
- `cluster_detection_enabled: false` (default, line 72)
- `cluster_count=0` always passed (line 103, 106)
- "비활성 유지" repeated in checklist items (line 139, 253)

All mentions point the same direction. Internally consistent.

### A3. OK: abs_floor Range Mentions

The abs_floor is consistently described in composite score domain:
- "1.0-3.0" recommended starting value (lines 68, 102)
- "roughly 0-15 range" for composite scores overall (line 91, 102)
- Default `0.0` = disabled (lines 66-67)

The numbers are consistent with each other. The 1.0-3.0 range is the threshold, 0-15 is the domain -- these are different things and do not conflict. However, see readability note B2 below.

### A4. OK: Score Domain (composite vs raw_bm25)

The plan consistently maintains that `confidence_label()` uses composite scores (BM25 - body_bonus), not raw_bm25. This is stated at lines 88-89, 101, 140-141. The code at `memory_retrieve.py:299` confirms: `entry.get("score", 0)` is passed, and `score` is the composite value (mutated at line 257). Internally consistent.

### A5. OK: Test Count Cross-Check

- Action #1: "~10-12 tests" stated. Checklist lists: abs_floor boundary (~8) + cluster_count=0 regression (~2) + existing 17 regression = matches.
- Action #2: "~15-30 tests" stated. Checklist lists: tiered mode output (~6) + security (~4) + tag preservation (~2) + search hint (~3) = ~15. The range upper bound 30 accounts for additional edge cases. Reasonable.
- Action #3: "~5-8 tests" stated. Checklist lists: emit_search_hint output (~3) + integration (~3) = ~6. Consistent.

---

## B. Readability and Understanding

### B1. ISSUE (HIGH): Excessive Historical Debate Obscures Implementation Steps

Action #1's "Related Info" section (lines 45-107) is dominated by review history and rejected alternatives. The "Score Domain Paradox" block (lines 81-93) is 13 lines of quoted historical debate including references to "V2-adversarial", "Deep Analysis", "NEW-4, HIGH", "Ranking-Label Inversion", two external model opinions, and a rejected proposal -- all to conclude "no code change needed."

Similarly, the cluster detection section (lines 71-79) references "Deep Analysis", "Cluster Tautology mathematical proof", "V2-fresh", "V2-adversarial", "Option B (pre-truncation counting)", and "dead code" -- all to conclude "keep it disabled."

A first-time reader would spend significant effort parsing what was rejected vs what needs to be built. The actual implementation requirements are buried within the historical context.

**Recommendation:** Move historical justifications to an appendix or collapsed section. Keep the action items focused on "what to build" and "why" (functional reason), not "what was debated and rejected."

### B2. ISSUE (LOW): abs_floor Domain Relationship Not Immediately Clear

The plan states `abs_floor` recommended range is `1.0-3.0` and the composite score domain is "roughly 0-15." A first-time reader might wonder: why is the floor only 1.0-3.0 when scores go up to 15? What fraction of scores would be affected?

The plan does note this is corpus-dependent and a PoC adjustment (line 69), but the relationship between the threshold and the domain could be stated more explicitly. Something like: "1.0-3.0 targets the weakest tail of matches (roughly the bottom 10-20% of observed scores)."

### B3. ISSUE (LOW): body_bonus Introduced Without Definition

The term `body_bonus` appears in the Score Domain Paradox block (line 83) without prior definition. It is explained indirectly ("BM25 - body_bonus") but never explicitly defined. A reader unfamiliar with the codebase would need to read `score_with_body()` in `memory_retrieve.py:247` to understand this is a 0-3 bonus for body text token matches.

### B4. ISSUE (LOW): Inconsistent Terminology for "Deactivated" Feature

The cluster detection feature is described using multiple terms:
- "비활성 유지" (keep inactive, line 77)
- "비활성 기능" (inactive feature, line 103)
- "현재 비활성" (currently inactive, line 103)
- "비활성 -- 향후 활성화 시" (inactive -- when activated in future, line 106)
- "기능 비활성 유지 확인" (confirm feature remains inactive, line 139)

This is consistent in meaning but verbose. Each mention re-explains the same point. A single definitive statement with a back-reference would be cleaner.

---

## C. Structural Completeness

### C1. OK: Action Scopes and Dependencies

The 4 actions have clear scopes:
- Action #1: `confidence_label()` function modification
- Action #2: `_output_results()` output branching
- Action #3: Hint format change (3 locations + new helper)
- Action #4: PoC on separate branch

Dependencies are explicit: #1 -> #2 -> #3, #4 independent. The dependency diagram (lines 396-399) matches the textual explanation (lines 402-406).

### C2. OK: Verification Gates

Gates A-D (lines 443-446) are defined and map to action completion points. Gate D (manual review with 20-30 prompts) is appropriately deferred to post-logging-infrastructure.

### C3. OK: YAML Frontmatter

`status: not-started` and `progress: "미시작..."` are consistent with each other and with the all-unchecked checklists.

### C4. ISSUE (LOW): Action #4 Has No Verification Gate Criteria

Actions #1-3 have Gates A-C. Action #4 has a checklist but no explicit pass/fail verification gate criteria. The checklist item "결과 문서화" (line 387) is the closest, but there is no gate that says "Action #4 passes if X, Y, Z are answered."

---

## D. Numeric Cross-Verification

### D1. Code Line References -- Verified Against Source

| Plan Reference | Claim | Actual Code | Status |
|---|---|---|---|
| `confidence_label()` at line 161-174 | Function definition | `memory_retrieve.py:161-174` | MATCH |
| `_output_results()` at line 262-301 | Function definition | `memory_retrieve.py:262-301` | MATCH |
| `score_with_body()` body_bonus mutation at line 257 | `r["score"] = r["score"] - body_bonus` | `memory_retrieve.py:257` | MATCH |
| `raw_bm25` preservation at line 256 | `r["raw_bm25"] = r["score"]` | `memory_retrieve.py:256` | MATCH |
| `_output_results()` confidence_label call at line 299 | `conf = confidence_label(...)` | `memory_retrieve.py:299` | MATCH |
| `main()` config parsing at line 353-384 | Config parsing block | `memory_retrieve.py:349-384` | CLOSE (off by 4 lines at start) |
| `apply_threshold()` at line 283-288 | 25% noise floor | `memory_search_engine.py:283-289` | CLOSE (off by 1 at end) |
| Hint at line 458 | FTS5 no-result hint | `memory_retrieve.py:458` | MATCH |
| Hint at line 495 | Legacy no-score hint | `memory_retrieve.py:495` | MATCH |
| Hint at line 560 | Legacy deep-check hint | `memory_retrieve.py:560` | MATCH |
| `TestConfidenceLabel` at line 493-562 | Test class | `test_memory_retrieve.py:493-562` | MATCH |
| `test_single_result_always_high` at line 535 | Test case | `test_memory_retrieve.py:535` | MATCH |
| `test_all_same_score_all_high` at line 539 | Test case | `test_memory_retrieve.py:539` | MATCH |
| `test_confidence_label_in_output` at line 618 | Test case | `test_memory_retrieve.py:618` | MATCH |
| `test_no_score_defaults_low` at line 649 | Test case | `test_memory_retrieve.py:649` | MATCH |
| `test_result_element_format` at line 658 | Test case | `test_memory_retrieve.py:658` | MATCH |
| `test_output_results_captures_all_paths` at line 1063 | Adversarial test | `test_v2_adversarial_fts5.py:1063` | MATCH |
| `test_output_results_description_injection` at line 1079 | Adversarial test | `test_v2_adversarial_fts5.py:1079` | MATCH |

**Result:** 16/18 exact match, 2/18 off by a few lines. All references point to the correct functions/tests. No broken references found.

### D2. TestConfidenceLabel Count

Plan claims "17 tests" at line 113. Actual test class `TestConfidenceLabel` (lines 493-562) contains methods:
1. `test_high_at_075`
2. `test_medium_just_below_075`
3. `test_medium_at_040`
4. `test_low_just_below_040`
5. `test_ratio_1_is_high`
6. `test_best_score_zero_returns_low`
7. `test_both_zero_returns_low`
8. `test_score_zero_best_nonzero_returns_low`
9. `test_negative_bm25_scores`
10. `test_positive_legacy_scores`
11. `test_single_result_always_high`
12. `test_all_same_score_all_high`
13. `test_negative_zero`
14. `test_nan_degrades_to_low`
15. `test_inf_best_zero`
16. `test_missing_score_defaults_zero`
17. `test_integer_inputs`

**Count: 17.** MATCH.

### D3. Rollback Count

Plan states "rollback 3 settings" (line 418): `confidence_abs_floor`, `cluster_detection_enabled`, `output_mode`. The rollback table (lines 410-416) lists exactly 3 config-based rollbacks + 1 code revert (Action #3) + 1 branch delete (Action #4). Consistent.

### D4. ISSUE (MEDIUM): Header LOC vs Table LOC (repeat of A1)

Header: `~60-80 LOC (code) + ~100-200 LOC (tests)` = `~160-280 total`
Table: `~66-105 LOC (code) + ~130-240 LOC (tests)` = `~196-345 total`

The table's total line (460) shows `~196-345` which is correct for its own rows but disagrees with the header. The header should be updated to match the detailed breakdown.

---

## E. External Model Feedback (Gemini 3.1 Pro)

An external review via Gemini 3.1 Pro (codereviewer role) independently identified:
1. **Overwhelming historical context** -- same as finding B1 above
2. **LOC discrepancies** -- same as finding A1/D4 above
3. **abs_floor vs domain range ambiguity** -- same as finding B2 above
4. **Contradictory stance on cluster detection** -- Background lists it as flaw #2 but Action #1 disables the fix. (Plan is internally consistent but the narrative flow is confusing)
5. **body_bonus unexplained** -- same as finding B3 above

All external findings align with or supplement the internal review findings. No new critical issues discovered.

---

## Verdict: PASS WITH NOTES

### Why PASS:
- Core logic is internally consistent (score domain, cluster detection state, test references)
- All 18 code line references verified (16 exact, 2 within 4 lines)
- Test counts match
- Action dependencies, rollback strategies, and verification gates are well-defined
- YAML frontmatter matches document state

### Notes for Improvement:
1. **(MEDIUM) Fix LOC header** to match detailed breakdown (`~66-105 code` + `~130-240 tests`), or add a footnote explaining the discrepancy
2. **(HIGH readability) Move historical debate** (Score Domain Paradox, Cluster Tautology proof, rejected proposals) to an appendix -- the current inline placement makes Action #1 hard to parse for a new reader
3. **(LOW) Define body_bonus** briefly before first use in the Score Domain block
4. **(LOW) Clarify abs_floor/domain relationship** with one sentence explaining what fraction of scores the threshold targets
5. **(LOW) Add Action #4 to LOC table** or add an explicit exclusion note
6. **(LOW) Add verification criteria for Action #4** (what constitutes a successful PoC?)

None of these notes represent logical errors or implementation blockers. The plan is implementable as-is; the notes improve readability and reduce cognitive load for the implementing engineer.
