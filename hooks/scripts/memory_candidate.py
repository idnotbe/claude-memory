#!/usr/bin/env python3
"""Candidate selection + structural verification for ACE consolidation.

Reads index.md, scores entries against new information, returns the best
candidate (or determines CREATE/NOOP). Called by the main agent once per
save operation.

Usage:
  python3 memory_candidate.py --category tech_debt --new-info "..." \
    [--lifecycle-event resolved] [--root MEMORY_ROOT_DIR]

No external dependencies (stdlib only).
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Same stop words as memory_retrieve.py
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
})

CATEGORY_FOLDERS = {
    "session_summary": "sessions",
    "decision": "decisions",
    "runbook": "runbooks",
    "constraint": "constraints",
    "tech_debt": "tech-debt",
    "preference": "preferences",
}

CATEGORY_DISPLAY = {
    "session_summary": "SESSION_SUMMARY",
    "decision": "DECISION",
    "runbook": "RUNBOOK",
    "constraint": "CONSTRAINT",
    "tech_debt": "TECH_DEBT",
    "preference": "PREFERENCE",
}

# Categories where triage-initiated DELETE is not allowed
DELETE_DISALLOWED = frozenset({"decision", "preference", "session_summary"})

# Category-specific content fields for key_fields excerpt
CATEGORY_KEY_FIELDS = {
    "session_summary": ["goal", "outcome"],
    "decision": ["context", "decision", "rationale"],
    "runbook": ["trigger", "root_cause"],
    "constraint": ["rule", "impact"],
    "tech_debt": ["description", "reason_deferred"],
    "preference": ["topic", "value", "reason"],
}

VALID_LIFECYCLE_EVENTS = frozenset({
    "resolved", "removed", "reversed", "superseded", "deprecated",
})

# Tokenizer: extract word-like tokens (letters and digits)
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Index line parser: - [CAT] title -> path #tags:t1,t2,...
_INDEX_RE = re.compile(
    r"^-\s+\[([A-Z_]+)\]\s+(.+?)\s+->\s+(\S+)"
    r"(?:\s+#tags:(.+))?$"
)

# Default memory root (components joined at runtime to avoid literal path)
_DEFAULT_ROOT_PARTS = [".claude", "memory"]


def tokenize(text: str) -> set[str]:
    """Extract meaningful lowercase tokens from text."""
    tokens = set()
    for word in _TOKEN_RE.findall(text.lower()):
        if word not in STOP_WORDS and len(word) > 2:
            tokens.add(word)
    return tokens


def parse_index_line(line: str) -> dict | None:
    """Parse an enriched index line into components.

    Returns dict with keys: category_display, title, path, tags
    or None if the line doesn't match.
    """
    m = _INDEX_RE.match(line.strip())
    if not m:
        return None
    cat_display = m.group(1)
    title = m.group(2).strip()
    path = m.group(3).strip()
    tags_str = m.group(4)
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []
    return {
        "category_display": cat_display,
        "title": title,
        "path": path,
        "tags": tags,
    }


def score_entry(new_info_tokens: set[str], entry: dict) -> int:
    """Score an index entry against new_info tokens.

    Scoring:
    - Exact word match on title: 2 points
    - Tag match: 3 points
    - Prefix match (4+ chars) on title: 1 point
    """
    score = 0

    # Tokenize title only (not path -- avoids path pollution)
    title_tokens = tokenize(entry["title"])

    # Exact title word matches
    exact_matches = new_info_tokens & title_tokens
    score += len(exact_matches) * 2

    # Tag matches (exact, case-insensitive)
    entry_tags_lower = {t.lower() for t in entry["tags"]}
    tag_matches = new_info_tokens & entry_tags_lower
    score += len(tag_matches) * 3

    # Prefix matches on title + tags (4+ char tokens not already matched)
    remaining = new_info_tokens - exact_matches - tag_matches
    prefix_targets = title_tokens | entry_tags_lower
    for pw in remaining:
        if len(pw) >= 4:
            if any(tw.startswith(pw) for tw in prefix_targets):
                score += 1

    return score


def build_excerpt(file_path: Path, category: str) -> dict | None:
    """Build a structured excerpt from a candidate JSON file.

    Returns excerpt dict or None if file cannot be read.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"WARNING: Could not read candidate file {file_path}: {e}", file=sys.stderr)
        return None

    # Build key_fields from category-specific content fields
    content = data.get("content", {})
    key_fields = {}
    fields = CATEGORY_KEY_FIELDS.get(category, [])
    for field in fields:
        value = content.get(field)
        if value is None:
            continue
        # Handle list fields: join into string
        if isinstance(value, list):
            value = "; ".join(str(v) for v in value)
        value = str(value)[:200]
        key_fields[field] = value

    # Derive last_change_summary
    changes = data.get("changes", [])
    if changes and isinstance(changes, list):
        last_change = changes[-1]
        last_change_summary = last_change.get("summary", "Unknown change")
    else:
        last_change_summary = "Initial creation"

    return {
        "title": data.get("title", ""),
        "record_status": data.get("record_status", "active"),
        "tags": data.get("tags", []),
        "last_change_summary": last_change_summary,
        "key_fields": key_fields,
    }


def main():
    default_root = str(Path(*_DEFAULT_ROOT_PARTS))

    parser = argparse.ArgumentParser(
        description="ACE candidate selection + structural verification."
    )
    parser.add_argument(
        "--category", required=True,
        choices=list(CATEGORY_FOLDERS.keys()),
        help="Memory category to search within",
    )
    parser.add_argument(
        "--new-info", required=True,
        help="New information to match against existing entries",
    )
    parser.add_argument(
        "--lifecycle-event",
        choices=sorted(VALID_LIFECYCLE_EVENTS),
        default=None,
        help="Lifecycle event (resolved, removed, reversed, superseded, deprecated)",
    )
    parser.add_argument(
        "--root", default=default_root,
        help="Root directory of memory storage",
    )
    args = parser.parse_args()

    root = Path(args.root)
    index_path = root / "index.md"

    # Rebuild index on demand if missing (derived artifact pattern)
    if not index_path.exists() and root.is_dir():
        import subprocess
        index_tool = Path(__file__).parent / "memory_index.py"
        if index_tool.exists():
            try:
                subprocess.run(
                    [sys.executable, str(index_tool), "--rebuild", "--root", str(root)],
                    capture_output=True, timeout=10,
                )
            except subprocess.TimeoutExpired:
                pass

    if not index_path.exists():
        print(f"ERROR: index.md not found at {index_path}", file=sys.stderr)
        sys.exit(1)

    category = args.category
    new_info = args.new_info
    lifecycle_event = args.lifecycle_event
    target_display = CATEGORY_DISPLAY[category]

    # Parse index, filter to target category
    entries = []
    try:
        with open(index_path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = parse_index_line(line)
                if parsed and parsed["category_display"] == target_display:
                    entries.append(parsed)
    except OSError as e:
        print(f"ERROR: Could not read index: {e}", file=sys.stderr)
        sys.exit(1)

    # Tokenize new_info
    new_info_tokens = tokenize(new_info)

    # Score entries
    scored = []
    for entry in entries:
        s = score_entry(new_info_tokens, entry)
        if s > 0:
            scored.append((s, entry))

    # Sort: highest score first, tie-break by path (deterministic)
    scored.sort(key=lambda x: (-x[0], x[1]["path"]))

    # Select top-1 candidate if score >= 3
    candidate = None
    candidate_score = 0
    if scored and scored[0][0] >= 3:
        candidate_score = scored[0][0]
        candidate = scored[0][1]

    # Hard gates
    delete_allowed = category not in DELETE_DISALLOWED

    # Pre-classification
    if candidate is None and lifecycle_event is None:
        pre_action = "CREATE"
    elif candidate is None and lifecycle_event is not None:
        pre_action = "NOOP"
    else:
        pre_action = None

    # Structural CUD
    if pre_action == "CREATE":
        structural_cud = "CREATE"
    elif pre_action == "NOOP":
        structural_cud = "NOOP"
    elif candidate is not None and delete_allowed:
        structural_cud = "UPDATE_OR_DELETE"
    elif candidate is not None:
        structural_cud = "UPDATE"
    else:
        structural_cud = "CREATE"

    # Structural vetoes
    vetoes = []
    if candidate is None and pre_action is None:
        # Should not happen, but guard against it
        vetoes.append("Cannot UPDATE with 0 candidates")
        vetoes.append("Cannot DELETE with 0 candidates")
    if not delete_allowed and candidate is not None:
        vetoes.append(f"Cannot DELETE {category} (triage-initiated)")

    # Hints
    hints = []
    if candidate is not None:
        hints.append(f"1 candidate found (score={candidate_score})")
        if lifecycle_event:
            if delete_allowed:
                hints.append(
                    f"lifecycle_event={lifecycle_event} suggests DELETE if eligible"
                )
            else:
                hints.append(
                    f"lifecycle_event={lifecycle_event} present but DELETE "
                    f"disallowed for {category}; consider UPDATE"
                )
    if pre_action == "NOOP":
        hints.append(
            f"lifecycle_event={lifecycle_event} with no matching candidate; NOOP"
        )

    # Build candidate output
    candidate_output = None
    if candidate is not None:
        candidate_file = Path(candidate["path"])
        # Validate it's a .json file
        if candidate_file.suffix != ".json":
            print(
                f"WARNING: Candidate path not a .json file: {candidate['path']}",
                file=sys.stderr,
            )
        else:
            # Resolve path: index paths are relative to project root
            resolved = candidate_file.resolve()
            root_resolved = root.resolve()
            # Safety: ensure resolved path is under memory root
            try:
                resolved.relative_to(root_resolved)
                is_safe = True
            except ValueError:
                is_safe = False

            if not is_safe:
                print(
                    f"WARNING: Candidate path {candidate['path']} resolves "
                    f"outside memory root {root}; skipping",
                    file=sys.stderr,
                )
            else:
                # Read the actual JSON file for excerpt
                excerpt = build_excerpt(resolved, category)
                candidate_output = {
                    "path": candidate["path"],
                    "title": candidate["title"],
                    "tags": candidate["tags"],
                    "excerpt": excerpt,
                }

    # If candidate was invalidated during path checks, recompute
    if candidate is not None and candidate_output is None:
        pre_action = "CREATE" if lifecycle_event is None else "NOOP"
        structural_cud = pre_action
        vetoes = []
        hints = [f"Candidate path invalid; falling back to {pre_action}"]

    result = {
        "candidate": candidate_output,
        "lifecycle_event": lifecycle_event,
        "delete_allowed": delete_allowed,
        "pre_action": pre_action,
        "structural_cud": structural_cud,
        "vetoes": vetoes,
        "hints": hints,
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
