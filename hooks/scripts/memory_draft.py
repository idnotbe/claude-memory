#!/usr/bin/env python3
"""Draft assembler for claude-memory plugin.

Assembles complete, schema-compliant memory JSON from a partial input file
written by an LLM subagent. This separates ASSEMBLY (this script) from
ENFORCEMENT (memory_write.py).

Usage:
  python3 memory_draft.py --action create --category decision \
    --input-file .claude/memory/.staging/input-decision-12345.json

  python3 memory_draft.py --action update --category decision \
    --input-file .claude/memory/.staging/input-decision-12345.json \
    --candidate-file .claude/memory/decisions/use-jwt.json

Output (stdout): JSON with status, action, draft_path
"""

import sys
import os

# Bootstrap: re-exec under the plugin venv if pydantic is not importable.
_venv_python = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '.venv', 'bin', 'python3'
)
if os.path.isfile(_venv_python) and os.path.realpath(sys.executable) != os.path.realpath(_venv_python):
    try:
        import pydantic  # noqa: F401 -- quick availability check
    except ImportError:
        os.execv(_venv_python, [_venv_python] + sys.argv)

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

# Import shared utilities from sibling memory_write.py.
# The venv bootstrap above ensures pydantic is available, so importing
# memory_write won't trigger its own os.execv (it only fires when
# pydantic is missing).
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

from memory_write import (  # noqa: E402
    slugify,
    now_utc,
    build_memory_model,
    CATEGORY_FOLDERS,
    ChangeEntry,
    ValidationError,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_CATEGORIES = list(CATEGORY_FOLDERS.keys())
REQUIRED_INPUT_FIELDS = ("title", "tags", "content", "change_summary")


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_input_path(path: str) -> str | None:
    """Validate input file path is in an allowed directory.

    Allowed: .claude/memory/.staging/ or /tmp/
    The /tmp/ allowance is broader than memory_write.py (which only allows
    .staging/) -- this is intentional per spec since memory_draft.py reads
    partial input written by the LLM via the Write tool, which may use /tmp/.
    """
    resolved = os.path.realpath(path)

    if ".." in path:
        return f"Input path must not contain '..' components: {path}"

    in_staging = "/.claude/memory/.staging/" in resolved
    in_tmp = resolved.startswith("/tmp/")

    if not in_staging and not in_tmp:
        return (
            f"Input file must be in .claude/memory/.staging/ or /tmp/. "
            f"Got: {path} (resolved: {resolved})"
        )
    return None


def validate_candidate_path(path: str) -> str | None:
    """Validate candidate file exists, is a JSON file, and is within memory root.

    Defense-in-depth: upstream memory_candidate.py already does containment
    checking, but we verify here too in case memory_draft.py is called directly.
    """
    if ".." in path:
        return f"Candidate path must not contain '..' components: {path}"
    if not os.path.isfile(path):
        return f"Candidate file does not exist: {path}"
    if not path.endswith(".json"):
        return f"Candidate file must be a .json file: {path}"
    resolved = os.path.realpath(path)
    if "/.claude/memory/" not in resolved:
        return (
            f"Candidate file must be within .claude/memory/. "
            f"Got: {path} (resolved: {resolved})"
        )
    return None


def read_json_file(path: str, label: str) -> dict | None:
    """Read and parse a JSON file. Returns None on error (prints to stderr)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"ERROR: {label} file contains invalid JSON: {e}", file=sys.stderr)
        return None


def check_required_fields(data: dict) -> str | None:
    """Check that the input has all required fields. Returns error or None."""
    missing = [f for f in REQUIRED_INPUT_FIELDS if f not in data]
    if missing:
        return f"Missing required fields in input: {', '.join(missing)}"
    return None


# ---------------------------------------------------------------------------
# Assembly: CREATE
# ---------------------------------------------------------------------------

def assemble_create(input_data: dict, category: str) -> dict:
    """Assemble a complete memory JSON for a CREATE action."""
    ts = now_utc()
    title = str(input_data.get("title", ""))
    mem_id = slugify(title)

    return {
        "schema_version": "1.0",
        "category": category,
        "id": mem_id,
        "title": title,
        "record_status": "active",
        "created_at": ts,
        "updated_at": ts,
        "tags": input_data.get("tags", []),
        "related_files": input_data.get("related_files"),
        "confidence": input_data.get("confidence"),
        "content": input_data.get("content", {}),
        "changes": [
            {
                "date": ts,
                "summary": str(input_data.get("change_summary", "Initial creation")),
            }
        ],
        "times_updated": 0,
    }


# ---------------------------------------------------------------------------
# Assembly: UPDATE
# ---------------------------------------------------------------------------

def assemble_update(input_data: dict, existing: dict, category: str) -> dict:
    """Assemble a complete memory JSON for an UPDATE action.

    Preserves immutable fields from existing, unions tags and related_files,
    appends change entry, increments times_updated, shallow-merges content
    (top-level content keys from input overlay existing content keys).
    """
    ts = now_utc()

    # Start from existing, overlay mutable fields
    result = dict(existing)

    # Preserve immutable fields from existing
    # (created_at, schema_version, category, id are never changed)

    # Update mutable metadata
    result["updated_at"] = ts
    result["record_status"] = existing.get("record_status", "active")

    # Title: use new if provided, else keep existing
    if input_data.get("title"):
        result["title"] = str(input_data["title"])

    # Tags: union of existing + new, deduplicated
    old_tags = set(existing.get("tags") or [])
    new_tags = set(input_data.get("tags") or [])
    result["tags"] = sorted(old_tags | new_tags)

    # Related files: union of existing + new, deduplicated
    old_files = set(existing.get("related_files") or [])
    new_files = set(input_data.get("related_files") or [])
    merged_files = sorted(old_files | new_files)
    result["related_files"] = merged_files if merged_files else None

    # Confidence: use new if provided
    if input_data.get("confidence") is not None:
        result["confidence"] = input_data["confidence"]

    # Content: shallow merge -- existing content with new content overlaid
    old_content = dict(existing.get("content") or {})
    new_content = dict(input_data.get("content") or {})
    old_content.update(new_content)
    result["content"] = old_content

    # Changes: append new entry
    changes = list(existing.get("changes") or [])
    changes.append({
        "date": ts,
        "summary": str(input_data.get("change_summary", "Updated")),
    })
    result["changes"] = changes

    # Increment times_updated
    result["times_updated"] = (existing.get("times_updated", 0) or 0) + 1

    return result


# ---------------------------------------------------------------------------
# Draft output
# ---------------------------------------------------------------------------

def write_draft(data: dict, category: str, root: str) -> str:
    """Write the assembled draft to .staging/ and return the path."""
    staging_dir = os.path.join(root, ".staging")
    os.makedirs(staging_dir, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pid = os.getpid()
    filename = f"draft-{category}-{ts}-{pid}.json"
    draft_path = os.path.join(staging_dir, filename)

    content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    with open(draft_path, "w", encoding="utf-8") as f:
        f.write(content)

    return draft_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble complete memory JSON from partial input."
    )
    parser.add_argument(
        "--action", required=True, choices=["create", "update"],
        help="Action: create a new memory or update an existing one."
    )
    parser.add_argument(
        "--category", required=True, choices=VALID_CATEGORIES,
        help="Memory category."
    )
    parser.add_argument(
        "--input-file", required=True,
        help="Path to partial JSON input file."
    )
    parser.add_argument(
        "--candidate-file",
        help="Path to existing memory file (required for update)."
    )
    parser.add_argument(
        "--root", default=".claude/memory",
        help="Memory root directory (default: .claude/memory)."
    )

    args = parser.parse_args()

    # Validate action-specific args
    if args.action == "update" and not args.candidate_file:
        print("ERROR: --candidate-file is required for update action.", file=sys.stderr)
        return 1

    # Validate input path security
    err = validate_input_path(args.input_file)
    if err:
        print(f"SECURITY_ERROR\n{err}", file=sys.stderr)
        return 1

    # Read input file
    input_data = read_json_file(args.input_file, "Input")
    if input_data is None:
        return 1

    # Check required fields
    err = check_required_fields(input_data)
    if err:
        print(f"INPUT_ERROR\n{err}", file=sys.stderr)
        return 1

    # Assemble the complete memory JSON
    if args.action == "create":
        assembled = assemble_create(input_data, args.category)
    else:
        # UPDATE: read existing memory
        err = validate_candidate_path(args.candidate_file)
        if err:
            print(f"INPUT_ERROR\n{err}", file=sys.stderr)
            return 1

        existing = read_json_file(args.candidate_file, "Candidate")
        if existing is None:
            return 1

        assembled = assemble_update(input_data, existing, args.category)

    # Validate assembled JSON against Pydantic schema
    Model = build_memory_model(args.category)
    try:
        Model.model_validate(assembled)
    except ValidationError as e:
        print("VALIDATION_ERROR", file=sys.stderr)
        for err_item in e.errors():
            loc = ".".join(str(part) for part in err_item["loc"])
            print(f"  field: {loc}", file=sys.stderr)
            print(f"  error: {err_item['msg']}", file=sys.stderr)
        return 1

    # Write draft to staging
    draft_path = write_draft(assembled, args.category, args.root)

    # Success output (stdout)
    result = {
        "status": "ok",
        "action": args.action,
        "draft_path": draft_path,
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
