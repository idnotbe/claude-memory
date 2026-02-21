#!/usr/bin/env python3
"""A1: Regex adversarial inputs against _COMPOUND_TOKEN_RE"""
import sys, os, time, re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))
from memory_retrieve import _COMPOUND_TOKEN_RE, _LEGACY_TOKEN_RE, tokenize, STOP_WORDS

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
        results.append(f"  FAIL: {label} -- expected={expected!r}, actual={actual!r}")

# --- Pure regex tests (findall on lowered input) ---
def regex_test(label, text, expected):
    actual = _COMPOUND_TOKEN_RE.findall(text.lower())
    check(label, expected, actual)

print("=== A1: _COMPOUND_TOKEN_RE Adversarial Inputs ===\n")

# Basic delimiters
regex_test("only underscores '___'", "___", [])
regex_test("only dots '...'", "...", [])
regex_test("only hyphens '---'", "---", [])

# Trailing/leading delimiters
regex_test("trailing hyphen 'a-'", "a-", ["a"])
regex_test("leading hyphen '-a'", "-a", ["a"])
regex_test("trailing dot 'a.'", "a.", ["a"])
regex_test("leading dot '.a'", ".a", ["a"])
regex_test("trailing underscore 'a_'", "a_", ["a"])
regex_test("leading underscore '_a'", "_a", ["a"])

# Long compound
regex_test("very long compound 'a_b_c_d_e_f_g_h_i_j_k'",
           "a_b_c_d_e_f_g_h_i_j_k", ["a_b_c_d_e_f_g_h_i_j_k"])

# Extremely long single word (performance check)
t0 = time.monotonic()
result = _COMPOUND_TOKEN_RE.findall("a" * 100000)
elapsed = time.monotonic() - t0
check("100K 'a' chars -- single token", ["a" * 100000], result)
check(f"100K 'a' chars -- time < 1s (was {elapsed:.4f}s)", True, elapsed < 1.0)

# Even longer compound with delimiters
long_compound = "_".join(["ab"] * 50000)  # 50K segments
t0 = time.monotonic()
result = _COMPOUND_TOKEN_RE.findall(long_compound.lower())
elapsed = time.monotonic() - t0
check(f"100K compound segments -- time < 2s (was {elapsed:.4f}s)", True, elapsed < 2.0)
check("100K compound segments -- single token", 1, len(result))

# Unicode inputs (these chars are outside [a-z0-9], should be dropped)
regex_test("unicode 'uber_wert' (u-umlaut stripped)", "über_wert", ["er_wert"])
regex_test("unicode 'cafe.latte' (accent stripped)", "café.latte", ["caf", "latte"])
regex_test("unicode 'naive-test' (diaeresis stripped)", "naïve-test", ["na", "ve-test"])

# Mixed case (lowered before regex)
actual_mc = _COMPOUND_TOKEN_RE.findall("CamelCase_test".lower())
check("mixed case 'CamelCase_test' lowered", ["camelcase_test"], actual_mc)

# Numbers only
regex_test("numbers '12345'", "12345", ["12345"])
regex_test("numbers '1_2_3'", "1_2_3", ["1_2_3"])
regex_test("numbers '1.2.3'", "1.2.3", ["1.2.3"])

# Consecutive delimiters
regex_test("consecutive dots 'a..b'", "a..b", ["a..b"])
regex_test("consecutive underscores 'a__b'", "a__b", ["a__b"])
regex_test("consecutive hyphens 'a--b'", "a--b", ["a--b"])
regex_test("mixed delimiters 'a._-b'", "a._-b", ["a._-b"])

# Edge: single char
regex_test("single char 'a'", "a", ["a"])
regex_test("single digit '1'", "1", ["1"])

# Delimiters at boundaries of multi-segment
regex_test("'a_b_'", "a_b_", ["a_b"])
regex_test("'_a_b'", "_a_b", ["a_b"])
regex_test("'.a.b.'", ".a.b.", ["a.b"])

# Empty
regex_test("empty string", "", [])

# Special characters between compound parts
regex_test("'a@b'", "a@b", ["a", "b"])
regex_test("'a b'", "a b", ["a", "b"])
regex_test("'a\\nb'", "a\nb", ["a", "b"])

# Now test through tokenize() which adds stop-word + len>1 filter
print("\n=== A1b: tokenize() with compound mode ===\n")

def tok_test(label, text, expected_set, legacy=False):
    actual = tokenize(text, legacy=legacy)
    check(label, expected_set, actual)

tok_test("'___' through tokenize", "___", set())
tok_test("'a-' single char filtered", "a-", set())  # 'a' has len 1
tok_test("'ab-' trailing delim", "ab-", {"ab"})
tok_test("unicode 'uber_wert'", "über_wert", set())  # 'er_wert' len>1 but check
# Actually er_wert should match: regex gives ['er_wert'], len('er_wert')=7>1, not in STOP_WORDS
tok_test("unicode 'uber_wert' (corrected)", "über_wert", {"er_wert"})

# Check that stop words are filtered
tok_test("stop words only", "the is a was", set())
tok_test("stop words + real word", "the authentication", {"authentication"})

# Check 'id' -- len=2, > 1 -- should be kept unless stop word
check("'id' not in STOP_WORDS", False, "id" in STOP_WORDS)
tok_test("'id' preserved in tokenize", "user_id field", {"user_id", "field"}, legacy=False)
tok_test("'id' preserved in legacy", "user_id field", {"user", "id", "field"}, legacy=True)

# 'as', 'am', 'us', 'vs' are in STOP_WORDS
for sw in ["as", "am", "us", "vs"]:
    check(f"'{sw}' is stop word", True, sw in STOP_WORDS)

print("\n=== A1 Results ===")
for r in results:
    print(r)
print(f"\nTotal: {PASS} passed, {FAIL} failed")
