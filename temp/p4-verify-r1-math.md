# Verification Report: CONSTRAINT Threshold Fix (Round 1 -- Math/Correctness)

**Verdict: PASS_WITH_NOTES**

**Verifier**: Opus 4.6 (1M context)
**Date**: 2026-03-22
**Perspective**: Mathematical correctness, regex validity, scoring quanta

---

## 1. Mathematical Verification

### Denominator
- Code (line 149): `denominator: 1.9`
- Calculation: `max_primary(3) * primary_weight(0.3) + max_boosted(2) * boosted_weight(0.5) = 0.9 + 1.0 = 1.9`
- **CORRECT**

### Threshold crossing (3 primaries only)
- Score: `3 * 0.3 / 1.9 = 0.9 / 1.9 = 0.473684...`
- Threshold: `0.45`
- Margin: `0.0237` (safe -- well above float64 precision limits)
- **CORRECT**

### Two primaries stay below
- Score: `2 * 0.3 / 1.9 = 0.6 / 1.9 = 0.315789...`
- `0.3158 < 0.45`
- **CORRECT**

### Complete Score Quanta Table

| Primaries (p) | Boosted (b) | Raw Score | Normalized | Triggers? |
|:---:|:---:|:---:|:---:|:---:|
| 0 | 0 | 0.0 | 0.0000 | No |
| 0 | 1 | 0.5 | 0.2632 | No |
| 0 | 2 | 1.0 | 0.5263 | Yes |
| 1 | 0 | 0.3 | 0.1579 | No |
| 1 | 1 | 0.8 | 0.4211 | No |
| 1 | 2 | 1.3 | 0.6842 | Yes |
| 2 | 0 | 0.6 | 0.3158 | No |
| 2 | 1 | 1.1 | 0.5789 | Yes |
| 2 | 2 | 1.6 | 0.8421 | Yes |
| 3 | 0 | 0.9 | 0.4737 | Yes |
| 3 | 1 | 1.4 | 0.7368 | Yes |
| 3 | 2 | 1.9 | 1.0000 | Yes |

Note: "boosted" consumes the primary hit on that line (the scoring logic promotes a primary to boosted when a booster keyword is in the co-occurrence window). So p=0, b=2 means 2 primary regex matches were both promoted to boosted. This is confirmed by `test_cannot_as_booster` where `primary_count == 0` and `boosted_count == 1`.

**Design observation (not a bug):** The combination 1 boosted + 1 unboosted primary (0.4211) does NOT trigger at threshold 0.45. Minimum trigger paths are: 3 pure primaries, 2 boosted, or 2 primaries + 1 boosted. This is a reasonable precision/recall trade-off.

### Config/Code Consistency
- `DEFAULT_THRESHOLDS["CONSTRAINT"]` (line 58): **0.45**
- `assets/memory-config.default.json` `triage.thresholds.constraint` (line 73): **0.45**
- **MATCH -- CORRECT**

---

## 2. Regex Correctness

### Syntax
All regex patterns compile without error. Verified via test execution (9/9 pass).

### Word boundary (`\b`) with multi-word patterns
`\b` works correctly with multi-word patterns like `does\s+not\s+support` because:
- `\b` checks the boundary between word chars `[a-zA-Z0-9_]` and non-word chars
- All multi-word patterns start and end with alphabetic characters
- `\s+` (whitespace) matches between the words, which is correctly bounded

Verified empirically:
- `"The API does not support this"` -- matches
- `"does  not  support"` (extra spaces) -- matches (due to `\s+`)
- `"NOT SUPPORTED"` -- matches (due to `re.IGNORECASE`)
- `"notsupported"` -- does NOT match (correct: no whitespace)

### `cannot` as booster interaction
`cannot` is now correctly a booster-only keyword. Verified:
- 3x "cannot" alone -> score 0.0 (test_cannot_not_primary: PASS)
- "quota" + "cannot" in window -> boosted score 0.2632 (test_cannot_as_booster: PASS)
- "error" + "cannot" -> score 0.0 for CONSTRAINT (test_constraint_runbook_overlap_reduced: PASS)

### Cross-category overlap
No CONSTRAINT primary keywords overlap with other categories' primaries (DECISION, RUNBOOK, TECH_DEBT, PREFERENCE). CONSTRAINT boosters (e.g., "deprecated", "discovered") could co-occur with other categories' contexts but they only amplify when a CONSTRAINT primary is already present, so no false cross-triggering.

### Minor observation: plural forms and `\b`
The `\b` at the end of the group means exact word endings only:
- `"limitation"` matches, but `"limitations"` does NOT match
- `"quota"` matches, but `"quotas"` does NOT match
- `"rate limit"` matches, but `"rate limits"` does NOT match

This is a pre-existing pattern behavior (not introduced by this fix), and "limitation" (singular) is the more common form in constraint-description contexts. The 11 alternation entries provide sufficient coverage. Not a defect, but worth documenting.

---

## 3. Test Coverage Assessment

All 9 tests in `TestConstraintThresholdFix` pass. Coverage:

| Test | What it verifies | Verdict |
|------|-----------------|---------|
| `test_three_primaries_crosses_threshold` | 3 primaries = 0.4737 > 0.45 | Good |
| `test_two_primaries_below_threshold` | 2 primaries = 0.3158 < 0.45 | Good |
| `test_cannot_not_primary` | cannot alone = 0.0 | Good |
| `test_cannot_as_booster` | primary + cannot = boosted 0.2632 | Good |
| `test_constraint_runbook_overlap_reduced` | error + cannot != CONSTRAINT | Good |
| `test_new_primaries_score` | 5 new primaries register | Good |
| `test_new_boosters_boost` | 7 new boosters amplify | Good |
| `test_other_categories_unaffected` | 5 other thresholds unchanged | Good |
| `test_default_threshold_value` | CONSTRAINT threshold == 0.45 | Good |

**Missing edge case (minor):** No test for the exact boundary case of 1 boosted + 1 unboosted (0.4211 < 0.45) to confirm it stays below threshold. Not critical since the quanta math is deterministic, but would strengthen the regression suite.

---

## 4. Issues Found

### ISSUE 1: Stale documentation in `commands/memory-config.md` (line 36)

**Severity: LOW (documentation only)**

Line 36 still reads:
```
Defaults: decision=0.4, runbook=0.4, constraint=0.5, tech_debt=0.4, preference=0.4, session_summary=0.6
```

Should be `constraint=0.45`. This does not affect runtime behavior (the code and config file are correct), but users reading the help text will see the old value.

**File:** `/home/idnotbe/projects/claude-memory/commands/memory-config.md` line 36

### ISSUE 2: Fallback threshold 0.5 on line 485 (informational, not a bug)

Line 485 uses `thresholds.get(entry["category"], 0.5)` as a fallback for unknown categories. This is correct for its purpose (conservative default for hypothetical new categories) and does NOT affect CONSTRAINT since it always has an explicit entry in `DEFAULT_THRESHOLDS`. No action needed.

---

## 5. Cross-Model Feedback Summary (Gemini 3.1 Pro)

Gemini confirmed:
1. **Margin (0.0237)** is safe -- well above float64 precision limits
2. **Regex `\b` + multi-word** patterns work correctly
3. **`cannot` demotion** causes expected recall loss for "cannot-only" constraint text -- this is an intended trade-off for false positive reduction
4. **Additional finding**: 1 boosted + 1 unboosted (0.4211) does not trigger -- verified this is a design choice, not a bug

No mathematical errors or regex problems identified by Gemini.

---

## 6. Final Verdict

**PASS_WITH_NOTES**

The implementation is mathematically correct, the regex patterns are valid and well-bounded, the tests cover the critical scenarios, and the config/code values are consistent. The only actionable finding is a stale documentation string in `commands/memory-config.md` line 36 (says `constraint=0.5` instead of `constraint=0.45`).
