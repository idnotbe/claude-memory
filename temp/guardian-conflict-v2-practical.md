# V2 Practical Implementation Review

**Reviewer:** v2-practical (fresh eyes, implementation focus)
**Date:** 2026-02-22
**Input:** `guardian-conflict-fix-design.md`, empirical testing of bash_guardian.py, SKILL.md analysis

---

## 1. Empirical Test Results: Three-Layer Failure Chain

### Test Method
Imported `split_commands`, `is_write_command`, `extract_paths`, `scan_protected_paths` directly from `bash_guardian.py` and ran against the actual triggering command.

### Triggering Command
```bash
cat > .claude/memory/.staging/input-decision.json << 'EOFZ'
{"title": "Score B->A->C ordering", "tags": ["scoring"], "content": {"decision": "chose B->A"}}
EOFZ
```

### Results

| Layer | Function | Finding | Confirmed? |
|-------|----------|---------|:----------:|
| Layer 2 | `split_commands()` | Splits into 3 sub-commands: command line, JSON body, `EOFZ` | YES |
| Layer 4 | `is_write_command()` | JSON body `"B->A->C"` matches `>` redirection pattern | YES |
| Layer 3 | `extract_paths()` | Extracts garbage paths from JSON body (`Score B->A->C ordering,`, `tags:`, etc.) | YES |
| F1 safety net | Lines 1033-1038 | Does NOT trigger (garbage paths count as "resolved") | PARTIALLY -- see below |
| Layer 1 | `scan_protected_paths()` | Catches `.env` in heredoc body when present | YES |

### Critical Nuance: F1 Is NOT the Primary Trigger

The design doc emphasizes F1 (fail-closed safety net) as the popup source. **Empirical testing shows this is misleading.** The actual verdict flow for the arrows-only case (`B->A->C`) resolves to `allow` because `extract_paths` returns garbage paths (satisfying the F1 "paths resolved" check).

**The real trigger is Layer 1** (`scan_protected_paths` at line 1009). This function scans the **raw command string** -- including heredoc body content -- for protected path references like `.env`. When memory content mentions `.env`, Layer 1 produces `ask` verdict regardless of how well `split_commands` works.

**Implication:** Option A (fixing `split_commands`) does NOT fix the `.env`-in-heredoc-body class of false positives. It only fixes Layers 2-4. Layer 1 runs on the raw string at line 1009, before `split_commands` is called at line 1015.

---

## 2. Option A Feasibility: Heredoc-Aware `split_commands`

### Prototype Results

Built a working prototype and ran all 10 test cases from the design doc:

| # | Test Case | Result |
|---|-----------|:------:|
| 1 | Basic heredoc `cat <<EOF\nhello\nEOF` | PASS |
| 2 | Quoted heredoc `cat << 'EOFZ'\ncontent with > arrows\nEOFZ` | PASS |
| 3 | Heredoc with redirection `cat > file << 'EOF'\n...\nEOF` | PASS |
| 4 | `<<-` tab stripping | PASS |
| 5 | `<<<` here-string (should NOT trigger heredoc) | PASS |
| 6 | Multiple heredocs on one line | PASS |
| 7 | Heredoc followed by next command (should be 2 subs) | PASS |
| 8 | Known limitation `cat <<EOF\n;\nEOF` (test_bypass_v2.py:142) | PASS |
| 9 | Actual triggering command | PASS |
| 10 | `.env` in heredoc body | PASS |

### Integration Assessment

- **Insertion point:** Lines 179-234 in the `depth == 0` block. Heredoc detection goes BEFORE the newline handler at line 230.
- **Diff size:** ~85 net new lines (25 inline + 2 helper functions of ~30 lines each).
- **State machine interaction:** The heredoc detection only fires at `depth == 0` outside quotes/backticks, which is correct. No changes to existing escape/quote/depth logic.
- **Risk of regression:** Low. All existing non-heredoc commands parse identically.

### Codex Review (via pal clink)

Codex 5.3 confirmed the approach and identified four practical risks (severity-ordered):

1. **HIGH: State corruption in `$(...)` heredocs.** If `depth > 0` and a heredoc body contains `)`, it could prematurely close the command substitution. The design doc's `depth == 0` constraint avoids this, but means heredocs inside `$(...)` are NOT handled.
2. **HIGH: FIFO queue design for multi-heredoc.** Multiple `<<` on one line requires a proper queue consumed across subsequent physical lines. Prototype handles this correctly.
3. **MEDIUM: Delimiter normalization.** Quote removal (`'EOF'` -> `EOF`) and `<<-` tab stripping must be exact. Prototype handles both.
4. **MEDIUM: Detection ordering.** Heredoc detection must run AFTER escape/quote/backtick checks. The proposed insertion point in the `depth == 0` block is correct.

### Feasibility Verdict: FEASIBLE

The prototype works. The main risk (heredoc-inside-`$(...)`) is out of scope for this fix and can be deferred. The ~85-line diff is manageable and isolated.

### Gap Identified

**Option A does NOT fix Layer 1 false positives.** `scan_protected_paths` scans the raw command string at line 1009, before any splitting. To fully fix `.env`-in-heredoc-body false positives, either:
- Make `scan_protected_paths` heredoc-aware (strip heredoc bodies before scanning), or
- Run `scan_protected_paths` per sub-command instead of on the raw string
- Or accept the gap and rely on Option C (memory-side enforcement) to prevent the trigger

This gap is NOT called out in the design doc's comparison matrix.

---

## 3. Option C Feasibility: SKILL.md + Guard Hook

### Part C1: SKILL.md Wording Change

**Location:** `/home/idnotbe/projects/claude-memory/skills/memory-management/SKILL.md` lines 81-83.

The current mandate is a single blockquote paragraph inside the "Subagent instructions" section. The proposed replacement extends the blockquote and adds anti-pattern/correct-pattern examples. This is **fully compatible** with the document structure -- it's a simple text replacement within an existing blockquote section.

**Assessment:** Trivial change, no structural risk.

### Part C2: PreToolUse:Bash Guard Hook

**Hook registration feasibility:** The memory plugin's `hooks.json` currently has hooks for `Stop`, `PreToolUse:Write`, `PostToolUse:Write`, and `UserPromptSubmit`. Adding a `PreToolUse:Bash` entry is structurally valid -- just another object in the `PreToolUse` array.

**Multi-plugin hook behavior:** Both the guardian plugin and the memory plugin would have `PreToolUse:Bash` hooks. Claude Code runs all hooks for a given event+matcher combination. **Hook execution order between plugins is NOT guaranteed.** If the guardian runs first and triggers an `ask` popup, the user sees the popup before the memory guard can deny. The memory guard's deny would only fire if the guardian allows.

**Regex false positive:** The proposed regex pattern `(?:cat|echo|tee|printf)\s+.*\.claude/memory/\.staging/` matches `cat .claude/memory/.staging/input.json` (a read operation). In practice, subagents use the Read tool (not `cat` via Bash) for reading staging files, so this is unlikely to be hit. However, it's a known imperfection.

**Improved regex suggestion:**
```python
# Require a redirection operator between command and staging path
r'(?:cat|echo|printf)\s+[^|&;\n]*>\s*[^\s]*\.claude/memory/\.staging/'
r'|'
r'\btee\s+[^\s]*\.claude/memory/\.staging/'
```

### Feasibility Verdict: FEASIBLE (with caveats)

- C1 (SKILL.md): Zero risk, immediate deployment
- C2 (guard hook): Best-effort secondary defense due to hook ordering uncertainty. The regex should be refined but the false positive is low-probability.

---

## 4. SKILL.md Mandate Location

**File:** `/home/idnotbe/projects/claude-memory/skills/memory-management/SKILL.md`
**Lines:** 81-83
**Section:** "Subagent instructions (kept simple for haiku)"

Current text:
```markdown
> **MANDATE**: All file writes to `.claude/memory/.staging/` MUST use the **Write tool**
> (not Bash cat/heredoc/echo). This avoids Guardian bash-scanning false positives
> when memory content mentions protected paths like `.env`.
```

The proposed replacement (negative constraint with anti-pattern example) is compatible with the document structure. It replaces a 3-line blockquote with a ~12-line blockquote including code examples. The numbered instruction list that follows (steps 1-10) remains unchanged.

**Compatibility:** FULL. No structural changes needed to surrounding text.

---

## 5. Deployment Considerations

### Deployment Path

Both plugins are local development installs (repos at `/home/idnotbe/projects/`):

| Plugin | Version | Repo | Deployment |
|--------|---------|------|-----------|
| claude-memory | 5.0.0 | `/home/idnotbe/projects/claude-memory/` | Local dev |
| claude-code-guardian | 1.0.0 | `/home/idnotbe/projects/claude-code-guardian/` | Local dev |

**For memory-side fixes (Option C):**
- Edit `SKILL.md` and `hooks.json` directly in the claude-memory repo
- No version dependency on guardian
- Immediately effective on next plugin load

**For guardian-side fixes (Options A+B):**
- Edit `bash_guardian.py` in the claude-code-guardian repo
- Add tests in `tests/security/`
- No version dependency on memory plugin
- Effective on next plugin load

**Cross-plugin dependency:** None. Each fix is independently deployable.

### Version Dependencies

- Option C requires no version bump (minor hook addition + wording change)
- Options A+B should bump guardian to 1.1.0 (new parser feature + behavior change)
- No cross-version dependencies between plugins

---

## 6. Blockers Identified

| # | Blocker | Severity | Affects |
|---|---------|:--------:|---------|
| 1 | **Layer 1 gap**: Option A does NOT fix `scan_protected_paths` false positives on `.env` in heredoc body | HIGH | Design doc completeness |
| 2 | Option C regex false positive on `cat` read operations | LOW | Guard hook accuracy |
| 3 | Hook ordering between plugins not guaranteed | MEDIUM | Guard hook reliability |
| 4 | Heredoc-inside-`$(...)` not handled by Option A | LOW | Edge case, out of scope |

Blocker #1 is the most significant finding. The design doc's comparison matrix shows Option A as "Fixes heredoc false positives: Yes (all plugins)" but this is only true for Layers 2-4. Layer 1 (`scan_protected_paths`) false positives on `.env`/`.pem`/etc. in heredoc body content are NOT fixed by Option A alone. The design doc should acknowledge this gap and either:
- Add a sub-option A2: make `scan_protected_paths` heredoc-aware
- Or document that Option C (preventing the heredoc trigger entirely) is required to cover Layer 1

---

## Overall Verdict: PASS WITH NOTES

The design recommendations are sound, implementable, and well-scoped. The layered approach (A+B for guardian, C for memory) is architecturally correct. However:

1. **The Layer 1 gap must be acknowledged.** Option A is necessary but NOT sufficient for the `.env`-in-heredoc-body class of false positives. Option C (preventing subagents from using heredoc) is essential to cover this gap, elevating it from "secondary defense" to "required complement."

2. **Option C should be implemented FIRST** (not just for priority -- it's the only fix that covers Layer 1 without modifying the guardian). The design doc's implementation priority already recommends this order, which is correct, but the rationale should be strengthened.

3. **The prototype works.** All 10 test cases pass. Integration risk is low. The diff is manageable (~85 lines).

4. **Deployment is straightforward.** Both plugins are local dev installs with no cross-version dependencies. Changes are independently deployable.
