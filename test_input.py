import sys
import os

def check(input_path):
    resolved = os.path.realpath(input_path)
    in_staging = "/.claude/memory/.staging/" in resolved
    print(f"Path: {input_path} | Resolved: {resolved} | In Staging: {in_staging}")

check("/tmp/.memory-write-pending.json")
check("/home/idnotbe/projects/claude-memory/.claude/memory/.staging/file.json")
