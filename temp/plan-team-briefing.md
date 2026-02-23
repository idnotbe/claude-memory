# Team Briefing: Plan Creation for Memory Retrieval Improvements

**Date:** 2026-02-22
**Project:** claude-memory plugin
**Repo:** /home/idnotbe/projects/claude-memory

---

## Mission

Create 3 plan files in `/home/idnotbe/projects/claude-memory/plans/`:

1. **plan-retrieval-confidence-and-output.md** -- Actions #1-#4 implementation plan (confidence calibration + tiered output + hints)
2. **plan-search-quality-logging.md** -- Logging infrastructure for search quality measurement
3. **plan-poc-retrieval-experiments.md** -- PoC experiments targeting retrieval quality (depends on logging infra)

Each plan must include: Background, Purpose, Related Info, Progress Checkboxes `[ ]`.

---

## Context Documents (READ THESE)

All analysis from previous session lives in `temp/`:
- `temp/final-recommendation.md` -- **PRIMARY**: Final recommendations with all actions/PoCs
- `temp/v1-practical.md` -- Implementation feasibility, LOC estimates, test impact
- `temp/v1-robustness.md` -- Security/robustness verification
- `temp/v2-fresh.md` -- Independent fresh verification
- `temp/v2-adversarial.md` -- Adversarial review, agent hook discovery
- `temp/agent-hook-verification.md` -- Independent agent hook verification
- `temp/synthesis.md` -- Korean synthesis of all analyst perspectives

---

## Plan #1: Actions #1-#4 (Implementation Plan)

### Action #1: Absolute Floor + Cluster Detection in confidence_label()
- **File:** `hooks/scripts/memory_retrieve.py:161-174`
- **Problem:** Single result always gets confidence="high" (ratio=1.0). Clustered scores all appear "high".
- **Fix:** Add `abs_floor` parameter + cluster detection. Config key: `retrieval.confidence_abs_floor`
- **LOC:** ~20-35 code, ~35-65 with tests
- **Risk:** Low. Default `abs_floor=0.0` preserves current behavior.
- **Test impact:** `test_single_result_always_high` (line 535), `test_all_same_score_all_high` (line 539) may break with nonzero default

### Action #2: Tiered Output in _output_results()
- **File:** `hooks/scripts/memory_retrieve.py:262-301`
- **Problem:** All results injected identically regardless of confidence
- **Fix:** HIGH=full inject, MEDIUM=compact (`<memory-compact>`), LOW=silence
- **Config:** `retrieval.output_mode` = "tiered" (default) / "legacy"
- **LOC:** ~40-60 code, ~80-150 with tests
- **Risk:** Low. "legacy" config restores current behavior.
- **Test impact:** 5-8 tests need updating across test_memory_retrieve.py and test_v2_adversarial_fts5.py
- **MUST:** Preserve XML structure wrapper (V1-robustness security requirement), preserve tags in compact mode (V2-fresh)

### Action #3: Hint Improvement
- **File:** `hooks/scripts/memory_retrieve.py` lines 458, 495, 560 (3 locations!)
- **Problem:** HTML comment hints (`<!-- -->`) likely ignored by Claude. No hint when results exist but all are LOW confidence.
- **Fix:** `<!-- -->` -> `<memory-note>`. Add all-low-confidence hint. Extract to helper function.
- **LOC:** ~6-10
- **Risk:** Very low.

### Action #4: Agent Hook PoC
- **This needs a separate git branch!**
- **What:** Test `type: "agent"` hook on UserPromptSubmit
- **Key questions:** Latency? Can agent hooks inject context? Plugin compatibility?
- **Reference:** `temp/agent-hook-verification.md`
- **Agent hooks return `{ "ok": true/false }`, NOT stdout text. Context injection mechanism unclear.**

### Implementation Order: #1 -> #2 -> #3 (sequential dependency). #4 is independent (separate branch).

### Rollback: 2 config changes (output_mode + abs_floor), NOT 1.

---

## Plan #2: Logging Infrastructure

### Purpose
Create logging infrastructure to measure search quality and enable self-improvement feedback loop.

### Requirements from User
- Log path for ops project: `/home/idnotbe/projects/ops/.claude/memory/` (inside a logs subfolder)
- Config controls: enable/disable logging, log level (debug, info, warning, error)
- Folder structure and file naming designed for easy analysis
- Must support later PoC measurements (precision, nudge compliance, etc.)

### Design Considerations
- Logging should be per-project (each project's .claude/memory/ has its own logs)
- The log path pattern: `<project>/.claude/memory/logs/`
- Need to think about: rotation, format (JSON lines for easy parsing?), naming convention
- Config keys: `logging.enabled`, `logging.level`, `logging.path` (override)
- Scripts that need logging: memory_retrieve.py, memory_search_engine.py, memory_judge.py

### What to Log
- Every retrieval: query keywords, matched results, scores, confidence labels, final injected set
- Judge decisions (if enabled): accepted/rejected entries, reasons
- Timing: search latency, judge latency
- Config state at time of retrieval

---

## Plan #3: PoC Experiments (depends on logging)

### PoC #4: Agent Hook Experiment (SEPARATE BRANCH)
- Build minimal agent hook for UserPromptSubmit
- Measure latency
- Test output mechanism (can it inject context?)
- **Needs logging to record latency measurements**

### PoC #5: BM25 Precision Measurement
- 20-30 manual query labels (relevant/not relevant)
- Calculate precision/recall with current system
- Compare before/after Action #1
- **Needs logging to capture all retrievals for labeling**

### PoC #6: Nudge Compliance Rate
- After Action #2 (tiered output), measure how often Claude follows the "use /memory:search" suggestion
- stderr/log-based measurement
- **Needs logging to track compact injections and subsequent search calls**

### PoC #7: OR-Query Precision
- Measure false positive rate from single-keyword BM25 matches
- "React error handling" -> "error" matches unrelated entries
- **Needs logging to identify single-token matches vs multi-token matches**

---

## Key Code References

| File | Lines | What |
|------|-------|------|
| hooks/scripts/memory_retrieve.py | 161-174 | confidence_label() |
| hooks/scripts/memory_retrieve.py | 262-301 | _output_results() |
| hooks/scripts/memory_retrieve.py | 458, 495, 560 | 0-result hints (3 locations) |
| hooks/scripts/memory_retrieve.py | 353-384 | Config parsing (dict.get() pattern) |
| hooks/scripts/memory_search_engine.py | 283-288 | apply_threshold() noise floor |
| hooks/scripts/memory_judge.py | all | LLM judge implementation |
| assets/memory-config.default.json | all | Default config |
| tests/test_memory_retrieve.py | 493-562, 618, 649, 658 | Affected tests |
| tests/test_v2_adversarial_fts5.py | 1063, 1079 | More affected tests |

---

## Working Conventions

- **Language:** Plans should be written in Korean (user's preference)
- **File links:** Communicate between teammates via file paths, not long messages
- **Vibe check:** Use at critical decision points
- **Pal clink:** Consult Codex 5.3 + Gemini 3 Pro at key points
- **Working memory:** Use temp/ for drafts and notes
- **Plan format:** Each plan needs Background, Purpose, Related Info, Progress Checkboxes `[ ]`
