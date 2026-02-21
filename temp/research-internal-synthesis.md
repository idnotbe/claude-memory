# Retrieval System: Internal Research Synthesis

**Date:** 2026-02-20
**Sources:** 6 investigation files (retrieval-complete-investigation.md, retrieval-cross-verification.md, retrieval-flow-analysis.md, retrieval-scoring-analysis.md, retrieval-security-analysis.md, retrieval-architecture-critique.md) + current source code of memory_retrieve.py
**Purpose:** Concise, deduplicated synthesis for ongoing development reference

---

## 1. Current Retrieval Mechanism

### Pipeline Overview

The retrieval system is a UserPromptSubmit hook (fires on every user prompt). It is a stdlib-only Python script (`memory_retrieve.py`, ~398 lines) that runs within a 10-second timeout.

**Flow:**
1. Read stdin JSON (`user_prompt`, `cwd`) from Claude Code hook payload
2. Early exits: empty stdin, prompt < 10 chars, missing index, retrieval disabled, max_inject=0, empty tokens
3. Auto-rebuild `index.md` from JSON source-of-truth files if missing (derived artifact pattern)
4. Load config (`retrieval.enabled`, `retrieval.max_inject` clamped to [0,20], category descriptions)
5. Parse index lines via regex into entries (category, title, path, tags)
6. Tokenize user prompt (lowercase, `[a-z0-9]+` regex, stop-word removal, min length filter)
7. **Pass 1 -- Text Matching:** Score all entries against prompt tokens. Discard score=0.
8. **Pass 2 -- Deep Check:** Read JSON files for top 20 candidates. Filter retired. Apply +1 recency bonus (<=30 days). Entries ranked 21+ included without deep check.
9. Re-sort, take top `max_inject` (default 5). Output `<memory-context>` XML block to stdout.

### Tokenization

```python
_TOKEN_RE = re.compile(r"[a-z0-9]+")
```

- Lowercases all text
- Extracts only ASCII alphanumeric runs (hyphens, underscores, Unicode all act as separators)
- Removes 64 stop words (including common verbs: `use`, `get`, `go`, `help`, `need`, `make`, etc., plus 2-char additions: `as`, `am`, `us`, `vs`)
- **Current code:** Minimum token length is **2 characters** (`len(word) > 1`)
  - NOTE: The investigation files describe the old threshold of 3 chars (`len(word) > 2`). The code has been updated since.
- Returns a `set` (frequency carries zero weight by design)

### Index Format

Each line in `index.md`:
```
- [CATEGORY] title -> path #tags:tag1,tag2,tag3
```

Parsed by regex `_INDEX_RE`. Title capture is non-greedy (`.+?`), stopping at first ` -> `. Tags are optional, comma-separated, lowercased at parse time.

---

## 2. Scoring Algorithm

### Pass 1: Text Matching

**`score_entry()` weights:**

| Match Type | Points | Condition |
|---|---|---|
| Exact title word match | +2 per token | `prompt_words & title_tokens` |
| Exact tag match | +3 per tag | `prompt_words & entry_tags` |
| Forward prefix match | +1 per prompt word | prompt word (len >= 4) is prefix of any title/tag token |
| Reverse prefix match | +1 per prompt word | any title/tag token (len >= 4) is prefix of prompt word |

The reverse prefix match (`pw.startswith(target)`) is a fix applied since the investigation files were written. The investigations describe only forward prefix matching and flag the one-way directionality as a major weakness. The current code now supports both directions, meaning `"authentication"` in the prompt can match `"auth"` in tags (if `len("auth") >= 4`).

**`score_description()` weights:**

| Match Type | Points | Cap |
|---|---|---|
| Exact match in category description | +1.0 per token | -- |
| Prefix match (4+ char) in description | +0.5 per token | -- |
| Total description contribution | capped at 2 | `min(2, int(score + 0.5))` |

The rounding has been fixed from `int(score)` (truncation) to `int(score + 0.5)` (round-half-up). The investigations flag the truncation as a likely bug; it has been addressed.

**Anti-flooding guard:** Description score is only applied when `text_score > 0` (the entry already matched on title/tags). This prevents pure category-description matches from flooding results.

**Category priority (tie-breaking only):** DECISION=1, CONSTRAINT=2, PREFERENCE=3, RUNBOOK=4, TECH_DEBT=5, SESSION_SUMMARY=6.

### Pass 2: Deep Check (Top 20)

- Reads JSON files for top 20 Pass-1 candidates
- Filters out `record_status == "retired"` entries
- Adds +1 recency bonus if `updated_at` is within 30 days
- Entries ranked 21+ are included without deep check (no retired filter, no recency bonus)
- **Path containment check** now applied to all entries (both top-20 and 21+): `file_path.resolve().relative_to(memory_root_resolved)` -- entries outside the memory root are skipped

### Key Constants

- `_DEEP_CHECK_LIMIT = 20`
- `_RECENCY_DAYS = 30`
- `max_inject` default 5, clamped [0, 20]
- Stop words: 64 tokens
- Token minimum length: `> 1` (2+ chars survive)
- Prompt minimum length: 10 chars

---

## 3. Fixes Already Applied (Post-Investigation)

The current codebase has addressed several issues identified across the investigation files:

| Issue | Status | Evidence in Current Code |
|---|---|---|
| One-way prefix matching (no reverse) | **Fixed** | Line 122: `pw.startswith(target) and len(target) >= 4` |
| `int(score)` truncation in `score_description()` | **Fixed** | Line 153: `int(score + 0.5)` round-half-up |
| Tags not XML-escaped in output | **Fixed** | Line 390: `html.escape(t)` for each tag |
| Path not XML-escaped in output | **Fixed** | Line 392: `html.escape(entry["path"])` |
| Path traversal in `check_recency()` | **Fixed** | Lines 334-337: `file_path.resolve().relative_to(memory_root_resolved)` containment check |
| Path containment on entries 21+ | **Fixed** | Lines 354-357: same containment check applied |
| `_sanitize_title()` truncation after XML escape | **Fixed** | Lines 202-204: truncate BEFORE escape now |
| `cat_key` unsanitized in descriptions attribute | **Fixed** | Lines 377-380: `re.sub(r'[^a-z_]', '', cat_key.lower())` |
| Category description flooding | **Fixed** | Line 313: `if cat_desc_tokens and text_score > 0:` guard |
| 2-char tokens permanently unreachable | **Partially fixed** | Line 67: `len(word) > 1` (lowered from `> 2`), with 2-char stop words added |

---

## 4. Known Weaknesses and Remaining Failure Modes

### 4.1 Semantic / Synonym Blindness (Fundamental Limitation)

The system has zero semantic understanding. No stemming, lemmatization, or synonym expansion.

- `"error"` does not match `"bug"`, `"issue"`, or `"problem"`
- `"Dockerfile"` does not match `"Container build configuration"`
- `"rate limiting"` does not match `"throttling policy"`
- Morphological variants: `"fixing"` and `"fix"` are distinct tokens (though prefix matching partially helps: `"fix"` forward-prefixes `"fixing"`)

Mitigation: Tags serve as a manual synonym layer, but depend entirely on the writing subagent's foresight.

### 4.2 Single-Prompt Context

Retrieval tokenizes only the current `user_prompt`. No conversation history, no recent file edits, no tool context. Short follow-up prompts ("continue", "same approach", "that error again") produce zero or near-zero keyword overlap with stored memories.

The triage system (save path) processes 50 messages; retrieval processes 1 line. Information flows into memory from rich context but is retrieved only from sparse context.

### 4.3 Body Content Not Indexed

Memory entry bodies are never consulted during Pass 1. An entry with a generic title but highly relevant body content scores low. Only title, tags, and (capped) category description contribute to text scoring. This particularly hurts RUNBOOKs, which often have detailed procedural content in the body but terse titles.

### 4.4 RUNBOOK Priority Paradox

RUNBOOK has priority 4 (lower than DECISION=1, CONSTRAINT=2, PREFERENCE=3). When a user describes an error, the RUNBOOK with the fix steps is the most actionable memory type, but it loses all tie-breaks to DECISIONs. Given the small-integer scoring (scores typically range 2-15), ties are common.

### 4.5 Retired Entries Beyond Deep-Check Limit

Entries ranked 21+ in Pass 1 bypass the retired-status JSON check. Under normal operation, retired entries are removed from the index immediately by `memory_write.py`, so this requires a stale index to manifest. The code documents this as an accepted performance trade-off.

### 4.6 Index Staleness / Sync Lag

`index.md` is a derived artifact with no self-healing mechanism for drift. If `memory_write.py` writes JSON but fails before updating the index, or if JSON files are hand-edited, the index can be stale. There is no watermark, content hash, or automatic rebuild trigger for stale-but-present indexes. The `--validate` command exists but must be invoked manually.

### 4.7 Hard-Coded Scoring Weights

Weights (title=2, tag=3, prefix=1, description cap=2, recency=1) are fixed with no learning or tuning mechanism. There is no feedback loop to adjust weights based on which retrieved memories were actually useful.

### 4.8 Linear Scan Scalability

All index entries are scanned on every prompt. At the design ceiling of 600 entries (6 categories x 100 max), this is fast. The real bottleneck is Pass 2 I/O: 20 JSON file reads. On network filesystems (WSL, Docker volumes), each read can cost 5-20ms, totaling 100-400ms per prompt.

### 4.9 `match_strategy` Config Key Is a No-Op

The config supports `retrieval.match_strategy: "title_tags"` but the script ignores it entirely. The full title+tags+description pipeline always runs. Documented as "agent-interpreted" but creates a gap if future strategies are needed.

### 4.10 Tokenization Inconsistency Across Scripts

`memory_retrieve.py` uses `len(word) > 1` (2+ char tokens) while `memory_candidate.py` still uses `len(word) > 2` (3+ char tokens). Tags like `"ci"` and `"db"` can now match during retrieval but not during candidate selection for writes.

---

## 5. Security Assessment (Post-Fixes)

### Confirmed Fixed

- **Tag XML injection / boundary breakout**: Tags now use `html.escape()`. A tag of `</memory-context>` renders as `&lt;/memory-context&gt;`.
- **Path traversal in deep check**: Containment validation via `.resolve().relative_to()` applied to all entries.
- **`_sanitize_title()` truncation order**: Truncation now happens before XML escaping, preventing broken HTML entities.
- **`cat_key` attribute injection**: Category keys sanitized to `[a-z_]` only.
- **Path field unsanitized**: Path now escaped via `html.escape()`.

### Remaining Concerns

1. **Index rebuild trusts write-side sanitization** (known gap, documented in CLAUDE.md). `memory_index.py` reads titles from JSON verbatim into `index.md`. If `memory_write_guard.py` is bypassed (hand-edited JSON, direct file write), titles containing ` -> ` or `#tags:` can corrupt index parsing. Defense-in-depth relies on `_sanitize_title()` at read time.

2. **Config integrity not verified.** `memory-config.json` has no checksum or signing. Malicious config can disable retrieval entirely (`enabled: false`), set `max_inject: 0`, or alter category descriptions to bias scoring.

3. **BiDi/Unicode stripping only at read time.** Write-side `auto_fix` does not strip bidirectional override characters from titles. They persist in JSON and index until stripped by `_sanitize_title()` during retrieval output.

4. **`grace_period_days` type confusion** in `memory_index.py`. Config value is not type-checked. A string value like `"30"` causes a TypeError in `gc_retired`. Low severity (manual operation only).

5. **Unicode normalization absent.** `_sanitize_title()` does not apply NFC/NFKC normalization. Visually identical composed vs. decomposed Unicode sequences are not collapsed.

6. **Concurrent index rebuild race condition.** Multiple simultaneous `UserPromptSubmit` events could trigger concurrent `memory_index.py --rebuild` subprocess calls. POSIX atomic rename mitigates, but behavior is undefined on certain filesystems (WSL, NFS).

---

## 6. Architecture Constraints

| Constraint | Impact on Retrieval |
|---|---|
| **Stdlib-only requirement** | No ML libraries, no embeddings, no sentence-transformers |
| **10-second hook timeout** | Hard ceiling on total execution time including index rebuild |
| **UserPromptSubmit payload** | Only provides `user_prompt` + `cwd`, no conversation history |
| **Flat index.md** | Linear scan, no inverted index, no pre-computed embeddings |
| **Derived artifact pattern** | Index can become stale; no self-healing staleness detection |
| **max 600 entries** (6 categories x 100) | Practical ceiling; linear scan is O(N*M) with prefix matching |
| **Plugin environment** | Cannot modify Claude Code hook protocol; must work within existing API |
| **Exit code convention** | Must exit 0 even on "no results" (non-0 = hook error) |

**Why keyword matching:** Zero external dependencies, deterministic and auditable, no model drift, and the use case is structurally friendly (both titles and prompts authored in consistent technical register). Semantic search would add the most value for paraphrase detection, which matters less in this context.

**Why flat index.md:** Zero-dependency, human-readable, recoverable. SQLite would add schema migration and locking concerns. Flat file allows `cat`/`grep` debugging.

**Why two-pass:** Classic pre-filter / detailed-evaluation pattern. Pass 1 narrows candidates cheaply; Pass 2 performs targeted I/O. The weakness is that Pass 1 determines which entries ever reach Pass 2 -- body-content-relevant entries with weak titles are permanently invisible.

---

## 7. Previously Identified Improvement Opportunities

### Tier 1: High Impact, Low Effort

**I1. Body token indexing.** Add `#body:token1,token2,...` suffix to index lines (top 10-15 most frequent non-stop-word tokens from the memory body). Populate at write time and rebuild time. Dramatically improves recall for content-relevant queries without architectural change. Index lines grow from ~120 to ~200 chars.

**I2. Intent-based category boosting.** Detect intent keywords in prompt to dynamically adjust category priority: error/fail/crash -> boost RUNBOOK; why/decide/choose -> boost DECISION; goal/summary/session -> boost SESSION_SUMMARY. Simple keyword-set lookup, ~20 lines.

**I3. Basic stemming (S-stemmer).** Strip common English suffixes ('s', 'ing', 'ed', 'ly', 'tion'/'sion' normalization) before matching. "fixing" matches "fix", "migrations" matches "migration". ~10-15 lines of string manipulation.

### Tier 2: Medium Impact, Medium Effort

**I4. Prompt ring buffer.** Store tokenized content of last 3-5 prompts in `.staging/.prompt-ring.json`. Include previous tokens with decay weight (0.3x) for follow-up prompt support. Requires session-boundary clearing logic. Depends on whether the hook API exposes session boundaries.

**I5. Configurable scoring weights.** Load weights from `memory-config.json` (`retrieval.weights.title`, `.tag`, `.prefix`, `.description_cap`). Allows tuning without code changes.

**I6. Retired status in index line.** Add `#status:retired` marker to index lines when retiring. Allows Pass 1 filtering without JSON I/O, eliminating the deep-check-limit gap entirely.

**I7. Index staleness detection.** Add timestamp watermark to index header. Compare against newest JSON mtime on read. Trigger background rebuild if stale beyond threshold (e.g., 60s).

### Tier 3: Lower Priority / Higher Effort

**I8. Per-category score multipliers.** Configurable `retrieval.category_weights.runbook: 1.2` to boost/penalize categories. More nuanced than static priority.

**I9. Synonym table.** Static mapping of common technical synonyms (auth<->authentication, db<->database, config<->configuration). Expand prompt tokens before matching. ~50-line lookup table.

**I10. Recency burst for SESSION_SUMMARY.** Session summaries created within last 2 hours get +2 bonus. Makes them "sticky" at session start when most relevant.

**I11. Tokenization consistency fix.** Align `memory_candidate.py` token minimum to `> 1` to match `memory_retrieve.py`. Currently inconsistent. Trivial fix.

---

## 8. Cross-Report Consensus

All 6 investigation files agree on these points:

1. Two-pass scoring structure (index scan -> JSON deep-check) is correctly implemented
2. Scoring weights (title=2, tag=3, prefix=1) are consistent and verifiable
3. Retired entries can leak through deep-check limit of 20 (accepted trade-off)
4. Keyword matching has fundamental synonym/semantic blindness
5. Single-prompt context is a persistent architectural limitation
6. The architecture is well-suited to the zero-dependency plugin constraint
7. The system is deterministic and auditable -- its most important design property

### Single Factual Error Across Reports

The main investigation report (retrieval-complete-investigation.md) states "32 stop words." The actual count is 64 in the current code (60 at the time of the investigation, plus 4 two-char additions). All other reports correctly state 60.

---

## 9. Delta: Investigation Files vs. Current Code

The investigation files (dated 2026-02-19) describe a prior version. Key behavioral changes since:

| Investigation Claim | Current Code Reality |
|---|---|
| Token min length `> 2` (3+ chars) | `> 1` (2+ chars) at line 67 |
| Prefix matching is one-way only | Bidirectional at lines 117-123 |
| `_sanitize_title` truncates after XML escape | Truncation before escape at lines 202-204 |
| Tags not XML-escaped in output | Escaped via `html.escape()` at line 390 |
| No path traversal check | Containment check at lines 334-337 |
| `cat_key` unsanitized | Sanitized at lines 377-380 |
| `int(score)` truncation | `int(score + 0.5)` round-half-up at line 153 |
| 60 stop words | 64 stop words (added `as`, `am`, `us`, `vs` at line 34) |
| Path field unsanitized | Escaped via `html.escape()` at line 392 |
| Description score applied to all entries in a category | Only applied when `text_score > 0` at line 313 |

When reading the investigation files, treat any finding related to these items as **already resolved** unless re-verified against the current code.

---

*Synthesized from 6 investigation files totaling ~2,800 lines of analysis, cross-verified against current source code.*
