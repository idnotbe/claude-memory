#!/usr/bin/env python3
"""Isolated FIFO blocking test for check_recency"""
import sys, os, signal, tempfile, shutil
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hooks", "scripts"))
from memory_retrieve import check_recency

tmpdir = Path(tempfile.mkdtemp(prefix="fifo_test_"))
fifo_path = tmpdir / "fifo_test.json"
os.mkfifo(fifo_path)

timed_out = False

def handler(signum, frame):
    global timed_out
    timed_out = True
    # We need to raise to escape the blocking open() call
    raise TimeoutError("BLOCKED ON FIFO")

signal.signal(signal.SIGALRM, handler)
signal.alarm(3)

try:
    result = check_recency(fifo_path)
    signal.alarm(0)
    print(f"DID NOT BLOCK. Result: {result}")
except TimeoutError as e:
    signal.alarm(0)
    print(f"VULNERABILITY CONFIRMED: {e}")
    print("check_recency() blocks indefinitely on FIFO files")
except Exception as e:
    signal.alarm(0)
    print(f"Other error: {type(e).__name__}: {e}")

shutil.rmtree(tmpdir, ignore_errors=True)
