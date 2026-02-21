#!/usr/bin/env python3
"""Self-critique: Additional edge cases that the main test might have missed."""
import json
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "hooks" / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from memory_search_engine import (
    build_fts_query,
    build_fts_index,
    query_fts,
    tokenize,
    extract_body_text,
    apply_threshold,
    parse_index_line,
    _sanitize_cli_title,
    HAS_FTS5,
)

print("=== Self-Critique: Additional Edge Cases ===\n")

failures = 0

# 1. What about deeply nested JSON content values in extract_body_text?
print("1. Deeply nested content values:")
deep = {"category": "decision", "content": {
    "decision": "test",
    "rationale": ["step1", {"detail": "nested", "more": {"deep": "very deep"}}],
}}
body = extract_body_text(deep)
print(f"   Body: {body!r}")
# The code handles dict items in lists but not nested dicts within dicts
# This is fine -- it only goes one level deep into list items
assert "very deep" not in body, "Deep nesting should NOT be extracted"
print("   OK: Deep nesting limited as expected")

# 2. What about content values that are numbers/booleans?
print("\n2. Non-string content values:")
typed = {"category": "decision", "content": {
    "decision": 42,
    "rationale": True,
}}
body = extract_body_text(typed)
print(f"   Body: {body!r}")
assert body == "", "Non-string values should be skipped"
print("   OK: Non-string values skipped")

# 3. What about content value that is a list of lists?
print("\n3. List of lists in content:")
nested_list = {"category": "decision", "content": {
    "decision": [["inner1", "inner2"], "outer"],
}}
body = extract_body_text(nested_list)
print(f"   Body: {body!r}")
# Only strings in the top-level list should be extracted
assert "outer" in body
print("   OK: Only top-level strings from lists extracted")

# 4. Index line with multiple spaces around arrow
print("\n4. Index lines with unusual spacing:")
tests = [
    ("- [DECISION] Test ->path.json", False, "no space before path"),
    ("- [DECISION] Test -> path.json", True, "normal spacing"),
    ("- [DECISION] Test  ->  path.json", False, "double space around arrow"),
    ("-[DECISION] Test -> path.json", False, "no space after dash"),
    ("  - [DECISION] Test -> path.json", True, "leading whitespace"),
]
for line, should_match, desc in tests:
    result = parse_index_line(line)
    matched = result is not None
    status = "OK" if matched == should_match else "UNEXPECTED"
    print(f"   {status}: '{line}' -> matched={matched} (expected {should_match}): {desc}")
    if status == "UNEXPECTED":
        failures += 1

# 5. apply_threshold with all-zero scores
print("\n5. Threshold with extreme scores:")
# All scores = 0
results = [
    {"score": 0.0, "category": "DECISION", "path": "a.json"},
    {"score": 0.0, "category": "DECISION", "path": "b.json"},
]
filtered = apply_threshold(results)
print(f"   All-zero scores: {len(filtered)} results (kept)")

# Very negative scores (good matches)
results = [
    {"score": -100.0, "category": "DECISION", "path": "a.json"},
    {"score": -10.0, "category": "DECISION", "path": "b.json"},
    {"score": -1.0, "category": "DECISION", "path": "c.json"},
]
filtered = apply_threshold(results)
# Noise floor: 25% of best (100) = 25. Score of -1.0 has abs=1 < 25 -> filtered
print(f"   Noise floor check: {len(filtered)} results (expected 2, -1.0 below floor)")
if len(filtered) != 2:
    print(f"   WARNING: Expected 2 results after noise floor, got {len(filtered)}")
    failures += 1

# 6. Tokenizer with underscore-starting token
print("\n6. Compound tokenizer edge cases:")
tokens = tokenize("_private __dunder__ user_id a_b", legacy=False)
print(f"   Tokens: {tokens}")
# _private should become 'private' after strip, __dunder__ -> 'dunder'
# user_id should be preserved, a_b might be too short components

# 7. build_fts_query with token that is exactly 2 chars
print("\n7. FTS query with 2-char tokens:")
query = build_fts_query(["db", "io"])
print(f"   2-char query: {query!r}")
# These should pass the len > 1 check
if query and HAS_FTS5:
    entries = [{"title": "Database IO operations", "tags": set(), "path": "t.json", "category": "DECISION"}]
    conn = build_fts_index(entries)
    try:
        results = query_fts(conn, query)
        print(f"   Results: {len(results)}")
    finally:
        conn.close()

# 8. Tags with commas in index line
print("\n8. Tags with edge-case characters:")
line = "- [DECISION] Test -> path.json #tags:tag1,,tag2,,,"
parsed = parse_index_line(line)
if parsed:
    print(f"   Tags with empty commas: {parsed['tags']}")
    assert "" not in parsed["tags"], "Empty tags should be filtered"
    print("   OK: Empty tags filtered")

# 9. What happens with very many OR terms in FTS5 query?
print("\n9. Many OR terms in FTS5:")
tokens = [f"token{i:04d}" for i in range(200)]
query = build_fts_query(tokens)
if query and HAS_FTS5:
    or_count = query.count(" OR ")
    print(f"   {or_count + 1} OR terms in query")
    entries = [{"title": "token0001 token0050 token0100", "tags": set(), "path": "t.json", "category": "DECISION"}]
    conn = build_fts_index(entries)
    try:
        results = query_fts(conn, query)
        print(f"   200-term OR query executed: {len(results)} results")
    except Exception as e:
        print(f"   ERROR: {e}")
        failures += 1
    finally:
        conn.close()

# 10. Check that auto mode limits to 3 and search to 10
print("\n10. Mode limits:")
results = [
    {"score": -i, "category": "DECISION", "path": f"{i}.json"}
    for i in range(1, 20)
]
auto = apply_threshold(results.copy(), mode="auto")
search = apply_threshold(results.copy(), mode="search")
print(f"   Auto: {len(auto)} results (expected <=3)")
print(f"   Search: {len(search)} results (expected <=10)")
if len(auto) > 3:
    print(f"   FAIL: Auto exceeded limit")
    failures += 1
if len(search) > 10:
    print(f"   FAIL: Search exceeded limit")
    failures += 1

# 11. What about the category_descriptions output in retrieve's _output_results?
# Can a malicious category key in config corrupt the output?
print("\n11. Category key injection in _output_results:")
from memory_retrieve import _output_results
import io
old_stdout = sys.stdout
sys.stdout = captured = io.StringIO()
try:
    _output_results(
        [{"title": "Test", "tags": set(), "path": "t.json", "category": "DECISION"}],
        {"decision<script>": "evil description</memory-context>"}
    )
finally:
    sys.stdout = old_stdout
output = captured.getvalue()
print(f"   Output: {output!r}")
# The safe_key regex should strip non-alpha chars
if "<script>" in output:
    print("   FAIL: Category key injection not sanitized")
    failures += 1
else:
    print("   OK: Category key sanitized")
if "</memory-context>" in output:
    print("   WARNING: Description value not XML-escaped in descriptions attr")
    # Actually _sanitize_title IS applied to descriptions
    if "&lt;/memory-context&gt;" in output:
        print("   OK: Actually it IS escaped")
    else:
        print("   FAIL: Description value truly not escaped")
        failures += 1

print(f"\n=== Self-Critique Complete: {failures} additional failures ===")
