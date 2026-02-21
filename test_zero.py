from pathlib import Path
import os
import signal
from hooks.scripts.memory_retrieve import check_recency

# Setup an alarm
def handler(signum, frame):
    print("Timeout! Blocked on read.")
    exit(1)
signal.signal(signal.SIGALRM, handler)

# Test /dev/zero
print("Testing /dev/zero...")
signal.alarm(2)
try:
    check_recency(Path("/dev/zero"))
    print("zero handled")
except Exception as e:
    print(f"zero err: {e}")

