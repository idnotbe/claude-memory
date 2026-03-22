#!/usr/bin/env python3
"""Log anomaly analyzer for claude-memory plugin.

Reads JSONL log files produced by memory_logger.py and detects
operational anomalies: skip-rate spikes, missing pipeline stages,
category threshold misconfiguration, performance degradation, etc.

Directory structure expected:
    {root}/logs/{event_category}/{YYYY-MM-DD}.jsonl

Usage:
    python3 memory_log_analyzer.py --root .claude/memory
    python3 memory_log_analyzer.py --root .claude/memory --days 14 --format json

No external dependencies (stdlib only).
"""

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Safe characters for path components (traversal prevention)
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")

# Severity ordering (for output sorting)
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "warning": 3}

# All triage categories the plugin knows about
_ALL_TRIAGE_CATEGORIES = frozenset({
    "DECISION", "RUNBOOK", "CONSTRAINT",
    "TECH_DEBT", "PREFERENCE", "SESSION_SUMMARY",
})

# Anomaly thresholds
_SKIP_RATE_THRESHOLD = 0.90        # 90% skip rate = critical
_ZERO_PROMPT_THRESHOLD = 0.50      # 50% of skips with prompt_length=0
_ERROR_RATE_THRESHOLD = 0.10       # 10% error rate in any category
_MAX_EVENTS = 100_000              # Memory safety: cap loaded events

# Minimum sample sizes for rate-based anomaly detection (statistical validity)
_MIN_SKIP_EVENTS_ZERO_PROMPT = 10   # _detect_zero_length_prompt
_MIN_RETRIEVAL_EVENTS_SKIP_RATE = 20  # _detect_skip_rate_high
_MIN_TRIAGE_EVENTS_CATEGORY = 30   # _detect_category_never_triggers
_MIN_TRIAGE_EVENTS_BOOSTER = 50    # _detect_booster_never_hits
_MIN_ERROR_SPIKE_EVENTS = 10       # _detect_error_spike (per-category)


# ---------------------------------------------------------------------------
# File loading (security-aware)
# ---------------------------------------------------------------------------

def _is_safe_path(base: Path, target: Path) -> bool:
    """Verify *target* is contained within *base* (no symlink escape)."""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except ValueError:
        return False


def _load_events(root: Path, start_date: str, end_date: str):
    """Load all JSONL events from {root}/logs/**/*.jsonl within date range.

    Returns a list of parsed dicts.  Malformed lines are silently skipped
    (fail-open: one bad line should not abort the analysis).

    Symlinks are skipped to prevent traversal attacks.
    """
    logs_dir = root / "logs"
    if not logs_dir.is_dir():
        return []

    events = []
    base_resolved = logs_dir.resolve()

    for category_dir in sorted(logs_dir.iterdir()):
        # Skip symlinks, hidden files, non-directories
        if category_dir.is_symlink():
            continue
        if not category_dir.is_dir() or category_dir.name.startswith("."):
            continue
        if not _SAFE_NAME_RE.match(category_dir.name):
            continue
        if not _is_safe_path(logs_dir, category_dir):
            continue

        for log_file in sorted(category_dir.iterdir()):
            if log_file.is_symlink():
                continue
            if not log_file.is_file() or log_file.suffix != ".jsonl":
                continue
            if not _SAFE_NAME_RE.match(log_file.name):
                continue

            # Date filtering: filename is YYYY-MM-DD.jsonl
            file_date = log_file.stem  # e.g. "2026-03-15"
            if file_date < start_date or file_date > end_date:
                continue

            try:
                with open(str(log_file), "r", encoding="utf-8") as fh:
                    for line_no, line in enumerate(fh, 1):
                        line = line.strip()
                        if not line:
                            continue
                        if len(events) >= _MAX_EVENTS:
                            return events  # Memory safety cap
                        try:
                            entry = json.loads(line)
                            if isinstance(entry, dict):
                                # Coerce event_type to str (prevent None.split())
                                if "event_type" in entry:
                                    entry["event_type"] = str(
                                        entry["event_type"] or ""
                                    )
                                events.append(entry)
                        except (json.JSONDecodeError, ValueError):
                            pass  # Fail-open: skip malformed lines
            except OSError:
                pass  # Fail-open: skip unreadable files

    return events


# ---------------------------------------------------------------------------
# Anomaly detection
# ---------------------------------------------------------------------------

def _detect_skip_rate_high(events, event_counts):
    """SKIP_RATE_HIGH: retrieval.skip >90% of all retrieval events."""
    retrieval_events = sum(
        c for et, c in event_counts.items()
        if et.startswith("retrieval.")
    )
    skip_count = event_counts.get("retrieval.skip", 0)

    if retrieval_events == 0:
        return None

    # Guard: insufficient sample size for reliable rate calculation
    if retrieval_events < _MIN_RETRIEVAL_EVENTS_SKIP_RATE:
        return None

    skip_rate = skip_count / retrieval_events
    if skip_rate <= _SKIP_RATE_THRESHOLD:
        return None

    return {
        "severity": "critical",
        "code": "SKIP_RATE_HIGH",
        "message": (
            f"Retrieval skip rate is {skip_rate * 100:.1f}% "
            f"({skip_count}/{retrieval_events}). "
            f"Memory injection not functioning."
        ),
        "data": {
            "skip_count": skip_count,
            "total_retrieval": retrieval_events,
            "skip_rate": round(skip_rate, 4),
            "sample_size": retrieval_events,
        },
    }


def _detect_zero_length_prompt(events, event_counts):
    """ZERO_LENGTH_PROMPT: >50% of retrieval.skip events have prompt_length=0."""
    skip_events = [
        e for e in events if e.get("event_type") == "retrieval.skip"
    ]
    if not skip_events:
        return None

    # Guard: insufficient sample size for reliable rate calculation
    if len(skip_events) < _MIN_SKIP_EVENTS_ZERO_PROMPT:
        return None

    zero_count = sum(
        1 for e in skip_events
        if isinstance(e.get("data"), dict)
        and e["data"].get("prompt_length", -1) == 0
    )
    zero_rate = zero_count / len(skip_events)
    if zero_rate <= _ZERO_PROMPT_THRESHOLD:
        return None

    return {
        "severity": "critical",
        "code": "ZERO_LENGTH_PROMPT",
        "message": (
            f"{zero_rate * 100:.1f}% of retrieval.skip events have "
            f"prompt_length=0 ({zero_count}/{len(skip_events)}). "
            f"Hook is not receiving user prompts."
        ),
        "data": {
            "zero_count": zero_count,
            "total_skip": len(skip_events),
            "zero_rate": round(zero_rate, 4),
            "sample_size": len(skip_events),
        },
    }


def _detect_category_never_triggers(events, event_counts):
    """CATEGORY_NEVER_TRIGGERS: category has 0 triggers but non-zero scores."""
    triage_events = [
        e for e in events if e.get("event_type") == "triage.score"
    ]
    if not triage_events:
        return []

    # Guard: insufficient sample size for reliable category analysis
    if len(triage_events) < _MIN_TRIAGE_EVENTS_CATEGORY:
        return []

    # Collect per-category: trigger count + whether it ever had score > 0
    trigger_counts = Counter()
    has_nonzero_score = set()

    for e in triage_events:
        data = e.get("data", {})
        if not isinstance(data, dict):
            continue

        # Count triggers
        triggered = data.get("triggered", [])
        if isinstance(triggered, list):
            for t in triggered:
                if isinstance(t, dict) and "category" in t:
                    trigger_counts[t["category"]] += 1

        # Check all_scores for non-zero values
        all_scores = data.get("all_scores", [])
        if isinstance(all_scores, list):
            for s in all_scores:
                if (
                    isinstance(s, dict)
                    and s.get("score", 0) > 0
                    and "category" in s
                ):
                    has_nonzero_score.add(s["category"])

    findings = []
    for cat in sorted(_ALL_TRIAGE_CATEGORIES):
        if trigger_counts.get(cat, 0) == 0 and cat in has_nonzero_score:
            findings.append({
                "severity": "high",
                "code": "CATEGORY_NEVER_TRIGGERS",
                "message": (
                    f"Category {cat} has non-zero scores but never triggers. "
                    f"Threshold may be too high."
                    f" (based on {len(triage_events)} triage events)"
                ),
                "data": {
                    "category": cat,
                    "trigger_count": 0,
                    "has_nonzero_scores": True,
                    "sample_size": len(triage_events),
                },
            })

    return findings


def _detect_booster_never_hits(events, event_counts):
    """BOOSTER_NEVER_HITS: category has 0 booster hits but non-zero primary scores.

    Requires triage.score events to include per-category primary_hits and
    booster_hits fields in all_scores. If these fields are absent (old log
    format), the detector is silently skipped.
    """
    triage_events = [
        e for e in events if e.get("event_type") == "triage.score"
    ]
    if not triage_events:
        return []

    # Accumulate per-category: total primary hits and total booster hits
    # Count only new-format events (with both booster fields) for sample size
    cat_primary_total = Counter()
    cat_booster_total = Counter()
    new_format_count = 0

    for e in triage_events:
        data = e.get("data", {})
        if not isinstance(data, dict):
            continue
        all_scores = data.get("all_scores", [])
        if not isinstance(all_scores, list):
            continue
        event_has_booster = False
        for s in all_scores:
            if not isinstance(s, dict) or "category" not in s:
                continue
            # Detect new-format log data (require both fields)
            if "primary_hits" in s and "booster_hits" in s:
                event_has_booster = True
                cat = s["category"]
                cat_primary_total[cat] += s.get("primary_hits", 0)
                cat_booster_total[cat] += s.get("booster_hits", 0)
        if event_has_booster:
            new_format_count += 1

    # If no events contain booster fields, skip silently (old format)
    if new_format_count == 0:
        return []

    # Guard: insufficient new-format sample size
    if new_format_count < _MIN_TRIAGE_EVENTS_BOOSTER:
        return []

    findings = []
    for cat in sorted(_ALL_TRIAGE_CATEGORIES):
        # SESSION_SUMMARY is activity-based, no booster concept
        if cat == "SESSION_SUMMARY":
            continue
        primary = cat_primary_total.get(cat, 0)
        booster = cat_booster_total.get(cat, 0)
        if primary > 0 and booster == 0:
            findings.append({
                "severity": "warning",
                "code": "BOOSTER_NEVER_HITS",
                "message": (
                    f"Category {cat} has {primary} primary pattern hits "
                    f"but 0 booster hits across {new_format_count} "
                    f"triage events. Booster patterns may be too narrow."
                ),
                "data": {
                    "category": cat,
                    "primary_hits": primary,
                    "booster_hits": 0,
                    "sample_size": new_format_count,
                },
            })

    return findings


def _detect_missing_event_types(events, event_counts):
    """MISSING_EVENT_TYPES: retrieval events exist but no search/inject."""
    has_retrieval = any(
        et.startswith("retrieval.") for et in event_counts
    )
    if not has_retrieval:
        return None

    has_search = event_counts.get("retrieval.search", 0) > 0
    has_inject = event_counts.get("retrieval.inject", 0) > 0

    if has_search or has_inject:
        return None

    present = sorted(
        et for et in event_counts if et.startswith("retrieval.")
    )
    return {
        "severity": "high",
        "code": "MISSING_EVENT_TYPES",
        "message": (
            f"Retrieval events exist but no retrieval.search or "
            f"retrieval.inject events found. Pipeline not reaching "
            f"search stage. Present types: {', '.join(present)}"
        ),
        "data": {
            "present_types": present,
            "missing": ["retrieval.search", "retrieval.inject"],
        },
    }


def _detect_error_spike(events, event_counts):
    """ERROR_SPIKE: error-level events exceed 10% of total in any log category."""
    # Group by log category (first part of event_type)
    category_totals = Counter()
    category_errors = Counter()

    for e in events:
        et = e.get("event_type", "")
        cat = et.split(".")[0] if "." in et else et
        category_totals[cat] += 1
        if e.get("level") == "error":
            category_errors[cat] += 1

    findings = []
    for cat in sorted(category_totals):
        total = category_totals[cat]
        errors = category_errors.get(cat, 0)
        if total < _MIN_ERROR_SPIKE_EVENTS:
            continue
        if total > 0 and errors / total > _ERROR_RATE_THRESHOLD:
            error_rate = errors / total
            findings.append({
                "severity": "high",
                "code": "ERROR_SPIKE",
                "message": (
                    f"Error rate in '{cat}' is {error_rate * 100:.1f}% "
                    f"({errors}/{total}). Investigate error-level events."
                ),
                "data": {
                    "category": cat,
                    "error_count": errors,
                    "total_count": total,
                    "error_rate": round(error_rate, 4),
                    "sample_size": total,
                },
            })

    return findings


def _detect_perf_degradation(events, event_counts):
    """PERF_DEGRADATION: avg duration_ms increases >50% first vs last day."""
    # Group duration_ms by date
    durations_by_date = defaultdict(list)

    for e in events:
        ts = e.get("timestamp", "")
        dur = e.get("duration_ms")
        if dur is None or not isinstance(dur, (int, float)):
            continue
        # Extract date from ISO timestamp
        date_str = ts[:10] if len(ts) >= 10 else ""
        if date_str:
            durations_by_date[date_str].append(dur)

    if len(durations_by_date) < 2:
        return None

    sorted_dates = sorted(durations_by_date.keys())
    first_day = sorted_dates[0]
    last_day = sorted_dates[-1]

    first_avg = (
        sum(durations_by_date[first_day]) / len(durations_by_date[first_day])
    )
    last_avg = (
        sum(durations_by_date[last_day]) / len(durations_by_date[last_day])
    )

    if first_avg <= 0:
        return None

    increase_pct = (last_avg - first_avg) / first_avg
    if increase_pct <= 0.50:
        return None

    return {
        "severity": "medium",
        "code": "PERF_DEGRADATION",
        "message": (
            f"Average duration_ms increased by {increase_pct * 100:.0f}% "
            f"from {first_day} ({first_avg:.1f}ms) to "
            f"{last_day} ({last_avg:.1f}ms)."
        ),
        "data": {
            "first_day": first_day,
            "first_avg_ms": round(first_avg, 1),
            "last_day": last_day,
            "last_avg_ms": round(last_avg, 1),
            "increase_pct": round(increase_pct, 4),
        },
    }


# ---------------------------------------------------------------------------
# Analysis orchestrator
# ---------------------------------------------------------------------------

def analyze(root: Path, days: int) -> dict:
    """Run all anomaly detectors and return structured results."""
    now = datetime.now(timezone.utc)
    end_date = now.strftime("%Y-%m-%d")
    start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

    events = _load_events(root, start_date, end_date)

    # Handle no-data case
    if not events:
        return {
            "analysis_date": end_date,
            "period": {"start": start_date, "end": end_date},
            "total_events": 0,
            "event_breakdown": {},
            "findings": [
                {
                    "severity": "warning",
                    "code": "NO_DATA",
                    "message": (
                        f"No log data found for period "
                        f"{start_date} to {end_date}."
                    ),
                    "data": {"days": days},
                }
            ],
            "recommendations": [
                "Verify logging is enabled in memory-config.json "
                "(logging.enabled: true).",
                "Check that log files exist at "
                "{root}/logs/{category}/{date}.jsonl.",
            ],
        }

    # Build event breakdown
    event_counts = Counter(e.get("event_type", "unknown") for e in events)

    # Determine actual date range from data
    timestamps = [e.get("timestamp", "")[:10] for e in events]
    actual_dates = sorted(set(d for d in timestamps if d))
    actual_start = actual_dates[0] if actual_dates else start_date
    actual_end = actual_dates[-1] if actual_dates else end_date

    # Run all detectors
    findings = []

    result = _detect_skip_rate_high(events, event_counts)
    if result:
        findings.append(result)

    result = _detect_zero_length_prompt(events, event_counts)
    if result:
        findings.append(result)

    findings.extend(_detect_category_never_triggers(events, event_counts))

    findings.extend(_detect_booster_never_hits(events, event_counts))

    result = _detect_missing_event_types(events, event_counts)
    if result:
        findings.append(result)

    findings.extend(_detect_error_spike(events, event_counts))

    result = _detect_perf_degradation(events, event_counts)
    if result:
        findings.append(result)

    # Sort findings by severity
    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f["severity"], 99))

    # Generate recommendations
    recommendations = _generate_recommendations(findings)

    return {
        "analysis_date": end_date,
        "period": {"start": actual_start, "end": actual_end},
        "total_events": len(events),
        "event_breakdown": dict(
            sorted(event_counts.items(), key=lambda x: -x[1])
        ),
        "findings": findings,
        "recommendations": recommendations,
    }


def _generate_recommendations(findings: list) -> list:
    """Map findings to actionable recommendations."""
    recs = []
    codes_seen = {f["code"] for f in findings}

    if "SKIP_RATE_HIGH" in codes_seen:
        recs.append(
            "Investigate why retrieval hook is skipping all prompts. "
            "Check if prompt extraction from hook input JSON is working."
        )

    if "ZERO_LENGTH_PROMPT" in codes_seen:
        recs.append(
            "Hook is receiving prompt_length=0. This likely indicates "
            "the UserPromptSubmit hook input field name has changed or "
            "prompt extraction logic has a bug."
        )

    if "CATEGORY_NEVER_TRIGGERS" in codes_seen:
        never_cats = sorted(
            f["data"]["category"]
            for f in findings
            if f["code"] == "CATEGORY_NEVER_TRIGGERS"
        )
        recs.append(
            f"Categories {', '.join(never_cats)} score above zero but "
            f"never exceed their trigger thresholds. Consider lowering "
            f"thresholds in memory-config.json (triage.thresholds)."
        )

    if "BOOSTER_NEVER_HITS" in codes_seen:
        booster_cats = sorted(
            f["data"]["category"]
            for f in findings
            if f["code"] == "BOOSTER_NEVER_HITS"
        )
        recs.append(
            f"Categories {', '.join(booster_cats)} have primary pattern "
            f"matches but zero booster co-occurrence hits. Review booster "
            f"patterns in memory_triage.py CATEGORY_PATTERNS or check "
            f"that conversation content includes contextual booster terms."
        )

    if "MISSING_EVENT_TYPES" in codes_seen:
        recs.append(
            "Retrieval pipeline does not reach the search stage. "
            "All prompts are being skipped before FTS5 search runs. "
            "Fix the skip-rate issue first."
        )

    if "ERROR_SPIKE" in codes_seen:
        recs.append(
            "High error rate detected. Check log files for error-level "
            "entries to identify the root cause (e.g., missing files, "
            "permission issues, schema validation failures)."
        )

    if "PERF_DEGRADATION" in codes_seen:
        recs.append(
            "Hook execution time is increasing over time. Check for "
            "growing index size, FTS5 database bloat, or increased "
            "memory file count."
        )

    if not recs:
        recs.append("No anomalies detected. System operating normally.")

    return recs


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

_SEVERITY_ICONS = {
    "critical": "[CRITICAL]",
    "high": "[HIGH]    ",
    "medium": "[MEDIUM]  ",
    "warning": "[WARNING] ",
}


def format_text(result: dict) -> str:
    """Format analysis result as human-readable text."""
    lines = []
    lines.append("=" * 68)
    lines.append("  claude-memory Log Analysis Report")
    lines.append("=" * 68)
    lines.append("")
    lines.append(
        f"  Analysis date : {result['analysis_date']}"
    )
    lines.append(
        f"  Period        : {result['period']['start']} "
        f"to {result['period']['end']}"
    )
    lines.append(
        f"  Total events  : {result['total_events']}"
    )
    lines.append("")

    # Event breakdown
    if result["event_breakdown"]:
        lines.append("  Event Breakdown:")
        for et, count in result["event_breakdown"].items():
            lines.append(f"    {et:30s} {count:>6}")
        lines.append("")

    # Findings
    findings = result["findings"]
    if findings:
        lines.append(f"  Findings ({len(findings)}):")
        lines.append("-" * 68)
        for f in findings:
            icon = _SEVERITY_ICONS.get(f["severity"], "[?]       ")
            lines.append(f"  {icon}  {f['code']}")
            lines.append(f"              {f['message']}")
            lines.append("")
    else:
        lines.append("  Findings: None -- system operating normally.")
        lines.append("")

    # Recommendations
    if result["recommendations"]:
        lines.append("  Recommendations:")
        lines.append("-" * 68)
        for i, rec in enumerate(result["recommendations"], 1):
            lines.append(f"  {i}. {rec}")
        lines.append("")

    lines.append("=" * 68)
    return "\n".join(lines)


def format_json(result: dict) -> str:
    """Format analysis result as JSON."""
    return json.dumps(result, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Analyze claude-memory JSONL logs for anomalies."
    )
    parser.add_argument(
        "--root",
        required=True,
        help="Memory root directory (containing logs/ subdirectory)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Analyze last N days (default: 7)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        dest="output_format",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    # Validate --days
    if args.days < 1:
        print("Error: --days must be >= 1", file=sys.stderr)
        sys.exit(1)

    root = Path(args.root)
    if not root.is_dir():
        print(
            f"Error: root directory does not exist: {args.root}",
            file=sys.stderr,
        )
        sys.exit(1)

    result = analyze(root, args.days)

    if args.output_format == "json":
        print(format_json(result))
    else:
        print(format_text(result))

    # Exit code: 1 if critical findings, 0 otherwise
    has_critical = any(
        f["severity"] == "critical" for f in result["findings"]
    )
    sys.exit(1 if has_critical else 0)


if __name__ == "__main__":
    main()
