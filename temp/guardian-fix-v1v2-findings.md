# V1/V2 Review Findings on Limitations Section

## Critical Findings (must fix)

### 1. ReDoS fix is INEFFECTIVE (REFUTED by both V1 and V2)

**Wrong diagnosis in doc:** "overlap between `[^|&;\n]*` and `\s*`"
**Actual root cause:** overlap between `\s+` (after cat/echo/printf) and `[^|&;\n>]*` — BOTH consume whitespace

The `>` exclusion we applied does NOT fix the O(N^2) backtracking for whitespace-heavy inputs.
- Before fix: 32K spaces → ~2.4s
- After fix: 32K spaces → ~2.4s (IDENTICAL)

**Correct fix:** `[^|&;\n>]*` → `[^|&;\n>\s]*` (exclude WHITESPACE from the character class)
This forces `\s+` to consume ALL whitespace, and `[^|&;\n>\s]*` matches only non-whitespace args.

### 2. Hook timeout fail-open NOT documented

If ReDoS causes timeout (5s), Claude Code fails open → Bash write proceeds unblocked.
This is a direct consequence of the unfixed ReDoS.

### 3. Documentation errors in limitations section

- Double-slash rationale wrong: says "Linux normalizes at runtime" but regex operates on raw string, never reaches filesystem
- ReDoS mechanism description wrong (overlap pair misidentified)
- ReDoS status should be "수정" only after the real fix is applied
- Missing bypasses: rsync/curl/wget, path traversal (../), not in summary table

### 4. Severity rating inconsistency

- Shell variable: rated LOW-MEDIUM but V2 source rated LOW. V2 adversarial says should be MEDIUM.
  Decision: keep LOW-MEDIUM as compromise between the two views.

## Action Plan -- ALL DONE

1. [x] Fix regex: `[^|&;\n>]*` → `[^|&;\n>\s]*` in memory_staging_guard.py
2. [x] Run tests: 24/24 passed
3. [x] Rewrite ReDoS section with correct diagnosis (`\s+` vs `[^|&;\n]*` overlap)
4. [x] Add missing bypasses: rsync/curl/wget (항목 5), path traversal (항목 6)
5. [x] Fix double-slash rationale (regex operates on raw string, not filesystem)
6. [x] Add hook timeout fail-open note
7. [x] Add "솔직한 한계 인정" paragraph about structural C1/C2 dependency

## Round 2 Verification Results

- V1-R2: ALL 9 ITEMS PASS
- V2-R2: 5 CONFIRMED, 2 CHALLENGED (low impact), 0 REFUTED
  - CHALLENGED: p1/p4 "상호 보완" → technically p4 is superset (minor phrasing)
  - CHALLENGED: C1 failure headline could be clearer (qualifier present in text)
