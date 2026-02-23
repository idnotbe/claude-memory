# V1 Context-Preservation Review: Guardian Heredoc Fix Prompt

**Reviewer:** v1-context-reviewer
**Date:** 2026-02-22
**Primary file:** `/home/idnotbe/projects/claude-memory/temp/guardian-heredoc-fix-prompt.md`
**Supporting files reviewed:** research report, V2 adversarial review, fix design, action plan

---

## Verdict: PASS WITH NOTES

## Self-Containment Score: 9/10

The guardian prompt is exceptionally well-constructed for a zero-context session. It provides complete, self-contained instructions that require no external file access. A fresh Claude Code session in `/home/idnotbe/projects/claude-code-guardian/` could execute this prompt end-to-end without reading any claude-memory repo files. The deduction of 1 point is for minor gaps documented below.

---

## Critical Context Preservation Checklist

### 1. Problem Statement -- WHY these changes are needed

**Status: EXCELLENT**

The prompt opens with a clear user-pain-point framing: "It has a heredoc blindness bug that causes false `[CONFIRM]` popups when any plugin writes multi-line content (like JSON) via bash heredoc syntax [...] This has caused 7 false positive popups in 20 hours for a sibling plugin (claude-memory) and affects all guardian users who use heredoc syntax." This gives the new session both the specific trigger (popups) and the scope (all guardian users). No external context needed.

### 2. Root Cause Chain

**Status: EXCELLENT**

The three-layer failure chain is explained in full detail under "Root Cause: Three-Layer Failure Chain" with a concrete example command, the exact split output, which regex matches, and why the F1 safety net escalates. The explanation is step-by-step and traces the full code path. A developer unfamiliar with the codebase could follow this without reading any source code first.

### 3. Two Failure Modes

**Status: EXCELLENT**

Both Mode A ("Detected write but could not resolve target paths") and Mode B ("Protected path reference detected: .env") are clearly separated with their own subsections. Mode B explicitly notes that Layer 1 runs BEFORE `split_commands()` in `main()`, making it clear that the heredoc parser fix alone does NOT fix Mode B. This is critical context that prevents the new session from declaring victory after only implementing Fix 1.

### 4. Arithmetic Bypass Risk

**Status: EXCELLENT**

The prompt addresses this at two levels:
- In the Step 3 implementation, the guard condition `(i == 0 or command[i-1] in ' \t\n;|&<>(')` is explained with: "This prevents `x<<2` (arithmetic shift) from being misdetected as a heredoc, because `x` is a word character not in the allowed set."
- In the test suite, `TestArithmeticBypassPrevention` has two explicit tests with failure messages that call out "arithmetic bypass!" if they fail.
- In the Edge Cases Reference table, both `(( x << 2 ))` and `let val<<1` are listed with expected handling.

This is thorough enough that the new session understands the security risk, the mitigation, and how to verify it.

### 5. Layer 1 Gap (scan_protected_paths ordering)

**Status: EXCELLENT**

This is explicitly addressed in multiple places:
- In "Background: How the Guardian Works" (Layer 1 description): "Called in `main()` BEFORE command splitting."
- In Failure Mode B: "Layer 1 runs BEFORE `split_commands()` in `main()`, so fixing the heredoc parser alone does NOT fix this failure mode."
- Step 4 is entirely dedicated to this fix, with before/after code showing the reorder.
- The test `TestScanProtectedPathsHeredocAware` verifies both that `.env` in heredoc body is NOT in sub-commands and that `.env` in actual commands IS still detected.

### 6. V1/V2 Findings Incorporation

**Status: GOOD (minor gaps)**

| Finding | Incorporated? | Notes |
|---------|:---:|-------|
| `<<<` here-string edge case (V1-code) | YES | Test `test_here_string_not_heredoc`, edge case table, code guard `command[i:i+3] != '<<<'` |
| Backtick blindness in `_is_inside_quotes()` (V2-adversarial Challenge 3) | PARTIALLY | Listed in "Out of Scope" as a pre-existing limitation. This is the correct decision (don't fix it), but the prompt could briefly note WHY it's low-impact (backtick substitution is rare in modern bash) to prevent the new session from worrying about it |
| Guard regex bypass gaps for cp/mv/install (V2-adversarial Challenge 4b) | NOT APPLICABLE | This finding was about the memory-side guard hook (C2), not the guardian-side fixes. The guardian prompt correctly focuses only on guardian-side changes |
| Arithmetic `((...))` bypass (V2-adversarial Challenge 2a) | YES | Thoroughly addressed as noted in item 4 above |
| Pre-pass regex alternative (V2-adversarial Challenge 7) | NO | The prompt chose the state-machine approach with the lookbehind guard rather than the regex pre-pass. This is a deliberate design choice, not a gap |

---

## Self-Containment Test

Performing the "fresh session" thought experiment:

| Question | Answer |
|----------|--------|
| Can I understand what to do without reading external files? | **YES.** The prompt is fully self-contained. Every code snippet, test case, and explanation is inline. |
| Do I know which files to modify and where? | **YES.** `hooks/scripts/bash_guardian.py` is explicitly named. The "Key Landmarks" table provides search patterns for every function and code location. |
| Do I understand the test cases well enough to write them? | **YES.** The complete test file is provided as copy-pasteable code with all imports, classes, and test methods. |
| Do I know what "success" looks like? | **YES.** Step 5 defines success: compile check passes, full test suite passes, `test_bypass_v2.py` heredoc test passes, version bump to 1.1.0. |
| Are there references to files I can't access? | **MOSTLY NO.** There is one reference to "test_bypass_v2.py:142-146" which exists in the guardian repo (accessible). The "Out of Scope" section mentions "claude-memory" as context but doesn't require reading any files from it. One minor issue: the test comment `test_heredoc_with_semicolon_in_body` references "the known limitation from test_bypass_v2.py:142-146" -- this is fine since that file is in the guardian repo. |

---

## External Model Comparison

Gemini 3 Pro was asked: "What are the top 5 things a zero-context AI coding session prompt MUST include to fix heredoc parsing bugs in a bash command guardian?"

### Gemini's Top 5 Requirements vs. Prompt Coverage

| # | Gemini Requirement | Present in Prompt? | Quality |
|---|-------------------|:---:|---------|
| 1 | **Explicit "Out of Scope" boundaries** -- prevent rabbit-holing into AST rewrites, external libraries, or tangential fixes | YES | The "Out of Scope" section at the top lists 4 explicit exclusions including backtick blindness, `<<\EOF`, heredoc inside `$()`, and changes to other files. This is well-positioned (before any implementation details) so the new session reads it first. |
| 2 | **Ready-to-run TDD test suite** -- complete copy-pasteable test code with standard cases, edge cases, and security regression tests | YES | 273 lines of complete pytest code provided in Step 1, with instructions to run tests first and verify failures as baseline. Includes both functional tests and security regression tests (arithmetic bypass). |
| 3 | **Precise architectural context (the "layers")** -- explain the pipeline and data flow, especially ordering issues | YES | "Background: How the Guardian Works" provides a 6-layer pipeline description with call ordering. The failure modes explicitly trace through the layers. The reorder fix (Step 4) is motivated by the architectural explanation. |
| 4 | **Exact file paths and semantic landmarks** -- function names, search patterns, section headers | YES | The "Key Landmarks" table at the bottom provides 9 semantic search patterns (e.g., "Search for `def split_commands(command: str)`"). File paths are relative to the guardian repo root. |
| 5 | **Forced sequential execution plan** -- incremental steps with test verification between each | YES | 5 numbered steps, each ending with a specific test command. Step 1 is TDD (create tests, verify failures). Steps 2-4 each target one fix with a test run afterward. Step 5 is final verification. |

**Gemini's assessment:** The prompt "perfectly exemplifies this structure." All 5 critical requirements are present.

---

## Specific Gaps

### Gap 1: No mention of the `<<\EOF` backslash-escaped delimiter edge case handling

**Severity: LOW**

The V2-adversarial review and Gemini both flagged `<<\EOF` (backslash-escaped heredoc delimiter) as an edge case. The prompt lists it in "Out of Scope" ("The `<<\EOF` backslash-escaped delimiter edge case") which is correct -- but the `_parse_heredoc_delimiter` function's bare-word parser will consume `\EOF` as a 4-character delimiter `\EOF`, which means the heredoc body would need to end with a line containing literally `\EOF`. In practice, bash strips the backslash and uses `EOF` as the delimiter. This means backslash-escaped delimiters will produce unterminated heredocs, which fail-closed (body consumed to end of string). Since this is listed as out of scope and fails closed, this is acceptable but could confuse the new session if they encounter it during testing.

**Suggested addition:** Add one line to the Edge Cases Reference table:

```
| `<<\EOF` (backslash-escaped) | Out of scope. Treated as bare word `\EOF` -- body consumed to end of string (fail-closed) |
```

### Gap 2: No explicit statement that the provided implementation code IS the final design

**Severity: LOW**

The prompt provides complete Python code for all three fixes. However, it does not explicitly state whether the new session should implement this code verbatim or treat it as a starting point to iterate on. The TDD structure (tests first, then implementation) implies the session should write code that passes the tests, but the exact code is also provided. A fresh session might wonder: "Am I supposed to paste this code, or write my own version that passes the tests?"

**Suggested addition:** Add one sentence after the "Execution Plan" heading:

```
The implementation code below is the final verified design. Implement it as written; do not redesign the approach.
```

### Gap 3: Backtick blindness out-of-scope could benefit from one-line rationale

**Severity: VERY LOW**

The "Out of Scope" section says: "The `_is_inside_quotes()` backtick blindness (it does not track backtick substitution -- this is a pre-existing limitation, not a regression)". This is sufficient for scope control. However, a fresh session might still worry about whether the Fix 2 `_is_inside_quotes()` usage will cause problems for backtick-containing commands. Adding "practical impact is low because backtick substitution is rare in modern bash" would fully close this concern.

**Suggested addition to the Out of Scope item:**

```
- The `_is_inside_quotes()` backtick blindness (it does not track backtick substitution -- this is a pre-existing limitation, not a regression; practical impact is low because backtick substitution is rare in modern bash)
```

---

## Action Plan Context (Secondary Review)

**File:** `/home/idnotbe/projects/claude-memory/action plans/plan-guardian-conflict-memory-fix.md`

| Check | Status | Notes |
|-------|--------|-------|
| Makes sense standalone? | YES | The plan is entirely within the claude-memory repo. All file paths are relative to this repo. Background section explains the problem without requiring external files. |
| "Before" code snippets accurate? | YES | The SKILL.md "Before" snippet matches what the research report identifies at lines 81-83. The hooks.json structure is provided in full. |
| Language barrier? | MINOR | The plan is written in Korean. The user presumably speaks Korean, so this is not a problem for them. Code snippets and file paths are in English. Test code is in English. A non-Korean-speaking session could still follow the code-heavy sections. |
| Regex improvements from V2? | YES | The staging guard regex includes `cp|mv|install|dd` which addresses V2-adversarial Challenge 4b. This is an improvement over the original fix design which only had `cat|echo|tee|printf`. |
| Test coverage | GOOD | 10 test cases (T1-T10) cover true positives, true negatives, and recovery behavior. Both manual and pytest verification methods provided. |

---

## Summary

The guardian heredoc fix prompt is an exemplary piece of work for cross-session context transfer. It satisfies all 5 critical requirements identified by the external model (scope boundaries, TDD tests, architectural context, file landmarks, sequential execution). The three identified gaps are all low-severity and would be addressed by adding approximately 3-4 sentences total.

The prompt successfully transforms a complex multi-document research investigation (spanning 8 files across 2 repos) into a single self-contained document that a zero-context session can execute mechanically. The "Key Landmarks" table and semantic search instructions are particularly well-designed for a session that needs to navigate an unfamiliar codebase.

| Metric | Rating |
|--------|--------|
| **Overall Verdict** | PASS WITH NOTES |
| **Self-Containment Score** | 9/10 |
| **Problem Statement Clarity** | 10/10 |
| **Root Cause Explanation** | 10/10 |
| **Two Failure Modes** | 10/10 |
| **Arithmetic Bypass Coverage** | 10/10 |
| **Layer 1 Gap Coverage** | 10/10 |
| **V1/V2 Findings Integration** | 8/10 |
| **Execution Plan Quality** | 10/10 |
| **Test Coverage** | 9/10 |
