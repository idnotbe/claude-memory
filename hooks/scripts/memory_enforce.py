#!/usr/bin/env python3
"""Rolling window enforcement for claude-memory.

Scans a category folder for active memories and retires the oldest
when the count exceeds the configured max_retained limit.

Usage:
    python3 memory_enforce.py --category session_summary [--max-retained 5] [--dry-run]
"""

import os
import sys

# ── venv bootstrap (MUST come before any memory_write imports) ──────────
_venv_python = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '.venv', 'bin', 'python3'
)
if os.path.isfile(_venv_python) and os.path.realpath(sys.executable) != os.path.realpath(_venv_python):
    try:
        import pydantic  # noqa: F401
    except ImportError:
        os.execv(_venv_python, [_venv_python] + sys.argv)

# ── sys.path setup (required for memory_write import) ──────────────────
_script_dir = os.path.dirname(os.path.abspath(__file__))
if _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)

# ── imports ─────────────────────────────────────────────────────────────
import argparse
import json
from pathlib import Path

from memory_write import (  # noqa: E402
    retire_record,
    FlockIndex,
    CATEGORY_FOLDERS,
)

# ── constants ───────────────────────────────────────────────────────────
MAX_RETIRE_ITERATIONS = 10  # Safety valve: never retire more than this in one run
DEFAULT_MAX_RETAINED = 5


# ---------------------------------------------------------------------------
# Root derivation
# ---------------------------------------------------------------------------

def _resolve_memory_root() -> Path:
    """Find .claude/memory/ directory.

    Strategy:
    1. $CLAUDE_PROJECT_ROOT environment variable (set by Claude Code)
    2. Walk CWD upward looking for .claude/memory/
    3. Hard error if not found
    """
    project_root_env = os.environ.get("CLAUDE_PROJECT_ROOT")
    if project_root_env:
        candidate = Path(project_root_env) / ".claude" / "memory"
        if candidate.is_dir():
            return candidate

    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        candidate = parent / ".claude" / "memory"
        if candidate.is_dir():
            return candidate

    print("ERROR: Cannot find .claude/memory/ directory.", file=sys.stderr)
    print("Ensure CLAUDE_PROJECT_ROOT is set or run from within the project.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Config reading
# ---------------------------------------------------------------------------

def _read_max_retained(memory_root: Path, category: str, cli_override: int | None) -> int:
    """Read max_retained from memory-config.json, with CLI override."""
    if cli_override is not None:
        return cli_override

    config_path = memory_root / "memory-config.json"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
            value = config.get("categories", {}).get(category, {}).get("max_retained", DEFAULT_MAX_RETAINED)
            # Reject booleans explicitly (bool is subtype of int in Python)
            if isinstance(value, bool) or not isinstance(value, int):
                print(
                    f"[WARN] max_retained must be an integer, got {type(value).__name__}: {value}. "
                    f"Using default {DEFAULT_MAX_RETAINED}.",
                    file=sys.stderr,
                )
                return DEFAULT_MAX_RETAINED
            return value
        except (json.JSONDecodeError, OSError):
            pass

    return DEFAULT_MAX_RETAINED


# ---------------------------------------------------------------------------
# Active session scanning
# ---------------------------------------------------------------------------

def _scan_active(category_dir: Path) -> list[dict]:
    """Scan category folder for active memory files.

    Returns list of dicts sorted by created_at (oldest first):
        [{"path": Path, "data": dict, "id": str, "created_at": str}, ...]
    """
    results = []
    if not category_dir.is_dir():
        return results

    for f in sorted(category_dir.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as e:
            print(f"[WARN] Skipping corrupted file {f.name}: {e}", file=sys.stderr)
            continue

        status = data.get("record_status", "active")  # absent = active (pre-v4 compat)
        if status == "active":
            results.append({
                "path": f,
                "data": data,
                "id": data.get("id", f.stem),
                "created_at": data.get("created_at", ""),
            })

    # Sort oldest first; filename as tiebreaker for identical timestamps
    results.sort(key=lambda s: (s["created_at"], s["path"].name))
    return results


# ---------------------------------------------------------------------------
# Deletion guard
# ---------------------------------------------------------------------------

def _deletion_guard(session_data: dict, session_id: str) -> None:
    """Warn if session contains unique content not captured elsewhere.

    Advisory only -- does not block retirement.
    """
    content = session_data.get("content", {})
    unique_items = []

    for field in ("completed", "blockers", "next_actions"):
        items = content.get(field, [])
        if items:
            unique_items.extend(items[:3])  # Sample first 3 items

    if unique_items:
        sample = "; ".join(str(item) for item in unique_items[:5])
        print(
            f"[WARN] Session {session_id} contains content that may not be captured "
            f"elsewhere: {sample}. Content preserved during 30-day grace period.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Main enforcement logic
# ---------------------------------------------------------------------------

def enforce_rolling_window(
    memory_root: Path,
    category: str,
    max_retained: int,
    dry_run: bool = False,
) -> dict:
    """Enforce rolling window for a category.

    Args:
        memory_root: Path to .claude/memory/ directory
        category: Category name (e.g., "session_summary")
        max_retained: Maximum active memories to keep
        dry_run: If True, print what would be retired without acting

    Returns summary dict:
        {"retired": [str, ...], "active_count": int, "max_retained": int}
    """
    index_path = memory_root / "index.md"

    folder_name = CATEGORY_FOLDERS.get(category)
    if not folder_name:
        print(f"ERROR: Unknown category '{category}'", file=sys.stderr)
        sys.exit(1)

    category_dir = memory_root / folder_name

    if not category_dir.is_dir():
        return {"retired": [], "active_count": 0, "max_retained": max_retained}

    retired_list = []

    if dry_run:
        # Dry-run: compute excess once, list what WOULD be retired (no lock needed)
        active = _scan_active(category_dir)
        excess = len(active) - max_retained
        if excess <= 0:
            return {"retired": [], "active_count": len(active), "max_retained": max_retained}

        excess = min(excess, MAX_RETIRE_ITERATIONS)
        for victim in active[:excess]:
            _deletion_guard(victim["data"], victim["id"])
            print(
                f"[ROLLING_WINDOW] Would retire: {victim['id']} "
                f"(created: {victim['created_at']})",
                file=sys.stderr,
            )
            retired_list.append(victim["id"])

        return {
            "retired": retired_list,
            "active_count": len(active) - len(retired_list),
            "max_retained": max_retained,
            "dry_run": True,
        }

    # Real enforcement: acquire lock for the entire scan-retire cycle
    with FlockIndex(index_path) as lock:
        lock.require_acquired()  # STRICT: raises TimeoutError if lock not held

        active = _scan_active(category_dir)
        excess = len(active) - max_retained

        if excess <= 0:
            return {"retired": [], "active_count": len(active), "max_retained": max_retained}

        excess = min(excess, MAX_RETIRE_ITERATIONS)

        for victim in active[:excess]:
            _deletion_guard(victim["data"], victim["id"])

            try:
                result = retire_record(
                    target_abs=victim["path"],
                    reason="Session rolling window: exceeded max_retained limit",
                    memory_root=memory_root,
                    index_path=index_path,
                )
                retired_list.append(victim["id"])
                remaining = len(active) - len(retired_list)
                print(
                    f"[ROLLING_WINDOW] Retired {victim['id']} "
                    f"(active: {remaining}/{max_retained})",
                    file=sys.stderr,
                )
            except FileNotFoundError as e:
                # File disappeared between scan and retire (rare, non-fatal)
                print(
                    f"[WARN] File gone before retire {victim['id']}: {e}. Continuing.",
                    file=sys.stderr,
                )
                continue
            except Exception as e:
                # Structural error -- stop the loop
                print(
                    f"[WARN] Failed to retire {victim['id']}: {e}. Stopping enforcement loop.",
                    file=sys.stderr,
                )
                break

    return {
        "retired": retired_list,
        "active_count": len(active) - len(retired_list),
        "max_retained": max_retained,
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Enforce rolling window retention for claude-memory categories."
    )
    parser.add_argument(
        "--category",
        required=True,
        choices=list(CATEGORY_FOLDERS.keys()),
        help="Category to enforce rolling window on",
    )
    parser.add_argument(
        "--max-retained",
        type=int,
        default=None,
        help=f"Override max_retained (default: from config or {DEFAULT_MAX_RETAINED})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be retired without actually retiring",
    )
    args = parser.parse_args()

    # Validate --max-retained
    if args.max_retained is not None and args.max_retained < 1:
        print("ERROR: --max-retained must be >= 1", file=sys.stderr)
        sys.exit(1)

    memory_root = _resolve_memory_root()
    max_retained = _read_max_retained(memory_root, args.category, args.max_retained)

    try:
        result = enforce_rolling_window(memory_root, args.category, max_retained, args.dry_run)
    except TimeoutError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result))


if __name__ == "__main__":
    main()
