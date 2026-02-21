#!/usr/bin/env python3
"""Session 1 functional verification script -- comprehensive testing of all new functionality."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Setup path so we can import memory_retrieve
SCRIPT_DIR = Path(__file__).resolve().parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from memory_retrieve import (
    tokenize,
    score_entry,
    score_description,
    extract_body_text,
    BODY_FIELDS,
    HAS_FTS5,
    _COMPOUND_TOKEN_RE,
    _LEGACY_TOKEN_RE,
)

results = []

def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((name, status, detail))
    mark = "OK" if condition else "FAIL"
    print(f"  [{mark}] {name}" + (f" -- {detail}" if detail else ""))
    return condition


# =========================================================================
# SECTION 1: Tokenizer Tests
# =========================================================================
print("\n=== SECTION 1: Tokenizer Tests ===")

# 1.1 Compound tokenizer preserves underscored identifiers
tok = tokenize("user_id field", legacy=False)
check("1.1a compound: user_id preserved", "user_id" in tok, f"got {tok}")
check("1.1b compound: field preserved", "field" in tok, f"got {tok}")

# 1.2 Legacy tokenizer splits underscored identifiers
tok_legacy = tokenize("user_id field", legacy=True)
check("1.2a legacy: splits user", "user" in tok_legacy, f"got {tok_legacy}")
check("1.2b legacy: splits id (len=2, kept by len>1)", "id" in tok_legacy, f"got {tok_legacy}")
check("1.2c legacy: field preserved", "field" in tok_legacy, f"got {tok_legacy}")
check("1.2d legacy: user_id NOT present", "user_id" not in tok_legacy, f"got {tok_legacy}")

# 1.3 Dotted compound tokens
tok = tokenize("React.FC component", legacy=False)
check("1.3 compound: react.fc preserved", "react.fc" in tok, f"got {tok}")

# 1.4 Hyphenated compound tokens
tok = tokenize("rate-limiting setup", legacy=False)
check("1.4 compound: rate-limiting preserved", "rate-limiting" in tok, f"got {tok}")

# 1.5 Version strings
tok = tokenize("v2.0 migration", legacy=False)
check("1.5a compound: v2.0 preserved", "v2.0" in tok, f"got {tok}")
check("1.5b compound: migration preserved", "migration" in tok, f"got {tok}")

# 1.6 Simple word same in both modes
tok_c = tokenize("pydantic", legacy=False)
tok_l = tokenize("pydantic", legacy=True)
check("1.6 simple word identical in both modes", tok_c == tok_l, f"compound={tok_c}, legacy={tok_l}")

# 1.7 Filename compound tokens
tok = tokenize("test_memory_retrieve.py", legacy=False)
has_compound = any("_" in t or "." in t for t in tok)
check("1.7 filename contains compound token", has_compound, f"got {tok}")

# 1.8 Empty string
tok = tokenize("", legacy=False)
check("1.8 empty string -> empty set", tok == set(), f"got {tok}")

# 1.9 All stop words
tok = tokenize("the is a", legacy=False)
check("1.9 all stop words -> empty set", tok == set(), f"got {tok}")

# 1.10 Additional tokenizer edge cases
tok = tokenize("___", legacy=False)
check("1.10a all underscores -> empty set", tok == set(), f"got {tok}")

tok = tokenize("1.2.3", legacy=False)
check("1.10b version string 1.2.3", "1.2.3" in tok, f"got {tok}")

tok = tokenize("a_b_c_d_e_f", legacy=False)
check("1.10c long underscore chain", "a_b_c_d_e_f" in tok, f"got {tok}")


# =========================================================================
# SECTION 2: Body Extraction Tests
# =========================================================================
print("\n=== SECTION 2: Body Content Extraction Tests ===")

# 2.1 Decision memory
decision_data = {
    "category": "decision",
    "content": {
        "context": "We needed to choose an auth strategy",
        "decision": "Use JWT with refresh tokens",
        "rationale": "Industry standard, stateless",
        "consequences": "Need token rotation logic"
    }
}
body = extract_body_text(decision_data)
check("2.1a decision: extracts context", "choose an auth strategy" in body)
check("2.1b decision: extracts decision", "JWT with refresh tokens" in body)
check("2.1c decision: extracts rationale", "Industry standard" in body)
check("2.1d decision: extracts consequences", "token rotation" in body)

# 2.2 Runbook memory
runbook_data = {
    "category": "runbook",
    "content": {
        "trigger": "Database connection timeout",
        "symptoms": ["Slow queries", "Connection pool exhausted"],
        "steps": [
            {"action": "Check connection pool", "detail": "Run pg_stat_activity"},
            {"action": "Restart service", "detail": "Use systemctl restart"}
        ],
        "verification": "Check latency drops below 100ms",
        "root_cause": "Connection leak in ORM"
    }
}
body = extract_body_text(runbook_data)
check("2.2a runbook: extracts trigger", "Database connection timeout" in body)
check("2.2b runbook: extracts symptoms (list)", "Slow queries" in body)
check("2.2c runbook: extracts steps (list of dicts)", "Check connection pool" in body)
check("2.2d runbook: extracts verification", "latency drops" in body)
check("2.2e runbook: extracts root_cause", "Connection leak" in body)

# 2.3 Constraint memory
constraint_data = {
    "category": "constraint",
    "content": {
        "rule": "API payload must not exceed 1MB",
        "impact": "Large file uploads will fail",
        "workarounds": ["Use chunked upload", "Compress payload"]
    }
}
body = extract_body_text(constraint_data)
check("2.3a constraint: extracts rule", "payload must not exceed" in body)
check("2.3b constraint: extracts impact", "Large file uploads" in body)
check("2.3c constraint: extracts workarounds", "chunked upload" in body)

# 2.4 Tech debt memory
tech_debt_data = {
    "category": "tech_debt",
    "content": {
        "description": "Legacy auth module uses MD5 hashing",
        "reason_deferred": "Migration requires downtime",
        "impact": "Security vulnerability for stored passwords",
        "suggested_fix": "Migrate to bcrypt with rolling update"
    }
}
body = extract_body_text(tech_debt_data)
check("2.4a tech_debt: extracts description", "Legacy auth module" in body)
check("2.4b tech_debt: extracts reason_deferred", "Migration requires downtime" in body)
check("2.4c tech_debt: extracts impact", "Security vulnerability" in body)
check("2.4d tech_debt: extracts suggested_fix", "bcrypt" in body)

# 2.5 Preference memory
preference_data = {
    "category": "preference",
    "content": {
        "topic": "TypeScript vs JavaScript",
        "value": "Always use TypeScript for new projects",
        "reason": "Type safety reduces bugs"
    }
}
body = extract_body_text(preference_data)
check("2.5a preference: extracts topic", "TypeScript vs JavaScript" in body)
check("2.5b preference: extracts value", "Always use TypeScript" in body)
check("2.5c preference: extracts reason", "Type safety" in body)

# 2.6 Session summary
session_data = {
    "category": "session_summary",
    "content": {
        "goal": "Implement FTS5 retrieval",
        "outcome": "Foundation code complete",
        "completed": ["Dual tokenizer", "Body extraction"],
        "next_actions": ["Build FTS5 index", "Add scoring"]
    }
}
body = extract_body_text(session_data)
check("2.6a session_summary: extracts goal", "Implement FTS5 retrieval" in body)
check("2.6b session_summary: extracts outcome", "Foundation code complete" in body)
check("2.6c session_summary: extracts completed (list)", "Dual tokenizer" in body)
check("2.6d session_summary: extracts next_actions (list)", "Build FTS5 index" in body)

# 2.7 Edge cases
check("2.7a empty dict content", extract_body_text({"category": "decision", "content": {}}) == "")
check("2.7b None content", extract_body_text({"category": "decision", "content": None}) == "")
check("2.7c non-dict content (string)", extract_body_text({"category": "decision", "content": "string"}) == "")
check("2.7d non-dict content (list)", extract_body_text({"category": "decision", "content": ["a", "b"]}) == "")
check("2.7e missing content key", extract_body_text({"category": "decision"}) == "")
check("2.7f missing category key", extract_body_text({"content": {"rule": "test"}}) == "")
check("2.7g unknown category", extract_body_text({"category": "unknown", "content": {"x": "y"}}) == "")

# 2.8 Truncation
big_content = {"category": "decision", "content": {"context": "A" * 3000}}
body = extract_body_text(big_content)
check("2.8 truncation to 2000 chars", len(body) == 2000, f"got {len(body)}")


# =========================================================================
# SECTION 3: FTS5 Availability
# =========================================================================
print("\n=== SECTION 3: FTS5 Check ===")

check("3.1 HAS_FTS5 is True on this system", HAS_FTS5 is True, f"got {HAS_FTS5}")
check("3.2 HAS_FTS5 is a bool", isinstance(HAS_FTS5, bool), f"type={type(HAS_FTS5)}")


# =========================================================================
# SECTION 4: Backward Compatibility (score_entry)
# =========================================================================
print("\n=== SECTION 4: Backward Compatibility ===")

# 4.1 Exact title match = 2 points
s = score_entry({"jwt"}, {"title": "JWT authentication", "tags": set()})
check("4.1 exact title match -> 2 pts", s == 2, f"got {s}")

# 4.2 Exact tag match = 3 points
s = score_entry({"jwt"}, {"title": "other", "tags": {"jwt"}})
check("4.2 exact tag match -> 3 pts", s == 3, f"got {s}")

# 4.3 Prefix match on title = 1 point
s = score_entry({"auth"}, {"title": "authentication system", "tags": set()})
check("4.3 prefix match -> 1 pt", s == 1, f"got {s}")

# 4.4 Title + tag combined
s = score_entry({"jwt", "auth"}, {"title": "JWT authentication", "tags": {"auth"}})
# jwt exact title = 2, auth exact tag = 3 -> 5
check("4.4 title(2) + tag(3) -> 5", s == 5, f"got {s}")

# 4.5 No match
s = score_entry({"unrelated"}, {"title": "something else", "tags": set()})
check("4.5 no match -> 0", s == 0, f"got {s}")

# 4.6 Score description capping
s = score_description({"configure", "database", "connection", "pooling", "timeout"},
                       {"database", "connection", "configuration", "management"})
check("4.6 score_description capped at 2", s <= 2, f"got {s}")


# =========================================================================
# SECTION 5: BODY_FIELDS coverage
# =========================================================================
print("\n=== SECTION 5: BODY_FIELDS Coverage ===")

expected_categories = {"session_summary", "decision", "runbook", "constraint", "tech_debt", "preference"}
actual_categories = set(BODY_FIELDS.keys())
check("5.1 all 6 categories present", actual_categories == expected_categories,
      f"missing={expected_categories - actual_categories}, extra={actual_categories - expected_categories}")

for cat, fields in BODY_FIELDS.items():
    check(f"5.2 {cat} has fields", len(fields) > 0, f"fields={fields}")


# =========================================================================
# SECTION 6: Integration Smoke Tests
# =========================================================================
print("\n=== SECTION 6: Integration Smoke Tests ===")

# Create a temporary memory environment
with tempfile.TemporaryDirectory() as tmpdir:
    mem_root = Path(tmpdir) / ".claude" / "memory"
    decisions_dir = mem_root / "decisions"
    runbooks_dir = mem_root / "runbooks"
    preferences_dir = mem_root / "preferences"
    constraints_dir = mem_root / "constraints"

    for d in [decisions_dir, runbooks_dir, preferences_dir, constraints_dir]:
        d.mkdir(parents=True)

    # Create memory files
    decision_file = decisions_dir / "jwt-auth.json"
    decision_file.write_text(json.dumps({
        "title": "JWT authentication flow",
        "category": "decision",
        "record_status": "active",
        "updated_at": "2026-02-20T00:00:00Z",
        "tags": ["jwt", "auth"],
        "content": {
            "context": "Need stateless auth",
            "decision": "Use JWT with refresh",
            "rationale": "Standard approach",
            "consequences": "Need rotation"
        }
    }))

    runbook_file = runbooks_dir / "db-timeout.json"
    runbook_file.write_text(json.dumps({
        "title": "Database connection timeout troubleshooting",
        "category": "runbook",
        "record_status": "active",
        "updated_at": "2026-02-19T00:00:00Z",
        "tags": ["database", "timeout"],
        "content": {
            "trigger": "Connection timeout errors",
            "symptoms": ["Slow queries"],
            "steps": ["Check pool stats"],
            "verification": "Latency check"
        }
    }))

    preference_file = preferences_dir / "typescript.json"
    preference_file.write_text(json.dumps({
        "title": "TypeScript preference",
        "category": "preference",
        "record_status": "active",
        "updated_at": "2026-02-18T00:00:00Z",
        "tags": ["typescript", "language"],
        "content": {
            "topic": "Language choice",
            "value": "TypeScript for all new projects",
            "reason": "Type safety"
        }
    }))

    constraint_file = constraints_dir / "api-payload.json"
    constraint_file.write_text(json.dumps({
        "title": "API payload limit",
        "category": "constraint",
        "record_status": "active",
        "updated_at": "2026-02-17T00:00:00Z",
        "tags": ["api", "payload", "limit"],
        "content": {
            "rule": "Max 1MB payload",
            "impact": "Large uploads fail",
            "workarounds": ["Chunk upload"]
        }
    }))

    # Create index.md
    index_lines = [
        "# Memory Index\n",
        "\n",
        f"- [DECISION] JWT authentication flow -> .claude/memory/decisions/jwt-auth.json #tags:jwt,auth\n",
        f"- [RUNBOOK] Database connection timeout troubleshooting -> .claude/memory/runbooks/db-timeout.json #tags:database,timeout\n",
        f"- [PREFERENCE] TypeScript preference -> .claude/memory/preferences/typescript.json #tags:typescript,language\n",
        f"- [CONSTRAINT] API payload limit -> .claude/memory/constraints/api-payload.json #tags:api,payload,limit\n",
    ]
    (mem_root / "index.md").write_text("".join(index_lines))

    script = str(SCRIPT_DIR / "memory_retrieve.py")

    def run_query(prompt):
        hook_input = json.dumps({"user_prompt": prompt, "cwd": tmpdir})
        result = subprocess.run(
            [sys.executable, script],
            input=hook_input,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip(), result.returncode

    # 6.1 JWT query
    out, rc = run_query("How does JWT authentication work?")
    check("6.1 JWT query matches decision", "JWT authentication" in out, f"rc={rc}, out={out[:200]}")

    # 6.2 Database timeout
    out, rc = run_query("database connection timeout")
    check("6.2 DB timeout matches runbook", "Database connection timeout" in out, f"rc={rc}, out={out[:200]}")

    # 6.3 TypeScript
    out, rc = run_query("TypeScript preference for projects")
    check("6.3 TypeScript matches preference", "TypeScript preference" in out, f"rc={rc}, out={out[:200]}")

    # 6.4 API payload
    out, rc = run_query("API payload limit constraint")
    check("6.4 API payload matches constraint", "API payload limit" in out, f"rc={rc}, out={out[:200]}")

    # 6.5 Irrelevant query
    out, rc = run_query("what is the weather today in Paris")
    check("6.5 irrelevant query no match", out == "", f"rc={rc}, out={out[:200]}")


# =========================================================================
# SUMMARY
# =========================================================================
print("\n" + "=" * 60)
passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s == "FAIL")
total = len(results)
print(f"RESULTS: {passed}/{total} passed, {failed} failed")
if failed > 0:
    print("\nFAILED TESTS:")
    for name, status, detail in results:
        if status == "FAIL":
            print(f"  FAIL: {name} -- {detail}")
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
    sys.exit(0)
