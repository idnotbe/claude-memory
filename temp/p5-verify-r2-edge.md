# Phase 5 -- Verification Round 2: Edge Case & Regression

**Verifier perspective**: Edge cases, regression risks, implementation gaps
**Verdict**: **PASS_WITH_NOTES**

---

## 1. Edge Case Analysis

### EC1: Both `not supported` and `does not support` on same line
- **Input**: `"This feature does not support X and is not supported by Y"`
- **Expected**: Single count (per-line `break` at L402)
- **Actual**: Correct -- `re.search` finds first match (`does not support`), `break` fires, one count
- **Status**: PASS

### EC2: `unlimited to` false positive prevention
- **Input**: `"We have unlimited to 100 users"`
- **Expected**: No match (`\b` prevents matching inside "unlimited")
- **Actual**: Correct -- `\b` word boundary at start of `limited\s+to` requires word boundary between 'n' and 'l', which doesn't exist in "unlimited"
- **Status**: PASS

### EC3: `limited to` as verb (false positive risk)
- **Input**: `"We limited to 3 retries for safety"`
- **Expected**: Should NOT match (verb form, not a constraint)
- **Actual**: MATCHES -- `\b` cannot distinguish verb vs adjective/prepositional usage
- **Status**: NOTE -- Known acceptable false positive. The scoring system requires 3+ primary hits OR primary+booster co-occurrence to cross threshold, so a single verb-form match alone cannot trigger the category. Risk is marginal.

### EC4: Multi-line `does\nnot\nsupport`
- **Input**: Line 1: `"This does"`, Line 2: `"not support"`
- **Expected**: No match (lines are scored independently)
- **Actual**: Correct -- Line 1 has no primary match; Line 2 has `"not support"` without `ed`, which does not match `not\s+supported`
- **Status**: PASS

### EC5: `vendor limitation` (primary) + `not configurable` (booster) on same line
- **Input**: `"This vendor limitation is not configurable"`
- **Expected**: Primary match for `vendor limitation`; booster `not configurable` detected in window (which includes current line)
- **Actual**: Correct -- `_has_pattern_in_window` includes center line (L346-347: `range(start, end)` includes `center_idx`), so booster fires on same line
- **Status**: PASS

### EC6: Plurals (`limitations`, `api limits`, `quotas`)
- **Input**: `"There are multiple limitations"`
- **Expected**: No match (trailing `\b` prevents matching within longer words)
- **Actual**: Correct -- `limitation\b` does not match `limitations` because `\b` requires boundary between 'n' and 's', but both are word chars
- **Status**: NOTE -- This is a coverage gap identified by cross-model review. Plurals like `limitations`, `api limits`, `rate limits`, `quotas` are not matched. This is a potential future improvement but OUT OF SCOPE for this threshold fix. The current patterns match the singular forms which appear in most constraint-describing language.

### EC7: Hyphenated forms (`rate-limit`, `api-limit`)
- **Input**: `"There is a rate-limit on this endpoint"`
- **Expected**: Unclear -- hyphen is a word boundary character
- **Actual**: No match -- the pattern `rate\s+limit` requires whitespace (`\s+`), not hyphen
- **Status**: NOTE -- Another coverage gap for future improvement. OUT OF SCOPE for this fix.

### EC8: Booster `cannot` on same line as primary
- **Input**: Primary `quota` + booster `cannot` on same line
- **Expected**: Boosted weight applied (window includes current line)
- **Actual**: Correct -- verified via `_has_pattern_in_window` range logic and existing test `test_cannot_as_booster`
- **Status**: PASS

---

## 2. Fallback Threshold (Line 485)

```python
threshold = thresholds.get(entry["category"], 0.5)
```

This uses 0.5 as fallback for **unknown/hypothetical future categories** that are not in the thresholds dict. It does NOT affect CONSTRAINT because CONSTRAINT always has an explicit entry in `DEFAULT_THRESHOLDS`. This is correct and documented in previous verification (p4-verify-r1-math.md).

**Status**: PASS (not a stale reference)

---

## 3. Stale Reference Audit

### Live code/documentation (non-temp, non-ref):
| File | Value | Status |
|------|-------|--------|
| `hooks/scripts/memory_triage.py` L58 | `"CONSTRAINT": 0.45` | CORRECT |
| `assets/memory-config.default.json` L73 | `"constraint": 0.45` | CORRECT |
| `README.md` L192 | `constraint=0.45` | CORRECT |
| `commands/memory-config.md` L36 | `constraint=0.45` | CORRECT |
| `tests/test_memory_triage.py` L2141 | Tests assert 0.45 | CORRECT |

### Historical/reference files (old 0.5 references -- acceptable):
- `action-plans/_ref/log-review-2026-03-22.md` -- Historical analysis documenting the bug
- `action-plans/plan-fix-constraint-threshold.md` -- Plan document describing the problem
- `tests/test_memory_triage.py` L1965 -- Docstring: "0.5 -> 0.45" (describes the fix)
- `temp/*` -- ~30 references in working/analysis files (historical artifacts)

**Status**: PASS -- No stale references in live code or documentation.

---

## 4. Test Results

```
pytest tests/test_memory_triage.py -v
97 passed in 0.18s
```

All 9 `TestConstraintThresholdFix` tests pass:
- `test_three_primaries_crosses_threshold` -- boundary test (0.4737 > 0.45)
- `test_two_primaries_below_threshold` -- boundary test (0.3158 < 0.45)
- `test_cannot_not_primary` -- demotion verification
- `test_cannot_as_booster` -- booster co-occurrence
- `test_constraint_runbook_overlap_reduced` -- overlap regression
- `test_new_primaries_score` -- 5 new keyword coverage
- `test_new_boosters_boost` -- 7 new booster amplification
- `test_other_categories_unaffected` -- regression guard
- `test_default_threshold_value` -- threshold assertion

All hook scripts compile cleanly (14/14 OK).

---

## 5. Cross-Model Review (Gemini 3.1 Pro)

Confirmed all 3 primary edge case questions:
1. No double-count on same-line overlapping patterns (break + re.search first-match)
2. `\b` correctly prevents `unlimited to` false positive
3. `_has_pattern_in_window` includes center line for same-line booster detection

Raised 4 future improvement suggestions (all OUT OF SCOPE for this fix):
- Plural forms (`limitations`, `api limits`) not matched
- Hyphenated forms (`rate-limit`) not matched
- Contractions (`doesn't support`) not matched
- Inline code stripping may remove keywords in backticks

These are valid observations for future keyword expansion but do not indicate bugs in the current fix.

---

## 6. Summary

| Check | Result |
|-------|--------|
| Edge case: same-line overlap | PASS |
| Edge case: `unlimited to` prevention | PASS |
| Edge case: `limited to` verb false positive | NOTE (marginal, mitigated by threshold) |
| Edge case: multi-line split | PASS |
| Edge case: same-line primary+booster | PASS |
| Edge case: plural forms | NOTE (coverage gap, out of scope) |
| Edge case: hyphenated forms | NOTE (coverage gap, out of scope) |
| Fallback threshold L485 | PASS (correct, not stale) |
| Stale references in live code | PASS (none found) |
| Test suite | PASS (97/97) |
| Compile check | PASS (14/14) |
| Cross-model validation | PASS (confirmed) |

**Verdict: PASS_WITH_NOTES**

The CONSTRAINT threshold fix is correctly implemented. The three "NOTE" items (verb-form false positive, plurals, hyphenated forms) are known coverage gaps that represent future enhancement opportunities, not bugs in the current fix. The threshold change, keyword additions, and scoring logic are mathematically sound and well-tested.
