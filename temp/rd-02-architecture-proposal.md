# Retrieval Architecture Proposal v2.0

**Date:** 2026-02-20
**Author:** architect (systems architect)
**Status:** PROPOSAL -- pending adversarial and feasibility review
**Inputs:** Research synthesis (rd-01), current codebase, external model validation (Gemini 3.1 Pro)

---

## Section 1: Architecture Overview

### High-Level System Diagram

```
                         ┌─────────────────────────────────┐
                         │        Claude Code Session       │
                         └──────┬──────────────┬───────────┘
                                │              │
                    ┌───────────▼──────┐  ┌────▼────────────────┐
                    │  Path A: Hook    │  │  Path B: On-Demand   │
                    │  (Auto-inject)   │  │  (/memory:search)    │
                    │  UserPromptSubmit│  │  Skill invocation    │
                    └───────┬──────────┘  └────┬────────────────┘
                            │                  │
                            ▼                  ▼
                    ┌───────────────────────────────────┐
                    │      Shared FTS5 BM25 Engine      │
                    │   sqlite3.connect(":memory:")     │
                    │                                   │
                    │  ┌─────────────────────────────┐  │
                    │  │ FTS5 Virtual Table           │  │
                    │  │ title (w=5.0) | tags (w=3.0)│  │
                    │  │ body  (w=1.0) | id UNINDEXED│  │
                    │  │ tokenize='porter unicode61'  │  │
                    │  └─────────────────────────────┘  │
                    │                                   │
                    │  Index populated from:             │
                    │  - JSON memory files on disk       │
                    │  - Body = concatenated text fields  │
                    └───────┬──────────────┬────────────┘
                            │              │
                    ┌───────▼──────┐  ┌────▼────────────────┐
                    │ High Thresh. │  │  Low Threshold       │
                    │ max 2-3 hits │  │  max 10 hits         │
                    │              │  │  Progressive discl.  │
                    └───────┬──────┘  └────┬────────────────┘
                            │              │
                    ┌───────▼──────┐  ┌────▼────────────────┐
                    │ Inject into  │  │ Return compact list  │
                    │ <memory-ctx> │  │ LLM reads full files │
                    └──────────────┘  └─────────────────────┘
```

### How This Differs from claude-mem and Current claude-memory

| Aspect | claude-mem | Current claude-memory | This Proposal |
|--------|-----------|----------------------|---------------|
| **Engine** | ChromaDB vectors (FTS5 dead code) | Keyword matching on title+tags | FTS5 BM25 (body content indexed) |
| **Auto-inject** | Recency-only (SessionStart) | Keyword scoring (UserPromptSubmit) | BM25 scoring with high threshold (UserPromptSubmit) |
| **On-demand** | 4 MCP tools, 3-layer progressive | None | Skill-based, 2-layer progressive |
| **Dependencies** | ChromaDB, ONNX, npm | stdlib only | stdlib only (sqlite3 built-in) |
| **Processes** | Daemon (chroma-mcp) | None | None |
| **Body content** | Full text indexed in Chroma | Not indexed (title+tags only) | Full text indexed in FTS5 |
| **Transcript** | Not used for retrieval | Not used | Last 2-3 user turns for query enrichment |

**Key design principle:** We occupy the space between claude-mem (too complex, fragile infrastructure) and current claude-memory (too simple, low precision). FTS5 BM25 gives us 80% of the benefit of vector search at 0% of the infrastructure cost.

---

## Section 2: Auto-Inject Path (UserPromptSubmit Hook)

### FTS5 BM25 Engine: Build, Populate, Query

#### Table Creation

```python
import sqlite3

def build_fts_index(memories: list[dict]) -> sqlite3.Connection:
    """Build in-memory FTS5 index from memory file data.

    Args:
        memories: list of dicts with keys: id, title, tags, body, category,
                  path, record_status, updated_at
    Returns:
        sqlite3.Connection with populated FTS5 table
    """
    conn = sqlite3.connect(":memory:")

    # Create FTS5 table with Porter stemmer
    # 'id' is UNINDEXED -- used for lookup, not for text matching
    # 'path' is UNINDEXED -- stored for result output
    # 'category' is UNINDEXED -- used for filtering/tiebreaking
    # 'updated_at' is UNINDEXED -- used for recency filtering
    conn.execute("""
        CREATE VIRTUAL TABLE memories USING fts5(
            title, tags, body,
            id UNINDEXED, path UNINDEXED,
            category UNINDEXED, updated_at UNINDEXED,
            tokenize='porter unicode61'
        );
    """)

    for mem in memories:
        conn.execute(
            "INSERT INTO memories(title, tags, body, id, path, category, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (mem["title"], mem["tags"], mem["body"],
             mem["id"], mem["path"], mem["category"], mem["updated_at"])
        )

    return conn
```

**Why in-memory, not disk-cached:**
- Benchmarked: 500 memories = ~4ms to build, queries <0.5ms.
- Gemini 3.1 Pro confirms: "At <35ms for 1,000 files, the I/O cost of writing/reading a temp SQLite file outweighs the benefits and introduces locking risks."
- Eliminates concurrency bugs when multiple Claude sessions run simultaneously.
- No cache invalidation logic needed.

**Decision: Always rebuild in-memory. No disk cache.**

#### Body Content Extraction from JSON Memories

Each memory category has different content fields. The body column concatenates all
text-valued fields from the `content` object, providing a unified search surface.

```python
# Category-specific text fields to extract for FTS5 body
BODY_FIELDS = {
    "session_summary": ["goal", "outcome", "completed", "in_progress",
                        "blockers", "next_actions", "key_changes"],
    "decision":        ["context", "decision", "rationale", "consequences"],
    "runbook":         ["trigger", "symptoms", "steps", "verification",
                        "root_cause", "environment"],
    "constraint":      ["rule", "impact", "workarounds"],
    "tech_debt":       ["description", "reason_deferred", "impact",
                        "suggested_fix", "acceptance_criteria"],
    "preference":      ["topic", "value", "reason"],
}

def extract_body(data: dict) -> str:
    """Extract searchable body text from a memory JSON file.

    Concatenates all text fields from the content object.
    List fields are joined with spaces. Nested dicts are skipped.
    Total body capped at 2000 chars to keep FTS5 index lean.
    """
    category = data.get("category", "")
    content = data.get("content", {})
    fields = BODY_FIELDS.get(category, [])

    parts = []
    for field in fields:
        value = content.get(field)
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    # Handle alternatives: [{option, rejected_reason}]
                    for v in item.values():
                        if isinstance(v, str):
                            parts.append(v)

    body = " ".join(parts)
    return body[:2000]  # Cap to prevent index bloat
```

**Why 2000 chars:** At 500 memories * 2KB average body, the FTS5 index stays under ~1MB
in memory. Bodies larger than 2000 chars add diminishing returns for keyword matching
while increasing build time.

#### Query Construction

```python
import re

# Stop words -- same set as current memory_retrieve.py, shared constant
STOP_WORDS = frozenset({...})  # existing set from memory_retrieve.py

# FTS5 reserved words that must not appear as bare tokens in MATCH
_FTS5_RESERVED = frozenset({"and", "or", "not", "near"})

def build_fts_query(prompt_tokens: list[str]) -> str | None:
    """Build a safe FTS5 MATCH query from sanitized tokens.

    Returns OR-joined token string, or None if no valid tokens.
    FTS5 reserved words are double-quoted to escape them.
    """
    safe_tokens = []
    for token in prompt_tokens:
        if token in _FTS5_RESERVED:
            safe_tokens.append(f'"{token}"')
        else:
            safe_tokens.append(token)

    if not safe_tokens:
        return None

    return " OR ".join(safe_tokens)


def tokenize_for_query(text: str) -> list[str]:
    """Extract query tokens from user text.

    Strips punctuation, lowercases, removes stop words.
    Only alphanumeric tokens of length > 1 are kept.
    """
    words = re.findall(r'[a-z0-9]+', text.lower())
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]
```

**FTS5 Safety:** The critical risk identified by Gemini is `malformed MATCH expression`
errors from unescaped user input. Our sanitization chain:
1. `re.findall(r'[a-z0-9]+', ...)` -- strips ALL punctuation and special characters
2. Stop word removal -- removes FTS5 reserved words (`AND`, `OR`, `NOT`)
3. For the rare case where a FTS5 reserved word IS a meaningful query term, double-quote it
4. OR-join remaining tokens

This makes MATCH injection impossible -- the query contains only alphanumeric tokens
joined by `OR`.

#### Transcript Context: Parse Last 2-3 Turns

The UserPromptSubmit hook receives `transcript_path` in its input JSON. This points to
the session's JSONL file containing all messages.

```python
import os

def extract_transcript_context(transcript_path: str, max_turns: int = 3) -> list[str]:
    """Extract the last N user messages from the JSONL transcript.

    Uses reverse-seek from end of file to avoid reading entire transcript.
    Returns list of user message texts (most recent first).

    Graceful degradation: returns empty list on any error.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        return []

    try:
        # Read last ~8KB from end (enough for 3-5 turns of typical length)
        with open(transcript_path, 'rb') as f:
            try:
                f.seek(-8192, os.SEEK_END)
            except OSError:
                f.seek(0)  # File smaller than 8KB
            tail = f.read().decode('utf-8', errors='replace')

        # Parse JSONL lines from the tail
        user_messages = []
        for line in tail.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue  # First line may be truncated from seek

            if entry.get("type") != "user":
                continue

            message = entry.get("message", {})
            if message.get("role") != "user":
                continue

            content = message.get("content", "")
            if isinstance(content, str) and content.strip():
                user_messages.append(content.strip())

        # Return last N, most recent first
        return user_messages[-max_turns:][::-1]

    except (OSError, UnicodeDecodeError):
        return []  # Graceful degradation
```

**Why seek from end:** Transcript files can grow to megabytes over a long session.
Reading the full file would blow the performance budget. Seeking to the last 8KB
gives us 3-5 turns of context reliably.

**Why only user messages:** Assistant messages contain tool calls, large code blocks,
and internal reasoning that would pollute keyword matching. User messages are the
most concentrated signal for topic context.

**JSONL format stability risk:** The transcript format (`type`, `message.role`,
`message.content`) is an internal Claude Code format, not a public API. We mitigate
this with:
1. Graceful degradation -- any parse error returns empty list
2. The transcript context is ENRICHMENT only, not primary query
3. Versioned format expectations with explicit fallback

#### Query Assembly

```python
# Threshold for "short/ambiguous" prompt (below this, use transcript enrichment)
SHORT_PROMPT_TOKEN_THRESHOLD = 3

def assemble_query(user_prompt: str, transcript_path: str | None) -> str | None:
    """Build the complete FTS5 query from prompt + transcript context.

    Strategy:
    1. Tokenize current prompt (primary signal, always used)
    2. IF prompt is short/ambiguous (<= 3 meaningful tokens):
       - Tokenize last 2-3 transcript turns (enrichment signal)
       - This handles cases like "fix that", "do it", "expand on that"
    3. Deduplicate tokens
    4. Build FTS5 MATCH query

    IMPORTANT: Transcript context is ONLY added for short prompts.
    For longer prompts, adding transcript tokens causes query dilution --
    the OR-joined query becomes too broad and matches irrelevant memories.
    Example of dilution:
      Prompt: "fix the login bug"
      Transcript: "we were discussing Redis cache timeout"
      BAD query: "login OR bug OR redis OR cache OR timeout" (matches Redis memories!)
      GOOD query: "login OR bug" (matches login-related memories only)
    """
    # Primary: current prompt
    prompt_tokens = tokenize_for_query(user_prompt)

    all_tokens = list(prompt_tokens)

    # Enrichment: transcript context ONLY for short/ambiguous prompts
    if len(prompt_tokens) <= SHORT_PROMPT_TOKEN_THRESHOLD and transcript_path:
        turns = extract_transcript_context(transcript_path, max_turns=3)
        transcript_tokens = []
        for turn in turns:
            transcript_tokens.extend(tokenize_for_query(turn))

        # Deduplicate while preserving order (prompt tokens first)
        seen = set(all_tokens)
        for t in transcript_tokens:
            if t not in seen:
                seen.add(t)
                all_tokens.append(t)

    # Cap total tokens to prevent overly broad queries
    # More tokens = more OR clauses = lower precision
    MAX_QUERY_TOKENS = 15
    all_tokens = all_tokens[:MAX_QUERY_TOKENS]

    return build_fts_query(all_tokens)
```

**Why only for short prompts:** Gemini 3.1 Pro flagged query dilution as a critical
risk: blindly appending transcript tokens to a specific prompt causes FTS5 to match
unrelated memories from the conversation history. By restricting transcript enrichment
to short prompts (<= 3 tokens), we only use it when the user's intent is genuinely
ambiguous (e.g., "fix that", "do it", "what about that?").

**Why cap at 15 tokens (not 20):** With transcript enrichment active, 15 is a safer
ceiling. Empirically, FTS5 OR queries with >15 terms start matching too broadly.

#### Threshold Calibration Strategy

BM25 scores in FTS5 are **negative** (lower = better match). The exact scale depends
on corpus statistics, making a fixed threshold fragile.

**Proposed approach: Percentile-based dynamic threshold.**

```python
def apply_threshold(results: list[tuple], mode: str = "auto") -> list[tuple]:
    """Filter results by score threshold.

    Args:
        results: list of (title, path, category, score, updated_at) tuples
                 sorted by score ASC (most relevant first, most negative)
        mode: "auto" (high threshold) or "search" (low threshold)

    Returns:
        Filtered and capped result list.

    CRITICAL NOTE on BM25 negative scores:
    FTS5 bm25() returns NEGATIVE scores where more negative = better match.
    All threshold comparisons use abs() to avoid inverted logic.
    Example: score=-10.0 is BETTER than score=-2.0.
             abs(-10.0) = 10.0 > abs(-2.0) = 2.0 -- correct ordering.
    """
    if not results:
        return []

    # Convert to absolute values for threshold math (more positive = better)
    best_score_abs = abs(results[0][3])  # Best match = largest absolute value

    if mode == "auto":
        # Auto-inject: only "slam dunk" matches
        # Require absolute score quality AND relative closeness to best
        MIN_SCORE_ABS = 0.5       # Reject if best match is weak (abs < 0.5)
        RELATIVE_CUTOFF = 0.6     # Each result must be >= 60% of best
        MAX_RESULTS = 3

        if best_score_abs < MIN_SCORE_ABS:
            return []  # Best match is too weak, inject nothing

        min_acceptable = best_score_abs * RELATIVE_CUTOFF
        filtered = [r for r in results if abs(r[3]) >= min_acceptable]
        return filtered[:MAX_RESULTS]

    else:  # mode == "search"
        # On-demand: more permissive
        MIN_SCORE_ABS = 0.1
        MAX_RESULTS = 10

        if best_score_abs < MIN_SCORE_ABS:
            return []

        return results[:MAX_RESULTS]
```

**Why relative threshold:** BM25 scores are corpus-dependent. A score of -2.0 might
be excellent in a small corpus but mediocre in a large one. Using the best score as
an anchor and requiring other results to be within 60% of it naturally adapts to corpus
size and query specificity.

**Why absolute minimum:** Prevents injection when queries are so vague that even the
"best" match is barely relevant (e.g., a 2-word query that weakly matches everything).

**Calibration plan:** Phase 0 benchmark will measure actual score distributions for
known-relevant and known-irrelevant queries. The thresholds (0.6 relative, -0.5 absolute)
are starting points to be tuned empirically.

#### FTS5 Fallback: What Happens if FTS5 Is Unavailable

```python
def is_fts5_available() -> bool:
    """Check if FTS5 is available in the current Python build."""
    try:
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE VIRTUAL TABLE _fts5_test USING fts5(x);")
        conn.execute("DROP TABLE _fts5_test;")
        conn.close()
        return True
    except sqlite3.OperationalError:
        return False
```

**Fallback strategy:** If FTS5 is unavailable, fall back to the **current** keyword
matching algorithm (title + tags + description scoring) with one enhancement: also
tokenize and match against extracted body content.

This is NOT a BM25 reimplementation -- that would be over-engineering. It is the current
system extended with body content matching, which the research identified as the single
highest-leverage improvement independent of BM25.

```python
def fallback_score_entry(prompt_words: set[str], entry: dict, body_tokens: set[str]) -> int:
    """Enhanced keyword scoring with body content (FTS5 fallback).

    Same as current score_entry() but adds body matching:
    - Body word match: 1 point (capped at 3)
    """
    # Existing title+tag scoring (unchanged)
    score = score_entry(prompt_words, entry)  # from current memory_retrieve.py

    # Body content bonus (new)
    body_matches = prompt_words & body_tokens
    score += min(3, len(body_matches))

    return score
```

**Decision: FTS5 is the primary path, not optional enhancement.** The fallback exists
for edge-case environments, but we expect FTS5 to be available on all supported
platforms (Linux, WSL2, macOS). Gemini 2.5 Pro assessed FTS5 availability risk as
"very low." Verified on this WSL2 system: FTS5 with Porter stemming works perfectly.

#### Performance Budget

Measured on this WSL2 system (ext4 filesystem, not /mnt/c/):

| Operation | 500 memories | 1000 memories |
|-----------|-------------|---------------|
| JSON file read + parse | ~5-10ms | ~10-20ms |
| FTS5 index build (in-memory) | ~4ms | ~8ms |
| FTS5 query (BM25) | <0.5ms | <0.5ms |
| Transcript tail read | <1ms | <1ms |
| **Total** | **~10-15ms** | **~20-30ms** |

This is well within the 10-second hook timeout and under the 100ms responsiveness target.

**WSL2 /mnt/c/ warning:** If the project directory is on the Windows host filesystem
(`/mnt/c/...`), file I/O is 10-50x slower due to 9P protocol overhead. 500 JSON reads
could take 500ms-1s. This is a known WSL2 limitation and affects all file operations,
not just retrieval. Documentation should recommend placing projects on the Linux
filesystem.

#### Auto-Inject Payload: Title + Tags + Path Only

The auto-inject hook outputs the SAME format as the current system: title, category,
tags, and file path. It does NOT inject body content or full memory JSON.

```
<memory-context source=".claude/memory/">
- [DECISION] Chose JWT over session cookies -> .claude/memory/decisions/jwt-over-session-cookies.json #tags:auth,jwt,cookies
- [RUNBOOK] Fix OAuth2 redirect loop -> .claude/memory/runbooks/fix-oauth-redirect-loop.json #tags:auth,oauth,login
</memory-context>
```

**Why not inject body content:** Three injected memories with full body text could
consume 5,000-10,000 tokens, pushing vital system instructions out of Claude's
attention window. The hook's job is to SIGNAL which memories are relevant, not to
dump their content. If Claude needs the full details, it can read the file.

This is a form of progressive disclosure even within the auto-inject path: the hook
provides a compact pointer, and Claude decides whether to follow up.

#### Security Model: Maintained and Extended

The existing security model is preserved:

1. **Title sanitization:** Re-sanitize on read (defense-in-depth), same as current
2. **Path containment:** Resolve paths, check `relative_to(memory_root)`
3. **XML escaping:** All output attributes and values escaped
4. **Record status filtering:** Skip retired/archived during index build
5. **NEW: FTS5 query injection prevention:** Input sanitized to alphanumeric tokens only

The FTS5 engine does NOT introduce new injection vectors because:
- User input never reaches SQL directly (parameterized MATCH query)
- The MATCH expression contains only sanitized alphanumeric tokens joined by OR
- FTS5 reserved words are double-quoted when needed

---

## Section 3: On-Demand Search Path (Skill vs MCP Decision)

### Decision: Skill-Based Search

**Chosen approach:** Skill (`/memory:search`)
**Rejected approach:** MCP tool

#### Rationale

| Factor | Skill | MCP Tool |
|--------|-------|----------|
| Daemon requirement | None | Requires persistent server process |
| stdlib constraint | Compatible | Violates (needs HTTP server) |
| Structural enforcement | Relies on LLM following instructions | API structure forces workflow |
| Reliability (claude-mem data) | 67% effectiveness (v5.4) | 100% effectiveness (v6+) |
| Complexity | Low (~100 LOC skill definition) | High (server, protocol, process mgmt) |

**Why skill despite the 67% problem:**

1. **The 67% number has context.** claude-mem's skill was a generic `search` skill
   competing with 9+ MCP tools in the same session. Our skill is a specific
   `/memory:search` command in a session that has NO competing MCP search tools.
   The trigger conditions are cleaner.

2. **Mitigations for trigger reliability:**
   - The auto-inject hook can include a reminder line when it has NO results:
     `<!-- Use /memory:search <topic> to search memories -->` This primes the LLM.
   - Skill trigger words are specific and diverse: "search memories", "find memory",
     "recall", "what did we decide", "what do we know about"
   - The user can invoke explicitly with `/memory:search <query>`

3. **The constraint is binding.** No daemons = no MCP. This is a hard architectural
   constraint, not a preference. We optimize within it.

4. **claude-mem's v5.5 improved skill effectiveness to ~100%** by renaming the skill and
   enhancing trigger mechanisms. The 67% was a naming/trigger problem, not a fundamental
   skill limitation.

#### Skill Design for Maximum Trigger Reliability

```yaml
---
name: memory-search
description: Search project memories for past decisions, runbooks, constraints, preferences, tech debt, and session summaries. Use when you need context from previous sessions.
globs:
  - ".claude/memory/**"
triggers:
  - "search memories"
  - "search memory"
  - "find memory"
  - "recall"
  - "what did we decide"
  - "what do we know about"
  - "previous decision"
  - "past session"
  - "look up memory"
  - "memory search"
---
```

#### Progressive Disclosure: Layer 1 (Compact) and Layer 2 (Full)

**Layer 1 -- Skill returns compact results:**

```
Found 7 memories matching "authentication":

1. [DECISION] Chose JWT over session cookies (score: -3.2)
   Tags: auth, jwt, cookies | Updated: 2026-02-15
   Path: .claude/memory/decisions/jwt-over-session-cookies.json

2. [RUNBOOK] Fix OAuth2 redirect loop (score: -2.1)
   Tags: auth, oauth, login | Updated: 2026-02-10
   Path: .claude/memory/runbooks/fix-oauth-redirect-loop.json

3. [CONSTRAINT] SAML not supported by provider (score: -1.8)
   Tags: auth, saml, limitation | Updated: 2026-01-28
   Path: .claude/memory/constraints/saml-not-supported.json

To read full details, use the Read tool on any path above.
```

**Layer 2 -- LLM reads selected files:**

The LLM decides which results are relevant and reads them using the built-in Read tool.
This is the "LLM-as-judge" pattern: Claude acts as the re-ranker, applying semantic
understanding that BM25 cannot.

**Why 2 layers instead of 3:** claude-mem needs 3 layers because its corpus is large
(thousands of observations) and each observation is expensive to retrieve (network call
to Chroma). Our corpus is small (100-500 files) and each file is a cheap local read.
Two layers provide sufficient progressive disclosure without unnecessary indirection.

#### Query Expansion

The skill instructions should encourage Claude to expand its query before searching:

```
When searching memories, consider expanding your query:
- If the user asks "how do we deploy?", also try "CI", "pipeline", "staging"
- If the user asks "what's the auth approach?", also try "JWT", "OAuth", "login"
- Run multiple searches if the first returns few results
```

This leverages Claude's semantic understanding to bridge the vocabulary gap between
user questions and stored memory titles/tags, without requiring any infrastructure.

---

## Section 4: Evaluation Framework (Phase 0)

### Benchmark Design

**Target: 25+ test queries** across these dimensions:

| Dimension | Examples | Count |
|-----------|---------|-------|
| **Category-specific** | "what database did we choose?" (DECISION), "how to fix the login error" (RUNBOOK) | 6 (one per category) |
| **Cross-category** | "what do we know about authentication?" (may span DECISION, RUNBOOK, CONSTRAINT) | 4 |
| **Specific vs vague** | "JWT token expiry" vs "security stuff" | 4 pairs (8 total) |
| **Follow-up / pronoun** | "what did we decide about that?" (requires transcript context) | 3 |
| **Negative** | "quantum computing" (should return nothing) | 2 |
| **Partial match** | "auth" should find "authentication" (stemming test) | 2 |

Each test query has:
- **Query text** (the simulated user prompt)
- **Expected relevant memories** (file paths)
- **Expected irrelevant memories** (should NOT be in top results)
- **Context** (simulated transcript turns, if applicable)

### Metrics

| Metric | Formula | What It Measures |
|--------|---------|-----------------|
| **Precision@K** | relevant_in_top_K / K | Are the injected results actually relevant? |
| **Recall@K** | relevant_in_top_K / total_relevant | Did we find all relevant memories? |
| **MRR** | 1 / rank_of_first_relevant | How quickly do we find the first relevant result? |
| **Silent rate** | queries_with_zero_injection / total | How often does auto-inject fire? (want: moderate, ~40-60%) |
| **False inject rate** | queries_with_irrelevant_injection / total | How often does auto-inject inject garbage? (want: <10%) |

Primary metric: **Precision@3** (for auto-inject) and **Recall@10** (for on-demand search).

### Automation

```python
# eval/run_benchmark.py
def run_benchmark(memory_root: str, queries: list[dict]) -> dict:
    """Run the evaluation benchmark.

    Each query dict has:
        query: str
        transcript_context: list[str] (simulated prior turns)
        expected_relevant: list[str] (file paths)
        expected_irrelevant: list[str] (file paths that should NOT appear)

    Returns metrics dict.
    """
    # Build FTS5 index once (same code as hook)
    memories = load_all_memories(memory_root)
    conn = build_fts_index(memories)

    results = []
    for q in queries:
        # Simulate query assembly
        tokens = tokenize_for_query(q["query"])
        for turn in q.get("transcript_context", []):
            tokens.extend(tokenize_for_query(turn))

        fts_query = build_fts_query(list(dict.fromkeys(tokens))[:20])
        if not fts_query:
            results.append({"query": q["query"], "hits": []})
            continue

        hits = conn.execute(
            "SELECT path, bm25(memories, 5.0, 3.0, 1.0) as score "
            "FROM memories WHERE memories MATCH ? ORDER BY score LIMIT 10",
            (fts_query,)
        ).fetchall()

        results.append({
            "query": q["query"],
            "hits": [{"path": h[0], "score": h[1]} for h in hits],
            "expected_relevant": q["expected_relevant"],
        })

    return compute_metrics(results)
```

### Baseline Measurement

Before any changes, run the benchmark against the CURRENT keyword system:
1. Create the test corpus (25+ memory JSON files across all categories)
2. Run queries through current `memory_retrieve.py` scoring
3. Record Precision@3, Recall@10, MRR, silent rate, false inject rate
4. This becomes the baseline to measure improvement against

---

## Section 5: Scoring Algorithm Detail

### BM25 Formula (FTS5 Built-in)

SQLite FTS5 implements Okapi BM25 internally. The `bm25()` function accepts per-column
weights. The formula (per FTS5 documentation):

```
score = Σ (weight_i * bm25_score_for_column_i)

where bm25_score_for_column_i uses:
  k1 = 1.2 (term frequency saturation)
  b = 0.75 (document length normalization)
  IDF(term) = log((N - n + 0.5) / (n + 0.5))
  tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl/avgdl))
```

We do NOT need to implement this -- FTS5 does it in optimized C code. We only configure
the column weights.

### Column Weights

```sql
SELECT *, bm25(memories, 5.0, 3.0, 1.0) as score
FROM memories
WHERE memories MATCH ?
ORDER BY score  -- ASC because scores are negative
LIMIT ?
```

| Column | Weight | Rationale |
|--------|--------|-----------|
| title | 5.0 | Highest signal. Titles are curated, dense, and specific. A title match is almost always relevant. |
| tags | 3.0 | High signal. Tags are manually assigned keywords. Less specific than titles but more reliable than body text. |
| body | 1.0 | Low weight but wide coverage. Body text contains the actual substance but is noisy (long text, boilerplate). |

**Why not weight category:** Category is UNINDEXED (not searchable). It is used for
post-query tiebreaking only.

### Category Priority as Tiebreaker

When two results have identical BM25 scores, break ties by category priority:

```python
CATEGORY_PRIORITY = {
    "decision": 1,      # Highest: active design choices
    "constraint": 2,    # Hard boundaries
    "preference": 3,    # Conventions
    "runbook": 4,       # Procedures
    "tech_debt": 5,     # Deferred work
    "session_summary": 6,  # Lowest: ephemeral context
}
```

Implementation: sort by `(bm25_score, category_priority)`.

### Recency Handling: Filter, Not Score Component

**Decision: Hard recency filter, not scoring decay.**

Rationale (from claude-mem and research consensus):
- Recency decay adds a tunable parameter (half-life) that is hard to calibrate
- A decision from 6 months ago is just as valid as one from yesterday
- The exception is session summaries, which have natural expiry (90 days by config)

**Implementation:** Filter out memories where `updated_at` is older than
`retention_days` (per-category config). Memories with `retention_days: 0` (permanent)
are never filtered by recency.

### File Path Matching Bonus

**Decision: Implement as Phase 2 enhancement, not in initial release.**

The concept: if a memory's `related_files` array contains the file Claude is currently
editing, boost that memory's score. This is a high-precision signal.

However, the hook input only provides `cwd`, not the specific file being edited.
To get the current file, we would need to parse the transcript for recent tool use
(Read/Edit calls), which adds complexity and fragility.

**Phase 2 plan:** Parse last 5 tool uses from transcript, extract file paths, match
against `related_files` in memories. Add a +2.0 score boost for matches.

### Structured Content Handling

Different categories have different JSON schemas. The `extract_body()` function
handles this by knowing which fields to extract per category (see Section 2).

**Key insight:** We do NOT try to give different categories different FTS5 tables or
different weights. All memories go into one table. The category-specific logic is in
body extraction (what text to index), not in querying.

---

## Section 6: Index and Caching Strategy

### When to Rebuild the FTS5 Index

**Every invocation. No caching.**

Rationale:
- Build time is ~4ms for 500 memories, ~8ms for 1000
- Caching introduces: stale data risk, concurrency bugs, invalidation logic, disk I/O
- The simplest correct solution is also the fastest in practice

### Cache Invalidation: Not Needed

Since we rebuild every time, there is no cache to invalidate. This eliminates an entire
class of bugs (stale cache, race conditions, corruption).

### index.md Role: Keep for Backward Compatibility, Not Primary

**Current role:** Primary retrieval surface (keyword matching against index lines).
**New role:** Backward compatibility artifact + human-readable inventory.

The FTS5 engine reads JSON files directly, not index.md. However, index.md is kept
because:
1. `memory_candidate.py` uses it for candidate selection during writes
2. It provides a human-readable overview of stored memories
3. `memory_index.py --query` uses it for simple CLI queries
4. The write guard and validation hooks reference it

**index.md is NOT in the retrieval hot path.** The FTS5 engine builds from JSON files.

### Body Token Storage: Read from JSON per Query

**Decision: Do NOT store extracted body text in index.md.**

Rationale:
- index.md is line-based, flat-text format -- storing multi-line body content would break parsing
- JSON read is fast enough (~10ms for 500 files)
- Body content changes when memories are updated; storing a copy creates staleness risk
- Keep index.md simple: title, path, tags (its current format)

---

## Section 7: Migration Plan

### Phase 0: Evaluation Benchmark

**Scope:** Build the test framework, create test corpus, measure baseline.
**Changes:**
- New file: `eval/benchmark.py` (evaluation runner)
- New file: `eval/queries.json` (25+ test queries with expected results)
- New directory: `eval/corpus/` (test memory JSON files)

**No production code changes.** This is measurement-only.

**Expected output:** Baseline metrics for current keyword system.
**Estimated effort:** ~200 LOC.

### Phase 0.5: Quick Wins (CONDITIONAL -- Safety Valve Only)

**Status:** Skip unless Phase 0 reveals FTS5 has unexpected issues on target platforms.

**Scope:** Body content indexing in the current keyword system.
**Changes:**
- `memory_retrieve.py`: Add body content reading + matching to `score_entry()`
- Read JSON files for top-scored candidates (extend existing deep-check)
- Add body match bonus (capped at 3 points)

**Expected precision improvement:** ~40% -> ~50% (body content is "non-negotiable"
per Gemini 2.5 Pro, highest-leverage single change).
**Estimated effort:** ~50 LOC change to `memory_retrieve.py`.

**When to use this phase:** Only if FTS5 is unavailable on a significant number of
target platforms (which Gemini 2.5 Pro assessed as "very low" risk). In that case,
Phase 0.5 delivers the highest-leverage improvement (body indexing) without requiring
FTS5. Otherwise, skip directly to Phase 1.

**Risk:** Increases JSON file reads per prompt. With _DEEP_CHECK_LIMIT=20, this means
reading up to 20 JSON files. At <1ms per file, adds ~20ms. Acceptable.

### Phase 1: FTS5 BM25 Engine

**Scope:** Replace keyword scoring with FTS5 BM25. New core of `memory_retrieve.py`.
**Changes:**
- `memory_retrieve.py`: Major rewrite
  - Add `build_fts_index()`, `extract_body()`, `build_fts_query()`, `tokenize_for_query()`
  - Replace `score_entry()` / `score_description()` with FTS5 MATCH + bm25()
  - Add `is_fts5_available()` with fallback to enhanced keyword scoring
  - Keep existing security model (sanitization, path containment, XML escaping)
- `tests/test_memory_retrieve.py`: Update/add tests for FTS5 path and fallback

**Expected precision improvement:** ~50% -> ~65% (BM25 with body content).
**Estimated effort:** ~300 LOC rewrite of core scoring, ~200 LOC tests.

### Phase 2: On-Demand Search Skill

**Scope:** Add `/memory:search` skill for explicit memory search.
**Changes:**
- New file: `skills/memory-search/SKILL.md` (skill definition with search instructions)
- Shared scoring engine extracted from `memory_retrieve.py` into `memory_search_engine.py`
- Both hook and skill import from the shared engine

**Expected improvement:** Effective recall from ~60% to ~80%+ (on-demand fills gaps
where auto-inject threshold is too conservative).
**Estimated effort:** ~150 LOC skill definition, ~100 LOC engine extraction.

### Phase 3: Transcript Context

**Scope:** Parse last 2-3 user turns from transcript for query enrichment.
**Changes:**
- `memory_retrieve.py`: Add `extract_transcript_context()`, integrate into query assembly
- Handle `transcript_path` from hook input JSON

**Expected precision improvement:** ~65% -> ~70% (transcript context helps with
pronoun references and topic continuity).
**Estimated effort:** ~80 LOC.

### Phase Summary

| Phase | Scope | Precision Est. | Effort | Risk |
|-------|-------|---------------|--------|------|
| 0 | Eval benchmark | Baseline measurement | ~200 LOC | None (measurement only) |
| 0.5 | Body content in keyword system | ~50% | ~50 LOC | Low (CONDITIONAL: skip if FTS5 OK) |
| 1 | FTS5 BM25 engine | ~65% | ~500 LOC | Medium (core rewrite) |
| 2 | On-demand search skill | ~65% + high recall | ~250 LOC | Low (additive) |
| 3 | Transcript context | ~70% | ~80 LOC | Medium (format stability, dilution risk managed) |

**Recommended fast path:** Phase 0 -> Phase 1 -> Phase 2 -> Phase 3 (skip 0.5).

Each phase is independently valuable and can be shipped separately. Phase 0 must
come first. Phases 1-3 can be reordered, though 1 before 2 is preferred (the skill
uses the same engine).

---

## Section 8: Configuration Design

### New Config Keys

```json
{
  "retrieval": {
    "enabled": true,
    "max_inject": 3,
    "match_strategy": "fts5_bm25",
    "engine": {
      "column_weights": {
        "title": 5.0,
        "tags": 3.0,
        "body": 1.0
      },
      "body_max_chars": 2000,
      "query_max_tokens": 20
    },
    "auto_inject": {
      "min_score_abs": 0.5,
      "relative_cutoff": 0.6,
      "max_results": 3
    },
    "search": {
      "min_score_abs": 0.1,
      "max_results": 10
    },
    "transcript_context": {
      "enabled": true,
      "max_turns": 3,
      "tail_bytes": 8192
    }
  }
}
```

### Backward Compatibility

| Existing Key | Behavior |
|-------------|----------|
| `retrieval.enabled` | Unchanged. Disables all retrieval. |
| `retrieval.max_inject` | Maps to `auto_inject.max_results`. Old key still works. |
| `retrieval.match_strategy` | Value `"title_tags"` forces legacy keyword mode. `"fts5_bm25"` (new default) uses FTS5. |

**Migration path:** When `match_strategy` is `"title_tags"` (current default), the
system runs the Phase 0.5 enhanced keyword scoring. When set to `"fts5_bm25"`, it
uses the full FTS5 engine. This allows users to opt in gradually.

**New keys are optional.** Defaults are embedded in the script. Config overrides are
read only if present. Missing keys fall back to defaults.

---

## Section 9: Risk Assessment

### What Could Go Wrong

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| **FTS5 unavailable** on user's Python | Medium | Very Low | Runtime check + fallback to enhanced keyword matching |
| **BM25 scores don't improve precision** as expected | High | Low | Phase 0 benchmark provides evidence before committing to Phase 1 |
| **Transcript format changes** in Claude Code update | Medium | Medium | Graceful degradation (empty list), versioned expectations |
| **WSL2 /mnt/c/ performance** blows time budget | Medium | Low | Document recommendation for Linux filesystem; still works, just slower |
| **Skill trigger unreliability** (67% problem) | Medium | Medium | Hook-injected reminder, diverse trigger words, explicit user `/memory:search` |
| **Query dilution from transcript context** | High | High (if not mitigated) | Restrict transcript enrichment to short prompts only (<= 3 tokens). **CAUGHT BY REVIEW.** |
| **Negative BM25 score math inversion** | High | Certain (if not fixed) | Use abs() for all threshold comparisons. **CAUGHT BY REVIEW, FIXED.** |
| **Auto-inject payload bloat** | Medium | Medium | Hook outputs title+tags+path only, NOT body content. Full read via skill path. |
| **Over-broad queries** (many OR tokens) match everything | Medium | Medium | Token cap (15), absolute score minimum, relative cutoff |
| **Body content extraction** misses important fields | Low | Medium | Per-category field mapping, capped but comprehensive |
| **FTS5 MATCH syntax error** from malformed input | High | Very Low | Input sanitized to alphanumeric-only before MATCH; try/except fallback |

### Reversibility Guarantees

Every phase is reversible:

| Phase | Reversal |
|-------|---------|
| 0 (benchmark) | Delete eval/ directory. No production impact. |
| 0.5 (body content) | Remove body scoring lines from `memory_retrieve.py`. |
| 1 (FTS5) | Set `match_strategy: "title_tags"` in config to revert to keyword scoring. |
| 2 (search skill) | Delete skill file. No impact on auto-inject. |
| 3 (transcript) | Set `transcript_context.enabled: false` in config. |

The `match_strategy` config key is the primary kill switch. It allows instant rollback
from FTS5 to keyword scoring without any code changes.

### What If FTS5 Doesn't Improve Precision?

If Phase 0 benchmark shows FTS5 BM25 does NOT meaningfully outperform enhanced keyword
matching (Phase 0.5), then:

1. **Ship Phase 0.5 only.** Body content indexing in the keyword system still provides
   the highest-leverage improvement.
2. **Skip Phase 1.** Do not rewrite the core engine.
3. **Still ship Phase 2** (on-demand search skill). It works with either engine.
4. **Still ship Phase 3** (transcript context). It works with either engine.

The phases are designed to be independently valuable. FTS5 is the expected winner but
not a hard dependency of the overall architecture.

---

## Appendix A: External Validation Summary

### Gemini 3.1 Pro -- Round 1 (Initial Architecture Review)

**Key feedback on this architecture:**
- "The proposed architecture is highly viable and performant for the constraints."
- **Risk flagged:** FTS5 MATCH syntax crashes from unescaped user input. **Addressed** via
  alphanumeric-only sanitization (Section 2).
- **Risk flagged:** WSL2 /mnt/c/ I/O penalty. **Addressed** via documentation recommendation.
- **Recommendation adopted:** "Ditch the disk cache. Build in :memory: every time."
- **Recommendation adopted:** "Truncate auto-injections to preserve context window."
- **Recommendation adopted:** "Robust query sanitization with OR-joined tokens."
- **Suggestion for skill reliability:** Inject system instruction via hook reminding
  Claude about `/memory:search`. **Adopted** in Section 3.
- Confirmed BM25 column weights (5.0, 3.0, 1.0) as "excellent baseline."
- Confirmed bm25() returns negative scores (lower = better). **Addressed** in scoring code.

### Gemini 3.1 Pro -- Round 2 (Proposal Review)

**Critical issues raised:**

1. **Negative score math trap (FIXED):** The relative threshold logic using `score * 0.6`
   produces inverted results with negative BM25 scores. Must use `abs()` before threshold
   comparison. **Fixed** in the `apply_threshold()` code in Section 2.

2. **Transcript context dilution (FIXED):** Blindly appending transcript tokens to
   specific prompts broadens the query and matches unrelated memories. **Fixed** by
   restricting transcript enrichment to short/ambiguous prompts only (<= 3 tokens).

3. **Auto-inject payload size (FIXED):** Full body injection for 3 memories wastes
   5k-10k tokens. **Fixed** by specifying that auto-inject outputs title+tags+path only,
   same format as current system.

**Simplification suggestions:**

| Suggestion | Our Decision | Rationale |
|-----------|-------------|-----------|
| Drop FTS5 fallback engine | **Accepted in spirit, modified in practice** | We keep a MINIMAL fallback (current keyword + body content) but do NOT build a "parallel pure-Python BM25" engine. The fallback is the existing code path with one small addition. Testing surface increase is ~10 lines, not a full engine. |
| Skip Phase 0.5 | **Partially accepted** | If Phase 0 benchmark is completed quickly, skip 0.5 and go straight to Phase 1. Phase 0.5 exists as a safety valve: if FTS5 has unexpected issues, body-content indexing in the keyword system is still a meaningful improvement. |
| Restrict transcript to short prompts only | **Accepted** | Threshold set to <= 3 meaningful tokens. |

### Key Disagreements and Resolutions

| Topic | This Proposal | Gemini Opinion | Resolution |
|-------|-------------|----------------|------------|
| Disk cache | No cache | "Abandon cache entirely" | **Agreement** |
| FTS5 fallback | Minimal fallback (existing keyword + body) | "Drop entirely, just disable retrieval" | **Partial disagree** -- disabling retrieval entirely when FTS5 missing is too aggressive. The fallback is cheap to maintain. |
| Phase 0.5 | Keep as safety valve | "Skip, go straight to Phase 1" | **Conditional** -- skip if Phase 0 baseline is acceptable. Keep if we need incremental proof. |
| Transcript enrichment | Short prompts only (<= 3 tokens) | "Short prompts only (< 3 words)" | **Agreement** (threshold at 3) |
| Stop words | Existing 80+ word set | "Hardcode 100-200 words" | **Partial** -- existing set is sufficient; FTS5 Porter stemmer handles morphological variants |
| Score thresholds | abs(score) with 0.5 min, 0.6 relative | Must use abs() for negative scores | **Agreement** -- critical fix applied |

---

## Appendix B: Full Hook Flow (Revised)

```
UserPromptSubmit hook fires
│
├─ Read hook input JSON (user_prompt, transcript_path, cwd)
├─ Skip if prompt < 10 chars
├─ Locate memory_root from cwd
│
├─ Check config (retrieval.enabled, match_strategy, thresholds)
│
├─ [If match_strategy == "fts5_bm25" AND FTS5 available]
│  │
│  ├─ Load all JSON memory files from category folders
│  │   └─ Filter: record_status == "active" only
│  │   └─ Extract: title, tags, body (via extract_body), id, path, category, updated_at
│  │
│  ├─ Build in-memory FTS5 index (~4ms for 500 files)
│  │
│  ├─ Construct query:
│  │   ├─ Tokenize user_prompt
│  │   ├─ IF prompt tokens <= 3: enrich with last 2-3 transcript turns
│  │   ├─ Deduplicate, cap at 15 tokens
│  │   └─ Build "token1 OR token2 OR ..." MATCH expression
│  │
│  ├─ Execute FTS5 query with BM25 ranking
│  │   └─ SELECT path, title, category, bm25(...) as score
│  │      WHERE memories MATCH ? ORDER BY score LIMIT 20
│  │
│  ├─ Apply recency filter (per-category retention_days)
│  ├─ Apply auto-inject threshold (absolute + relative)
│  ├─ Apply category priority tiebreaker
│  ├─ Cap at max_results (default 3)
│  │
│  └─ Output with security model:
│     ├─ Title re-sanitization
│     ├─ Path containment check
│     ├─ XML escaping
│     └─ <memory-context> wrapper
│
├─ [Else: fallback to enhanced keyword matching]
│  │
│  ├─ Read index.md (existing flow)
│  ├─ Score entries with body content bonus
│  ├─ Deep-check top 20 for recency/retired
│  └─ Output (existing format)
│
└─ Exit 0 (stdout added to context)
```
