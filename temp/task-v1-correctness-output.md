# V1 Correctness Review - Output Report

## Reviewer: v1-correctness
## Date: 2026-02-20
## Files Reviewed: memory_retrieve.py, memory_index.py

---

## VERDICT: PASS (with one minor observation)

All 12 fixes are correctly implemented. No regressions detected. No merge conflicts.

---

## Fix-by-Fix Verdict

### Group A: Security Vulnerabilities

**A1 (HIGH) - Tag XML Injection** -- PASS
- `import html` added at line 13 (stdlib, no external dependency added)
- `sorted(html.escape(t) for t in tags)` at line 390 -- correct
- `html.escape()` handles `&` first (no double-encoding risk)
- Verified: `html.escape('</memory-context>')` -> `'&lt;/memory-context&gt;'`

**A2 (MEDIUM) - Path Traversal in check_recency** -- PASS
- `memory_root_resolved = memory_root.resolve()` computed once at line 328 (before loop)
- Top-20 loop (lines 330-345): containment check with `relative_to()`, `continue` on ValueError
- Extended to fallback loop (lines 352-358): same containment check applied
- Verified: traversal paths (`../../../etc/passwd`) blocked, absolute paths (`/etc/passwd`) blocked, normal paths pass
- Both loops use the same pre-computed `memory_root_resolved` -- correct

**A3 (LOW) - cat_key Unsanitized in descriptions Attribute** -- PASS
- `re.sub(r'[^a-z_]', '', cat_key.lower())` at line 378 -- correct
- Empty result check (`if not safe_key: continue`) prevents empty attribute names
- Verified: `=`, `"`, digits, spaces all stripped
- The `safe_desc` is passed through `_sanitize_title()` which escapes `"` to `&quot;`
- Resulting `desc_attr` is valid XML attribute syntax

**A4 (LOW) - Path Field Not XML-Escaped** -- PASS
- `safe_path = html.escape(entry["path"])` at line 392 -- correct
- Used in print statement at line 393
- Verified: `<inject>` in path -> `&lt;inject&gt;` in output

---

### Group B: Functional Bugs

**B1 (MEDIUM) - _sanitize_title() Truncation Order** -- PASS
- Fix at lines 202-204: `strip()[:120]` BEFORE XML escape replaces
- Verified: string with `&` at position 119 now produces complete `&amp;` entity
- Old order would produce bare `&` (invalid XML) when `&` fell at truncation boundary
- Manual replace chain has correct order (`&` first), consistent with `html.escape()` behavior

**B2 (LOW) - int(score) Truncation in score_description** -- PASS
- `return min(2, int(score + 0.5))` at line 153 -- correct round-half-up
- Verified: `int(1.5 + 0.5) = 2` (was `int(1.5) = 1` before fix)
- `min(2, ...)` cap still applies correctly for all input values
- Note on banker's rounding: `int(score + 0.5)` is explicit round-half-up, avoids Python's `round()` banker's rounding where `round(0.5) = 0`

**B3 (LOW) - grace_period_days Type Confusion** -- PASS
- Fix at lines 216-220 in `memory_index.py`:
  ```python
  raw_gpd = config.get("delete", {}).get("grace_period_days", 30)
  try:
      grace_period_days = max(0, int(raw_gpd))
  except (ValueError, TypeError):
      grace_period_days = 30
  ```
- Handles string `"30"`, integer `30`, negative values (clamped to 0), `None`, invalid strings
- `float` strings like `"30.5"` correctly fall back to 30 (int("30.5") raises ValueError)
- This is acceptable behavior

**B4 (MEDIUM) - Index Rebuild Doesn't Sanitize Titles** -- PASS
- `_sanitize_index_title()` helper added at lines 89-99 in `memory_index.py`
- Uses `" ".join(title.split())` to collapse ALL whitespace (including `\n`, `\t`, `\r`, `\x0b`, `\x0c`)
- Strips ` -> ` injection markers and `#tags:` injection markers
- Truncates to 120 chars
- Used at line 117: `_sanitize_index_title(m['title'])` in `rebuild_index()`
- Verified: newlines, tabs, `->` injection, `#tags:` injection all handled

---

### Group C: Algorithm/Quality Improvements

**C1 (MEDIUM) - 2-char Tokens Permanently Unreachable** -- PASS
- `len(word) > 1` at line 67 (was `> 2`, now allows 2-char tokens)
- New stop words added at lines 33-34: `"as", "am", "us", "vs"`
- `"go"` was already in STOP_WORDS (confirmed present)
- Verified: `ci`, `db`, `ui`, `k8`, `ai`, `cd`, `vm`, `io` all pass through
- Verified: `as`, `am`, `us`, `vs`, `go`, `in`, `at`, `to` all still filtered
- Single-char tokens still blocked (`len > 1` excludes `len == 1`)

**C2 (LOW) - Description Category Flooding** -- PASS
- Guard at line 313: `if cat_desc_tokens and text_score > 0:`
- Description bonus only applied when entry already scored on title/tags
- Verified: entries with `text_score=0` skip description bonus, remain below `if text_score > 0:` threshold at line 315 and are not appended to `scored`
- Correct interaction with flow: no entry with zero text score can flood results via description match

**C3 (LOW) - Prefix Direction Asymmetry** -- PASS
- Reverse prefix check added at lines 122-123:
  ```python
  elif any(pw.startswith(target) and len(target) >= 4 for target in combined_targets):
      score += 1
  ```
- `elif` prevents double-scoring if forward prefix already matched
- Guard `len(target) >= 4` prevents short false positives (e.g., `cat` matching `category`)
- Verified: `authentication`.startswith(`auth`) = True, len=4 >= 4 -> +1 (correct)
- Verified: `database`.startswith(`db`) = True but len(`db`)=2 < 4 -> no match (correct)
- Verified: no interaction issue with `already_matched` exclusion set (unmodified)
- Note: my initial test for `authenticate`/`authentication` was incorrect (they share different stems). The fix handles its stated use case correctly.

**C4 (LOW) - Retired Entries at Rank 21+ Skip Retired Check** -- PASS (comment-only fix)
- Comment added at lines 347-350 explaining the safety assumption
- Documents that `index.md` contains only active entries (filtered by `rebuild_index()`)
- No code change needed per fix plan; comment correctly documents the known limitation
- A2 extended fix additionally applies path containment to the fallback loop

---

## Interaction Analysis

**C1 + STOP_WORDS**: Safe. New 2-char tokens `"as", "am", "us", "vs"` correctly added to STOP_WORDS alongside `"go"`.

**B2 (rounding) + C2 (description gating)**: Safe. `score_description()` returns via `min(2, int(score+0.5))`. The C2 guard prevents calling `score_description()` when `text_score == 0`. No interaction issue.

**A2 + C4**: Complementary. A2 extended adds containment check to fallback loop; C4 documents the retired-check gap in that same loop.

**B1 + A1/A4**: No conflict. B1 fixes `_sanitize_title()` (used for titles). A1/A4 use `html.escape()` separately for tags and paths. Both are independent and correct.

**A3 desc_attr + A1/A4**: Safe. Category descriptions go through `_sanitize_title()` (which escapes `"` to `&quot;`), ensuring the `descriptions="..."` attribute value cannot contain raw double quotes. A1 and A4 handle tags and paths independently.

---

## No Merge Conflicts

Both files checked -- no `<<<<<<<`, `=======`, or `>>>>>>>` markers found.

---

## Observation (Non-blocking)

**B4 doesn't sanitize tags in index rebuild**: `rebuild_index()` outputs raw tag strings into `index.md` without escaping. However:
1. Tags are schema-validated by Pydantic at write time (low risk)
2. The A1 fix (html.escape in retrieve.py output) provides defense-in-depth
3. Tags with `' -> '` are captured in the `#tags:` group by `_INDEX_RE` (verified), not confused with path delimiter

This is an acceptable gap given the existing defense-in-depth. Not a regression introduced by these fixes.

---

## Summary

| Fix | Status | Notes |
|-----|--------|-------|
| A1 | PASS | html.escape on tags |
| A2 | PASS | containment check + extended to fallback loop |
| A3 | PASS | cat_key sanitized, empty key skipped |
| A4 | PASS | path html.escape |
| B1 | PASS | truncate before escape |
| B2 | PASS | round-half-up via int(score+0.5) |
| B3 | PASS | int() coercion with try/except |
| B4 | PASS | _sanitize_index_title() with whitespace collapse |
| C1 | PASS | len>1, new stop words added |
| C2 | PASS | text_score>0 guard |
| C3 | PASS | reverse prefix with len(target)>=4 guard |
| C4 | PASS | comment-only, correctly documents assumption |

**Overall: PASS. All 12 fixes are correct. No regressions. No merge conflicts.**
