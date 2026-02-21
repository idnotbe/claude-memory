# Retrieval Architecture Critique: claude-memory Plugin

**Date:** 2026-02-19
**Scope:** `memory_retrieve.py`, `memory_triage.py` (comparison), `SKILL.md`, `assets/memory-config.default.json`
**Perspective:** Software Architecture and Design

---

## 1. Design Decisions: Why Keyword Matching?

### The Core Trade-off

Keyword matching was chosen over semantic search / vector embeddings. This is a deliberate, defensible decision for a Claude Code plugin context -- but it carries costs that deserve examination.

**Why keyword matching makes sense here:**

- **Zero external dependencies at runtime.** `memory_retrieve.py` is stdlib-only. Semantic search would require sentence-transformers, faiss, numpy, or a network call to an embedding API. In a hook that fires on every user prompt, adding a 50-200ms embedding call (or a subprocess that boots a Python ML environment) would be perceptible friction. The hook's implicit budget is tight.
- **Determinism and debuggability.** Keyword matching produces the same results for the same input, every time. Embedding similarity is opaque: if the retrieval misses something, there is no clear answer as to why. Debugging "why didn't that memory surface?" is trivially answered with keyword matching.
- **No model drift.** Embedding models change over time. A memory tagged `pydantic` will always match a prompt containing `pydantic` regardless of what embedding model version is installed. Semantic drift -- where a model update silently changes which memories surface -- is a real operational risk in long-lived projects.
- **The use case is structurally friendly to keyword matching.** Memory titles are authored by an LLM that already knows the domain. A title like "Use pydantic v2 for schema validation" is highly lexically predictable. The query surface (user prompts) tends to reuse the same domain terms that appear in titles. Semantic search would add the most value for paraphrase detection (e.g., "serialization library" matching "pydantic"), which matters less when both title and prompt are authored in a consistent technical register.

**Where keyword matching falls short:**

- **Synonym blindness.** "Dockerfile" won't match a memory titled "Container build configuration." "Auth token" won't match "bearer credential." In practice, this gap is partially mitigated by the tag system, which allows a subagent to annotate memories with aliases, but the mitigation is manual and depends on the writing agent having thought ahead.
- **Compositional queries fail.** A prompt like "how do I handle the database migration issue?" might have a relevant runbook titled "postgres alembic version conflict fix." The shared vocabulary is thin. Keyword matching scores zero unless `database`, `migration`, or similar terms appear in the title or tags.
- **No query expansion.** There is no stemming, lemmatization, or synonym expansion. `test` and `testing` are treated as different tokens (though prefix matching at 4+ chars partially addresses stemming: `test` would prefix-match `testing`).

**The 10-second timeout constraint** (visible in the subprocess call to rebuild the index) is a real driver. The rebuild call uses `timeout=10`. A retrieval hook that took 10 seconds would be intolerable. But the timeout comment applies to a subprocess launch for index rebuild -- not the main retrieval path itself, which is a pure in-process file read and string operation that completes in well under 100ms for any realistic index size. The timeout is not a constraint on retrieval strategy selection; it is a constraint on the recovery path.

**Verdict on keyword matching:** The choice is correct for the current scope. The implementation is pragmatic given the plugin environment. The gaps are real but mostly manageable for a domain where both writes and reads are LLM-mediated.

### Why a Flat index.md Instead of a Database?

The flat `index.md` is motivated by the same zero-dependency principle. SQLite would be a reasonable alternative (stdlib, no install), but introduces:
- Schema migration concerns as the plugin evolves
- Locking concerns (SQLite WAL mode handles concurrent readers, but Write-Ahead Log adds complexity)
- Less human-readable state for debugging

The flat file approach has a significant operational advantage: a developer can inspect, grep, and reason about the full memory catalog in any text editor. This aligns with the plugin's philosophy of being a transparent layer rather than an opaque store.

The trade-off appears in Section 5 (scalability) below.

### Why Two-Pass Scoring (Text Then JSON Deep-Check)?

The two-pass design is architecturally sound. It separates concerns correctly:

**Pass 1 (index.md scan, in-memory):** Fast lexical scoring against all entries. No I/O beyond the initial file read. This narrows the candidate set from potentially hundreds of entries to the top 20.

**Pass 2 (JSON deep-check, per-file I/O):** Reads actual JSON files for recency bonus and retired status. Opening 20 files per prompt is acceptable; opening 600+ would not be.

The two-pass structure is a classic pre-filter / detailed-evaluation pattern. The weakness is that the pre-filter (title + tags) determines which entries ever reach deep-check. An entry with a weak title and no tags but highly relevant content body will never be deeply evaluated. The index line is a permanent first-class filter -- there is no fallback path for content-based retrieval.

One subtle issue with Pass 2: entries beyond the `_DEEP_CHECK_LIMIT` of 20 are added back to `final` without verification of their retired status (line 329-330). The comment says "assume not retired," but retired entries in the index represent an index-out-of-sync condition that could silently inject stale memories. This is a correctness gap, not just a performance trade-off.

---

## 2. Retrieval vs. Triage Asymmetry

### The Asymmetry Is Stark

**Triage scoring** (save path):
- Multi-pattern regex with primary/booster distinction
- Co-occurrence sliding window (4 lines before/after)
- Weighted scoring with caps and per-category denominators for normalization
- Code stripping (fenced blocks and inline code) to reduce false positives
- Activity metrics for SESSION_SUMMARY (tool count, distinct tools, exchanges)
- Context excerpt extraction for downstream subagents
- Configurable per-category thresholds

**Retrieval scoring** (load path):
- Tokenization with stop word filter
- Exact title match (2 pts), exact tag match (3 pts), prefix match on title or tags (1 pt)
- Description-based scoring with cap at 2 points
- Recency bonus (1 pt for entries updated within 30 days)

The difference is roughly a 3:1 complexity ratio in favor of the save path. This asymmetry is largely justified, but not entirely.

### Why the Difference Is Justified

Triage runs once per session stop, against a full conversation transcript that can span thousands of lines. The sophistication is warranted because:
1. The signal is noisy (conversation text includes tangents, tool outputs, code)
2. Mistakes at triage time are costly: a false negative means a decision is never recorded; a false positive means unnecessary LLM subagent invocations
3. The co-occurrence model captures genuine linguistic patterns (primary signal + contextual confirmation)

Retrieval runs on every user prompt, which is typically 10-200 words. The scoring surface is much smaller, so complex pattern matching offers diminishing returns.

### Where the Asymmetry Creates Problems

**The tag system does heavy lifting on the read side.** Triage creates memories with tags determined by the writing subagent. Retrieval gives tags 3x the weight of title matches. This means retrieval quality is heavily dependent on how well the writing subagent tagged the memory. There is no feedback loop: if a memory was poorly tagged at write time, it will never surface during retrieval. The asymmetry pushes quality responsibility upstream to the write side with no correction mechanism.

**Retrieval ignores conversation context.** The retrieval hook (`UserPromptSubmit`) receives only the current user prompt. It has no access to the conversation history. This creates a fundamental limitation:

- A user asks "can you continue what we started with the auth module?" -- there are no keywords from the previous session in this prompt. The retrieval returns nothing, even though session summaries and decisions about the auth module are highly relevant.
- A user types "I'm getting that error again" -- no keywords. Nothing is retrieved.
- A follow-up like "use the approach we discussed" -- nothing.

The triage system processes the full transcript tail (up to 50 messages). The retrieval system processes a single line. This creates a persistent asymmetry: information flows into memory from rich context, but is retrieved only from sparse context.

**Should retrieval consider conversation context beyond the single prompt?**

Yes, with caveats. A reasonable improvement would be to also tokenize the last 3-5 user messages (available in the hook input if the API exposes them, or from a lightweight local ring buffer). This would meaningfully improve recall for short follow-up prompts without adding significant latency. However, this requires the `UserPromptSubmit` hook to receive conversation history, which may not be available in the current Claude Code hook API design.

A simpler approach: extract key noun phrases from the last few lines of the assistant response (if available), since that text often contains domain terms relevant to what the user will ask next.

---

## 3. Index as Derived Artifact

### The Design

`index.md` is derived from JSON source-of-truth files. `memory_retrieve.py` auto-rebuilds it if absent:

```python
if not index_path.exists() and memory_root.is_dir():
    subprocess.run([..., "--rebuild", ...], timeout=10)
```

This is a lazy-rebuild derived-artifact pattern. The index is a performance cache, not the authoritative store.

### Pros

- **Resilient to index loss.** If `index.md` is `.gitignore`d and not committed, the plugin still recovers transparently on first use in a new checkout.
- **Human-readable state.** A developer can `cat index.md` to see all memories without writing code.
- **Decoupling.** The index format can evolve without changing JSON schemas. Adding the `#tags:` suffix was backward compatible.
- **Atomic consistency model.** Each memory write calls `memory_write.py`, which presumably updates both the JSON and the index in a single operation. The JSON is authoritative; the index is a projection.

### Cons and Out-of-Sync Scenarios

**When can index.md get out of sync?**

1. **Partial write failure.** If `memory_write.py` writes the JSON but crashes before updating the index (or vice versa), they diverge. The atomic write pattern mitigates but does not eliminate this (filesystem atomicity is per-file, not across two files).
2. **Manual edits.** A developer editing a JSON file directly to fix a field bypasses the index update. The index will reflect stale data until rebuild.
3. **Retirement not reflected.** If a memory is retired (JSON updated), but the index rebuild is not triggered, the index still lists the entry. The retrieval hook's deep-check handles this (checks `record_status` in the JSON), but only for the top 20 entries. Entries 21+ are served without retirement verification (the correctness gap noted in Section 1).
4. **Category rename.** If a JSON file's category field is corrected directly, the index shows the old category.
5. **File move.** If a JSON file is moved (e.g., by reorganizing folders), the path in the index becomes stale.
6. **Concurrent writes.** Two simultaneous `memory_write.py` calls could interleave index updates. The scripts appear to use file locking, which reduces but may not fully eliminate races on NFS or certain filesystems.

**The rebuild-on-missing strategy** is sound but incomplete. There is no scheduled or triggered rebuild when the index becomes stale. The system has no way to detect drift short of a full rebuild. A `--validate` option exists in `memory_index.py`, but it must be invoked manually.

**Recommendation:** Add a content-hash or timestamp watermark to the index header. When `memory_retrieve.py` loads the index, compare the watermark against the newest JSON file's mtime. If they diverge beyond a threshold (e.g., 60 seconds), trigger a background rebuild. This self-heals staleness without full synchronous rebuilds on every read.

---

## 4. Category Priority System

### Current Ordering

```python
CATEGORY_PRIORITY = {
    "DECISION": 1,      # highest priority
    "CONSTRAINT": 2,
    "PREFERENCE": 3,
    "RUNBOOK": 4,
    "TECH_DEBT": 5,
    "SESSION_SUMMARY": 6,  # lowest priority
}
```

### Rationale (Inferred)

The ordering reflects an implicit model of "information criticality":
- **DECISION** first: architectural choices define the project's identity; knowing them before acting is most important
- **CONSTRAINT** second: knowing what you cannot do prevents wasted effort
- **PREFERENCE** third: conventions shape how you work
- **RUNBOOK** fourth: operational fixes are important when relevant but situational
- **TECH_DEBT** fifth: context for ongoing work, not universally critical
- **SESSION_SUMMARY** last: recent context, but the broadest and least precise

### Where This Ordering Is Problematic

**Priority is a tiebreaker, not a filter.** Priority only matters when two entries have equal text scores. If a RUNBOOK scores 8 and a DECISION scores 3 for a given prompt, the RUNBOOK is retrieved first. Priority does not override relevance. This is correct behavior -- but it means the ordering only matters at score ties, which are more common than they might seem (the scoring system uses small integers: 2, 3, 1, and a cap of 2 for descriptions).

**The RUNBOOK case is underweighted.** When a user describes an error, RUNBOOK is the single most actionable memory type -- it contains the exact fix steps. Yet it sits at priority 4. If a user prompt says "I'm seeing a traceback" and there is both a DECISION about the error handling library (score 2) and a RUNBOOK for that exact error (score 2), the DECISION surfaces first. This is backwards for that use case.

**CONSTRAINT should arguably be higher than DECISION in many contexts.** Surfacing "this API has a rate limit of 100 req/s" before "we decided to use this API" is more immediately actionable in a coding session. The DECISION is already reflected in the codebase; the CONSTRAINT is invisible until you hit it.

**SESSION_SUMMARY at the bottom is defensible but has a cost.** Session summaries contain `next_actions[]` and `in_progress[]` fields that are highly relevant at the start of a new session. A session summary scoring 5 is much more useful at the start of a coding session than a DECISION scoring 5. But the priority system has no temporal awareness: it does not distinguish "user just started a new session" from "user is mid-session deep in a specific task."

**The ordering creates categorical bias.** With `max_inject=5`, if scores are equal across categories, only the top 5 priority categories will ever appear. SESSION_SUMMARY and TECH_DEBT are structurally disadvantaged. TECH_DEBT items tracking important known issues (e.g., "do not use X API -- it crashes on empty input") would be suppressed in favor of less relevant decisions.

**Proposed alternative:** Use priority as a 0.5-point score boost rather than a pure tiebreaker. This preserves relevance ordering while giving higher-priority categories a mild nudge. Alternatively, add a "recency burst" for SESSION_SUMMARY specifically: session summaries created within the last 24 hours get +2 points regardless of keyword match.

---

## 5. Scalability Concerns

### Linear Scanning of index.md

The current approach reads the entire `index.md` on every `UserPromptSubmit`. At 600+ entries (6 categories × 100 memories), each line is approximately 120 characters. That is ~72KB of text parsed on every user prompt.

**At current scale (sub-100 entries):** Negligible. Python reads 72KB in microseconds.

**At `max_memories_per_category=100` (600 entries):** Still fast. String processing is fast in Python. The scan is O(n) but n is small.

**The real scaling bottleneck is the deep-check I/O.** Opening 20 JSON files per prompt at 600+ entries is the actual cost. If each file read takes 1ms (local SSD), 20 reads = 20ms per prompt. That is perceptible at scale if the user types quickly. On network filesystems (WSL, Docker volume mounts, network drives), latency per read can be 5-20ms, making 20 reads = 100-400ms of retrieval overhead per prompt. This is the real performance risk, not the index scan.

**The `_DEEP_CHECK_LIMIT = 20` cap** is a reasonable engineering trade-off: bound the worst-case I/O while still checking a meaningful candidate set. But as noted earlier, entries beyond position 20 skip the retired-status check.

### Could Highly Relevant Entries Be Missed?

Yes, in a specific scenario: if a memory has an average title and minimal tags, but highly relevant body content, it will score low in Pass 1 and might not appear in the top 20. Its relevance can never be discovered because the body is not indexed.

More concretely: a RUNBOOK titled "API integration fix" with tags `api,fix` will score far lower for a prompt about "stripe webhook signature validation error" than a DECISION titled "Use stripe for payments" tagged `stripe,payments,webhook`. The RUNBOOK is vastly more relevant, but keyword matching on the title gives it no advantage.

At 600+ entries, the probability that a relevant entry falls outside the top 20 candidates grows. The current default of 100 memories per category is deliberately capped to constrain this risk, but the cap itself is a workaround for the retrieval system's limitations.

### What 100+ Memories Per Category Actually Means

The `max_memories_per_category=100` default means the total index can reach 600 entries. At that scale:

- Linear scan: still fast (~1-2ms in process)
- Deep-check I/O: up to 20ms on local SSD, potentially 400ms on network filesystem
- Pass 1 false-negative rate: increases as the ratio of relevant entries to total entries grows

The system is designed to never reach this scale in practice (memories should be retired, session summaries roll over), but the retrieval architecture does not gracefully degrade if it does.

---

## 6. Alternative Approaches: Concrete Improvements

The goal here is targeted improvements within the existing architecture, not a complete redesign. Semantic search is deliberately excluded as over-engineering for this context.

### 6.1 Add Body Tokens to the Index Line (High Impact, Low Cost)

**Current:** Index lines contain only title, category, path, and tags.
**Proposed:** Add a `#body:word1,word2,...` suffix containing the top 10-15 highest-frequency non-stop-word tokens from the memory body.

This dramatically improves recall without changing the two-pass architecture. The retrieval system gains access to content-level keywords without opening JSON files. The body tokens could be populated at write time by `memory_write.py` and re-computed at rebuild time by `memory_index.py`.

Example index line before:
```
- [RUNBOOK] Stripe webhook signature validation fix -> .claude/memory/runbooks/stripe-webhook-fix.json #tags:stripe,webhook,signature
```

After:
```
- [RUNBOOK] Stripe webhook signature validation fix -> .claude/memory/runbooks/stripe-webhook-fix.json #tags:stripe,webhook,signature #body:stripe,payload,header,raw,secret,hmac,middleware,django
```

**Trade-off:** Index lines get longer (~200 chars vs. ~120 chars). The index file grows proportionally. At 600 entries: ~120KB vs. ~72KB. Still trivially fast to scan.

### 6.2 Fix the Retired-Status Gap Beyond Deep-Check (Correctness, Low Cost)

**Current:** Entries beyond position 20 skip the retired-status JSON check.
**Proposed:** Either (a) cap `final` contributions from beyond `_DEEP_CHECK_LIMIT` to entries with non-retired index markers, or (b) add a `#status:retired` marker to index lines when a memory is retired, allowing the retrieval hook to filter them in Pass 1 without JSON I/O.

Option (b) is cleaner. Retiring a memory in `memory_write.py` would also update the index line to add `#status:retired`, and `parse_index_line` would filter these out during Pass 1. This eliminates both the correctness gap and the need for any deep-check for retirement status.

### 6.3 Recency-Biased Category Priority for SESSION_SUMMARY (Low Cost)

**Current:** SESSION_SUMMARY is always last in priority.
**Proposed:** When the index is loaded, check the mtime of the sessions folder. If any session summary was created or updated within the last 2 hours, treat SESSION_SUMMARY as priority 1.5 (between DECISION and CONSTRAINT) for that retrieval pass.

This makes session summaries "sticky" at the start of a new session -- when they are most relevant -- without permanently elevating them.

### 6.4 Separate Scoring Weight for Functional Category (Low Cost)

**Current:** Priority is a tiebreaker on equal scores.
**Proposed:** Apply a configurable per-category score multiplier (default 1.0 for all categories). Operators can configure `retrieval.category_weights.runbook: 1.2` to boost runbooks by 20% in technical projects where error lookup is a common pattern.

This avoids hardcoding bias while making the priority system explicit and tunable.

### 6.5 Lightweight Ring-Buffer for Last N Prompt Tokens (Medium Impact, Medium Cost)

**Current:** Retrieval considers only the current user prompt.
**Proposed:** `memory_retrieve.py` writes the tokenized content of each retrieved prompt to a small ring buffer file (`.claude/memory/.staging/.prompt-ring.json`, max 5 entries). On subsequent prompts, the token set includes the union of the current prompt and the last 3-5 prompt token sets (with a decay weight: 0.3x for previous prompts).

This improves recall for follow-up prompts ("use the approach we discussed") by carrying forward domain vocabulary from the recent conversation. The ring buffer is cheap to maintain and read. The decay weight prevents old prompts from permanently biasing retrieval.

**Risk:** The ring buffer file creates a new class of staleness. It must be cleared on session start (or keyed by session ID if available).

### 6.6 Score Normalization Across Categories (Low Cost)

**Current:** All categories compete on the same raw score scale.
**Proposed:** Track the average score and standard deviation per category over the last N prompts (written to `.staging/.score-stats.json`). Normalize scores to z-scores before sorting. This prevents one category with systematically higher scores from dominating all injections.

This is arguably over-engineering for the current scale, but worth noting as the system matures.

---

## Summary: Architectural Strengths and Weaknesses

| Aspect | Strength | Weakness |
|--------|----------|----------|
| Keyword matching | Zero-dep, deterministic, fast | Synonym blindness, no paraphrase |
| Two-pass scoring | Efficient, correct pre-filter pattern | Body content never indexed |
| Flat index.md | Human-readable, zero-dep, recoverable | Staleness with no self-heal |
| Category priority | Simple, understandable ordering | RUNBOOK underweighted, no temporal context |
| Deep-check limit | Bounds worst-case I/O | Retired-status gap for entries 21+ |
| Retrieval scope | Fast, low latency | Single-prompt only, no context window |
| Triage vs. retrieval | Save side correctly sophisticated | Read side misses cross-turn context |

The architecture is well-suited to its environment: a CLI plugin with no external dependencies, tight latency budgets, and a need for transparent, debuggable behavior. The identified weaknesses are real but tractable. The most impactful single improvement would be adding body tokens to index lines (#6.1), which improves recall without architectural change. The most important correctness fix is the retired-status gap (#6.2).
