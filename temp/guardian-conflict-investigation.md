# Guardian-Memory Conflict: Root Cause Investigation

## Summary

The `bash_guardian.py` PreToolUse:Bash hook from the `claude-code-guardian` plugin triggers a `[CONFIRM] Detected write but could not resolve target paths` popup when `claude-memory` writes JSON staging files via heredoc. The root cause is a **missing heredoc parser** in `split_commands()` combined with a **quote-unaware** `is_write_command()` regex, which together cause the F1 fail-closed safety net to fire on JSON body content.

---

## Root Cause: Three-Layer Failure Chain

### Layer 1: `split_commands()` has no heredoc awareness (line 82-245)

`split_commands()` at `/home/idnotbe/projects/claude-code-guardian/hooks/scripts/bash_guardian.py:82` splits on newlines (line 230-234) as one of its top-level delimiters:

```python
# Line 230-234
if c == "\n":
    sub_commands.append("".join(current).strip())
    current = []
    i += 1
    continue
```

There is **zero handling** of heredoc syntax (`<< DELIM`, `<< 'DELIM'`, `<<- DELIM`). Grep for "heredoc", "here_doc", "<<" across both `bash_guardian.py` and `_guardian_utils.py` returns no results. This is a **known limitation** documented in the guardian's own security tests at `tests/security/test_bypass_v2.py:142-146`:

```python
# 1f. Heredoc with separator
result = split_commands('cat <<EOF\n;\nEOF')
# Tokenizer doesn't track heredocs
test("tokenizer: heredoc with ; should NOT split at ;",
     len(result), 1, "tokenizer")
```

**Result:** A heredoc command like:
```
cat > path << 'EOFZ'
{
  "content": "upgrade path B->A->C"
}
EOFZ
```

Gets split into **separate sub-commands per line**. Verified empirically -- the above produces 8 sub-commands instead of 1.

### Layer 2: `is_write_command()` matches `>` inside JSON content (line 635-667)

`is_write_command()` at line 635 uses this regex as its first pattern:

```python
r">\s*['\"]?[^|&;]+"  # Redirection (line 651)
```

This pattern matches any `>` character followed by non-delimiter content. **It has no quote awareness.** When JSON content lines like `"upgrade path B->A->C"` are treated as standalone sub-commands, the `->` arrows match this pattern:

| JSON body line (after split) | `is_write_command()` match |
|---|---|
| `"Use B->A migration path",` | `>A migration path",` |
| `"Skip C->D shortcut"` | `>D shortcut"` |
| `"upgrade path B->A->C"` | `>A->C"` |

### Layer 3: F1 safety net fires because single-token sub-commands yield no paths (line 1033-1038)

The F1 fail-closed safety net at line 1033:

```python
if (is_write or is_delete) and not sub_paths:
    op_type = "delete" if is_delete else "write"
    final_verdict = _stronger_verdict(
        final_verdict,
        ("ask", f"Detected {op_type} but could not resolve target paths"),
    )
```

When `extract_paths()` (line 478) processes a fake sub-command like `"Use B->A migration path",`, `shlex.split()` produces a **single token** `['Use B->A migration path,']`. Since `extract_paths` skips `parts[0]` (treating it as the command name, line 507: `for part in parts[1:]`), `parts[1:]` is empty. No paths are extracted.

Similarly, `extract_redirection_targets()` (line 431) finds no matches because the "redirection" is inside what was originally quoted content.

**Result:** `is_write=True` AND `sub_paths=[]` --> F1 escalates to `("ask", "Detected write but could not resolve target paths")`.

Since `_stronger_verdict` uses `deny > ask > allow` precedence, **a single F1 trigger on any body line escalates the entire command**.

---

## Empirical Verification

### Test 1: split_commands decomposition

```python
command = '''cat > path << 'EOFZ'
{
  "related_decisions": [
    "Use B->A migration path",
    "Skip C->D shortcut"
  ],
  "key_findings": [
    "upgrade path B->A->C"
  ]
}
EOFZ'''

subs = split_commands(command)
# Result: 17 sub-commands instead of 1
```

### Test 2: F1 trigger identification

Three sub-commands trigger F1:
- Sub[9]: `"Use B->A migration path",` -- `>` in arrow
- Sub[10]: `"Skip C->D shortcut"` -- `>` in arrow
- Sub[13]: `"upgrade path B->A->C"` -- `>` in arrow

### Test 3: Broader F1 trigger patterns

Any JSON body line where:
1. `is_write_command()` matches `>` (from `->`, `>`, or similar), AND
2. `shlex.split()` produces a single token (no key: prefix, or the whole line is one quoted string)

Examples that trigger F1:
- `"B->C",` (array element with arrow)
- `"tags": ["a->b"]` (array with arrows)
- `"v1 -> v2",` (array element)
- `"score > 8",` (comparison in text)
- `"upgrade: B->A->C"` (single-token after shlex)

Examples that do NOT trigger F1 (despite false `is_write=True`):
- `"content": "upgrade path B->A->C",` -- shlex produces 2 tokens, `parts[1:]` yields a bogus path that `_is_within_project_or_would_be` accepts with `allow_nonexistent=True`

---

## Adjacent Issues Identified

### Issue A: `is_write_command()` is entirely quote-unaware

Even without heredocs, simple commands trigger false positives:
- `echo "B->A"` -- `is_write=True` (matches `>A"`)
- `git commit -m "Fixed B->A"` -- `is_write=True`
- `echo "value > threshold"` -- `is_write=True`

These may also trigger F1 depending on whether `extract_paths` can extract any path from the quoted content.

### Issue B: Layer 1 raw path scan runs on heredoc body

`scan_protected_paths()` at line 1009 scans the **entire raw command** including heredoc body. If the JSON content happens to contain strings like `.env` or `.pem`, it will trigger false deny/ask verdicts from Layer 1 as well.

### Issue C: `extract_redirection_targets()` can match heredoc delimiters

The regex at line 447 `<(?!<)` is designed to skip `<<`, but if the `<` characters get split across sub-commands or appear in other contexts within the heredoc body, they could produce false path matches.

### Issue D: Security consideration for heredoc parsing

If a fix adds heredoc body skipping to `split_commands()`, it must distinguish between:
- `<< 'EOF'` (literal, no interpolation) -- safe to skip entirely
- `<< EOF` (interpolated) -- `$(rm -rf /)` inside would be executed by bash

---

## External Model Opinions

### Gemini (via pal clink)

**Confirmed the analysis.** Additionally identified that:
1. Fixing `split_commands()` alone is insufficient because `is_write_command()` would still match `>` inside heredoc content even if kept as one compound sub-command
2. The F1 false-positive extends to ANY command with `>` inside quotes (not just heredocs)
3. Recommended both patching `split_commands()` for heredoc awareness AND making `is_write_command()` quote-aware using the existing `_is_inside_quotes()` helper

### Codex (via pal clink)

**Confirmed the analysis and reproduced end-to-end.** Additional findings:
1. `extract_redirection_targets()` can misread heredoc delimiters (`<<EOF`) as redirection targets, yielding fake path `EOF`
2. `extract_paths(..., allow_nonexistent=True)` accepts shell metatokens (`>`, `<<`) as "paths", which can suppress F1 in some heredoc forms (a separate safety regression)
3. Referenced existing security test at `test_bypass_v2.py:143` documenting the known tokenizer gap
4. Layer 1 `scan_protected_paths()` running on full raw command is another false-positive vector for heredoc content

---

## Code Trace: Exact Execution Path

For the triggering command `cat > path << 'EOFZ'\n{"related_decisions": ["Use B->A migration path"]}\nEOFZ`:

1. **`main()` line 946** receives the full heredoc command via stdin JSON
2. **`match_block_patterns()` line 990** -- no block patterns match, continues
3. **`match_ask_patterns()` line 1004** -- no ask patterns match, continues
4. **`scan_protected_paths()` line 1009** -- may or may not match depending on content
5. **`split_commands()` line 1015** -- splits on `\n`, producing N sub-commands including heredoc body lines
6. **Loop at line 1018** iterates each sub-command:
   - Sub[0] `cat > path << 'EOFZ'`: `is_write=True`, paths extracted (F1 does NOT fire)
   - Sub[N] `"Use B->A migration path",`: `is_write=True` (via `>A` match), `extract_paths` returns empty (shlex single token), `extract_redirection_targets` returns empty --> **F1 fires at line 1033**
7. **`_stronger_verdict()` line 1035** escalates `final_verdict` to `("ask", "Detected write but could not resolve target paths")`
8. **Line 1176** emits the ask response: `print(json.dumps(ask_response(final_verdict[1])))`
9. **User sees**: `[CONFIRM] Detected write but could not resolve target paths`

---

## Key File References

| File | Lines | Role |
|---|---|---|
| `bash_guardian.py` | 82-245 | `split_commands()` -- no heredoc handling, splits on `\n` at line 230 |
| `bash_guardian.py` | 635-667 | `is_write_command()` -- quote-unaware `>` regex at line 651 |
| `bash_guardian.py` | 478-568 | `extract_paths()` -- skips `parts[0]`, empty for single-token lines |
| `bash_guardian.py` | 431-475 | `extract_redirection_targets()` -- can match heredoc delimiters |
| `bash_guardian.py` | 1033-1038 | F1 safety net -- the direct source of the popup message |
| `bash_guardian.py` | 1015 | `split_commands(command)` call in main flow |
| `bash_guardian.py` | 1176 | Final ask verdict emission |
| `test_bypass_v2.py` | 142-146 | Known limitation: "Tokenizer doesn't track heredocs" |
| `test_v2fixes_adversarial.py` | 154-161 | Existing heredoc test (only tests `is_write_command`, not full flow) |

All paths relative to `/home/idnotbe/projects/claude-code-guardian/hooks/scripts/` (scripts) or `/home/idnotbe/projects/claude-code-guardian/tests/` (tests).
