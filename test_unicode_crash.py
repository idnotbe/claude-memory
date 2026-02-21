import sys
from pathlib import Path
from hooks.scripts.memory_retrieve import check_recency

Path("test_invalid.json").write_bytes(b'{"content": "hello \xff"}')

try:
    check_recency(Path("test_invalid.json"))
    print("Success")
except Exception as e:
    print(f"Crash: {type(e).__name__} - {e}")

Path("test_invalid.json").unlink()
