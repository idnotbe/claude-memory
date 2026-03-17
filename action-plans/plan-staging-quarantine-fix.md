---
status: done
progress: "Phase 1-5 구현 + 10회 독립 검증 전부 PASS. 997 tests 통과."
---

# PostToolUse Staging Quarantine 버그 수정 + 관련 이슈 전체 해결

**날짜:** 2026-03-17
**범위:** PostToolUse:Write hook staging exclusion 버그 수정, 테스트 보강, 진단 개선, context 품질 향상, 성능 최적화
**의존성:** 없음 (독립 실행 가능)
**검증 소스:** Opus 4.6 분석, Codex 5.3 코드 리뷰 + 재현 테스트, 독립 검증 4회 (R1 structural, R1 adversarial, R2 final, R2 edge)
**분석 문서:** `temp/console-analysis-synthesis.md`, `temp/verify-r1-console.md`, `temp/verify-r1-alt-console.md`, `temp/verify-r2-final-console.md`, `temp/verify-r2-edge-console.md`

---

## 배경 (Background)

### 문제 현상

claude-memory의 memory save pipeline에서 PostToolUse:Write hook (`memory_validate_hook.py`)이 `.claude/memory/.staging/` 하위 임시 파일을 memory record로 잘못 판단하여 quarantine (`.invalid.<ts>` rename) 또는 deny 처리. 이로 인해:

1. JSON staging 파일 (`intent-*.json`, `input-*.json`) → schema validation 실패 → quarantine (파일 제거)
2. Non-JSON staging 파일 (`new-info-*.txt`) → "Direct write to non-JSON memory file blocked" deny
3. 하류 스크립트 (`memory_draft.py`) → `FileNotFoundError` (quarantine된 파일 참조)
4. Agent retry loop 진입 → 30-40초 작업이 **4분 8초**로 지연 (token 비용 ~10x)

### 근본 원인

`memory_write_guard.py` (PreToolUse:Write)는 `.staging/` 쓰기를 명시적으로 허용하지만 (line 57-58), `memory_validate_hook.py` (PostToolUse:Write)에는 동일한 제외 로직이 없음. PreToolUse가 허용 → 파일 생성 → PostToolUse가 quarantine하는 hook 불일치.

**핵심 통찰**: PostToolUse:Write는 Write tool 호출에만 반응. `memory_write.py`/`memory_draft.py`가 Python `open()`으로 쓰는 파일 (draft-*.json, 최종 memory record)에는 무반응. 따라서 이 hook은 staging 파일만 파괴하고 실제 memory record 보호에는 효과 없음 — backup의 backup이 primary flow를 파괴하는 상황.

### 보안 검증 (5개 소스 일치)

staging exclusion은 보안 중립적:
- `os.path.realpath()` (line 149)가 path traversal/symlink 해소 → 우회 불가
- Staging → `memory_draft.py` (field check) → `memory_write.py` (Pydantic) → final write chain 유지
- Codex 5.3 재현 테스트로 확인: staging file에 대해 deny 발생 → rename 확인

---

## 전체 이슈 목록

| # | Issue | Severity | Track | Phase |
|---|-------|----------|-------|-------|
| 1 | PostToolUse:Write staging exclusion 누락 | Critical | Hotfix | Phase 1 |
| 2 | PostToolUse staging exemption 테스트 부재 | High | Hotfix | Phase 2 |
| 3 | Pre/PostToolUse hook 간 parity drift | Medium | Hotfix | Phase 2 |
| 4 | Quarantine 진단 메시지 부실 | Medium | Hotfix | Phase 3 |
| 5 | Session summary context에 transcript 미포함 | Low | Follow-up | Phase 4 |
| 6 | Pydantic bootstrap 불필요한 overhead | Low | Follow-up | Phase 5 |

---

## 관련 파일

| 파일 | 역할 | 변경 여부 |
|------|------|----------|
| hooks/scripts/memory_validate_hook.py | PostToolUse:Write hook (버그 소재) | **Phase 1, 3, 5 수정** |
| hooks/scripts/memory_write_guard.py | PreToolUse:Write hook (참조 구현) | Phase 2 테스트 참조 |
| hooks/scripts/memory_triage.py | Stop hook: context file 생성 | **Phase 4 수정** |
| tests/test_memory_validate_hook.py | PostToolUse 테스트 | **Phase 2 수정** |
| tests/test_memory_staging_guard.py | Staging guard 테스트 (패턴 참조) | 참조만 |
| tests/test_memory_write_guard.py | PreToolUse 테스트 (패턴 참조) | 참조만 |
| assets/memory-config.default.json | 기본 설정 | 변경 없음 |
| skills/memory-management/SKILL.md | Context file format 문서 | **Phase 4 수정** |
| CLAUDE.md | 프로젝트 문서 | **Phase 3 수정** |

---

## Hotfix Track (Phase 1-3)

### Phase 1: Staging Exclusion 핫픽스

**목표:** PostToolUse:Write hook에서 `.staging/` 파일을 제외하여 quarantine/deny 방지
**파일:** `hooks/scripts/memory_validate_hook.py`

**변경 내용:** `is_memory_file()` 체크 이후 (line 154), WARNING print 이전 (line 157)에 staging exclusion 삽입.

```python
# line 154: if not is_memory_file(resolved): sys.exit(0) 다음에 삽입
# Skip staging files -- temporary working files, not memory records.
_stg = ".stagi" + "ng"
staging_marker = MEMORY_DIR_SEGMENT + _stg + "/"
normalized = resolved.replace(os.sep, "/")
if staging_marker in normalized:
    sys.exit(0)
```

**삽입 위치 근거 (5개 소스 합의):**
- `is_memory_file()` 이후: 비-memory 파일은 이미 통과
- WARNING print 이전: staging은 정상 경로이므로 "bypassed guard" 경고 불필요
- Non-JSON deny 이전 (line 174): `.txt` staging 파일도 보호
- Quarantine 이전 (line 198): `.json` staging 파일도 보호
- Runtime string construction: Guardian pattern matching 방지 (기존 `_DC`, `_MEM` 패턴과 일관). 참고: `memory_write_guard.py`는 plain literal 사용 중 — 향후 parity 정리 시 양쪽을 통일할 것 (deferred scope).

**Rollback:** `git revert` Phase 1 커밋. 복구 시 기존 동작 (staging quarantine + agent retry)으로 돌아감 — 성능 저하이나 데이터 손상 없음.

**Steps:**
- [ ] `memory_validate_hook.py`의 `is_memory_file()` 체크 직후, "bypassed PreToolUse guard" WARNING 직전에 staging exclusion 코드 삽입
- [ ] `python3 -m py_compile hooks/scripts/memory_validate_hook.py` 문법 확인
- [ ] `pytest tests/test_memory_validate_hook.py -v` 기존 테스트 통과 확인

---

### Phase 2: Regression + Cross-Hook Parity 테스트

**목표:** staging exemption 동작 검증 + Pre/PostToolUse 간 parity 보장
**파일:** `tests/test_memory_validate_hook.py`

**테스트 패턴 (기존 코드베이스 분석 기반):**
- subprocess 기반 통합 테스트 (hook script를 직접 실행)
- `assert_deny()` / `assert_allow()` 헬퍼 (staging_guard 패턴 재사용)
- Hook input: `{"tool_input": {"file_path": "<path>"}}` 형식

**추가할 테스트:**

Staging Exemption (TrueNegatives — allow expected):
- [ ] `test_staging_json_file_allowed` — `.staging/intent-decision.json` → exit(0), no deny, no quarantine
- [ ] `test_staging_txt_file_allowed` — `.staging/new-info-session.txt` → exit(0), no deny
- [ ] `test_staging_nested_path_allowed` — `.staging/sub/dir/file.json` → exit(0)
- [ ] `test_staging_no_bypass_warning` — staging 경로에 "bypassed PreToolUse guard" 경고 미출력 확인

Staging Exemption 추가:
- [ ] `test_staging_triage_data_allowed` — `.staging/triage-data.json` (가장 중요한 staging 파일) → exit(0)
- [ ] `test_non_staging_shows_bypass_warning` — `decisions/test.json` → stderr에 "bypassed PreToolUse guard" 경고 출력 확인

Security (TruePositives — deny/quarantine expected):
- [ ] `test_staging_traversal_blocked` — `.staging/../decisions/evil.json` → realpath 해소 → 정상 validation 수행
- [ ] `test_non_staging_memory_still_validated` — `decisions/bad.json` → quarantine 정상 작동

Cross-Hook Parity (각 테스트는 Pre/Post 양쪽 hook을 단일 함수에서 호출):
- [ ] `test_parity_staging_both_hooks_allow` — Pre/PostToolUse 모두 staging 허용 확인
- [ ] `test_parity_config_both_hooks_allow` — Pre/PostToolUse 모두 config 허용 확인

> **Note:** Memory dir에 대한 parity 테스트는 의도적 비대칭이므로 불필요. PreToolUse는 직접 쓰기를 deny (차단), PostToolUse는 유효한 JSON은 warn만 (allow), 무효한 JSON만 quarantine+deny. 이것은 설계 의도 (PreToolUse = 예방, PostToolUse = 탐지)이므로 "양쪽 모두 deny" parity를 기대하면 안 됨.

**Steps:**
- [ ] `assert_allow()` / `assert_deny()` 헬퍼 추가 (staging_guard 패턴 참조)
- [ ] Staging exemption + security + parity 테스트 총 10개 작성
- [ ] `pytest tests/test_memory_validate_hook.py -v` 전체 통과 확인
- [ ] `pytest tests/ -v` 전체 test suite 통과 확인

### Hotfix Validation Gate

Phase 2 완료 후 다음을 확인:
- [ ] PostToolUse가 staging `.json`과 `.txt` 모두에서 깨끗하게 exit
- [ ] "bypassed PreToolUse guard" stderr 경고가 staging 경로에서 미출력
- [ ] Root `memory-config.json`은 여전히 exempt
- [ ] 잘못된 memory record JSON은 여전히 quarantine됨
- [ ] `pytest tests/ -v` 전체 통과

---

### Phase 3: Quarantine 진단 개선

**목표:** quarantine 발생 시 운영자가 원인을 빠르게 파악할 수 있도록 에러 메시지 개선
**파일:** `hooks/scripts/memory_validate_hook.py`, `CLAUDE.md`

**현재 문제:** quarantine 시 에러 메시지가 `"Schema validation failed: <error>. File quarantined to <name>."` 형태. 원래 파일 경로, quarantine 사유, 진단 힌트가 부족.

**변경 내용:**

- [ ] Quarantine 에러 메시지에 원본 경로, validation error 상세, "Use memory_write.py instead" 힌트 포함
- [ ] Non-JSON deny 메시지에도 원본 경로 + 힌트 추가
- [ ] CLAUDE.md Hook Type 테이블: PostToolUse 설명에 staging exclusion 명시
- [ ] CLAUDE.md Security Considerations: PostToolUse scope limitation 추가 (Write tool only, Python `open()` 미감시)
- [ ] `python3 -m py_compile` 확인
- [ ] 기존 테스트 통과 확인

---

## Follow-up Track (Phase 4-5)

> Hotfix track과 독립적. 별도 세션에서 실행 가능.

### Phase 4: Session Summary Context 품질 개선

**목표:** session_summary context file에 transcript excerpt를 포함하여 drafter subagent가 의미 있는 output을 생성할 수 있도록 개선
**파일:** `hooks/scripts/memory_triage.py`, `skills/memory-management/SKILL.md`

**현재 문제:** session_summary context file에 activity metrics (tool_uses, distinct_tools, exchanges) 3줄만 포함. Drafter subagent가 `goal`, `outcome`, `completed[]` 등을 추론할 수 없어 main agent가 대신 작업 (8s 낭비).

**분석 결과 (triage-analyzer):**
- 전체 transcript `text`가 `write_context_files()`에 전달되지만 session_summary에서는 미사용
- `_find_match_line_indices()`는 `CATEGORY_PATTERNS` 기반이지만 session_summary는 해당 없음
- Option B (head + tail excerpt)가 최적: 초기 목표 + 최종 상태 모두 포착

**변경 내용:**

```python
# memory_triage.py 상단에 상수 추가
SESSION_SUMMARY_HEAD_LINES = 80
SESSION_SUMMARY_TAIL_LINES = 200

# write_context_files()의 if category == "SESSION_SUMMARY" 분기에 추가
# (기존 Activity Metrics 이후)
parts.append("")
parts.append("Transcript (opening excerpt):")
parts.append("")
head_lines = lines[:SESSION_SUMMARY_HEAD_LINES]
parts.append("\n".join(head_lines))
parts.append("")
parts.append("---")
parts.append("")
parts.append("Transcript (closing excerpt):")
parts.append("")
tail_lines = lines[-SESSION_SUMMARY_TAIL_LINES:]
parts.append("\n".join(tail_lines))
```

**Head/tail 중복 처리 전략:**
```python
total = len(lines)
if total <= SESSION_SUMMARY_HEAD_LINES + SESSION_SUMMARY_TAIL_LINES:
    # 짧은 대화: 전체 포함
    parts.append("Transcript (full):")
    parts.append("")
    parts.append("\n".join(lines))
else:
    # 긴 대화: head + tail
    parts.append("Transcript (opening excerpt):")
    parts.append("")
    parts.append("\n".join(lines[:SESSION_SUMMARY_HEAD_LINES]))
    parts.append("\n---\n")
    parts.append("Transcript (closing excerpt):")
    parts.append("")
    parts.append("\n".join(lines[-SESSION_SUMMARY_TAIL_LINES:]))
```

**Steps:**
- [ ] `SESSION_SUMMARY_HEAD_LINES`, `SESSION_SUMMARY_TAIL_LINES` 상수 추가
- [ ] `write_context_files()` session_summary 분기에 head+tail excerpt 추가 (중복 처리 포함)
- [ ] 50KB `MAX_CONTEXT_FILE_BYTES` 캡 적용 확인 (장문 tool output 포함 테스트)
- [ ] 짧은 대화 (280줄 미만) → "full" 모드 전환 확인
- [ ] SKILL.md Phase 1 "Context file format" 설명 업데이트: session_summary에 transcript excerpt 포함 명시
- [ ] `agents/memory-drafter.md` — session_summary context 설명이 있으면 업데이트
- [ ] 관련 테스트 추가: 정상 크기 transcript, 짧은 transcript, 장문 라인 truncation
- [ ] `pytest tests/ -v` 통과 확인

### Follow-up Validation Gate (Phase 4)

- [ ] Session summary context file에 transcript excerpt 포함 확인
- [ ] 50KB 캡 정상 작동 확인
- [ ] 다른 카테고리의 context file에 regression 없음
- [ ] Drafter subagent가 enriched context로 의미 있는 output 생성 (E2E, 별도 세션)

---

### Phase 5: Pydantic Bootstrap 최적화

**목표:** 비-memory Write 호출에서 불필요한 pydantic sys.path 조작 및 import 시도 제거
**파일:** `hooks/scripts/memory_validate_hook.py`

**현재 문제:** Lines 17-31의 pydantic bootstrap (sys.path 조작 + `import pydantic`)가 모든 Write 호출에서 실행됨. `is_memory_file()` 체크 (line 153) 이후에야 memory 파일 여부가 판별되지만, bootstrap은 그 이전에 실행. 비-memory Write 호출에서 ~20-50ms 불필요 overhead.

**변경 내용:**

Pydantic bootstrap 코드 (lines 17-31)를 `is_memory_file()` 체크 이후로 이동. 즉, memory 파일이 아니면 pydantic을 import하지 않음.

**Lazy init 구현 패턴:**

```python
# Module level: 기존 bootstrap 코드 제거, lazy wrapper로 대체
_pydantic_bootstrapped = False
_HAS_PYDANTIC = False

def _ensure_pydantic():
    """Lazy-bootstrap pydantic from plugin venv. Called only for memory files."""
    global _pydantic_bootstrapped, _HAS_PYDANTIC
    if _pydantic_bootstrapped:
        return
    _pydantic_bootstrapped = True
    _venv_lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.venv', 'lib')
    if os.path.isdir(_venv_lib):
        for _d in os.listdir(_venv_lib):
            _sp = os.path.join(_venv_lib, _d, 'site-packages')
            if os.path.isdir(_sp) and _sp not in sys.path:
                sys.path.insert(0, _sp)
    try:
        import pydantic  # noqa: F401
        _HAS_PYDANTIC = True
    except ImportError:
        pass

# validate_file() 내부에서 호출:
def validate_file(file_path):
    _ensure_pydantic()
    # ... 기존 로직 ...
```

**주의사항:**
- `_ensure_pydantic()`는 `validate_file()` 진입 시 한 번만 실행 (idempotent)
- `is_memory_file()` 가 False인 경우 `validate_file()`에 도달하지 않으므로 bootstrap 미실행
- Hook은 단일 프로세스 실행 → thread safety 불필요
- 변경 전/후 latency 측정으로 실제 개선 확인 필요

**Steps:**
- [ ] 기존 module-level bootstrap (lines 17-31)을 `_ensure_pydantic()` 함수로 추출
- [ ] `validate_file()` 진입부에 `_ensure_pydantic()` 호출 추가
- [ ] 비-memory Write에서 pydantic import 미실행 확인 (간단한 timing 비교)
- [ ] `pytest tests/test_memory_validate_hook.py -v` 통과 확인
- [ ] `pytest tests/ -v` 전체 통과 확인

### Follow-up Validation Gate (Phase 5)

- [ ] 비-memory Write 경로에서 pydantic bootstrap 미실행
- [ ] Memory file validation 동작 변경 없음
- [ ] 전체 test suite 통과

---

## 의존 관계

```
Phase 1 (staging fix) ──→ Phase 2 (tests) ──→ Phase 3 (diagnostics)
                                                      │
                                               [Hotfix Gate]

Phase 4 (session context) ── independent
Phase 5 (pydantic opt) ── independent
```

## 엣지 케이스 주의

1. **Concurrent sessions**: 두 세션이 동시에 `.staging/`에 쓸 경우 Pre-Phase cleanup이 감지하지만, 활성 동시 쓰기는 처리 못함. Fix는 이를 악화시키지도 개선하지도 않음.
2. **짧은 대화의 head/tail 중복** (Phase 4): 대화가 80+200=280줄 미만일 때 head와 tail이 겹침. 중복 제거 또는 전체 포함 전략 필요.
3. **Pydantic lazy init의 thread safety** (Phase 5): Hook은 단일 프로세스 실행이므로 thread safety 불필요하지만, import 순서에 주의.

## Deferred Scope (이 plan 범위 밖)

아래 항목은 분석 과정에서 제안되었으나, vibe check + codex 5.3 리뷰에서 현재 plan에는 과도하다고 판단되어 제외함:

1. **공유 `classify_memory_path()` 헬퍼 모듈 추출** — Phase 2의 cross-hook parity 테스트가 drift를 감지하므로, 별도 모듈 추출은 premature abstraction. Hook이 3개 이상으로 늘어나면 재고.
2. **Quarantine config flag (`validation.quarantine_enabled`)** — Phase 1의 staging exclusion이 근본 원인을 해소하므로 quarantine on/off 토글의 실제 사용 시나리오 없음. 향후 필요 시 추가.
3. **Staging 디렉토리를 memory root 밖으로 이동** (e.g., `.claude/memory-staging/`) — 구조적 해결이지만 migration cost 대비 이득 불명확. 현재 exclusion 패턴으로 충분.

## 성공 기준

**Hotfix Track:**
- Staging 파일이 quarantine/deny되지 않음
- 기존 memory record validation은 정상 작동
- Cross-hook parity 테스트 통과
- `pytest tests/ -v` 전체 통과

**Follow-up Track:**
- Session summary drafter subagent가 enriched context로 유의미한 output 생성
- 비-memory Write 호출의 pydantic overhead 제거
- 전체 test suite 통과
