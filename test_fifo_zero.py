from pathlib import Path
import os
import signal
from hooks.scripts.memory_retrieve import check_recency

# Setup an alarm
def handler(signum, frame):
    print("Timeout! Blocked on open/read.")
    exit(1)
signal.signal(signal.SIGALRM, handler)

# Test FIFO
fifo_path = Path("test_fifo")
if not fifo_path.exists():
    os.mkfifo(fifo_path)

print("Testing FIFO...")
signal.alarm(2)
try:
    check_recency(fifo_path)
    print("FIFO handled")
except Exception as e:
    print(f"FIFO err: {e}")

signal.alarm(0)

# Test /dev/zero
print("Testing /dev/zero...")
signal.alarm(2)
try:
    check_recency(Path("/dev/zero"))
    print("zero handled")
except Exception as e:
    print(f"zero err: {e}")

