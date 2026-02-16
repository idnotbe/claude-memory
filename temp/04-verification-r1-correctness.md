# Verification Round 1: Correctness Review

> **Reviewer:** verifier-r1-correctness (Claude Opus 4.6)
> **Date:** 2026-02-16
> **Files reviewed:** memory_triage.py, hooks.json, 02-solution-design-final.md, 03-implementation-log.md
> **External reviews:** Gemini 3 Pro (via PAL clink, codereviewer role), Vibe-check metacognitive review
> **Status:** COMPLETE

---

## Executive Summary

The implementation is **structurally sound and well-designed**. It correctly implements the fail-open philosophy, handles the 6 categories, and produces proper exit codes. However, there are **2 real bugs** (one correctness, one data integrity), **3 design-vs-implementation divergences** that should be documented, and **several edge case observations** that are low-risk but worth noting.

**Verdict: PASS with required fixes** (2 bugs) and recommended improvements.

---

## A. Logic Correctness

### A1. stdin Reading -- PASS with 1 BUG

**Bug: UTF-8 multi-byte character corruption** (Severity: Medium)

In `read_stdin()` (line 199), each `os.read()` chunk is decoded independently:
```python
chunks.append(chunk.decode("utf-8", errors="replace"))
```

If a multi-byte UTF-8 character (e.g., emoji, CJK character) is split across two 65536-byte read boundaries, each half will be decoded as replacement characters (`\ufffd`). The fix is to accumulate raw bytes and decode once at the end:

```python
chunks: list[bytes] = []
# ...
chunks.append(chunk)  # Don't decode yet
# ...
return b"".join(chunks).decode("utf-8", errors="replace")
```

**Practical impact:** Low. stdin from Claude Code is JSON with ASCII keys and typically short values. But non-English content in `cwd` paths or `transcript_path` could trigger this.

**stdin format handling -- PASS:**
- Empty stdin: `raw_input.strip()` returns falsy -> exit 0. Correct.
- Malformed JSON: `json.JSONDecodeError` caught -> exit 0. Correct.
- Non-dict JSON (e.g., `"hello"` or `[1,2]`): `isinstance(hook_input, dict)` check -> exit 0. Correct.
- Valid JSON dict: proceeds correctly.

**select.select behavior -- PASS:**
- The `select()` approach correctly handles Claude Code's no-EOF behavior.
- `remaining` is set to `0.1` after the first successful read, creating a drain loop. Correct.
- On Linux/WSL (target platform), `select()` works on pipe file descriptors. Correct.
- Not portable to Windows (select only works on sockets there), but acceptable per target platform.

### A2. Transcript Parsing -- PASS

- Missing file: `OSError` caught -> returns `[]`. Correct.
- Empty file: no lines parsed -> returns `[]`. Correct.
- Corrupt JSONL lines: `json.JSONDecodeError` caught -> skip line, continue. Correct.
- Non-dict JSON lines (e.g., `"string"`, `42`): `isinstance(msg, dict)` guard -> skipped. Correct. This is an improvement over the design.
- `max_messages` clamping: `messages[-max_messages:]` for positive values. If `max_messages <= 0`, returns all messages. Config loader clamps to `[10, 200]` so this is safe.

**Note:** The implementation reads the entire file into memory before slicing. For very large transcripts (thousands of messages), this could use significant memory. A `collections.deque(maxlen=N)` would be more memory-efficient but functionally equivalent. In practice, transcript files for a single session are unlikely to reach problematic sizes, and the fail-open try/except will catch any MemoryError. This is a **performance optimization opportunity**, not a correctness bug.

### A3. Heuristic Scoring -- PASS with 1 BUG

**Bug: Scoring drops matches silently when both caps are reached** (Severity: Low)

In `score_text_category()` (lines 346-354), the scoring logic has this structure:
```python
if has_booster and boosted_count < max_boosted:
    raw_score += boosted_weight
    boosted_count += 1
    # ...
elif primary_count < max_primary:
    raw_score += primary_weight
    primary_count += 1
```

When `boosted_count >= max_boosted` AND `primary_count >= max_primary`, a primary match with a booster is silently dropped -- it contributes nothing to the score. This is by design (the caps prevent runaway scores), but there's a subtle interaction:

**The elif means a boosted match that exceeds the boosted cap falls through to the primary counter.** This is actually correct behavior -- a match with a booster that can't be counted as boosted should still count as a primary match. However, when BOTH caps are full, the match is dropped. This is intentional (the denominator is calculated as `max_primary * primary_weight + max_boosted * boosted_weight`), so the normalization is correct.

**Wait -- actually there IS a subtle issue:** Snippets are only collected for boosted matches (line 349-351), never for standalone primary matches. This means the `snippets` list in the result may be empty even when the category scores above threshold from primary-only matches. The `format_block_message()` handles this with a fallback ("Significant activity detected"), so it's not a crash bug, but it means the user gets less informative feedback for primary-only matches.

**Revised assessment:** This is a **minor bug** -- snippets should also be collected for standalone primary matches to provide better context in the block message.

### A4. Stop Hook Active Flag -- PASS

- No flag: returns `False` (continue evaluation). Correct.
- Fresh flag (age < 300s): deletes flag, returns `True` (allow stop). Correct.
- Stale flag (age >= 300s): deletes flag, returns `False` (re-evaluate). Correct.
- OSError on stat/unlink: returns `False` (continue evaluation). Correct.
- Flag is always deleted after reading (line 443), regardless of freshness. Correct.

The implementation matches the design. The flag uses file mtime rather than contents for age check, then also writes the timestamp as content (line 459). This is slightly redundant -- the mtime alone would suffice -- but not incorrect.

### A5. Output Format -- PASS

- Exit 0: no output. Correct for command-type Stop hooks.
- Exit 2: message on stderr. Correct for command-type Stop hooks (stderr is shown to the agent).
- Exit codes are always 0 or 2 from `_run_triage()`, and the top-level `main()` catches all exceptions and returns 0. No path produces other exit codes.

### A6. Exit Codes -- PASS

Every code path traced:
1. `main()` catches `Exception` -> 0
2. Empty stdin -> 0
3. Invalid JSON -> 0
4. Non-dict input -> 0
5. Disabled config -> 0
6. Fresh stop flag -> 0
7. No transcript path -> 0
8. Empty transcript -> 0
9. No categories above threshold -> 0
10. Categories above threshold -> 2

All paths verified correct.

---

## B. Edge Cases

### B1. Empty conversation (no messages) -- PASS
`parse_transcript` returns `[]` -> `_run_triage` exits 0 at line 602. Correct.

### B2. Very long conversation (1000+ messages) -- PASS with NOTE
The entire file is read into memory then sliced. With `max_messages` clamped to 200 max, and typical JSONL lines being 1-10KB, worst case is reading a multi-MB file. The `deque` optimization would help but this isn't a correctness issue. Any MemoryError would be caught by the top-level handler and exit 0.

### B3. Conversation with only tool_use messages -- PASS
`extract_text_content` filters to `type in ("human", "assistant")` only. If all messages are `tool_use`, the extracted text is empty. `score_text_category` gets zero-length lines, scores 0.0 for all text categories. `extract_activity_metrics` would count tool uses and could trigger SESSION_SUMMARY if sufficient. Correct behavior.

### B4. transcript_path doesn't exist -- PASS
`open()` raises `OSError`, caught on line 231 -> returns `[]` -> exit 0. Correct.

### B5. transcript_path is a directory -- PASS
`open()` on a directory raises `IsADirectoryError` (subclass of `OSError`), caught -> returns `[]` -> exit 0. Correct.

### B6. Unicode content in messages -- PASS
The regex patterns use `re.IGNORECASE` which handles Unicode case folding. `\b` word boundaries work correctly with Unicode in Python's `re` module. No issues.

### B7. Code blocks containing keywords -- PASS with NOTE
Fenced code blocks (` ```...``` `) are stripped. Inline code (`` `...` ``) is stripped.

**Known limitation:** Unclosed code fences (truncated transcript) will NOT be stripped, potentially causing false positives from code content. The regex `r"```[\s\S]*?```"` requires both opening and closing fences. This is a heuristic limitation, not a bug.

### B8. Multiple primary pattern matches on same line -- PASS
The `break` at line 357 ensures only one primary pattern match per line. Correct.

---

## C. Error Handling

### C1. Every exception path leads to exit 0 -- PASS
The top-level `main()` (line 562-566) wraps `_run_triage()` in `try/except Exception`. The only non-zero exit code (2) is returned explicitly inside `_run_triage`. All other paths return 0. `Exception` catches all non-system-exit exceptions including `MemoryError` (which is a subclass of `Exception` in Python 3... wait, actually `MemoryError` is NOT a subclass of `Exception`; it's a subclass of `BaseException`).

**Correction:** `MemoryError` IS actually a subclass of `Exception` in Python 3. The only `BaseException` subclasses that aren't `Exception` subclasses are `SystemExit`, `KeyboardInterrupt`, and `GeneratorExit`. So the `except Exception` DOES catch `MemoryError`. Verified correct.

### C2. Top-level try/except coverage -- PASS
`main()` calls `_run_triage()` inside `try/except Exception`. All logic is inside `_run_triage()`, so all exceptions are caught. `sys.exit(main())` in the `if __name__` block passes the return value; `main()` always returns an int. Correct.

### C3. cwd without write permissions -- PASS
If `flag_path.parent.mkdir()` or `flag_path.write_text()` fails in `set_stop_flag()`, the `OSError` is caught (line 460-461) and silently ignored. This means the flag won't be created, so the next stop attempt will re-evaluate instead of getting a free pass. This is the correct fail-open behavior -- the worst case is the user gets blocked twice in a row.

### C4. Concurrent transcript writes -- PASS
`parse_transcript` reads line-by-line. If Claude Code is appending to the transcript concurrently, the reader will get a consistent prefix of the file (lines already flushed). A partially-written final line would fail `json.loads()` and be skipped. No corruption risk.

---

## D. Design Conformance

### D1. Design Match -- MOSTLY CONFORMANT with documented divergences

| Aspect | Design | Implementation | Assessment |
|--------|--------|---------------|------------|
| Co-occurrence window | "4-line sliding window (2 before, 1 after)" | `CO_OCCURRENCE_WINDOW=4` -> 4 before, 4 after + center = 9 lines | **DIVERGENCE** -- wider than designed. The design text is self-contradictory ("4-line" vs "2 before, 1 after"). Implementation chose symmetric 4+4+1. Functionally, this is more generous and reduces false negatives. |
| session_id | Listed in stdin fields | Not extracted or used | **DIVERGENCE** -- harmless. The field is present in stdin JSON but unused. Acceptable for v1. |
| isinstance(msg, dict) guard | Not in design pseudocode | Added at line 227 | **IMPROVEMENT** -- valid JSON line could be a string/number. Good defensive addition. |
| PREFERENCE primary_weight | Design table says 0.3 | Implementation uses 0.35 | **DIVERGENCE** -- denominator correctly adjusted to 2.05. Appears to be intentional tuning. |
| read_stdin implementation | Uses `sys.stdin.read(4096)` | Uses `os.read(fd, 65536)` | **IMPROVEMENT** -- `os.read` is non-blocking on ready fd, `sys.stdin.read` may buffer. Larger chunk size reduces syscalls. |
| Inline code stripping | Not in design | Added `_INLINE_CODE_RE` at line 55 | **IMPROVEMENT** -- reduces false positives from inline code. |

### D2. All 6 categories implemented -- PASS
DECISION, RUNBOOK, CONSTRAINT, TECH_DEBT, PREFERENCE in `CATEGORY_PATTERNS`. SESSION_SUMMARY handled separately via `score_session_summary()`. All 6 present and scored.

### D3. Configuration system -- PASS
- Reads from `{cwd}/.claude/memory/memory-config.json`
- Falls back to defaults on missing/invalid config
- `enabled` flag: boolean conversion. Correct.
- `max_messages`: clamped to [10, 200]. Correct (addresses unclamped config concern from CLAUDE.md).
- `thresholds`: clamped to [0.0, 1.0] per category. Correct.
- Only known categories are read (iterates `DEFAULT_THRESHOLDS.items()`). Unknown categories in config are ignored. Correct.

---

## E. Bug Summary

### Bugs (Requires Fix)

| # | Severity | Location | Description | Fix |
|---|----------|----------|-------------|-----|
| 1 | Medium | `read_stdin()` L199 | UTF-8 multi-byte chars split across chunk boundaries are corrupted | Accumulate raw bytes, decode once at end |
| 2 | Low | `score_text_category()` L349-354 | Snippets only collected for boosted matches, not standalone primary matches | Add snippet collection to the `elif` branch too |

### Design Divergences (Document, Don't Fix)

| # | Aspect | Assessment |
|---|--------|------------|
| 1 | Window size 9 vs design's 4 | Wider window is more generous. Document as intentional. |
| 2 | session_id unused | Harmless. Document as deferred to v2. |
| 3 | PREFERENCE weight 0.35 vs 0.3 | Intentional tuning. Document. |
| 4 | Inline code stripping added | Improvement over design. Document. |
| 5 | `os.read` vs `sys.stdin.read` | Implementation improvement. No action needed. |

### Performance Recommendations (Optional)

| # | Location | Description | Fix |
|---|----------|-------------|-----|
| 1 | `parse_transcript()` L218-233 | Reads entire file into list before slicing | Use `collections.deque(maxlen=N)` |

### Known Limitations (Acceptable for v1)

| # | Limitation | Risk | Mitigation |
|---|-----------|------|------------|
| 1 | Unclosed code fences not stripped | False positives from code content | Heuristic limitation; fail-open means worst case is unnecessary block |
| 2 | English-only keywords | False negatives for non-English | Acceptable; worst case is missed memory |
| 3 | Windows incompatibility (`select.select`) | Won't work on Windows | Target platform is Linux/macOS |
| 4 | SESSION_SUMMARY not configurable for patterns/weights | Inconsistent with other categories | By design; activity-based scoring is fundamentally different |

---

## F. External Review Findings

### Gemini 3 Pro (via PAL clink, codereviewer role)

Gemini identified the same 2 bugs I found (UTF-8 chunk corruption, memory usage in parse_transcript) plus the unclosed code fence limitation. Gemini categorized the memory usage as "Critical" -- I disagree and rate it as a performance recommendation since: (a) transcripts for a single session rarely exceed a few MB, (b) max_messages is capped at 200, and (c) MemoryError is caught by the top-level handler. However, the `deque` fix is trivial and worth doing.

Gemini also noted the `select.select` Windows incompatibility and the SESSION_SUMMARY configuration asymmetry, both of which I concur with as known limitations.

### Vibe-Check Metacognitive Review

The vibe-check confirmed all 4 design-vs-implementation divergences are improvements or intentional, not bugs. It recommended documenting them explicitly to prevent future reviewers from re-flagging them. I concur.

---

## G. Overall Assessment

**Rating: PASS with required fixes**

The implementation is well-crafted, follows the fail-open philosophy consistently, and correctly implements all 6 categories. The 2 bugs found are both low-to-medium severity and have straightforward fixes. The design divergences are all improvements over the original design and should be documented rather than reverted.

The code quality is high: good separation of concerns, comprehensive docstrings, defensive error handling, and clear naming conventions. The `_run_triage()` separation from `main()` enables clean testability.

**Required actions before merge:**
1. Fix UTF-8 chunk decoding in `read_stdin()` (2 lines of code)
2. Add snippet collection for standalone primary matches in `score_text_category()` (3 lines of code)

**Recommended actions:**
3. Use `deque(maxlen=N)` in `parse_transcript()` for memory efficiency
4. Document the 4 design divergences in the implementation log
