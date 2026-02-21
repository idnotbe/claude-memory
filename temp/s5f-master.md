# Session 5 Follow-up -- Hardening & Tests Master Plan

**Date:** 2026-02-21
**Status:** COMPLETE
**Scope:** Fix 3 follow-up items from S5 V2 verifications + unit tests

---

## Follow-up Items (from S5 V2 verifications)

### F1: Tag-Based Confidence Spoofing [MEDIUM]
**Source:** V2-adversarial Finding 2, V2-independent IF-2
**Problem:** Tags containing `[confidence:high]` pass through both write-side and read-side sanitization. Brackets survive `html.escape()`. Output shows dual conflicting labels.
**Fix approach (two-layer defense):**
- **Write-side** (`memory_write.py:316-320`): Strip `[confidence:*]` from tag values in `auto_fix()` tag sanitization
- **Read-side** (`memory_retrieve.py:288`): Strip `[confidence:*]` from individual tag values before joining in `_output_results()`

### F2: Path-Based Confidence Injection [LOW]
**Source:** V2-adversarial Finding 3
**Problem:** Directory names with brackets (e.g., `[confidence:high]/`) survive path containment checks and `html.escape()`.
**Fix approach:** Validate directory components in `memory_write.py` target path handling. Directory names should match `[a-z0-9_.-]` pattern. The `slugify()` function already enforces this for file stems; extend to directory components.
**Note:** V2-adversarial (2nd agent) said this is NOT exploitable through the API due to `slugify()`. Need to verify.

### F3: Unit Tests for `confidence_label()` [LOW]
**Source:** All reviewers noted this gap
**Tests needed:**
- Boundary ratios (0.75 exact, 0.7499, 0.40 exact, 0.3999)
- Zero scores (best=0, score=0)
- Single result (ratio=1.0)
- All same scores (all ratio=1.0)
- NaN, Inf, -0.0 edge cases
- Missing score key (defaults to 0)
- Integration test: verify `[confidence:*]` appears in `_output_results()` output

### F4: Nested Regex Bypass [LOW]
**Source:** V2-adversarial (2nd agent) Finding F2
**Problem:** `[confid[confidence:x]ence:high]` -> after single-pass strip -> `[confidence:high]`
**Fix approach:** Run the regex strip in a loop until no more matches, OR apply it twice.

---

## Task Breakdown

1. **Implementation** -- Apply all 4 fixes
2. **Security review** -- Review fixes for correctness and completeness
3. **Correctness review** -- Verify edge cases and backward compatibility
4. **V1 verification** (2 perspectives: functional + integration)
5. **V2 verification** (2 perspectives: adversarial + independent)

---

## Key Files
- `hooks/scripts/memory_retrieve.py` (lines 144-159, 263-293) -- read-side fixes
- `hooks/scripts/memory_write.py` (lines 310-327, 645-668) -- write-side fixes
- `tests/test_memory_retrieve.py` -- new unit tests

---

## Log
- [start] Master plan created
- [phase 1 complete] All 4 fixes implemented. 633/633 tests pass (27 new).
  - Report: temp/s5f-implementer-output.md
- [phase 2 - correctness review] APPROVE with 1 HIGH finding:
  - HIGH: 3-deep nested tag bypass (write+read-side both use single-pass)
  - MEDIUM: Unicode confusable bypass (future)
  - MEDIUM-LOW: Whitespace variant bypass (future)
  - LOW: regex compiled inside loop
  - Report: temp/s5f-review-correctness.md
- [hotfix applied] Nested loop added to both write-side and read-side tag sanitization.
  - Also moved regex compile to module-level in _output_results.
  - Compile check PASSED, 633/633 tests PASS
- [phase 2 - security review] APPROVE WITH CONDITIONS:
  - RC1 BLOCKING: Regex `[a-z]+` too narrow (whitespace, unicode bypasses)
  - RC2 MEDIUM: Inconsistent sanitization surfaces (paths, write-side titles)
  - RC3 MEDIUM: Single-pass tag sanitization (already fixed by hotfix above)
  - Report: temp/s5f-review-security.md
- [hotfix 2 applied] Addressed all review findings:
  - RC1: Broadened regex to `\[\s*confidence\s*:[^\]]*\]` in ALL locations (module-level constant)
  - RC2-B4: Added path sanitization in _output_results
  - RC2-B5: Added write-side title confidence stripping in auto_fix()
  - RC2-B6: _check_dir_components on CREATE only (acceptable -- update/retire act on existing files)
  - Compile check PASSED, 633/633 tests PASS
- [phase 3 started] V1 verification round (functional + integration)
- [phase 3 complete] Both V1 verifications PASS:
  - V1-functional: 633/633 tests, all fixes correct, 2 residual (fullwidth colon, ZWS in tags)
  - V1-integration: 633/633 tests, no downstream breakage, 1 LOW (path single-pass)
  - Reports: temp/s5f-v1-functional.md, temp/s5f-v1-integration.md
- [phase 4 started] V2 verification round (adversarial + independent)
- [phase 4 complete] V2 verifications done:
  - V2-adversarial: CONDITIONAL FAIL -- 4 new Unicode bypasses (Mn/Cf category gaps in tags)
    - Recommends P0 (Cf+Mn tag strip), P1 (path while loop), P3 (XML attr migration)
    - Report: temp/s5f-v2-adversarial.md
  - V2-independent: APPROVE with residuals (ZWS in tags, path single-pass, fullwidth colon)
    - Report: temp/s5f-v2-independent.md
- [hotfix 3 applied] Addressed V2 adversarial P0/P1/P2 findings:
  - P0: Added Cf+Mn stripping to tag pipeline (both write-side and read-side)
  - P1: Added while loop to path sanitization in _output_results
  - P2: Extended write-side AND read-side title Cf filter to also strip Mn category
  - Compile check PASSED, 633/633 tests PASS
- [SESSION S5F COMPLETE] All phases done. Remaining follow-ups:
  - P3 STRATEGIC: Migrate confidence annotation from inline text to XML attributes (future session)
  - Fullwidth brackets (U+FF3B/U+FF3D) bypass -- NFKC normalization trade-off (future)
  - Cyrillic confusables (N2) -- fundamentally cannot be fixed by regex (future/architectural)
