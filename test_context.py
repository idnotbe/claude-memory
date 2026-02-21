from hooks.scripts.memory_judge import extract_recent_context
import json

with open("test_transcript.jsonl", "w") as f:
    f.write(json.dumps({"type": "user", "content": {"huge_dict": "data" * 100}}) + "\n")

print(extract_recent_context("test_transcript.jsonl"))
