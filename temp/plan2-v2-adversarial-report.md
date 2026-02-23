# V2 Adversarial Report: plan-search-quality-logging.md

**Reviewer:** v2-adversarial
**Date:** 2026-02-22
**Target:** Three edits to `action-plans/plan-search-quality-logging.md`
**External Validation:** Gemini 3.1 Pro (codereviewer via pal clink), Gemini 3 Pro (vibe-check via pal chat)
**Codex 5.3:** Unavailable (usage limit reached)

---

## Executive Summary

**Overall Verdict: APPROVE WITH 1 MEDIUM ISSUE, 2 LOW ISSUES, 2 NOTES**

The three edits (session-ID solution, implementation order, rollback strategy) are substantively correct and well-sourced. No critical or high-severity issues found. One medium-severity issue was discovered: the Phase 3/4 parallelism claim has a file overlap that the plan doesn't acknowledge. Two low-severity issues and two cosmetic notes round out the findings.

The duplicate H2 rollback section identified by V1 reviewers has been successfully removed -- only the H3 subsection under "Risks & Mitigations" remains.

---

## Attack 1: Session-ID (Lines 141-142)

### 1a) Accuracy of the solution description

**STATUS: PASS**

The plan states:
> `--session-id` CLI 파라미터 + `CLAUDE_SESSION_ID` 환경변수 폴백을 통해 CLI 모드에서도 session_id를 전달할 수 있다. 우선순위: `--session-id CLI 인자 > CLAUDE_SESSION_ID 환경변수 > 빈 문자열`.

Cross-referenced against `temp/41-finding4-5-integration.md` section 2.3:
> Precedence: --session-id CLI arg > CLAUDE_SESSION_ID env var > empty string

Exact match. The implementation detail (`argparse` param + `os.environ.get()` fallback) is accurate and consistent with the source.

### 1b) ~12 LOC estimate includes Phase 2 dependency

**STATUS: NOTE (not an inaccuracy, but a subtlety)**

The plan says "~12 LOC 추가로 구현 (argparse 파라미터 추가 + os.environ.get() 폴백 + emit_event() 전달)". The source (`temp/41-finding4-5-integration.md` Appendix) breaks this down as: argparse (3) + resolution (1) + emit_event call (8) = 12 LOC.

The `emit_event()` call (8 LOC) depends on `memory_logger.py` existing (Phase 2 of this plan). Without Phase 2, the emit_event call compiles but is a noop via the lazy import fallback. So the ~12 LOC can be deployed at any time -- 4 LOC will be functional immediately (argparse + resolution), and the remaining 8 LOC become active when Phase 2 completes.

This is technically correct but could mislead an implementer into thinking Finding #4 delivers 12 LOC of functional value independent of Phase 2. The plan partially addresses this by stating "SKILL.md 변경 불필요" and explaining the env var forward-compatibility, but doesn't explicitly note the Phase 2 dependency of the emit_event portion.

**Severity: NOTE** -- Not an inaccuracy, merely an unstated dependency that's implicit from the plan structure (Finding #4 session-id is part of Phase 3, which is after Phase 2).

### 1c) SKILL.md assertion correctness

**STATUS: PASS**

The plan states "SKILL.md 변경 불필요 -- 현재 `CLAUDE_SESSION_ID` 환경변수가 없으므로 skill 측 전파는 불가하나, 향후 Claude Code가 해당 환경변수를 노출하면 코드 변경 없이 자동 적용된다."

Verified against:
- `temp/41-finding4-5-integration.md` section 2.4: "Do NOT instruct the LLM to pass `--session-id` in SKILL.md yet."
- `temp/41-finding4-5-integration.md` section 2.2: Confirmed `CLAUDE_SESSION_ID` env var does not exist in the runtime environment.
- Actual `skills/memory-search/SKILL.md` invocation: No `--session-id` in the command template.

All accurate.

### 1d) Edge cases not mentioned

**STATUS: PASS**

Checked for:
- Null bytes in `--session-id`: Structurally impossible per `temp/41-v2-adversarial.md` Attack 3a (Unix `execve` constraint).
- Extremely long session_id: Local tool, not meaningful attack surface per source.
- Session_id injection: Only written to JSONL logs, never to stdout/prompt context.

The source documents address these edge cases thoroughly. The plan summary at lines 141-142 appropriately omits them (implementation detail, not plan-level concern).

### Attack 1 Verdict: PASS (1 NOTE)

---

## Attack 2: Implementation Order (Lines 327-354)

### 2a) Phase 3/4 parallelism claim -- file overlap

**STATUS: MEDIUM ISSUE**

The plan at line 336 states:
> 두 Phase가 수정하는 파일이 다름 (Phase 3: `memory_retrieve.py`, `memory_judge.py`, `memory_search_engine.py` / Phase 4: `memory_triage.py`, 기존 stderr 출력)

This claim is **partially incorrect**. Phase 4's scope is "기존 stderr [DEBUG]/[WARN]/[INFO] 출력을 로거 호출로 대체" (line 384). The existing stderr outputs are located in:

| stderr output | File | Line |
|---------------|------|------|
| `[DEBUG] judge parallel: ...` | `memory_judge.py` | 347 |
| `[DEBUG] judge call: ...` | `memory_judge.py` | 360 |
| `[WARN] FTS5 unavailable; using keyword fallback` | `memory_retrieve.py` | 466 |

**`memory_judge.py` and `memory_retrieve.py` are in BOTH Phase 3's and Phase 4's file lists.** Phase 3 adds new instrumentation to these files; Phase 4 replaces existing stderr lines in the same files.

While the two phases touch different code regions within the files (Phase 3: new emit_event() calls near search/judge logic; Phase 4: replacing existing `print(..., file=sys.stderr)` lines), parallel execution creates merge conflict risk if both branches modify nearby code.

**External validation:** Gemini 3 Pro (vibe-check) flagged this as "guaranteed merge conflict" -- "Phase 3 Dev: Refactors logic in `memory_judge.py`. Phase 4 Dev: Deletes `print(..., file=sys.stderr)` lines in `memory_judge.py` and replaces them with `logger.debug()`. The Result: This is a guaranteed merge conflict."

**Counter-argument:** In a single-developer workflow (which this plugin is), "parallel" may mean "conceptually independent" rather than "git-branch parallel". The plan's Phase dependency diagram shows them as conceptually parallelizable. If one developer does Phase 3 then Phase 4 serially within the same branch, the overlap is a non-issue.

**However**, the plan explicitly claims "두 Phase가 수정하는 파일이 다름" (the two phases modify different files) which is factually incorrect for `memory_judge.py` and `memory_retrieve.py`. The claim should be corrected.

**Recommendation:** Amend line 336 to acknowledge the file overlap:
- Phase 3 and Phase 4 both touch `memory_retrieve.py` and `memory_judge.py`, but in different code regions (Phase 3: new instrumentation near search/judge pipelines; Phase 4: replacing existing stderr at lines 347, 360, 466).
- Parallel execution is feasible if changes are coordinated, but the "different files" claim is incorrect.

**Severity: MEDIUM** -- The parallelism itself is not unsafe (different code regions), but the stated rationale ("파일이 다름") is factually wrong, which could mislead an implementer or reviewer.

### 2b) TDD overlap for Phase 5

**STATUS: PASS**

The plan at line 336 states: "Phase 5 (테스트)는 Phase 3+4 완료 후 최종 벤치마크 실행하되, Phase 2/3/4 진행 중에도 TDD 방식으로 단위 테스트 점진적 작성 가능."

This is a reasonable claim. TDD means writing tests alongside implementation. The Phase 5 checklist (lines 387-399) includes both unit tests and a final benchmark. Unit tests can be written during Phase 2-4; the benchmark requires Phase 3+4 completion. The plan correctly distinguishes these.

### 2c) Cross-plan dependency assertions

**STATUS: PASS**

| Plan | Claimed Relationship | Verified |
|------|---------------------|----------|
| Plan #1 | Independent, parallel execution possible | Correct -- Plan #1 modifies `memory_retrieve.py` confidence/output logic, Plan #2 adds logging. Different concerns. |
| Plan #3 | Depends on Plan #2 | Correct -- Plan #3 PoC experiments require logging data. Source: `temp/41-final-report.md` Finding #4 and plan line 351. |

The nuance "최종 계측(Phase 3)은 Plan #1 수정 반영 후가 이상적" (line 350) is accurate -- if Plan #1 changes the confidence labeling logic, Phase 3 instrumentation should capture the final code state.

### 2d) Phase ordering rationale

**STATUS: PASS**

The 5-point rationale (lines 340-344) follows a logical "contract-first -> core primitive -> edge integration -> validation -> documentation" pattern. The "Schema Discovery Risk" note (line 342: "Phase 4에서 스키마 누락 필드 발견 시 Phase 1 계약 수정 필요할 수 있음") acknowledges a realistic feedback loop.

### Attack 2 Verdict: 1 MEDIUM ISSUE (Phase 3/4 file overlap claim is factually incorrect)

---

## Attack 3: Rollback Strategy (Lines 420-431)

### 3a) Scenario where stated rollback would NOT work

**STATUS: LOW ISSUE -- "Blind state" after full rollback post-Phase 4**

The "전체" row (line 427) says: "`logging` 설정 키 제거 → 기본값 `false`로 폴백". This disables new JSONL logging. But if Phase 4 has already completed (old stderr logging removed), the system enters a "zero observability" state -- neither new JSONL logs nor old stderr debug output.

**Gemini 3.1 Pro flagged this:** "If the 'Overall' rollback is triggered after Phase 4, the system is left with zero observability -- neither the new JSONL logs nor the legacy stderr logs."

**Counter-argument:** The "전체" row represents a config-level disable, not a code rollback. A true "undo everything" rollback would be `git revert` of all commits, which restores stderr. The table treats "전체" as a quick disable switch, which is valid for its stated purpose (zero-config full disable of the new feature).

**However**, the plan should note that post-Phase 4, the "전체" config-only rollback leaves the system without any debug observability. A full rollback (restoring stderr) requires reverting Phase 4 code changes, not just config.

**Severity: LOW** -- The config rollback IS safe for core functionality (fail-open). The observability gap is a quality-of-debugging issue, not a correctness issue.

### 3b) Phase 1 exclusion from rollback table

**STATUS: LOW ISSUE**

Phase 1 (schema contract) is excluded. Phase 1's deliverables are:
1. JSONL schema definition (documentation)
2. `assets/memory-config.default.json` with `logging` section added (config file)

The schema definition is harmless to leave behind. The config file change adds default keys that are inert (`logging.enabled: false`).

**Gemini 3.1 Pro flagged this:** "Leaving a 'zombie' default configuration for a rolled-back feature creates technical debt."

**Counter-argument:** The config defaults to `false`, so the zombie config key has zero runtime impact. Removing it requires a config migration or version bump, which is more disruptive than leaving an inert key. This is a valid design choice for a "forward-compatible" config.

**Severity: LOW** -- Technically a gap in the rollback table, but pragmatically correct to omit. A note acknowledging this would be thorough but not critical.

### 3c) Phase 2 rollback: noop fallback completeness

**STATUS: PASS (Gemini false positive debunked)**

Gemini 3.1 Pro flagged a "critical" issue: if `memory_logger.py` is deleted but consumer scripts import `get_session_id()`, the noop fallback only stubs `emit_event`, causing a `NameError` crash.

**This is a false positive.** Examining the plan's lazy import pattern (lines 83-89) and the source code design (`temp/41-finding4-5-integration.md` section 7.2), consumer scripts ONLY import `emit_event`:

```python
try:
    from memory_logger import emit_event
except ImportError as e:
    if getattr(e, 'name', None) != 'memory_logger':
        raise
    def emit_event(*args, **kwargs): pass
```

The `get_session_id()`, `cleanup_old_logs()`, and `parse_logging_config()` functions (lines 303-311) are **internal to `memory_logger.py`**, used by `emit_event()` implementation, not imported by consumer scripts. The plan's interface section (lines 270-312) shows these as part of the `memory_logger.py` module's internal API, not its consumer-facing exports.

The lazy import pattern is correct and complete for Phase 2 rollback.

### 3d) Phase 3 rollback via config

**STATUS: PASS**

"`logging.enabled: false` 설정 → 파일 I/O 0. emit_event() 호출은 남지만 즉시 반환."

If `memory_logger.py` exists and is imported, but `logging.enabled` is `false`, `emit_event()` should check the config and return early with zero I/O. The plan's core requirement (line 96: "파일 핸들 lazy initialization (로깅 비활성 시 파일 I/O 0)") confirms this design. The `emit_event()` calls in instrumented code become effectively free.

### Attack 3 Verdict: 2 LOW ISSUES (blind state post-Phase 4; Phase 1 omission)

---

## Attack 4: Omissions

### 4a) Deep Analysis items not reflected in this plan

**STATUS: PASS**

Checked `temp/41-final-report.md` "Newly Discovered Issues" table:

| Issue | Relevant to Plan #2? | Status |
|-------|----------------------|--------|
| NEW-1 (apply_threshold noise floor) | No -- `memory_search_engine.py` scoring, not logging | Correctly omitted |
| NEW-2 (Judge import vulnerability) | Addressed via Finding #5 lazy import pattern (lines 82-91) | Present |
| NEW-3 (Empty XML after judge rejects all) | No -- retrieval output formatting, not logging | Correctly omitted |
| NEW-4 (Ranking-label inversion) | No -- Plan #1 concern, not Plan #2 | Correctly omitted |
| NEW-5 (ImportError masks transitive failures) | Addressed via `e.name` scoping (lines 86-88) | Present |

All Plan #2-relevant items are present. No omissions detected.

### 4b) V2-adversarial "Newly Discovered Vulnerabilities" impact

**STATUS: PASS**

From `temp/41-v2-adversarial.md`:
- NEW-4 (Confidence-Ranking Inversion): Affects Plan #1's confidence labeling, not Plan #2's logging. Plan #2's logging schema correctly includes `raw_bm25`, `score`, and `body_bonus` fields (line 119) which support diagnostic analysis regardless of which score domain is used for confidence.
- NEW-5 (ImportError Masks Transitive Failures): Fully addressed in Plan #2 at lines 82-91 with `e.name` scoping.

No missing items.

### 4c) Triage migration detail

**STATUS: NOTE**

The plan's "기존 로그 마이그레이션" section (lines 247-255) mentions migrating `.staging/.triage-scores.log`. Looking at the actual triage code (`memory_triage.py:996-1015`), the current pattern uses `os.fdopen(fd, "a")` with `f.write()` -- NOT the `os.write(fd, line_bytes)` pattern that the plan specifies for the new logger (line 79).

The plan's migration section (line 251) correctly identifies this as a target: `.staging/.triage-scores.log` -> `logs/triage/{YYYY-MM-DD}.jsonl`. However, the existing triage code's use of `os.fdopen().write()` (buffered, NOT single-syscall atomic) is a pre-existing concern that the migration to the new logger's `os.write()` pattern will fix. This is correctly captured in the plan's write pattern decision (line 79) but worth noting that the migration isn't just a format change -- it's also an atomicity improvement.

**Severity: NOTE** -- Not an omission, just an unstated side-benefit of the migration.

---

## Attack 5: Regressions

### 5a) Did edits break existing content?

**STATUS: PASS**

Verified all pre-existing sections remain intact:
- YAML frontmatter (lines 1-4): Unchanged, correct
- Background section (lines 15-33): Unchanged
- Purpose section (lines 36-44): Unchanged
- Architecture decisions (lines 49-184): Unchanged (session-id fix at 141-142 replaces old content, doesn't break surrounding text)
- Logging points (lines 197-245): Unchanged
- Migration table (lines 247-255): Unchanged
- File list (lines 257-268): Unchanged
- Logger interface (lines 270-312): Unchanged
- PoC dependency mapping (lines 314-323): Unchanged
- Progress checklists (lines 357-405): Unchanged
- Risk table (lines 408-418): Unchanged
- External model consensus (lines 434-464): Unchanged
- Plan #3 dependencies (lines 468-478): Unchanged
- Review history (lines 482-493): Unchanged

### 5b) Line number references

**STATUS: PASS**

The plan does not contain internal line number cross-references. External documents (source analysis files in `temp/`) reference line numbers in the PLAN file, but those documents are already finalized and won't be consumed by implementers as line-precise references.

The V1 accuracy report (`temp/plan2-v1-accuracy-report.md`) references specific plan line numbers (e.g., "Lines 141-142", "Lines 327-354", "Lines 420-430"). These line numbers are still correct in the current file.

### 5c) Orphaned text from duplicate rollback removal

**STATUS: PASS**

The V1 reviewers identified a duplicate `## 롤백 전략 (Rollback Strategy)` at approximately line 469 (H2 standalone section). This has been removed. The current file transitions cleanly from the `### 롤백 전략` subsection (lines 420-431) through the `---` separator (line 432) to `## 외부 모델 합의` (line 434). No orphaned headings, dangling references, or leftover content from the removed duplicate.

The `## Plan #3 의존성` section (line 468) is correctly positioned after `## 외부 모델 합의` (line 434), maintaining proper document flow.

### Attack 5 Verdict: PASS -- No regressions detected

---

## External Validation Summary

| Source | Key Finding | Disposition |
|--------|------------|-------------|
| Gemini 3 Pro (vibe-check) | Phase 3/4 file overlap is "guaranteed merge conflict" | **ADOPTED** as MEDIUM issue. Validated against actual code. |
| Gemini 3 Pro (vibe-check) | Session-ID LOC estimate hides Phase 2 dependency | Noted but downgraded to NOTE (implicit from plan structure) |
| Gemini 3 Pro (vibe-check) | "전체" rollback is feature-flag disable, not true rollback | **ADOPTED** as LOW issue (blind state concern) |
| Gemini 3.1 Pro (clink) | get_session_id() not stubbed in fallback = crash | **REJECTED** (false positive: consumers only import emit_event) |
| Gemini 3.1 Pro (clink) | "Blind state" after overall rollback post-Phase 4 | **ADOPTED** as LOW issue |
| Gemini 3.1 Pro (clink) | Phase 1 config key should have rollback row | **ADOPTED** as LOW issue |
| Codex 5.3 | Unavailable (usage limit) | N/A |

---

## Issues Summary

| # | Attack | Severity | Issue | Recommendation |
|---|--------|----------|-------|----------------|
| 1 | Attack 2a | **MEDIUM** | Phase 3/4 parallelism claim states "파일이 다름" but both phases modify `memory_judge.py` and `memory_retrieve.py` (different code regions, same files) | Amend line 336 to acknowledge file overlap; state parallelism is feasible due to non-overlapping code regions, not different files |
| 2 | Attack 3a | LOW | "전체" rollback post-Phase 4 leaves system with zero observability (no JSONL, no stderr) | Add note that full rollback post-Phase 4 requires restoring stderr, not just config disable |
| 3 | Attack 3b | LOW | Phase 1 excluded from rollback table; leaves zombie config key | Acknowledge in table or add Phase 1 row (low priority -- config defaults to false) |
| 4 | Attack 1b | NOTE | ~12 LOC estimate for session-id includes 8 LOC dependent on Phase 2 (emit_event call) | No action needed -- implicit from plan structure |
| 5 | Attack 4c | NOTE | Triage migration also fixes atomicity (os.fdopen -> os.write), unstated side-benefit | No action needed -- implementation detail |

**No CRITICAL or HIGH issues found.**

---

## Confidence Statement

I am confident in this assessment because:

1. **Thorough source cross-referencing:** Every claim in the three edits was verified against the Deep Analysis source documents (`temp/41-final-report.md`, `temp/41-finding4-5-integration.md`, `temp/41-v2-adversarial.md`, `temp/41-solution-synthesis.md`).

2. **Actual code verification:** The Phase 3/4 file overlap was verified by reading the actual source files (`memory_judge.py:347,360`, `memory_retrieve.py:466`) to confirm stderr outputs exist in Phase 3's target files.

3. **External validation debunking:** Gemini's "critical" finding about `get_session_id` stubbing was investigated and debunked by examining the actual import pattern design -- consumers only import `emit_event`, not helper functions.

4. **V1 concern resolution verified:** The duplicate H2 rollback section identified by both V1 reviewers has been successfully removed without leaving orphaned content.

5. **No issues fabricated:** Each finding maps to specific line numbers and source evidence. The MEDIUM issue (Phase 3/4 file overlap) is the strongest finding, supported by both code evidence and external model consensus.
