#!/usr/bin/env python3
"""A4: score_entry() scoring proof -- verify IDENTICAL scores before/after change"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))
from memory_retrieve import score_entry, tokenize, STOP_WORDS

PASS = 0
FAIL = 0
results = []

def check(label, expected, actual):
    global PASS, FAIL
    ok = expected == actual
    if ok:
        PASS += 1
        results.append(f"  PASS: {label}")
    else:
        FAIL += 1
        results.append(f"  FAIL: {label}\n        expected={expected!r}\n        actual  ={actual!r}")

print("=== A4: score_entry() Scoring Proof ===\n")

# The ONLY change to score_entry was:
#   OLD: tokenize(entry["title"])        # used default legacy=False... wait, check this
#   NEW: tokenize(entry["title"], legacy=True)
#
# BEFORE Session 1, there was only one tokenize() with [a-z0-9]+ regex.
# AFTER Session 1, score_entry calls tokenize(title, legacy=True) which uses the same [a-z0-9]+ regex.
# So the outputs should be IDENTICAL.

# We simulate the OLD score_entry by using tokenize(title, legacy=True) -- which IS the old behavior.
# The question is: does score_entry() now produce the same scores as before?
# Since the ONLY change was adding `legacy=True` to the call, and legacy=True uses the same regex,
# the answer is YES. But let's prove it with test cases.

OLD_RE = re.compile(r"[a-z0-9]+")

def old_score_entry(prompt_words, entry):
    """Simulate the pre-Session-1 score_entry (identical logic, uses OLD_RE directly)"""
    title_tokens = {w for w in OLD_RE.findall(entry["title"].lower()) if w not in STOP_WORDS and len(w) > 1}
    entry_tags = entry["tags"]

    exact_title = prompt_words & title_tokens
    score = len(exact_title) * 2

    exact_tags = prompt_words & entry_tags
    score += len(exact_tags) * 3

    already_matched = exact_title | exact_tags
    combined_targets = title_tokens | entry_tags
    for pw in prompt_words - already_matched:
        if len(pw) >= 4:
            if any(target.startswith(pw) for target in combined_targets):
                score += 1
            elif any(pw.startswith(target) and len(target) >= 4 for target in combined_targets):
                score += 1

    return score

test_cases = [
    # (prompt_words, title, tags, description)
    ({"jwt"}, "JWT authentication flow", set(), "exact title match"),
    ({"jwt"}, "Other title", {"jwt"}, "exact tag match"),
    ({"auth"}, "authentication system", set(), "prefix match (forward)"),
    ({"authentication"}, "auth setup", {"auth"}, "reverse prefix + tag match"),
    ({"jwt", "auth"}, "JWT authentication flow", {"auth"}, "multi-match"),
    ({"unrelated"}, "Other thing", set(), "no match"),
    ({"database"}, "Database connection pooling", {"db", "postgres"}, "title match, no tag match"),
    ({"config"}, "configuration file parsing", {"config"}, "prefix + tag overlap"),
    ({"rate"}, "rate-limiting setup", set(), "title word match on compound word (legacy splits 'rate-limiting')"),
    ({"memory"}, "memory_write.py validation", set(), "title match with compound identifier (legacy splits)"),
    ({"pydantic", "validation"}, "Pydantic v2 schema validation", {"pydantic", "schema"}, "multiple matches"),
    ({"fts5", "search"}, "FTS5 full-text search indexing", {"fts5", "sqlite"}, "mixed title+tag"),
    ({"abc"}, "abcdef ghijkl", set(), "3-char prefix -- blocked by len>=4"),
    ({"abcd"}, "abcdef ghijkl", set(), "4-char prefix -- allowed"),
    (set(), "title", set(), "empty prompt words"),
    ({"word"}, "", set(), "empty title"),
]

for prompt_words, title, tags, desc in test_cases:
    entry = {"title": title, "tags": tags, "category": "DECISION", "path": "test.json", "raw": ""}
    old = old_score_entry(prompt_words, entry)
    new = score_entry(prompt_words, entry)
    check(f"{desc}: old={old}, new={new}", old, new)

# Extra: verify that compound titles like "user_id" are handled correctly
# In the OLD code, tokenize("user_id field") = {"user", "id", "field"}
# In the NEW code with legacy=True, tokenize("user_id field", legacy=True) = {"user", "id", "field"}
# So score_entry should match on "user", "id", "field" individually, not "user_id"
entry = {"title": "user_id field mapping", "tags": set(), "category": "DECISION", "path": "test.json", "raw": ""}
for prompt_word in ["user", "id", "field", "user_id"]:
    old = old_score_entry({prompt_word}, entry)
    new = score_entry({prompt_word}, entry)
    check(f"compound title, prompt='{prompt_word}': old={old}, new={new}", old, new)

print("\n=== A4 Results ===")
for r in results:
    print(r)
print(f"\nTotal: {PASS} passed, {FAIL} failed")
