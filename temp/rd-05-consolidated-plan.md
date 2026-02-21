# Consolidated Retrieval Improvement Plan

**Date:** 2026-02-20
**Author:** Team Lead (consolidation of synthesizer, architect, skeptic, pragmatist outputs)
**Status:** DRAFT -- pending verification rounds
**Cross-validated:** Gemini 3.1 Pro (clink), vibe-check skill

---

## Executive Summary

Replace the current keyword-matching retrieval (~40% estimated precision) with a 3-phase improvement plan that delivers body content indexing, FTS5 BM25 ranking, and on-demand search. Expected outcome: auto-inject precision ~65-75% (high threshold), effective recall ~80%+ (with on-demand search).

**3 phases, 3 focused days, ~400-600 LOC total change.**

---

## Key Decisions (Resolved Conflicts)

### 1. FTS5 vs Enhanced Keyword: FTS5 APPROVED

**Skeptic argument:** IDF has diminishing returns at N<500 (ratio only ~3.3x).
**Counter-argument (Gemini 3.1 Pro, adopted):** "3.3x is mathematically sufficient to fix rank inversion. If 'pydantic' and 'refactor' both match 1 time, an IDF-less system scores them equally. BM25 scores 'pydantic' 3.3x higher, ensuring the specific technical term wins. Absolute magnitude doesn't matter; ordering does."

**Additional FTS5 justification:** FTS5's `tokenchars` option natively solves the coding-term tokenization problem (`user_id`, `React.FC` preserved as single tokens). Reimplementing this + IDF weighting in Python is reinventing the wheel.

**Decision:** FTS5 is worth the rewrite because it solves TWO problems at once (tokenization + IDF ranking) with less code than fixing both in the keyword system.

### 2. Phase Ordering: Body Content FIRST (Unconditional)

**Architect proposed:** Phase 0.5 (body content) as conditional safety valve.
**Skeptic + Pragmatist + Gemini agreed:** Body content is "foundational and non-negotiable", highest ROI change.
**Decision:** Body content indexing is Phase 1, unconditional. This also validates the body-content hypothesis before committing to Phase 2 (FTS5).

### 3. Tokenization Fix: Elevated to Blocking Prerequisite

**Skeptic finding (CRITICAL):** Current tokenizer `[a-z0-9]+` destroys coding terms.
**Gemini solution:** FTS5 `tokenize='unicode61 tokenchars ''_.-'''` preserves underscores, dots, hyphens natively.
**Decision:** Fix the Python tokenizer in Phase 1 AND use FTS5 tokenchars in Phase 2. Both phases benefit.

### 4. Threshold Strategy: Drop Absolute Minimum

**Pragmatist finding:** BM25 scores for 500-doc corpus are ~0.000001 magnitude. Absolute threshold of 0.5 rejects everything.
**Gemini confirmed:** "Abandon absolute BM25 thresholds entirely."
**Decision:** Use Top-K limit + relative cutoff (>= 50% of best score). No absolute minimum.

### 5. Relative Cutoff: Relaxed to 50%

**Skeptic finding (HIGH):** 60% relative cutoff with column weights (title 5x, body 1x) creates "winner takes all" -- a strong title match excludes all body-only matches.
**Decision:** Lower relative cutoff to 50% AND add a minimum results guarantee (always return at least top 2 if any matches exist). This prevents context starvation from column weight disparities.

### 6. On-Demand Search: Skill (Not MCP)

**Constraint is binding:** No daemons = no MCP. This is an architectural constraint from WSL2 stability requirements and zero-infrastructure design philosophy.
**Mitigations for 67% skill effectiveness:**
- Hook injects reminder when auto-inject returns zero results
- Diverse trigger words
- User can invoke explicitly: `/memory:search <query>`
- claude-mem v5.5 improved skill effectiveness to ~100% with better naming/triggers

### 7. Deferred Items

| Item | Why Defer |
|------|-----------|
| Transcript context | Marginal value (only fires on <3-token prompts). 8KB seek fails after long responses. Format stability risk. |
| Eval benchmark framework | Personal project -- manual testing with 5-10 queries sufficient. Build formally if/when project gets users. |
| Fallback keyword engine | FTS5 available on all modern Python 3. Error loudly if missing. |
| Config proliferation | Hardcode sensible defaults. Add config keys only when users need to tune. |

---

## Phase 1: Body Content + Tokenizer Fix (Day 1)

### Scope
Add body content scoring to the EXISTING keyword system + fix the tokenizer to preserve coding identifiers.

### Changes to `memory_retrieve.py`

**1. Fix tokenizer (affects all scoring):**
```python
# BEFORE: [a-z0-9]+  (destroys user_id, React.FC, .env)
# AFTER:  [a-z0-9][a-z0-9_.-]*[a-z0-9]|[a-z0-9]+
# Preserves: user_id, react.fc, auth-service, node_modules
# Still strips: pure punctuation, single-char noise
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+")
```

**2. Add body content extraction:**
```python
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

def extract_body_tokens(data: dict) -> set[str]:
    """Extract tokenized body content from memory JSON."""
    category = data.get("category", "")
    content = data.get("content", {})
    fields = BODY_FIELDS.get(category, [])
    parts = []
    for field in fields:
        value = content.get(field)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    for v in item.values():
                        if isinstance(v, str):
                            parts.append(v)
    body_text = " ".join(parts)[:2000]
    return tokenize(body_text)
```

**3. Extend deep-check loop to score body content:**
```python
# In the existing deep-check loop (lines 330-358 of memory_retrieve.py):
# Currently reads JSON for recency and retired status.
# EXTEND to also extract body tokens and add bonus.
body_tokens = extract_body_tokens(data)
body_matches = prompt_words & body_tokens
body_bonus = min(3, len(body_matches))  # Cap at 3
final_score = text_score + (1 if is_recent else 0) + body_bonus
```

### Expected Outcome
- Precision: ~40% -> ~50-55% (body content adds discriminating signal)
- Effort: ~60-80 LOC change, 2-4 hours
- Risk: Near zero (extends existing system, fully reversible)

### Test
Manual: run 5-10 queries that currently return irrelevant results. Verify body content matching improves relevance.

---

## Phase 2: FTS5 BM25 Engine (Day 2-3 morning)

### Scope
Replace keyword scoring core with in-memory FTS5 BM25. Keep all I/O, security, and output formatting.

### FTS5 Configuration
```python
conn = sqlite3.connect(":memory:")
conn.execute("""
    CREATE VIRTUAL TABLE memories USING fts5(
        title, tags, body,
        id UNINDEXED, path UNINDEXED,
        category UNINDEXED, updated_at UNINDEXED,
        tokenize="unicode61 tokenchars '_.-'"
    );
""")
```

**Why `tokenchars '_.-'`:** Preserves `user_id`, `React.FC`, `auth-service` as single tokens in FTS5, matching the Phase 1 tokenizer fix. This is Gemini's key insight: FTS5 natively handles the coding-term problem.

### Query Construction
```python
def build_fts_query(tokens: list[str]) -> str | None:
    """Build FTS5 MATCH with wildcard prefix matching."""
    safe = []
    for t in tokens:
        # Escape FTS5 special chars, keep tokenchars
        cleaned = re.sub(r'[^a-z0-9_.\-]', '', t.lower())
        if cleaned and cleaned not in STOP_WORDS and len(cleaned) > 1:
            # Wildcard suffix for prefix matching (auth* -> authentication)
            safe.append(f'"{cleaned}"*')
    if not safe:
        return None
    return " OR ".join(safe)
```

**Why `"token"*` (quoted + wildcard):** The quotes prevent FTS5 from interpreting dots/underscores as operators. The `*` wildcard preserves prefix matching behavior (auth* matches authentication), fixing the pragmatist's critical regression finding.

### Scoring and Threshold
```python
def query_fts(conn, fts_query: str, mode: str = "auto") -> list[dict]:
    """Query FTS5 with BM25 ranking and threshold filtering."""
    MAX_AUTO = 3
    MAX_SEARCH = 10
    max_results = MAX_AUTO if mode == "auto" else MAX_SEARCH

    results = conn.execute(
        "SELECT id, title, path, category, updated_at, "
        "bm25(memories, 5.0, 3.0, 1.0) as score "
        "FROM memories WHERE memories MATCH ? "
        "ORDER BY score LIMIT ?",
        (fts_query, max_results * 3)  # Over-fetch for filtering
    ).fetchall()

    if not results:
        return []

    # Category priority tiebreaker (applied post-BM25)
    CATEGORY_PRIORITY = {
        "decision": 1, "constraint": 2, "preference": 3,
        "runbook": 4, "tech_debt": 5, "session_summary": 6,
    }

    if mode == "auto":
        # Relative cutoff: >= 50% of best score (abs values)
        best_abs = abs(results[0][5])
        if best_abs < 1e-10:  # Essentially zero
            return []
        cutoff = best_abs * 0.50
        filtered = [r for r in results if abs(r[5]) >= cutoff]
        # Guarantee: always return at least top 2 if any matches
        if len(filtered) < 2 and len(results) >= 2:
            filtered = list(results[:2])
        # Sort by (score, category_priority), cap at MAX_AUTO
        filtered.sort(key=lambda r: (r[5], CATEGORY_PRIORITY.get(r[3], 10)))
        return filtered[:MAX_AUTO]
    else:
        return results[:MAX_SEARCH]
```

### Architecture: Always Rebuild In-Memory
**Decision: Rebuild FTS5 per invocation. No disk cache.**

Skeptic objected (Finding #6): reads N files per prompt, wasteful.
**Counter-argument:**
- Pragmatist benchmarked: 500 files -> 12ms read + 23ms build = ~35ms total. Well within 100ms budget.
- Caching introduces stale data risk, concurrency bugs, invalidation logic.
- WSL2 /mnt/c/ warning: 500ms-1s on Windows host filesystem. Document recommendation: use Linux filesystem.
- The simplicity benefit (zero cache bugs, zero stale data) outweighs the latency cost for the expected corpus size.

**Compromise for future scalability:** If corpus exceeds ~1000 memories and latency becomes noticeable, implement mtime-based cache invalidation as a future optimization. Not now.

### Security Model: Maintained
- Title sanitization: unchanged (`_sanitize_title`)
- Path containment: unchanged (`resolve().relative_to()`)
- XML escaping: unchanged
- FTS5 query injection: prevented by alphanumeric + `_.-` only tokenization
- Output format: unchanged (`<memory-context>` wrapper)

### Expected Outcome
- Precision: ~50% -> ~65% (BM25 IDF + stemming + column weights)
- Auto-inject with high threshold: ~70-75%
- Effort: ~150-200 LOC rewrite of scoring core, 1-2 days
- Risk: Medium (core rewrite, but fully reversible via config)

---

## Phase 3: On-Demand Search Skill (Day 3 afternoon)

### Scope
Add `/memory:search` skill for explicit memory search when auto-inject misses or user wants to explore.

### Architecture
```
/memory:search <query>
    |
    v
Skill instructions tell Claude to:
    1. Run: python3 $PLUGIN_ROOT/hooks/scripts/memory_search_engine.py --query "<query>" --root <memory_root> --mode search
    2. Read the compact results (title, category, score, path)
    3. Decide which memories are relevant (LLM-as-judge)
    4. Read selected JSON files using Read tool
```

### Shared Engine Extraction
Extract from `memory_retrieve.py` into `hooks/scripts/memory_search_engine.py`:
- `build_fts_index(memories)` -> `Connection`
- `extract_body(data)` -> `str`
- `tokenize_for_query(text)` -> `list[str]`
- `build_fts_query(tokens)` -> `str | None`
- `query_fts(conn, query, mode)` -> `list[dict]`
- CLI interface: `--query`, `--root`, `--mode auto|search`

The hook (`memory_retrieve.py`) imports and calls the engine.
The skill invokes the engine as a subprocess (same as other scripts).

### Progressive Disclosure (2-layer)
**Layer 1 (compact list from script):**
```
Found 5 memories matching "authentication":

1. [DECISION] Chose JWT over session cookies (score: -3.2)
   Tags: auth, jwt | Updated: 2026-02-15
   Path: .claude/memory/decisions/jwt-over-session-cookies.json

2. [RUNBOOK] Fix OAuth2 redirect loop (score: -2.1)
   Tags: auth, oauth | Updated: 2026-02-10
   Path: .claude/memory/runbooks/fix-oauth-redirect-loop.json

Read any path above for full details.
```

**Layer 2 (Claude reads selected files):**
Claude uses the Read tool on the JSON files it judges relevant.
No additional infrastructure needed -- Claude's built-in Read tool IS the Layer 2.

### Skill Trigger Reliability
- Inject `<!-- Use /memory:search <topic> for deeper memory search -->` when auto-inject returns 0 results
- Diverse trigger words in skill frontmatter
- User can always invoke explicitly: `/memory:search authentication`

### Expected Outcome
- Effective recall: ~60% -> ~80%+ (on-demand fills auto-inject gaps)
- Effort: ~80-120 LOC skill + ~60-100 LOC engine extraction, 4-6 hours
- Risk: Low (purely additive, no existing behavior changed)

---

## Summary: 3-Day Implementation Schedule

| Time | Phase | Deliverable | LOC | Risk |
|------|-------|------------|-----|------|
| Day 1 AM | Phase 1a: Tokenizer fix | Coding terms preserved | ~15 | Near zero |
| Day 1 PM | Phase 1b: Body content scoring | Body matches add discriminating signal | ~60 | Near zero |
| Day 1 evening | Validate | Manual test with 5-10 queries | - | - |
| Day 2 | Phase 2a: FTS5 engine core | BM25 replaces keyword scoring | ~150 | Medium |
| Day 3 AM | Phase 2b: Threshold calibration + testing | Tuned auto-inject | ~50 | Low |
| Day 3 PM | Phase 3: Search skill + engine extraction | `/memory:search` available | ~150 | Low |

**Total: ~425-475 LOC, 3 focused days.**

---

## Risk Matrix

| Risk | Severity | Likelihood | Mitigation |
|------|----------|-----------|------------|
| FTS5 doesn't improve precision | High | Low | Phase 1 (body content) ships independently and is valuable regardless |
| FTS5 unavailable | Medium | Very Low | Error loudly; all modern Python 3 on Linux/WSL2/macOS has FTS5 |
| Prefix matching regression | High | Certain | Fixed: `"token"*` wildcard in FTS5 queries |
| BM25 threshold rejects everything | High | Certain | Fixed: no absolute threshold, Top-K + relative cutoff only |
| Coding term tokenization | Critical | Certain | Fixed: `tokenchars '_.-'` in FTS5, updated regex in Python |
| Skill trigger reliability (67%) | Medium | Medium | Hook-injected reminder, diverse triggers, explicit /command |
| WSL2 /mnt/c/ latency | Medium | Low | Document Linux filesystem recommendation |

---

## Files Changed

| File | Action | Phase |
|------|--------|-------|
| `hooks/scripts/memory_retrieve.py` | Modify (tokenizer + body content, then FTS5 rewrite) | 1, 2 |
| `hooks/scripts/memory_search_engine.py` | Create (shared FTS5 engine, CLI interface) | 3 |
| `skills/memory-search/SKILL.md` | Create (on-demand search skill) | 3 |
| `tests/test_memory_retrieve.py` | Update (FTS5 tests, body content tests) | 1, 2 |

---

## Configuration Changes

Minimal. Hardcode defaults, add config keys only as needed:

```json
{
  "retrieval": {
    "enabled": true,
    "max_inject": 3,
    "match_strategy": "fts5_bm25"
  }
}
```

- `match_strategy: "fts5_bm25"` (new default) or `"title_tags"` (legacy, for rollback)
- `max_inject: 3` (reduced from 5)
- All other parameters hardcoded with sensible defaults

---

## What This Plan Does NOT Do

1. **No transcript context parsing** -- deferred (marginal value, format risk)
2. **No fallback keyword engine** -- error if FTS5 unavailable
3. **No formal eval benchmark** -- manual testing sufficient for personal project
4. **No config key proliferation** -- hardcode defaults
5. **No MCP tools** -- no daemons, skill-based on-demand search
6. **No synonym maps** -- LLM-driven query expansion in skill
7. **No disk cache for FTS5** -- always rebuild in-memory

---

## Source Files (Full Team Output)

| File | Content | Author |
|------|---------|--------|
| `temp/rd-01-research-synthesis.md` | Research synthesis (343 lines) | synthesizer |
| `temp/rd-02-architecture-proposal.md` | Full architecture proposal (1083 lines) | architect |
| `temp/rd-03-skeptic-review.md` | Adversarial review (482 lines) | skeptic |
| `temp/rd-04-pragmatist-review.md` | Feasibility review (414 lines) | pragmatist |
| `temp/rd-05-consolidated-plan.md` | This consolidated plan | lead |

## External Validation Log

| Source | Key Opinion | Adopted? |
|--------|-------------|----------|
| Gemini 3.1 Pro (synthesizer) | FTS5 with porter, column weights 5/3/1, transcript last 2-3 turns | Partially (no transcript) |
| Gemini 2.5 Pro (synthesizer) | Body content "non-negotiable", FTS5 availability risk "very low" | Yes |
| Gemini 3.1 Pro (architect R1) | Ditch disk cache, robust query sanitization | Yes |
| Gemini 3.1 Pro (architect R2) | Negative score math fix, query dilution fix, payload size fix | Yes |
| Gemini 3.1 Pro (skeptic) | Every-invocation rebuild "reckless" for /mnt/c/ | Noted, accepted latency |
| Gemini 3 Pro (skeptic) | IDF volatile at small N, Top-K over thresholds | Partially (relative cutoff, not pure Top-K) |
| Gemini 3.1 Pro (pragmatist) | Do FTS5, wildcard prefixes mandatory | Yes |
| Gemini 3.0 Pro (pragmatist) | Don't rewrite to FTS5, just add weighted scoring | Rejected |
| Gemini 3.1 Pro (lead clink) | `tokenchars` solves tokenization natively, IDF ordering matters not magnitude | Yes |
| Vibe-check | Compress verification rounds, write final plan directly | Partially adopted |
