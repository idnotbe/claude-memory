from pathlib import Path
import os
memory_root = Path.cwd() / ".claude" / "memory"
memory_root.mkdir(parents=True, exist_ok=True)
zero_sym = memory_root / "zero.json"
if not zero_sym.exists():
    os.symlink("/dev/zero", zero_sym)

try:
    zero_sym.resolve().relative_to(memory_root.resolve())
    print("Zero is relative!")
except ValueError:
    print("Zero is NOT relative!")

fifo_path = memory_root / "fifo.json"
if not fifo_path.exists():
    os.mkfifo(fifo_path)

try:
    fifo_path.resolve().relative_to(memory_root.resolve())
    print("FIFO is relative!")
except ValueError:
    print("FIFO is NOT relative!")

