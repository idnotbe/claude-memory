# S7 Docs Output -- CLAUDE.md Judge Documentation

## What Was Done

Updated `/home/idnotbe/projects/claude-memory/CLAUDE.md` with 5 targeted edits to document the new judge module.

## Edits Made

### 1. Architecture Table (line 18)
Updated UserPromptSubmit hook description to mention the optional LLM judge layer:
> "optional LLM judge layer filters false positives"

### 2. Key Files Table (after line 48)
Added new row for `memory_judge.py`:
> `| hooks/scripts/memory_judge.py | LLM-as-judge for retrieval verification (anti-position-bias, anti-injection) | stdlib only (urllib.request) |`

### 3. Config Architecture (line 63)
Added `retrieval.judge.*` keys to the script-read config list with all 7 sub-keys enumerated.

### 4. Security Considerations (new item #6)
Added entry documenting the judge's anti-injection defenses:
- `<memory_data>` XML tag boundaries
- System prompt data/instruction separation
- Write-side `<`/`>` sanitization
- Anti-position-bias via sha256 deterministic shuffle
- Graceful fallback on all errors

### 5. Quick Smoke Check
Added `python3 -m py_compile hooks/scripts/memory_judge.py` to the compile check list.

## Verification
- All scripts compile cleanly
- Documentation is consistent with actual implementation
