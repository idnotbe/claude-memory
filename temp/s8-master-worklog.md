# Session 8 Master Worklog -- Phase 3b-3c: Judge Tests + Search Judge

**Date:** 2026-02-22
**Status:** IN PROGRESS
**Team:** s8-team

---

## Scope (from rd-08-final-plan.md, Session 8 checklist)

### Phase 3b: Judge Tests (~200 LOC, 15 tests)
Create `tests/test_memory_judge.py`:
1. `test_call_api_success` (mock urllib response)
2. `test_call_api_no_key` (returns None)
3. `test_call_api_timeout` (returns None)
4. `test_call_api_http_error` (returns None)
5. `test_format_judge_input_shuffles` (deterministic, cross-run stable)
6. `test_format_judge_input_with_context` (includes conversation)
7. `test_parse_response_valid_json` (happy path)
8. `test_parse_response_with_preamble` (markdown wrapper)
9. `test_parse_response_string_indices` (coercion)
10. `test_parse_response_nested_braces` (robust extraction)
11. `test_parse_response_invalid` (returns None)
12. `test_judge_candidates_integration` (mock API, end-to-end)
13. `test_judge_candidates_api_failure` (returns None for fallback)
14. `test_extract_recent_context` (correct transcript parsing)
15. `test_extract_recent_context_empty` (missing file)

### Phase 3c: On-Demand Search Judge (~0.5 day)
1. Update `/memory:search` skill (SKILL.md) to spawn Task subagent for judgment
2. Lenient mode: wider candidate acceptance
3. Subagent prompt: "Which of these memories are RELATED to the user's query? Be inclusive."

---

## Key Files (inputs for teammates)

| File | Purpose |
|------|---------|
| `hooks/scripts/memory_judge.py` | Source code to test (254 LOC) |
| `hooks/scripts/memory_retrieve.py` | Judge integration point |
| `skills/memory-search/SKILL.md` | Current search skill (to update) |
| `tests/conftest.py` | Test fixtures |
| `research/rd-08-final-plan.md` | Full plan with specs |

## Architecture Notes for Teammates

### memory_judge.py API:
- `call_api(system, user_msg, model, timeout)` -> str | None
- `extract_recent_context(transcript_path, max_turns)` -> str
- `format_judge_input(user_prompt, candidates, conversation_context)` -> (str, list[int])
- `parse_response(text, order_map, n_candidates)` -> list[int] | None
- `_extract_indices(display_indices, order_map, n_candidates)` -> list[int]
- `judge_candidates(user_prompt, candidates, transcript_path, model, timeout, include_context, context_turns)` -> list[dict] | None

### Key behaviors to test:
- Anti-position-bias: sha256-seeded shuffle is deterministic across runs
- Boolean rejection: `_extract_indices` rejects `True`/`False`
- Transcript path validation: rejects paths outside `/tmp/` and `$HOME/`
- html.escape on titles/categories in format_judge_input
- Deque with maxlen for transcript parsing

### Search Judge (Phase 3c):
- SKILL.md should instruct Claude to spawn a Task subagent (haiku model)
- Subagent evaluates search results with LENIENT mode (be inclusive)
- If subagent fails, show unfiltered results

---

## Team Assignment

| Teammate | Role | Task |
|----------|------|------|
| judge-test-writer | Implementation | Write test_memory_judge.py |
| search-judge-impl | Implementation | Update SKILL.md with subagent judge |
| v1-correctness | V1 Review | Correctness + coverage review |
| v1-security | V1 Review | Security + injection review |
| v1-adversarial | V1 Review | Adversarial edge cases |
| v2-quality | V2 Review | Code quality + patterns |
| v2-integration | V2 Review | Integration + compatibility |
| v2-adversarial | V2 Review | Fresh adversarial review |

---

## Progress Log

- [x] Phase 3b: Judge tests written (51 tests, 649 LOC by judge-test-writer)
- [x] Phase 3c: Search skill updated (73 new lines by search-judge-impl)
- [x] Tests pass: 734 passed in 29.78s (initial run)
- [x] V1 verification complete (3 reviewers: correctness, security, adversarial)
- [x] V1 fixes applied: 8 edits (H1,H2 correctness, M1,M2,M6 coverage, H2 security breakout, L2 traversal, L3 negative indices)
- [x] Post-V1 tests pass: 740 passed in 31.32s
- [x] V2 verification complete (3 reviewers: quality, compliance, adversarial-fresh)
- [x] V2 fixes applied: 3 source code bugs fixed + 4 test improvements + 1 CLAUDE.md doc fix
- [x] Final test run passes: **743 passed** in 36.53s

### V2 Fix Summary
| Fix | Source | Change |
|-----|--------|--------|
| H1 v2-adversarial | Non-dict JSONL crash | Added `isinstance(msg, dict)` guard in `memory_judge.py:115` + test |
| H2 v2-adversarial | UnicodeDecodeError | Added `ValueError` to except clause in `call_api` + test |
| H3 v2-adversarial | Lone surrogate crash | `encode("utf-8", errors="replace")` in `format_judge_input` + test |
| N1 v2-quality | keeps_all order | Added title assertions to verify original order preserved |
| M2 v2-adversarial | Mock patching | Changed all TestCallApi patches from global to `memory_judge.urllib...` |
| M2 v1-security | CLAUDE.md doc | Corrected write-side to read-side sanitization claim |

### V1 Fix Summary
| Fix | Source | Change |
|-----|--------|--------|
| H1 correctness | `clear=True` env wipe | Preserve non-API-key env vars |
| H2 correctness | max_turns identity | Added message content assertions |
| M1 correctness | payload body | Added test_call_api_payload_body |
| M2 correctness | non-text block | Added test_call_api_non_text_block |
| M6 correctness | missing transcript | Added test_judge_candidates_missing_transcript |
| H2 security | tag breakout | Added test_format_judge_input_memory_data_breakout |
| L2 security | path traversal | Added test_extract_recent_context_path_traversal |
| L3 security | negative indices | Added test_negative_string_indices_rejected |
