#!/usr/bin/env python3
"""A6: extract_body_text() truncation bypass attempts"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))
from memory_retrieve import extract_body_text

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

print("=== A6: extract_body_text() Truncation Bypass Attempts ===\n")

# Strategy 1: Single huge field
data = {"category": "decision", "content": {"context": "A" * 5000}}
result = extract_body_text(data)
check("single 5000-char field -> max 2000", True, len(result) <= 2000)
check("single 5000-char field -> exactly 2000", 2000, len(result))

# Strategy 2: Many large fields
data = {"category": "decision", "content": {
    "context": "A" * 1000,
    "decision": "B" * 1000,
    "rationale": "C" * 1000,
    "consequences": "D" * 1000,
}}
result = extract_body_text(data)
check("4 x 1000-char fields (4003 total with spaces) -> max 2000", True, len(result) <= 2000)
check("4 x 1000-char fields -> exactly 2000", 2000, len(result))

# Strategy 3: List fields with many items pushing past 2000 via join spaces
# runbook.steps can be a list of dicts, each containing strings
data = {"category": "runbook", "content": {
    "steps": [{"desc": "x" * 200} for _ in range(20)],  # 20 * 200 = 4000 chars + spaces
}}
result = extract_body_text(data)
check("20 dict items x 200 chars -> max 2000", True, len(result) <= 2000)

# Strategy 4: Extremely many small list items (spaces add up)
data = {"category": "runbook", "content": {
    "symptoms": ["x" for _ in range(10000)],  # 10K single-char items = 10K chars + 9999 spaces
}}
result = extract_body_text(data)
check("10K single-char list items -> max 2000", True, len(result) <= 2000)

# Strategy 5: All 7 session_summary fields maxed out
data = {"category": "session_summary", "content": {
    "goal": "G" * 1000,
    "outcome": "O" * 1000,
    "completed": ["C" * 500 for _ in range(10)],  # 5000 chars
    "in_progress": ["I" * 500 for _ in range(10)],
    "blockers": ["B" * 500 for _ in range(10)],
    "next_actions": ["N" * 500 for _ in range(10)],
    "key_changes": ["K" * 500 for _ in range(10)],
}}
result = extract_body_text(data)
check("session_summary with all 7 fields maxed -> max 2000", True, len(result) <= 2000)
check("session_summary maxed -> exactly 2000", 2000, len(result))

# Strategy 6: Unicode chars that might expand when joined
# Some unicode chars are multi-byte but still count as 1 in Python str
data = {"category": "decision", "content": {"context": "\U0001f600" * 3000}}  # emoji
result = extract_body_text(data)
check("3000 emoji chars -> truncated to 2000 chars (not bytes)", 2000, len(result))

# Strategy 7: Attempt to exceed 2000 via nested dict values
data = {"category": "runbook", "content": {
    "steps": [
        {f"key{i}": "v" * 100 for i in range(30)}  # 30 keys * 100 chars = 3000 per dict
        for _ in range(5)  # 5 dicts = 15000 chars
    ],
}}
result = extract_body_text(data)
check("5 dicts x 30 keys x 100 chars -> max 2000", True, len(result) <= 2000)

# Strategy 8: Verify truncation is by character count, not byte count
data = {"category": "decision", "content": {"context": "\u00e9" * 3000}}  # e-acute, 2 bytes in UTF-8
result = extract_body_text(data)
check("3000 two-byte chars -> truncated to 2000 chars", 2000, len(result))
check("truncated content is all e-acute", "\u00e9" * 2000, result)

# Strategy 9: Can we trick the function by adding extra fields not in BODY_FIELDS?
data = {"category": "decision", "content": {
    "context": "legit",
    "evil_extra_field": "X" * 5000,
    "another_fake": "Y" * 5000,
}}
result = extract_body_text(data)
check("extra fields not in BODY_FIELDS -- ignored", "legit", result)

# Strategy 10: Try to get output > 2000 via interaction between categories
# (Only one category's fields are extracted per call)
data = {"category": "decision", "content": {
    "context": "A" * 999,      # decision field
    "rule": "B" * 999,          # constraint field -- should be IGNORED
    "trigger": "C" * 999,       # runbook field -- should be IGNORED
}}
result = extract_body_text(data)
check("cross-category fields ignored", "A" * 999, result)

# Final: verify no way to get > 2000
import random
for i in range(20):
    category = random.choice(["decision", "runbook", "constraint", "tech_debt", "preference", "session_summary"])
    from memory_retrieve import BODY_FIELDS
    fields = BODY_FIELDS.get(category, [])
    content = {}
    for field in fields:
        choice = random.randint(0, 2)
        if choice == 0:
            content[field] = "x" * random.randint(0, 5000)
        elif choice == 1:
            content[field] = ["y" * random.randint(0, 500) for _ in range(random.randint(0, 20))]
        else:
            content[field] = [{"k": "z" * random.randint(0, 200)} for _ in range(random.randint(0, 10))]
    data = {"category": category, "content": content}
    result = extract_body_text(data)
    check(f"fuzz #{i+1} ({category}, {len(fields)} fields) -> max 2000", True, len(result) <= 2000)

print("\n=== A6 Results ===")
for r in results:
    print(r)
print(f"\nTotal: {PASS} passed, {FAIL} failed")
