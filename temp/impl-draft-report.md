# Implementation Report: hooks/scripts/memory_draft.py

## Summary

Created `hooks/scripts/memory_draft.py` -- a draft assembler script that builds complete, schema-compliant memory JSON from partial input files written by LLM subagents.

## File

`/home/idnotbe/projects/claude-memory/hooks/scripts/memory_draft.py` (267 lines)

## What It Does

- **CREATE**: Auto-populates `schema_version`, `category`, `id` (slugified from title), `created_at`, `updated_at`, `record_status`, `changes[]`, `times_updated=0` from a partial input containing only `title`, `tags`, `content`, `change_summary`.
- **UPDATE**: Reads existing memory from `--candidate-file`, preserves immutable fields (`created_at`, `schema_version`, `category`, `id`), unions `tags` and `related_files` (deduplicated), appends change entry, increments `times_updated`, shallow-merges content (top-level content keys overlaid).
- **Validates** assembled JSON against Pydantic models (via `build_memory_model()` from memory_write.py).
- **Outputs** draft to `.claude/memory/.staging/draft-<category>-<timestamp>-<pid>.json` with JSON result on stdout.

## Interface

```
python3 memory_draft.py \
  --action create|update \
  --category session_summary|decision|runbook|constraint|tech_debt|preference \
  --input-file <path-to-partial-json> \
  [--candidate-file <path-to-existing-memory>]  # required for update \
  [--root <memory-root-dir>]                     # default: .claude/memory
```

## Design Decisions

1. **Venv bootstrap first, then import**: The script does its own venv bootstrap before importing from `memory_write.py`. Since pydantic is available after bootstrap, `memory_write.py`'s top-level `os.execv` (which only fires when pydantic is missing) is safely skipped during import.

2. **No separate `memory_utils.py`**: Gemini suggested extracting shared utilities into a separate module. Rejected because: (a) the import-safety concern is addressed by bootstrap ordering, (b) creating a new file for 6 imports is scope creep, (c) it would require modifying memory_write.py.

3. **`/tmp/` input path allowed**: Per spec. Broader than memory_write.py's `.staging/`-only restriction. Added a comment explaining the rationale.

4. **`related_files` union on UPDATE**: Gemini flagged that pure shallow merge would lose `related_files` entries, causing memory_write.py to reject the draft (grow-only rule). Fixed by explicitly unioning `related_files` alongside `tags`.

5. **Draft filename includes PID**: `draft-<cat>-<ts>-<pid>.json` avoids collision if two drafts for the same category happen in the same second (vibe-check suggestion).

6. **Minimal merge logic**: Per spec, this script does assembly only. It does NOT duplicate memory_write.py's merge protections (grow-only tags enforcement, append-only changes enforcement). memory_write.py handles that on final save.

## Verification

- `python3 -m py_compile` passes
- All imports from memory_write.py work correctly
- Smoke tests passed for all 6 categories (CREATE)
- UPDATE tested: immutable fields preserved, tags unioned, related_files unioned, changes appended, times_updated incremented, content shallow-merged
- Error cases tested: bad input path, missing fields, invalid content, missing candidate file, path traversal

## External Feedback

- **Vibe Check**: Plan assessed as on-track. Suggested PID in filename (implemented) and confirming import safety (confirmed).
- **Gemini (via clink)**: Flagged 3 issues: (1) `/tmp/` security -- kept per spec, (2) import `os.execv` risk -- addressed by bootstrap ordering, (3) `related_files` merge gap -- fixed.
