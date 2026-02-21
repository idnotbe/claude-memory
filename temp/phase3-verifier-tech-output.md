# Phase 3: Technical Accuracy Verification Report (Round 1)

**Verifier:** verifier-1-tech
**Date:** 2026-02-20
**Report Verified:** phase2-synthesis-output.md
**Approach:** Adversarial -- actively sought errors, exaggerations, and unsupported claims

---

## Verification Checklist Results

### A. Code-Level Verification

#### 1. "max_inject clamped to [0, 20]" -- PASS
**File:** `hooks/scripts/memory_retrieve.py`, lines 257-261
```python
raw_inject = retrieval.get("max_inject", 5)
try:
    max_inject = max(0, min(20, int(raw_inject)))
except (ValueError, TypeError, OverflowError):
    max_inject = 5
```
Confirmed: Clamping logic exists exactly as described. Handles negative, very large, non-integer values with fallback to default 5. The `OverflowError` catch is a nice touch for edge cases like `float('inf')`.

#### 2. "changes[] capped at 50" -- PASS
**File:** `hooks/scripts/memory_write.py`, line 77
```python
CHANGES_CAP = 50
```
FIFO overflow enforced in multiple locations:
- `do_update()` line 782-783: `if len(existing_changes) > CHANGES_CAP: existing_changes = existing_changes[-CHANGES_CAP:]`
- `do_retire()` line 928-929: same pattern
- `do_archive()` line 1002-1003: same pattern
- `do_unarchive()` line 1068-1069: same pattern
- `do_restore()` line 1142-1143: same pattern

Confirmed: FIFO overflow at 50 is enforced across all 5 mutation actions (update, retire, archive, unarchive, restore). `do_create()` does NOT enforce it because new memories start with no changes array. This is correct behavior.

#### 3. "draft files include PID" -- PASS (in SKILL.md instructions, NOT in Python code)
**File:** `skills/memory-management/SKILL.md`, line 99
```
For CREATE or UPDATE: Write complete memory JSON to `.claude/memory/.staging/draft-<category>-<pid>.json`.
```
The PID-in-filename pattern is a SKILL.md instruction to the LLM agent, not enforced by Python code. The Python scripts (`memory_triage.py`, `memory_write.py`) do not generate draft filenames with PIDs -- the subagent does, following SKILL.md instructions. The report's claim about PID-suffixed draft files accumulating is accurate in practice because subagents follow this naming convention.

#### 4. "max_memories_per_category is advisory only" -- PASS
**File:** `hooks/scripts/memory_write.py`
Searched for `max_memories_per_category` -- **zero results**. The `do_create()` function (lines 615-711) performs: input reading, auto-fix, validation, path traversal check, id matching, anti-resurrection check, atomic write, and index update. There is NO check for category file count limits anywhere in the function or anywhere else in memory_write.py.

Confirmed: `max_memories_per_category` is purely agent-interpreted (appears in config and README) with zero script enforcement.

#### 5. "triage score log is append-only" -- PASS
**File:** `hooks/scripts/memory_triage.py`, lines 1000-1001
```python
fd = os.open(
    log_path,
    os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
    0o600,
)
```
Confirmed: Uses `O_APPEND` flag. No rotation, truncation, or size-limiting logic exists anywhere in the codebase for this log file. The report's claim that it "never rotates" is accurate.

#### 6. "session rolling window max_retained=5" -- PASS (agent-enforced, not script-enforced)
**File:** `skills/memory-management/SKILL.md`, lines 203-218
The rolling window is documented as SKILL.md orchestration logic, not Python script logic. It instructs the LLM agent to:
1. Count active sessions in `sessions/` folder
2. Compare against `max_retained` (default 5)
3. Retire oldest via `memory_write.py --action retire`

**File:** `assets/memory-config.default.json`, line 10: `"max_retained": 5`

Confirmed: max_retained=5 is the default. Enforcement is via SKILL.md instructions (agent-interpreted), not via Python script. Report 2 (arch-analyst) says "script-enforced via SKILL.md" which is slightly misleading -- it's LLM-enforced via SKILL.md instructions, not script-enforced. The synthesis report's section 3.2 table says "Requires manual `--gc` invocation" for retired memory accumulation, which is correct -- even after rolling window retires old sessions, they remain on disk until GC.

#### 7. "no auto-GC" -- PASS
Searched `hooks/scripts/` for `auto.*gc`, `automatic.*garbage`, `auto.*clean` -- **zero results**. The only GC mechanism is `memory_index.py --gc` which must be invoked manually. No hook triggers automatic garbage collection.

Confirmed: No automatic garbage collection exists in any hook script.

### B. Claim Verification

#### 8. "Retrieval precision ~40% current" -- PARTIAL (correctly cited but poorly contextualized)
**File:** `research/retrieval-improvement/06-analysis-relevance-precision.md`, lines 77-82

The research file contains the precision table:
| Scenario | Current (est.) | BM25 (est.) | Vector/LLM (est.) |
|---|---|---|---|
| General query ("auth bug") | ~40% | ~60% | ~80-85% |
| Specific query ("pydantic v2 migration") | ~70% | ~85% | ~90% |
| Ambiguous query ("fix the bug") | ~20% | ~30% | ~50% |

The synthesis report (Section 4.3) correctly cites the ~40% figure but attributes it only to "general queries." The research document **prominently warns** (line 75): "All precision numbers in this table are directional rough estimates based on constructed examples, NOT measured values from real usage data."

The synthesis report does acknowledge this in Section 8.1 ("All precision/recall numbers are estimates") but the body text presents the ~40% figure as if it were a measurement, not an estimate. The ambiguous-query row (~20%) is omitted, which cherry-picks the more favorable data.

**Verdict:** Numbers are accurately sourced but their uncertainty is underrepresented in the body text.

#### 9. "7+ distinct memory leak issues in claude-mem" -- PASS
The leak researcher report (Phase 1) documents exactly 8 distinct issues: #499, #572, #737, #789, #1145, #1168, #1178, #1185. Each issue is documented with symptoms, root cause, and fix status. "7+" is accurate (actually 8).

#### 10. "Issue #1185 still OPEN" -- PASS
**Verified via GitHub API:** `gh api repos/thedotmack/claude-mem/issues/1185`
- State: **open**
- Title: "chroma-mcp CPU/memory leak in v10.3.1"
- Last updated: 2026-02-19T21:33:11Z

Confirmed: Issue #1185 is open as of verification time (Feb 20, 2026).

### C. Cross-Model Verification

#### 11. Cross-model assessment (Claude via pal clink, Gemini quota exhausted)

Gemini 3 Pro was unavailable (quota exhausted -- same issue the synthesis report noted). Used Claude Sonnet 4.6 via pal clink instead.

**Key findings from cross-model review:**

| Claim | External Verdict |
|---|---|
| 60-70% keyword ceiling vs 80-85% semantic | **Misleading framing** -- the 60-70% figure is the BM25 ceiling, not the keyword baseline. The report merges distinct figures into a composite that misrepresents both systems. |
| Zero process leak risk | **Overstated** -- "zero" is indefensible as an absolute claim. `memory_retrieve.py` uses `subprocess.run()` for index rebuilds. |
| BM25 ~40% -> ~60% improvement | **Directionally defensible** but confidence is overstated given that source labels numbers as unverified estimates. |
| Exact matching sometimes better for coding terminology | **Valid** -- well-supported by IR literature and consistent with the research data. |

**My verification of the cross-model subprocess claim:**
The external reviewer flagged `subprocess.run()` in `memory_retrieve.py` (line 236) as a potential orphan-process risk on timeout. However, I verified Python's `subprocess.run` source code -- it explicitly calls `process.kill()` in the `TimeoutExpired` handler before re-raising. The `except subprocess.TimeoutExpired: pass` in memory_retrieve.py catches the re-raised exception AFTER the child has been killed. **No orphan risk from this code path.** The external review's specific claim about orphan processes here is technically incorrect.

However, the broader point stands: the architecture is NOT "zero subprocess spawning" as claimed. `memory_retrieve.py` does spawn a subprocess for index rebuilds. The "zero process leak risk" claim should be qualified to "near-zero" or "dramatically lower than daemon architectures."

### D. Vibe Check

No vibe-check skill found (confirmed by checking available skills). Using independent judgment instead.

**Overall vibe assessment:** The synthesis report is well-structured, methodologically sound, and honest about its limitations (Section 8 is commendably thorough). The Korean/English bilingual executive summary is a nice touch. The cross-reference matrix (Section 7) adds genuine value. However, the report has a subtle self-serving tendency that manifests in specific ways documented below.

---

## Errors Found

### Error 1: "Zero process leak risk" is factually incorrect (MEDIUM severity)
- **Claim (Section 3.1):** "All three reports agree unanimously: claude-memory has zero process leak risk... No subprocess spawning."
- **Reality:** `memory_retrieve.py` line 236 uses `subprocess.run()` to invoke `memory_index.py --rebuild`. This IS subprocess spawning. The subprocess is properly managed (killed on timeout, synchronous), but the absolute "zero" and "no subprocess spawning" claims are factually wrong.
- **Correction:** Change to "near-zero process leak risk" and note the subprocess.run usage as a controlled exception.

### Error 2: Precision ceiling attribution error (LOW severity)
- **Claim (Section 4.3):** "The fundamental quality ceiling for stdlib-only retrieval is ~60-70% precision."
- **Reality:** The source document (`06-analysis-relevance-precision.md`) attributes ~60-70% to BM25 specifically (lines 77-82), not to keyword matching generally. The current system is estimated at ~40% for general queries and ~70% for specific queries. The "~60-70% ceiling" is a composite that doesn't precisely match any single row in the source table.
- **Impact:** Low -- the directional conclusion (keyword < semantic) is still correct, but the specific number is a misleading composite.

---

## Exaggerations Found

### Exaggeration 1: "15+ dimensions" where claude-memory wins (LOW severity)
- **Claim (Section 1, English Summary):** "claude-memory wins 15+ dimensions"
- **Reality:** Report 3's comparison table (Section 3) lists 17 dimensions where claude-memory wins, 3 where claude-mem wins, and 3 ties. However, some of these "dimensions" are artificially granular (e.g., "Git Friendliness" and "Per-Project Isolation" could be considered aspects of the same architectural advantage). The "15+" count is defensible if you accept the table's granularity but could be considered inflated.
- **Impact:** Low -- this is more a framing choice than a factual error.

### Exaggeration 2: "~30 min fix" estimates (LOW severity)
- **Claim (Section 3.2 table):** Staging cleanup estimated at "~30 min," enforce category cap at "~30 min"
- **Reality:** The implementation effort estimates are plausible for the code changes themselves but don't account for testing, edge cases, or documentation updates. More realistic estimates would be 1-2 hours each.
- **Impact:** Low -- these are rough estimates presented as rough estimates.

---

## Unsupported Claims

### Unsupported 1: "Test suite (6,200+ LOC)" discrepancy
- **Claim (Section 4.1):** "Test suite (6,200+ LOC)"
- **Verification:** CLAUDE.md says "2,169 LOC across 6 test files" while Report 3 says "6,218 LOC across 10 test files." The synthesis report uses Report 3's higher number without noting the discrepancy.
- **Impact:** Medium -- one number or the other is wrong, or they're counting differently (one might include conftest.py, blank lines, or additional test files created between measurements). The synthesis should acknowledge the discrepancy or verify.

### Unsupported 2: Gemini quote attribution
- **Claim (Section 2.1):** Gemini 2.5 Pro independently named this the "Local Distributed System Fallacy."
- **Verification:** This comes from Report 1, which states Gemini was consulted via pal chat. The quote is attributed to Gemini but I cannot independently verify this specific phrasing was used by Gemini vs. being paraphrased by the leak researcher. Report 1 does present it as a Gemini coinage.
- **Impact:** Low -- the concept is accurate regardless of attribution.

---

## Cross-Model Feedback Summary

Claude Sonnet 4.6 (via pal clink) identified four key issues:

1. **Precision numbers are misattributed** -- The synthesis report presents BM25's ceiling as if it were the general keyword system ceiling. The numbers exist in the source but are reassembled in a misleading way.

2. **"Zero" is an indefensible absolute** -- Verified against code: `memory_retrieve.py` does use `subprocess.run()`. The "zero process leak risk" claim is factually wrong, though the risk is indeed dramatically lower than claude-mem's architecture.

3. **BM25 improvement estimate is directionally sound** -- The ~40% to ~60% improvement on general queries is consistent with IR literature, but the source explicitly labels these as unverified estimates. The report should carry this caveat more prominently.

4. **Domain-specific keyword matching advantage is valid** -- The argument that coding terminology is precise enough for keyword matching to be competitive with semantic search on specific queries is well-supported.

---

## Overall Technical Accuracy Score: 7/10

**Rationale:**
- Core architectural claims (no daemons, lifecycle management, keyword matching) are verified correct
- Process leak comparison between the two projects is directionally accurate
- Issue citations and GitHub data are verified correct
- Retrieval precision numbers are accurately sourced but misleadingly composed
- "Zero process leak risk" is factually incorrect (subprocess.run exists)
- Test LOC numbers are inconsistent between sources
- The report's own caveats (Section 8) are commendably honest and partially compensate for body-text overstatements

---

## Recommendations for Report Corrections

1. **HIGH:** Change "zero process leak risk" to "near-zero process leak risk" in Sections 1 and 3.1. Add footnote about `subprocess.run` usage in `memory_retrieve.py` being a controlled exception (synchronous, killed on timeout, only triggered when index.md is missing).

2. **HIGH:** Add the research file's caveat disclaimer more prominently in Section 4.3 when presenting precision numbers. Consider adding a parenthetical "(estimated, not measured)" after each precision figure.

3. **MEDIUM:** Clarify that the "~60-70% ceiling" in Section 4.3 applies to BM25-enhanced keyword retrieval specifically, not to the current system (which is ~40% for general queries). The current system's ceiling and BM25's ceiling are distinct numbers that shouldn't be merged.

4. **MEDIUM:** Reconcile the test LOC discrepancy (2,169 LOC in CLAUDE.md vs. 6,200+ in the report). Verify the correct number and use it consistently.

5. **LOW:** Change "No subprocess spawning" in Section 3.1 to "No long-lived subprocesses" or "No daemon spawning." The current text is factually incorrect.

6. **LOW:** Consider including the ambiguous-query precision row (~20% current, ~30% BM25, ~50% vector) in Section 4.3's precision table. Omitting it cherry-picks the more favorable data.
