#!/usr/bin/env python3
"""Smoke test for FTS5 engine integration in memory_retrieve.py.

Creates a temporary project structure with index.md + JSON memory files,
feeds hook_input JSON via stdin, and verifies output.
Tests both FTS5 and legacy fallback paths.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent / "hooks" / "scripts" / "memory_retrieve.py"


def make_project(tmp_dir, match_strategy="fts5_bm25"):
    """Create a project with .claude/memory/, config, index.md, and JSON files."""
    proj = Path(tmp_dir)
    mem = proj / ".claude" / "memory"
    mem.mkdir(parents=True)
    for folder in ["decisions", "runbooks", "preferences", "constraints", "sessions", "tech-debt"]:
        (mem / folder).mkdir()

    # Config
    config = {
        "retrieval": {
            "enabled": True,
            "max_inject": 5,
            "match_strategy": match_strategy,
        },
        "categories": {
            "decision": {"enabled": True, "folder": "decisions",
                         "description": "Architectural and technical choices"},
            "runbook": {"enabled": True, "folder": "runbooks",
                        "description": "Step-by-step procedures for fixing errors"},
            "preference": {"enabled": True, "folder": "preferences",
                           "description": "User conventions and workflow preferences"},
        },
    }
    with open(mem / "memory-config.json", "w") as f:
        json.dump(config, f)

    # Memory files
    memories = [
        {
            "schema_version": "1.0", "category": "decision", "id": "use-jwt",
            "title": "Use JWT for authentication",
            "record_status": "active",
            "created_at": "2026-01-15T10:00:00Z",
            "updated_at": "2026-02-10T10:00:00Z",
            "tags": ["auth", "jwt", "security"],
            "confidence": 0.9,
            "content": {
                "status": "accepted",
                "context": "Need stateless auth for API",
                "decision": "Use JWT tokens with 1h expiry",
                "rationale": ["Stateless", "Industry standard"],
                "alternatives": [{"option": "Session cookies", "rejected_reason": "Not stateless"}],
                "consequences": ["Must handle token refresh"],
            },
            "changes": [], "times_updated": 0,
        },
        {
            "schema_version": "1.0", "category": "runbook", "id": "fix-db-timeout",
            "title": "Fix database connection timeout",
            "record_status": "active",
            "created_at": "2026-01-25T14:00:00Z",
            "updated_at": "2026-02-01T14:00:00Z",
            "tags": ["database", "connection", "timeout"],
            "confidence": 0.8,
            "content": {
                "trigger": "Database connection timeout errors in logs",
                "symptoms": ["Slow queries", "Connection pool exhaustion"],
                "steps": ["Check connection pool size", "Restart connection pool"],
                "verification": "Query response time < 100ms",
                "root_cause": "Connection leak in ORM",
            },
            "changes": [], "times_updated": 0,
        },
        {
            "schema_version": "1.0", "category": "preference", "id": "prefer-typescript",
            "title": "Prefer TypeScript over JavaScript",
            "record_status": "active",
            "created_at": "2026-01-10T08:00:00Z",
            "updated_at": "2026-02-01T08:00:00Z",
            "tags": ["typescript", "language"],
            "confidence": 0.95,
            "content": {
                "topic": "Programming language choice",
                "value": "TypeScript",
                "reason": "Better type safety and tooling",
                "strength": "strong",
            },
            "changes": [], "times_updated": 0,
        },
        {
            "schema_version": "1.0", "category": "decision", "id": "rate-limiting",
            "title": "Rate limiting with sliding window",
            "record_status": "active",
            "created_at": "2026-01-20T10:00:00Z",
            "updated_at": "2026-02-05T10:00:00Z",
            "tags": ["rate-limiting", "api", "security"],
            "confidence": 0.85,
            "content": {
                "status": "accepted",
                "context": "Need rate limiting for public API endpoints",
                "decision": "Use sliding window algorithm with Redis",
                "rationale": ["Smooth traffic", "Handles bursts well"],
                "alternatives": [{"option": "Token bucket", "rejected_reason": "Less fair"}],
                "consequences": ["Redis dependency"],
            },
            "changes": [], "times_updated": 0,
        },
    ]

    folder_map = {
        "decision": "decisions", "runbook": "runbooks",
        "preference": "preferences", "constraint": "constraints",
        "tech_debt": "tech-debt", "session_summary": "sessions",
    }

    index_lines = ["# Memory Index", "", "<!-- Auto-generated -->", ""]
    for m in memories:
        cat = m["category"]
        folder = folder_map[cat]
        path = f".claude/memory/{folder}/{m['id']}.json"
        file_path = mem / folder / f"{m['id']}.json"
        with open(file_path, "w") as f:
            json.dump(m, f, indent=2)

        display = cat.upper()
        tags = m.get("tags", [])
        line = f"- [{display}] {m['title']} -> {path}"
        if tags:
            line += f" #tags:{','.join(tags)}"
        index_lines.append(line)

    index_lines.append("")
    with open(mem / "index.md", "w") as f:
        f.write("\n".join(index_lines))

    return proj


def run_retrieve(project_dir, user_prompt):
    """Run memory_retrieve.py with the given prompt and return stdout."""
    hook_input = json.dumps({
        "user_prompt": user_prompt,
        "cwd": str(project_dir),
    })
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input=hook_input, capture_output=True, text=True, timeout=15,
    )
    return result.stdout, result.stderr, result.returncode


def test_fts5_path():
    """Test FTS5 BM25 path."""
    print("=== TEST: FTS5 BM25 Path ===")
    with tempfile.TemporaryDirectory() as tmp:
        proj = make_project(tmp, match_strategy="fts5_bm25")
        queries = [
            ("How does authentication work?", "authentication"),
            ("Fix the database connection timeout issue", "database"),
            ("What TypeScript preferences do we have?", "TypeScript"),
            ("Rate limiting configuration", "rate"),
            ("JWT token refresh flow", "JWT"),
        ]
        all_pass = True
        for prompt, expect_keyword in queries:
            stdout, stderr, rc = run_retrieve(proj, prompt)
            if "<memory-context" in stdout:
                print(f"  PASS: '{prompt[:40]}...' -> got results")
                if "</memory-context>" not in stdout:
                    print(f"    WARN: Missing closing tag")
                    all_pass = False
            else:
                print(f"  FAIL: '{prompt[:40]}...' -> no results (rc={rc})")
                if stderr:
                    print(f"    stderr: {stderr.strip()}")
                all_pass = False

        return all_pass


def test_legacy_path():
    """Test legacy keyword fallback path."""
    print("\n=== TEST: Legacy Keyword Path ===")
    with tempfile.TemporaryDirectory() as tmp:
        proj = make_project(tmp, match_strategy="title_tags")
        queries = [
            ("How does authentication work?", "authentication"),
            ("Fix the database connection timeout issue", "database"),
            ("What TypeScript preferences do we have?", "TypeScript"),
            ("Rate limiting configuration", "rate"),
            ("JWT token refresh flow", "JWT"),
        ]
        all_pass = True
        for prompt, expect_keyword in queries:
            stdout, stderr, rc = run_retrieve(proj, prompt)
            if "<memory-context" in stdout:
                print(f"  PASS: '{prompt[:40]}...' -> got results")
            else:
                print(f"  FAIL: '{prompt[:40]}...' -> no results (rc={rc})")
                if stderr:
                    print(f"    stderr: {stderr.strip()}")
                all_pass = False

        return all_pass


def test_output_format_match():
    """Verify FTS5 and legacy paths produce same output format."""
    print("\n=== TEST: Output Format Consistency ===")
    prompt = "How does JWT authentication work?"
    with tempfile.TemporaryDirectory() as tmp:
        proj_fts5 = make_project(tmp + "/fts5", match_strategy="fts5_bm25")
        proj_legacy = make_project(tmp + "/legacy", match_strategy="title_tags")

        stdout_fts5, _, _ = run_retrieve(proj_fts5, prompt)
        stdout_legacy, _, _ = run_retrieve(proj_legacy, prompt)

        # Both should start/end with memory-context tags
        fts5_ok = "<memory-context" in stdout_fts5 and "</memory-context>" in stdout_fts5
        legacy_ok = "<memory-context" in stdout_legacy and "</memory-context>" in stdout_legacy

        if fts5_ok and legacy_ok:
            print(f"  PASS: Both paths produce <memory-context> output")
            # Check line format consistency (<result category="..." confidence="...">...</result>)
            fts5_lines = [l for l in stdout_fts5.strip().split("\n") if l.strip().startswith("<result ")]
            legacy_lines = [l for l in stdout_legacy.strip().split("\n") if l.strip().startswith("<result ")]
            if fts5_lines and legacy_lines:
                print(f"  PASS: FTS5 returned {len(fts5_lines)} results, legacy returned {len(legacy_lines)} results")
                # Verify format: - [CAT] title -> path #tags:...
                for line in fts5_lines + legacy_lines:
                    if " -> " not in line:
                        print(f"  FAIL: Missing ' -> ' delimiter in: {line}")
                        return False
                print(f"  PASS: All lines have correct format")
                return True
            else:
                print(f"  FAIL: No result lines found")
                return False
        else:
            print(f"  FAIL: FTS5 output ok={fts5_ok}, legacy ok={legacy_ok}")
            if not fts5_ok:
                print(f"    FTS5 stdout: {stdout_fts5[:200]}")
            if not legacy_ok:
                print(f"    Legacy stdout: {stdout_legacy[:200]}")
            return False


def test_short_prompt_exit():
    """Verify short prompts exit silently."""
    print("\n=== TEST: Short Prompt Exit ===")
    with tempfile.TemporaryDirectory() as tmp:
        proj = make_project(tmp)
        stdout, stderr, rc = run_retrieve(proj, "hi")
        if not stdout.strip():
            print(f"  PASS: Short prompt produced no output")
            return True
        else:
            print(f"  FAIL: Short prompt produced output: {stdout[:100]}")
            return False


def test_empty_input():
    """Verify empty input exits silently."""
    print("\n=== TEST: Empty Input Exit ===")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        input="", capture_output=True, text=True, timeout=15,
    )
    if not result.stdout.strip():
        print(f"  PASS: Empty input produced no output")
        return True
    else:
        print(f"  FAIL: Empty input produced output: {result.stdout[:100]}")
        return False


if __name__ == "__main__":
    results = []
    results.append(("FTS5 path", test_fts5_path()))
    results.append(("Legacy path", test_legacy_path()))
    results.append(("Output format", test_output_format_match()))
    results.append(("Short prompt", test_short_prompt_exit()))
    results.append(("Empty input", test_empty_input()))

    print("\n=== SUMMARY ===")
    all_pass = True
    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {status}: {name}")
        if not passed:
            all_pass = False

    sys.exit(0 if all_pass else 1)
