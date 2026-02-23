# Guardian Permission Popup Research - Search Summary

**Date:** 2026-02-22
**Task:** Find research files about memory saving permission popups

---

## Found Files

### Primary Documents

| File | Type | Description |
|------|------|-------------|
| `research/guardian-memory-pretooluse-conflict.md` | Research (complete) | Master analysis - root cause, fix design, V1/V2 verification (8 agents, 6 reviewers) |
| `action-plans/plan-guardian-conflict-memory-fix.md` | Action Plan | Implementation plan for immediate fixes C1+C2 (~45min) |

### Supporting Temp Files (9 files)

| File | Contents |
|------|----------|
| `temp/guardian-conflict-investigation.md` | Root cause trace (investigator-guardian) |
| `temp/guardian-conflict-memory-side.md` | Memory plugin analysis (investigator-memory) |
| `temp/guardian-conflict-fix-design.md` | Fix design with pseudocode (architect) |
| `temp/guardian-conflict-v1-code.md` | V1 code correctness review |
| `temp/guardian-conflict-v1-security.md` | V1 security review |
| `temp/guardian-conflict-v1-ux.md` | V1 UX review |
| `temp/guardian-conflict-v2-adversarial.md` | V2 adversarial review |
| `temp/guardian-conflict-v2-crossmodel.md` | V2 cross-model review (Codex/Gemini) |
| `temp/guardian-conflict-v2-practical.md` | V2 practical implementation review |

---

## Action Plan Status

**File:** `action-plans/plan-guardian-conflict-memory-fix.md`
**Status:** `not-started`
**Progress:** "미시작. 독립 실행 가능 (~45분). SKILL.md 강화 + staging guard"

### What the plan covers (2 fixes):
1. **C2: `memory_staging_guard.py` 생성** (20min) - PreToolUse:Bash guard that denies heredoc writes to `.staging/`
2. **C1: SKILL.md 강화** (10min) - Strengthen prohibition wording + anti-pattern example
3. **Tests** (15min) - 15 test cases + pytest file

### Implementation order decided: C2 -> C1 (hard guard first, then soft prompt)

---

## Problem Summary (for context)

Memory subagents (especially haiku) use Bash heredoc (`cat > path << 'EOFZ'`) instead of Write tool to create staging JSON files. Guardian's `bash_guardian.py` has no heredoc awareness, causing:
- **Failure A:** `>` in JSON body triggers false write detection -> popup
- **Failure B:** `.env` string in JSON body triggers protected path detection -> popup
- **Result:** 7 popups in 20 hours, disrupting user workflow

---

## Self-Review Checklist

- [x] Searched action-plans/ folder - found `plan-guardian-conflict-memory-fix.md`
- [x] Searched research/ folder - found `guardian-memory-pretooluse-conflict.md`
- [x] Checked temp/ folder - found 9 supporting investigation/review files
- [x] Read both primary files fully
- [x] Confirmed action plan frontmatter status: `not-started`
- [x] No other action plans or research files about this specific topic found
