#!/usr/bin/env python3
"""Memory retrieval hook for claude-memory plugin (UserPromptSubmit).

Reads user prompt from stdin (hook input JSON), matches against
.claude/memory/index.md entries, outputs relevant memories to stdout.
Stdout is added to Claude's context automatically (exit 0).

Supports enriched index lines with #tags: suffix for higher-weight matching.

No external dependencies (stdlib only).
"""

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

# Tokenizer: extract word-like tokens
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# How many top candidates to read JSON files for (recency + retired check)
_DEEP_CHECK_LIMIT = 20

# Recency window in days
_RECENCY_DAYS = 30


def tokenize(text: str) -> set[str]:
    """Extract meaningful lowercase tokens from text."""
    tokens = set()
    for word in _TOKEN_RE.findall(text.lower()):
        if word not in STOP_WORDS and len(word) > 2:
            tokens.add(word)
    return tokens


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
    title_tokens = tokenize(entry["title"])
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
            if any(target.startswith(pw) for target in combined_targets):
                score += 1

    return score


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

    if not index_path.exists():
        sys.exit(0)

    # Check retrieval config
    max_inject = 5
    config_path = memory_root / "memory-config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            retrieval = config.get("retrieval", {})
            if not retrieval.get("enabled", True):
                sys.exit(0)
            max_inject = retrieval.get("max_inject", 5)
        except (json.JSONDecodeError, KeyError, OSError):
            pass

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

    # Tokenize prompt
    prompt_words = tokenize(user_prompt)

    if not prompt_words:
        sys.exit(0)

    # Pass 1: Score each entry by text matching (title + tags)
    scored = []
    for entry in entries:
        score = score_entry(prompt_words, entry)
        if score > 0:
            priority = CATEGORY_PRIORITY.get(entry["category"], 10)
            scored.append((score, priority, entry))

    if not scored:
        sys.exit(0)

    # Sort: highest score first, then by category priority
    scored.sort(key=lambda x: (-x[0], x[1]))

    # Pass 2: Deep check top candidates for recency bonus + retired exclusion
    # Resolve paths relative to project root (memory_root is .claude/memory)
    project_root = memory_root.parent.parent
    final = []
    for text_score, priority, entry in scored[:_DEEP_CHECK_LIMIT]:
        file_path = project_root / entry["path"]
        is_retired, is_recent = check_recency(file_path)

        # Defensive: skip retired entries even if they somehow remain in index
        if is_retired:
            continue

        final_score = text_score + (1 if is_recent else 0)
        final.append((final_score, priority, entry))

    # Also include entries beyond deep-check limit (no recency bonus, assume not retired)
    for text_score, priority, entry in scored[_DEEP_CHECK_LIMIT:]:
        final.append((text_score, priority, entry))

    if not final:
        sys.exit(0)

    # Re-sort with adjusted scores
    final.sort(key=lambda x: (-x[0], x[1]))
    top = final[:max_inject]

    # Output as plain text (added to Claude's context on exit 0)
    print("RELEVANT MEMORIES (from .claude/memory/):")
    for _, _, entry in top:
        print(entry["raw"])
    print()
    print("Read the referenced files above if you need detailed context for this task.")


if __name__ == "__main__":
    main()
