#!/usr/bin/env python3
"""Shared FTS5 search engine for claude-memory plugin.

Extracted from memory_retrieve.py (Session 3) for reuse by:
- memory_retrieve.py (UserPromptSubmit hook, auto-inject mode)
- CLI interface (on-demand search via skill)

Core search logic (tokenization, FTS5 indexing, querying, thresholding)
is IO-free. CLI wrapper handles file loading and path security checks.
Hook callers (memory_retrieve.py) handle their own IO and containment.

No external dependencies (stdlib + sqlite3 only).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Shared Constants
# ---------------------------------------------------------------------------

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

# Body content fields by category
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


# ---------------------------------------------------------------------------
# FTS5 Availability Check
# ---------------------------------------------------------------------------

try:
    import sqlite3
    _test_conn = sqlite3.connect(":memory:")
    _test_conn.execute("CREATE VIRTUAL TABLE _fts5_test USING fts5(c)")
    _test_conn.close()
    HAS_FTS5 = True
except Exception:
    HAS_FTS5 = False


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def tokenize(text: str, legacy: bool = False) -> set[str]:
    """Tokenize text. Use legacy=True for fallback keyword scoring path."""
    regex = _LEGACY_TOKEN_RE if legacy else _COMPOUND_TOKEN_RE
    words = regex.findall(text.lower())
    return {w for w in words if len(w) > 1 and w not in STOP_WORDS}


# ---------------------------------------------------------------------------
# Index Parsing
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Body Content Extraction
# ---------------------------------------------------------------------------

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
# FTS5 Index Building
# ---------------------------------------------------------------------------

def build_fts_index(entries: list[dict], include_body: bool = False) -> "sqlite3.Connection":
    """Build FTS5 in-memory index from parsed index entries.

    Args:
        entries: List of dicts from parse_index_line() (keys: title, tags, path, category).
                 For include_body=True, entries must also have a "body" key.
        include_body: If True, creates a body column in the FTS5 table for full-text
                      body search. Entries should have "body" key (default "").

    Returns the sqlite3 connection (caller must close).
    """
    conn = sqlite3.connect(":memory:")
    if include_body:
        conn.execute("""CREATE VIRTUAL TABLE memories USING fts5(
            title, tags, body, path UNINDEXED, category UNINDEXED
        )""")
        rows = []
        for e in entries:
            rows.append((
                e["title"],
                " ".join(sorted(e["tags"])) if isinstance(e["tags"], (set, list)) else str(e.get("tags", "")),
                e.get("body", ""),
                e["path"],
                e["category"],
            ))
        conn.executemany("INSERT INTO memories VALUES (?, ?, ?, ?, ?)", rows)
    else:
        conn.execute("""CREATE VIRTUAL TABLE memories USING fts5(
            title, tags, path UNINDEXED, category UNINDEXED
        )""")
        rows = []
        for e in entries:
            rows.append((
                e["title"],
                " ".join(sorted(e["tags"])) if isinstance(e["tags"], (set, list)) else str(e.get("tags", "")),
                e["path"],
                e["category"],
            ))
        conn.executemany("INSERT INTO memories VALUES (?, ?, ?, ?)", rows)
    return conn


# ---------------------------------------------------------------------------
# FTS5 Query Construction
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# FTS5 Query Execution
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Threshold / Top-K Selection
# ---------------------------------------------------------------------------

def apply_threshold(results: list[dict], mode: str = "auto",
                    max_inject: int | None = None) -> list[dict]:
    """Apply Top-K threshold with 25% noise floor.

    Limits: max_inject (if provided) overrides defaults.
    Defaults: MAX_AUTO=3 for auto-inject, MAX_SEARCH=10 for explicit search.
    Sorts by score (most negative = best), then CATEGORY_PRIORITY.
    Discards results where abs(score) < 25% of abs(best_score).
    """
    MAX_AUTO = 3
    MAX_SEARCH = 10
    if max_inject is not None:
        limit = max_inject
    else:
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


# ---------------------------------------------------------------------------
# CLI Interface
# ---------------------------------------------------------------------------

def _check_path_containment(json_path: Path, memory_root_resolved: Path) -> bool:
    """Check if a path is contained within the memory root directory.

    Used by CLI for security. Hook callers should use their own containment checks.
    """
    try:
        json_path.resolve().relative_to(memory_root_resolved)
        return True
    except ValueError:
        return False


def _sanitize_cli_title(title: str) -> str:
    """Sanitize title for CLI output (defense-in-depth against prompt injection)."""
    title = re.sub(r'[\x00-\x1f\x7f]', '', title)
    title = re.sub(r'[\u200b-\u200f\u2028-\u202f\u2060-\u2069\ufeff\U000e0000-\U000e007f]', '', title)
    title = title.replace(" -> ", " - ").replace("#tags:", "")
    title = title.strip()[:120]
    # XML-escape to prevent boundary breakout in LLM context
    title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', '&quot;')
    return title


def _cli_load_entries(memory_root: Path, mode: str,
                      include_retired: bool = False) -> list[dict]:
    """Load and parse index entries for CLI use.

    For mode="search", also reads JSON files to extract body text.
    Applies path containment checks. Filters retired/archived entries
    unless include_retired is True (only in search mode where JSON is read).
    """
    index_path = memory_root / "index.md"
    if not index_path.exists():
        return []

    memory_root_resolved = memory_root.resolve()

    entries = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        parsed = parse_index_line(line)
        if not parsed:
            continue

        # Path containment check: index paths are relative to project root
        # For CLI, memory_root IS the root (paths in index are relative to project root)
        # We need to find the project root from the memory_root
        project_root = memory_root.parent.parent
        json_path = project_root / parsed["path"]
        if not _check_path_containment(json_path, memory_root_resolved):
            continue

        if mode == "search":
            # Full-body mode: read JSON, extract body, check retired/archived
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                status = data.get("record_status", "active")
                if not include_retired and status in ("retired", "archived"):
                    continue
                parsed["body"] = extract_body_text(data)
                parsed["_status"] = status
                body_text = parsed["body"]
                parsed["_snippet"] = (body_text[:150] + "...") if len(body_text) > 150 else body_text
                parsed["_updated_at"] = data.get("updated_at", "")
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                parsed["body"] = ""
                parsed["_status"] = "active"
                parsed["_snippet"] = ""
                parsed["_updated_at"] = ""

        entries.append(parsed)

    return entries


def cli_search(query: str, memory_root: Path, mode: str = "auto",
               max_results: int | None = None,
               include_retired: bool = False) -> list[dict]:
    """Run a search query and return results as dicts.

    Args:
        query: User search query string.
        memory_root: Path to .claude/memory directory.
        mode: "auto" (title+tags, top-3) or "search" (full-body, top-10).
        max_results: Override default result limit.
        include_retired: Include retired/archived entries in results.

    Returns list of result dicts with keys: title, tags, path, category, score,
    and (search mode only) status, snippet, updated_at.
    """
    if not HAS_FTS5:
        return []

    entries = _cli_load_entries(memory_root, mode, include_retired)
    if not entries:
        return []

    # Build metadata lookup for enriching results (search mode)
    metadata = {}
    for e in entries:
        metadata[e["path"]] = {
            "status": e.get("_status", "active"),
            "snippet": e.get("_snippet", ""),
            "updated_at": e.get("_updated_at", ""),
        }

    include_body = (mode == "search")
    conn = build_fts_index(entries, include_body=include_body)

    try:
        prompt_tokens = list(tokenize(query))
        fts_query = build_fts_query(prompt_tokens)
        if not fts_query:
            return []

        results = query_fts(conn, fts_query, limit=30)
        results = apply_threshold(results, mode=mode, max_inject=max_results)

        # Enrich results with metadata from JSON reads
        for r in results:
            meta = metadata.get(r["path"], {})
            r["status"] = meta.get("status", "active")
            r["snippet"] = meta.get("snippet", "")
            r["updated_at"] = meta.get("updated_at", "")

        return results
    finally:
        conn.close()


def main():
    """CLI entry point for memory search."""
    parser = argparse.ArgumentParser(
        description="Search claude-memory entries using FTS5.",
        epilog="Example: python3 memory_search_engine.py --query 'authentication' "
               "--root /path/to/.claude/memory --mode search",
    )
    parser.add_argument("--query", "-q", required=True, help="Search query string")
    parser.add_argument("--root", "-r", required=True,
                        help="Path to .claude/memory directory")
    parser.add_argument("--mode", "-m", choices=["auto", "search"], default="auto",
                        help="Search mode: 'auto' (title+tags, top-3) or "
                             "'search' (full-body, top-10)")
    parser.add_argument("--max-results", "-n", type=int, default=None,
                        help="Override max results (default: 3 for auto, 10 for search)")
    parser.add_argument("--include-retired", action="store_true", default=False,
                        help="Include retired and archived memories in results")
    parser.add_argument("--format", "-f", choices=["json", "text"], default="json",
                        help="Output format (default: json)")

    args = parser.parse_args()
    memory_root = Path(args.root).resolve()

    # Clamp max-results to [1, 30]
    if args.max_results is not None:
        args.max_results = max(1, min(30, args.max_results))

    if not memory_root.is_dir():
        print(json.dumps({"error": "Memory root directory not found",
                           "query": args.query}))
        sys.exit(1)

    if not HAS_FTS5:
        print("[WARN] FTS5 unavailable in this Python/SQLite build", file=sys.stderr)
        print(json.dumps({"error": "FTS5 not available", "query": args.query}))
        sys.exit(1)

    results = cli_search(args.query, memory_root, args.mode, args.max_results,
                          args.include_retired)

    if args.format == "json":
        output = {
            "query": args.query,
            "total_results": len(results),
            "results": [
                {
                    "title": _sanitize_cli_title(r["title"]),
                    "category": r["category"].lower(),
                    "path": r["path"],
                    "tags": sorted(r.get("tags", set())),
                    "status": r.get("status", "active"),
                    "snippet": r.get("snippet", ""),
                    "updated_at": r.get("updated_at", ""),
                }
                for r in results
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        if not results:
            print("No results found.")
        else:
            for i, r in enumerate(results, 1):
                tags_str = ", ".join(sorted(r.get("tags", set())))
                safe_title = _sanitize_cli_title(r["title"])
                print(f"{i}. [{r['category']}] {safe_title}")
                if tags_str:
                    print(f"   Tags: {tags_str}")
                print(f"   Path: {r['path']}")
                print(f"   Score: {r['score']:.4f}")
                print()


if __name__ == "__main__":
    main()
