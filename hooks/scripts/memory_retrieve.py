#!/usr/bin/env python3
"""Memory retrieval hook for claude-memory plugin (UserPromptSubmit).

Reads user prompt from stdin (hook input JSON), matches against
.claude/memory/index.md entries, outputs relevant memories to stdout.
Stdout is added to Claude's context automatically (exit 0).

No external dependencies (stdlib only).
"""

import json
import os
import sys
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
                line = line.strip()
                if line.startswith("- [") and " -> " in line:
                    entries.append(line)
    except OSError:
        sys.exit(0)

    if not entries:
        sys.exit(0)

    # Tokenize prompt
    prompt_words = set()
    for word in user_prompt.lower().split():
        # Strip common punctuation
        cleaned = word.strip(".,;:!?\"'()[]{}")
        if cleaned and cleaned not in STOP_WORDS and len(cleaned) > 2:
            prompt_words.add(cleaned)

    if not prompt_words:
        sys.exit(0)

    # Score each entry by keyword overlap
    scored = []
    for entry in entries:
        entry_lower = entry.lower()
        score = sum(1 for w in prompt_words if w in entry_lower)
        if score > 0:
            # Extract category tag for priority sorting
            cat = ""
            try:
                cat = entry.split("]")[0].split("[")[1]
            except IndexError:
                pass
            priority = CATEGORY_PRIORITY.get(cat, 10)
            scored.append((score, priority, entry))

    if not scored:
        sys.exit(0)

    # Sort: highest score first, then by category priority
    scored.sort(key=lambda x: (-x[0], x[1]))
    top = scored[:max_inject]

    # Output as plain text (added to Claude's context on exit 0)
    print("RELEVANT MEMORIES (from .claude/memory/):")
    for _, _, entry in top:
        print(entry)
    print()
    print("Read the referenced files above if you need detailed context for this task.")


if __name__ == "__main__":
    main()
