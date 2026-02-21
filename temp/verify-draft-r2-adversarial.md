# Adversarial Verification Round 2: memory_draft.py + memory_candidate.py

**Verifier:** verifier-r2-adversarial
**Date:** 2026-02-21
**Status:** PASS -- 0 critical, 1 medium, 4 low, 4 informational findings
**Files attacked:**
1. `hooks/scripts/memory_draft.py` (NEW, 343 lines)
2. `hooks/scripts/memory_candidate.py` (MODIFIED, --new-info-file)
3. `tests/test_memory_draft.py` (NEW, 1011 lines)

**Reference:** `hooks/scripts/memory_write.py` (downstream enforcement)

---

## Methodology

I wrote and executed targeted attack scripts for each of 9 attack vectors, running them against the actual implementation. All attacks were executed with real subprocess calls to the scripts under test, not mocked. For attacks that found draft-level issues, I verified end-to-end through the full pipeline (memory_draft.py -> memory_write.py) to determine real-world impact.

---

## Finding 1: Zero-Width and RTL Override Characters Survive Full Pipeline

**Severity:** MEDIUM
**Type:** Unicode visual spoofing
**Vector:** Attack 4 (Unicode edge cases)

**Description:**
Zero-width space (U+200B) and RTL override (U+202E) characters survive through BOTH memory_draft.py AND memory_write.py's `auto_fix()`. These characters can enable visual spoofing attacks:

- **Zero-width space (U+200B):** Can make visually identical titles that are different strings, causing deduplication failures. Two memories titled "UseJWTforauth" would appear identical but be treated as different entries.
- **RTL override (U+202E):** Can reverse the visual display of text, hiding malicious content. Title `Normal ‮EDIROVER‬ text` displays as `Normal REVID‮E text` in some renderers.

**Proof of Concept:**
```
Input title:  "Use\u200bJWT\u200bfor\u200bauth"
Draft title:  "Use\u200bJWT\u200bfor\u200bauth"  (ZWJ survived)
Final title:  "Use\u200bJWT\u200bfor\u200bauth"  (ZWJ survived auto_fix)
```

```
Input title:  "Normal \u202eEDIROVER\u202c text"
Draft title:  "Normal \u202eEDIROVER\u202c text"  (RTL survived)
Final title:  "Normal \u202eEDIROVER\u202c text"  (RTL survived auto_fix)
```

**Root cause:** `memory_write.py`'s `auto_fix()` strips control characters in range `[\x00-\x1f\x7f]` (C0/C1 control codes). Zero-width space (U+200B) and RTL override (U+202E) are in Unicode category "Cf" (format), not "Cc" (control), so the regex `r'[\x00-\x1f\x7f]'` does not match them.

**Null bytes (U+0000) ARE stripped** -- confirmed auto_fix handles them correctly.

**Impact:** An LLM subagent influenced by a crafted transcript could create memory entries with visually confusing titles. When these titles are injected into context by the retrieval hook, they could subtly mislead subsequent LLM behavior. The risk is moderate because:
1. The attacker must influence what the LLM writes as a title (indirect injection)
2. The retrieval hook re-sanitizes titles, but only for control chars and index-injection markers, not Unicode format chars
3. The impact is visual confusion / deduplication failure, not code execution

**Recommendation:** Extend `auto_fix()` title sanitization to strip Unicode format characters (category Cf):
```python
import unicodedata
sanitized = ''.join(c for c in sanitized if unicodedata.category(c) != 'Cf')
```

**Existing defense:** `slugify()` strips all non-ASCII during NFKD normalization + ASCII encoding, so the `id` field is safe (ZWJ/RTL chars are removed from slugs). Only the `title` field is affected.

---

## Finding 2: Dict-as-Title Passes Through Full Pipeline

**Severity:** LOW
**Type:** Type confusion / input validation gap

**Description:**
When a non-string value (e.g., a dict) is provided as the `title` field in partial JSON input, `memory_draft.py`'s `assemble_create()` calls `str(input_data.get("title", ""))`, converting the dict to its Python string representation: `"{'nested': 'object', 'with': 'keys'}"`. This string then passes through Pydantic validation (it's a valid string under 120 chars) and is written as the final title.

**PoC:**
```
Input:  {"title": {"nested": "object"}, ...}
Draft:  title = "{'nested': 'object', 'with': 'keys'}"
Final:  title = "{'nested': 'object', 'with': 'keys'}"  (accepted)
```

**Impact:** Low. The result is cosmetically ugly but not a security issue. The LLM subagent would have to be confused enough to write a dict instead of a string, and the result is clearly wrong to a human reviewer. Phase 2 verification would likely catch this as poor content quality.

**Recommendation:** Add type validation in `check_required_fields()` or `assemble_create()`:
```python
if not isinstance(input_data.get("title"), str):
    return "title must be a string"
```

---

## Finding 3: 1000 Tags Pass memory_draft.py (Mitigated by memory_write.py)

**Severity:** LOW (mitigated)
**Type:** Resource consumption / missing validation

**Description:**
memory_draft.py accepts 1000 tags without any cap. The draft file contains all 1000 tags. However, when the draft reaches memory_write.py, `auto_fix()` enforces TAG_CAP (12), truncating to 12 tags.

**PoC:**
```
Input:  1000 tags
Draft:  1000 tags (no cap in memory_draft.py)
Final:  12 tags (TAG_CAP enforced by memory_write.py auto_fix)
```

**Impact:** Low. The pipeline self-heals. The only concern is that Phase 2 verification sees the 1000-tag draft, which could cause confusion or excessive context injection in the verifier prompt. No data integrity impact.

**Recommendation:** Optional: add a TAG_CAP check in `assemble_create()` for consistency, but this is not required since enforcement is in memory_write.py.

---

## Finding 4: Index Delimiter Injection in Draft -- Correctly Mitigated

**Severity:** INFORMATIONAL (no vulnerability)
**Type:** End-to-end verification

**Description:**
Titles and tags containing index delimiter strings (` -> `, `#tags:`) survive in the draft but are correctly sanitized by memory_write.py's `auto_fix()`:

```
Input title:   "Evil -> /etc/passwd #tags:admin,root"
Draft title:   "Evil -> /etc/passwd #tags:admin,root"  (injection markers present)
Final title:   "Evil - /etc/passwd admin,root"          (sanitized by auto_fix)

Input tags:    ["test", "evil -> inject", "#tags:fake"]
Draft tags:    ["test", "evil -> inject", "#tags:fake"]  (injection present)
Final tags:    ["evil inject", "fake", "test"]            (sanitized)
```

The index line is correctly built from the sanitized title and tags. Index parsing succeeds without confusion.

**Verdict:** The defense-in-depth chain works as designed. memory_draft.py does NOT sanitize (by spec), and memory_write.py catches everything.

---

## Finding 5: Symlink Input Path Bypass via /tmp/ Allowance

**Severity:** LOW
**Type:** Trust boundary interaction

**Description:**
A symlink placed in `.claude/memory/.staging/` pointing to a file under `/tmp/` will be followed, because `validate_input_path()` checks the resolved path against two conditions: contains `/.claude/memory/.staging/` OR starts with `/tmp/`. Since the temp directory IS under `/tmp/`, the symlink resolves to a `/tmp/` path, which is allowed.

**PoC:**
```
Raw path:     /tmp/<tmpdir>/.claude/memory/.staging/legit-input.json
Symlink ->    /tmp/<tmpdir>/outside/evil.json
Resolved:     /tmp/<tmpdir>/outside/evil.json
in_staging:   False
in_tmp:       True    <-- passes because resolved starts with /tmp/
```

However, symlinks to paths OUTSIDE `/tmp/` are correctly rejected:
```
Symlink to /etc/hostname:  REJECTED (resolved not in /tmp/ or .staging/)
Symlink to ~/.bashrc:      REJECTED (resolved not in /tmp/ or .staging/)
```

**Impact:** Low. The `/tmp/` allowance is intentional per spec (the Write tool may place files there). Any file under `/tmp/` can already be passed directly as `--input-file /tmp/anything.json` without a symlink. The symlink adds no additional capability.

**Recommendation:** No action needed. This is working as designed.

---

## Finding 6: Extra Fields in Partial JSON Correctly Ignored

**Severity:** INFORMATIONAL (no vulnerability)
**Type:** Input validation verification

**Description:**
I attempted to inject `record_status`, `id`, `created_at`, and arbitrary extra fields via the partial JSON input. All were correctly handled:

| Injected Field | Result |
|---------------|--------|
| `"record_status": "retired"` | Ignored. Draft uses `"active"` (hardcoded in `assemble_create()`) |
| `"id": "evil-id"` | Ignored. Draft uses `slugify(title)` |
| `"created_at": "1970-01-01T00:00:00Z"` | Ignored. Draft uses `now_utc()` |
| `"evil_key": "value"` | Ignored. Not extracted by `assemble_create()` |

**Verdict:** The allowlist extraction pattern in `assemble_create()` and `assemble_update()` correctly prevents field injection. No vulnerability.

---

## Finding 7: Non-Memory JSON and Wrong-Category Candidates Correctly Rejected

**Severity:** INFORMATIONAL (no vulnerability)
**Type:** Candidate file manipulation verification

**Description:**
Three candidate manipulation attacks were tested:

| Attack | Result |
|--------|--------|
| Non-memory JSON as `--candidate-file` (random fields) | REJECTED: Pydantic `extra="forbid"` catches unknown fields |
| Wrong-category candidate (preference as decision) | REJECTED: `Literal['decision']` constraint fails |
| Malicious candidate with prompt injection in title | ACCEPTED: This is by design -- UPDATE merges from existing, and the input's title overrides the existing title |

**Verdict:** Pydantic validation with `extra="forbid"` and category literal types provide strong defense against candidate file manipulation. The malicious content case (attack 9c) is expected behavior -- if the existing memory file already contains malicious content, an UPDATE preserves it (which is correct, since that data was already stored).

---

## Finding 8: No Race Condition in Draft Filenames

**Severity:** INFORMATIONAL (no vulnerability)
**Type:** Concurrency verification

**Description:**
10 concurrent `memory_draft.py` invocations all produced unique draft filenames. The filename pattern `draft-{category}-{ts}-{pid}.json` uses per-process PIDs, and since each subprocess invocation has a unique PID, collisions are impossible in the standard invocation pattern.

**Verification:** 10/10 concurrent drafts succeeded with 10/10 unique paths.

---

## Finding 9: Import Hijacking Not Exploitable

**Severity:** INFORMATIONAL (no vulnerability)
**Type:** Supply chain verification

**Description:**
Attempted to hijack imports by placing a malicious `memory_write.py` in the cwd and via PYTHONPATH. Both failed because:

1. `memory_draft.py` inserts its own script directory (`hooks/scripts/`) at `sys.path[0]` (line 42-43), which takes precedence over cwd and PYTHONPATH
2. The venv bootstrap re-execs under the plugin's venv python, which further isolates the import path

**Verdict:** Not exploitable. The `sys.path.insert(0, _script_dir)` pattern provides effective import isolation.

---

## Finding 10: Null Values and Type Mismatches Correctly Rejected

**Severity:** INFORMATIONAL (no vulnerability)
**Type:** Input validation verification

**Description:**
| Input | Result |
|-------|--------|
| All fields set to `null` | REJECTED: Pydantic VALIDATION_ERROR |
| Tags as integer (42) | REJECTED: Pydantic VALIDATION_ERROR |
| Change summary > 300 chars | REJECTED: Pydantic `max_length=300` on ChangeEntry.summary |
| Title > 120 chars (10KB) | REJECTED: Pydantic `max_length=120` on title |

Pydantic validation in memory_draft.py catches all type and constraint violations before the draft is written.

---

## What Previous Reviews Missed

### Missed by security review:
- **Finding 1 (Unicode Cf chars):** The security review noted control char stripping but did not identify that Unicode format characters (category Cf) are not covered by the `[\x00-\x1f\x7f]` regex. This is the most significant finding.

### Missed by code-level review:
- **Finding 2 (dict-as-title):** The code review traced `str(input_data.get("title", ""))` but did not flag the case where `title` is not a string.

### Correctly identified by previous reviews (confirmed):
- Candidate path containment check IS present (security review Finding 3 was based on incomplete code -- R1 code review correctly noted this)
- No merge protection duplication (design review confirmed)
- Extra fields correctly ignored via allowlist pattern (security review Finding 5 self-confirmed)

---

## Summary Table

| # | Finding | Severity | Exploitable? | Action |
|---|---------|----------|-------------|--------|
| 1 | Zero-width/RTL chars survive full pipeline | MEDIUM | Indirect (requires LLM confusion) | Extend auto_fix to strip Unicode Cf category |
| 2 | Dict-as-title passes through | LOW | Requires confused LLM | Optional: add isinstance check |
| 3 | 1000 tags pass draft (mitigated by write) | LOW | No data integrity impact | Optional: add draft-level cap |
| 4 | Index delimiter injection mitigated end-to-end | INFO | Not exploitable | No action (working as designed) |
| 5 | Symlink via /tmp/ allowance | LOW | No added capability | No action (by design) |
| 6 | Extra field injection blocked | INFO | Not exploitable | No action |
| 7 | Non-memory/wrong-category candidates rejected | INFO | Not exploitable | No action |
| 8 | No race condition in filenames | INFO | Not exploitable | No action |
| 9 | Import hijacking not possible | INFO | Not exploitable | No action |
| 10 | Type mismatches/nulls rejected by Pydantic | INFO | Not exploitable | No action |

---

## Overall Verdict

**PASS with 1 medium advisory.**

The implementation is robust against adversarial attack. The one actionable finding (Finding 1: Unicode format characters) is a pre-existing gap in `memory_write.py`'s `auto_fix()` that affects the entire pipeline, not just the new `memory_draft.py` code. All other attacks are either correctly blocked or correctly mitigated by the defense-in-depth chain.

The defense-in-depth architecture works as designed:
- memory_draft.py does ASSEMBLY (no sanitization, by spec)
- memory_write.py does ENFORCEMENT (sanitization, merge protections, validation)
- Pydantic with `extra="forbid"` catches schema violations
- Index delimiter injection is sanitized before index building

**Confidence level:** HIGH. I executed real attack scripts against the actual code, verified end-to-end through the full pipeline, and all critical security boundaries held.
