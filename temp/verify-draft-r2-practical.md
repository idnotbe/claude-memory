# Verification Round 2: Practical Real-World Testing

**Verifier:** verifier-r2-practical
**Date:** 2026-02-21
**Verdict:** PASS (all 5 scenarios + edge cases pass)

## Test Environment

- Memory root: `/tmp/memory-r2-test/.claude/memory/` (proper path structure required by memory_write.py)
- Scripts tested from: `/home/idnotbe/projects/claude-memory/hooks/scripts/`
- Pydantic version: 2.12.5

## Scenario Results

### Scenario 1: Full CREATE Pipeline (session_summary) -- PASS

Followed SKILL.md Phase 1 instructions literally:

| Step | Action | Result |
|------|--------|--------|
| 1 | Write new-info to `.staging/new-info-session_summary.txt` | PASS |
| 2 | Run `memory_candidate.py --new-info-file` | PASS - returned `pre_action=CREATE`, `structural_cud=CREATE` |
| 3 | Write partial JSON to `.staging/input-session_summary.json` | PASS |
| 4 | Run `memory_draft.py --action create --category session_summary` | PASS - produced valid draft |
| 5 | Run `memory_write.py --action create` | PASS - `{"status": "created"}` |
| 6 | Verify final file + index | PASS - file exists, index contains entry with tags |

The assembled draft was schema-complete with all auto-populated fields (schema_version, id, created_at, updated_at, record_status, changes, times_updated).

### Scenario 2: Full CREATE Pipeline (decision) -- PASS

Same pipeline flow for `decision` category with different content schema:

| Step | Result |
|------|--------|
| memory_candidate.py | PASS - `pre_action=CREATE` |
| memory_draft.py | PASS - produced valid draft with `alternatives[]`, `rationale[]`, `consequences[]` |
| memory_write.py | PASS - created decision file |
| Verification | PASS - file exists, index updated |

### Scenario 3: Full UPDATE Pipeline -- PASS

Built on Scenario 1 session_summary. Key verifications:

| Check | Result |
|-------|--------|
| `memory_candidate.py` finds existing entry | PASS - `structural_cud=UPDATE`, score=4 |
| `memory_draft.py --action update` preserves `created_at` | PASS |
| `memory_draft.py --action update` preserves `schema_version` | PASS |
| `memory_draft.py --action update` preserves `category` | PASS |
| Tags merged (union of old + new) | PASS - `[bugfix, memory-draft, pipeline, schema, testing]` |
| Changes appended (not replaced) | PASS - 2 entries (original + update) |
| `times_updated` incremented | PASS - 0 -> 1 |
| Content shallow-merged | PASS - `completed[]` grew from 3 to 6 items |
| OCC hash verified | PASS - `memory_write.py` accepted the hash |
| Final file persisted | PASS |

### Scenario 4: --new-info-file with .env content -- PASS

- Wrote content mentioning `.env` to a file
- `memory_candidate.py --new-info-file` processed it without issues
- Both `--new-info` (inline) and `--new-info-file` produce identical output
- The file-based approach avoids Guardian bash scanning of the content

### Scenario 5: SKILL.md Walkthrough -- PASS

All 10 Phase 1 steps verified for actionability:

| Step | Instruction | Verdict |
|------|-------------|---------|
| 1 | Read context file | Clear path, has skip fallback |
| 2 | Write new-info via Write tool | Specific path + tool |
| 3 | Run memory_candidate.py | Verified command works |
| 4 | Parse JSON output | Exact fields listed |
| 5 | Determine action | Unambiguous decision tree |
| 6 | Write partial JSON input | Exact format + exclusion list |
| 7 | Run memory_draft.py | Both CREATE + UPDATE commands shown |
| 8 | Parse draft output | JSON format documented |
| 9 | DELETE path | Simple retire JSON |
| 10 | Report | Clear spec |

No ambiguity found. The MANDATE about Write tool is prominently placed.

## Edge Case Results

| Edge Case | Expected | Actual | Result |
|-----------|----------|--------|--------|
| Missing required fields in input | INPUT_ERROR | `Missing required fields in input: content, change_summary` | PASS |
| Update without --candidate-file | Error | `--candidate-file is required for update action` | PASS |
| Input from /tmp/ (broad allowance) | Allowed per spec | Allowed (then fails on content validation as expected) | PASS |
| Input outside /tmp/ and .staging/ | SECURITY_ERROR | `Input file must be in .claude/memory/.staging/ or /tmp/` | PASS |
| Path with `..` traversal | SECURITY_ERROR | `Input path must not contain '..' components` | PASS |

## Initial Finding: Test Setup Required .claude/memory/ Path

The first run attempt used `/tmp/memory-r2-test/` as memory root directly. `memory_write.py`'s `_resolve_memory_root()` function requires the path to contain `.claude/memory/` components -- this is a security feature. The fix was to use `/tmp/memory-r2-test/.claude/memory/` as the root, which mirrors real deployment. This is documented behavior and not a bug.

## Key Observations

1. **Pipeline works end-to-end**: The full CREATE and UPDATE flows (candidate -> draft -> write) work seamlessly.
2. **Separation of concerns is clean**: memory_draft.py handles assembly, memory_write.py handles enforcement. No duplication of merge protections.
3. **memory_draft.py output is always schema-valid**: Pydantic validation happens before writing the draft.
4. **The /tmp/ allowance in validate_input_path is intentional**: Per spec, memory_draft.py allows `/tmp/` since LLMs may use the Write tool to /tmp paths. memory_write.py is stricter (only .staging/).
5. **OCC works correctly**: The MD5 hash from the pre-update file was accepted by memory_write.py.

## Cleanup

All temp files at `/tmp/memory-r2-test/` were cleaned up after testing.
