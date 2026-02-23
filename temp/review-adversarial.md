# Adversarial Review (Round 2): Draft Plans #1, #2, #3

**Reviewer:** reviewer-adv (Adversarial Perspective, Round 2)
**Date:** 2026-02-22
**External Validation:** Codex 5.3 (codereviewer), Gemini 3 Pro (codereviewer), Vibe-check
**Scope:** All 3 draft plans reviewed against actual source code
**Previous round:** `temp/review-adversarial.md` (superseded by this file)

---

## Methodology

1. Read all 3 draft plans and context documents
2. Read and verified claims against actual source code:
   - `hooks/scripts/memory_retrieve.py` (577 lines)
   - `hooks/scripts/memory_search_engine.py` (499 lines)
   - `hooks/hooks.json` (57 lines)
   - `assets/memory-config.default.json` (93 lines)
   - `hooks/scripts/memory_triage.py` (triage-scores.log pattern, lines 994-1005)
3. Cross-referenced with `temp/v2-adversarial.md` and `temp/agent-hook-verification.md`
4. Obtained adversarial opinions from Codex 5.3 and Gemini 3 Pro via pal clink
5. Ran vibe-check for metacognitive calibration

---

## Executive Summary

The plans are structurally coherent and demonstrate thorough analysis. However, they contain **3 HIGH-severity concerns, 4 MEDIUM-severity concerns, and 3 LOW-severity issues**. The highest-impact findings are privacy/data safety issues in the logging infrastructure and a cross-plan schema gap that blocks PoC #7.

**Key theme:** The plans are strongest on retrieval logic correctness and weakest on data safety, privacy, and rollback coverage in the logging infrastructure.

---

## Plan #1: Actions #1-#4

### FINDING 1: BM25 Absolute Floor Is Corpus-Dependent

**Severity: HIGH**

**What the plan claims:** Add `confidence_abs_floor` config key (default `0.0`). Recommended starting value: 1.0-2.0 (Plan #1, lines 62-63).

**What's actually true:** BM25 scores from SQLite FTS5 are unnormalized and corpus-dependent. They vary with:
- Number of documents in the index (corpus size)
- Average document length
- Query token count
- Column weights

A score of `-0.8` might be a perfect match in a 5-entry index but meaningless in a 500-entry index. The plan's "recommended 1.0-2.0" has no empirical basis and could cause silent over-filtering or under-filtering depending on the user's index size.

**Mitigating factor:** Default `0.0` disables the floor entirely. This is safe.

**Codex assessment:** "Fixed abs_floor is brittle across query length/corpus drift and may over-demote."

**Gemini assessment (CRITICAL):** "BM25 scores are unbounded and highly corpus-dependent. An absolute floor will cause catastrophic failures as the user's index grows."

**Recommended fix:**
- Remove the "recommended starting value 1.0-2.0" guidance -- it's misleading without data
- Explicitly state that abs_floor must remain at `0.0` until Plan #2 logging + Plan #3 PoC #5 provide empirical calibration data
- Consider documenting future work: percentile-based approach (e.g., "below 25th percentile of observed scores") instead of absolute values

---

### FINDING 2: Cluster Detection Has No Config Toggle and No Safe Rollback

**Severity: HIGH**

**What the plan claims:** Cluster detection is "always-on (no config toggle). Reason: this is a bug fix, not a user preference" (Plan #1, line 66). Rollback requires code revert (lines 106, 385).

**What's actually true:** Calling this a "bug fix" is misleading framing. With `max_inject=3` (the default per `assets/memory-config.default.json:51`), it is common and legitimate for all 3 returned results to have ratio > 0.90. Verified from code at `memory_retrieve.py:169-170`:

```python
ratio = abs(score) / abs(best_score)
if ratio >= 0.75:
    return "high"
```

Legitimate scenario: Query "OAuth configuration" returns 3 memories about OAuth setup, OAuth token refresh, and OAuth scopes. All three are genuinely relevant with similar BM25 scores. Cluster detection would demote all 3 from HIGH to MEDIUM. In tiered mode, this reduces information density for genuinely relevant results.

**The rollback gap is the core issue:** Unlike `abs_floor` (set to 0.0) and `output_mode` (set to "legacy"), cluster detection has NO config-based rollback. The plan's own rollback table (line 385) says "code revert required."

**Codex assessment (MEDIUM):** "Always-on cluster demotion with no kill switch is over-confident pre-data."

**Gemini assessment (CRITICAL):** "Deploying always-on cluster detection without a config toggle or fallback means any algorithmic hallucination will permanently pollute Claude's context window."

**The plan itself notes the disagreement (line 68):** "Codex recommends always-on, Gemini recommends `retrieval.cluster_cap_enabled` toggle."

**Recommended fix:** Add `retrieval.cluster_cap_enabled` config key (default `true` to preserve bug-fix intent, but with config-based rollback). Cost: ~3 LOC in code + 1 line in config. This brings rollback consistency: all 3 Actions have config-based rollback paths.

---

### FINDING 3: `<memory-compact>` Is Semantically Misleading, Not Actually Compact

**Severity: LOW**

**What the plan claims:** Tiered output creates information hierarchy with "compact" format for MEDIUM results (Plan #1, Action #2, lines 126-178).

**Verified against source code.** Current output at `memory_retrieve.py:300`:
```
<result category="DECISION" confidence="high">JWT Auth -> .claude/memory/decisions/jwt.json #tags:auth,jwt</result>
```

Proposed compact format:
```
<memory-compact category="DECISION" confidence="medium">JWT Auth -> .claude/memory/decisions/jwt.json #tags:auth,jwt</memory-compact>
```

The content is identical -- only the tag name changes. The plan honestly acknowledges this (line 150: "existing format is already relatively compact"). The real value is:
1. LOW results are silenced (actual token savings)
2. Tag name difference signals lower confidence to Claude
3. `<memory-note>` nudge for search

**Recommended fix:** No code change needed, but consider renaming to `<memory-suggestion>` to better convey semantic purpose (signal, not compression).

---

### FINDING 4: Agent Hook PoC Questions Are Partially Pre-Answered

**Severity: LOW**

**What the plan claims:** "Key questions" include "Can agent hooks inject context?" (Plan #1, Action #4, lines 336-338).

**What's already established:** `temp/agent-hook-verification.md` already conclusively answers this: agent hooks return `{ "ok": true/false }` and CANNOT inject arbitrary context text (lines 11-15, 27-29).

**Recommended fix:** Reframe PoC questions. Question 2 is answered. Focus on: (a) actual p50/p95 latency measurement, (b) whether `ok: false` + `reason` provides useful gate-keeping, and (c) hybrid command+agent chain feasibility.

---

### FINDING 5: Line Number References Are Accurate (Positive)

**Severity: N/A (Positive)**

Verified all code references against source:
- `confidence_label()` at `memory_retrieve.py:161-174` -- CORRECT
- `_output_results()` at `memory_retrieve.py:262-301` -- CORRECT
- Hint at line 458 -- CORRECT (`<!-- No matching memories found...`)
- Hint at line 495 -- CORRECT (identical text)
- Hint at line 560 -- CORRECT (identical text)
- `apply_threshold()` at `memory_search_engine.py:283-288` -- CORRECT
- `build_fts_query()` OR join at `memory_search_engine.py:226` -- CORRECT
- `hooks.json` UserPromptSubmit at line 43-55 -- CORRECT (type: "command", timeout: 15)

This is a positive signal of plan quality.

---

## Plan #2: Logging Infrastructure

### FINDING 6: Privacy Risk -- Logging query_tokens From User Prompts

**Severity: HIGH**

**What the plan claims:** "Privacy: raw prompt is not logged by default -- only at level debug" (Plan #2, line 115). Query tokens are logged at info level (schema example lines 97-98).

**What's actually true:** `query_tokens` are derived directly from user prompts. Verified at `memory_retrieve.py:411`:
```python
prompt_tokens = list(tokenize(user_prompt))
```
And `memory_search_engine.py:96-100`:
```python
def tokenize(text: str, legacy: bool = False) -> set[str]:
    regex = _LEGACY_TOKEN_RE if legacy else _COMPOUND_TOKEN_RE
    words = regex.findall(text.lower())
    return {w for w in words if len(w) > 1 and w not in STOP_WORDS}
```

Tokenization removes stop-words and lowercases, but remaining tokens ARE user prompt content. A prompt "How do I fix the authentication bug in customer_payment_service?" logs `["authentication", "bug", "customer_payment_service", "fix"]`. These reveal:
- User intent
- Internal service names / identifiers
- Project-specific terminology
- Potentially sensitive information (API names, security topics)

**The distinction between "raw prompt" and "query_tokens" is privacy theater.** Query tokens are a lightly-processed version of the same data.

Additionally:
1. **Secret residue risk:** If a memory title contains sensitive data (e.g., API key) and is later retired, the title persists in log files for up to 14 days.
2. **No .gitignore guidance:** `.claude/memory/logs/` is not mentioned in .gitignore. Logs could be accidentally committed to shared repos.

**Codex assessment (HIGH):** "Prompt-derived identifiers/secrets can be persisted without explicit consent; this is a serious privacy/compliance and trust issue for an installable plugin."

**Gemini assessment (HIGH):** "`query_tokens` are derived directly from user prompts, which often contain highly sensitive data."

**Recommended fixes (prioritized):**
1. Add `.claude/memory/logs/` to `.gitignore` guidance -- ESSENTIAL
2. Log only `matched_tokens` (intersection of query tokens and index tokens) instead of raw `query_tokens` at info level. This preserves diagnostic value while only logging tokens that already exist in user-created memory entries.
3. Log full `query_tokens` only at debug level
4. Document the data residue risk so users make informed opt-in decisions

---

### FINDING 7: logging.enabled Defaults to true -- Inappropriate for Plugin

**Severity: HIGH (combined with Finding 6)**

**What the plan claims:** `logging.enabled` defaults to `true` because "the core purpose of the feedback loop is data collection, so disabling by default makes it meaningless" (Plan #2, line 151).

**What's actually true:** This is a user-installed plugin. Silently writing files to the user's project directory without explicit consent is a trust violation. The rationale conflates the developer's goals with the user's expectations.

**Codex and Gemini both recommend changing this to `false`.**

**However -- counter-argument from vibe-check:** If logging defaults to `false`, almost no one will enable it, and the entire logging infrastructure + PoC plan becomes moot. The feedback loop that justifies Plan #2 and #3 never produces data.

**Recommended fix (compromise):** If Finding 6's recommendation is implemented (log only `matched_tokens`, not `query_tokens`), then `logging.enabled: true` becomes more defensible because the logged data is already public within the memory index. If Finding 6 is NOT implemented, then `logging.enabled` MUST default to `false`.

---

### FINDING 8: Log Path Security -- O_NOFOLLOW Is Insufficient

**Severity: MEDIUM**

**What the plan claims:** Uses `os.open(O_APPEND|O_CREAT|O_WRONLY|O_NOFOLLOW)` pattern (Plan #2, lines 74, 304).

**What's actually true:** `O_NOFOLLOW` prevents following symlinks on the *final* path component only. The plan's path construction (line 267):
```python
event_category = event_type.split('.')[0]
# path: {memory_root}/logs/{event_category}/{YYYY-MM-DD}.jsonl
```

If `event_type` ever contains path separators or `..` characters, log files could be written outside the intended directory. Currently event types are hardcoded strings (`"retrieval.search"`), which is safe. But no validation exists.

**Codex assessment (MEDIUM):** "O_NOFOLLOW protects only the final file; traversal/symlink-dir issues remain."

**Recommended fix:** Add a strict allowlist for `event_category`: `{"retrieval", "judge", "search", "triage"}`. Validate event_type matches `^[a-z_]+\.[a-z_]+$`. Resolve log directory and verify containment within `memory_root`.

---

### FINDING 9: Atomic Append Guarantee Is Overstated

**Severity: MEDIUM**

**What the plan claims:** "Atomic append (single write syscall for entire JSONL line)" (Plan #2, line 78).

**What's actually true:** The reference pattern from `memory_triage.py:1000-1005`:
```python
fd = os.open(log_path, os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, 0o600)
```
Uses `os.fdopen(fd, "a")` followed by `f.write()`. Python's `file.write()` through `fdopen()` uses C stdio buffering, NOT direct `os.write()`. This means:
1. Writes may be split across multiple kernel syscalls if buffer boundary is crossed
2. On POSIX, `O_APPEND` guarantees atomic positioning but NOT atomic data writes exceeding `PIPE_BUF` (4096 bytes on Linux)

With full candidate lists (8+ candidates with paths, scores, tokens), entries could approach 4KB.

**Practical risk:** Claude Code typically doesn't execute the same hook concurrently. So corruption is unlikely. But the plan claims atomicity as a guarantee, which it technically is not.

**Recommended fix:** Use `os.write(fd, line_bytes)` directly for true single-syscall append. Keep entries under 4KB. Or acknowledge the limitation and note that concurrent corruption is unlikely in practice.

---

### FINDING 10: session_id Assumption Not Verified

**Severity: MEDIUM**

**What the plan claims:** `session_id` extracted from `hook_input.transcript_path` (Plan #2, line 116).

**What the code shows:** At `memory_retrieve.py:432`:
```python
transcript_path = hook_input.get("transcript_path", "")
```

The `.get()` with default `""` confirms `transcript_path` may be absent. The `get_session_id()` function design (Plan #2, line 273) must handle empty strings, None, paths with no filename, and non-standard formats.

**This matters for PoC #6:** Session-level correlation depends on stable, consistent session_ids across hooks.

**Recommended fix:** Document `get_session_id()` fallback (e.g., random UUID or timestamp hash when transcript_path is missing). Add test cases for edge cases.

---

### FINDING 11: .last_cleanup Race Condition (Benign)

**Severity: LOW**

**What the plan claims:** Cleanup at most once per 24h via `.last_cleanup` timestamp (Plan #2, lines 157-163).

**What's actually true:** Concurrent Claude Code sessions could both trigger cleanup. But worst case:
- Double-deletion of already-expired files (benign)
- Race on writing `.last_cleanup` (last writer wins, benign)

**Gemini assessment (MEDIUM):** Recommends atomic file locking.

**My assessment:** Over-engineering for a benign race. The plan's fail-open semantics already handle this.

**Recommended fix:** Use `os.rename()` for atomic `.last_cleanup` update. Skip full file locking.

---

## Plan #3: PoC Experiments

### FINDING 12: PoC #7 Depends on Schema Field Not in Plan #2 (Cross-Plan Gap)

**Severity: HIGH (Cross-Plan)**

**What Plan #3 needs:** `matched_tokens` per result to analyze OR-query false positives (Plan #3, lines 229, 384).

**What Plan #2 provides:** Schema (lines 86-108) includes `data.results[]` with `path`, `score`, and `confidence` -- but NOT `matched_tokens`.

**Plan #3's workaround** (lines 249-256) is post-hoc token intersection:
```python
result_tokens = tokenize(result["title"]) | result["tags"]
matched_tokens = query_tokens & result_tokens
```

This is unreliable because:
1. FTS5 uses prefix wildcards (`"auth"*` matches "authentication"). Set intersection won't catch this.
2. Body bonus matches (`score_with_body()` at `memory_retrieve.py:186-259`) are not in title+tags
3. The workaround produces different results than what FTS5 actually matched

**Codex assessment (HIGH, blocking):** "Plan #3 PoC #7 has a schema dependency gap that is effectively blocking."

**Gemini assessment (HIGH):** "PoC #7 is functionally unexecutable without matched_tokens in the logs."

**Recommended fix:** Update Plan #2 schema to add `matched_tokens` and `matched_token_count` to `data.results[]`. Compute at log time in `memory_retrieve.py`: `matched_tokens = query_tokens & (title_tokens | result_tags)`. This is imperfect (doesn't capture prefix matches) but far better than post-hoc reconstruction.

---

### FINDING 13: PoC #6 Nudge Compliance Is Fundamentally Brittle

**Severity: MEDIUM**

**What the plan claims:** Nudge compliance = correlation between compact injection and subsequent `/memory:search` calls within 3 turns / 5 minutes (Plan #3, lines 283-289).

**What all reviewers agree:** This cannot establish causation. The plan acknowledges this (line 305).

**Unaddressed confounding variable:** Complex queries naturally produce both (a) lower-confidence matches (triggering compact injection) and (b) user follow-up searches (because the task is hard). The nudge is not causing the search -- task complexity is causing both.

**The attribution window is arbitrary** -- "3 turns / 5 minutes" has no empirical basis.

**Codex and Gemini both flagged this in earlier rounds and again in this review.**

**Recommended fix (choose one):**
1. Redesign as A/B test from the start (randomly show/hide nudge, compare search rates)
2. Downgrade to "exploratory data collection" and remove the decision thresholds (>40% effective, <10% ineffective)
3. At minimum: log continuously without filtering, compute correlation curves across multiple windows during post-hoc analysis

---

### FINDING 14: PoC #4 Kill Criteria May Be Too Generous

**Severity: LOW**

**What the plan claims:** Kill criteria: p95 > 5 seconds = unsuitable for auto-inject (Plan #3, line 153).

**What's actually true:** Current command hook runs in ~100ms. 5 seconds is 50x the current latency. The existing hook timeout is 15 seconds (`hooks.json:50`), so 5 seconds consumes 1/3 of the total budget. For a hook that fires on every user prompt, even 2 seconds would be noticeably slow.

**Recommended fix:** p95 < 1s = "viable for production", p95 < 2s = "investigate further", p95 > 2s = "unsuitable for auto-inject". The 5s threshold should be "absolute upper bound, explore only if other benefits are compelling."

---

### FINDING 15: Sample Size Handling Is Sound (Positive)

**Severity: N/A (Positive)**

The plan's approach to sample sizing (pilot 25-30, expand to 50+, stratified by 5 query types) is pragmatic. Inter-annotator agreement (Cohen's kappa >= 0.6), labeling rubric, and the honest presentation of Codex/Gemini disagreement on sample sizes are all good methodological practices.

---

## Cross-Plan Analysis

### FINDING 16: Implementation Order Has a Baseline Capture Risk

**Severity: MEDIUM**

The plans don't specify whether Actions #1-#3 should complete BEFORE or AFTER logging is operational. If Actions #1-#3 go first:
- PoC #5's "before/after Action #1" comparison loses its baseline (no logging to capture pre-Action #1 performance)

If logging goes first:
- Actions #1-#3 are delayed while logging infrastructure is built

**Recommended fix:** Add explicit cross-plan order:
1. Plan #2 Phase 1-2 (logger module + `retrieval.search` event) -- minimum viable logging
2. PoC #5 Phase A (pilot baseline with current retrieval) -- capture pre-change metrics
3. Plan #1 Actions #1-#3 (retrieval improvements)
4. PoC #5 Phase B (post-change comparison)
5. Remaining Plan #2 phases + remaining PoCs

---

### FINDING 17: Plans Form a Coherent Whole (Positive)

Despite the gaps identified above, the three plans are structurally coherent:
- Plan #1 implements features with safe defaults
- Plan #2 builds observability for those features
- Plan #3 uses observability to validate feature effectiveness
- Rollback paths exist for 2 of 3 main features (output_mode, abs_floor)
- The Agent Hook PoC is correctly isolated to a separate branch

---

## External Model Consensus Summary

| Finding | Codex 5.3 | Gemini 3 Pro | Reviewer |
|---------|-----------|--------------|----------|
| query_tokens privacy | HIGH | HIGH | HIGH |
| logging.enabled default | HIGH | HIGH | HIGH (conditional) |
| PoC #7 matched_tokens gap | HIGH (blocking) | HIGH (blocking) | HIGH |
| abs_floor corpus-dependent | MEDIUM | CRITICAL | HIGH |
| Cluster detection no toggle | MEDIUM | CRITICAL | HIGH |
| Log path security | MEDIUM | N/A | MEDIUM |
| Atomic append overstated | MEDIUM | MEDIUM | MEDIUM |
| session_id assumption | N/A | N/A | MEDIUM |
| PoC #6 attribution | MEDIUM | MEDIUM | MEDIUM |
| Implementation order | N/A | N/A | MEDIUM |
| .last_cleanup race | N/A | MEDIUM | LOW |
| memory-compact naming | N/A | N/A | LOW |
| PoC #4 kill criteria | N/A | N/A | LOW |

**Strong consensus (all agree):**
1. Logging query_tokens is a privacy risk
2. PoC #7 schema gap is blocking
3. Cluster detection needs a config toggle
4. XML tag conversion from HTML comments is correct
5. Agent Hook PoC branch isolation is correct
6. Legacy-safe defaults are well-designed

**Disagreement:**
- Gemini rates abs_floor as CRITICAL (abandon it); Codex and I rate HIGH (safe with default 0.0, needs calibration warning)
- Gemini rates cluster detection as CRITICAL; I rate HIGH (needs toggle, not removal)

---

## Overall Verdicts

### Plan #1 (Actions #1-#4): APPROVE WITH CHANGES

**Required changes:**
1. Add `retrieval.cluster_cap_enabled` config toggle (default `true`) -- ~3 LOC for config-based rollback
2. Remove "recommended starting value 1.0-2.0" for abs_floor -- defer to empirical data
3. Reframe Agent Hook PoC question 2 (already answered by verification doc)

**Strengths to preserve:** Backward-compatible defaults, sequential ordering, thorough test impact analysis, security requirements preserved.

### Plan #2 (Logging Infrastructure): APPROVE WITH CHANGES

**Required changes:**
1. Add `.claude/memory/logs/` to `.gitignore` guidance -- ESSENTIAL
2. Log `matched_tokens` (query AND index intersection) instead of raw `query_tokens` at info level
3. Add `matched_tokens` and `matched_token_count` fields to `retrieval.search` schema (unblocks PoC #7)
4. Add event_type allowlist validation for log path security
5. Document write guard non-interference

**Strengths to preserve:** Fail-open semantics, minimal config surface (3 keys), dual-write migration strategy.

### Plan #3 (PoC Experiments): APPROVE WITH CHANGES

**Required changes:**
1. Resolve matched_tokens schema dependency with Plan #2 before PoC #7
2. Downgrade PoC #6 to "exploratory data collection" or redesign as A/B test -- remove decision thresholds
3. Lower Agent Hook kill criteria from 5s to 2s (p95)
4. Add cross-plan implementation ordering (logging baseline -> measure -> implement -> re-measure)

**Strengths to preserve:** Time-boxed PoC #4, stratified sampling for PoC #5, dataset reuse between #5 and #7.
