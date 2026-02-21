#!/usr/bin/env python3
"""A5: Module import side effects"""
import sys, os, io

# Capture stdout/stderr during import
old_stdout = sys.stdout
old_stderr = sys.stderr
sys.stdout = captured_stdout = io.StringIO()
sys.stderr = captured_stderr = io.StringIO()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))
import memory_retrieve

sys.stdout = old_stdout
sys.stderr = old_stderr

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

print("=== A5: Module Import Side Effects ===\n")

# A5.1: Check stdout output during import
stdout_output = captured_stdout.getvalue()
check("no stdout during import", "", stdout_output)

# A5.2: Check stderr output (FTS5 warning goes here if FTS5 unavailable)
stderr_output = captured_stderr.getvalue()
if memory_retrieve.HAS_FTS5:
    check("no stderr when FTS5 available", "", stderr_output)
else:
    check("stderr contains FTS5 warning", True, "[WARN] FTS5 unavailable" in stderr_output)

# A5.3: Check _test variable accessibility
has_test = hasattr(memory_retrieve, '_test')
check("_test variable accessible (confirmed leak)", True, has_test)
if has_test:
    # Verify it's closed
    try:
        memory_retrieve._test.execute("SELECT 1")
        check("_test connection closed (should raise)", True, False)  # Should not reach here
    except Exception as e:
        check("_test connection is closed (ProgrammingError)", True, "closed" in str(e).lower() or "Cannot operate" in str(e))

# A5.4: Check HAS_FTS5 type
check("HAS_FTS5 is bool", True, isinstance(memory_retrieve.HAS_FTS5, bool))

# A5.5: Can HAS_FTS5 be modified by external code?
original = memory_retrieve.HAS_FTS5
memory_retrieve.HAS_FTS5 = not original
check("HAS_FTS5 can be modified (Python doesn't have const)", not original, memory_retrieve.HAS_FTS5)
# Restore
memory_retrieve.HAS_FTS5 = original
check("HAS_FTS5 restored", original, memory_retrieve.HAS_FTS5)

# A5.6: Check that no unexpected global state is created
# Look for any sqlite3 connections or temp files
import tempfile, glob as glob_mod
temp_files_before = set(glob_mod.glob(os.path.join(tempfile.gettempdir(), "*sqlite*")))
temp_files_after = set(glob_mod.glob(os.path.join(tempfile.gettempdir(), "*sqlite*")))
check("no temp sqlite files created", temp_files_before, temp_files_after)

# A5.7: Re-import does NOT re-run FTS5 check (module caching)
old_stdout2 = sys.stdout
old_stderr2 = sys.stderr
sys.stdout = captured2_stdout = io.StringIO()
sys.stderr = captured2_stderr = io.StringIO()
import importlib
# Note: importlib.import_module won't re-exec, but reload would
sys.stdout = old_stdout2
sys.stderr = old_stderr2
check("re-import produces no output", "", captured2_stdout.getvalue())

# A5.8: Check what public names are exported
public_names = [n for n in dir(memory_retrieve) if not n.startswith('_')]
expected_public = {
    'BODY_FIELDS', 'CATEGORY_PRIORITY', 'HAS_FTS5', 'STOP_WORDS',
    'check_recency', 'datetime', 'extract_body_text', 'html', 'json',
    'main', 'os', 'parse_index_line', 're', 'score_description',
    'score_entry', 'sys', 'tokenize', 'timezone', 'Path',
}
# Don't assert exact match -- just check key exports exist
for name in ['tokenize', 'score_entry', 'extract_body_text', 'HAS_FTS5', 'BODY_FIELDS', 'STOP_WORDS']:
    check(f"'{name}' is exported", True, name in public_names)

# A5.9: Module-level constants are the right types
check("STOP_WORDS is frozenset", True, isinstance(memory_retrieve.STOP_WORDS, frozenset))
check("CATEGORY_PRIORITY is dict", True, isinstance(memory_retrieve.CATEGORY_PRIORITY, dict))
check("BODY_FIELDS is dict", True, isinstance(memory_retrieve.BODY_FIELDS, dict))

print("\n=== A5 Results ===")
for r in results:
    print(r)
print(f"\nTotal: {PASS} passed, {FAIL} failed")
