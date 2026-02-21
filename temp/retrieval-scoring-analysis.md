# Retrieval Scoring Analysis: claude-memory Plugin

**Date:** 2026-02-19
**Files analyzed:**
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_retrieve.py`
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_candidate.py`

---

## 1. Tokenization

### Implementation

Both scripts share an identical tokenizer. In `memory_retrieve.py`:

```python
_TOKEN_RE = re.compile(r"[a-z0-9]+")

def tokenize(text: str) -> set[str]:
    tokens = set()
    for word in _TOKEN_RE.findall(text.lower()):
        if word not in STOP_WORDS and len(word) > 2:
            tokens.add(word)
    return tokens
```

### What Gets Kept

- Text is lowercased before matching: `"Docker"` -> `"docker"`.
- The regex `[a-z0-9]+` extracts runs of ASCII letters and digits only. Punctuation, hyphens, underscores, Unicode characters, and all non-ASCII content are treated as word separators.
- Words must be longer than 2 characters (`len(word) > 2`), so 1- and 2-character tokens are discarded. `"db"`, `"ui"`, `"k8s"` (the "k8s" case: `"k8s"` has length 3, so it passes) all survive this threshold, but `"CI"` (lowercased `"ci"`) does not.

### What Gets Discarded

**Stop words (60 tokens):**

```
a, an, the, is, was, are, were, be, been, being,
do, does, did, have, has, had, will, would, could,
can, should, may, might, shall, must,
i, you, we, they, he, she, it, me, my, your,
this, that, these, those, what, which, who, whom,
how, when, where, why, if, then, else, so,
and, or, but, not, no, yes, to, of, in, on,
at, for, with, from, by, about, up, out, into,
just, also, very, too, let, please, help, need,
want, know, think, make, like, use, get, go, see
```

**Structural discards:**
- Hyphens split tokens: `"memory-config"` -> tokens `{"memory", "config"}`.
- Underscores split tokens: `"tech_debt"` -> tokens `{"tech", "debt"}`.
- Any word of 1-2 characters after lowercasing is dropped (including `"db"`, `"ui"`, `"ci"`, `"k8s"` is actually 3 chars and passes, but `"js"`, `"ts"`, `"go"` all fail the length check or are in stop words).
- Non-ASCII characters are silently ignored by the regex. A prompt in French or with Unicode identifiers will lose all non-ASCII content before scoring.

**Return type:** The function returns a `set[str]`, meaning all duplicate tokens are collapsed. A prompt that says "Docker Docker Docker" contributes exactly one `"docker"` token.

### Critical Observation: Sets vs Bags

Because both prompt tokens and title tokens are sets, the system cannot reward repeated mentions. The word "performance" appearing 5 times in a title yields the same contribution as it appearing once. This is intentional (avoids gaming by keyword stuffing), but it also means frequency carries zero weight.

---

## 2. Index Line Parsing

### Regex Pattern

Both scripts use the identical regex:

```python
_INDEX_RE = re.compile(
    r"^-\s+\[([A-Z_]+)\]\s+(.+?)\s+->\s+(\S+)"
    r"(?:\s+#tags:(.+))?$"
)
```

### Group Breakdown

| Group | Captured content | Example |
|-------|-----------------|---------|
| `group(1)` | Category (uppercase, underscores allowed) | `TECH_DEBT` |
| `group(2)` | Title (non-greedy, strips trailing space before `->`) | `Defer PostgreSQL migration` |
| `group(3)` | Path (non-whitespace run) | `.claude/memory/tech-debt/abc123.json` |
| `group(4)` | Tags string (optional, everything after `#tags:`) | `postgres,migration,database` |

### Enriched Line Format

A fully enriched index line looks like:

```
- [TECH_DEBT] Defer PostgreSQL migration -> .claude/memory/tech-debt/abc123.json #tags:postgres,migration,database
```

Tags are split by comma, stripped, and lowercased in `memory_retrieve.py`:

```python
tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()]
```

In `memory_candidate.py`, tags are NOT lowercased at parse time:

```python
tags = [t.strip() for t in tags_str.split(",") if t.strip()]  # note: no .lower()
```

This is a behavioral difference (discussed in Section 4).

### Backwards Compatibility

Lines without the `#tags:` suffix match via the optional non-capturing group `(?:\s+#tags:(.+))?$`. Group 4 returns `None`, and the code handles this:

```python
tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()] if tags_str else []
```

Old-format lines without tags parse correctly and get an empty tag set. No migration is required.

### Regex Fragility Notes

- The title capture group uses `.+?` (non-greedy) between `\[CAT\]` and `->`. If the title itself contains ` -> `, the regex will split on the first occurrence, truncating the title. This is the "index format injection" vulnerability mentioned in CLAUDE.md. The write-side sanitization is supposed to catch this, but the parser itself does not validate.
- The `group(2)` strip only removes trailing whitespace before the ` -> ` separator; leading whitespace in the title is removed by the final `.strip()` in the parse function.
- Paths (group 3) are captured as `\S+` (no whitespace), so paths with spaces would fail silently. This is consistent with the write-side behavior (JSON paths do not normally have spaces).

---

## 3. Scoring Weights

### 3.1 Primary Scorer: `score_entry` in `memory_retrieve.py`

```python
def score_entry(prompt_words: set[str], entry: dict) -> int:
    title_tokens = tokenize(entry["title"])
    entry_tags = entry["tags"]  # already a set of lowercased strings

    # Exact title word matches: 2 points each
    exact_title = prompt_words & title_tokens
    score = len(exact_title) * 2

    # Exact tag matches: 3 points each
    exact_tags = prompt_words & entry_tags
    score += len(exact_tags) * 3

    # Prefix matches (4+ char tokens not already matched): 1 point each
    already_matched = exact_title | exact_tags
    combined_targets = title_tokens | entry_tags
    for pw in prompt_words - already_matched:
        if len(pw) >= 4:
            if any(target.startswith(pw) for target in combined_targets):
                score += 1

    return score
```

**Weight table for `score_entry`:**

| Match type | Points | Condition |
|---|---|---|
| Exact title word match | +2 per matching token | Prompt token in title tokens |
| Exact tag match | +3 per matching token | Prompt token in entry tags |
| Prefix match (title or tags) | +1 per prompt token | Token >= 4 chars, not already matched, any target starts with it |

**Prefix matching details:** The loop iterates over prompt words that were NOT exact-matched (either by title or tags), and checks if any title token or tag starts with that prompt word. The prompt word must be at least 4 characters. A single prompt word can contribute at most 1 prefix point regardless of how many targets it prefixes. There is no corresponding prefix match in the reverse direction (i.e., a tag prefixing a prompt word does NOT score).

**Example prefix match:**
- Prompt token: `"migrat"` (6 chars)
- Entry tag: `"migration"`
- `"migration".startswith("migrat")` -> True -> +1 point

**Example of asymmetry:**
- Prompt token: `"migration"` (9 chars)
- Entry tag: `"migrat"` (6 chars)
- `"migrat".startswith("migration")` -> False -> 0 points

The prefix direction is always: prompt-word is the prefix, entry content is the target. Short prompt words cannot match long entry terms via prefix.

### 3.2 Description Score: `score_description` in `memory_retrieve.py`

```python
def score_description(prompt_words: set[str], description_tokens: set[str]) -> int:
    score = 0.0
    exact = prompt_words & description_tokens
    score += len(exact) * 1.0
    already_matched = exact
    for pw in prompt_words - already_matched:
        if len(pw) >= 4:
            if any(dt.startswith(pw) for dt in description_tokens):
                score += 0.5
    return min(2, int(score))
```

**Weight table for `score_description`:**

| Match type | Points | Cap |
|---|---|---|
| Exact match in category description | +1.0 per matching token | - |
| Prefix match (4+ char) in description | +0.5 per matching token | - |
| Total | - | capped at `min(2, int(score))` |

**Cap mechanics:** The cap is applied as `min(2, int(score))`. The `int()` truncates (floors) the float. This means:
- Score of 1.5 (one exact + one prefix) -> `int(1.5)` = 1 -> `min(2, 1)` = 1
- Score of 2.5 (two exact + one prefix) -> `int(2.5)` = 2 -> `min(2, 2)` = 2
- Score of 3.0 (three exact) -> `int(3.0)` = 3 -> `min(2, 3)` = 2

The use of `int()` instead of `round()` means a score of 1.5 is truncated to 1, not rounded to 2. Two prefix matches (0.5 + 0.5 = 1.0) yield 1 description point.

**Description scoring is per-category, not per-entry:** All entries in the same category share the same description score. If your prompt happens to match words in the "session_summary" category description (`"summary"`, `"coding"`, `"session"`, `"goals"`, `"outcomes"`, `"steps"`), then EVERY entry in SESSION_SUMMARY gets +1 or +2 bonus points, regardless of whether those individual entries are relevant.

### 3.3 Recency Bonus

```python
_RECENCY_DAYS = 30

final_score = text_score + (1 if is_recent else 0)
```

A flat +1 is added to any entry whose JSON file has an `updated_at` timestamp within the last 30 days. This is determined by reading the actual JSON file during the deep check phase.

**Threshold:** `age_days <= _RECENCY_DAYS`. The variable `age_days` is computed via `(now - updated_at).days`, which is a whole-number floor of the difference in seconds. An entry updated 30 days and 23 hours ago would have `age_days = 30`, which passes (`30 <= 30`). An entry updated 31 days ago has `age_days = 31`, which does not pass.

---

## 4. Comparison with `memory_candidate.py`

### Shared Architecture

Both scripts share:
- Identical `STOP_WORDS` frozenset (60 tokens)
- Identical `_TOKEN_RE = re.compile(r"[a-z0-9]+")`
- Identical `_INDEX_RE` regex
- Identical `tokenize()` function (same logic, same minimum length of 3 chars: `len(word) > 2`)
- Same basic scoring weights: title exact = 2, tag exact = 3, prefix = 1

### Key Differences

| Aspect | `memory_retrieve.py` | `memory_candidate.py` |
|---|---|---|
| **Purpose** | Select memories to inject into Claude's context on every user prompt | Select the best existing entry to update/delete during a write operation |
| **Input** | User prompt text (from hook stdin JSON) | `--new-info` CLI argument (new information being saved) |
| **Scope** | All categories in index | Single specified category only |
| **Tag lowercasing at parse** | Yes: `t.strip().lower()` | No: `t.strip()` only (tags keep original case) |
| **Tag comparison** | `prompt_words & entry_tags` (already lowercase) | `new_info_tokens & {t.lower() for t in entry["tags"]}` (lowercase at match time) |
| **Description scoring** | Yes (`score_description()` with cap at 2) | No description scoring at all |
| **Recency bonus** | Yes (+1 for entries updated within 30 days) | No recency check |
| **Category priority** | Yes: DECISION=1 ... SESSION_SUMMARY=6 (tie-breaking) | No category priority (tie-breaks on path string for determinism) |
| **Score threshold** | None (any score > 0 qualifies) | Minimum score of 3 to be a candidate |
| **Output count** | Top `max_inject` (default 5, max 20) | Top 1 only |
| **Retired entries** | Excluded (deep check reads JSON) | Not checked (assumes index is clean) |
| **Deep check limit** | Top 20 candidates | N/A (no deep check) |
| **Result format** | Formatted text for context injection | JSON with candidate details and structural CUD recommendation |

### Tag Lowercasing Discrepancy

In `memory_retrieve.py`, tags are lowercased at parse time and stored as a set:

```python
tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()]
# ...
"tags": set(tags),
```

In `memory_candidate.py`, tags are stored with original case from the index:

```python
tags = [t.strip() for t in tags_str.split(",") if t.strip()]
# ...
"tags": tags,
```

But at score time, `memory_candidate.py` lowercases on-the-fly:

```python
entry_tags_lower = {t.lower() for t in entry["tags"]}
tag_matches = new_info_tokens & entry_tags_lower
```

The net result is the same behavior (case-insensitive tag matching), but the implementation is inconsistent. The `memory_candidate.py` approach is slightly less efficient (creates a new set on every `score_entry` call) and could diverge if someone changes the code without noticing the two-step lowercasing.

### Score Threshold Difference

`memory_candidate.py` has an explicit minimum score of 3 to declare a candidate:

```python
if scored and scored[0][0] >= 3:
    candidate_score = scored[0][0]
    candidate = scored[0][1]
```

A score of 3 means at minimum: one exact tag match OR one exact title match plus one prefix match (2 + 1). If no entry reaches 3, the result is `CREATE` (new entry).

`memory_retrieve.py` has no minimum threshold. Any score > 0 qualifies an entry for potential injection. This is intentional: the retrieval use case wants to surface anything plausibly related, while the write use case needs high confidence before overwriting an existing record.

---

## 5. Sorting and Selection

### Pass 1: Text Score Sort

After all entries are scored, results with score > 0 are collected:

```python
scored = []
for entry in entries:
    text_score = score_entry(prompt_words, entry)
    cat_desc_tokens = desc_tokens_by_cat.get(entry["category"], set())
    if cat_desc_tokens:
        text_score += score_description(prompt_words, cat_desc_tokens)
    if text_score > 0:
        priority = CATEGORY_PRIORITY.get(entry["category"], 10)
        scored.append((text_score, priority, entry))

scored.sort(key=lambda x: (-x[0], x[1]))
```

Sort key: `(-text_score, category_priority)` -- highest score first, ties broken by category priority (lower number = higher priority).

**Category priority values:**
- DECISION: 1 (highest priority in tie-break)
- CONSTRAINT: 2
- PREFERENCE: 3
- RUNBOOK: 4
- TECH_DEBT: 5
- SESSION_SUMMARY: 6 (lowest priority in tie-break)
- Unknown categories: 10

Ties in text score are resolved by category, not by recency or alphabet. A DECISION and a SESSION_SUMMARY with the same text score will always rank DECISION first.

### Pass 2: Deep Check (Top 20 Only)

```python
_DEEP_CHECK_LIMIT = 20

for text_score, priority, entry in scored[:_DEEP_CHECK_LIMIT]:
    file_path = project_root / entry["path"]
    is_retired, is_recent = check_recency(file_path)
    if is_retired:
        continue  # dropped entirely
    final_score = text_score + (1 if is_recent else 0)
    final.append((final_score, priority, entry))

# Entries beyond limit are included without deep check
for text_score, priority, entry in scored[_DEEP_CHECK_LIMIT:]:
    final.append((text_score, priority, entry))
```

**Deep check limit implications:**
- Only the top 20 text-scored entries have their JSON files read. This bounds the I/O cost: at most 20 file reads per prompt.
- Entries ranked 21st or lower are included in `final` without recency bonus and without retired exclusion. A retired entry ranked 21st would not be excluded.
- The recency bonus (+1) can re-sort entries 1-20 relative to each other after the deep check. An entry initially ranked 5th with score 4 and a recency bonus becomes score 5, which can overtake an entry initially ranked 2nd with score 4 and no recency bonus.

### Final Sort and Cutoff

```python
final.sort(key=lambda x: (-x[0], x[1]))
top = final[:max_inject]
```

The final sort uses the same key. `max_inject` defaults to 5 (from config, clamped to [0, 20]).

**Clamp behavior for max_inject:**

```python
max_inject = max(0, min(20, int(raw_inject)))
```

- Negative values are clamped to 0 (result: no injection).
- Values over 20 are clamped to 20.
- Non-integer values (e.g., `"5.7"`) are converted with `int()`, which truncates.
- Non-parseable values (e.g., `"all"`, `null`) trigger a warning and fall back to 5.
- `OverflowError` is caught, which handles values like `float("inf")`.

---

## 6. Worked Examples

### Example 1: Direct Keyword Hit (High Confidence)

**Setup:**

User prompt: `"Why did we decide to use PostgreSQL instead of MySQL?"`

After tokenization (lowercased, stop words removed, min length 3):
- Removed stop words: `"why"`, `"we"`, `"to"`, `"use"`, `"instead"`, `"of"`
- Wait: `"instead"` and `"of"` -- check: `"instead"` (7 chars) is NOT in the stop word list. `"of"` IS in the stop word list.
- `"why"` IS in stop words, `"we"` IS in stop words.

Prompt tokens: `{"decide", "postgresql", "instead", "mysql"}`

Note: `"use"` is in STOP_WORDS. `"why"` is in STOP_WORDS. `"we"` is in STOP_WORDS. `"to"` is in STOP_WORDS. `"instead"` is NOT in STOP_WORDS.

Prompt tokens: `{"decide", "postgresql", "instead", "mysql"}`

**Index entries (simplified):**

```
Entry A: - [DECISION] Use PostgreSQL over MySQL for persistence -> .claude/memory/decisions/abc.json #tags:postgresql,mysql,database,persistence
Entry B: - [CONSTRAINT] MySQL version must be >= 8.0 -> .claude/memory/constraints/def.json #tags:mysql,version
Entry C: - [SESSION_SUMMARY] Session: initial database setup -> .claude/memory/sessions/ghi.json
```

**Scoring Entry A:**

- Title tokens: `tokenize("Use PostgreSQL over MySQL for persistence")` = `{"postgresql", "mysql", "persistence"}` (removed: `"use"` is stop word, `"over"`, `"for"` are stop words)
- Tags: `{"postgresql", "mysql", "database", "persistence"}`
- Exact title matches: `{"decide", "postgresql", "instead", "mysql"}` & `{"postgresql", "mysql", "persistence"}` = `{"postgresql", "mysql"}` -> +4 points
- Exact tag matches: remaining tokens = `{"decide", "instead"}`, tags = `{"postgresql", "mysql", "database", "persistence"}`. Intersection of remaining tokens and tags: none (since `"postgresql"` and `"mysql"` are already in `already_matched`). Wait, re-checking:
  - `exact_title = {"postgresql", "mysql"}`, score = 4
  - `exact_tags`: `prompt_words & entry_tags` = `{"decide", "postgresql", "instead", "mysql"}` & `{"postgresql", "mysql", "database", "persistence"}` = `{"postgresql", "mysql"}` -> +6 points
  - `already_matched = exact_title | exact_tags = {"postgresql", "mysql"}`
  - Prefix check on `{"decide", "instead"}` (remaining unmatched, each >= 4 chars): `"decide"` -- does any target start with `"decide"`? No. `"instead"` -- does any target start with `"instead"`? No.
  - **Entry A total: 4 (title) + 6 (tags) = 10 points**

**Scoring Entry B:**

- Title tokens: `tokenize("MySQL version must be >= 8.0")` -> `"mysql"`, `"version"`, `"must"` is stop word, `"8"` is 1 char, discarded. Tokens: `{"mysql", "version"}`
- Tags: `{"mysql", "version"}`
- Exact title: `{"decide", "postgresql", "instead", "mysql"}` & `{"mysql", "version"}` = `{"mysql"}` -> +2
- Exact tags: `{"decide", "postgresql", "instead", "mysql"}` & `{"mysql", "version"}` = `{"mysql"}` -> +3
- `already_matched = {"mysql"}`
- Prefix on `{"decide", "postgresql", "instead"}`: no targets start with these
- **Entry B total: 2 + 3 = 5 points**

**Scoring Entry C:**

- Title tokens: `tokenize("Session: initial database setup")` -> `{"session", "initial", "database", "setup"}`
- Tags: empty
- Exact title: `{"decide", "postgresql", "instead", "mysql"}` & `{"session", "initial", "database", "setup"}` = empty -> 0
- **Entry C total: 0 points** (excluded from results)

**Description scoring (assuming default config descriptions):**

- `"decision"` description: `"Architectural and technical choices with rationale -- why X was chosen over Y"` -> tokens: `{"architectural", "technical", "choices", "rationale", "chosen", "over"}` (after removing stop words like `"why"`, `"was"`, `"with"`)
  - Wait, `"was"` is a stop word. `"why"` is a stop word. `"and"` is a stop word. `"with"` is a stop word. `"over"` is not a stop word (`len("over") = 4, "over"` not in STOP_WORDS). Let me re-check: `"over"` is not in the STOP_WORDS list.
  - Description tokens for DECISION: `{"architectural", "technical", "choices", "rationale", "why"...}` -- actually `"why"` IS in STOP_WORDS so it's removed. Let me compute carefully: tokens from `"Architectural and technical choices with rationale -- why X was chosen over Y"`:
    - `"architectural"` (ok), `"and"` (stop), `"technical"` (ok), `"choices"` (ok), `"with"` (stop), `"rationale"` (ok), `"why"` (stop), `"x"` (1 char, dropped), `"was"` (stop), `"chosen"` (ok), `"over"` (ok, 4 chars, not in stop words), `"y"` (1 char, dropped)
  - Description tokens: `{"architectural", "technical", "choices", "rationale", "chosen", "over"}`
  - Prompt tokens `{"decide", "postgresql", "instead", "mysql"}` vs description tokens: no exact matches.
  - Prefix: `"decide"` (6 chars): does any description token start with `"decide"`? No. `"postgresql"` (10 chars): no. Others: no.
  - Description score for DECISION: 0

- Description score adds 0 for both Entry A and B in this example.

**Final ranking (before recency):**

| Rank | Entry | Score | Priority |
|---|---|---|---|
| 1 | Entry A (DECISION) | 10 | 1 |
| 2 | Entry B (CONSTRAINT) | 5 | 2 |

If Entry A was updated 15 days ago, it gets +1 recency -> score 11. Final output includes both (with default max_inject=5).

---

### Example 2: Description Scoring Dominance (Low Confidence)

This example shows how description scoring can inject entries without any direct keyword relevance.

**Setup:**

User prompt: `"What are the next steps after the session?"`

After tokenization: `"what"` (stop), `"are"` (stop), `"the"` (stop), `"next"` (ok, 4 chars), `"steps"` (ok, 5 chars), `"after"` (ok, 5 chars), `"the"` (stop), `"session"` (ok, 7 chars).

Prompt tokens: `{"next", "steps", "after", "session"}`

**Index entries:**

```
Entry A: - [SESSION_SUMMARY] Initial project setup session -> .claude/memory/sessions/aaa.json
Entry B: - [RUNBOOK] Fix Docker container startup failure -> .claude/memory/runbooks/bbb.json #tags:docker,container,startup
```

**Scoring Entry A (SESSION_SUMMARY):**

- Title tokens: `{"initial", "project", "setup", "session"}`
- Tags: empty
- Exact title: `{"next", "steps", "after", "session"}` & `{"initial", "project", "setup", "session"}` = `{"session"}` -> +2
- Exact tags: none
- Prefix: unmatched tokens `{"next", "steps", "after"}` vs title tokens `{"initial", "project", "setup"}`:
  - `"next"` (4 chars): does any target start with `"next"`? No.
  - `"steps"` (5 chars): `"setup".startswith("steps")`? No. `"steps".startswith("steps")`? Yes -- but `"steps"` is not in the target set. Target is `{"initial", "project", "setup"}`. No match.
  - `"after"` (5 chars): no target starts with `"after"`.
- Base score: 2

**Description score for SESSION_SUMMARY:**

Default description: `"High-level summary of work done in a coding session, including goals, outcomes, and next steps"`

Tokens: `{"high", "level", "summary", "work", "done", "coding", "session", "including", "goals", "outcomes", "next", "steps"}` (removing stop words: `"of"`, `"in"`, `"a"`, `"and"`)

Wait, `"high"` is 4 chars and not a stop word. `"level"` is ok. `"done"` is 4 chars (not a stop word). Let me verify `"and"` is a stop word (yes). `"in"` is a stop word (yes). `"a"` is a stop word (yes).

Description tokens: `{"high", "level", "summary", "work", "done", "coding", "session", "including", "goals", "outcomes", "next", "steps"}`

Prompt tokens: `{"next", "steps", "after", "session"}`

Exact matches: `{"next", "steps", "after", "session"}` & `{"high", "level", "summary", "work", "done", "coding", "session", "including", "goals", "outcomes", "next", "steps"}` = `{"next", "steps", "session"}` -> score = 3.0

Prefix: remaining unmatched: `{"after"}`. Does any description token start with `"after"`? No.

Description score: `min(2, int(3.0))` = `min(2, 3)` = **2**

**Entry A total: 2 (title) + 2 (description) = 4 points**

**Scoring Entry B (RUNBOOK):**

- Title tokens: `{"fix", "docker", "container", "startup", "failure"}`
- Tags: `{"docker", "container", "startup"}`
- Exact title: `{"next", "steps", "after", "session"}` & title tokens = empty -> 0
- Exact tags: empty -> 0
- Prefix: all 4 prompt tokens vs title+tags: none start with `"next"`, `"step"`, `"after"`, or `"session"`.
- Base score: 0

Default RUNBOOK description: `"Step-by-step procedures for diagnosing and fixing specific errors or issues"`

Tokens: `{"step", "procedures", "diagnosing", "fixing", "specific", "errors", "issues"}` (removing: `"by"`, `"for"`, `"and"`, `"or"`)

Wait, `"step"` is 4 chars (not a stop word). `"by"` is a stop word (yes). `"for"` is a stop word (yes). `"and"` is stop word.

Exact: `{"next", "steps", "after", "session"}` & `{"step", "procedures", "diagnosing", "fixing", "specific", "errors", "issues"}` = empty

Prefix: `"next"` (4 chars) does not prefix any description token. `"step"` would match but `"steps"` (5 chars) -- does `"step"` start with `"steps"`? No, the check is `target.startswith(pw)`, so `"step".startswith("steps")` = False. But `"step".startswith("step")` = True, and `"step"` IS in the description token set.

Wait, prompt token is `"steps"` (5 chars), target is `"step"` (4 chars). `"step".startswith("steps")` = False. The prefix check is always `target.startswith(prompt_word)`. A longer prompt word does NOT match a shorter target. So `"steps"` from the prompt does not prefix-match `"step"` in the description.

What about `"next"` (4 chars)? Description has no token starting with `"next"`.

Description score for RUNBOOK: 0. Entry B base score is 0, so Entry B is excluded.

**Outcome:**

Only Entry A qualifies (score 4). This shows that the SESSION_SUMMARY description is rich with common words (`"summary"`, `"session"`, `"goals"`, `"outcomes"`, `"next"`, `"steps"`, `"coding"`) that match many user prompts even when the prompt is not asking about a specific memory entry. The description bonus effectively makes all SESSION_SUMMARY entries more likely to appear whenever the user asks about work summaries or next steps.

---

### Example 3: Prefix Match and Score Threshold (Candidate Selection)

This demonstrates `memory_candidate.py`'s score threshold of 3.

**Setup:**

New info being saved (via `--new-info`): `"Removed the global lock on migrations"`

After tokenization: `"removed"` (7 chars, not stop word), `"global"` (6 chars), `"lock"` (4 chars), `"migrations"` (10 chars).

Prompt tokens: `{"removed", "global", "lock", "migrations"}`

**Index entries (TECH_DEBT category only):**

```
Entry A: - [TECH_DEBT] Global migration lock causes startup delays -> .claude/memory/tech-debt/xyz.json #tags:lock,migration,startup
Entry B: - [TECH_DEBT] Defer schema migration to v2 -> .claude/memory/tech-debt/def.json #tags:schema,migration
```

**Scoring Entry A:**

- Title tokens: `{"global", "migration", "lock", "causes", "startup", "delays"}`
- Tags (lowercased at score time in candidate.py): `{"lock", "migration", "startup"}`

Exact title: `{"removed", "global", "lock", "migrations"}` & `{"global", "migration", "lock", "causes", "startup", "delays"}` = `{"global", "lock"}` -> +4

Wait, `"migrations"` vs `"migration"` -- these are different tokens. `"migrations"` is NOT the same as `"migration"`. The exact match fails for these.

Exact tags: `new_info_tokens & entry_tags_lower` = `{"removed", "global", "lock", "migrations"}` & `{"lock", "migration", "startup"}` = `{"lock"}` -> +3

`already_matched = {"global", "lock"} | {"lock"} = {"global", "lock"}`

Prefix check on `{"removed", "migrations"}` (remaining, both >= 4 chars):
- `"removed"` (7 chars): does `"global".startswith("removed")`? No. Does `"migration".startswith("removed")`? No. Does `"lock".startswith("removed")`? No. Does `"causes".startswith("removed")`? No. Does `"startup".startswith("removed")`? No. Does `"delays".startswith("removed")`? No. No hit.
- `"migrations"` (10 chars): does any target start with `"migrations"`? Targets: `{"global", "migration", "lock", "causes", "startup", "delays", "startup"}`. `"migration".startswith("migrations")` = False (migration is shorter than migrations). No hit.

**Entry A total: 4 (title) + 3 (tags) = 7 points** -- exceeds threshold of 3, becomes the candidate.

**Scoring Entry B:**

- Title tokens: `{"defer", "schema", "migration"}`
- Tags: `{"schema", "migration"}`

Exact title: `{"removed", "global", "lock", "migrations"}` & `{"defer", "schema", "migration"}` = empty -> 0

Exact tags: `{"removed", "global", "lock", "migrations"}` & `{"schema", "migration"}` = empty (no exact matches; `"migration"` != `"migrations"`) -> 0

Prefix on all 4 tokens (none matched):
- `"removed"` (7 chars): no target starts with it
- `"global"` (6 chars): no target starts with it
- `"lock"` (4 chars): does `"defer"` start with `"lock"`? No. Does `"schema"` start with `"lock"`? No. Does `"migration"` start with `"lock"`? No. No hit.
- `"migrations"` (10 chars): does `"migration"` start with `"migrations"`? No.

**Entry B total: 0 points** -- excluded from results.

**Outcome:** Entry A is selected as the candidate with score 7. The system recommends UPDATE_OR_DELETE (since tech_debt allows deletion). The suffix difference (`"migration"` vs `"migrations"`) costs Entry B the exact match on every check but the prefix check also fails because prefix direction requires the prompt token to be the shorter prefix.

---

## 7. Strengths and Weaknesses

### Strengths

**1. Zero dependencies, fast execution**

The entire retrieval pipeline runs in milliseconds using only stdlib. No vector embeddings, no model calls, no network requests. For a hook that runs on every user prompt, this is essential.

**2. Predictable and auditable**

The scoring is fully deterministic and transparent. A developer can manually trace why any particular entry was or was not retrieved. There are no probabilistic components.

**3. Tag system extends coverage without increasing title length**

Tags provide a controlled vocabulary layer. A title like "Use Pydantic v2 for validation" can be tagged with `api,schema,validation,models,v2` to surface it for a much broader range of prompts. This is the right architectural response to the limitations of title-only keyword matching.

**4. Category priority prevents low-value category flooding**

SESSION_SUMMARY entries (which are plentiful) rank after DECISIONs and CONSTRAINTs in tie situations. This is appropriate because decisions and constraints are typically more actionable than past session notes.

**5. Recency bonus is subtle and additive**

The +1 recency bonus does not dominate. It can only change rankings when entries have the same text score. A very old but highly relevant entry (score 10) will still outrank a recent but weakly matching entry (score 2 + 1 = 3).

**6. Description cap at 2 prevents category bleed**

Without the cap, a category with a description that happens to use many common technical terms would inflate scores for all entries in that category equally. The cap of 2 limits the maximum bias any category description can introduce.

**7. Graceful degradation**

If the index file is missing, it attempts a rebuild. If the config is malformed, it uses defaults. If a JSON file cannot be read during deep check, the entry is dropped rather than crashing.

### Weaknesses

**1. No synonym or semantic understanding**

The single largest failure mode. A prompt asking `"How do we handle rate limiting?"` will not match an entry titled `"Throttling policy for API calls"` tagged with `api,throttle,policy`. `"rate"` and `"limiting"` do not appear in that title or tags; `"throttle"` and `"throttling"` are different tokens. The system has zero awareness of semantic equivalence.

More examples:
- Prompt: `"authentication"` vs memory entry tagged `"auth"` -> no match (neither prefixes the other in the right direction; `"auth"` would need to be the prefix, not `"authentication"`)
- Prompt: `"database schema"` vs entry titled `"DB structure constraints"` -> `"database"` and `"schema"` do not appear in the title; `"structure"` and `"constraints"` do not match

**2. Prefix direction is one-way (prompt must be shorter)**

The prefix check only fires when the prompt word is a prefix of the entry word. This means:
- Prompt: `"config"` -> matches entry tag `"configuration"` (correct behavior, `"configuration".startswith("config")`)
- Prompt: `"configuration"` -> does NOT match entry tag `"config"` (because `"config".startswith("configuration")` = False)

Users who type full words will miss entries with abbreviated tags. Entry tags created by the system tend to be shorter and more specific, so long-form user queries will often fail the prefix check.

**3. Description bonus creates false positives via category bleed**

As shown in Example 2, an entry like "Session: initial database setup" that has no textual relationship to a prompt about "next steps after the session" still scores 4 points: 2 from the title `"session"` match and 2 from the SESSION_SUMMARY description. If `max_inject=5`, this entry will appear in context even though the user's intent was almost certainly unrelated.

The problem is that the description bonus is category-wide. Every SESSION_SUMMARY entry gets the same description score. In a memory store with 50 session summaries, all 50 get the same +2 description bonus whenever the user asks anything mentioning "session", "summary", "coding", "goals", "steps", or "outcomes". This effectively inflates the rank of all SESSION_SUMMARY entries simultaneously, which could flood the context limit with irrelevant session notes.

**4. Tag system requires maintenance and discipline**

Tags are only effective if they are populated and use the same vocabulary as user prompts. Entries created without tags rely entirely on title word matching. If the SKILL.md orchestration does not consistently tag entries, the +3 tag bonus never fires in practice, reducing the scoring system to only title-matching.

There is also no tag taxonomy or ontology enforcement. Two entries about Docker could have tags `"docker"`, `"Docker"`, `"DOCKER"`, or `"docker-compose"`. The first three are collapsed by lowercasing, but `"docker-compose"` becomes `"docker"` and `"compose"` as separate tokens at parse time (since hyphens are not captured by `[a-z0-9]+`). Wait -- actually tags are stored in the index as-is (e.g., `#tags:docker-compose`) and the tag string `"docker-compose"` is split by comma only. The tag token is stored as `"docker-compose"`. When compared against prompt tokens, the prompt token `"docker"` would need to exactly match or prefix `"docker-compose"`, which it does: `"docker-compose".startswith("docker")` = True. So this case works, but it is accidental.

**5. The `int()` truncation in `score_description` loses half-points**

`min(2, int(score))` truncates rather than rounds. A score of 1.5 (one exact + one prefix hit) becomes 1, not 2. This means the description score can appear lower than expected when there is a mix of exact and prefix matches. There is no practical justification for truncation over rounding here -- it is likely unintentional.

**6. 2-character tokens are always dropped**

Common technical abbreviations like `"db"`, `"ui"`, `"ci"`, `"cd"`, `"ml"`, `"ai"`, `"vm"`, `"k8"` (from `k8s` the `s` joins) are dropped by the minimum length filter. A user asking `"How did we configure the CI pipeline?"` loses `"ci"` completely. The entry titled `"CI/CD pipeline configuration"` tokenizes to `{"pipeline", "configuration"}` (since `"ci"` and `"cd"` are 2 chars each). If the entry was tagged `ci,pipeline,config`, the `"ci"` tag (2 chars) would also be dropped at parse time by the `len(word) > 2` check in `tokenize()`.

Wait -- actually tags are stored in the index as comma-separated strings and then run through `tokenize()` for prefix matching but NOT for exact matching. Let me re-examine:

```python
entry_tags = entry["tags"]  # set of strings, each tag is the whole tag string

# Exact tag matches
exact_tags = prompt_words & entry_tags
```

Prompt tokens are produced by `tokenize()` (min length 3). Entry tags are the raw tag strings stored in the index (e.g., `{"ci", "pipeline"}`). The exact tag match is a set intersection between tokenized prompt words (all >= 3 chars) and raw tag strings. Since `"ci"` is in `entry_tags` but no prompt token can be 2 chars or less (they're all filtered by `tokenize()`), the intersection will never include `"ci"`. Short tags are permanently unreachable via exact matching.

For prefix matching:
```python
for pw in prompt_words - already_matched:
    if len(pw) >= 4:
        if any(target.startswith(pw) for target in combined_targets):
```

Prompt words are already >= 3 chars; prefix check adds >= 4. `"ci"` could only be matched if a prompt word of >= 4 chars starts with `"ci"`. `"cicd"` (4 chars) would match tag `"ci"` if `"ci".startswith("cicd")` -- but that's false (shorter string cannot start with longer string). There is no way for a short tag to score points, ever.

**7. Entries ranked beyond 20 skip the retired check**

Entries ranked 21st and beyond in text score are appended to `final` without reading their JSON files. If these entries have `record_status: "retired"`, they will not be excluded. In practice this only matters if a retired entry scores higher than the 20 non-retired entries below the _DEEP_CHECK_LIMIT, which should be rare but is possible in large memory stores. The comment in the code acknowledges this as an intentional performance trade-off:

```python
# Also include entries beyond deep-check limit (no recency bonus, assume not retired)
```

**8. No feedback loop or learning**

The scoring weights (2/3/1) are hard-coded and never adjusted. There is no mechanism to learn that users always want RUNBOOK entries when they ask about errors, or that a specific tag is consistently relevant. The weights were presumably chosen by intuition and remain fixed.

**9. Prompt tokenization has high discard rate for short, focused prompts**

A prompt like `"How to fix this?"` after tokenization becomes empty (`"how"` stop word, `"to"` stop word, `"fix"` stop word, `"this"` stop word). The code handles this:

```python
if not prompt_words:
    sys.exit(0)
```

But it means that many natural user prompts (especially imperative commands and short questions) produce no results. Prompts shorter than 10 characters are also pre-filtered:

```python
if len(user_prompt.strip()) < 10:
    sys.exit(0)
```

**10. Tag scoring can dominate title scoring on multi-tag entries**

An entry tagged with 5 tags, where 3 of them match prompt words, scores 9 points from tags alone. A more precisely titled entry matching 2 words scores only 4 points. For example:

- Entry A: title "Database connection setup" (score: 2 + 2 = 4), tags: `database,connection,setup,postgres,pool,retry,timeout` (if 3 prompt words match tags: +9)
- Entry B: title "Configure PostgreSQL connection pooling" (score: exact matches for all 3 prompt words: 6), no tags

With prompt tokens `{"configure", "postgresql", "connection", "pooling"}`:
- Entry A tags score: `{"database", "connection"}` matches 1 from `connection` -> +3 from tags. Title `"database", "connection", "setup"` -> `"connection"` matches -> +2. Total = 5.
- Entry B title score: `{"configure", "postgresql", "connection", "pooling"}` all match -> +8 (4 tokens x 2). Total = 8.

In this case the title-rich entry wins. But if Entry A had many more tag matches than this example, tags could dominate. The relative weight (3 vs 2) means 1 tag match outweighs 1 title match. In high-cardinality tag scenarios this could produce spurious high scores.

---

## Summary Table

| Property | Value |
|---|---|
| Algorithm type | Keyword set intersection |
| Prompt tokenization | Regex `[a-z0-9]+`, lowercase, min 3 chars, 60 stop words removed, returns set |
| Exact title match weight | +2 per matching token |
| Exact tag match weight | +3 per matching token |
| Prefix match weight | +1 per prompt token (>= 4 chars) prefixing any title/tag token |
| Description exact weight | +1 per matching token (capped, shared per category) |
| Description prefix weight | +0.5 per prefix match (capped, shared per category) |
| Description cap | `min(2, int(score))` -- truncates, not rounds |
| Recency bonus | +1 if `updated_at` within 30 days |
| Deep check limit | Top 20 entries only |
| Minimum threshold (retrieve) | None (score > 0 qualifies) |
| Minimum threshold (candidate) | Score >= 3 |
| Max results (retrieve) | `max_inject` from config, clamped [0, 20], default 5 |
| Max results (candidate) | Top 1 |
| Tie-breaking (retrieve) | Category priority (DECISION=1 ... SESSION_SUMMARY=6) |
| Tie-breaking (candidate) | Path string (alphabetical, for determinism) |
| Semantic understanding | None |
| Short-token handling | Tokens <= 2 chars silently dropped (e.g., `ci`, `db`, `ui`) |
