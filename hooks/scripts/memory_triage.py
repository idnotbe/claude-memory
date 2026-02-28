#!/usr/bin/env python3
"""Memory triage hook for claude-memory plugin (Stop event).

Replaces 6 unreliable type:"prompt" Stop hooks with 1 deterministic
type:"command" hook. Reads the conversation transcript, applies keyword
heuristic scoring for 6 memory categories, and decides whether to block
the stop so the agent can save memories.

Output protocol (advanced JSON hook API):
  Block stop: exit 0, stdout = {"decision": "block", "reason": "..."}
  Allow stop: exit 0, no stdout output

No external dependencies (stdlib only).
"""

from __future__ import annotations

import collections
import datetime
import json
import math
import os
import re
import select
import sys
import time
from pathlib import Path
from typing import Optional

# Lazy import: logging module may not exist during partial deployments
try:
    from memory_logger import emit_event, get_session_id, parse_logging_config
except (ImportError, SyntaxError) as e:
    if isinstance(e, ImportError) and getattr(e, 'name', None) != 'memory_logger':
        raise  # Transitive dependency failure -- fail-fast
    def emit_event(*args, **kwargs): pass
    def get_session_id(*args, **kwargs): return ""
    def parse_logging_config(*args, **kwargs): return {"enabled": False, "level": "info", "retention_days": 14}


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
                        msg_type = msg.get("type", "")
                        if msg_type in ("user", "human", "assistant"):
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
        if msg_type not in ("user", "human", "assistant"):
            continue
        # Try nested path first (real transcripts), fall back to flat (test fixtures)
        content = msg.get("message", {}).get("content", "") or msg.get("content", "")
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
            # Fallback: top-level tool_use (backwards compat with flat format)
            tool_uses += 1
            name = msg.get("name", "")
            if name:
                tool_names.add(name)
        elif msg_type in ("user", "human", "assistant"):
            exchanges += 1
            # For assistant messages, inspect nested content for tool_use blocks
            if msg_type == "assistant":
                content = msg.get("message", {}).get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_uses += 1
                            name = block.get("name", "")
                            if name:
                                tool_names.add(name)

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


def _score_all_raw(
    text: str,
    metrics: dict[str, int],
) -> list[dict]:
    """Compute scores + snippets for ALL 6 categories (shared core).

    Returns list of dicts for every category:
      [{"category": "DECISION", "score": 0.72, "snippets": ["..."]}]

    Used by both ``run_triage()`` (threshold-filtered) and
    ``score_all_categories()`` (all scores, no snippets).
    Single evaluation avoids duplicate regex execution.
    """
    all_raw: list[dict] = []
    lines = text.split("\n")

    # Text-based categories
    for category in CATEGORY_PATTERNS:
        score, snippets = score_text_category(lines, category)
        all_raw.append({
            "category": category,
            "score": score,
            "snippets": snippets,
        })

    # Activity-based: SESSION_SUMMARY
    score, snippets = score_session_summary(metrics)
    all_raw.append({
        "category": "SESSION_SUMMARY",
        "score": score,
        "snippets": snippets,
    })

    return all_raw


def run_triage(
    text: str,
    metrics: dict[str, int],
    thresholds: dict[str, float],
) -> list[dict]:
    """Run heuristic triage across all 6 categories.

    Returns list of dicts for categories that exceed their threshold:
      [{"category": "DECISION", "score": 0.72, "snippets": ["..."]}]
    """
    all_raw = _score_all_raw(text, metrics)
    results: list[dict] = []
    for entry in all_raw:
        threshold = thresholds.get(entry["category"], 0.5)
        if entry["category"] == "SESSION_SUMMARY":
            threshold = thresholds.get("SESSION_SUMMARY", 0.6)
        if entry["score"] >= threshold:
            results.append(entry)
    return results


def score_all_categories(
    text: str,
    metrics: dict[str, int],
) -> list[dict]:
    """Score ALL 6 categories and return their scores (for logging/analytics).

    Unlike ``run_triage()`` which filters by threshold, this returns every
    category with its computed score. Snippets are intentionally excluded
    to keep log payloads compact and avoid leaking transcript content.

    Returns:
        [{"category": "DECISION", "score": 0.32}, ...]
    """
    all_raw = _score_all_raw(text, metrics)
    return [
        {"category": entry["category"], "score": round(entry["score"], 4)}
        for entry in all_raw
    ]


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

VALID_MODELS = {"haiku", "sonnet", "opus"}

DEFAULT_PARALLEL_CONFIG: dict = {
    "enabled": True,
    "category_models": {
        "session_summary": "haiku",
        "decision": "sonnet",
        "runbook": "haiku",
        "constraint": "sonnet",
        "tech_debt": "haiku",
        "preference": "haiku",
    },
    "verification_model": "sonnet",
    "default_model": "haiku",
}

VALID_CATEGORY_KEYS = set(DEFAULT_PARALLEL_CONFIG["category_models"].keys())


def load_config(cwd: str) -> dict:
    """Load triage configuration from memory-config.json.

    Returns a dict with keys: enabled, max_messages, thresholds, parallel,
    category_descriptions.
    Falls back to defaults on any error.
    """
    config: dict = {
        "enabled": True,
        "max_messages": DEFAULT_MAX_MESSAGES,
        "thresholds": dict(DEFAULT_THRESHOLDS),
        "parallel": _deep_copy_parallel_defaults(),
        "category_descriptions": {},
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

    # thresholds (case-insensitive key matching: accept both UPPERCASE and lowercase)
    if "thresholds" in triage and isinstance(triage["thresholds"], dict):
        # Normalize user keys to UPPERCASE for matching against DEFAULT_THRESHOLDS
        user_thresholds = {k.upper(): v for k, v in triage["thresholds"].items()}
        for cat, default_val in DEFAULT_THRESHOLDS.items():
            raw_val = user_thresholds.get(cat)
            if raw_val is not None:
                try:
                    val = float(raw_val)
                    # Reject NaN and Inf (CPython json.loads accepts these)
                    if math.isnan(val) or math.isinf(val):
                        continue
                    config["thresholds"][cat] = max(0.0, min(1.0, val))
                except (ValueError, TypeError):
                    pass

    # parallel config
    config["parallel"] = _parse_parallel_config(triage.get("parallel"))

    # category descriptions (agent-interpreted, not used by triage scoring)
    categories_raw = raw.get("categories", {})
    if isinstance(categories_raw, dict):
        descs: dict[str, str] = {}
        for cat_key, cat_val in categories_raw.items():
            if isinstance(cat_val, dict):
                desc = cat_val.get("description", "")
                desc = desc if isinstance(desc, str) else ""
                descs[cat_key.lower()] = desc[:500]
        config["category_descriptions"] = descs

    # Store raw config for logging subsystem (emit_event needs full config with logging key)
    config["_raw"] = raw

    return config


def _deep_copy_parallel_defaults() -> dict:
    """Return a fresh copy of DEFAULT_PARALLEL_CONFIG."""
    return {
        "enabled": DEFAULT_PARALLEL_CONFIG["enabled"],
        "category_models": dict(DEFAULT_PARALLEL_CONFIG["category_models"]),
        "verification_model": DEFAULT_PARALLEL_CONFIG["verification_model"],
        "default_model": DEFAULT_PARALLEL_CONFIG["default_model"],
    }


def _parse_parallel_config(raw: object) -> dict:
    """Parse and validate the triage.parallel config section.

    Returns a validated parallel config dict. Falls back to defaults
    for any invalid or missing values.
    """
    defaults = _deep_copy_parallel_defaults()

    if not isinstance(raw, dict):
        return defaults

    # enabled
    if "enabled" in raw:
        defaults["enabled"] = bool(raw["enabled"])

    # default_model (parse first, used as fallback for category_models)
    if "default_model" in raw:
        val = str(raw["default_model"]).lower()
        if val in VALID_MODELS:
            defaults["default_model"] = val

    # verification_model
    if "verification_model" in raw:
        val = str(raw["verification_model"]).lower()
        if val in VALID_MODELS:
            defaults["verification_model"] = val

    # category_models
    if "category_models" in raw and isinstance(raw["category_models"], dict):
        for cat_key in VALID_CATEGORY_KEYS:
            raw_val = raw["category_models"].get(cat_key)
            if raw_val is not None:
                val = str(raw_val).lower()
                if val in VALID_MODELS:
                    defaults["category_models"][cat_key] = val
                # Invalid model value: keep the default for this category

    return defaults


# ---------------------------------------------------------------------------
# Context file generation
# ---------------------------------------------------------------------------

# Lines of context to include before/after each keyword match
CONTEXT_WINDOW_LINES = 10

# Maximum context file size in bytes (prevents oversized subagent prompts)
MAX_CONTEXT_FILE_BYTES = 50_000  # 50 KB


def _find_match_line_indices(lines: list[str], category: str) -> list[int]:
    """Find line indices where primary patterns match for a category."""
    cfg = CATEGORY_PATTERNS.get(category)
    if not cfg:
        return []

    indices: list[int] = []
    for idx, line in enumerate(lines):
        for pat in cfg["primary"]:
            if pat.search(line):
                indices.append(idx)
                break  # One match per line is enough
    return indices


def _extract_context_excerpt(
    lines: list[str],
    match_indices: list[int],
    window: int = CONTEXT_WINDOW_LINES,
) -> str:
    """Extract merged context windows around match indices.

    Returns a single string with non-overlapping excerpts separated by
    '---' markers. Each excerpt includes +/- window lines around the match.
    """
    if not match_indices or not lines:
        return ""

    # Build merged ranges (avoid overlapping excerpts)
    ranges: list[tuple[int, int]] = []
    for idx in sorted(set(match_indices)):
        start = max(0, idx - window)
        end = min(len(lines), idx + window + 1)
        if ranges and start <= ranges[-1][1]:
            # Merge with previous range
            ranges[-1] = (ranges[-1][0], end)
        else:
            ranges.append((start, end))

    parts: list[str] = []
    for start, end in ranges:
        parts.append("\n".join(lines[start:end]))

    return "\n---\n".join(parts)


def write_context_files(
    text: str,
    metrics: dict[str, int],
    results: list[dict],
    *,
    cwd: str = "",
    category_descriptions: dict[str, str] | None = None,
) -> dict[str, str]:
    """Write per-category context files to the project staging directory.

    Returns a dict mapping category name -> context file path.
    For text-based categories, includes generous transcript excerpts
    around keyword matches. For SESSION_SUMMARY, includes activity metrics.

    Files are written to {cwd}/.claude/memory/.staging/context-{cat}.txt.
    Falls back to /tmp/ if cwd is empty or directory creation fails.
    """
    lines = text.split("\n")
    context_paths: dict[str, str] = {}

    # Determine staging directory
    staging_dir = ""
    if cwd:
        staging_dir = os.path.join(cwd, ".claude", "memory", ".staging")
        try:
            os.makedirs(staging_dir, exist_ok=True)
        except OSError:
            staging_dir = ""  # Fall back to /tmp/

    for r in results:
        category = r["category"]
        cat_lower = category.lower()
        score = r["score"]
        snippets = r.get("snippets", [])
        if staging_dir:
            path = os.path.join(staging_dir, f"context-{cat_lower}.txt")
        else:
            path = f"/tmp/.memory-triage-context-{cat_lower}.txt"

        try:
            parts: list[str] = [
                f"Category: {cat_lower}",
                f"Score: {score:.2f}",
            ]

            # Add description if provided
            if category_descriptions:
                desc = category_descriptions.get(cat_lower, "")
                if desc:
                    parts.append(f"Description: {_sanitize_snippet(desc)}")

            parts.append("")

            parts.append("<transcript_data>")
            if category == "SESSION_SUMMARY":
                parts.append("Activity Metrics:")
                parts.append(f"  Tool uses: {metrics.get('tool_uses', 0)}")
                parts.append(f"  Distinct tools: {metrics.get('distinct_tools', 0)}")
                parts.append(f"  Exchanges: {metrics.get('exchanges', 0)}")
            else:
                # Text-based category: include generous context excerpts
                match_indices = _find_match_line_indices(lines, category)
                excerpt = _extract_context_excerpt(lines, match_indices)
                if excerpt:
                    parts.append("Relevant transcript excerpts:")
                    parts.append("")
                    parts.append(excerpt)
            parts.append("</transcript_data>")

            if snippets:
                parts.append("")
                parts.append("Key snippets:")
                for s in snippets:
                    parts.append(f"  - {s}")

            content = "\n".join(parts)

            # Truncate if exceeds max size (prevents oversized subagent prompts)
            content_bytes = content.encode("utf-8")
            if len(content_bytes) > MAX_CONTEXT_FILE_BYTES:
                # Truncate at byte boundary, decode safely
                truncated = content_bytes[:MAX_CONTEXT_FILE_BYTES].decode(
                    "utf-8", errors="ignore"
                )
                content = truncated + "\n</transcript_data>\n[Truncated: context exceeded 50KB]"

            # Secure file creation: O_CREAT|O_WRONLY|O_TRUNC|O_NOFOLLOW
            # prevents symlink attacks and sets restrictive permissions
            fd = os.open(
                path,
                os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW,
                0o600,
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise

            context_paths[cat_lower] = path
        except OSError:
            # Non-critical: subagent can still work without context file
            pass

    return context_paths


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

# Regex for sanitizing snippets injected into stderr output
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")
_ZERO_WIDTH_RE = re.compile(
    r"[\u200b-\u200f\u2028-\u202f\u2060-\u2069\ufeff\U000e0000-\U000e007f]"
)


def _sanitize_snippet(text: str) -> str:
    """Sanitize a snippet for safe injection into output.

    Strips control characters, zero-width Unicode (including tag characters),
    backticks, and escapes XML-sensitive characters to prevent prompt injection
    via crafted conversation content.
    """
    text = _CONTROL_CHAR_RE.sub("", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = text.replace("`", "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.strip()[:120]


def build_triage_data(
    results: list[dict],
    context_paths: dict[str, str],
    parallel_config: dict,
    category_descriptions: dict[str, str] | None = None,
) -> dict:
    """Build structured triage data dict from results.

    Extracted from format_block_message() so _run_triage() can write
    the data to a file before formatting the message.
    """
    triage_categories = []
    for r in results:
        category = r["category"]
        cat_lower = category.lower()
        entry = {
            "category": cat_lower,
            "score": round(r["score"], 4),
        }
        if category_descriptions:
            desc = category_descriptions.get(cat_lower, "")
            if desc:
                entry["description"] = desc
        ctx_path = context_paths.get(cat_lower)
        if ctx_path:
            entry["context_file"] = ctx_path
        triage_categories.append(entry)

    return {
        "categories": triage_categories,
        "parallel_config": {
            "enabled": parallel_config.get("enabled", True),
            "category_models": parallel_config.get(
                "category_models",
                DEFAULT_PARALLEL_CONFIG["category_models"],
            ),
            "verification_model": parallel_config.get(
                "verification_model",
                DEFAULT_PARALLEL_CONFIG["verification_model"],
            ),
            "default_model": parallel_config.get(
                "default_model",
                DEFAULT_PARALLEL_CONFIG["default_model"],
            ),
        },
    }


def format_block_message(
    results: list[dict],
    context_paths: dict[str, str],
    parallel_config: dict,
    *,
    category_descriptions: dict[str, str] | None = None,
    triage_data_path: str | None = None,
) -> str:
    """Format the block message for stdout JSON response (block stop).

    Produces a human-readable message that Claude can understand and act on,
    followed by either a file reference (<triage_data_file>) or inline
    structured (<triage_data>) JSON block for programmatic parsing.
    """
    if not results:
        return ""

    lines: list[str] = [
        "The following items should be saved as memories before stopping:",
    ]
    for r in results:
        category = r["category"]
        score = r["score"]
        snippets = r.get("snippets", [])
        # Build description hint for human-readable line
        desc_hint = ""
        if category_descriptions:
            desc = category_descriptions.get(category.lower(), "")
            if desc:
                # Sanitize description (untrusted input)
                desc_hint = f" ({_sanitize_snippet(desc)})"
        if snippets:
            summary = _sanitize_snippet(snippets[0])
            lines.append(f"- [{category}]{desc_hint} {summary} (score: {score:.2f})")
        else:
            lines.append(f"- [{category}]{desc_hint} Significant activity detected (score: {score:.2f})")

    lines.append("")
    lines.append(
        "Use the memory-management skill to save each item. "
        "After saving, you may stop."
    )

    # Structured triage data: file reference or inline fallback
    if triage_data_path:
        lines.append("")
        lines.append(f"<triage_data_file>{triage_data_path}</triage_data_file>")
    else:
        triage_data = build_triage_data(
            results, context_paths, parallel_config,
            category_descriptions=category_descriptions,
        )
        lines.append("")
        lines.append("<triage_data>")
        lines.append(json.dumps(triage_data, indent=2))
        lines.append("</triage_data>")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    """Main entry point for the memory triage hook.

    Returns exit code 0. Block/allow decision is communicated via
    stdout JSON (advanced hook API), not exit codes.
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

    # 4b. Sentinel-based idempotency: skip if recently handled
    sentinel_path = os.path.join(cwd, ".claude", "memory", ".staging", ".triage-handled")
    try:
        sentinel_mtime = os.stat(sentinel_path).st_mtime
        if time.time() - sentinel_mtime < FLAG_TTL_SECONDS:
            return 0
    except OSError:
        pass  # Sentinel doesn't exist, continue normally

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

    # 7. Run heuristic triage (single scoring pass via shared _score_all_raw)
    results = run_triage(text, metrics, config["thresholds"])

    # Score logging (non-critical observability)
    _triage_session_id = get_session_id(transcript_path or "")
    _memory_root_str = os.path.join(cwd, ".claude", "memory")
    _triage_raw_config = config.get("_raw", {})

    # All category scores for logging. Note: this re-evaluates _score_all_raw
    # (duplicate regex pass). Acceptable since triage runs once per session stop
    # and total overhead is <100ms. The shared _score_all_raw ensures both
    # functions stay in sync when categories are added/changed.
    all_scores = score_all_categories(text, metrics)

    # New structured logging via emit_event
    emit_event("triage.score", {
        "text_len": len(text),
        "exchanges": metrics.get("exchanges", 0),
        "tool_uses": metrics.get("tool_uses", 0),
        "triggered": [
            {"category": r["category"], "score": round(r["score"], 4)}
            for r in results
        ],
        "all_scores": all_scores,
    }, hook="Stop", script="memory_triage.py",
       session_id=_triage_session_id,
       memory_root=_memory_root_str, config=_triage_raw_config)

    # LEGACY: remove after migration validation
    try:
        log_entry = {
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "cwd": cwd,
            "text_len": len(text),
            "exchanges": metrics.get("exchanges", 0),
            "tool_uses": metrics.get("tool_uses", 0),
            "triggered": [
                {"category": r["category"], "score": round(r["score"], 4)}
                for r in results
            ],
        }
        staging_log_dir = os.path.join(cwd, ".claude", "memory", ".staging")
        try:
            os.makedirs(staging_log_dir, exist_ok=True)
            log_path = os.path.join(staging_log_dir, ".triage-scores.log")
        except OSError:
            log_path = "/tmp/.memory-triage-scores.log"
        fd = os.open(
            log_path,
            os.O_CREAT | os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW,
            0o600,
        )
        try:
            with os.fdopen(fd, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
    except OSError:
        pass  # LEGACY: Non-critical: fail silently

    # 8. Output decision
    if results:
        # Block stop: create flag and output message
        set_stop_flag(cwd)

        # Touch sentinel file for idempotency
        try:
            sentinel_dir = os.path.join(cwd, ".claude", "memory", ".staging")
            os.makedirs(sentinel_dir, exist_ok=True)
            sentinel_file = os.path.join(sentinel_dir, ".triage-handled")
            fd = os.open(
                sentinel_file,
                os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW,
                0o600,
            )
            try:
                os.write(fd, str(time.time()).encode("utf-8"))
            finally:
                os.close(fd)
        except OSError:
            pass  # Non-critical: worst case is duplicate triage

        # Write per-category context files for subagent consumption
        cat_descs = config.get("category_descriptions", {})
        context_paths = write_context_files(
            text, metrics, results,
            cwd=cwd,
            category_descriptions=cat_descs,
        )

        # Build triage data and write to file (atomic)
        parallel_config = config.get("parallel", _deep_copy_parallel_defaults())
        triage_data = build_triage_data(
            results, context_paths, parallel_config,
            category_descriptions=cat_descs,
        )
        triage_data_path = os.path.join(
            cwd, ".claude", "memory", ".staging", "triage-data.json",
        )
        tmp_path = None
        try:
            tmp_path = f"{triage_data_path}.{os.getpid()}.tmp"
            fd = os.open(
                tmp_path,
                os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW,
                0o600,
            )
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
            except Exception:
                os.close(fd)
                raise
            with f:
                json.dump(triage_data, f, indent=2)
            os.replace(tmp_path, triage_data_path)
        except Exception:
            # Clean up stale tmp on failure (catches OSError + unexpected errors)
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
            triage_data_path = None  # Fallback to inline

        # Format message with structured triage data
        message = format_block_message(
            results, context_paths, parallel_config,
            category_descriptions=cat_descs,
            triage_data_path=triage_data_path,
        )
        print(json.dumps({"decision": "block", "reason": message}))
        return 0
    else:
        # Allow stop: nothing to save
        return 0


if __name__ == "__main__":
    sys.exit(main())
