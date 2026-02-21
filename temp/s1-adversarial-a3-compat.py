#!/usr/bin/env python3
"""A3: tokenize() backward compat proof -- old vs new code path side by side"""
import sys, os, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))
from memory_retrieve import tokenize, STOP_WORDS, _LEGACY_TOKEN_RE

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

print("=== A3: tokenize() Backward Compatibility Proof ===\n")

# The OLD code path was:
#   _TOKEN_RE = re.compile(r"[a-z0-9]+")
#   def tokenize(text): return {w for w in _TOKEN_RE.findall(text.lower()) if w not in STOP_WORDS and len(w) > 1}
#
# The NEW code with legacy=True uses:
#   _LEGACY_TOKEN_RE = re.compile(r"[a-z0-9]+")
#   def tokenize(text, legacy=False): regex = _LEGACY_TOKEN_RE if legacy else _COMPOUND_TOKEN_RE; ...
#
# Verify these produce IDENTICAL results.

OLD_RE = re.compile(r"[a-z0-9]+")

# Note: The OLD code used len(w) > 1 (min length 2) but also the ORIGINAL STOP_WORDS
# Before Session 1, the STOP_WORDS didn't include "as", "am", "us", "vs"
# We need to check if that matters. Let's test with the CURRENT STOP_WORDS for both paths.
# The comparison is: does `legacy=True` in the new code behave identically to the old code
# (assuming STOP_WORDS is the same set)?

test_inputs = [
    "How does JWT authentication work?",
    "configure the user_id field for database",
    "React.FC component setup",
    "fix rate-limiting in API v2.0",
    "",
    "the is a",
    "a b c d e",
    "CamelCase_thing",
    "What about the session_summary category?",
    "memory_write.py validation schema",
    "pydantic v2 models",
    "FTS5 full-text search",
    "3-letter acronyms like JWT API SQL",
    "a" * 1000,
    "hello world this is a test of the system",
    "über café naïve résumé",
    "12345 67890",
    "user_id rate-limiting React.FC test_memory_retrieve.py",
    "   whitespace   around   words   ",
    "UPPERCASE AND lowercase MiXeD",
    "punctuation: hello, world! foo@bar.com (test) [brackets]",
]

print("--- Testing OLD regex (manual) vs NEW tokenize(legacy=True) ---\n")

for text in test_inputs:
    # OLD path (simulated)
    old_result = {w for w in OLD_RE.findall(text.lower()) if w not in STOP_WORDS and len(w) > 1}
    # NEW path
    new_result = tokenize(text, legacy=True)
    check(f"text={text[:60]!r}{'...' if len(text)>60 else ''}", old_result, new_result)
    if old_result != new_result:
        results.append(f"        OLD: {sorted(old_result)}")
        results.append(f"        NEW: {sorted(new_result)}")

# Verify the regex pattern itself is identical
check("OLD_RE pattern matches _LEGACY_TOKEN_RE pattern",
      OLD_RE.pattern, _LEGACY_TOKEN_RE.pattern)

print("\n=== A3 Results ===")
for r in results:
    print(r)
print(f"\nTotal: {PASS} passed, {FAIL} failed")
