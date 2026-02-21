from pathlib import Path
import json

def test_logic():
    initial = [
        {"path": "good1.json", "score": -10},
        {"path": "bad.json", "score": -9}, # Simulates out of bounds
        {"path": "retired.json", "score": -8},
        {"path": "unchecked.json", "score": -7}, # Beyond top_k_paths
    ]
    top_k_paths = 3
    
    # Simulate the loop
    for result in initial[:top_k_paths]:
        if result["path"] == "bad.json":
            # Simulate ValueError
            result["body_bonus"] = 0
            continue
            
        if result["path"] == "retired.json":
            result["_retired"] = True
            result["body_bonus"] = 0
            continue
            
        result["body_bonus"] = 2
        
    initial = [r for r in initial if not r.get("_retired")]
    for r in initial:
        r["score"] = r["score"] - r.get("body_bonus", 0)
        
    print(json.dumps(initial, indent=2))

test_logic()
