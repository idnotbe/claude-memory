#!/usr/bin/env python3
"""Memory triage hook for claude-memory plugin (Stop event).

Replaces 6 unreliable type:"prompt" Stop hooks with 1 deterministic
type:"command" hook. Reads the conversation transcript, applies keyword
heuristic scoring for 6 memory categories, and decides whether to block
the stop so the agent can save memories.

Exit codes:
  0 -- Allow stop (nothing to save, or error/fallback)
  2 -- Block stop (stderr contains items to save)

No external dependencies (stdlib only).
"""

from __future__ import annotations

import collections
import json
import os
import re
import select
import sys
import time
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maximum messages to read from transcript tail
DEFAULT_MAX_MESSAGES = 50

# Flag TTL in seconds (prevents stale flags from giving a "free pass")
FLAG_TTL_SECONDS = 300  # 5 minutes

# Co-occurrence sliding window: check N lines before/after a primary match
CO_OCCURRENCE_WINDOW = 4

# Default per-category thresholds
DEFAULT_THRESHOLDS: dict[str, float] = {
    "DECISION": 0.4,
    "RUNBOOK": 0.4,
    "CONSTRAINT": 0.5,
    "TECH_DEBT": 0.4,
    "PREFERENCE": 0.4,
    "SESSION_SUMMARY": 0.6,
}

# Regex to strip fenced code blocks (reduces false positives)
_CODE_FENCE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)

# Regex to strip inline code
_INLINE_CODE_RE = re.compile(r"`[^`]+`")


# ---------------------------------------------------------------------------
# Category pattern definitions
# ---------------------------------------------------------------------------

# Each category has:
#   primary: list of compiled regex patterns (must match to score)
#   boosters: list of compiled regex patterns (co-occurrence amplifier)
#   primary_weight: score added per primary match (alone)
#   boosted_weight: score added per primary match + booster in window
#   max_primary: cap on standalone primary matches
#   max_boosted: cap on boosted matches
#   denominator: divide raw score by this for normalization to [0, 1]

_WORD = r"\b"

CATEGORY_PATTERNS: dict[str, dict] = {
    "DECISION": {
        "primary": [
            re.compile(
                rf"{_WORD}(decided|chose|selected|went\s+with|picked){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "boosters": [
            re.compile(
                rf"{_WORD}(because|due\s+to|reason|rationale|over|instead\s+of|rather\s+than){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "primary_weight": 0.3,
        "boosted_weight": 0.5,
        "max_primary": 3,
        "max_boosted": 2,
        "denominator": 1.9,  # 3*0.3 + 2*0.5 = 1.9
    },
    "RUNBOOK": {
        "primary": [
            re.compile(
                rf"{_WORD}(error|exception|traceback|stack\s*trace|failed|failure|crash){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "boosters": [
            re.compile(
                rf"{_WORD}(fixed\s+by|resolved|root\s+cause|solution|workaround|the\s+fix){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "primary_weight": 0.2,
        "boosted_weight": 0.6,
        "max_primary": 3,
        "max_boosted": 2,
        "denominator": 1.8,  # 3*0.2 + 2*0.6 = 1.8
    },
    "CONSTRAINT": {
        "primary": [
            re.compile(
                rf"{_WORD}(limitation|api\s+limit|cannot|restricted|not\s+supported|quota|rate\s+limit){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "boosters": [
            re.compile(
                rf"{_WORD}(discovered|found\s+that|turns\s+out|permanently|enduring|platform){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "primary_weight": 0.3,
        "boosted_weight": 0.5,
        "max_primary": 3,
        "max_boosted": 2,
        "denominator": 1.9,
    },
    "TECH_DEBT": {
        "primary": [
            re.compile(
                rf"{_WORD}(TODO|deferred|tech\s+debt|workaround|hack|will\s+address\s+later|technical\s+debt){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "boosters": [
            re.compile(
                rf"{_WORD}(because|for\s+now|temporary|acknowledged|deferring|cost|risk){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "primary_weight": 0.3,
        "boosted_weight": 0.5,
        "max_primary": 3,
        "max_boosted": 2,
        "denominator": 1.9,
    },
    "PREFERENCE": {
        "primary": [
            re.compile(
                rf"{_WORD}(always\s+use|prefer|convention|from\s+now\s+on|standard|never\s+use|established){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "boosters": [
            re.compile(
                rf"{_WORD}(agreed|going\s+forward|consistently|rule|practice|workflow){_WORD}",
                re.IGNORECASE,
            ),
        ],
        "primary_weight": 0.35,
        "boosted_weight": 0.5,
        "max_primary": 3,
        "max_boosted": 2,
        "denominator": 2.05,  # 3*0.35 + 2*0.5 = 2.05
    },
}


# ---------------------------------------------------------------------------
# stdin reading
# ---------------------------------------------------------------------------

def read_stdin(timeout_seconds: float = 2.0) -> str:
    """Read stdin with timeout.

    Claude Code does not send EOF after writing hook input to stdin,
    so a plain sys.stdin.read() would block forever. We use select()
    to detect when data is available and a short follow-up timeout
    to detect end-of-input.
    """
    chunks: list[bytes] = []
    fd = sys.stdin.fileno()
    remaining = timeout_seconds

    while remaining > 0:
        start = time.monotonic()
        ready, _, _ = select.select([fd], [], [], remaining)
        elapsed = time.monotonic() - start

        if not ready:
            break

        chunk = os.read(fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)

        # After first successful read, use a short timeout
        # to drain any remaining buffered data
        remaining = 0.1

    return b"".join(chunks).decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def parse_transcript(transcript_path: str, max_messages: int) -> list[dict]:
    """Parse last N messages from JSONL transcript file.

    Returns list of message dicts (most recent last).
    Handles missing files, empty files, and corrupt JSONL lines gracefully.
    """
    maxlen = max_messages if max_messages > 0 else None
    messages: collections.deque[dict] = collections.deque(maxlen=maxlen)
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    if isinstance(msg, dict):
                        messages.append(msg)
                except json.JSONDecodeError:
                    continue
    except (OSError, IOError):
        return []
    return list(messages)


def extract_text_content(messages: list[dict]) -> str:
    """Extract human and assistant text content from messages.

    Strips fenced code blocks and inline code to reduce false positives
    from keywords appearing in code (e.g., variable names, comments).
    """
    parts: list[str] = []
    for msg in messages:
        msg_type = msg.get("type", "")
        if msg_type not in ("human", "assistant"):
            continue
        content = msg.get("content", "")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
        elif isinstance(content, str):
            parts.append(content)

    text = "\n".join(parts)
    # Strip fenced code blocks first, then inline code
    text = _CODE_FENCE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    return text


def extract_activity_metrics(messages: list[dict]) -> dict[str, int]:
    """Extract activity metrics for SESSION_SUMMARY scoring.

    Counts tool uses, distinct tool names, and human/assistant exchanges.
    """
    tool_uses = 0
    tool_names: set[str] = set()
    exchanges = 0

    for msg in messages:
        msg_type = msg.get("type", "")
        if msg_type == "tool_use":
            tool_uses += 1
            name = msg.get("name", "")
            if name:
                tool_names.add(name)
        elif msg_type in ("human", "assistant"):
            exchanges += 1

    return {
        "tool_uses": tool_uses,
        "distinct_tools": len(tool_names),
        "exchanges": exchanges,
    }


# ---------------------------------------------------------------------------
# Heuristic scoring
# ---------------------------------------------------------------------------

def _has_pattern_in_window(
    lines: list[str],
    center_idx: int,
    patterns: list[re.Pattern],
    window: int,
) -> bool:
    """Check if any of the given patterns match within a window around center_idx.

    Includes the center line itself -- co-occurring keywords on the same line
    are the strongest signal (e.g., "decided ... because" on one line).
    """
    start = max(0, center_idx - window)
    end = min(len(lines), center_idx + window + 1)
    for i in range(start, end):
        for pat in patterns:
            if pat.search(lines[i]):
                return True
    return False


def score_text_category(
    lines: list[str],
    category: str,
) -> tuple[float, list[str]]:
    """Score a text-based category using primary patterns + co-occurrence boosters.

    Returns (normalized_score, list_of_matched_context_snippets).
    """
    cfg = CATEGORY_PATTERNS.get(category)
    if not cfg:
        return 0.0, []

    primary_pats: list[re.Pattern] = cfg["primary"]
    booster_pats: list[re.Pattern] = cfg["boosters"]
    primary_weight: float = cfg["primary_weight"]
    boosted_weight: float = cfg["boosted_weight"]
    max_primary: int = cfg["max_primary"]
    max_boosted: int = cfg["max_boosted"]
    denominator: float = cfg["denominator"]

    raw_score = 0.0
    primary_count = 0
    boosted_count = 0
    snippets: list[str] = []

    for idx, line in enumerate(lines):
        for pat in primary_pats:
            if pat.search(line):
                # Check for co-occurrence booster in window
                has_booster = _has_pattern_in_window(
                    lines, idx, booster_pats, CO_OCCURRENCE_WINDOW
                )
                if has_booster and boosted_count < max_boosted:
                    raw_score += boosted_weight
                    boosted_count += 1
                    snippet = line.strip()[:120]
                    if snippet and snippet not in snippets:
                        snippets.append(snippet)
                elif primary_count < max_primary:
                    raw_score += primary_weight
                    primary_count += 1
                    snippet = line.strip()[:120]
                    if snippet and snippet not in snippets:
                        snippets.append(snippet)

                # Only count one primary pattern match per line
                break

    normalized = min(1.0, raw_score / denominator) if denominator > 0 else 0.0
    return normalized, snippets


def score_session_summary(metrics: dict[str, int]) -> tuple[float, list[str]]:
    """Score SESSION_SUMMARY based on activity metrics.

    Returns (normalized_score, description_snippets).
    """
    tool_uses = metrics.get("tool_uses", 0)
    distinct_tools = metrics.get("distinct_tools", 0)
    exchanges = metrics.get("exchanges", 0)

    score = min(
        1.0,
        (tool_uses * 0.05) + (distinct_tools * 0.1) + (exchanges * 0.02),
    )

    snippets: list[str] = []
    if score > 0:
        snippets.append(
            f"{tool_uses} tool uses across {distinct_tools} tools, "
            f"{exchanges} exchanges"
        )

    return score, snippets


def run_triage(
    text: str,
    metrics: dict[str, int],
    thresholds: dict[str, float],
) -> list[dict]:
    """Run heuristic triage across all 6 categories.

    Returns list of dicts for categories that exceed their threshold:
      [{"category": "DECISION", "score": 0.72, "snippets": ["..."]}]
    """
    results: list[dict] = []
    lines = text.split("\n")

    # Text-based categories
    for category in CATEGORY_PATTERNS:
        threshold = thresholds.get(category, 0.5)
        score, snippets = score_text_category(lines, category)
        if score >= threshold:
            results.append({
                "category": category,
                "score": score,
                "snippets": snippets,
            })

    # Activity-based: SESSION_SUMMARY
    threshold = thresholds.get("SESSION_SUMMARY", 0.6)
    score, snippets = score_session_summary(metrics)
    if score >= threshold:
        results.append({
            "category": "SESSION_SUMMARY",
            "score": score,
            "snippets": snippets,
        })

    return results


# ---------------------------------------------------------------------------
# Stop hook active flag (with TTL)
# ---------------------------------------------------------------------------

def check_stop_flag(cwd: str) -> bool:
    """Check the stop_hook_active flag.

    Returns True if the script should exit 0 immediately (fresh flag = user
    is re-stopping after a recent block, allow it through).
    Returns False if the script should continue evaluation.

    Uses exception-based control flow to avoid TOCTOU races.
    """
    flag_path = Path(cwd) / ".claude" / ".stop_hook_active"
    try:
        mtime = flag_path.stat().st_mtime
        age = time.time() - mtime
        flag_path.unlink(missing_ok=True)
        return age < FLAG_TTL_SECONDS
    except OSError:
        return False


def set_stop_flag(cwd: str) -> None:
    """Create the stop_hook_active flag file."""
    flag_path = Path(cwd) / ".claude" / ".stop_hook_active"
    try:
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass  # Non-critical: worst case is user gets blocked twice


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(cwd: str) -> dict:
    """Load triage configuration from memory-config.json.

    Returns a dict with keys: enabled, max_messages, thresholds.
    Falls back to defaults on any error.
    """
    config: dict = {
        "enabled": True,
        "max_messages": DEFAULT_MAX_MESSAGES,
        "thresholds": dict(DEFAULT_THRESHOLDS),
    }

    config_path = Path(cwd) / ".claude" / "memory" / "memory-config.json"
    if not config_path.exists():
        return config

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return config

    triage = raw.get("triage", {})
    if not isinstance(triage, dict):
        return config

    # enabled
    if "enabled" in triage:
        config["enabled"] = bool(triage["enabled"])

    # max_messages
    if "max_messages" in triage:
        try:
            val = int(triage["max_messages"])
            config["max_messages"] = max(10, min(200, val))
        except (ValueError, TypeError):
            pass

    # thresholds
    if "thresholds" in triage and isinstance(triage["thresholds"], dict):
        for cat, default_val in DEFAULT_THRESHOLDS.items():
            raw_val = triage["thresholds"].get(cat)
            if raw_val is not None:
                try:
                    val = float(raw_val)
                    config["thresholds"][cat] = max(0.0, min(1.0, val))
                except (ValueError, TypeError):
                    pass

    return config


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

# Regex for sanitizing snippets injected into stderr output
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_ZERO_WIDTH_RE = re.compile(
    r"[\u200b-\u200f\u2028-\u202f\u2060-\u2069\ufeff\U000e0000-\U000e007f]"
)


def _sanitize_snippet(text: str) -> str:
    """Sanitize a snippet for safe injection into stderr output.

    Strips control characters, zero-width Unicode (including tag characters),
    backticks, and escapes XML-sensitive characters to prevent prompt injection
    via crafted conversation content.
    """
    text = _CONTROL_CHAR_RE.sub("", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.replace("`", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.strip()[:120]


def format_block_message(results: list[dict]) -> str:
    """Format the stderr message for exit 2 (block stop).

    Produces a human-readable message that Claude can understand and act on.
    """
    lines: list[str] = [
        "The following items should be saved as memories before stopping:",
    ]
    for r in results:
        category = r["category"]
        score = r["score"]
        snippets = r.get("snippets", [])
        if snippets:
            summary = _sanitize_snippet(snippets[0])
            lines.append(f"- [{category}] {summary} (score: {score:.2f})")
        else:
            lines.append(f"- [{category}] Significant activity detected (score: {score:.2f})")

    lines.append("")
    lines.append(
        "Use the memory-management skill to save each item. "
        "After saving, you may stop."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Main entry point for the memory triage hook.

    Returns exit code: 0 (allow stop) or 2 (block stop).
    """
    try:
        return _run_triage()
    except Exception as e:
        # Fail open: never trap the user on unexpected errors
        print(f"[memory_triage] Error (fail-open): {e}", file=sys.stderr)
        return 0


def _run_triage() -> int:
    """Internal triage logic, separated for testability."""
    # 1. Read stdin JSON
    raw_input = read_stdin(timeout_seconds=2.0)
    if not raw_input.strip():
        return 0

    try:
        hook_input = json.loads(raw_input)
    except json.JSONDecodeError:
        return 0

    if not isinstance(hook_input, dict):
        return 0

    # 2. Extract fields
    transcript_path: Optional[str] = hook_input.get("transcript_path")
    cwd: str = hook_input.get("cwd", os.getcwd())

    # 3. Load configuration
    config = load_config(cwd)
    if not config["enabled"]:
        return 0

    # 4. Check stop_hook_active flag
    if check_stop_flag(cwd):
        return 0

    # 5. Read and parse transcript
    if not transcript_path or not os.path.isfile(transcript_path):
        return 0

    # Validate transcript path is within expected scope (defense in depth)
    resolved = os.path.realpath(transcript_path)
    home = os.path.expanduser("~")
    if not (resolved.startswith("/tmp/") or resolved.startswith(home + "/")):
        return 0

    messages = parse_transcript(resolved, config["max_messages"])
    if not messages:
        return 0

    # 6. Extract text and activity metrics
    text = extract_text_content(messages)
    metrics = extract_activity_metrics(messages)

    # 7. Run heuristic triage
    results = run_triage(text, metrics, config["thresholds"])

    # 8. Output decision
    if results:
        # Block stop: create flag and output message
        set_stop_flag(cwd)
        message = format_block_message(results)
        print(message, file=sys.stderr)
        return 2
    else:
        # Allow stop: nothing to save
        return 0


if __name__ == "__main__":
    sys.exit(main())
