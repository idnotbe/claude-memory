#!/usr/bin/env python3
"""Phase 1.5 orchestration: deterministic CUD resolution pipeline.

Replaces LLM-driven Phase 1.5 with a single script invocation.
Reads intent files, runs candidate selection, resolves CUD actions,
assembles drafts, and outputs a manifest.

Supports three action modes:
  - No --action flag (default): steps 1-6 only (backward compatible)
  - --action prepare: steps 1-6 + target path generation + manifest enrichment
  - --action commit: step 7 only from existing manifest
  - --action run: steps 1-7 (prepare + commit in one call)
"""

import sys
import os

# Bootstrap: re-exec under the plugin venv if pydantic is not importable.
# This is needed so slugify and CATEGORY_FOLDERS can be imported from
# memory_write.py in prepare/run modes.  The bootstrap is a no-op when
# pydantic is already available (including global installs).
_venv_python = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', '.venv', 'bin', 'python3'
)
if os.path.isfile(_venv_python) and os.path.realpath(sys.executable) != os.path.realpath(_venv_python):
    try:
        import pydantic  # noqa: F401 -- quick availability check
    except ImportError:
        os.execv(_venv_python, [_venv_python] + sys.argv)

import argparse
import fnmatch
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from memory_staging_utils import PinnedStagingDir
except ImportError:
    PinnedStagingDir = None


# CUD resolution table: (L1_structural_cud, L2_intended_action) -> resolved_action
# See SKILL.md "CUD Verification Rules" for rationale.
CUD_TABLE = {
    ("CREATE", "CREATE"): "CREATE",
    ("UPDATE_OR_DELETE", "UPDATE"): "UPDATE",
    ("UPDATE_OR_DELETE", "DELETE"): "DELETE",
    ("CREATE", "UPDATE"): "CREATE",
    ("CREATE", "DELETE"): "NOOP",
    ("UPDATE_OR_DELETE", "CREATE"): "CREATE",
    # UPDATE (no DELETE gate) + any -> UPDATE (structural only allows UPDATE)
    ("UPDATE", "CREATE"): "CREATE",
    ("UPDATE", "UPDATE"): "UPDATE",
    ("UPDATE", "DELETE"): "UPDATE",  # DELETE vetoed structurally
}

# ---------------------------------------------------------------------------
# Markdown fence stripping (H5 / D7)
# ---------------------------------------------------------------------------

_MARKDOWN_FENCE_RE = re.compile(
    r'^\s*```(?:json|JSON)?\s*\n?',  # leading fence
)
_MARKDOWN_FENCE_END_RE = re.compile(
    r'\n?\s*```\s*$',  # trailing fence
)


def _strip_markdown_fences(content: str) -> str:
    """Strip markdown code fences from JSON content.

    Handles: ```json\\n{...}\\n```, ```JSON\\n{...}\\n```,
             ```\\n{...}\\n```, and variations with whitespace.
    """
    content = _MARKDOWN_FENCE_RE.sub('', content)
    content = _MARKDOWN_FENCE_END_RE.sub('', content)
    return content.strip()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_write(path: str, content: str, pinned=None):
    """Write file atomically with O_NOFOLLOW to prevent symlink attacks.

    If *pinned* (a PinnedStagingDir) is provided, uses fd-pinned write_file
    to eliminate TOCTOU windows.  Otherwise falls back to the path-based
    os.open + os.replace pattern.
    """
    if pinned is not None:
        pinned.write_file(os.path.basename(path), content)
        return
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_manifest(staging_dir: str, manifest: dict, pinned=None):
    """Write orchestration manifest to staging directory."""
    path = os.path.join(staging_dir, "orchestration-result.json")
    _safe_write(path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", pinned=pinned)


# ---------------------------------------------------------------------------
# Target path generation (H2 / D8)
# ---------------------------------------------------------------------------

def generate_target_path(memory_root, category, title, category_folders, slugify_fn):
    """Generate target file path for a CREATE action.

    Args:
        memory_root: Path to memory root (e.g., ".claude/memory").
        category: Category name (e.g., "decision").
        title: Memory title to slugify.
        category_folders: CATEGORY_FOLDERS mapping (category -> folder name).
        slugify_fn: slugify() function from memory_write.

    Returns:
        Target path string (e.g., ".claude/memory/decisions/use-jwt.json").
    """
    folder = category_folders.get(category)
    if not folder:
        raise ValueError(f"Unknown category: {category}")
    slug = slugify_fn(title)
    if not slug:
        slug = f"untitled-{os.getpid()}"
    return os.path.join(memory_root, folder, f"{slug}.json")


# ---------------------------------------------------------------------------
# Step 1: Collect intents
# ---------------------------------------------------------------------------

def collect_intents(staging_dir: str, pinned=None) -> dict:
    """Step 1: Collect and validate intent JSONs from staging directory.

    Returns dict mapping category -> validated intent data.
    Skips noop intents and intents with missing required fields.
    Strips markdown code fences from intent file contents before parsing (H5).

    If *pinned* (a PinnedStagingDir) is provided, uses fd-pinned listdir
    and read_file to eliminate TOCTOU windows.
    """
    intents = {}

    if pinned is not None:
        names = sorted(
            n for n in pinned.listdir() if fnmatch.fnmatch(n, "intent-*.json")
        )
        for name in names:
            cat = name.replace("intent-", "").replace(".json", "")
            try:
                raw = pinned.read_file(name)
                content = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                content = _strip_markdown_fences(content)
                data = json.loads(content)
            except (json.JSONDecodeError, OSError):
                continue
            if _accept_intent(data, cat):
                intents[cat] = data
    else:
        for f in sorted(Path(staging_dir).glob("intent-*.json")):
            cat = f.stem.replace("intent-", "")
            try:
                content = f.read_text(encoding="utf-8")
                content = _strip_markdown_fences(content)
                data = json.loads(content)
            except (json.JSONDecodeError, OSError):
                continue
            if _accept_intent(data, cat):
                intents[cat] = data

    return intents


def _accept_intent(data: dict, cat: str) -> bool:
    """Validate an intent dict; return True if it should be accepted."""
    if data.get("action") == "noop":
        return False
    required = ["category", "new_info_summary", "partial_content"]
    if not all(data.get(k) for k in required):
        return False
    pc = data.get("partial_content", {})
    pc_required = ["title", "tags", "confidence", "change_summary", "content"]
    if not all(pc.get(k) is not None for k in pc_required):
        return False
    return True


# ---------------------------------------------------------------------------
# Step 2: Candidate selection + OCC hash capture (H4 / D6)
# ---------------------------------------------------------------------------

def run_candidate_selection(
    intents: dict,
    staging_dir: str,
    scripts_dir: str,
    python: str,
    memory_root: str | None = None,
    pinned=None,
) -> dict:
    """Step 2: Run memory_candidate.py for each intent + capture OCC hashes.

    Returns dict mapping category -> candidate result (or None on failure).
    For candidates with a file path, computes MD5 hash and stores as 'file_hash'.
    """
    candidates = {}
    for cat, intent in intents.items():
        # Write new-info summary to a temp file for candidate.py
        new_info_path = os.path.join(staging_dir, f"new-info-{cat}.txt")
        _safe_write(new_info_path, intent["new_info_summary"], pinned=pinned)

        cmd = [
            python,
            os.path.join(scripts_dir, "memory_candidate.py"),
            "--category", cat,
            "--new-info-file", new_info_path,
        ]
        if memory_root:
            cmd.extend(["--root", memory_root])

        lifecycle_hints = intent.get("lifecycle_hints", [])
        if lifecycle_hints:
            cmd.extend(["--lifecycle-event", lifecycle_hints[0]])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                cand = json.loads(result.stdout)
                candidates[cat] = cand

                # OCC hash capture: read candidate file and compute MD5
                cand_entry = cand.get("candidate")
                if cand_entry and cand_entry.get("path"):
                    cand_path = cand_entry["path"]
                    try:
                        file_bytes = Path(cand_path).read_bytes()
                        cand["file_hash"] = hashlib.md5(file_bytes).hexdigest()
                    except (OSError, IOError):
                        cand["file_hash"] = None
                else:
                    cand["file_hash"] = None
            else:
                candidates[cat] = None
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            candidates[cat] = None

    return candidates


# ---------------------------------------------------------------------------
# Step 3: CUD resolution
# ---------------------------------------------------------------------------

def resolve_cud(intents: dict, candidates: dict) -> dict:
    """Step 3: CUD resolution -- combine L1 (structural) with L2 (intent).

    Returns dict mapping category -> resolution dict with keys:
      action, candidate, candidate_path, occ_hash, reason (for NOOP/SKIP)
    """
    resolved = {}
    for cat, intent in intents.items():
        cand = candidates.get(cat)
        if cand is None:
            resolved[cat] = {"action": "SKIP", "reason": "candidate_failed"}
            continue

        pre_action = cand.get("pre_action")
        vetoes = cand.get("vetoes", [])

        # Pre-action NOOP means no viable target
        if pre_action == "NOOP":
            resolved[cat] = {"action": "NOOP", "reason": "pre_action_noop"}
            continue

        l1 = cand.get("structural_cud", "CREATE")
        l2 = intent.get("intended_action", "update").upper()
        if l2 not in ("CREATE", "UPDATE", "DELETE"):
            l2 = "UPDATE"  # safety default

        # Resolve via CUD table
        action = CUD_TABLE.get((l1, l2))
        if action is None:
            action = "UPDATE"  # safety default for unmapped combos

        # Apply vetoes: vetoes restrict specific actions
        if vetoes:
            veto_actions = set()
            for v in vetoes:
                v_upper = v.upper()
                if "DELETE" in v_upper:
                    veto_actions.add("DELETE")
                if "CREATE" in v_upper:
                    veto_actions.add("CREATE")
            if action in veto_actions:
                resolved[cat] = {
                    "action": "NOOP",
                    "reason": f"vetoed: {action}",
                }
                continue

        resolved[cat] = {
            "action": action,
            "candidate": cand.get("candidate"),
            "candidate_path": (
                cand.get("candidate", {}).get("path")
                if cand.get("candidate")
                else None
            ),
            "occ_hash": cand.get("file_hash"),  # propagate OCC hash from step 2
        }

    return resolved


# ---------------------------------------------------------------------------
# Step 4: Execute drafts
# ---------------------------------------------------------------------------

def execute_drafts(
    intents: dict,
    resolved: dict,
    staging_dir: str,
    scripts_dir: str,
    python: str,
    pinned=None,
    memory_root: str | None = None,
    slugify_fn=None,
    category_folders=None,
) -> None:
    """Step 4: Run memory_draft.py for each CREATE/UPDATE action.

    Mutates resolved dict in-place, adding draft_path or changing action to SKIP.
    When slugify_fn and category_folders are provided (prepare/run modes),
    generates target_path for CREATE actions.
    """
    for cat, res in resolved.items():
        if res["action"] not in ("CREATE", "UPDATE"):
            continue

        intent = intents[cat]
        input_path = os.path.join(staging_dir, f"input-{cat}.json")
        _safe_write(
            input_path,
            json.dumps(intent["partial_content"], ensure_ascii=False),
            pinned=pinned,
        )

        cmd = [
            python,
            os.path.join(scripts_dir, "memory_draft.py"),
            "--action", res["action"].lower(),
            "--category", cat,
            "--input-file", input_path,
            "--root", staging_dir,
        ]

        if res["action"] == "UPDATE" and res.get("candidate_path"):
            cmd.extend(["--candidate-file", res["candidate_path"]])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                draft_output = json.loads(result.stdout)
                res["draft_path"] = draft_output.get("draft_path")
            else:
                res["action"] = "SKIP"
                res["reason"] = f"draft_failed: {result.stderr[:200]}"
        except (subprocess.TimeoutExpired, json.JSONDecodeError) as e:
            res["action"] = "SKIP"
            res["reason"] = f"draft_error: {e}"

        # Generate target paths only in prepare/run modes (not no-flag default)
        if slugify_fn is not None and category_folders is not None:
            # CREATE: generate path from slugified title
            if res["action"] == "CREATE" and memory_root:
                title = intent.get("partial_content", {}).get("title", "")
                res["target_path"] = generate_target_path(
                    memory_root, cat, title, category_folders, slugify_fn
                )

            # UPDATE: target_path is the candidate_path
            if res["action"] == "UPDATE" and res.get("candidate_path"):
                res["target_path"] = res["candidate_path"]


def handle_deletes(intents: dict, resolved: dict, staging_dir: str, pinned=None) -> None:
    """Step 5: Write retire JSONs for DELETE actions.

    Mutates resolved dict in-place, adding draft_path for retire files.
    """
    for cat, res in resolved.items():
        if res["action"] != "DELETE":
            continue
        retire_path = os.path.join(staging_dir, f"draft-{cat}-retire.json")
        retire_data = {
            "action": "retire",
            "target": res.get("candidate_path", ""),
            "reason": intents[cat].get("new_info_summary", "Automated retirement"),
        }
        _safe_write(
            retire_path,
            json.dumps(retire_data, ensure_ascii=False),
            pinned=pinned,
        )
        res["draft_path"] = retire_path


def build_manifest(resolved: dict, enrich: bool = False) -> dict:
    """Step 6: Build the orchestration manifest.

    Returns manifest dict with status and per-category results.
    When enrich=True (prepare/run modes), adds manifest_version and prepared_at.
    """
    has_actionable = any(
        r["action"] in ("CREATE", "UPDATE", "DELETE")
        for r in resolved.values()
    )

    manifest = {
        "status": "actionable" if has_actionable else "all_noop",
        "categories": resolved,
    }

    if enrich:
        manifest["manifest_version"] = 1
        manifest["prepared_at"] = _now_utc()

    return manifest


# ---------------------------------------------------------------------------
# Step 7: Execute saves (D2)
# ---------------------------------------------------------------------------

def execute_saves(
    manifest: dict,
    staging_dir: str,
    memory_root: str,
    scripts_dir: str,
    python: str,
    exclude_categories: set | None = None,
    pinned=None,
) -> dict:
    """Step 7: Execute saves via memory_write.py subprocess calls.

    Args:
        manifest: Orchestration manifest from steps 1-6 (or loaded from file).
        staging_dir: Path to staging directory.
        memory_root: Path to memory root (e.g., ".claude/memory").
        scripts_dir: Path to hooks/scripts/ directory.
        python: Python executable path.
        exclude_categories: Categories to skip (verifier-blocked).
        pinned: Optional PinnedStagingDir for TOCTOU-safe I/O.

    Returns:
        {
            "status": "success" | "partial_failure" | "total_failure",
            "saved": [{"category": str, "action": str, "title": str, "target": str}],
            "errors": [{"category": str, "error": str}],
            "blocked": [{"category": str, "reason": str}],
        }
    """
    if exclude_categories is None:
        exclude_categories = set()

    categories = manifest.get("categories", {})
    saved = []
    errors = []
    blocked = []

    # If manifest is all_noop, return immediately
    if manifest.get("status") == "all_noop":
        return {"status": "success", "saved": [], "errors": [], "blocked": []}

    write_py = os.path.join(scripts_dir, "memory_write.py")

    # 1. Sentinel -> saving
    _update_sentinel(python, write_py, staging_dir, "saving")

    # 2. Per-category subprocess calls
    session_summary_saved = False
    for cat, res in categories.items():
        action = res.get("action", "NOOP")
        if action not in ("CREATE", "UPDATE", "DELETE"):
            continue

        # Skip excluded categories (verifier-blocked)
        if cat in exclude_categories:
            blocked.append({
                "category": cat,
                "reason": f"blocked_by_verifier",
            })
            continue

        draft_path = res.get("draft_path")
        target_path = res.get("target_path")
        candidate_path = res.get("candidate_path")
        occ_hash = res.get("occ_hash")

        # Build subprocess command
        if action == "CREATE":
            if not target_path:
                errors.append({
                    "category": cat,
                    "error": "SKIP: null target_path for CREATE action",
                })
                continue
            cmd = [
                python, write_py,
                "--action", "create",
                "--target", target_path,
                "--input", draft_path,
                "--category", cat,
                "--skip-auto-enforce",
            ]
        elif action == "UPDATE":
            update_target = candidate_path or target_path
            if not update_target:
                errors.append({
                    "category": cat,
                    "error": "SKIP: null target for UPDATE action (no candidate or target_path)",
                })
                continue
            if not draft_path:
                errors.append({
                    "category": cat,
                    "error": "SKIP: null draft_path for UPDATE action",
                })
                continue
            cmd = [
                python, write_py,
                "--action", "update",
                "--target", update_target,
                "--input", draft_path,
                "--skip-auto-enforce",
            ]
            if occ_hash:
                cmd.extend(["--hash", occ_hash])
        elif action == "DELETE":
            if not candidate_path:
                errors.append({
                    "category": cat,
                    "error": "SKIP: null candidate_path for DELETE action",
                })
                continue
            reason = "Automated retirement via orchestrator"
            # Try to get reason from the retire draft
            if draft_path:
                try:
                    retire_data = json.loads(Path(draft_path).read_text(encoding="utf-8"))
                    reason = retire_data.get("reason", reason)
                except (json.JSONDecodeError, OSError):
                    pass
            cmd = [
                python, write_py,
                "--action", "retire",
                "--target", candidate_path,
                "--reason", reason,
                "--skip-auto-enforce",
            ]
        else:
            continue

        # Execute
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                # Extract title from stdout if available
                title = _extract_title(result.stdout, res, cat)
                saved.append({
                    "category": cat,
                    "action": action,
                    "title": title,
                    "target": target_path or candidate_path or "",
                })
                if cat == "session_summary":
                    session_summary_saved = True
            else:
                err_msg = result.stderr.strip()[-500:] if result.stderr else "unknown error"
                errors.append({
                    "category": cat,
                    "error": f"WRITE_ERROR: {err_msg}",
                })
        except subprocess.TimeoutExpired:
            errors.append({
                "category": cat,
                "error": "SUBPROCESS_TIMEOUT: memory_write.py timed out after 30s",
            })

    # 3. Enforce once (session_summary only)
    if session_summary_saved:
        enforce_py = os.path.join(scripts_dir, "memory_enforce.py")
        try:
            subprocess.run(
                [python, enforce_py, "--category", "session_summary"],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass  # fail-open: enforcement failure is not fatal

    # Determine overall status
    all_errors = list(errors)
    # Add blocked categories as errors for the result file
    for b in blocked:
        all_errors.append({
            "category": b["category"],
            "error": f"blocked_by_verifier: {b.get('reason', 'no reason')}",
        })

    if not saved and (errors or blocked):
        status = "total_failure"
    elif errors:
        status = "partial_failure"
    else:
        status = "success"

    # 4. Write .triage-pending.json FIRST if any failed (D3-F1 correction)
    if errors:
        pending_data = {
            "categories": [e["category"] for e in errors],
            "reason": "total_failure" if not saved else "partial_failure",
            "timestamp": _now_utc(),
        }
        if saved:
            pending_data["succeeded_categories"] = [s["category"] for s in saved]
        pending_data["errors"] = errors
        _safe_write(
            os.path.join(staging_dir, ".triage-pending.json"),
            json.dumps(pending_data, indent=2, ensure_ascii=False) + "\n",
            pinned=pinned,
        )

    # 5. Write last-save-result.json via memory_write.py --action write-save-result
    if saved or all_errors:
        result_data = {
            "saved_at": _now_utc(),
            "categories": [s["category"] for s in saved],
            "titles": [s["title"] for s in saved],
            "errors": [{"category": e["category"], "error": e["error"]} for e in all_errors],
        }
        result_json = json.dumps(result_data, ensure_ascii=False)
        result_file_path = os.path.join(staging_dir, ".save-result-payload.json")
        try:
            _safe_write(result_file_path, result_json, pinned=pinned)
        except OSError:
            pass  # fail-open: sentinel and cleanup must still run
        try:
            subprocess.run(
                [python, write_py,
                 "--action", "write-save-result",
                 "--staging-dir", staging_dir,
                 "--result-file", result_file_path],
                capture_output=True, text=True, timeout=15,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass  # fail-open

    # 6. Sentinel -> saved/failed
    sentinel_state = "saved" if status == "success" else "failed"
    _update_sentinel(python, write_py, staging_dir, sentinel_state)

    # 7. Cleanup staging (only on full success)
    if status == "success":
        try:
            subprocess.run(
                [python, write_py,
                 "--action", "cleanup-staging",
                 "--staging-dir", staging_dir],
                capture_output=True, text=True, timeout=15,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass  # fail-open

    return {
        "status": status,
        "saved": saved,
        "errors": errors,
        "blocked": blocked,
    }


def _update_sentinel(python: str, write_py: str, staging_dir: str, state: str):
    """Update sentinel state (fail-open)."""
    try:
        subprocess.run(
            [python, write_py,
             "--action", "update-sentinel-state",
             "--state", state,
             "--staging-dir", staging_dir],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass  # fail-open per existing convention


def _extract_title(stdout: str, res: dict, cat: str) -> str:
    """Extract title from memory_write.py stdout or fallback to manifest data."""
    try:
        output = json.loads(stdout)
        if isinstance(output, dict) and output.get("title"):
            return output["title"]
    except (json.JSONDecodeError, ValueError):
        pass
    # Fallback: try candidate metadata
    cand = res.get("candidate")
    if isinstance(cand, dict) and cand.get("title"):
        return cand["title"]
    return cat


# ---------------------------------------------------------------------------
# Action mode: commit (step 7 from existing manifest)
# ---------------------------------------------------------------------------

def _run_commit(staging_dir: str, scripts_dir: str, python: str,
                memory_root: str | None, exclude_cats: set, pinned) -> int:
    """Read manifest from orchestration-result.json and run step 7 (execute_saves).

    Validates manifest version, staleness (2h TTL per p1-final.md), and status.
    """
    manifest_path = os.path.join(staging_dir, "orchestration-result.json")
    if not os.path.isfile(manifest_path):
        print("ERROR: orchestration-result.json not found in staging directory.",
              file=sys.stderr)
        return 1

    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"ERROR: Cannot read manifest: {e}", file=sys.stderr)
        return 1

    # Validate manifest version
    if manifest.get("manifest_version") != 1:
        print("ERROR: Incompatible manifest version. Expected manifest_version=1.",
              file=sys.stderr)
        return 1

    # Validate staleness (2 hours per p1-final.md D1-F2)
    prepared_at = manifest.get("prepared_at", "")
    if prepared_at:
        try:
            prepared_dt = datetime.strptime(prepared_at, "%Y-%m-%dT%H:%M:%SZ")
            prepared_dt = prepared_dt.replace(tzinfo=timezone.utc)
            age_seconds = abs((datetime.now(timezone.utc) - prepared_dt).total_seconds())
            if age_seconds > 7200:  # 2 hours (abs handles clock skew)
                print(f"ERROR: Stale manifest (prepared {age_seconds:.0f}s ago, "
                      f"max 7200s). Re-run with --action prepare.",
                      file=sys.stderr)
                return 1
        except (ValueError, TypeError):
            pass  # If we can't parse, proceed (fail-open)

    # If all_noop, nothing to do
    if manifest.get("status") == "all_noop":
        print(json.dumps({"status": "success", "saved": [], "errors": [], "blocked": []},
                         separators=(",", ":")))
        return 0

    # Validate target_paths for CREATE actions (I-5 correction)
    for cat, res in manifest.get("categories", {}).items():
        if res.get("action") == "CREATE" and not res.get("target_path"):
            if cat not in exclude_cats:
                print(f"WARNING: Null target_path for CREATE category '{cat}', "
                      f"will be skipped.", file=sys.stderr)

    # Resolve memory_root -- use from manifest or CLI
    effective_root = memory_root or ".claude/memory"

    result = execute_saves(
        manifest, staging_dir, effective_root, scripts_dir, python,
        exclude_categories=exclude_cats, pinned=pinned,
    )

    print(json.dumps(result, separators=(",", ":")))
    return 0 if result["status"] == "success" else 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 1.5 orchestration: deterministic CUD resolution pipeline."
    )
    parser.add_argument(
        "--staging-dir",
        required=True,
        help="Path to staging directory with intent-*.json files.",
    )
    parser.add_argument(
        "--memory-root",
        default=None,
        help="Path to memory root directory (passed to memory_candidate.py --root). "
        "Defaults to .claude/memory (candidate.py default).",
    )
    parser.add_argument(
        "--action",
        choices=["prepare", "commit", "run"],
        default=None,
        help="Action mode: prepare (steps 1-6 + target paths), "
             "commit (step 7 from manifest), run (steps 1-7). "
             "Default (no flag): steps 1-6 only.",
    )
    parser.add_argument(
        "--exclude-categories",
        default="",
        help="Comma-separated categories to skip in commit mode "
             "(verifier-blocked categories).",
    )
    args = parser.parse_args()

    staging_dir = str(Path(args.staging_dir).resolve())
    scripts_dir = str(Path(__file__).parent)
    python = sys.executable
    action = args.action  # None, "prepare", "commit", or "run"

    # Parse exclude categories
    exclude_cats = set()
    if args.exclude_categories:
        exclude_cats = {c.strip() for c in args.exclude_categories.split(",") if c.strip()}

    # Lazy import: only needed for prepare/run modes (target path generation)
    # commit reads target paths from manifest; no-flag default skips target gen
    slugify_fn = None
    category_folders = None
    if action in ("prepare", "run"):
        _script_dir = os.path.dirname(os.path.abspath(__file__))
        if _script_dir not in sys.path:
            sys.path.insert(0, _script_dir)
        from memory_write import slugify, CATEGORY_FOLDERS
        slugify_fn = slugify
        category_folders = CATEGORY_FOLDERS

    # Dispatch based on action mode
    if action == "commit":
        if PinnedStagingDir is not None:
            with PinnedStagingDir(path=staging_dir) as pinned:
                return _run_commit(staging_dir, scripts_dir, python,
                                   args.memory_root, exclude_cats, pinned)
        else:
            return _run_commit(staging_dir, scripts_dir, python,
                               args.memory_root, exclude_cats, None)
    else:
        # None, "prepare", "run" all start with steps 1-6
        enrich = action in ("prepare", "run")
        if PinnedStagingDir is not None:
            with PinnedStagingDir(path=staging_dir) as pinned:
                rc = _run_pipeline(
                    staging_dir, scripts_dir, python, args.memory_root, pinned,
                    enrich=enrich,
                    slugify_fn=slugify_fn,
                    category_folders=category_folders,
                )
                if rc != 0:
                    return rc
                if action == "run":
                    return _run_commit(staging_dir, scripts_dir, python,
                                       args.memory_root, exclude_cats, pinned)
                return 0
        else:
            rc = _run_pipeline(
                staging_dir, scripts_dir, python, args.memory_root, None,
                enrich=enrich,
                slugify_fn=slugify_fn,
                category_folders=category_folders,
            )
            if rc != 0:
                return rc
            if action == "run":
                return _run_commit(staging_dir, scripts_dir, python,
                                   args.memory_root, exclude_cats, None)
            return 0


def _run_pipeline(staging_dir: str, scripts_dir: str, python: str,
                  memory_root: str | None, pinned,
                  enrich: bool = False,
                  slugify_fn=None,
                  category_folders=None) -> int:
    """Execute the orchestration pipeline (steps 1-6).

    When *pinned* is not None, all staging I/O uses the fd-pinned directory
    to eliminate TOCTOU windows.

    When enrich=True (prepare/run modes), generates target paths for CREATE
    actions and adds manifest_version/prepared_at to the manifest.
    """
    # Resolve effective memory root for target path generation (prepare/run).
    # memory_root=None is fine for candidate selection (candidate.py has its own default),
    # but target path generation needs a concrete root path.
    effective_memory_root = memory_root
    if enrich and not effective_memory_root:
        effective_memory_root = ".claude/memory"

    # Step 1: Collect and validate intent JSONs
    intents = collect_intents(staging_dir, pinned=pinned)

    if not intents:
        # All NOOP -- output empty manifest
        manifest = {"status": "all_noop", "categories": {}}
        if enrich:
            manifest["manifest_version"] = 1
            manifest["prepared_at"] = _now_utc()
        _write_manifest(staging_dir, manifest, pinned=pinned)
        print(json.dumps(manifest, separators=(",", ":")))
        return 0

    # Step 2: Run candidate selection for each intent (includes OCC hash capture)
    candidates = run_candidate_selection(
        intents, staging_dir, scripts_dir, python,
        memory_root=memory_root,
        pinned=pinned,
    )

    # Step 3: CUD Resolution (propagates occ_hash from candidates)
    resolved = resolve_cud(intents, candidates)

    # Step 4: Execute drafts for CREATE/UPDATE (with target path gen in prepare/run modes)
    execute_drafts(
        intents, resolved, staging_dir, scripts_dir, python,
        pinned=pinned,
        memory_root=effective_memory_root,
        slugify_fn=slugify_fn,
        category_folders=category_folders,
    )

    # Step 5: Handle DELETE actions
    handle_deletes(intents, resolved, staging_dir, pinned=pinned)

    # Step 6: Build and write manifest
    manifest = build_manifest(resolved, enrich=enrich)
    _write_manifest(staging_dir, manifest, pinned=pinned)

    # Print compact summary to stdout
    print(json.dumps(manifest, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Step 2.9: Error handling -- on unhandled exception, try to preserve state
        # Write .triage-pending.json and set sentinel to failed
        print(f"FATAL: Unhandled exception: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)

        # Best-effort: write .triage-pending.json
        try:
            # Try to extract staging_dir from sys.argv
            staging_dir = None
            for i, arg in enumerate(sys.argv):
                if arg == "--staging-dir" and i + 1 < len(sys.argv):
                    staging_dir = str(Path(sys.argv[i + 1]).resolve())
                    break
            if staging_dir and os.path.isdir(staging_dir):
                pending_path = os.path.join(staging_dir, ".triage-pending.json")
                pending_data = {
                    "categories": [],
                    "reason": "total_failure",
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "errors": [{"category": "unknown", "error": f"FATAL: {e}"}],
                }
                _safe_write(pending_path, json.dumps(pending_data, indent=2) + "\n")

                # Update sentinel to failed
                scripts_dir = str(Path(__file__).parent)
                write_py = os.path.join(scripts_dir, "memory_write.py")
                _update_sentinel(sys.executable, write_py, staging_dir, "failed")
        except Exception:
            pass  # last-resort: silently fail

        sys.exit(1)
