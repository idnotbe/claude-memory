"""Shared fixtures for claude-memory ACE v4.2 tests."""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

# Add scripts directory to path so we can import modules directly
SCRIPTS_DIR = str(Path(__file__).parent.parent / "hooks" / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Sample memory data factories
# ---------------------------------------------------------------------------

def make_decision_memory(
    id_val="use-jwt",
    title="Use JWT for authentication",
    tags=None,
    record_status="active",
    retired_at=None,
    retired_reason=None,
    times_updated=0,
    changes=None,
    related_files=None,
    confidence=0.9,
    content_overrides=None,
):
    """Build a valid decision memory dict."""
    content = {
        "status": "accepted",
        "context": "Need stateless auth for API",
        "decision": "Use JWT tokens with 1h expiry",
        "rationale": ["Stateless", "Industry standard"],
        "alternatives": [{"option": "Session cookies", "rejected_reason": "Not stateless"}],
        "consequences": ["Must handle token refresh"],
    }
    if content_overrides:
        content.update(content_overrides)
    data = {
        "schema_version": "1.0",
        "category": "decision",
        "id": id_val,
        "title": title,
        "record_status": record_status,
        "created_at": "2026-01-15T10:00:00Z",
        "updated_at": "2026-02-10T10:00:00Z",
        "tags": tags or ["auth", "jwt", "security"],
        "related_files": related_files,
        "confidence": confidence,
        "content": content,
        "changes": changes or [],
        "times_updated": times_updated,
    }
    if retired_at:
        data["retired_at"] = retired_at
    if retired_reason:
        data["retired_reason"] = retired_reason
    return data


def make_preference_memory(
    id_val="prefer-typescript",
    title="Prefer TypeScript over JavaScript",
    tags=None,
    record_status="active",
    times_updated=0,
    changes=None,
):
    """Build a valid preference memory dict."""
    data = {
        "schema_version": "1.0",
        "category": "preference",
        "id": id_val,
        "title": title,
        "record_status": record_status,
        "created_at": "2026-01-10T08:00:00Z",
        "updated_at": "2026-02-01T08:00:00Z",
        "tags": tags or ["typescript", "language"],
        "confidence": 0.95,
        "content": {
            "topic": "Programming language choice",
            "value": "TypeScript",
            "reason": "Better type safety and tooling",
            "strength": "strong",
            "examples": {
                "prefer": ["TypeScript for new projects"],
                "avoid": ["Plain JavaScript for anything beyond scripts"],
            },
        },
        "changes": changes or [],
        "times_updated": times_updated,
    }
    return data


def make_tech_debt_memory(
    id_val="legacy-api-v1",
    title="Legacy API v1 cleanup",
    tags=None,
    record_status="active",
    retired_at=None,
    times_updated=0,
):
    """Build a valid tech_debt memory dict."""
    data = {
        "schema_version": "1.0",
        "category": "tech_debt",
        "id": id_val,
        "title": title,
        "record_status": record_status,
        "created_at": "2026-01-20T12:00:00Z",
        "updated_at": "2026-02-05T12:00:00Z",
        "tags": tags or ["api", "legacy", "cleanup"],
        "confidence": 0.7,
        "content": {
            "status": "open",
            "priority": "medium",
            "description": "API v1 endpoints still in production",
            "reason_deferred": "Migration requires client coordination",
            "impact": ["Dual maintenance burden"],
            "suggested_fix": ["Deprecate v1 endpoints", "Migrate clients"],
        },
        "changes": [],
        "times_updated": times_updated,
    }
    if retired_at:
        data["retired_at"] = retired_at
        data["retired_reason"] = "Resolved"
    return data


def make_session_memory(
    id_val="session-2026-02-14",
    title="Implemented ACE v4.2 tests",
    tags=None,
    record_status="active",
    times_updated=0,
):
    """Build a valid session_summary memory dict."""
    data = {
        "schema_version": "1.0",
        "category": "session_summary",
        "id": id_val,
        "title": title,
        "record_status": record_status,
        "created_at": "2026-02-14T09:00:00Z",
        "updated_at": "2026-02-14T17:00:00Z",
        "tags": tags or ["testing", "ace"],
        "confidence": 0.85,
        "content": {
            "goal": "Write comprehensive tests",
            "outcome": "success",
            "completed": ["Test suite for all 6 scripts"],
            "next_actions": ["Review test coverage"],
        },
        "changes": [],
        "times_updated": times_updated,
    }
    return data


def make_runbook_memory(
    id_val="fix-db-connection",
    title="Fix database connection timeout",
    tags=None,
    record_status="active",
):
    """Build a valid runbook memory dict."""
    data = {
        "schema_version": "1.0",
        "category": "runbook",
        "id": id_val,
        "title": title,
        "record_status": record_status,
        "created_at": "2026-01-25T14:00:00Z",
        "updated_at": "2026-02-01T14:00:00Z",
        "tags": tags or ["database", "connection", "timeout"],
        "confidence": 0.8,
        "content": {
            "trigger": "Database connection timeout errors in logs",
            "symptoms": ["Slow queries", "Connection pool exhaustion"],
            "steps": ["Check connection pool size", "Restart connection pool", "Monitor"],
            "verification": "Query response time < 100ms",
            "root_cause": "Connection leak in ORM",
        },
        "changes": [],
        "times_updated": 0,
    }
    return data


def make_constraint_memory(
    id_val="max-payload-size",
    title="Maximum payload size limit",
    tags=None,
    record_status="active",
):
    """Build a valid constraint memory dict."""
    data = {
        "schema_version": "1.0",
        "category": "constraint",
        "id": id_val,
        "title": title,
        "record_status": record_status,
        "created_at": "2026-01-18T11:00:00Z",
        "updated_at": "2026-01-30T11:00:00Z",
        "tags": tags or ["api", "payload", "limit"],
        "confidence": 1.0,
        "content": {
            "kind": "technical",
            "rule": "API payloads must not exceed 10MB",
            "impact": ["Large file uploads need chunking"],
            "workarounds": ["Use multipart upload"],
            "severity": "high",
            "active": True,
        },
        "changes": [],
        "times_updated": 0,
    }
    return data


# ---------------------------------------------------------------------------
# Index fixtures
# ---------------------------------------------------------------------------

FOLDER_MAP = {
    "session_summary": "sessions",
    "decision": "decisions",
    "runbook": "runbooks",
    "constraint": "constraints",
    "tech_debt": "tech-debt",
    "preference": "preferences",
}


def build_enriched_index(*memories, path_prefix=".claude/memory"):
    """Build an enriched index.md content string from memory dicts.

    Args:
        *memories: Memory dicts to include.
        path_prefix: The prefix for paths in the index. Default is
            ".claude/memory" which is the standard project-relative path.
            Pass a different prefix (e.g. an absolute path or relative path)
            to match the test's directory structure.
    """
    from memory_candidate import CATEGORY_DISPLAY
    lines = [
        "# Memory Index",
        "",
        "<!-- Auto-generated by memory_index.py. Do not edit manually. -->",
        "",
    ]
    for m in memories:
        cat = m["category"]
        display = CATEGORY_DISPLAY.get(cat, cat.upper())
        title = m["title"]
        folder = FOLDER_MAP[cat]
        path = f"{path_prefix}/{folder}/{m['id']}.json"
        tags = m.get("tags", [])
        line = f"- [{display}] {title} -> {path}"
        if tags:
            line += f" #tags:{','.join(tags)}"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Filesystem fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def memory_root(tmp_path):
    """Create a temporary memory root directory with category subdirs."""
    root = tmp_path / "memory"
    root.mkdir()
    for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
        (root / folder).mkdir()
    return root


@pytest.fixture
def memory_project(tmp_path):
    """Create a full project-like structure with .claude/memory/."""
    proj = tmp_path / "project"
    proj.mkdir()
    dc = proj / ".claude"
    dc.mkdir()
    mem = dc / "memory"
    mem.mkdir()
    for folder in ["sessions", "decisions", "runbooks", "constraints", "tech-debt", "preferences"]:
        (mem / folder).mkdir()
    return proj


def write_memory_file(memory_root, memory_data):
    """Write a memory JSON file to the appropriate category folder."""
    folder_map = {
        "session_summary": "sessions",
        "decision": "decisions",
        "runbook": "runbooks",
        "constraint": "constraints",
        "tech_debt": "tech-debt",
        "preference": "preferences",
    }
    cat = memory_data["category"]
    folder = folder_map[cat]
    file_path = memory_root / folder / f"{memory_data['id']}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(memory_data, f, indent=2)
    return file_path


def write_index(memory_root, *memories, path_prefix=".claude/memory"):
    """Write an index.md file for the given memories."""
    content = build_enriched_index(*memories, path_prefix=path_prefix)
    index_path = memory_root / "index.md"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)
    return index_path
