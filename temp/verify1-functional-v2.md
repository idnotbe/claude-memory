# Verification Round 1 -- Functional

**Verifier:** v1-functional
**Date:** 2026-02-20
**Method:** Independent code verification + Gemini cross-validation via clink
**Files verified:** 7 research files, 2 review files, 2 source code files

---

## Review Finding Validation

### From reviewer-accuracy

#### ISSUE 1: `user_prompt` vs `prompt` field name -- CONFIRMED

**Evidence:**
- `memory_retrieve.py:218` reads `hook_input.get("user_prompt", "")`
- `01-research-claude-code-context.md:191` correctly identifies the official field as `prompt` (from Anthropic hooks docs)
- `06-qa-consolidated-answers.md` line 168 (pre-fix) showed `"user_prompt"` in example JSON, matching the code but NOT the official API

**Verdict: CONFIRMED.** This is a real discrepancy. The research file `01-research-claude-code-context.md` is correct (field = `prompt`). The Q&A file's example JSON was wrong. Whether `memory_retrieve.py` itself has a bug or relies on an undocumented compatibility alias is an open question that needs investigation outside this research scope.

**Fix applied:** Changed Q&A example JSON to use `prompt` and added a note about the code discrepancy.

---

#### ISSUE 2: False positive scoring example error -- CONFIRMED

**Evidence (manual trace through `score_entry()`):**

Query: "how to fix the authentication bug in the login page"
Prompt tokens: `{fix, authentication, bug, login, page}`

For "JWT authentication token refresh flow" (claimed tags: auth, jwt):
- Title tokens: `{jwt, authentication, token, refresh, flow}`
- Tags: `{auth, jwt}`
- "authentication" in prompt AND title_tokens -> exact title = +2
- "auth" tag: "authentication".startswith("auth") and len("auth")>=4 -> prefix = +1
- "jwt" tag: "jwt" not in prompt_words, len("jwt")<4 -> no match
- "token" in title: "token" not in prompt_words -> no match
- **Actual score: 3** (not 4 as claimed)

The claimed breakdown "auth=tag+3, token=prefix+1" is doubly wrong:
1. "auth" is NOT an exact tag match with any prompt word (should be prefix +1, not tag +3)
2. "token" does NOT appear in prompt_words (no match at all)

**Gemini independently confirmed:** Verified via Python simulation that the score is 3, not 4.

**Fix applied:** Corrected the score to 3 with accurate breakdown in both `06-analysis-relevance-precision.md` and `06-qa-consolidated-answers.md`.

---

#### ISSUE 3: README missing `02-research-claude-mem-rationale.md` entry -- CONFIRMED

**Evidence:** File exists on disk at `research/retrieval-improvement/02-research-claude-mem-rationale.md`. README file table listed only 5 files, omitting this one.

**Fix applied:** Added the missing entry to the README file table.

---

### From reviewer-critical

#### ISSUE 1: Threshold 6 is mathematically broken -- CONFIRMED

**Evidence (verified against `score_entry()` at `memory_retrieve.py:93-125`):**

Scoring components:
| Match Type | Points |
|-----------|--------|
| Exact title word | +2 per word |
| Exact tag match | +3 per tag |
| Prefix match (4+ chars, bidirectional) | +1 per match |
| Description bonus (capped, only when text_score > 0) | +0 to +2 |
| Recency bonus (deep-check pass) | +0 or +1 |

**Maximum score from a single keyword match (no bonuses):** 5 (title=+2 AND tag=+3, same word in both)
**Maximum score from a single keyword match (all bonuses):** 8 (title+tag=5, description=+2, recency=+1)
**Without bonuses, threshold 6 requires at minimum 2 distinct keyword matches** (e.g., two tags=6, or title+tag+prefix=6)

**Real-world example:** Query "how to deploy the backend", memory "Kubernetes deployment runbook" (tags: kubernetes, deployment, k8s):
- "deploy" -> "deployment" prefix match = +1
- "backend" -> no match = +0
- Total: 1. NOT injected at threshold 6. NOT injected at threshold 4. NOT injected at threshold 2.

This confirms the critical reviewer's finding: threshold 6 would effectively disable auto-retrieval for most single-topic queries.

**Gemini independently confirmed:** "Raising the threshold to 6 guarantees that single-topic queries (the majority of use cases) will trigger zero auto-retrieval results" and recommended threshold 5 or lower.

**Fix applied:** Changed recommended threshold from 6 to 4 across all research files. Added threshold analysis with score math. Threshold 4 eliminates the worst false positives (single prefix match = 1, single title match = 2) while preserving confident matches (title+tag = 5, two title matches = 4).

---

#### ISSUE 2: Precision numbers unmeasured -- CONFIRMED

**Evidence:** The ~40% and ~85%+ precision numbers appear in multiple research files but are derived from a single constructed example (the "fix the authentication bug" query). No evaluation framework exists. No real-world query data was collected. The ~85%+ target was chosen to "sound good" without derivation.

This is the exact error the research itself criticizes (Phase 0: "No measurement = no confidence in any change").

**Fix applied:** Added "estimated, not measured" qualifiers to all precision claims. Changed the comparison table to use directional descriptions ("improved", "lower", "higher") instead of specific percentages for the Hybrid approach. Added caveats noting the numbers are rough estimates requiring Phase 0 validation.

---

#### ISSUE 3: `transcript_path` in retrieval is proposal, not implementation -- CONFIRMED

**Evidence:**
- `grep "transcript_path" memory_retrieve.py` -> **zero matches**
- `grep "transcript_path" memory_triage.py` -> matches at lines 215, 224, 939, 961, 965
- The retrieval hook reads ONLY `user_prompt` (line 218) from hook input

The research files (pre-fix) presented transcript_path as a component of the Tier 1 auto-inject plan, but it has zero implementation in the retrieval code. It is used only in `memory_triage.py` (the Stop hook for memory capture).

**Fix applied:** Clearly separated "implemented" from "proposed" throughout:
- Moved transcript_path from Tier 1 to Tier 3 (Proposed, Not Yet Implemented)
- Added explicit note that retrieval hook currently uses ONLY `user_prompt`
- Updated roadmap to show transcript context as "(future)"
- Added stability caveat about the JSONL format not being a stable API

---

#### ISSUE 4: Skill-based search contradicts claude-mem evolution -- PARTIAL

**Evidence:** `02-research-claude-mem-rationale.md` documents that claude-mem:
- v5.4.0: Migrated TO skill-based search (`claude-mem:search`)
- v6+: Migrated BACK TO simplified MCP tools (4 instead of 9+)

The inferred reason: "Skills add cognitive overhead for the LLM (understanding when to invoke the skill vs. using MCP tools directly)."

This is relevant counter-evidence for the `/memory-search` skill proposal, but the analogy is imperfect:
- claude-mem's skill was for PRIMARY search (replacing MCP tools entirely)
- claude-memory's proposal is for SUPPLEMENTARY search (filling recall gap when auto-inject misses)
- The use cases are different: "always use skill for all search" vs "use skill only when auto-inject returns nothing"

**Verdict: PARTIAL.** The counter-evidence is legitimate and should be mentioned (it now is), but it doesn't fully invalidate the proposal because the use cases differ. The skill's effectiveness remains unvalidated regardless.

**Fix applied:** Added a note about claude-mem's experience when describing the `/memory-search` skill proposal.

---

## Fixes Applied

### Files modified:

1. **`research/retrieval-improvement/README.md`**
   - Added missing `02-research-claude-mem-rationale.md` to file table
   - Changed "~40%" to "estimated ~40%" in key conclusions
   - Added "(rough estimate, not measured)" qualifier
   - Clarified transcript_path status: "confirmed in memory_triage.py; NOT yet used in memory_retrieve.py"
   - Changed threshold from "high threshold" to "threshold 4"
   - Added "(proposed, not yet implemented)" for /memory-search skill
   - Updated roadmap Phase 0.5 description

2. **`research/retrieval-improvement/06-analysis-relevance-precision.md`**
   - Fixed JWT auth scoring example: score 3 (not 4), with correct breakdown
   - Added score breakdown column to false positive table
   - Marked all precision tables as "(rough estimates, not measured)"
   - Added caveat block explaining numbers are unmeasured
   - Changed threshold from 6 to 4 with full threshold analysis
   - Added threshold math showing single-keyword max scores
   - Changed Tier 3 from "Future" to "Proposed, Not Yet Implemented"
   - Added explicit note about transcript_path not being in retrieval code
   - Changed comparison table to use directional descriptions instead of specific %
   - Changed config example min_score from 6 to 4
   - Updated Phase 0.5 recommendation to list transcript_path as future item
   - Added note about claude-mem's skill-based search abandonment

3. **`research/retrieval-improvement/06-qa-consolidated-answers.md`**
   - Fixed example JSON field from "user_prompt" to "prompt"
   - Added note about code vs official API field name discrepancy
   - Fixed JWT auth scoring: 3점 (not 4점) with correct breakdown
   - Changed precision from "~40%" to "~40% (추정, 미측정)"
   - Changed Tier 1 threshold from 6 to 4
   - Moved transcript_path from Tier 1 to future enhancement
   - Changed Tier 1 precision target from "~85%+" to "향상 (구체적 수치는 측정 필요)"
   - Changed Tier 2 recall from "~80%+" to "향상 예상 (검증 필요, 미구현)"
   - Marked /memory-search skill as "미구현/미검증"
   - Reordered Phase 0.5 steps: threshold first, transcript_path last (as future)

4. **`research/retrieval-improvement/00-final-report.md`**
   - Changed Tier 1 threshold from 6 to 4 with math justification
   - Marked Tier 2 skill as "proposed, not yet implemented or validated"
   - Added transcript_path as separate "Future" item
   - Fixed "Key signal" row to note transcript context is proposed

### File NOT modified (no issues found):

5. **`research/retrieval-improvement/01-research-claude-mem-retrieval.md`** -- Accurate as-is
6. **`research/retrieval-improvement/01-research-claude-code-context.md`** -- Accurate as-is (correctly identifies `prompt` field)
7. **`research/retrieval-improvement/02-research-claude-mem-rationale.md`** -- Accurate as-is

---

## Remaining Issues

### Not fixed (out of scope for research file fixes):

1. **`memory_retrieve.py:218` reads `user_prompt` instead of `prompt`** -- This is likely a code bug, not a documentation error. If the official Claude Code hooks API sends `prompt` and the code reads `user_prompt`, the retrieval hook would get an empty string and silently exit. This needs investigation and potentially a code fix, but is outside the scope of research file corrections.

2. **`description_score` not documented in research** -- The research files do not mention the `score_description()` function (up to +2 bonus points from category description matching). This is a gap in the scoring documentation but does not invalidate the conclusions since the threshold analysis accounts for these bonus points.

3. **Recency bonus and priority-based tie-breaking** -- These scoring components are mentioned in the code but not prominently documented in the research. The threshold analysis in the fixes accounts for recency bonus.

4. **Version discrepancy** -- `01-research-claude-mem-retrieval.md` says "v6.5.0" while `02-research-claude-mem-rationale.md` says "v10.3.1". Both may be correct for their respective focus areas but it's confusing. A clarifying note could be added but was not prioritized.

5. **transcript_path stability risk** -- Building retrieval features on an unstable JSONL format is a real risk that the research acknowledges but the Hybrid architecture somewhat ignores. The fixes add more explicit caveats but cannot eliminate the underlying risk.

---

## Cross-Validation Summary

| Claim | reviewer-accuracy | reviewer-critical | v1-functional | Gemini |
|-------|------------------|-------------------|---------------|--------|
| JWT auth score = 4 | WRONG (says score is lower) | -- | WRONG (actual = 3) | CONFIRMED wrong |
| Threshold 6 is viable | -- | BROKEN | BROKEN | BROKEN |
| Precision numbers measured | -- | UNMEASURED | UNMEASURED | -- |
| transcript_path in retrieval | -- | VAPORWARE | NOT IMPLEMENTED | -- |
| `prompt` vs `user_prompt` | INCONSISTENT | -- | `prompt` is correct | -- |
| README missing file | CONFIRMED | -- | CONFIRMED | -- |
| Skill viability | -- | UNVALIDATED | PARTIAL concern | -- |
