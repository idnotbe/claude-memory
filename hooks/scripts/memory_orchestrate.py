#!/usr/bin/env python3
"""Phase 1.5 orchestration: deterministic CUD resolution pipeline.

Replaces LLM-driven Phase 1.5 with a single script invocation.
Reads intent files, runs candidate selection, resolves CUD actions,
assembles drafts, and outputs a manifest.

No external dependencies (stdlib only -- calls candidate.py and draft.py as subprocesses).
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


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


def _safe_write(path: str, content: str):
    """Write file atomically with O_NOFOLLOW to prevent symlink attacks."""
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


def _write_manifest(staging_dir: str, manifest: dict):
    """Write orchestration manifest to staging directory."""
    path = os.path.join(staging_dir, "orchestration-result.json")
    _safe_write(path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def collect_intents(staging_dir: str) -> dict:
    """Step 1: Collect and validate intent JSONs from staging directory.

    Returns dict mapping category -> validated intent data.
    Skips noop intents and intents with missing required fields.
    """
    intents = {}
    for f in sorted(Path(staging_dir).glob("intent-*.json")):
        cat = f.stem.replace("intent-", "")
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue  # skip invalid files

        if data.get("action") == "noop":
            continue  # skip noop intents

        # Validate required top-level fields
        required = ["category", "new_info_summary", "partial_content"]
        if not all(data.get(k) for k in required):
            continue

        # Validate required partial_content fields
        pc = data.get("partial_content", {})
        pc_required = ["title", "tags", "confidence", "change_summary", "content"]
        if not all(pc.get(k) is not None for k in pc_required):
            continue

        intents[cat] = data

    return intents


def run_candidate_selection(
    intents: dict,
    staging_dir: str,
    scripts_dir: str,
    python: str,
    memory_root: str | None = None,
) -> dict:
    """Step 2: Run memory_candidate.py for each intent.

    Returns dict mapping category -> candidate result (or None on failure).
    """
    candidates = {}
    for cat, intent in intents.items():
        # Write new-info summary to a temp file for candidate.py
        new_info_path = os.path.join(staging_dir, f"new-info-{cat}.txt")
        _safe_write(new_info_path, intent["new_info_summary"])

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
                candidates[cat] = json.loads(result.stdout)
            else:
                candidates[cat] = None
        except (subprocess.TimeoutExpired, json.JSONDecodeError):
            candidates[cat] = None

    return candidates


def resolve_cud(intents: dict, candidates: dict) -> dict:
    """Step 3: CUD resolution -- combine L1 (structural) with L2 (intent).

    Returns dict mapping category -> resolution dict with keys:
      action, candidate, candidate_path, reason (for NOOP/SKIP)
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
        }

    return resolved


def execute_drafts(
    intents: dict,
    resolved: dict,
    staging_dir: str,
    scripts_dir: str,
    python: str,
) -> None:
    """Step 4: Run memory_draft.py for each CREATE/UPDATE action.

    Mutates resolved dict in-place, adding draft_path or changing action to SKIP.
    """
    for cat, res in resolved.items():
        if res["action"] not in ("CREATE", "UPDATE"):
            continue

        intent = intents[cat]
        input_path = os.path.join(staging_dir, f"input-{cat}.json")
        _safe_write(
            input_path,
            json.dumps(intent["partial_content"], ensure_ascii=False),
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


def handle_deletes(intents: dict, resolved: dict, staging_dir: str) -> None:
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
        )
        res["draft_path"] = retire_path


def build_manifest(resolved: dict) -> dict:
    """Step 6: Build the orchestration manifest.

    Returns manifest dict with status and per-category results.
    """
    has_actionable = any(
        r["action"] in ("CREATE", "UPDATE", "DELETE")
        for r in resolved.values()
    )

    return {
        "status": "actionable" if has_actionable else "all_noop",
        "categories": resolved,
    }


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
    args = parser.parse_args()

    staging_dir = str(Path(args.staging_dir).resolve())
    scripts_dir = str(Path(__file__).parent)
    python = sys.executable

    # Step 1: Collect and validate intent JSONs
    intents = collect_intents(staging_dir)

    if not intents:
        # All NOOP -- output empty manifest
        manifest = {"status": "all_noop", "categories": {}}
        _write_manifest(staging_dir, manifest)
        print(json.dumps(manifest, separators=(",", ":")))
        return 0

    # Step 2: Run candidate selection for each intent
    candidates = run_candidate_selection(
        intents, staging_dir, scripts_dir, python,
        memory_root=args.memory_root,
    )

    # Step 3: CUD Resolution
    resolved = resolve_cud(intents, candidates)

    # Step 4: Execute drafts for CREATE/UPDATE
    execute_drafts(intents, resolved, staging_dir, scripts_dir, python)

    # Step 5: Handle DELETE actions
    handle_deletes(intents, resolved, staging_dir)

    # Step 6: Build and write manifest
    manifest = build_manifest(resolved)
    _write_manifest(staging_dir, manifest)

    # Print compact summary to stdout
    print(json.dumps(manifest, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
