# Accuracy Review (Phase 1 Outputs)

**Reviewer:** reviewer-accuracy
**Date:** 2026-02-20
**Method:** Line-by-line verification against source code + Gemini cross-validation
**Files reviewed:** 7 research files + 2 process files + 2 source code files + official Anthropic hooks documentation

---

## Summary

The research conclusions are **largely accurate** on the core technical claims. The scoring formulas, architecture descriptions, and claude-mem analysis all check out against source code. However, I found **3 issues** (1 potentially critical, 2 moderate) and **3 minor inaccuracies** in the false positive scoring examples. The ~40% precision estimate is directionally correct but not rigorous. The transcript_path discovery is the most impactful finding and is accurately described.

---

## Verified Claims (correct)

### Scoring System (`memory_retrieve.py`)
- **Title exact match = +2 points**: Confirmed at line 106 (`len(exact_title) * 2`)
- **Tag exact match = +3 points**: Confirmed at line 110 (`len(exact_tags) * 3`)
- **Prefix match (4+ chars) = +1 point**: Confirmed at lines 118-123, bidirectional
- **Score > 0 allows injection**: Confirmed at line 315 (`if text_score > 0:`)
- **No body content searched**: Confirmed -- no grep matches for "body" in retrieve.py
- **~400 LOC**: Confirmed -- 398 lines actual

### Configuration
- **max_inject defaults to 5**: Confirmed at line 247
- **max_inject clamped to [0, 20]**: Confirmed at line 259 (`max(0, min(20, int(raw_inject)))`)
- **Fallback to 5 on parse failure**: Confirmed at line 261
- **_DEEP_CHECK_LIMIT = 20**: Confirmed at line 57

### cwd Usage
- **cwd received but not used for scoring**: Confirmed. Line 219 reads cwd, line 226 uses it only for locating memory root. No scoring use.

### transcript_path Claims
- **memory_triage.py uses transcript_path**: Confirmed at line 939 (`hook_input.get("transcript_path")`) and line 970 (`parse_transcript(resolved, config["max_messages"])`)
- **memory_retrieve.py does NOT use transcript_path**: Confirmed -- zero grep matches for "transcript_path" in the file
- **All hooks receive transcript_path**: Confirmed by official Anthropic docs (common input fields table)

### claude-mem Architecture (01-research-claude-mem-retrieval.md)
- **Dual-path retrieval**: Hook (recency) + MCP (vector) -- described accurately
- **No keyword search in active path**: FTS5 deprecated claim is well-sourced
- **3-layer progressive disclosure**: search -> timeline -> get_observations -- described accurately
- **ChromaDB for vector search**: Accurately described with cosine distance
- **90-day hard recency cutoff**: Correctly identified as filter, not scoring component

### claude-mem Rationale (02-research-claude-mem-rationale.md)
- **Evidence classification [CONFIRMED] vs [INFERRED]**: Appropriate and transparent
- **Architecture evolution timeline**: v1-v5+ evolution is well-sourced with specific PR numbers and dates
- **Token economics as primary driver**: Multiple confirmed sources cited
- **Two MCP transitions**: v5.4.0 skill-based (PR #78) -> v6+ simplified MCP (PR #480) -- accurately described
- **FTS5 status**: Nuanced and honest about uncertainty (exists in schema, not in active search path)

### Precision-First Hybrid Architecture (06-analysis-relevance-precision.md)
- **Hook + Skill hybrid concept**: Technically sound and well-argued
- **Tier design**: Conservative auto-inject (high threshold) + on-demand search (/memory-search) -- coherent architecture
- **Claude as LLM-as-Judge insight**: Valid -- using the existing LLM for relevance judgment without external API

### Q&A Answers (06-qa-consolidated-answers.md)
- **All 7 questions answered**: Confirmed complete
- **cwd explanation (Q1)**: Accurate
- **Document suite issues status (Q2)**: Accurately states "accepted, not resolved"
- **MCP vs Skill comparison (Q3)**: Accurate architecture comparison
- **TF vs TF-IDF explanation (Q7)**: Correct and accessible

### Final Report (00-final-report.md)
- **7 alternatives analysis**: Scoring tables internally consistent
- **BM25 consensus recommendation**: Well-supported across reviewers
- **stdlib-only constraint**: Correctly identified as sacrosanct
- **600-entry scale**: Correctly argues linear scan is adequate
- **Addendum corrections**: Properly annotated as superseding original recommendations

---

## Issues Found

### ISSUE 1 (Potentially Critical): `user_prompt` vs `prompt` Field Name

**Location:** `06-qa-consolidated-answers.md` line 168, cross-referenced with `memory_retrieve.py` line 218 and official Anthropic hooks docs

**Claim in Q&A file (line 168):** Shows example JSON with `"user_prompt": "fix the auth bug"` as the field name for UserPromptSubmit hooks.

**What the code does:** `memory_retrieve.py` line 218: `user_prompt = hook_input.get("user_prompt", "")`

**What official docs say:** The Anthropic hooks reference (https://code.claude.com/docs/en/hooks) shows:
```json
{
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Write a function to calculate the factorial of a number"
}
```

The official field name is `prompt`, not `user_prompt`. If Claude Code sends `prompt` and the code reads `user_prompt`, the retrieval hook would get an empty string and silently exit (line 222: `if len(user_prompt.strip()) < 10: sys.exit(0)`).

**Note:** This may be a pre-existing code issue rather than a research documentation error. The research file `01-research-claude-code-context.md` correctly identifies the field as `prompt` (line 191). However, `06-qa-consolidated-answers.md` incorrectly shows `"user_prompt"` in its example JSON, matching the code rather than the official docs.

**Gemini cross-validation:** Gemini independently flagged this as a "confirmed bug" in memory_retrieve.py.

**Impact on research conclusions:** The core finding that "hooks receive transcript_path" is unaffected. But the example code in Q&A Q4-Q5 uses the wrong field name.

---

### ISSUE 2 (Moderate): False Positive Scoring Example Errors

**Location:** `06-analysis-relevance-precision.md` lines 26-31, repeated in `06-qa-consolidated-answers.md` lines 80-84

**The example table for query "how to fix the authentication bug in the login page":**

| Memory Title | Claimed Score | Claimed Breakdown |
|---|---|---|
| "JWT authentication token refresh flow" | 4 | auth=tag+3, token=prefix+1 |
| "Login page CSS grid layout" | 4 | login=title+2, page=title+2 |
| "Fix database connection pool bug" | 4 | fix=title+2, bug=title+2 |

**Errors found:**

1. **"JWT authentication token refresh flow" scoring is wrong.** The claimed breakdown says "auth=tag+3" but the prompt token is "authentication", not "auth". If the tag is "auth":
   - "authentication" (prompt) vs "auth" (tag): NOT exact match, so no +3
   - Prefix match: "authentication".startswith("auth") and len("auth")>=4 = True, so +1
   - Additionally, "token" appears in the title tokens, but "token" is NOT in the prompt tokens (prompt is: fix, authentication, bug, login, page). So "token=prefix+1" is also wrong.
   - **Actual score would be lower than 4** (likely 1-2 depending on exact tags, not 4)

2. **"Login page CSS grid layout" scoring is correct.** "login" exact title match (+2) + "page" exact title match (+2) = 4. Verified.

3. **"Fix database connection pool bug" scoring is correct.** "fix" exact title match (+2) + "bug" exact title match (+2) = 4. Verified. ("fix" is not a stop word -- confirmed.)

**Impact:** The first example in the false positive demonstration table is materially wrong. The CSS and database examples are correct and still demonstrate the false positive problem effectively. The overall ~40% precision claim is directionally plausible but the supporting example is flawed.

---

### ISSUE 3 (Moderate): README Missing File Entry

**Location:** `research/retrieval-improvement/README.md`

The file `02-research-claude-mem-rationale.md` exists on disk but is NOT listed in the README's file table. The README lists 5 files:
- 00-final-report.md
- 01-research-claude-mem-retrieval.md
- 01-research-claude-code-context.md
- 06-analysis-relevance-precision.md
- 06-qa-consolidated-answers.md

Missing: `02-research-claude-mem-rationale.md` (the claude-mem architecture rationale research).

---

### ISSUE 4 (Minor): Version Number Discrepancy for claude-mem

**Location:** `01-research-claude-mem-retrieval.md` line 4 says "v6.5.0"; `02-research-claude-mem-rationale.md` line 5 says "v10.3.1 as of research date"

These files were likely produced at different times during the research session. The v10.3.1 number is more recent and likely reflects the actual repository state. The v6.5.0 version in the retrieval analysis may refer to the version where the search architecture described was established. This is confusing but not factually wrong -- just needs a clarifying note.

---

### ISSUE 5 (Minor): Inconsistent Stop Hook Field Names

**Location:** `01-research-claude-code-context.md` line 194

The table shows Stop hooks receive `stop_hook_active` and `last_assistant_message`. This is confirmed correct by the official docs. No issue here -- I initially flagged this but verified it.

---

### ISSUE 6 (Minor): description_score Not Mentioned in Research

**Location:** `memory_retrieve.py` lines 128-153, 300-314

The scoring system also includes `score_description()` which adds up to +2 points from category description matching (only when text_score > 0 already). None of the research documents mention this additional scoring component. The description scoring is: exact match = +1 each, prefix match (4+ chars) = +0.5, capped at 2 total.

This means the effective scoring is: title(+2) + tag(+3) + prefix(+1) + **description(+2 max)**. The total theoretical maximum per-entry score is higher than the research documents suggest. This doesn't change the overall conclusion (keyword matching has precision issues) but means the scoring formula described in the research is incomplete.

---

## Missing Information

1. **description_score component**: The research should mention the category description scoring (up to +2 bonus points when a text_score > 0 entry's category description also matches prompt words). See `score_description()` at `memory_retrieve.py:128-153`.

2. **Recency bonus**: The code adds +1 for recent entries (updated within 30 days, checked during deep-check pass). This is mentioned briefly in the codebase description but not in the precision analysis examples.

3. **Priority-based tie-breaking**: Entries are sorted by score descending, then by category priority (DECISION=1 > CONSTRAINT=2 > ... > SESSION_SUMMARY=6). This affects which memories get injected when scores tie.

4. **Index rebuild on demand**: `memory_retrieve.py` lines 231-241 will auto-rebuild the index if it's missing but the memory directory exists. This resilience mechanism is not documented in the research.

5. **Path traversal protection**: The retrieval hook has containment checks (lines 334-336, 354-356) that prevent crafted index entries from reading files outside the memory root. This security feature is mentioned in CLAUDE.md but not in the research documents.

---

## Recommendations

### Must Fix
1. **Fix Q&A example JSON field name**: In `06-qa-consolidated-answers.md` line 168, change `"user_prompt"` to `"prompt"` to match official Claude Code hooks API. Add a note about the discrepancy with the actual code.

2. **Fix false positive example scoring**: In `06-analysis-relevance-precision.md` and `06-qa-consolidated-answers.md`, correct the "JWT authentication token refresh flow" score breakdown. Replace with a valid example that actually scores 4 (e.g., a memory titled "Authentication middleware setup" with tags:auth,middleware -- where "authentication" exact title = +2 and prefix match on "auth" tag = +1, for a total of 3, not 4).

3. **Add `02-research-claude-mem-rationale.md` to README**: Add the missing file entry to the README file table.

### Should Fix
4. **Add description_score to scoring documentation**: The precision analysis should mention that category descriptions can add up to +2 bonus points, making the effective scoring range wider than documented.

5. **Add note about version discrepancy**: In `01-research-claude-mem-retrieval.md`, add a note that v6.5.0 refers to the version at which the described search architecture was established, while the latest version as of research date is v10.3.1.

### Nice to Have
6. **Note the user_prompt vs prompt code discrepancy**: The research should document whether this is actually a bug in `memory_retrieve.py` or if there's a compatibility layer. If it IS a bug, it means retrieval has never worked with the standard Claude Code hook protocol, which would be a significant finding.
