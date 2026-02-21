# Phase 3c: On-Demand Search Judge -- Work Summary

**Date:** 2026-02-22
**Agent:** search-judge-impl
**Task:** Update `/memory:search` SKILL.md with Task subagent judge (lenient mode)
**Status:** COMPLETE

---

## Changes Made

**File:** `skills/memory-search/SKILL.md`

Added new section "## Judge Filtering (Optional)" (lines 105-176) between "Parsing Results" and "Presenting Results". The existing structure and content were preserved -- only the new section was inserted.

### Section Structure

1. **When to Apply** -- Conditions: 2+ results AND `retrieval.judge.enabled` is true in config. Notes that on-demand judge does NOT need `ANTHROPIC_API_KEY` (uses Task subagent, not direct API call).

2. **How to Run the Judge** -- Task subagent with `subagent_type=Explore` and `model=haiku`. Includes full prompt template with:
   - Lenient criteria: "RELATED to the user's query? Be inclusive"
   - Anti-injection: `<search_results>` data tags with explicit instruction to treat as data
   - JSON output format: `{"keep": [0, 2, 5]}`

3. **Processing Judge Output** -- Parse JSON, filter by `keep` indices, present filtered results.

4. **Graceful Degradation** -- On any failure: show all unfiltered BM25 results. Optional user note about skipped filtering.

5. **Lenient vs Strict Mode** -- Comparison table showing differences from auto-inject hook judge.

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Task subagent (not API call) | Runs within agent context, no API key needed, has full conversation context |
| Haiku model | Cost-efficient for classification task |
| Lenient mode | User explicitly searched -- broader recall is better than strict precision |
| 2+ results threshold | No point filtering 0-1 results |
| Config-gated only (no API key check) | Task subagent uses Claude's own context, not external API |
| Graceful degradation to unfiltered | Never discard user's search results on failure |

### Differences from Auto-Inject Judge (memory_judge.py)

| Aspect | Auto-inject (Hook) | On-demand (This change) |
|--------|-------------------|-------------------------|
| Execution | Python subprocess, `urllib.request` to Anthropic API | Task subagent within agent conversation |
| API key | Required (`ANTHROPIC_API_KEY`) | Not required |
| Context | Limited (last N transcript turns) | Full conversation context |
| Strictness | Strict: "DIRECTLY RELEVANT and would ACTIVELY HELP" | Lenient: "RELATED to the query? Be inclusive" |
| Anti-position-bias | sha256-seeded shuffle | Not needed (subagent sees formatted list, not making API call) |
| Failure mode | Falls back to conservative top-K | Shows all unfiltered results |

---

## Files Touched

- `skills/memory-search/SKILL.md` -- Added 73 lines (Judge Filtering section)

## Verification Checklist

- [x] New section inserted between Parsing Results and Presenting Results
- [x] Existing content unchanged
- [x] Lenient mode prompt matches spec ("RELATED", "Be inclusive")
- [x] Graceful degradation on failure
- [x] Conditional on `judge.enabled` config
- [x] Does NOT require `ANTHROPIC_API_KEY`
- [x] Anti-injection guidance in subagent prompt
- [x] Comparison table for lenient vs strict
- [x] Model specified as haiku
