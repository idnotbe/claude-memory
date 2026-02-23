# Plan #2 Fixes -- Team Briefing

**Date:** 2026-02-22
**Objective:** Fix all issues in `action-plans/plan-search-quality-logging.md`

---

## Tasks

### Task 1: Fix Missing Finding #4 Session-ID Solution
**File:** `action-plans/plan-search-quality-logging.md` line 141
**Problem:** Line 141 documents the session_id CLI limitation but does NOT reflect the concrete solution already designed in Deep Analysis: `--session-id` CLI parameter + `CLAUDE_SESSION_ID` env var fallback.
**Source:** `temp/41-finding4-5-integration.md` sections 2.2-2.6 (the detailed design)
**Required change:** Update line 141 area to document the designed solution (--session-id CLI param, precedence: CLI arg > env var > empty string, ~12 LOC in memory_search_engine.py). Keep the existing limitation note but add that a concrete fix was designed.

### Task 2: Add Explicit "구현 순서" Section
**File:** `action-plans/plan-search-quality-logging.md`
**Problem:** Plan #2 only has implicit ordering via Phase 1-6. Plans #1 and #3 both have explicit "구현 순서" / "실행 순서 및 근거" sections.
**Reference for style:**
- Plan #1: `action-plans/plan-retrieval-confidence-and-output.md` lines 398-409 ("구현 순서" with dependency diagram)
- Plan #3: `action-plans/plan-poc-retrieval-experiments.md` lines 50-62 ("실행 순서 및 근거" with model consensus table)
**Required:** Add a "구현 순서 (Implementation Order)" section with:
1. Phase dependency diagram (Phase 1→2→3→4→5→6, noting Phase 4 can partially overlap Phase 3)
2. Cross-plan dependencies (Plan #1 Actions are independent; Plan #3 PoCs depend on this plan)
3. Brief rationale for the ordering

### Task 3: Add "롤백 전략" Section (Structural Consistency)
**File:** `action-plans/plan-search-quality-logging.md`
**Problem:** Plan #1 has a "롤백 전략" section. Plan #2 mentions rollback inline (logging.enabled=false disables everything) but lacks a dedicated section.
**Reference:** Plan #1 `action-plans/plan-retrieval-confidence-and-output.md` lines 411-425
**Required:** Add a brief "롤백 전략 (Rollback Strategy)" section documenting:
- `logging.enabled: false` disables all logging (zero file I/O)
- Removing `memory_logger.py` triggers fail-open noop fallback (no crash)
- Dual-write migration period allows reverting to old stderr logging

---

## File References
- **Target file:** `action-plans/plan-search-quality-logging.md`
- **Finding #4 design:** `temp/41-finding4-5-integration.md` (sections 2.2-2.6)
- **Final report:** `temp/41-final-report.md`
- **Plan #1 (structure reference):** `action-plans/plan-retrieval-confidence-and-output.md`
- **Plan #3 (structure reference):** `action-plans/plan-poc-retrieval-experiments.md`
- **README (format rules):** `action-plans/README.md`
- **Previous analysis:** `temp/analysis-plan2-structure-audit.md`
