#!/usr/bin/env python3
"""Memory retrieval hook for claude-memory plugin (UserPromptSubmit).

Reads user prompt from stdin (hook input JSON), matches against
.claude/memory/index.md entries, outputs relevant memories to stdout.
Stdout is added to Claude's context automatically (exit 0).

Supports enriched index lines with #tags: suffix for higher-weight matching.

No external dependencies (stdlib only).
"""

import html
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Words too common to be useful for matching
STOP_WORDS = frozenset({
    "a", "an", "the", "is", "was", "are", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had", "will", "would", "could",
    "can", "should", "may", "might", "shall", "must",
    "i", "you", "we", "they", "he", "she", "it", "me", "my", "your",
    "this", "that", "these", "those", "what", "which", "who", "whom",
    "how", "when", "where", "why", "if", "then", "else", "so",
    "and", "or", "but", "not", "no", "yes", "to", "of", "in", "on",
    "at", "for", "with", "from", "by", "about", "up", "out", "into",
    "just", "also", "very", "too", "let", "please", "help", "need",
    "want", "know", "think", "make", "like", "use", "get", "go", "see",
    # Additional 2-char stopwords needed after lowering token length minimum to 2
    "as", "am", "us", "vs",
})

# Higher priority = injected first when multiple match
CATEGORY_PRIORITY = {
    "DECISION": 1,
    "CONSTRAINT": 2,
    "PREFERENCE": 3,
    "RUNBOOK": 4,
    "TECH_DEBT": 5,
    "SESSION_SUMMARY": 6,
}

# Regex for enriched index lines: - [CAT] title -> path #tags:t1,t2,...
_INDEX_RE = re.compile(
    r"^-\s+\[([A-Z_]+)\]\s+(.+?)\s+->\s+(\S+)"
    r"(?:\s+#tags:(.+))?$"
)

# Legacy tokenizer -- MUST be preserved for fallback scoring path
_LEGACY_TOKEN_RE = re.compile(r"[a-z0-9]+")

# New compound-preserving tokenizer -- for FTS5 query construction ONLY
_COMPOUND_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_.\-]*[a-z0-9]|[a-z0-9]+")

# How many top candidates to read JSON files for (recency + retired check)
_DEEP_CHECK_LIMIT = 20

# Recency window in days
_RECENCY_DAYS = 30


def tokenize(text: str, legacy: bool = False) -> set[str]:
    """Tokenize text. Use legacy=True for fallback keyword scoring path."""
    regex = _LEGACY_TOKEN_RE if legacy else _COMPOUND_TOKEN_RE
    words = regex.findall(text.lower())
    return {w for w in words if len(w) > 1 and w not in STOP_WORDS}


def parse_index_line(line: str) -> dict | None:
    """Parse an index line into components.

    Returns dict with keys: category, title, path, tags, raw
    or None if the line doesn't match.
    Backward compatible: lines without #tags: get empty tag set.
    """
    m = _INDEX_RE.match(line.strip())
    if not m:
        return None
    tags_str = m.group(4)
    tags = [t.strip().lower() for t in tags_str.split(",") if t.strip()] if tags_str else []
    return {
        "category": m.group(1),
        "title": m.group(2).strip(),
        "path": m.group(3).strip(),
        "tags": set(tags),
        "raw": line.strip(),
    }


def score_entry(prompt_words: set[str], entry: dict) -> int:
    """Score an index entry against prompt words.

    Scoring:
    - Exact word match on title: 2 points
    - Exact tag match: 3 points
    - Prefix match (4+ chars) on title or tags: 1 point
    """
    title_tokens = tokenize(entry["title"], legacy=True)
    entry_tags = entry["tags"]

    # Exact title word matches
    exact_title = prompt_words & title_tokens
    score = len(exact_title) * 2

    # Exact tag matches
    exact_tags = prompt_words & entry_tags
    score += len(exact_tags) * 3

    # Prefix matches on title and tags (4+ char tokens not already matched)
    already_matched = exact_title | exact_tags
    combined_targets = title_tokens | entry_tags
    for pw in prompt_words - already_matched:
        if len(pw) >= 4:
            # Forward prefix: prompt word is prefix of target (e.g. "auth" matches "authentication")
            if any(target.startswith(pw) for target in combined_targets):
                score += 1
            # Reverse prefix: target is prefix of prompt word (e.g. "authentication" matches "auth" tag)
            # Require target >= 4 chars to avoid short false positives (e.g. "cat" matching "category")
            elif any(pw.startswith(target) and len(target) >= 4 for target in combined_targets):
                score += 1

    return score


def score_description(prompt_words: set[str], description_tokens: set[str]) -> int:
    """Score prompt against category description tokens.

    Lower weight than tag matches (1 point per exact match, capped).
    Prefix matches (4+ chars) contribute 0.5 points (floored to int at end).
    Total capped at 2 to prevent descriptions from dominating scoring.
    """
    if not description_tokens or not prompt_words:
        return 0

    score = 0.0

    # Exact matches: 1 point each
    exact = prompt_words & description_tokens
    score += len(exact) * 1.0

    # Prefix matches on remaining tokens (4+ char prompt words)
    already_matched = exact
    for pw in prompt_words - already_matched:
        if len(pw) >= 4:
            if any(dt.startswith(pw) for dt in description_tokens):
                score += 0.5

    # Cap at 2 to prevent descriptions from dominating
    # Use int(score + 0.5) for standard round-half-up (avoids Python banker's rounding)
    return min(2, int(score + 0.5))


def check_recency(file_path: Path) -> tuple[bool, bool]:
    """Read a JSON memory file and check recency and retired status.

    Returns (is_retired, is_recent).
    If file cannot be read, returns (False, False).
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False, False

    # Check retired status
    record_status = data.get("record_status", "active")
    if record_status == "retired":
        return True, False

    # Check recency
    updated_at_str = data.get("updated_at")
    if not updated_at_str:
        return False, False

    try:
        # Parse ISO 8601 datetime
        updated_at_str = updated_at_str.replace("Z", "+00:00")
        updated_at = datetime.fromisoformat(updated_at_str)
        # Ensure timezone-aware comparison
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        age_days = (now - updated_at).days
        return False, age_days <= _RECENCY_DAYS
    except (ValueError, TypeError):
        return False, False


def _sanitize_title(title: str) -> str:
    """Sanitize a title for safe injection into prompt context."""
    # Strip control characters
    title = re.sub(r'[\x00-\x1f\x7f]', '', title)
    # Strip zero-width, bidirectional override, and tag Unicode characters
    title = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u2069\ufeff\U000e0000-\U000e007f]', '', title)
    # Strip index-format injection markers
    title = title.replace(" -> ", " - ").replace("#tags:", "")
    # Truncate to 120 chars first (matches write-side max_length), then escape
    # (escape after truncate to avoid splitting mid-entity, e.g. "&amp;" cut to "&am")
    title = title.strip()[:120]
    # Escape XML-sensitive characters to prevent data boundary breakout
    title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', '&quot;')
    return title


# ---------------------------------------------------------------------------
# Body content extraction (Phase 1b)
# ---------------------------------------------------------------------------

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


def extract_body_text(data: dict) -> str:
    """Extract searchable body text from memory JSON."""
    category = data.get("category", "")
    content = data.get("content", {})
    if not isinstance(content, dict):
        return ""
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
    return " ".join(parts)[:2000]


# ---------------------------------------------------------------------------
# FTS5 availability check (Phase 1c)
# ---------------------------------------------------------------------------

try:
    import sqlite3
    _test = sqlite3.connect(":memory:")
    _test.execute("CREATE VIRTUAL TABLE _t USING fts5(c)")
    _test.close()
    HAS_FTS5 = True
except Exception:
    HAS_FTS5 = False
    print("[WARN] FTS5 unavailable; using keyword fallback", file=sys.stderr)


# ---------------------------------------------------------------------------
# FTS5 Engine Functions (Phase 2a)
# ---------------------------------------------------------------------------

def build_fts_index_from_index(index_path: Path) -> "sqlite3.Connection":
    """Build FTS5 in-memory index from index.md (1 file read, no JSON parsing).

    Parses index.md using parse_index_line(), creates an in-memory FTS5 table
    with title/tags (indexed) and path/category (unindexed), inserts all entries.
    Returns the sqlite3 connection (caller must close).
    """
    conn = sqlite3.connect(":memory:")
    conn.execute("""CREATE VIRTUAL TABLE memories USING fts5(
        title, tags, path UNINDEXED, category UNINDEXED
    )""")
    rows = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_index_line(line)
        if parsed:
            rows.append((parsed["title"], " ".join(parsed["tags"]),
                         parsed["path"], parsed["category"]))
    conn.executemany("INSERT INTO memories VALUES (?, ?, ?, ?)", rows)
    return conn


def build_fts_query(tokens: list[str]) -> str | None:
    """Build FTS5 MATCH query string from tokenized user prompt.

    Smart wildcard strategy:
    - Compound tokens (containing _, ., -): exact phrase match "user_id" (no wildcard)
    - Single tokens: prefix wildcard "auth"* for broader matching

    Returns None if no safe tokens remain after filtering.
    """
    safe = []
    for t in tokens:
        cleaned = re.sub(r'[^a-z0-9_.\-]', '', t.lower()).strip('_.-')
        if cleaned and cleaned not in STOP_WORDS and len(cleaned) > 1:
            # Compound tokens: exact phrase match (no wildcard)
            # Single tokens: prefix wildcard for broader matching
            if any(c in cleaned for c in '_.-'):
                safe.append(f'"{cleaned}"')      # exact: "user_id"
            else:
                safe.append(f'"{cleaned}"*')     # prefix: "auth"*
    if not safe:
        return None
    return " OR ".join(safe)


def query_fts(conn: "sqlite3.Connection", fts_query: str, limit: int = 15) -> list[dict]:
    """Execute FTS5 MATCH query and return ranked results.

    Returns list of dicts with keys: title, tags (as set), path, category, score.
    Score is the BM25 rank value (more negative = better match).
    """
    cursor = conn.execute(
        "SELECT title, tags, path, category, rank FROM memories "
        "WHERE memories MATCH ? ORDER BY rank LIMIT ?",
        (fts_query, limit),
    )
    results = []
    for title, tags_str, path, category, rank in cursor:
        tags = set(t.strip() for t in tags_str.split() if t.strip()) if tags_str else set()
        results.append({
            "title": title,
            "tags": tags,
            "path": path,
            "category": category,
            "score": rank,
        })
    return results


def apply_threshold(results: list[dict], mode: str = "auto") -> list[dict]:
    """Apply Top-K threshold with 25% noise floor.

    Limits: MAX_AUTO=3 for auto-inject, MAX_SEARCH=10 for explicit search.
    Sorts by score (most negative = best), then CATEGORY_PRIORITY.
    Discards results where abs(score) < 25% of abs(best_score).
    """
    MAX_AUTO = 3
    MAX_SEARCH = 10
    limit = MAX_AUTO if mode == "auto" else MAX_SEARCH

    if not results:
        return []

    # Sort by score (most negative = best), then category priority
    results.sort(key=lambda r: (r["score"], CATEGORY_PRIORITY.get(r["category"], 10)))

    # Noise floor: discard results below 25% of best score
    best_abs = abs(results[0]["score"])
    if best_abs > 1e-10:
        noise_floor = best_abs * 0.25
        results = [r for r in results if abs(r["score"]) >= noise_floor]

    return results[:limit]


def _check_path_containment(json_path: Path, memory_root_resolved: Path) -> bool:
    """Check if a path is contained within the memory root directory."""
    try:
        json_path.resolve().relative_to(memory_root_resolved)
        return True
    except ValueError:
        return False


def score_with_body(conn: "sqlite3.Connection", fts_query: str, user_prompt: str,
                    top_k_paths: int, memory_root: Path, mode: str = "auto") -> list[dict]:
    """Hybrid scoring: FTS5 title+tags ranking + body content bonus.

    Steps:
    1. Get initial rankings from FTS5 MATCH on title+tags
    2. For top-K candidates, read JSON file, extract body text, compute body matches
    3. Apply body bonus (capped at 3) to final score (more negative = better)
    4. Apply threshold and return results

    SECURITY: Path containment check prevents reading files outside memory_root.
    """
    # Step 1: Get initial rankings from title+tags FTS5
    initial = query_fts(conn, fts_query, limit=top_k_paths * 3)

    # Resolve paths relative to project root (memory_root is .claude/memory)
    # Index paths are project-relative (e.g. .claude/memory/decisions/foo.json)
    project_root = memory_root.parent.parent
    memory_root_resolved = memory_root.resolve()

    # SECURITY: Pre-filter ALL entries for path containment (not just top_k_paths).
    # Without this, entries beyond top_k_paths bypass containment checks entirely,
    # which is a regression from the legacy path (lines 612-618 check all entries).
    initial = [
        r for r in initial
        if _check_path_containment(project_root / r["path"], memory_root_resolved)
    ]

    # Step 2: Read JSON for top candidates, extract body
    for result in initial[:top_k_paths]:
        json_path = project_root / result["path"]
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            # Defensive: skip retired entries even if they remain in index
            if data.get("record_status") == "retired":
                result["_retired"] = True
                result["body_bonus"] = 0
                continue
            body_text = extract_body_text(data)
            body_tokens = tokenize(body_text)
            query_tokens = tokenize(user_prompt)
            body_matches = query_tokens & body_tokens
            result["body_bonus"] = min(3, len(body_matches))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            result["body_bonus"] = 0

    # Step 3: Filter retired, then re-rank with body bonus
    initial = [r for r in initial if not r.get("_retired")]
    for r in initial:
        r["score"] = r["score"] - r.get("body_bonus", 0)  # More negative = better

    return apply_threshold(initial, mode)


def _output_results(top: list[dict], category_descriptions: dict[str, str]) -> None:
    """Output matched memories in the standard XML format.

    Shared between FTS5 and legacy paths for consistent output format.
    Applies all security checks: _sanitize_title, XML escaping, safe key sanitization.
    """
    desc_attr = ""
    if category_descriptions:
        desc_parts = []
        for cat_key, desc in sorted(category_descriptions.items()):
            safe_desc = _sanitize_title(desc)
            safe_key = re.sub(r'[^a-z_]', '', cat_key.lower())
            if not safe_key:
                continue
            desc_parts.append(f"{safe_key}={safe_desc}")
        if desc_parts:
            desc_attr = " descriptions=\"" + "; ".join(desc_parts) + "\""

    print(f"<memory-context source=\".claude/memory/\"{desc_attr}>")
    for entry in top:
        safe_title = _sanitize_title(entry["title"])
        tags = entry.get("tags", set())
        tags_str = f" #tags:{','.join(sorted(html.escape(t) for t in tags))}" if tags else ""
        safe_path = html.escape(entry["path"])
        cat = entry["category"]
        print(f"- [{cat}] {safe_title} -> {safe_path}{tags_str}")
    print("</memory-context>")


def main():
    # Read hook input from stdin
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            sys.exit(0)
        hook_input = json.loads(raw)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    user_prompt = hook_input.get("user_prompt", "")
    cwd = hook_input.get("cwd", os.getcwd())

    # Skip very short prompts (greetings, acks)
    if len(user_prompt.strip()) < 10:
        sys.exit(0)

    # Locate memory root
    memory_root = Path(cwd) / ".claude" / "memory"
    index_path = memory_root / "index.md"

    # Rebuild index on demand if missing (derived artifact pattern).
    # index.md may be .gitignored -- rebuild from authoritative JSON files.
    if not index_path.exists() and memory_root.is_dir():
        import subprocess
        index_tool = Path(__file__).parent / "memory_index.py"
        if index_tool.exists():
            try:
                subprocess.run(
                    [sys.executable, str(index_tool), "--rebuild", "--root", str(memory_root)],
                    capture_output=True, timeout=10,
                )
            except subprocess.TimeoutExpired:
                pass

    if not index_path.exists():
        sys.exit(0)

    # Check retrieval config
    max_inject = 3  # Reduced from 5: FTS5 BM25 is more precise, fewer results needed
    match_strategy = "fts5_bm25"
    category_descriptions: dict[str, str] = {}
    config_path = memory_root / "memory-config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            retrieval = config.get("retrieval", {})
            if not retrieval.get("enabled", True):
                sys.exit(0)
            raw_inject = retrieval.get("max_inject", 3)
            try:
                max_inject = max(0, min(20, int(raw_inject)))
            except (ValueError, TypeError, OverflowError):
                max_inject = 3
                print(
                    f"[WARN] Invalid max_inject value: {raw_inject!r}; using default 3",
                    file=sys.stderr,
                )
            match_strategy = retrieval.get("match_strategy", "fts5_bm25")
            # Load category descriptions
            categories_raw = config.get("categories", {})
            if isinstance(categories_raw, dict):
                for cat_key, cat_val in categories_raw.items():
                    if isinstance(cat_val, dict):
                        desc = cat_val.get("description", "")
                        if isinstance(desc, str) and desc:
                            category_descriptions[cat_key.lower()] = desc[:500]
        except (json.JSONDecodeError, KeyError, OSError):
            pass

    if max_inject == 0:
        sys.exit(0)

    # Parse index entries
    entries = []
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = parse_index_line(line)
                if parsed:
                    entries.append(parsed)
    except OSError:
        sys.exit(0)

    if not entries:
        sys.exit(0)

    # -----------------------------------------------------------------------
    # FTS5 BM25 path (default when FTS5 is available)
    # -----------------------------------------------------------------------
    if HAS_FTS5 and match_strategy == "fts5_bm25":
        prompt_tokens = list(tokenize(user_prompt))  # compound tokenizer (legacy=False)
        fts_query = build_fts_query(prompt_tokens)
        if fts_query:
            conn = build_fts_index_from_index(index_path)
            try:
                results = score_with_body(conn, fts_query, user_prompt,
                                          10, memory_root, "auto")
            finally:
                conn.close()
            if results:
                top = results[:max_inject]
                _output_results(top, category_descriptions)
                return
        # No valid query tokens or no results -- exit silently
        sys.exit(0)

    # -----------------------------------------------------------------------
    # Legacy keyword path (fallback when FTS5 unavailable or strategy=title_tags)
    # -----------------------------------------------------------------------
    # Tokenize prompt (legacy=True for backward-compatible keyword scoring path)
    prompt_words = tokenize(user_prompt, legacy=True)

    if not prompt_words:
        sys.exit(0)

    # Pre-tokenize category descriptions for scoring
    desc_tokens_by_cat: dict[str, set[str]] = {}
    for cat_key, desc in category_descriptions.items():
        desc_tokens_by_cat[cat_key.upper()] = tokenize(desc, legacy=True)

    # Pass 1: Score each entry by text matching (title + tags + description)
    scored = []
    for entry in entries:
        text_score = score_entry(prompt_words, entry)
        # Add description-based score only for entries that already matched on title/tags.
        # Without this guard, all entries in a category flood results when the category
        # description matches the prompt (even if the entry itself is unrelated).
        cat_desc_tokens = desc_tokens_by_cat.get(entry["category"], set())
        if cat_desc_tokens and text_score > 0:
            text_score += score_description(prompt_words, cat_desc_tokens)
        if text_score > 0:
            priority = CATEGORY_PRIORITY.get(entry["category"], 10)
            scored.append((text_score, priority, entry))

    if not scored:
        sys.exit(0)

    # Sort: highest score first, then by category priority
    scored.sort(key=lambda x: (-x[0], x[1]))

    # Pass 2: Deep check top candidates for recency bonus + retired exclusion
    # Resolve paths relative to project root (memory_root is .claude/memory)
    project_root = memory_root.parent.parent
    memory_root_resolved = memory_root.resolve()
    final = []
    for text_score, priority, entry in scored[:_DEEP_CHECK_LIMIT]:
        file_path = project_root / entry["path"]
        # A2: Containment check - prevent path traversal via crafted index entries.
        # Note: absolute entry["path"] values are also caught (Path('/x') / '/abs' == Path('/abs')).
        try:
            file_path.resolve().relative_to(memory_root_resolved)
        except ValueError:
            continue  # Skip entries outside memory root
        is_retired, is_recent = check_recency(file_path)

        # Defensive: skip retired entries even if they somehow remain in index
        if is_retired:
            continue

        final_score = text_score + (1 if is_recent else 0)
        final.append((final_score, priority, entry))

    # Also include entries beyond deep-check limit (no recency bonus, no retired check).
    # Safety assumption: index.md only contains active entries (rebuild_index filters inactive).
    # A stale index could theoretically include retired entries here, but performance cost
    # of reading JSON for low-ranked results outweighs the edge case risk.
    # A2 extended: apply cheap containment check here too so malicious paths never reach output.
    for text_score, priority, entry in scored[_DEEP_CHECK_LIMIT:]:
        file_path = project_root / entry["path"]
        try:
            file_path.resolve().relative_to(memory_root_resolved)
        except ValueError:
            continue  # Skip entries outside memory root
        final.append((text_score, priority, entry))

    if not final:
        sys.exit(0)

    # Re-sort with adjusted scores
    final.sort(key=lambda x: (-x[0], x[1]))
    top_entries = final[:max_inject]

    # Convert legacy (score, priority, entry) tuples to dict format for _output_results
    _output_results([e for _, _, e in top_entries], category_descriptions)


if __name__ == "__main__":
    main()
