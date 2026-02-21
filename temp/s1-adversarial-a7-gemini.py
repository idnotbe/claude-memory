#!/usr/bin/env python3
"""A7: Additional attack vectors from Gemini review
Tests: UnicodeDecodeError, future date poisoning, JSON bomb, FIFO blocking
"""
import sys, os, json, signal, stat, tempfile, shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))
from memory_retrieve import check_recency, extract_body_text, _sanitize_title, BODY_FIELDS

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

print("=== A7: Gemini-Suggested Attack Vectors ===\n")

# Create temp directory for file-based tests
tmpdir = Path(tempfile.mkdtemp(prefix="adversarial_"))

try:
    # --- A7.1: UnicodeDecodeError in check_recency ---
    print("--- A7.1: UnicodeDecodeError ---")

    # Write a file with invalid UTF-8 bytes
    invalid_utf8_path = tmpdir / "invalid_utf8.json"
    invalid_utf8_path.write_bytes(b'{"content": "hello \xff\xfe invalid"}\n')

    try:
        is_retired, is_recent = check_recency(invalid_utf8_path)
        # If it doesn't crash, it handled the error gracefully
        check("check_recency with invalid UTF-8 -- no crash", True, True)
        check("check_recency with invalid UTF-8 -- returns (False, False)", (False, False), (is_retired, is_recent))
    except UnicodeDecodeError as e:
        check("check_recency with invalid UTF-8 -- CRASHED with UnicodeDecodeError", False, True)
        results.append(f"        Error: {e}")
    except Exception as e:
        check(f"check_recency with invalid UTF-8 -- unexpected error: {type(e).__name__}", False, True)
        results.append(f"        Error: {e}")

    # --- A7.2: Future date cache poisoning ---
    print("\n--- A7.2: Future Date Cache Poisoning ---")

    future_date = (datetime.now(timezone.utc) + timedelta(days=365*100)).isoformat()
    future_file = tmpdir / "future_date.json"
    future_file.write_text(json.dumps({
        "record_status": "active",
        "updated_at": future_date,
        "category": "decision",
        "content": {"context": "test"}
    }), encoding="utf-8")

    is_retired, is_recent = check_recency(future_file)
    # Future date: (now - future) gives negative days, negative <= 30 is True
    # So is_recent will be True -- this IS the bug Gemini found
    check("future date (100 years) -- is_retired", False, is_retired)
    # This SHOULD be False but will likely be True (bug)
    if is_recent:
        check("VULNERABILITY: future date grants permanent recency bonus", True, is_recent)
        results.append("        NOTE: Future-dated entry gets +1 recency score forever")
        results.append(f"        Date used: {future_date}")
    else:
        check("future date -- not recent (unexpectedly safe)", False, is_recent)

    # Test with date just 1 day in the future
    near_future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    nf_file = tmpdir / "near_future.json"
    nf_file.write_text(json.dumps({
        "record_status": "active",
        "updated_at": near_future
    }), encoding="utf-8")
    _, is_recent_nf = check_recency(nf_file)
    check("VULNERABILITY: 1-day-future date also grants recency", True, is_recent_nf)

    # --- A7.3: JSON bomb (large file) ---
    print("\n--- A7.3: JSON Bomb Size Check ---")

    # Create a moderately large JSON file (10MB) - not too large to avoid test slowness
    big_json_path = tmpdir / "json_bomb.json"
    big_data = {"record_status": "active", "updated_at": datetime.now(timezone.utc).isoformat(), "padding": "X" * (10 * 1024 * 1024)}
    big_json_path.write_text(json.dumps(big_data), encoding="utf-8")

    import time
    t0 = time.monotonic()
    is_retired, is_recent = check_recency(big_json_path)
    elapsed = time.monotonic() - t0
    check(f"10MB JSON file -- completed (no OOM)", True, True)
    check(f"10MB JSON file -- time < 5s (was {elapsed:.3f}s)", True, elapsed < 5.0)
    # Note: the real concern is multi-GB files, but we can't test that in CI

    # --- A7.4: FIFO blocking test ---
    print("\n--- A7.4: FIFO Blocking Test ---")

    fifo_path = tmpdir / "fifo_test"
    os.mkfifo(fifo_path)

    # Set alarm to detect blocking
    timed_out = False
    def alarm_handler(signum, frame):
        global timed_out
        timed_out = True
        raise TimeoutError("FIFO blocked")

    old_handler = signal.signal(signal.SIGALRM, alarm_handler)
    signal.alarm(3)  # 3 second timeout

    try:
        is_retired, is_recent = check_recency(fifo_path)
        signal.alarm(0)
        # If we get here without timeout, it means open() didn't block
        # This would happen if check_recency catches the right exception
        check("FIFO -- handled without blocking", True, True)
    except TimeoutError:
        signal.alarm(0)
        check("VULNERABILITY: FIFO blocks indefinitely on open()", True, True)
        results.append("        NOTE: check_recency blocks forever on FIFO file")
    except Exception as e:
        signal.alarm(0)
        check(f"FIFO -- error: {type(e).__name__}", True, True)
        results.append(f"        Error: {e}")

    signal.signal(signal.SIGALRM, old_handler)

    # --- A7.5: Mixed-case category in extract_body_text ---
    print("\n--- A7.5: Case Sensitivity in extract_body_text ---")

    # lowercase works
    data_lower = {"category": "decision", "content": {"context": "lower case works"}}
    check("lowercase category 'decision'", "lower case works", extract_body_text(data_lower))

    # UPPERCASE fails (BODY_FIELDS keys are lowercase)
    data_upper = {"category": "DECISION", "content": {"context": "upper case fails"}}
    result = extract_body_text(data_upper)
    if result == "":
        check("CONFIRMED: uppercase 'DECISION' returns empty (case-sensitive miss)", "", result)
    else:
        check("uppercase 'DECISION' somehow works", "upper case fails", result)

    # Mixed case fails too
    data_mixed = {"category": "Decision", "content": {"context": "mixed case fails"}}
    result_mixed = extract_body_text(data_mixed)
    check("CONFIRMED: mixed case 'Decision' returns empty", "", result_mixed)

    # --- A7.6: Verify UnicodeDecodeError inheritance ---
    print("\n--- A7.6: Exception Hierarchy Check ---")
    check("UnicodeDecodeError is ValueError subclass", True, issubclass(UnicodeDecodeError, ValueError))
    check("UnicodeDecodeError is NOT OSError subclass", False, issubclass(UnicodeDecodeError, OSError))
    check("UnicodeDecodeError is NOT json.JSONDecodeError subclass", False, issubclass(UnicodeDecodeError, json.JSONDecodeError))
    # So `except (OSError, json.JSONDecodeError)` does NOT catch UnicodeDecodeError

    # Verify what check_recency actually catches
    # Line 166: except (OSError, json.JSONDecodeError):
    # UnicodeDecodeError is a subclass of ValueError, NOT caught by this handler

finally:
    # Cleanup
    shutil.rmtree(tmpdir, ignore_errors=True)

print("\n=== A7 Results ===")
for r in results:
    print(r)
print(f"\nTotal: {PASS} passed, {FAIL} failed")
