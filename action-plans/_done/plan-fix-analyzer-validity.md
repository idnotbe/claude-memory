---
status: done
progress: "2026-03-22 구현 완료. 253/253 tests pass. Items 1-2 done, 3-4 deferred."
---

# Fix: Analyzer Validity Guards

## Origin

Log review 2026-03-22에서 식별. `ZERO_LENGTH_PROMPT` CRITICAL false positive이 N=4 이벤트에서 80% 비율 계산으로 발생.

## Problem

`memory_log_analyzer.py`의 비율 기반 탐지기들이 작은 표본에서도 높은 severity 알림을 생성:
- `_detect_zero_length_prompt`: N=1 skip 이벤트에서도 100% = CRITICAL 발생 가능
- `_detect_skip_rate_high`: 마찬가지
- `_detect_category_never_triggers`: 버전 경계 인식 없이 혼합 윈도우에서 판단

## Required Changes

### 1. Minimum sample size guard
- [v] `_detect_zero_length_prompt`: N >= 10 skip events required
- [v] `_detect_skip_rate_high`: N >= 20 retrieval events required
- [v] `_detect_category_never_triggers`: N >= 30 triage.score events required
- [v] `_detect_error_spike`: N >= 10 per-category events required (bonus, same bug class)

### 2. Booster-hit-rate metric
- [v] `score_text_category` → 4-tuple return (expose `primary_count`, `boosted_count`)
- [v] `score_all_categories` → include `primary_hits`/`booster_hits` in output
- [v] 새 탐지기 `_detect_booster_never_hits`: N >= 50 new-format triage events, per-category, SESSION_SUMMARY 제외
- [v] Mixed old/new format 안전 처리 (`new_format_count` 기반 guard)
- [v] Recommendation wiring in `_generate_recommendations`

### 3. Version boundary awareness (optional, lower priority)
- [ ] `plugin_version` 필드를 JSONL 이벤트 스키마에 추가
- [ ] 분석기가 버전별로 메트릭 분리
- [ ] 혼합 버전 윈도우 감지 시 경고

### 4. Snapshot discipline (optional)
- [ ] 분석 시작 시 cutoff timestamp 기록
- [ ] 라이브 로그 변동 감지 및 경고

## Testing
- [v] 기존 테스트 regression 없음 (triage 97 + logger 116)
- [v] 새 테스트 40개: 최소 표본 미달 시 None/[] 반환 확인
- [v] Edge case: N=0, N=threshold-1, N=threshold, N=threshold+1
- [v] Booster: old format, mixed format, SESSION_SUMMARY 제외, zero-primary 미탐지
- [v] 최종: 253/253 passed

## Cross-Model Validation
- Opus 4.6 (설계 + vibe check + V1/V2 자체 검증)
- Codex 5.3 (설계 + V1 correctness: `or`→`and` 수정 발견)
- Gemini 3.1 Pro (설계 + V1/V2: error_spike guard 추가 제안)

## Files Changed
- `hooks/scripts/memory_log_analyzer.py` — 5 constants, 4 guards, 1 new detector, 1 recommendation
- `hooks/scripts/memory_triage.py` — 4-tuple return, primary_hits/booster_hits 노출, docstring 업데이트
- `tests/test_log_analyzer.py` — NEW (40 tests)
- `tests/test_memory_logger.py` — test_only_expected_keys 업데이트

## Known Future Work
- Skip rate denominator 문제 (all retrieval.* vs prompt attempts)
- Perf degradation per-day sample guard
- Pre-existing type-safety hardening (non-numeric field values)
- Per-category minimum for CATEGORY_NEVER_TRIGGERS / BOOSTER_NEVER_HITS
