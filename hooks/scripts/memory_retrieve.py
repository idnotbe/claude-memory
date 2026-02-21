#!/usr/bin/env python3
"""Memory retrieval hook for claude-memory plugin (UserPromptSubmit).

Reads user prompt from stdin (hook input JSON), matches against
.claude/memory/index.md entries, outputs relevant memories to stdout.
Stdout is added to Claude's context automatically (exit 0).

Supports enriched index lines with #tags: suffix for higher-weight matching.

No external dependencies (stdlib only + memory_search_engine.py).
"""

import html
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# Import path safety: ensure sibling modules are findable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parent))

from memory_search_engine import (  # noqa: E402
    BODY_FIELDS,
    CATEGORY_PRIORITY,
    HAS_FTS5,
    STOP_WORDS,
    apply_threshold,
    build_fts_index,
    build_fts_query,
    extract_body_text,
    parse_index_line,
    query_fts,
    tokenize,
)

# How many top candidates to read JSON files for (recency + retired check)
_DEEP_CHECK_LIMIT = 20

# Recency window in days
_RECENCY_DAYS = 30


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

    # Check retired/archived status
    record_status = data.get("record_status", "active")
    if record_status in ("retired", "archived"):
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
    # Strip zero-width, bidirectional override, tag Unicode chars, and combining marks/variation selectors
    title = ''.join(c for c in title if unicodedata.category(c) not in ('Cf', 'Mn'))
    # Strip index-format injection markers
    title = title.replace(" -> ", " - ").replace("#tags:", "")
    # Truncate to 120 chars first (matches write-side max_length), then escape
    # (escape after truncate to avoid splitting mid-entity, e.g. "&amp;" cut to "&am")
    title = title.strip()[:120]
    # Escape XML-sensitive characters to prevent data boundary breakout
    title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', '&quot;')
    return title


def confidence_label(score: float, best_score: float) -> str:
    """Map score to confidence bracket based on ratio to best score.

    Works for both BM25 (negative, more negative = better) and legacy
    (positive, higher = better) scores via abs().
    """
    if best_score == 0:
        return "low"
    ratio = abs(score) / abs(best_score)
    if ratio >= 0.75:
        return "high"
    elif ratio >= 0.40:
        return "medium"
    return "low"


def _check_path_containment(json_path: Path, memory_root_resolved: Path) -> bool:
    """Check if a path is contained within the memory root directory."""
    try:
        json_path.resolve().relative_to(memory_root_resolved)
        return True
    except ValueError:
        return False


def score_with_body(conn: "sqlite3.Connection", fts_query: str, user_prompt: str,
                    top_k_paths: int, memory_root: Path, mode: str = "auto",
                    max_inject: int | None = None) -> list[dict]:
    """Hybrid scoring: FTS5 title+tags ranking + body content bonus.

    Steps:
    1. Get initial rankings from FTS5 MATCH on title+tags
    2. SECURITY: Pre-filter ALL entries for path containment
    3. Check retired status on ALL path-contained entries (M2 fix)
    4. For top-K non-retired candidates, extract body text and compute body bonus
    5. Apply threshold and return results

    SECURITY: Path containment check prevents reading files outside memory_root.
    """
    # Step 1: Get initial rankings from title+tags FTS5
    initial = query_fts(conn, fts_query, limit=top_k_paths * 3)

    # Resolve paths relative to project root (memory_root is .claude/memory)
    # Index paths are project-relative (e.g. .claude/memory/decisions/foo.json)
    project_root = memory_root.parent.parent
    memory_root_resolved = memory_root.resolve()

    # Step 2: SECURITY: Pre-filter ALL entries for path containment (not just top_k_paths).
    # Without this, entries beyond top_k_paths bypass containment checks entirely,
    # which is a regression from the legacy path.
    initial = [
        r for r in initial
        if _check_path_containment(project_root / r["path"], memory_root_resolved)
    ]

    # Step 3 (M2 fix): Check retired status on ALL path-contained entries,
    # not just top_k_paths. This prevents retired entries from slipping through
    # when they rank beyond top_k_paths in initial FTS5 results.
    for result in initial:
        json_path = project_root / result["path"]
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            if data.get("record_status") in ("retired", "archived"):
                result["_retired"] = True
                result["body_bonus"] = 0
                continue
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            # Can't read file -- assume not retired, no body bonus
            result["body_bonus"] = 0
            continue

        # Step 4: Extract body only for top-K candidates (expensive operation)
        # Check if this result is within top_k_paths of the non-retired entries seen so far
        result["_data"] = data  # Cache for body extraction below

    # Filter retired entries
    initial = [r for r in initial if not r.get("_retired")]

    # Body extraction for top-K candidates only (performance optimization)
    query_tokens = tokenize(user_prompt)
    for result in initial[:top_k_paths]:
        data = result.pop("_data", None)
        if data is not None:
            body_text = extract_body_text(data)
            body_tokens = tokenize(body_text)
            body_matches = query_tokens & body_tokens
            result["body_bonus"] = min(3, len(body_matches))
        # body_bonus already set to 0 for file-read failures above

    # Clean up cached data for remaining entries
    for result in initial[top_k_paths:]:
        result.pop("_data", None)

    # Step 5: Re-rank with body bonus
    for r in initial:
        r["raw_bm25"] = r["score"]  # Preserve raw BM25 for debugging/benchmarking
        r["score"] = r["score"] - r.get("body_bonus", 0)  # More negative = better

    return apply_threshold(initial, mode, max_inject=max_inject)


def _output_results(top: list[dict], category_descriptions: dict[str, str]) -> None:
    """Output matched memories in XML element format.

    Each result is a <result> element with category and confidence as XML attributes
    (system-controlled, structurally separated from user content).
    Element body contains user content (title, path, tags) -- all XML-escaped.
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

    # Compute best score for confidence labeling
    best_score = max((abs(entry.get("score", 0)) for entry in top), default=0)

    print(f"<memory-context source=\".claude/memory/\"{desc_attr}>")
    for entry in top:
        safe_title = _sanitize_title(entry["title"])
        tags = entry.get("tags", set())
        safe_tags = []
        for t in tags:
            # Strip Cf+Mn Unicode categories (zero-width, bidi, combining marks, variation selectors)
            val = ''.join(c for c in t if unicodedata.category(c) not in ('Cf', 'Mn'))
            val = html.escape(val).strip()
            if val:
                safe_tags.append(val)
        tags_str = f" #tags:{','.join(sorted(safe_tags))}" if safe_tags else ""
        safe_path = html.escape(entry["path"])
        cat = html.escape(entry["category"])
        conf = confidence_label(entry.get("score", 0), best_score)
        print(f'<result category="{cat}" confidence="{conf}">{safe_title} -> {safe_path}{tags_str}</result>')
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

    # Parse index entries once (L1 fix: eliminates double-read of index.md)
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
            # L1/L2 fix: build FTS5 index from already-parsed entries (no re-read)
            conn = build_fts_index(entries)
            try:
                results = score_with_body(conn, fts_query, user_prompt,
                                          max(10, max_inject), memory_root, "auto",
                                          max_inject=max_inject)
            finally:
                conn.close()
            if results:
                top = results
                _output_results(top, category_descriptions)
                return
            # Valid query but no results -- hint at manual search
            print("<!-- No matching memories found. If project context is needed, use /memory:search <topic> -->")
        # No valid query tokens (all stop-words) -- exit silently without hint
        sys.exit(0)

    # -----------------------------------------------------------------------
    # Legacy keyword path (fallback when FTS5 unavailable or strategy=title_tags)
    # -----------------------------------------------------------------------
    if not HAS_FTS5 and match_strategy == "fts5_bm25":
        print("[WARN] FTS5 unavailable; using keyword fallback", file=sys.stderr)

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
        # Valid query but no entries scored -- hint at manual search
        print("<!-- No matching memories found. If project context is needed, use /memory:search <topic> -->")
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
        if not _check_path_containment(file_path, memory_root_resolved):
            continue
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
        if not _check_path_containment(file_path, memory_root_resolved):
            continue
        final.append((text_score, priority, entry))

    if not final:
        # Valid query but no results survived deep check -- hint at manual search
        print("<!-- No matching memories found. If project context is needed, use /memory:search <topic> -->")
        sys.exit(0)

    # Re-sort with adjusted scores
    final.sort(key=lambda x: (-x[0], x[1]))
    top_entries = final[:max_inject]

    # Convert legacy (score, priority, entry) tuples to dict format for _output_results
    # Attach score to each entry for confidence labeling
    top_list = []
    for score, _, entry in top_entries:
        entry["score"] = score
        top_list.append(entry)
    _output_results(top_list, category_descriptions)


if __name__ == "__main__":
    main()
