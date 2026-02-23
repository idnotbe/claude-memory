# V2 Cross-Model Review: Guardian Conflict Memory Fix

**Date:** 2026-02-22
**Reviewer:** V2 Cross-Model Review Agent (Claude Opus 4.6)
**External Models Consulted:** Gemini 3.1 Pro Preview (4 queries), Claude Sonnet 4.6 (1 query)
**Codex Status:** Unavailable (usage limit hit) -- Queries 3 and 4 rerouted to Gemini and Claude

---

## Verdict: PASS WITH NOTES

The overall defense-in-depth approach is architecturally sound, and all three external model responses confirm this. However, the proposed implementations contain **three actionable defects** that must be addressed before deployment, plus one medium-severity design concern. The defects are all fixable within the existing architecture.

---

## Query 1: Guardian Heredoc Parser Design

### External Model Response (Gemini 3.1 Pro)

**Critical finding: The lookbehind guard `command[i-1] in ' \t\n;|&<>('` does NOT prevent `(( x << 2 ))` from being misdetected.**

Gemini identified two failures in the guard:

1. **False negative on arithmetic:** In `(( x << 2 ))`, the character before `<<` is a space. Space IS in the allowed set, so the guard evaluates to `True` and triggers heredoc parsing. This would consume `2 ))` as the delimiter and then treat subsequent lines as heredoc body -- a **security bypass** where malicious commands could be hidden.

2. **False positive on valid heredocs:** Bash allows `cat<<EOF` (no space). Here `command[i-1]` is `t`, which is NOT in the allowed set. The guard falsely rejects a valid heredoc.

Gemini also flagged array subscript contexts (`arr[x<<1]=5`) as an additional edge case.

**Gemini's recommendation:** Remove the lookbehind guard entirely. Instead, add `arithmetic_depth` tracking to the state machine (increment on `((` / `$((`, decrement on `))`). Only parse heredoc when `arithmetic_depth == 0`.

### Comparison with Our Documents

The guardian prompt document (`guardian-heredoc-fix-prompt.md`) relies on the lookbehind guard as the "mandatory mitigation" for the arithmetic bypass (line 466: "This is the mandatory mitigation"). The test suite includes `TestArithmeticBypassPrevention` which tests `(( x << 2 ))` -- but **the test would pass incorrectly** because the lookbehind guard allows it through, the parser would consume `2 ))` as a delimiter word, and then `rm -rf /` on the next line would be consumed as heredoc body. The assertion `any("rm" in sub for sub in subs)` would FAIL, catching the bug -- **meaning the tests are correctly written to detect this**, but the proposed implementation would not pass them.

**Action Required:** The lookbehind guard approach is fundamentally flawed. Must switch to `arithmetic_depth` tracking (Option A from Query 4).

---

## Query 2: Regex-Based Staging Guard Effectiveness

### External Model Response (Gemini 3.1 Pro)

Gemini identified multiple bypass vectors, categorized by severity:

**Critical bypasses:**
- `tee -a .claude/memory/.staging/file` -- the `-a` flag breaks `[^\s]*` matching
- `> .claude/memory/.staging/file echo foo` -- bash allows leading redirections; the regex requires `cat/echo/printf` prefix
- Unlisted write commands: `touch`, `sed ... > path`, `python -c "open(...)"`
- `&>` redirection: `echo foo &> .claude/memory/.staging/file` -- the `&` breaks `[^|&;\n]*`

**High bypasses:**
- Path normalization: double slashes (`//`), `./` prefix, `../` traversal
- Globbing: `echo foo > .claude/m*/.staging/file`

**Medium bypasses:**
- String quoting in paths: `.claude/"memory"/.staging/`
- Variable expansion: `STAGE=".claude/memory/.staging"; echo foo > $STAGE/file`

**Low bypasses:**
- Symlink indirection
- `eval` / `bash -c` obfuscation

**Gemini's recommendations:**
1. Simplify to match the staging path anywhere in the command regardless of preceding command
2. Consider runtime validation via `realpath`
3. Use filesystem permissions as a complementary control

### Comparison with Our Documents

The action plan (`plan-guardian-conflict-memory-fix.md`) acknowledges "path bypass via shell variables / relative paths" as a low-severity risk (line 63), arguing that subagents follow SKILL.md templates and rarely use exotic path patterns. This is a reasonable **threat model assumption** -- the guard is not defending against adversarial human attackers but against LLM behavioral drift. However, the `tee -a` and `&>` bypasses are realistic LLM behaviors, not exotic attacks.

**Action Required (Medium):** At minimum:
1. Fix the `tee` pattern: `\btee\s+.*\.claude/memory/\.staging/` (allow flags)
2. Add a simple catch-all: `>\s*[^\s]*\.claude/memory/\.staging/` without requiring a preceding command name
3. Fix `&>` by allowing it in the first clause: `[^;\n]*[&]?>\s*[^\s]*\.claude/memory/\.staging/`

The more exotic bypasses (variable expansion, symlinks, eval) are acceptable residual risk given the threat model: LLM subagents following templates.

---

## Query 3: Overall Approach Validation

### External Model Responses (Gemini 3.1 Pro + Claude Sonnet 4.6)

Both models independently confirmed the defense-in-depth approach is **architecturally sound**.

**Gemini's additional findings:**

1. **[Critical] `is_write_command()` quote-awareness bypass:** The proposed code uses `re.search()` which finds only the FIRST match. If the first `>` is inside quotes, it `continue`s to the next pattern entirely -- missing a second, real `>` later in the same string. Example: `echo " > benign" > ~/.bashrc` would be classified as NOT a write. **Fix:** Use `re.finditer()` to check ALL occurrences of each pattern.

2. **[High] `(( ))` depth tracking is mandatory**, not optional. Without it, `x=$(( y << EOF ))\n<malicious>\nEOF` hides commands.

3. **[High] Memory staging guard regex bypass** via leading redirections (same as Query 2).

4. **[Medium] `scan_protected_paths()` layer reorder concern:** Moving `scan_protected_paths()` to run on joined sub-commands (instead of raw string) undermines its defense-in-depth purpose. If `split_commands()` has a parser bug, Layer 1 misses it. Gemini recommends maintaining raw-string scanning but pre-stripping heredoc bodies.

**Claude Sonnet's findings:**

1. Confirmed the two-pronged approach is correct defense-in-depth
2. Explicitly called out that Failure Mode B (`.env` in heredoc body triggering `scan_protected_paths`) is NOT fixed by the heredoc parser alone -- needs the layer reorder
3. Recommended the same deployment sequencing: memory-side guard first (immediate), then staged guardian fixes
4. Warned against config allowlists as an alternative

### Comparison with Our Documents

The guardian prompt document does propose the layer reorder (Step 4, line 475-513) which addresses Failure Mode B. However, Gemini raises a valid architectural concern: moving `scan_protected_paths()` after `split_commands()` means a parser bug in `split_commands()` could cause `scan_protected_paths()` to miss something. The current architecture intentionally scans the raw string as a defense-in-depth layer.

The `is_write_command()` `re.search` vs `re.finditer` issue is a **genuine critical bug** in the proposed Fix 2. The document proposes a loop over `write_patterns` where each pattern uses `re.search()`. If the first match of the `>` pattern is inside quotes, it `continue`s to the NEXT pattern (e.g., `\btee\s+`), not to the next match of the same pattern. A command like `echo "> foo" > /etc/passwd` would be missed.

**Action Required:**
1. **[Critical]** Fix `is_write_command()` to use `re.finditer()` for patterns with `needs_quote_check=True`
2. **[Medium]** Consider a hybrid approach for `scan_protected_paths()`: strip heredoc bodies from the raw string (reusing the parser logic), then scan the stripped string. This preserves the defense-in-depth intent while avoiding heredoc false positives.

---

## Query 4: Arithmetic Bypass Mitigation Proposals

### External Model Response (Gemini 3.1 Pro)

Gemini evaluated all three options with clear severity ratings:

| Option | Verdict | Severity of Rejection |
|--------|---------|----------------------|
| **A: Add `(( ))` tracking** | **Recommended** | N/A -- this is the correct approach |
| **B: Context heuristic** | **Reject** | High -- fails on `(( result = variable << 2 ))` because variable names are not digits/spaces/parens |
| **C: Regex pre-pass** | **Reject** | Critical -- regex cannot handle nested contexts, guaranteed parsing bugs in security-critical code |

**Gemini's detailed recommendation for Option A:**
- Introduce `arithmetic_depth` counter alongside existing `depth`
- Increment on `((` and `$((`
- Decrement on `))`
- Also consider `$[` (legacy arithmetic) incrementing and `]` decrementing
- Only parse `<<` as heredoc when `arithmetic_depth == 0`

### Comparison with Our Documents

The guardian prompt document uses the lookbehind guard (Option not listed by Gemini) and mentions the `(( x << 2 ))` risk but frames it as handled by the guard. As established in Query 1, the guard does not work.

The action plan (`plan-guardian-conflict-memory-fix.md`) lists "Guardian parser heredoc awareness (Fix A)" as a future/optional follow-up in a separate repository (line 337), deferring it. This is acceptable for the immediate memory-side fix, but the guardian prompt document (which IS the guardian fix) needs to use Option A.

**Recommendation:** Adopt Option A exclusively. The implementation should:
1. Add `arithmetic_depth = 0` as a state variable in `split_commands()`
2. Detect `((` (when preceded by start-of-string, whitespace, or `$`) to increment
3. Detect `))` to decrement
4. Gate heredoc detection on `arithmetic_depth == 0` in addition to `depth == 0`
5. Remove the lookbehind guard entirely (it breaks `cat<<EOF` and fails on `(( x << 2 ))`)

---

## Summary of Required Changes

### Critical (must fix before deployment)

1. **`is_write_command()` must use `re.finditer()` for quote-checked patterns** -- the `re.search()` approach only finds the first match, allowing `echo " > foo" > /etc/passwd` to bypass detection. (Source: Gemini Query 3)

2. **Replace the lookbehind guard with `arithmetic_depth` tracking** in `split_commands()` -- the lookbehind guard fails in both directions: allows `(( x << 2 ))` through (space is in the allowed set) and rejects valid `cat<<EOF` (letter `t` is not in the allowed set). (Source: Gemini Query 1, confirmed by all models in Queries 3-4)

### High (strongly recommended)

3. **Fix `memory_staging_guard.py` regex** to handle `tee -a`, `&>` redirection, and command-less redirections like `> path`. Simplest fix: add a catch-all `(?:>|>>)\s*[^\s]*\.claude/memory/\.staging/` clause. (Source: Gemini Queries 2 and 3)

### Medium (recommended)

4. **Consider hybrid approach for `scan_protected_paths()`** -- rather than moving it after `split_commands()`, pre-strip heredoc bodies from the raw string, then scan. This preserves its defense-in-depth value against parser bugs. (Source: Gemini Query 3)

### Acknowledged (acceptable residual risk)

5. Variable expansion, symlink, eval, and globbing bypasses of the staging guard are acceptable given the threat model (LLM subagents, not adversarial humans). The SKILL.md prompt layer (C1) is the primary prevention; the guard (C2) is a safety net for common patterns only.

---

## New Insights from External Models

1. **Array subscript arithmetic:** `arr[x<<1]=5` is valid bash where `<<` is arithmetic shift inside `[]`. This is an additional edge case for the parser. (Gemini Query 1)

2. **`$[` legacy arithmetic syntax:** Bash supports `$[ expr ]` as a deprecated arithmetic form. The `arithmetic_depth` tracker should account for this. (Gemini Query 4)

3. **`scan_protected_paths()` architectural intent:** The raw-string scan was intentionally a defense-in-depth layer. Moving it after parsing defeats that purpose. A pre-strip approach preserves the layered defense. (Gemini Query 3)

4. **`let val<<2` behavior:** Bash actually treats `let val<<2` as a heredoc with delimiter `2` (not arithmetic), because `let` does not establish an arithmetic context the way `(( ))` does. Gemini noted this, which means the test `test_let_shift_not_heredoc` in the guardian prompt document may need reconsideration -- or the test expectation should be that `let val<<2` IS treated as heredoc (matching real bash behavior).

---

## Final Recommendation for Arithmetic Bypass Fix

**Use Option A: `arithmetic_depth` state tracking.**

This is the unanimous recommendation from all external models that addressed the question. It is:
- Architecturally consistent with the existing state machine (which already tracks `depth` for `$()`, `<()`, `>()`)
- Correctly mirrors Bash's native tokenization behavior
- The only approach that handles all edge cases (variables in arithmetic, nested contexts)
- Maintainable and testable

Reject Options B (heuristic) and C (regex pre-pass) for the reasons detailed above.
