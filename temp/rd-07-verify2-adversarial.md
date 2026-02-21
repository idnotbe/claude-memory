# Verification Round 2: Adversarial Analysis

**Verifier:** verifier2-adversarial
**Date:** 2026-02-20
**Status:** COMPLETE
**Input:** Consolidated plan (rd-05), R1 technical (rd-06-verify1-technical), R1 practical (rd-06-verify1-practical), Original skeptic review (rd-03), Current code (memory_retrieve.py)
**External validation:** Gemini 3.1 Pro (via clink), empirical Python 3 sqlite3 tests, pal challenge tool

---

## Executive Summary

After all previous reviews and R1 verification, the plan is **technically correct on its core claims** but has **3 remaining issues that previous reviewers either missed or mischaracterized**. The most significant is a semantic precision problem with phrase query wildcards that everyone marked as "PASS" but which empirically produces false positives for the exact use case this system targets: coding identifier queries.

**Findings: 1 CRITICAL, 2 HIGH, 2 MEDIUM, 1 LOW**

---

## Finding 1: Phrase Query Wildcards Create Systematic False Positives for Coding Identifiers

**Severity: CRITICAL**

### What Everyone Missed

R1-technical verified that `"user_id"*` works and "matches entries containing token `user_id`." R1-practical said to drop `tokenchars` and use default `unicode61` with phrase queries. Both marked this PASS.

**They are both technically correct and both practically wrong.**

### The Mechanism

With default `unicode61`, underscore is a separator. FTS5 tokenizes `user_id` into two tokens: `user` and `id`. When the plan builds query `"user_id"*`, FTS5 interprets this as:

> Find token `user` immediately followed by any token starting with `id`

**Empirically verified on this system:**

```
Query: "user_id"*
  MATCH: The user_id is important          <- TRUE POSITIVE
  MATCH: Each user identity is verified    <- FALSE POSITIVE
```

The wildcard `*` applies **only to the last token** in the phrase. So `"user_id"*` matches:
- `user_id` (user + id) -- correct
- `user identity` (user + id*entity) -- **false positive**
- `user idle` (user + id*le) -- **false positive**
- `user idempotent` (user + id*empotent) -- **false positive**

### Why R1-Technical Missed This

R1-technical tested `"user_id"*` against data containing `user_id` and confirmed it matched. They did NOT test what ELSE it matches. They checked for false negatives (does it find what it should?) but not false positives (does it find what it shouldn't?).

### Quantified Impact

In a developer memory corpus, `user_id` is a common identifier. But so are terms starting with "user id" in different contexts:
- "user identification" (authentication flows)
- "user idle timeout" (session management)
- "user identity provider" (SSO/Okta)

**My empirical test with realistic memory titles:**

```
Query: "user_id"*
  User identification flow          <- FALSE POSITIVE (matched user + id*entification)
  User ID generation strategy       <- TRUE POSITIVE
  User idempotency keys             <- FALSE POSITIVE (matched user + id*empotency)
  User idle detection               <- FALSE POSITIVE (matched user + id*le)
```

**Result: 75% false positive rate** for this specific query pattern. Even accounting for BM25 ranking separating true from false positives (it doesn't -- they all scored within 10% of each other), the `max_inject: 3` limit means false positives will crowd out true positives.

### Gemini 3.1 Pro Confirmation

> "The `*` prefix operator applies only to the last token. Your query becomes 'find the word `user` immediately followed by any word starting with `id`'. It erroneously matches strings like `user identifier` and `user idiotic`. You lose exact variable-name precision."

### Why This Is Worse Than the Current System

The current keyword system tokenizes `user_id` as `['user_id']` (the Python regex preserves underscores). When matching against index titles, it looks for the EXACT token `user_id`. It will NOT match "user identity" because "user_id" != "identity".

**The FTS5 migration actively regresses precision for the primary use case** (coding identifier queries) while improving it for natural language queries.

### The tokenchars Dilemma

R1-practical correctly identified that `tokenchars='_.-'` breaks substring matching. But dropping `tokenchars` introduces this false positive problem. **Neither option is clean:**

| Approach | Benefit | Cost |
|----------|---------|------|
| `tokenchars='_.-'` | No false positives for `user_id` | Breaks substring search: `"id"` alone returns nothing |
| Default `unicode61` | Substring search works | `"user_id"*` matches `user identity`, `user idle`, etc. |

This is a **fundamental tension** that no reviewer has resolved. The plan needs to specify which tradeoff it accepts and document the degradation.

### Possible Mitigations

1. **Drop the wildcard for phrase queries:** Use `"user_id"` (exact phrase, no `*`) when the query token contains `_`, `.`, or `-`. Use `"token"*` (with wildcard) only for single-word tokens. This prevents `user_id` from matching `user identity` while preserving prefix matching for `auth` -> `authentication`.

2. **Dual query strategy:** Run both `"user_id"` (exact) and `"user"* OR "id"*` (broad), then merge and re-rank results.

3. **Accept the tradeoff and document it:** If natural language recall is more important than coding identifier precision, document that coding identifiers will have higher false positive rates.

### Recommendation

**Mitigation 1 is the minimum viable fix.** It is ~5 LOC: check if the cleaned token contains `_`, `.`, or `-` and omit the wildcard suffix for those tokens. This preserves prefix matching for single-word queries while preventing phrase-wildcard false positives for compound identifiers.

---

## Finding 2: The 50% Relative Cutoff Is Unstable and Corpus-Size-Dependent

**Severity: HIGH**

### What R1 Found vs What's Actually True

R1-technical verified the cutoff math is correct (abs() handling of negative scores). R1-practical validated performance. Neither tested cutoff **stability** across varying corpus conditions.

### Empirical Score Distribution Analysis

I tested the 50% cutoff across corpus sizes with randomized data:

| Corpus | Matches | 40% pass | 50% pass | 60% pass | Score variance |
|--------|---------|----------|----------|----------|----------------|
| N=50   | 12      | 12 (100%) | 6 (50%) | 4 (33%) | 1.13 |
| N=100  | 20      | 20 (100%) | 19 (95%) | 14 (70%) | 0.79 |
| N=200  | 20      | 20 (100%) | 20 (100%) | 19 (95%) | 1.12 |
| N=500  | 20      | 20 (100%) | 20 (100%) | 20 (100%) | 0.02 |

**Key observation:** At N=500, all scores cluster within 0.02 of each other, making ANY percentage cutoff pass everything. At N=50, the 50% cutoff aggressively halves the result set. The cutoff's behavior is **completely different depending on corpus size**.

### Why This Matters

The plan hardcodes 50% as the relative cutoff. But:
- For a new user with 30 memories: the cutoff is aggressive, filtering ~50% of matches
- For a mature user with 500 memories: the cutoff filters nothing, all scores are identical
- As the user's corpus grows, the cutoff silently changes behavior

This means the retrieval quality will **drift over time** without any code changes. A user who tuned their expectations at 100 memories will get different results at 300 memories.

### Gemini 3.1 Pro Confirmation

> "A single-word match in a Title (weight 5) will typically yield a BM25 score around ~6.5. A single-word match in the Body (weight 1) will yield ~3.3. If your best document matches the title, your 50% cutoff will aggressively prune ALL documents that only matched in the body."

### The Top-2 Guarantee Is Insufficient

The plan's "guarantee: always return at least top 2" (lines 215-217) partially addresses this. But `max_inject: 3` means the guarantee only adds 1 extra result. If the cutoff removes 5 relevant body-only matches, getting 2 back is not sufficient.

### Recommendation

Replace the percentage-based relative cutoff with a **pure Top-K approach**: always return the top K results by BM25 score, with no relative filtering. The skeptic (Finding #5) and Gemini 3 Pro both recommended this. The plan adopted a compromise (50% + top-2 guarantee) that satisfies neither approach.

If a relative cutoff is desired for noise reduction, use a much lower threshold (25-30%) as a "noise floor" rather than a "quality gate."

---

## Finding 3: Every-Invocation Rebuild Cost Is 74x Higher Than Acknowledged

**Severity: HIGH**

### What Previous Reviews Said

- Pragmatist: "500 files -> ~35ms. Well within budget." **Correct on absolute latency.**
- Skeptic: "Reckless. 300,000 file reads per 2-hour session." **Correct on relative cost, dismissed by plan.**
- R1-technical: Not addressed.
- R1-practical: "31.1ms actual. VALIDATED." **Correct on absolute latency.**
- Plan resolution: "Rebuild per invocation. No disk cache."

### What Nobody Quantified

**I benchmarked the comparison the plan never made:**

```
Per-invocation cost (500 memories):
  Read 500 JSON files:    7.6 ms
  Read index.md (1 file): 0.1 ms
  Full FTS5 rebuild:      10.9 ms
  Ratio JSON/index:       74x

Over a 2-hour session (60 prompts):
  FTS5 rebuild: 30,000 file reads, 0.7 seconds total I/O
  Index.md:     60 file reads, 0.006 seconds total I/O
```

**The FTS5 rebuild approach uses 74x more I/O than reading index.md.** The absolute cost (10.9ms) is acceptable, but the relative cost is not "negligible" -- it is a design choice with measurable overhead.

### Why This Matters More Than Latency

1. **Battery/power on laptops:** 30,000 file reads vs 60 file reads per 2-hour session. For a plugin that fires on every keystroke-submitted prompt, this adds up.

2. **WSL2 /mnt/c/ users:** The plan acknowledges 500ms-1s per rebuild on Windows filesystem. This makes the plugin **visibly laggy** for cross-filesystem users. The plan says "document recommendation: use Linux filesystem" but this is a support burden, not a fix.

3. **File system monitoring interference:** 30,000 file reads per session can trigger filesystem watchers (inotify, fswatch) that other tools depend on. This is a side-effect the plan does not account for.

### The Skeptic Was Right

The skeptic's Finding #6 recommended using index.md as the primary lookup surface and reading JSON only for body content of top-K candidates. This hybrid approach gives body content benefits at O(K) file read cost instead of O(N).

The plan dismissed this with "simplicity benefit outweighs latency cost." **But simplicity is not just about implementation -- operational simplicity (fewer I/O operations, less interference with other tools) also matters.**

### Recommendation

Implement the skeptic's hybrid approach:
1. Read index.md for title/tag/path data (1 file read)
2. Score top candidates by title/tags (existing approach)
3. Read JSON for top-K candidates ONLY to extract body content
4. Re-score with body content bonus

This reduces per-invocation file reads from N to K+1 (where K is typically 5-10).

Alternatively, extend `memory_write.py` to maintain a `body-index.json` cache file alongside index.md, containing pre-extracted body text for each memory. This allows full body search at 2-file-read cost.

---

## Finding 4: Phase 1 Manual Testing Is Invalidated by Phase 2

**Severity: MEDIUM**

### The Problem

Phase 1 adds body content scoring with an **additive** bonus:
```python
body_bonus = min(3, len(body_matches))
final_score = text_score + (1 if is_recent else 0) + body_bonus
```

Phase 2 replaces this with BM25 **weighted** scoring:
```python
bm25(memories, 5.0, 3.0, 1.0)  # title weight 5, tags 3, body 1
```

These are fundamentally different scoring philosophies:
- Phase 1: body matches ADD to existing score (floor of previous ranking preserved)
- Phase 2: body matches COMPETE with title/tag scores via IDF weighting

### Concrete Impact

A memory that scored high in Phase 1 (strong title match + body bonus) may rank differently in Phase 2 (BM25 may weight the body contribution differently based on IDF).

**The plan's Phase 1 validation step** ("Manual: run 5-10 queries that currently return irrelevant results. Verify body content matching improves relevance") **produces results that cannot be compared to Phase 2 behavior.** The validation effort is partially wasted.

### Code Reuse Analysis

Phase 1 is not entirely throwaway -- approximately 60% of the code is reused:
- **Reused (40 LOC):** tokenizer regex fix, BODY_FIELDS dict, extract_body_tokens()
- **Thrown away (20 LOC):** body_bonus integration into scoring loop

### Recommendation

If the plan is committed to Phase 2, skip Phase 1's scoring integration (the 20 LOC that will be thrown away) and instead:
1. Implement the tokenizer fix (Phase 1a) -- universally useful
2. Implement body content extraction (Phase 1b) -- reused by Phase 2
3. Skip Phase 1c (scoring integration) -- thrown away in 1-2 days
4. Go directly to Phase 2 FTS5 with body content included from the start

This saves ~4-6 hours of Phase 1 testing/validation that would be invalidated anyway.

---

## Finding 5: The Plan Underspecifies FTS5 Unavailability Handling

**Severity: MEDIUM**

### The Problem

The plan says: "Error loudly if FTS5 unavailable. All modern Python 3 on Linux/WSL2/macOS has FTS5."

R1-practical recommended: "Add try/except around FTS5 initialization. Fall back to existing keyword system."

The plan's "Deferred Items" table lists "Fallback keyword engine" as deferred with rationale "FTS5 available on all modern Python 3."

### What's Missing

1. **No code snippet** for the FTS5 availability check
2. **No specification** of what "error loudly" means (stderr? exit code? error message format?)
3. **No recovery path** -- if FTS5 fails, the retrieval hook exits with error and the user gets zero memory context

R1-practical estimated this at ~15 LOC. The plan should include these 15 lines explicitly because getting the error handling wrong (e.g., printing to stdout instead of stderr, or exiting with code 0 instead of 1) can either pollute context or silently disable retrieval.

### Recommendation

Add a concrete code snippet for FTS5 fallback. Minimum viable:
```python
try:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE VIRTUAL TABLE _fts5_test USING fts5(c)")
    conn.close()
    HAS_FTS5 = True
except sqlite3.OperationalError:
    HAS_FTS5 = False
    print("[WARN] FTS5 unavailable; falling back to keyword matching", file=sys.stderr)
```

---

## Finding 6: R1 Verification Has a Scope Gap on the "user" + "id"* False Positive Class

**Severity: LOW (meta-finding about verification process)**

### The Problem

R1-technical ran 30+ test cases for the tokenizer regex and verified FTS5 behavior empirically. However, the test methodology checked **each feature in isolation** (prefix matching works, phrase queries work, wildcard works) without testing **feature combinations under realistic conditions**.

The phrase-wildcard false positive (Finding 1 above) only manifests when:
1. Default unicode61 splits compound tokens (produces multi-token phrase)
2. Wildcard is appended to the phrase
3. The last token fragment (`id`) is a common prefix of other English words

Each of these is "working as designed." The bug is in their composition, not in any individual component. This is a classic integration testing gap.

### Recommendation

Future verification rounds should include **adversarial composition tests**: take each pair of interacting features and test whether their combination produces unexpected behavior. The verification template should include a "feature interaction matrix" section.

---

## R1 Findings Verification (Were they correct?)

| R1 Finding | Their Verdict | My Verification | Status |
|------------|---------------|-----------------|--------|
| tokenchars dropped, use unicode61 | Correct | Correct, BUT creates Finding 1 above | INCOMPLETE |
| Absolute BM25 threshold abandoned | Correct | Correct | CONFIRMED |
| BM25 scores are ~1-4 magnitude | Correct | Verified: scores range 2.3-6.8 with weights | CONFIRMED |
| Test rewrite needs +4-6 hours | Correct | Correct | CONFIRMED |
| Need automatic FTS5 fallback | Correct | Correct, but no code provided | CONFIRMED |
| Import path needs sys.path fix | Correct | Correct | CONFIRMED |
| Quoting is mandatory for dotted terms | Correct | Correct | CONFIRMED |
| Prefix matching across token boundaries works | Correct | Correct, BUT with false positives (Finding 1) | INCOMPLETE |

**2 of 8 R1 findings are INCOMPLETE** -- they verified the happy path without adversarial testing.

---

## Skeptic Findings Cross-Check (Were they resolved?)

| Skeptic Finding | Severity | Plan Resolution | My Assessment |
|-----------------|----------|-----------------|---------------|
| #1 Precision estimates ungrounded | CRITICAL | Acknowledged, kept estimates | STILL UNRESOLVED (no benchmark yet) |
| #2 Body content is the real win | CRITICAL | Phase 1 delivers body content first | RESOLVED |
| #3 Sanitization destroys code terms | CRITICAL | Tokenizer fix in Phase 1 | PARTIALLY RESOLVED (Finding 1 above) |
| #4 Transcript 8KB seek fails | HIGH | Deferred entirely | RESOLVED (deferred is correct decision) |
| #5 Relative threshold starvation | HIGH | 50% cutoff + top-2 guarantee | PARTIALLY RESOLVED (Finding 2 above) |
| #6 Every-invocation rebuild | HIGH | "Simplicity outweighs cost" | NOT RESOLVED (Finding 3 above) |
| #7 Skill 67% effectiveness | MEDIUM | Mitigations listed | NOT RESOLVED (mitigations unproven) |
| #8 claude-mem lessons selective | MEDIUM | Addressed in design rationale | RESOLVED |
| #9 Config attack surface | MEDIUM | Config keys minimized | RESOLVED |
| #10 No daemon unjustified | LOW | Documented as hard constraint | RESOLVED |

**3 of 10 skeptic findings remain unresolved.** 2 are partially resolved. 5 are fully resolved.

---

## Summary of Findings

| # | Finding | Severity | New or Existing? |
|---|---------|----------|------------------|
| 1 | Phrase query wildcard creates false positives for compound identifiers | CRITICAL | NEW (missed by all reviewers) |
| 2 | 50% relative cutoff is unstable across corpus sizes | HIGH | EXISTING (skeptic #5 reframed with data) |
| 3 | Per-invocation rebuild is 74x costlier than index.md approach | HIGH | EXISTING (skeptic #6 reframed with data) |
| 4 | Phase 1 manual testing invalidated by Phase 2 scoring change | MEDIUM | NEW |
| 5 | FTS5 unavailability handling underspecified | MEDIUM | EXISTING (R1-practical, unresolved) |
| 6 | R1 verification missed feature interaction testing | LOW | META |

---

## Consolidated Recommendations (Priority Order)

1. **Fix phrase query wildcard for compound tokens** (CRITICAL, ~5 LOC): Omit `*` suffix when token contains `_`, `.`, or `-`. Use `"user_id"` (exact phrase) instead of `"user_id"*` for compound identifiers.

2. **Replace 50% relative cutoff with pure Top-K** (HIGH, ~3 LOC): Return top K results by BM25 score. If noise filtering is needed, use 25-30% as a floor, not 50% as a gate.

3. **Implement hybrid index.md + JSON approach** (HIGH, ~30 LOC): Use index.md for initial title/tag scoring. Read JSON only for top-K body content. Or maintain a body-index.json cache.

4. **Skip Phase 1 scoring integration** (MEDIUM, saves ~6 hours): Implement tokenizer fix and body extraction (reusable), skip scoring loop changes (thrown away by Phase 2).

5. **Add explicit FTS5 fallback code** (MEDIUM, ~15 LOC): Try/except with keyword system fallback and stderr warning.

---

## External Validation Summary

### Gemini 3.1 Pro (via clink)

Key findings independently confirmed:
- `"user_id"*` wildcard applies only to last token, matching `user identifier`, `user idle`
- 50% cutoff with 5/3/1 weights will "aggressively prune ALL documents that only matched in the body"
- IDF volatility at small N makes score distributions unpredictable
- Unescaped FTS5 syntax (colons, hyphens) can crash queries -- the plan's sanitization handles this but it's a common migration bug

### pal challenge (self-scrutiny)

Confirmed that the phrase-wildcard false positive is a real precision problem, not an overblown edge case. The false positives (`user identity`, `user idle`) are plausible developer memory titles, not theoretical constructs.

### Empirical Testing (local Python 3 sqlite3)

All findings verified with reproducible test scripts. Score distributions, false positive rates, and I/O benchmarks measured directly on the target WSL2 system.
