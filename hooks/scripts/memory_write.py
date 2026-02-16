#!/usr/bin/env python3
"""Schema-enforced memory write tool for claude-memory plugin.

Handles CREATE, UPDATE, DELETE, ARCHIVE, UNARCHIVE, and RESTORE operations
with Pydantic validation, mechanical merge protections, OCC, atomic writes,
and index management.

Usage:
  python3 memory_write.py --action create --category decision \
    --target .claude/memory/decisions/use-jwt.json \
    --input /tmp/.memory-write-pending.json

  python3 memory_write.py --action update --category decision \
    --target .claude/memory/decisions/use-jwt.json \
    --input /tmp/.memory-write-pending.json --hash <md5>

  python3 memory_write.py --action delete \
    --target .claude/memory/decisions/use-jwt.json \
    --reason "Decision reversed"
"""

import sys
import os

# Bootstrap: re-exec under the plugin venv if pydantic is not importable.
# The venv may have a different Python version with compiled C extensions
# (pydantic_core .so), so site-packages injection alone is not enough.
_venv_python = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '.venv', 'bin', 'python3'
)
if os.path.isfile(_venv_python) and os.path.realpath(sys.executable) != os.path.realpath(_venv_python):
    try:
        import pydantic  # noqa: F401 -- quick availability check
    except ImportError:
        os.execv(_venv_python, [_venv_python] + sys.argv)

import argparse
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator, ValidationError
except ImportError:
    print("ERROR: pydantic>=2.0 is required. Install: pip install 'pydantic>=2.0,<3.0'", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

TAG_CAP = 12
CHANGES_CAP = 50
ID_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$")


# ---------------------------------------------------------------------------
# Category-specific content models
# ---------------------------------------------------------------------------

class Alternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option: str
    rejected_reason: str


class DecisionContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["proposed", "accepted", "deprecated", "superseded"]
    context: str
    decision: str
    alternatives: Optional[list[Alternative]] = None
    rationale: list[str] = Field(min_length=1)
    consequences: Optional[list[str]] = None


class SessionSummaryContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str
    outcome: Literal["success", "partial", "blocked", "abandoned"]
    completed: list[str]
    in_progress: Optional[list[str]] = None
    blockers: Optional[list[str]] = None
    next_actions: list[str]
    key_changes: Optional[list[str]] = None


class RunbookContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trigger: str
    symptoms: Optional[list[str]] = None
    steps: list[str] = Field(min_length=1)
    verification: str
    root_cause: Optional[str] = None
    environment: Optional[str] = None


class ConstraintContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["limitation", "gap", "policy", "technical"]
    rule: str
    impact: list[str] = Field(min_length=1)
    workarounds: Optional[list[str]] = None
    severity: Literal["high", "medium", "low"]
    active: bool
    expires: Optional[str] = None


class TechDebtContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "in_progress", "resolved", "wont_fix"]
    priority: Literal["critical", "high", "medium", "low"]
    description: str
    reason_deferred: str
    impact: Optional[list[str]] = None
    suggested_fix: Optional[list[str]] = None
    acceptance_criteria: Optional[list[str]] = None


class PreferenceExamples(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prefer: Optional[list[str]] = None
    avoid: Optional[list[str]] = None


class PreferenceContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str
    value: str
    reason: str
    strength: Literal["strong", "default", "soft"]
    examples: Optional[PreferenceExamples] = None


CONTENT_MODELS = {
    "session_summary": SessionSummaryContent,
    "decision": DecisionContent,
    "runbook": RunbookContent,
    "constraint": ConstraintContent,
    "tech_debt": TechDebtContent,
    "preference": PreferenceContent,
}


# ---------------------------------------------------------------------------
# Change log entry model
# ---------------------------------------------------------------------------

class ChangeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: str
    summary: str = Field(max_length=300)
    field: Optional[str] = None
    old_value: Optional[object] = None
    new_value: Optional[object] = None


# ---------------------------------------------------------------------------
# Base memory model (built dynamically per category)
# ---------------------------------------------------------------------------

_model_cache: dict[str, type[BaseModel]] = {}


def build_memory_model(category: str) -> type[BaseModel]:
    """Build a Pydantic model for the given category (cached)."""
    if category in _model_cache:
        return _model_cache[category]

    from pydantic import create_model

    content_cls = CONTENT_MODELS[category]
    cat_literal = Literal[category]  # type: ignore[valid-type]

    model = create_model(
        f"{category.title().replace('_', '')}Memory",
        __config__=ConfigDict(extra="forbid"),
        schema_version=(Literal["1.0"], ...),
        category=(cat_literal, ...),
        id=(str, Field(pattern=r"^[a-z0-9]([a-z0-9-]{0,78}[a-z0-9])?$")),
        title=(str, Field(max_length=120)),
        record_status=(Literal["active", "retired", "archived"], "active"),
        created_at=(str, ...),
        updated_at=(str, ...),
        tags=(list[str], Field(min_length=1)),
        related_files=(Optional[list[str]], None),
        confidence=(Optional[float], Field(None, ge=0.0, le=1.0)),
        content=(content_cls, ...),
        changes=(Optional[list[ChangeEntry]], None),
        times_updated=(int, 0),
        retired_at=(Optional[str], None),
        retired_reason=(Optional[str], None),
        archived_at=(Optional[str], None),
        archived_reason=(Optional[str], None),
    )

    _model_cache[category] = model
    return model


# ---------------------------------------------------------------------------
# Auto-fix helpers
# ---------------------------------------------------------------------------

def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(text: str) -> str:
    """Convert text to kebab-case slug."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    # Enforce max length of 80
    if len(text) > 80:
        text = text[:80].rstrip("-")
    return text


def auto_fix(data: dict, action: str) -> dict:
    """Apply auto-fix rules. Logs fixes to stderr."""
    # schema_version
    if "schema_version" not in data or not data["schema_version"]:
        data["schema_version"] = "1.0"
        print("[AUTO-FIX] schema_version: set to '1.0'", file=sys.stderr)

    # updated_at
    if "updated_at" not in data or not data["updated_at"]:
        data["updated_at"] = now_utc()
        print("[AUTO-FIX] updated_at: set to current UTC", file=sys.stderr)

    # created_at on CREATE
    if action == "create" and ("created_at" not in data or not data["created_at"]):
        data["created_at"] = now_utc()
        print("[AUTO-FIX] created_at: set to current UTC", file=sys.stderr)

    # tags: string -> array
    if isinstance(data.get("tags"), str):
        data["tags"] = [data["tags"]]
        print("[AUTO-FIX] tags: wrapped string in array", file=sys.stderr)

    # id: slugify
    if "id" in data and data["id"]:
        original_id = data["id"]
        fixed_id = slugify(original_id)
        if fixed_id != original_id:
            data["id"] = fixed_id
            print(f"[AUTO-FIX] id: slugified '{original_id}' -> '{fixed_id}'", file=sys.stderr)

    # confidence: clamp
    if data.get("confidence") is not None:
        try:
            c = float(data["confidence"])
            if c < 0.0:
                data["confidence"] = 0.0
                print("[AUTO-FIX] confidence: clamped to 0.0", file=sys.stderr)
            elif c > 1.0:
                data["confidence"] = 1.0
                print("[AUTO-FIX] confidence: clamped to 1.0", file=sys.stderr)
        except (TypeError, ValueError):
            pass

    # Strip whitespace from string fields
    for field in ("title", "id"):
        if isinstance(data.get(field), str):
            stripped = data[field].strip()
            if stripped != data[field]:
                data[field] = stripped
                print(f"[AUTO-FIX] {field}: stripped whitespace", file=sys.stderr)

    # Sanitize title: strip control characters and index-injection markers
    if isinstance(data.get("title"), str):
        original_title = data["title"]
        # Strip all control characters (null bytes, newlines, tabs, etc.)
        sanitized = re.sub(r'[\x00-\x1f\x7f]', '', original_title).strip()
        # Strip index-injection markers
        sanitized = sanitized.replace(" -> ", " - ").replace("#tags:", "")
        if sanitized != original_title:
            data["title"] = sanitized
            print("[AUTO-FIX] title: stripped control chars/index-injection markers", file=sys.stderr)

    # Dedupe and sort tags (with sanitization)
    if isinstance(data.get("tags"), list):
        sanitized_tags = []
        for t in data["tags"]:
            if not isinstance(t, str) or not t.strip():
                continue
            sanitized = t.lower().strip()
            # Remove control characters (newlines, carriage returns, tabs, null bytes)
            sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized)
            # Remove index format characters (commas, arrow separator, tags prefix)
            sanitized = sanitized.replace(',', ' ').replace(' -> ', ' ').replace('#tags:', '')
            sanitized = sanitized.strip()
            if sanitized:
                sanitized_tags.append(sanitized)
        data["tags"] = sorted(set(sanitized_tags))
        if not data["tags"]:
            data["tags"] = ["untagged"]
            print("[AUTO-FIX] tags: empty after dedup, set to ['untagged']", file=sys.stderr)

    # Enforce TAG_CAP on tags
    if isinstance(data.get("tags"), list) and len(data["tags"]) > TAG_CAP:
        data["tags"] = data["tags"][:TAG_CAP]
        print(f"[AUTO-FIX] tags: truncated to TAG_CAP ({TAG_CAP})", file=sys.stderr)

    return data


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_memory(data: dict, category: str) -> tuple[bool, Optional[str]]:
    """Validate data against the category model. Returns (ok, error_msg)."""
    Model = build_memory_model(category)
    try:
        Model.model_validate(data)
        return True, None
    except ValidationError as e:
        return False, format_validation_error(e)


def format_validation_error(e: ValidationError) -> str:
    """Format Pydantic error into the spec's error format."""
    lines = ["VALIDATION_ERROR"]
    for err in e.errors():
        loc = ".".join(str(l) for l in err["loc"])
        lines.append(f"field: {loc}")
        msg = err["msg"]
        lines.append(f"expected: {msg}")
        if "input" in err:
            lines.append(f"got: {json.dumps(err['input'])}")
        lines.append(f"fix: Correct the value for '{loc}'")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Index management
# ---------------------------------------------------------------------------

def build_index_line(data: dict, rel_path: str) -> str:
    """Build an enriched index line: - [CAT] title -> path #tags:t1,t2,..."""
    cat = data.get("category", "")
    display = CATEGORY_DISPLAY.get(cat, cat.upper())
    title = data.get("title", "")
    tags = data.get("tags", [])
    tag_str = ",".join(tags) if tags else ""
    line = f"- [{display}] {title} -> {rel_path}"
    if tag_str:
        line += f" #tags:{tag_str}"
    return line


def add_to_index(index_path: Path, line: str) -> None:
    """Add a line to index.md, maintaining sorted order."""
    lines = _read_index_lines(index_path)
    # Separate header and entry lines
    entries = []
    header = []
    for l in lines:
        if l.startswith("- ["):
            entries.append(l)
        else:
            header.append(l)
    entries.append(line)
    entries.sort(key=lambda x: x.lower())
    all_lines = header + entries
    content = "\n".join(all_lines)
    if not content.endswith("\n"):
        content += "\n"
    atomic_write_text(str(index_path), content)


def remove_from_index(index_path: Path, target_path: str) -> None:
    """Remove the entry matching target_path from index.md."""
    lines = _read_index_lines(index_path)
    filtered = [l for l in lines if not (l.startswith("- [") and f"-> {target_path}" in l)]
    content = "\n".join(filtered)
    if not content.endswith("\n"):
        content += "\n"
    atomic_write_text(str(index_path), content)


def update_index_entry(index_path: Path, old_path: str, new_line: str) -> None:
    """Replace the index entry for old_path with new_line."""
    lines = _read_index_lines(index_path)
    new_lines = []
    replaced = False
    for l in lines:
        if l.startswith("- [") and f"-> {old_path}" in l:
            new_lines.append(new_line)
            replaced = True
        else:
            new_lines.append(l)
    if not replaced:
        # Entry not found, add it
        add_to_index(index_path, new_line)
        return
    content = "\n".join(new_lines)
    if not content.endswith("\n"):
        content += "\n"
    atomic_write_text(str(index_path), content)


def _read_index_lines(index_path: Path) -> list[str]:
    """Read index.md lines, creating if missing."""
    if not index_path.exists():
        return [
            "# Memory Index", "",
            "<!-- Auto-generated by memory_index.py. Do not edit manually. -->", ""
        ]
    with open(index_path, "r", encoding="utf-8") as f:
        return [l.rstrip("\n") for l in f.readlines()]


# ---------------------------------------------------------------------------
# OCC / Atomic writes
# ---------------------------------------------------------------------------

def file_md5(path: str) -> Optional[str]:
    """Compute MD5 hash of a file. Returns None if file doesn't exist."""
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    except FileNotFoundError:
        return None


def atomic_write_text(target: str, content: str) -> None:
    """Write text atomically via unique tmp + rename."""
    import tempfile
    target_dir = os.path.dirname(target) or "."
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, suffix=".tmp", prefix=".mw-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.rename(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(target: str, data: dict) -> None:
    """Write JSON atomically via unique tmp + rename."""
    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    atomic_write_text(target, content)


# ---------------------------------------------------------------------------
# Merge protections (UPDATE)
# ---------------------------------------------------------------------------

def check_merge_protections(old: dict, new: dict) -> tuple[bool, Optional[str], list[dict]]:
    """Enforce mechanical merge rules. Returns (ok, error, auto_changes)."""
    auto_changes = []

    # Immutable fields
    for field in ("created_at", "schema_version", "category"):
        if old.get(field) != new.get(field):
            return False, (
                f"MERGE_ERROR\nfield: {field}\nrule: immutable\n"
                f"old: {json.dumps(old.get(field))}\n"
                f"new: {json.dumps(new.get(field))}\n"
                f"fix: Do not change '{field}' during UPDATE"
            ), []

    # record_status immutable via UPDATE (only via delete/archive)
    if old.get("record_status", "active") != new.get("record_status", "active"):
        return False, (
            "MERGE_ERROR\nfield: record_status\nrule: immutable via UPDATE\n"
            "fix: Use --action delete to retire, or --action archive to archive"
        ), []

    # Tags: grow-only with eviction at cap
    old_tags = set(old.get("tags", []))
    new_tags = set(new.get("tags", []))
    removed_tags = old_tags - new_tags
    added_tags = new_tags - old_tags

    if removed_tags:
        if len(old_tags) < TAG_CAP:
            # Below cap: no removals allowed
            return False, (
                f"MERGE_ERROR\nfield: tags\nrule: grow-only (below cap of {TAG_CAP})\n"
                f"removed: {json.dumps(sorted(removed_tags))}\n"
                f"fix: Tags can only be added, not removed "
                f"(current count {len(old_tags)} < cap {TAG_CAP})"
            ), []
        else:
            # At cap: eviction allowed only if adding new tags
            if not added_tags:
                return False, (
                    f"MERGE_ERROR\nfield: tags\nrule: no net shrink without addition\n"
                    f"removed: {json.dumps(sorted(removed_tags))}\n"
                    f"fix: Can only evict tags when adding new ones at cap ({TAG_CAP})"
                ), []
            if len(new_tags) > TAG_CAP:
                return False, (
                    f"MERGE_ERROR\nfield: tags\nrule: cap exceeded\n"
                    f"count: {len(new_tags)}\n"
                    f"fix: Keep tags at or below {TAG_CAP}"
                ), []
            # Log eviction
            auto_changes.append({
                "date": now_utc(),
                "summary": (
                    f"Tags evicted at cap: removed {sorted(removed_tags)}, "
                    f"added {sorted(added_tags)}"
                ),
                "field": "tags",
                "old_value": sorted(removed_tags),
                "new_value": sorted(added_tags),
            })

    # related_files: grow-only, but allow removal of non-existent paths
    old_files = set(old.get("related_files") or [])
    new_files = set(new.get("related_files") or [])
    removed_files = old_files - new_files
    for rf in removed_files:
        if os.path.exists(rf):
            return False, (
                f"MERGE_ERROR\nfield: related_files\n"
                f"rule: grow-only (cannot remove existing file reference)\n"
                f"removed: {rf}\n"
                f"fix: Only non-existent (dangling) file references can be removed"
            ), []

    # changes[]: append-only
    old_changes = old.get("changes") or []
    new_changes = new.get("changes") or []
    if len(new_changes) < len(old_changes):
        return False, (
            f"MERGE_ERROR\nfield: changes\nrule: append-only\n"
            f"old_count: {len(old_changes)}\nnew_count: {len(new_changes)}\n"
            f"fix: changes[] must grow; do not remove entries"
        ), []

    # Auto-generate change entries for scalar content field changes
    old_content = old.get("content", {})
    new_content = new.get("content", {})
    for key in set(list(old_content.keys()) + list(new_content.keys())):
        old_val = old_content.get(key)
        new_val = new_content.get(key)
        if old_val != new_val and isinstance(old_val, (str, int, float, bool, type(None))):
            auto_changes.append({
                "date": now_utc(),
                "summary": f"content.{key} changed",
                "field": f"content.{key}",
                "old_value": old_val,
                "new_value": new_val,
            })

    # Warn if content list fields shrink (but allow it)
    for key in new_content:
        old_val = old_content.get(key)
        new_val = new_content.get(key)
        if (isinstance(old_val, list) and isinstance(new_val, list)
                and len(new_val) < len(old_val)):
            print(
                f"[WARN] content.{key}: list shrank from "
                f"{len(old_val)} to {len(new_val)} items",
                file=sys.stderr,
            )

    return True, None, auto_changes


def word_difference_ratio(old_title: str, new_title: str) -> float:
    """Calculate word difference ratio between two titles."""
    old_words = set(old_title.lower().split())
    new_words = set(new_title.lower().split())
    if not old_words and not new_words:
        return 0.0
    union = old_words | new_words
    if not union:
        return 0.0
    diff = old_words.symmetric_difference(new_words)
    return len(diff) / len(union)


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def do_create(args, memory_root: Path, index_path: Path) -> int:
    """Handle --action create."""
    # Read input
    data = _read_input(args.input)
    if data is None:
        return 1

    # Auto-fix
    data = auto_fix(data, "create")

    # Force active status for new memories (prevent record_status injection)
    data["record_status"] = "active"
    data.pop("retired_at", None)
    data.pop("retired_reason", None)
    data.pop("archived_at", None)
    data.pop("archived_reason", None)

    # Validate category matches
    if data.get("category") != args.category:
        data["category"] = args.category
        print(f"[AUTO-FIX] category: set to '{args.category}'", file=sys.stderr)

    # Validate
    ok, err = validate_memory(data, args.category)
    if not ok:
        print(err)
        return 1

    target = Path(args.target)
    target_abs = Path.cwd() / target if not target.is_absolute() else target

    # Path traversal check
    if _check_path_containment(target_abs, memory_root, "CREATE"):
        return 1

    # Ensure id matches filename
    expected_id = target_abs.stem
    if data.get("id") != expected_id:
        data["id"] = expected_id
        print(
            f"[AUTO-FIX] id: set to match filename '{expected_id}'",
            file=sys.stderr,
        )

    # Re-validate after auto-fixes that changed id
    ok, err = validate_memory(data, args.category)
    if not ok:
        print(err)
        return 1

    # Ensure target directory exists
    target_abs.parent.mkdir(parents=True, exist_ok=True)

    # Compute relative path for index
    rel_path = str(target)

    # OCC: flock on index -- anti-resurrection check inside lock
    with _flock_index(index_path):
        # Anti-resurrection check (inside flock to prevent TOCTOU)
        if target_abs.exists():
            try:
                with open(target_abs, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if (existing.get("record_status") == "retired"
                        and existing.get("retired_at")):
                    retired_at = datetime.fromisoformat(
                        existing["retired_at"].replace("Z", "+00:00")
                    )
                    age = (datetime.now(timezone.utc) - retired_at).total_seconds()
                    if age < 86400:  # 24 hours
                        print(
                            f"ANTI_RESURRECTION_ERROR\n"
                            f"target: {args.target}\n"
                            f"retired_at: {existing['retired_at']}\n"
                            f"fix: This file was retired less than 24 hours ago. "
                            f"Wait or use a different target path."
                        )
                        return 1
            except (json.JSONDecodeError, KeyError, ValueError):
                pass

        atomic_write_json(str(target_abs), data)
        index_line = build_index_line(data, rel_path)
        add_to_index(index_path, index_line)

    # Cleanup temp file
    _cleanup_input(args.input)

    # Success output
    result = {
        "status": "created",
        "target": str(target),
        "id": data["id"],
        "title": data["title"],
    }
    print(json.dumps(result))
    return 0


def do_update(args, memory_root: Path, index_path: Path) -> int:
    """Handle --action update."""
    target = Path(args.target)
    target_abs = Path.cwd() / target if not target.is_absolute() else target

    # Path traversal check
    if _check_path_containment(target_abs, memory_root, "UPDATE"):
        return 1

    if not target_abs.exists():
        print(
            f"UPDATE_ERROR\ntarget: {args.target}\n"
            f"fix: File does not exist. Use --action create instead."
        )
        return 1

    # Read existing
    try:
        with open(target_abs, "r", encoding="utf-8") as f:
            old_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"READ_ERROR\ntarget: {args.target}\nerror: {e}")
        return 1

    # Read new input
    new_data = _read_input(args.input)
    if new_data is None:
        return 1

    # Auto-fix
    new_data = auto_fix(new_data, "update")

    # Preserve immutable fields from old (id preserved here; rename path sets it later)
    for field in ("created_at", "schema_version", "category", "id"):
        if old_data.get(field) is not None:
            new_data[field] = old_data[field]

    # Preserve record_status
    new_data["record_status"] = old_data.get("record_status", "active")

    # Validate
    category = old_data.get("category", args.category)
    ok, err = validate_memory(new_data, category)
    if not ok:
        print(err)
        return 1

    # Check merge protections (id checked separately for rename)
    ok, err, auto_changes = check_merge_protections(old_data, new_data)
    if not ok:
        print(err)
        return 1

    # Merge auto-generated changes into new_data.changes
    old_changes_count = len(old_data.get("changes") or [])
    existing_changes = list(new_data.get("changes") or [])
    existing_changes.extend(auto_changes)

    # Strict check: total changes (including auto) must exceed old count
    if len(existing_changes) <= old_changes_count:
        print(
            f"MERGE_ERROR\nfield: changes\nrule: append-only (new entry required)\n"
            f"old_count: {old_changes_count}\ntotal_count: {len(existing_changes)}\n"
            f"fix: At least one new change entry is required per UPDATE"
        )
        return 1

    # FIFO overflow at 50
    if len(existing_changes) > CHANGES_CAP:
        existing_changes = existing_changes[-CHANGES_CAP:]

    new_data["changes"] = existing_changes

    # Increment times_updated
    new_data["times_updated"] = (old_data.get("times_updated", 0) or 0) + 1

    # Update timestamp
    new_data["updated_at"] = now_utc()

    # Check for slug rename (title changed >50%)
    old_title = old_data.get("title", "")
    new_title = new_data.get("title", "")
    rename_needed = False
    new_target_abs = target_abs
    new_rel_path = str(target)

    if (old_title and new_title
            and word_difference_ratio(old_title, new_title) > 0.5):
        new_slug = slugify(new_title)
        if new_slug and new_slug != target_abs.stem:
            new_file = target_abs.parent / f"{new_slug}.json"
            if new_file.exists():
                print(
                    f"[WARN] Slug rename collision: {new_file} exists. "
                    f"Keeping old slug.",
                    file=sys.stderr,
                )
            else:
                rename_needed = True
                new_target_abs = new_file
                # Recompute relative path
                parent_rel = str(target).rsplit("/", 1)[0]
                new_rel_path = f"{parent_rel}/{new_slug}.json"
                new_data["id"] = new_slug

    # Re-validate after all changes
    ok, err = validate_memory(new_data, category)
    if not ok:
        print(err)
        return 1

    rel_path = str(target)

    # OCC: flock on index for atomic transaction
    with _flock_index(index_path):
        # OCC hash check inside flock to prevent TOCTOU
        if args.hash:
            current_hash = file_md5(str(target_abs))
            if current_hash != args.hash:
                print(
                    f"OCC_CONFLICT\ntarget: {args.target}\n"
                    f"expected_hash: {args.hash}\n"
                    f"current_hash: {current_hash}\n"
                    f"fix: File was modified by another session. "
                    f"Re-read the file and retry."
                )
                return 1

        if rename_needed:
            # Rename flow: write new, update index, delete old
            atomic_write_json(str(new_target_abs), new_data)
            new_index_line = build_index_line(new_data, new_rel_path)
            remove_from_index(index_path, rel_path)
            add_to_index(index_path, new_index_line)
            try:
                os.unlink(str(target_abs))
            except OSError:
                pass
        else:
            atomic_write_json(str(target_abs), new_data)
            index_line = build_index_line(new_data, rel_path)
            update_index_entry(index_path, rel_path, index_line)

    # Cleanup temp file
    _cleanup_input(args.input)

    result = {
        "status": "updated",
        "target": new_rel_path if rename_needed else str(target),
        "id": new_data["id"],
        "title": new_data["title"],
        "times_updated": new_data["times_updated"],
    }
    if rename_needed:
        result["renamed_from"] = str(target)
    print(json.dumps(result))
    return 0


def do_delete(args, memory_root: Path, index_path: Path) -> int:
    """Handle --action delete (retire)."""
    target = Path(args.target)
    target_abs = Path.cwd() / target if not target.is_absolute() else target

    # Path traversal check
    if _check_path_containment(target_abs, memory_root, "DELETE"):
        return 1

    if not target_abs.exists():
        print(f"DELETE_ERROR\ntarget: {args.target}\nfix: File does not exist.")
        return 1

    # Read existing
    try:
        with open(target_abs, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"READ_ERROR\ntarget: {args.target}\nerror: {e}")
        return 1

    # Already retired? Idempotent success
    if data.get("record_status") == "retired":
        result = {"status": "already_retired", "target": str(target)}
        print(json.dumps(result))
        return 0

    # Block archived -> retired (must unarchive first)
    if data.get("record_status") == "archived":
        print(
            f"DELETE_ERROR\ntarget: {args.target}\n"
            f"fix: Archived memories must be unarchived before retiring. "
            f"Use --action unarchive first."
        )
        return 1

    # Set retirement fields
    old_record_status = data.get("record_status", "active")
    data["record_status"] = "retired"
    data["retired_at"] = now_utc()
    data["retired_reason"] = args.reason or "No reason provided"
    data["updated_at"] = now_utc()
    # Clear archived fields (spec: retired records must not have archived fields)
    data.pop("archived_at", None)
    data.pop("archived_reason", None)

    # Add change entry
    changes = data.get("changes") or []
    changes.append({
        "date": now_utc(),
        "summary": f"Retired: {data['retired_reason']}",
        "field": "record_status",
        "old_value": old_record_status,
        "new_value": "retired",
    })
    if len(changes) > CHANGES_CAP:
        changes = changes[-CHANGES_CAP:]
    data["changes"] = changes

    rel_path = str(target)

    # OCC: flock on index
    with _flock_index(index_path):
        atomic_write_json(str(target_abs), data)
        remove_from_index(index_path, rel_path)

    result = {
        "status": "retired",
        "target": str(target),
        "reason": data["retired_reason"],
    }
    print(json.dumps(result))
    return 0


def do_archive(args, memory_root: Path, index_path: Path) -> int:
    """Handle --action archive."""
    target = Path(args.target)
    target_abs = Path.cwd() / target if not target.is_absolute() else target

    # Path traversal check
    if _check_path_containment(target_abs, memory_root, "ARCHIVE"):
        return 1

    if not target_abs.exists():
        print(f"ARCHIVE_ERROR\ntarget: {args.target}\nfix: File does not exist.")
        return 1

    # Read existing
    try:
        with open(target_abs, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"READ_ERROR\ntarget: {args.target}\nerror: {e}")
        return 1

    # Already archived? Idempotent success
    if data.get("record_status") == "archived":
        result = {"status": "already_archived", "target": str(target)}
        print(json.dumps(result))
        return 0

    # Only active memories can be archived
    if data.get("record_status", "active") != "active":
        print(
            f"ARCHIVE_ERROR\ntarget: {args.target}\n"
            f"record_status: {data.get('record_status')}\n"
            f"fix: Only active memories can be archived."
        )
        return 1

    # Set archive fields
    data["record_status"] = "archived"
    data["archived_at"] = now_utc()
    data["archived_reason"] = args.reason or "No reason provided"
    data["updated_at"] = now_utc()
    # Clear retired fields if present
    data.pop("retired_at", None)
    data.pop("retired_reason", None)

    # Add change entry
    changes = data.get("changes") or []
    changes.append({
        "date": now_utc(),
        "summary": f"Archived: {data['archived_reason']}",
        "field": "record_status",
        "old_value": "active",
        "new_value": "archived",
    })
    if len(changes) > CHANGES_CAP:
        changes = changes[-CHANGES_CAP:]
    data["changes"] = changes

    rel_path = str(target)

    # flock on index
    with _flock_index(index_path):
        atomic_write_json(str(target_abs), data)
        remove_from_index(index_path, rel_path)

    result = {
        "status": "archived",
        "target": str(target),
        "reason": data["archived_reason"],
    }
    print(json.dumps(result))
    return 0


def do_unarchive(args, memory_root: Path, index_path: Path) -> int:
    """Handle --action unarchive."""
    target = Path(args.target)
    target_abs = Path.cwd() / target if not target.is_absolute() else target

    # Path traversal check
    if _check_path_containment(target_abs, memory_root, "UNARCHIVE"):
        return 1

    if not target_abs.exists():
        print(f"UNARCHIVE_ERROR\ntarget: {args.target}\nfix: File does not exist.")
        return 1

    # Read existing
    try:
        with open(target_abs, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"READ_ERROR\ntarget: {args.target}\nerror: {e}")
        return 1

    # Only archived memories can be unarchived
    if data.get("record_status") != "archived":
        print(
            f"UNARCHIVE_ERROR\ntarget: {args.target}\n"
            f"record_status: {data.get('record_status', 'active')}\n"
            f"fix: Only archived memories can be unarchived."
        )
        return 1

    # Set active status
    data["record_status"] = "active"
    data["updated_at"] = now_utc()
    # Clear archived fields
    data.pop("archived_at", None)
    data.pop("archived_reason", None)

    # Add change entry
    changes = data.get("changes") or []
    changes.append({
        "date": now_utc(),
        "summary": "Unarchived: restored to active",
        "field": "record_status",
        "old_value": "archived",
        "new_value": "active",
    })
    if len(changes) > CHANGES_CAP:
        changes = changes[-CHANGES_CAP:]
    data["changes"] = changes

    rel_path = str(target)

    # flock on index
    with _flock_index(index_path):
        atomic_write_json(str(target_abs), data)
        index_line = build_index_line(data, rel_path)
        add_to_index(index_path, index_line)

    result = {
        "status": "unarchived",
        "target": str(target),
    }
    print(json.dumps(result))
    return 0


def do_restore(args, memory_root: Path, index_path: Path) -> int:
    """Handle --action restore (retired -> active)."""
    target = Path(args.target)
    target_abs = Path.cwd() / target if not target.is_absolute() else target

    # Path traversal check
    if _check_path_containment(target_abs, memory_root, "RESTORE"):
        return 1

    if not target_abs.exists():
        print(f"RESTORE_ERROR\ntarget: {args.target}\nfix: File does not exist.")
        return 1

    # Read existing
    try:
        with open(target_abs, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"READ_ERROR\ntarget: {args.target}\nerror: {e}")
        return 1

    # Already active? Idempotent success
    if data.get("record_status", "active") == "active":
        result = {"status": "already_active", "target": str(target)}
        print(json.dumps(result))
        return 0

    # Only retired memories can be restored
    if data.get("record_status") != "retired":
        print(
            f"RESTORE_ERROR\ntarget: {args.target}\n"
            f"record_status: {data.get('record_status', 'active')}\n"
            f"fix: Only retired memories can be restored. "
            f"Use --action unarchive for archived memories."
        )
        return 1

    # Set active status
    data["record_status"] = "active"
    data["updated_at"] = now_utc()
    # Clear retirement fields
    data.pop("retired_at", None)
    data.pop("retired_reason", None)

    # Add change entry
    changes = data.get("changes") or []
    changes.append({
        "date": now_utc(),
        "summary": "Restored: returned to active from retired",
        "field": "record_status",
        "old_value": "retired",
        "new_value": "active",
    })
    if len(changes) > CHANGES_CAP:
        changes = changes[-CHANGES_CAP:]
    data["changes"] = changes

    rel_path = str(target)

    # flock on index
    with _flock_index(index_path):
        atomic_write_json(str(target_abs), data)
        index_line = build_index_line(data, rel_path)
        add_to_index(index_path, index_line)

    result = {
        "status": "restored",
        "target": str(target),
    }
    print(json.dumps(result))
    return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_input(input_path: str) -> Optional[dict]:
    """Read JSON from input temp file.

    Validates that the input path is within /tmp/ and contains no path
    traversal components (defense-in-depth against subagent manipulation).
    """
    # Defense-in-depth: input files must be in /tmp/ with no traversal
    resolved = os.path.realpath(input_path)
    if not resolved.startswith("/tmp/") or ".." in input_path:
        print(
            f"SECURITY_ERROR\npath: {input_path}\n"
            f"resolved: {resolved}\n"
            f"fix: Input file must be a /tmp/ path with no '..' components."
        )
        return None
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(
            f"INPUT_ERROR\npath: {input_path}\n"
            f"fix: Input file does not exist. Write JSON to the temp file first."
        )
        return None
    except json.JSONDecodeError as e:
        print(
            f"INPUT_ERROR\npath: {input_path}\n"
            f"error: Invalid JSON: {e}\n"
            f"fix: Ensure the input file contains valid JSON."
        )
        return None


def _cleanup_input(input_path: str) -> None:
    """Delete the temp input file."""
    try:
        os.unlink(input_path)
    except OSError:
        pass


def _check_path_containment(target_abs: Path, memory_root: Path, action_label: str) -> int:
    """Verify target_abs is within memory_root. Returns 0 if ok, 1 if not."""
    try:
        target_abs.resolve().relative_to(memory_root.resolve())
        return 0
    except ValueError:
        print(
            f"PATH_ERROR\ntarget: {target_abs}\n"
            f"fix: Target must be within the memory directory ({memory_root})"
        )
        return 1


class _flock_index:
    """Portable lock for index mutations. Uses mkdir (atomic on all FS including NFS)."""

    _LOCK_TIMEOUT = 5.0    # Max seconds to wait for lock
    _STALE_AGE = 60.0      # Seconds before a lock is considered stale
    _POLL_INTERVAL = 0.05   # Seconds between retry attempts

    def __init__(self, index_path: Path):
        self.lock_dir = index_path.parent / ".index.lockdir"
        self.acquired = False

    def __enter__(self):
        deadline = time.monotonic() + self._LOCK_TIMEOUT
        while True:
            try:
                os.mkdir(self.lock_dir)
                self.acquired = True
                return self
            except FileExistsError:
                # Lock held by another process -- check for stale
                try:
                    mtime = self.lock_dir.stat().st_mtime
                    if (time.time() - mtime) > self._STALE_AGE:
                        # Stale lock -- break it with warning
                        try:
                            os.rmdir(self.lock_dir)
                        except OSError:
                            pass
                        print(
                            "[WARN] Broke stale index lock (older than 60s)",
                            file=sys.stderr,
                        )
                        continue
                except OSError:
                    pass  # Lock dir disappeared between check and stat -- retry

                if time.monotonic() >= deadline:
                    print(
                        "[WARN] Index lock timeout; proceeding without lock",
                        file=sys.stderr,
                    )
                    return self
                time.sleep(self._POLL_INTERVAL)
            except OSError:
                # mkdir failed for non-existence reason (permissions, etc.)
                # Proceed without lock rather than failing the write
                print(
                    "[WARN] Could not create lock directory; proceeding without lock",
                    file=sys.stderr,
                )
                return self

    def __exit__(self, *args):
        if self.acquired:
            try:
                os.rmdir(self.lock_dir)
            except OSError:
                pass


def _resolve_memory_root(target: str) -> tuple[Path, Path]:
    """Derive memory_root and index_path from the target path.

    Requires .claude/memory marker in the path. Fails closed if missing.
    """
    target_path = Path(target)
    # Resolve to absolute for consistent part scanning
    target_abs = (
        Path.cwd() / target_path
        if not target_path.is_absolute()
        else target_path
    )
    parts = target_abs.parts
    _dc = ".clau" + "de"
    for i, part in enumerate(parts):
        if part == "memory" and i > 0 and parts[i - 1] == _dc:
            memory_root = Path(*parts[: i + 1])
            break
    else:
        print(
            f"PATH_ERROR\ntarget: {target}\n"
            f"fix: Target path must contain '.claude/memory/' components. "
            f"Example: .claude/memory/decisions/my-decision.json"
        )
        sys.exit(1)

    memory_root_abs = (
        Path.cwd() / memory_root
        if not memory_root.is_absolute()
        else memory_root
    )
    index_path = memory_root_abs / "index.md"
    return memory_root_abs, index_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Schema-enforced memory write tool."
    )
    parser.add_argument(
        "--action", required=True,
        choices=["create", "update", "delete", "archive", "unarchive", "restore"],
    )
    parser.add_argument("--category", choices=list(CATEGORY_FOLDERS.keys()))
    parser.add_argument(
        "--target", required=True, help="Relative path to memory file"
    )
    parser.add_argument("--input", help="Path to temp JSON input file")
    parser.add_argument(
        "--hash",
        help="MD5 hash of existing file for OCC (update only)",
    )
    parser.add_argument("--reason", help="Reason for deletion or archival (delete/archive)")

    args = parser.parse_args()

    # Validate required args per action
    if args.action in ("create", "update") and not args.input:
        print("ERROR: --input is required for create and update actions.")
        return 1

    if args.action == "create" and not args.category:
        print("ERROR: --category is required for create action.")
        return 1

    if args.action == "update" and not args.hash:
        print("WARNING: --hash not provided for update. OCC protection disabled.", file=sys.stderr)

    # Resolve memory root and index path
    memory_root, index_path = _resolve_memory_root(args.target)

    if args.action == "create":
        return do_create(args, memory_root, index_path)
    elif args.action == "update":
        return do_update(args, memory_root, index_path)
    elif args.action == "delete":
        return do_delete(args, memory_root, index_path)
    elif args.action == "archive":
        return do_archive(args, memory_root, index_path)
    elif args.action == "unarchive":
        return do_unarchive(args, memory_root, index_path)
    elif args.action == "restore":
        return do_restore(args, memory_root, index_path)

    return 1


if __name__ == "__main__":
    sys.exit(main())
