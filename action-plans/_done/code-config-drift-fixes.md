---
status: done
progress: "전체 완료. Phase 1-3 all done. 5개 파일 변경, 6회 독립 검증 (codex+gemini cross-verify 포함)"
---

# Action Plan: Code/Config Drift Fixes (v6.0.0)

**Goal**: PRD/Architecture 현행화 과정에서 발견된 코드/설정 불일치 수정
**Parent Plan**: `action-plans/update-prd-architecture-v6.md` (문서 현행화)
**Note**: 문서 업데이트와 분리하여 코드 변경만 수행
**Evidence**: `temp/phase1-draft.md`, `temp/phase2-draft.md`, `temp/phase3-final-report.md`
**Verification**: `temp/phase1-verify-r1.md`, `temp/phase1-verify-r2.md`, `temp/phase2-verify-r1.md`, `temp/phase2-verify-r2.md`

---

## Phase 1: Config/Doc Drift 수정

- [v] Step 1.1: RUNBOOK threshold 통일
  - `hooks/scripts/memory_triage.py` DEFAULT_THRESHOLDS["RUNBOOK"] = 0.5
  - `assets/memory-config.default.json` runbook threshold = 0.4
  - **결정: 0.5로 통일** (code 기준). 코드 주석에 의도적 인상 이유 명시 ("Raised from 0.4: reduces SKILL.md keyword contamination false positives")
  - **변경**: `assets/memory-config.default.json:72` — `0.4` → `0.5`
  - 테스트 확인: `pytest tests/test_memory_triage.py -v` PASS

- [v] Step 1.2: SKILL.md max_inject default 수정
  - `skills/memory-management/SKILL.md`에서 "default: 5" → "default: 3"
  - 실제 default: code 3 (`memory_retrieve.py:551,567,571`), config 3 (`memory-config.default.json:51`)
  - **변경**: `skills/memory-management/SKILL.md:329` — `(default: 5)` → `(default: 3)`

- [v] Step 1.3: SKILL.md staging path 업데이트
  - `/tmp/.claude-memory-staging-<hash>/` → XDG 기반 설명으로 변경
  - `memory_staging_utils.py`의 `_resolve_staging_base()` 참조: XDG_RUNTIME_DIR > /run/user/$UID > macOS confstr > ~/.cache (No /tmp/ fallback)
  - **변경**: `skills/memory-management/SKILL.md:38-44` — 4-tier XDG 해결 설명으로 전면 개작
  - **추가 발견**: `SKILL.md:55` Pre-Phase recovery path에도 `<resolved_tmp>` 잔존 → `<staging_base>` + `UID:realpath(project_path)`로 수정
  - **테스트 회귀**: `tests/test_regression_popups.py:762-768` `test_staging_uses_tmp_prefix` assertion이 `/tmp/` 제거로 실패 → `test_staging_uses_xdg_tier_description`으로 교체, 에러 메시지(L759) 및 class docstring(L741-742)도 XDG 반영

## Phase 2: Version Metadata 수정

- [v] Step 2.1: plugin.json version bump
  - `.claude-plugin/plugin.json`: "5.1.0" → "6.0.0"
  - **변경**: `.claude-plugin/plugin.json:3` — `"version": "5.1.0"` → `"version": "6.0.0"`

- [v] Step 2.2: hooks.json description 업데이트
  - `hooks/hooks.json`: description의 "v5.0.0" → "v6.0.0"
  - **변경**: `hooks/hooks.json:2` — `"v5.0.0:"` → `"v6.0.0:"`

## Phase 3: 검증

- [v] Step 3.1: 테스트 실행
  - `pytest tests/ -v` — 1537 passed (21 pre-existing `test_triage_observability` stdin 환경 이슈 — isolation 실행 시 34/34 pass 확인)
  - 모든 hook 스크립트 `py_compile` 통과 (16개)

- [v] Step 3.2: Config/code 일관성 확인
  - grep 감사 7개 쿼리 실행: 운영 파일에 stale 값 0건
  - codex + gemini 최종 cross-verify: APPROVED

---

## 변경 파일 목록

| # | File | Line(s) | Change |
|---|------|---------|--------|
| 1 | `assets/memory-config.default.json` | 72 | RUNBOOK threshold 0.4 → 0.5 |
| 2 | `skills/memory-management/SKILL.md` | 38-44 | staging description → XDG 4-tier |
| 3 | `skills/memory-management/SKILL.md` | 55 | recovery path → staging_base |
| 4 | `skills/memory-management/SKILL.md` | 329 | max_inject default 5 → 3 |
| 5 | `tests/test_regression_popups.py` | 741-742, 759, 762-769 | test + docstring XDG 반영 |
| 6 | `.claude-plugin/plugin.json` | 3 | version 5.1.0 → 6.0.0 |
| 7 | `hooks/hooks.json` | 2 | description v5.0.0 → v6.0.0 |

## Follow-up Items (out of scope)

검증 중 codex/gemini 양측에서 일관적으로 flagged된 범위 외 drift:
1. `README.md`: runbook=0.4→0.5, max_inject=5→3, v5.0.0→v6.0.0
2. `commands/memory-config.md`: runbook=0.4→0.5, max_inject=5→3
3. `docs/architecture/architecture.md`: /tmp/ staging refs, hash description
4. `docs/requirements/prd.md`: RUNBOOK threshold 0.4→0.5
