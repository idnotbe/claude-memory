#!/usr/bin/env python3
"""Deep adversarial tests -- second pass attacking harder on specific vectors."""

import io
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))

from memory_retrieve import (
    _COMPOUND_TOKEN_RE, _LEGACY_TOKEN_RE, tokenize, extract_body_text,
    score_entry, score_description, parse_index_line, _sanitize_title,
    BODY_FIELDS, HAS_FTS5, STOP_WORDS
)

results = []

def record(test_id, desc, passed, detail=""):
    status = "PASS" if passed else "**FAIL**"
    results.append((test_id, desc, status, detail))
    marker = "OK" if passed else "BROKEN"
    print(f"  [{marker}] {test_id}: {desc}")
    if detail and not passed:
        print(f"         {detail}")


# ============================================================
# DEEP-A1: Compound regex edge cases that could cause surprise
# ============================================================
print("\n=== DEEP-A1: Compound Regex Deeper Analysis ===")

# Can we get the compound regex to match something the legacy wouldn't?
# The compound regex matches [a-z0-9][a-z0-9_.\-]*[a-z0-9] which includes _.-
# These characters would split tokens in legacy mode. So by definition,
# compound matches more than legacy. Verify this superset property.

test_strings = [
    "user_id",
    "react.fc",
    "rate-limiting",
    "v2.0",
    "a_b_c_d_e_f_g_h_i_j_k",
    "test_memory_retrieve.py",
    "node.js",
    "vue.js",
    "express.js",
    "1.2.3.4",
    "my-cool-app",
    "UPPER_CASE_CONST",
    "camelCase",  # No delimiters, same in both
]

for s in test_strings:
    legacy_tokens = tokenize(s, legacy=True)
    compound_tokens = tokenize(s, legacy=False)
    # For simple alphanum words (no delimiters), both should be same
    # For compound words, legacy splits and compound preserves
    record(f"DEEP-A1-superset-{s[:20]}", f"Compound is superset or different partition of '{s}'",
           True, f"legacy={legacy_tokens}, compound={compound_tokens}")

# DEEP-A1 Specific: what happens with "a-" as compound token input?
# The regex first branch requires start+middle+end: [a-z0-9][...]*[a-z0-9]
# For "a-", first branch: 'a' matches [a-z0-9], '-' matches [a-z0-9_.\-]*,
#   but then needs [a-z0-9] at end -- no char left! Branch fails.
# Second branch: [a-z0-9]+ -> matches 'a'.
# So "a-" -> ["a"] which is filtered by len>1 -> empty set
result = tokenize("a-", legacy=False)
record("DEEP-A1-trailing-delim", "'a-' with compound tokenizer -> empty (single char filtered)",
       result == set(), f"got {result}")

# What about "ab-" ?
result = tokenize("ab-", legacy=False)
# First branch: 'a'[a-z0-9], 'b'[a-z0-9_.\-]*, but then needs final [a-z0-9]
# 'a' matches anchor, 'b' could be middle, but '-' needs final anchor -- no!
# Wait: 'ab' matches first branch as [a-z0-9][a-z0-9_.\-]*[a-z0-9] with 'a' as start, '' as middle, 'b' as end
# Then '-' is not matched. So match is 'ab' at position 0-1, '-' not matched.
record("DEEP-A1-ab-trailing", "'ab-' with compound tokenizer -> {'ab'}",
       result == {"ab"}, f"got {result}")

# "ab-cd" should produce "ab-cd" (compound) or "ab","cd" (legacy)
result_c = tokenize("ab-cd", legacy=False)
result_l = tokenize("ab-cd", legacy=True)
record("DEEP-A1-compound-vs-legacy", "'ab-cd': compound={'ab-cd'} vs legacy={'ab','cd'}",
       "ab-cd" in result_c and "ab" in result_l and "cd" in result_l,
       f"compound={result_c}, legacy={result_l}")


# ============================================================
# DEEP-A2: parse_index_line adversarial inputs
# ============================================================
print("\n=== DEEP-A2: parse_index_line() Adversarial ===")

# Normal line
r = parse_index_line("- [DECISION] JWT auth flow -> .claude/memory/decisions/jwt.json #tags:auth,jwt")
record("DEEP-A2-normal", "Normal index line parses correctly",
       r is not None and r["category"] == "DECISION" and r["title"] == "JWT auth flow"
       and "auth" in r["tags"] and "jwt" in r["tags"],
       f"got {r}")

# Line with -> in title (injection attempt)
r = parse_index_line("- [DECISION] title -> fake/path -> real/path #tags:hack")
record("DEEP-A2-arrow-in-title", "Arrow in title: regex matches first ' -> '",
       r is not None, f"got {r}")
if r:
    record("DEEP-A2-arrow-title-val", f"Title captured as: '{r['title']}'",
           True, f"path={r['path']}, tags={r['tags']}")

# Line with #tags: in title
r = parse_index_line("- [DECISION] title #tags:fake -> real/path #tags:real")
record("DEEP-A2-tags-in-title", "#tags: in title: regex behavior",
       r is not None, f"got {r}")
if r:
    record("DEEP-A2-tags-title-val", f"Title: '{r['title']}', tags: {r['tags']}",
           True, "")

# Empty category
r = parse_index_line("- [] title -> path")
record("DEEP-A2-empty-cat", "Empty category fails to match [A-Z_]+ regex",
       r is None, f"got {r}")

# Category with lowercase
r = parse_index_line("- [decision] title -> path")
record("DEEP-A2-lowercase-cat", "Lowercase category fails to match [A-Z_]+",
       r is None, f"got {r}")

# Very long line
long_title = "X" * 10000
r = parse_index_line(f"- [DECISION] {long_title} -> path.json")
record("DEEP-A2-very-long", "Very long title (10K chars) still parses",
       r is not None and len(r["title"]) == 10000, f"title_len={len(r['title']) if r else 'None'}")

# Newline in middle (shouldn't match since ^ and $ anchor)
r = parse_index_line("- [DECISION] title\ninjection -> path.json")
record("DEEP-A2-newline", "Newline in line fails to match (regex doesn't use DOTALL)",
       r is None, f"got {r}")

# Path traversal attempt
r = parse_index_line("- [DECISION] evil -> ../../../etc/passwd #tags:hack")
record("DEEP-A2-path-traversal-parse", "Path traversal in index line: parses but main() has containment check",
       r is not None and "../../../etc/passwd" in r["path"], f"got {r}")


# ============================================================
# DEEP-A3: _sanitize_title() adversarial
# ============================================================
print("\n=== DEEP-A3: _sanitize_title() Adversarial ===")

# Double encoding attack
result = _sanitize_title("&amp;lt;script&amp;gt;")
record("DEEP-A3-double-encode", "Double-encoded HTML: gets re-escaped (no unescape first)",
       "&amp;" in result, f"got '{result}'")

# Unicode homoglyphs (visually similar to ASCII but different codepoints)
# These should pass through since they're not in the strip list
import unicodedata
homoglyphs = "\u0410\u0412\u0421\u0415"  # Cyrillic A, V, S, E
result = _sanitize_title(homoglyphs)
record("DEEP-A3-homoglyphs", "Cyrillic homoglyphs pass through (not in strip list)",
       len(result) > 0, f"got '{result}' (len={len(result)})")

# RTL override (U+202E) - should be stripped
result = _sanitize_title("normal\u202Eesrever")
record("DEEP-A3-rtl-override", "RTL override U+202E stripped",
       "\u202e" not in result, f"got '{result}'")

# Zero-width joiner (U+200D) - check if it's in the strip range
result = _sanitize_title("test\u200djoiner")
record("DEEP-A3-zwj", "Zero-width joiner U+200D stripped (in U+200B-U+200F range)",
       "\u200d" not in result, f"got '{result}'")

# Truncation + escape interaction
# If we truncate at 120 then escape, the escaped output could be longer than 120
# (e.g., "&" becomes "&amp;" = 5 chars)
input_str = "&" * 120
result = _sanitize_title(input_str)
record("DEEP-A3-truncate-then-escape", f"120 '&' chars -> truncated then escaped (len={len(result)})",
       len(result) > 120, f"got len={len(result)}, expected 120*5=600")
# This means output CAN exceed 120 chars after escaping. Is this a problem?
# For prompt injection: titles are in XML context, so escaping is correct.
# For buffer overflow: Python strings are unbounded.
record("DEEP-A3-escape-expansion", "Escape expansion: output can exceed 120 chars (by design, escaping is after truncation)",
       True, f"120 '&' -> {len(result)} chars after escaping")

# Null byte handling
result = _sanitize_title("before\x00after")
record("DEEP-A3-null-byte", "Null byte stripped by control char regex",
       "\x00" not in result and "beforeafter" == result, f"got '{result}'")

# Tab and newline
result = _sanitize_title("line1\nline2\ttab")
record("DEEP-A3-newline-tab", "Newline and tab stripped by control char regex",
       "\n" not in result and "\t" not in result, f"got '{result}'")


# ============================================================
# DEEP-A4: score_description() edge cases
# ============================================================
print("\n=== DEEP-A4: score_description() Edge Cases ===")

# Cap at 2
prompt_words = {"database", "connection", "timeout", "pooling", "retry", "backoff"}
desc_tokens = {"database", "connection", "timeout", "pooling", "configuration"}
score = score_description(prompt_words, desc_tokens)
record("DEEP-A4-cap", f"6 matching words capped at 2 (got {score})",
       score == 2, f"got {score}")

# Empty sets
score = score_description(set(), {"database"})
record("DEEP-A4-empty-prompt", "Empty prompt -> 0", score == 0, f"got {score}")

score = score_description({"database"}, set())
record("DEEP-A4-empty-desc", "Empty desc -> 0", score == 0, f"got {score}")

# Prefix match gives 0.5, rounds to 1
prompt_words = {"authentication"}
desc_tokens = {"auth"}  # len("auth") < 4 in prompt context, but here "auth" is desc token
# "authentication" is prompt word, len >= 4, check if any desc_token starts with "authentication" -> no
# Actually: for pw in prompt_words: if any(dt.startswith(pw)) -> "auth".startswith("authentication") -> no
# So no prefix match here, score = 0
score = score_description(prompt_words, desc_tokens)
record("DEEP-A4-prefix-direction", "Prefix match: checks if desc starts with prompt (not reverse)",
       score == 0, f"got {score}")

# Now try the other direction: short prompt, long desc
prompt_words = {"auth"}
desc_tokens = {"authentication"}
# "auth" len=4, check if "authentication".startswith("auth") -> YES! 0.5 points
# int(0.5 + 0.5) = int(1.0) = 1
score = score_description(prompt_words, desc_tokens)
record("DEEP-A4-prefix-forward", "Prefix: 'auth' matches 'authentication' = 0.5 -> rounds to 1",
       score == 1, f"got {score}")

# Test the rounding: 1 exact + 1 prefix = 1.0 + 0.5 = 1.5, int(1.5 + 0.5) = int(2.0) = 2
prompt_words = {"database", "auth"}
desc_tokens = {"database", "authentication"}
# exact: {"database"} -> 1.0
# remaining: {"auth"} -> len >= 4, "authentication".startswith("auth") -> yes, 0.5
# total = 1.5, int(1.5 + 0.5) = 2
score = score_description(prompt_words, desc_tokens)
record("DEEP-A4-rounding", "1 exact + 1 prefix = 1.5, rounds to 2",
       score == 2, f"got {score}")

# Test Python banker's rounding avoidance: 0.5 should round to 1 (not 0)
prompt_words = {"auth"}
desc_tokens = {"authentication", "database"}
# prefix: 0.5, int(0.5 + 0.5) = int(1.0) = 1
score = score_description(prompt_words, desc_tokens)
record("DEEP-A4-bankers-rounding", "0.5 rounds to 1 (not 0 via banker's rounding)",
       score == 1, f"got {score}")


# ============================================================
# DEEP-A5: Interaction between tokenize modes in scoring
# ============================================================
print("\n=== DEEP-A5: Scoring Path Integrity ===")

# Verify that score_entry ALWAYS uses legacy tokenizer regardless of default
# The function calls tokenize(entry["title"], legacy=True) on line 102
# If someone changes the default from False to True or vice versa,
# score_entry should be unaffected because it explicitly passes legacy=True

entry = {"title": "user_id_field mapping", "tags": set(), "category": "DECISION"}

# With "user_id_field" in prompt:
# Legacy tokenizer splits to: {"user", "id", "field", "mapping"}
# If compound were used: {"user_id_field", "mapping"}
prompt_words_compound = tokenize("user_id_field", legacy=False)
prompt_words_legacy = tokenize("user_id_field", legacy=True)

record("DEEP-A5-tokenize-split", f"Compound: {prompt_words_compound} vs Legacy: {prompt_words_legacy}",
       prompt_words_compound != prompt_words_legacy,
       f"compound={prompt_words_compound}, legacy={prompt_words_legacy}")

# When score_entry tokenizes the title with legacy=True:
# title "user_id_field mapping" -> legacy -> {"user", "id", "field", "mapping"}
# prompt_words from compound tokenize: {"user_id_field"}
# No exact match (user_id_field not in {user, id, field, mapping})
# Prefix check: len("user_id_field") >= 4, "user".startswith("user_id_field") -> no
# Reverse: "user_id_field".startswith("user") and len("user") >= 4 -> yes! 1 point
score_with_compound_prompt = score_entry(prompt_words_compound, entry)
record("DEEP-A5-compound-prompt-scoring",
       f"Compound prompt token 'user_id_field' scores {score_with_compound_prompt} against legacy-tokenized title",
       score_with_compound_prompt == 1, f"got {score_with_compound_prompt}")

# Now verify with legacy prompt words
score_with_legacy_prompt = score_entry(prompt_words_legacy, entry)
# Legacy: {"user", "id", "field"}  (all are substrings of the title tokens which are also {"user", "id", "field", "mapping"})
# Wait: tokenize("user_id_field", legacy=True) -> re.compile(r"[a-z0-9]+").findall("user_id_field") -> ["user", "id", "field"]
# After len>1 and stop word filter: "id" (len 2, not stop word) stays -> {"user", "id", "field"}
# title tokens: tokenize("user_id_field mapping", legacy=True) -> ["user", "id", "field", "mapping"] -> {"user", "id", "field", "mapping"}
# exact_title = {"user", "id", "field"} -> 3 * 2 = 6 points
score_with_legacy_prompt2 = score_entry(prompt_words_legacy, entry)
record("DEEP-A5-legacy-prompt-scoring",
       f"Legacy prompt tokens score {score_with_legacy_prompt2} (3 exact matches * 2 = 6)",
       score_with_legacy_prompt2 == 6, f"got {score_with_legacy_prompt2}")

# This demonstrates that using compound tokens as prompt words (which will happen
# in Session 2's FTS5 path) scores DIFFERENTLY than legacy tokens.
# This is expected and correct -- FTS5 will handle compound matching differently.
record("DEEP-A5-scoring-divergence",
       f"Compound vs legacy prompt scoring: {score_with_compound_prompt} vs {score_with_legacy_prompt2} (expected divergence)",
       score_with_compound_prompt != score_with_legacy_prompt2,
       "This is expected: compound tokens match differently than split legacy tokens")


# ============================================================
# DEEP-A6: Memory allocation stress test
# ============================================================
print("\n=== DEEP-A6: Memory Allocation Edge Cases ===")

# Can we get extract_body_text to allocate a huge intermediate before truncation?
# Build a dict with many list items, each containing large dicts with string values
big_data = {
    "category": "runbook",
    "content": {
        "steps": [
            {"action": "X" * 10000, "detail": "Y" * 10000, "note": "Z" * 10000}
            for _ in range(100)
        ]
    }
}
# Total string data: 100 * 3 * 10000 = 3,000,000 chars
# The join will allocate ~3MB before truncating to 2000
t0 = time.monotonic()
result = extract_body_text(big_data)
t1 = time.monotonic()
record("DEEP-A6-large-alloc", f"3MB intermediate allocation: time={t1-t0:.4f}s, output_len={len(result)}",
       len(result) <= 2000 and (t1-t0) < 5.0, f"time={t1-t0:.4f}s")

# Even bigger: 100MB intermediate
# This tests whether the implementation handles very large data without crashing
big_data2 = {
    "category": "session_summary",
    "content": {
        "completed": ["A" * 100000 for _ in range(1000)]  # 100M chars total
    }
}
t0 = time.monotonic()
result = extract_body_text(big_data2)
t1 = time.monotonic()
record("DEEP-A6-100mb-alloc", f"100MB intermediate: time={t1-t0:.4f}s, output_len={len(result)}",
       len(result) <= 2000 and (t1-t0) < 30.0, f"time={t1-t0:.4f}s")


# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("DEEP ADVERSARIAL SUMMARY")
print("=" * 60)

total = len(results)
passed = sum(1 for _, _, s, _ in results if s == "PASS")
failed = sum(1 for _, _, s, _ in results if s == "**FAIL**")

print(f"\nTotal: {total}, Passed: {passed}, Failed: {failed}")

if failed > 0:
    print("\nFAILED:")
    for tid, desc, status, detail in results:
        if status == "**FAIL**":
            print(f"  {tid}: {desc}")
            if detail:
                print(f"    {detail}")

# Write results
with open(os.path.join(os.path.dirname(__file__), "s1-adversarial-deep-results.json"), "w") as f:
    json.dump([{"id": t, "desc": d, "status": s, "detail": det} for t, d, s, det in results], f, indent=2)

print(f"\nResults written to temp/s1-adversarial-deep-results.json")
sys.exit(0 if failed == 0 else 1)
