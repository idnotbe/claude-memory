---
status: active
progress: "Phase 3/4 reader 코드 구현 완료 (memory_retrieve.py + SKILL.md post-save/pre-phase). Phase 0/1/2 미착수. Phase 3/4 writer 미완."
---

# Plan: Memory Save UI Noise Reduction

**날짜:** 2026-02-28
**범위:** Stop hook save process의 UI noise 50-85% 감소 (50-100+ lines → 8-38 lines, 카테고리 수에 따라 다름)
**검증 소스:** Opus 4.6 (research lead), Gemini 3.1 Pro (4 rounds cross-validation), V1 impl/risk verifiers, V2 contrarian/completeness verifiers
**의존성:** 없음 (독립 실행 가능)
**리서치 문서:** `research/memory-save-noise-reduction.md`

---

## 배경 (Background)

### 문제 정의

claude-memory의 Stop hook이 트리거되면, memory save process가 메인 대화에 50-100+ 라인의 visible output을 생성한다:

1. **Stop hook triage output** (~20-30 lines): `<triage_data>` JSON 블록이 `reason` 필드에 인라인 포함
2. **Phase 1/2 subagent spawn** (~2-4 lines each): Task subagent 생성 (최소 noise)
3. **Phase 3 save operations** (~30-50 lines): `memory_candidate.py`, `memory_draft.py`, `memory_write.py`, `memory_enforce.py` 다중 Bash 호출
4. **Error handling/retries** (가변): 예측 불가, 매우 verbose할 수 있음

### 영향

- 사용자가 원래 대화를 보려면 50-100+ 줄을 스크롤해야 함
- 메인 context window에서 ~7,000-20,000 토큰 소모
- Auto-compact가 ~167K 토큰에서 트리거 — 3-category save는 사용 가능 버퍼의 ~4-12% 소모
- /compact 발동 시 이전 대화 컨텍스트가 영구적으로 요약됨

### 근본 원인

`{"decision": "block", "reason": "..."}` 패턴이 **메인 에이전트**를 save pipeline 오케스트레이터로 만든다. 메인 에이전트의 모든 후속 행동(subagent 생성, 파일 읽기, Bash 명령 실행)은:
1. 사용자에게 보임 (숨길 수 없음)
2. 메인 context window에 추가됨 (/compact 트리거)

`suppressOutput`, `run_in_background: true` 등은 메인 에이전트의 tool call 가시성 문제를 해결하지 못한다.

---

## 목적 (Purpose)

| Phase | 의사결정 | 결과에 따른 후속 조치 |
|-------|---------|---------------------|
| Phase 0: Agent Hook 실험 | Agent hook subagent의 tool call이 메인 transcript에서 격리되는가? | YES → Phase 5에서 full agent hook 구현 / NO → Fix A+B가 primary path |
| Phase 1: Fix A | triage_data 인라인 JSON 제거로 ~20 lines 감소 | reason 필드 ~3 lines로 축소 |
| Phase 2: Fix B | Phase 3 save operations을 single Task subagent으로 통합 | ~30-50 lines → ~3 lines (isolation 유지 시) |
| Phase 3: Save 확인 | 이전 세션 save 결과를 다음 세션 첫 프롬프트에서 확인 | silent failure 방지 |
| Phase 4: Error Fallback | Save 실패 시 deferred sentinel 작성 | 다음 세션에서 재시도 |
| Phase 5: Optional | Agent hook full impl / Deferred mode opt-in | 완전한 zero-noise 또는 수동 제어 옵션 |

---

## 관련 정보 (Related Info)

### 실행 순서 및 근거

**결정된 순서: Phase 0 (실험, time-boxed) → Phase 1 (Fix A) → Phase 2 (Fix B) → Phase 3 → Phase 4 → Phase 5**

이 순서에 대한 검증 소스별 의견:

| 소스 | 추천 순서 | 핵심 근거 |
|------|----------|----------|
| V2 Contrarian | Fix A+B 먼저 | "Agent hook은 10분 실험이 아님. Fix A+B가 가장 신뢰할 수 있는 경로" |
| V2 Feasibility | Agent hook 실험 먼저 | "Stop 이벤트에서 type: agent 지원 확인됨. 격리 여부만 테스트 필요" |
| Gemini R3 | Fix A+B 먼저 | "Speculative spike가 guaranteed value 전달을 지연" |
| V1 Arch/UX | Agent hook 먼저 테스트 | "테스트 비용 대비 잠재적 이득이 가장 큼" |
| V1 Risk | 현행 순서 유효 | "Phase 0 time-boxed spike는 standard agile practice" |

**합의:** Phase 0 실험을 **엄격하게 시간 제한된 스파이크**(최대 반나절)로 먼저 실행. 결과 불문 빠르게 종료하고 Fix A+B로 진입.

**대안:** Fix A+B를 먼저 구현하고 실험을 나중에 진행해도 무방. 팀 리소스가 있으면 Phase 0과 Phase 1을 병렬 실행 가능.

### Noise 감소 예상치

| 시나리오 | Visible lines | Context tokens | 감소율 |
|---------|--------------|----------------|--------|
| Before (현재) | 50-100+ | 7,000-20,000 | — |
| 1-category save (best case) | ~8-12 | ~1,000-1,500 | ~85% |
| 3-category save (typical) | ~13-24 | ~1,500-3,000 | ~50-75% |
| 6-category save (worst case) | ~21-38 | ~2,500-5,000 | ~40-60% |
| + subagent transcript leakage | +10-15 lines per scenario | +1,000-2,000 | 추가 감소 |

> **주의 (V2 Contrarian + V1 Risk):** 85% 감소는 **1-category save + subagent isolation 유지** 시에만 달성. Phase 1/2 subagent spawn 라인이 카테고리 수에 비례하여 증가하므로, multi-category save의 현실적 감소율은 **50-65%**. Phase 2 시작 전 5분 isolation 검증 테스트 필수. Multi-category까지 85%+ 달성하려면 Phase 5c (Phase 1/2 spawn 통합) 필요.

### 코드 참조

| 파일 | 라인 | Phase 관련 |
|------|------|----------|
| `hooks/hooks.json` | 8-13 | Phase 0 — 현재 Stop hook (`type: "command"`) |
| `hooks/scripts/memory_triage.py` | 950-953 | Phase 1 — `<triage_data>` 인라인 임베딩 |
| `hooks/scripts/memory_triage.py` | 1110-1131 | Phase 1 — sentinel + context file 작성 + block message 출력 |
| `hooks/scripts/memory_triage.py` | 870-955 | Phase 1 — `format_block_message()` 전체 |
| `hooks/scripts/memory_triage.py` | 908-948 | Phase 1 — `triage_data` dict 생성 (format_block_message 내부) |
| `skills/memory-management/SKILL.md` | 38-40 | Phase 1 — Phase 0 triage output 파싱 |
| `skills/memory-management/SKILL.md` | 188-212 | Phase 2 — Phase 3 save operations (main agent) |
| `skills/memory-management/SKILL.md` | 228-247 | Phase 2 — CUD Verification Rules section |
| `hooks/scripts/memory_retrieve.py` | 411-429 | Phase 3/4 — config 로딩 + short prompt skip. **삽입 지점: line 422 이전** (short prompt check 전) |

---

## Phase 상세 설계

### Phase 0: Agent Hook Isolation 실험 [ ]

**목적:** `type: "agent"` hook의 subagent tool call이 메인 transcript에서 격리되는지 경험적 확인. 이 결과가 전체 아키텍처 방향을 결정한다.

**핵심 질문:**
1. Agent hook subagent의 tool call이 메인 대화 transcript에 보이는가?
2. `ok: false`가 Stop 이벤트에서 session 종료를 차단하는가?
3. Agent hook subagent가 `$CLAUDE_PLUGIN_ROOT` 환경변수에 접근 가능한가?
4. Agent hook subagent가 Stop 이벤트의 transcript/context에 접근 가능한가? (Gemini R3)
5. Timeout 동작: 기본 60초 내에 save pipeline 완료 가능한가?

**브랜치 격리 필수:** `hooks.json` 변경은 모든 세션에 영향 — 별도 git 브랜치 (`exp/agent-hook-stop`)에서 실행.

**실험 설계:**

```
실험 A (격리 테스트):
  hooks.json: type="agent" → prompt: "Run: echo hello via Bash tool. Then return ok:true"
  측정: Bash tool call이 메인 transcript에 보이는가?

실험 B (파일 접근 테스트):
  hooks.json: type="agent" → prompt: "Read .claude/memory/memory-config.json, return ok:true"
  측정: 파일 접근 가능 여부, $CLAUDE_PLUGIN_ROOT 해석 여부

실험 C (block 테스트):
  hooks.json: type="agent" → prompt: "Return ok:false with reason 'test block'"
  측정: 세션 종료 차단 여부, reason 전달 방식

실험 D (데이터 접근 테스트):
  hooks.json: type="agent" → prompt: "Read $ARGUMENTS. Report what data you received."
  측정: Stop 이벤트 payload가 agent hook에 전달되는지
```

**Agent Hook 스키마 주의사항** (V2 Contrarian):
- Agent hook은 `prompt` 필드 사용 (`command` 필드 무시)
- 반환 스키마: `{"ok": true/false, "reason": "..."}` (command hook의 `{"decision": "block"}` 아님)
- `$ARGUMENTS`로 hook input JSON을 prompt에 치환 가능 (확인 필요)

**종료 기준 (Kill Criteria):**
- 최대 반나절 time-box
- 격리 확인 불가 시: Phase 5a 취소
- 격리 확인 시: Phase 5a 진행

**단계:**
- [ ] git 브랜치 `exp/agent-hook-stop` 생성
- [ ] 실험 A: 격리 테스트 (Bash tool call 가시성 확인)
- [ ] 실험 B: 파일 접근 테스트
- [ ] 실험 C: ok:false block 테스트
- [ ] 실험 D: $ARGUMENTS 데이터 접근 테스트
- [ ] 결과 문서화 (`temp/agent-hook-stop-results.md`)
- [ ] main 브랜치 복귀

---

### Phase 1: Fix A — triage_data 외부화 [ ]

**목적:** `format_block_message()`에서 `<triage_data>` JSON 블록을 인라인 삽입 대신 파일로 외부화. reason 필드를 ~25 lines에서 ~5 lines로 축소.

> **배포 순서 (V1 Risk — CRITICAL):** SKILL.md를 먼저 업데이트, 그 후 memory_triage.py 변경.
> 이유: 새 SKILL.md는 `<triage_data_file>`과 inline `<triage_data>` 모두 지원 (backwards compatible). 그러나 구 SKILL.md는 `<triage_data>` 태그만 파싱. memory_triage.py를 먼저 변경하면 구 SKILL.md가 triage data를 찾지 못해 **모든 memory save가 silent 실패**.

**변경 내용:**

**1. `memory_triage.py` — triage_data 구성을 `format_block_message()`에서 추출**

> **V1 Impl — CRITICAL bug fix:** `triage_data`는 `format_block_message()` 내부 (lines 908-948)에서 생성되는 지역 변수. `_run_triage()`에서 직접 접근 불가 (NameError 발생). 해결: `build_triage_data()` 헬퍼 함수를 추출하여 `_run_triage()`에서 호출 후 파일 쓰기, 그리고 `format_block_message()`에 triage_data_path만 전달.

```python
# 새 헬퍼 함수
def build_triage_data(results, context_paths, parallel_config, category_descriptions):
    """triage_data dict를 구성하여 반환."""
    # 기존 format_block_message() lines 908-948의 로직을 여기로 이동
    ...
    return triage_data

# _run_triage()에서:
triage_data = build_triage_data(results, context_paths, parallel_config, cat_descs)

# atomic write
triage_data_path = os.path.join(cwd, ".claude", "memory", ".staging", "triage-data.json")
os.makedirs(os.path.dirname(triage_data_path), exist_ok=True)
tmp_path = triage_data_path + ".tmp"
fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
try:
    os.write(fd, json.dumps(triage_data, indent=2).encode("utf-8"))
finally:
    os.close(fd)
os.replace(tmp_path, triage_data_path)

message = format_block_message(
    results, context_paths, parallel_config,
    category_descriptions=cat_descs,
    triage_data_path=triage_data_path,
)
```

**Error fallback (V1 Risk):** triage-data.json 파일 쓰기 실패 시, inline `<triage_data>` 출력으로 graceful degradation:
```python
try:
    # atomic write ...
    os.replace(tmp_path, triage_data_path)
except OSError:
    triage_data_path = None  # fallback to inline
```

**2. `format_block_message()` 변경 (lines 950-953):**

```python
# triage_data_path가 있으면 파일 참조, 없으면 inline fallback
if triage_data_path:
    lines.append("")
    lines.append(f"<triage_data_file>{triage_data_path}</triage_data_file>")
else:
    lines.append("")
    lines.append("<triage_data>")
    lines.append(json.dumps(triage_data, indent=2))
    lines.append("</triage_data>")
```

**3. SKILL.md Phase 0 파싱 업데이트 (line 39):**

```
Read the triage data file path from `<triage_data_file>` tag in the stop hook output.
Load the JSON from that file path. If the tag is not present, fall back to extracting
inline `<triage_data>` JSON block (backwards compatibility).
```

**4. 테스트 업데이트 (V1 Impl — HIGH):**

기존 테스트 중 `<triage_data>` 태그를 assert하는 테스트들을 업데이트:
- `tests/test_memory_triage.py`: `<triage_data>` assertion → `<triage_data_file>` 또는 inline fallback
- `tests/test_adversarial_descriptions.py`: 동일
- 새 테스트: `triage-data.json` 파일 생성 확인, JSON validity 확인

**5. 문서 업데이트 (V1 Impl — HIGH):**
- `CLAUDE.md`: "structured `<triage_data>` JSON" 참조 업데이트
- `SKILL.md` line 58: "The `<triage_data>` JSON block" 참조 업데이트

**단계:**
- [ ] SKILL.md Phase 0 업데이트 (파일 경로 기반 로드 + inline fallback) — **먼저 배포**
- [ ] `build_triage_data()` 헬퍼 함수 추출
- [ ] `_run_triage()`에 triage_data.json 파일 쓰기 로직 추가 (atomic write + error fallback)
- [ ] `format_block_message()`에 `triage_data_path` 파라미터 추가 및 조건부 출력
- [ ] 기존 테스트 업데이트 (~15+ tests)
- [ ] 새 테스트 작성 (파일 생성, JSON validity, fallback)
- [ ] CLAUDE.md, SKILL.md 문서 업데이트
- [ ] `python3 -m py_compile hooks/scripts/memory_triage.py`
- [ ] `pytest tests/ -v`
- [ ] 통합 테스트: 전체 save flow 검증

**Rollback:** SKILL.md는 backwards compatible이므로 `memory_triage.py`만 revert하면 inline 모드로 복귀.

---

### Phase 2: Fix B — Phase 3 Single Task Subagent [ ]

**목적:** SKILL.md Phase 3 (save operations)를 메인 에이전트 대신 단일 foreground Task subagent에서 실행. Phase 3의 ~30-50 lines tool call noise를 ~3 lines로 축소.

> **Phase 2 시작 전 (V1 Risk):** 5분 subagent isolation 검증 테스트 실행. 간단한 Task subagent (Bash echo 실행)의 tool call이 메인 context에 보이는지 확인. 보이면 Phase 2의 기대 효과가 60% 감소에 그침.

**현재 Phase 3 (SKILL.md lines 188-212):**
- 메인 에이전트가 Phase 1/2 결과 수집
- CUD resolution table 적용
- 각 카테고리별 `memory_write.py` Bash 호출 (CREATE/UPDATE/RETIRE)
- `memory_enforce.py` 호출 (session_summary)
- 모든 호출이 메인 transcript에 노출

**변경 내용:**

SKILL.md Phase 3를 다음과 같이 재구성:

```markdown
### Phase 3: Save (Single Subagent)
1. Main agent applies CUD resolution table to Phase 1/2 results → produces action list
2. Spawn ONE foreground Task subagent with the pre-computed action list
3. Subagent executes commands ONLY (no CUD decision-making)
4. Main agent outputs brief summary from Task return value
```

> **CUD resolution은 메인 에이전트가 수행 (V1 Risk — HIGH):**
> V1 Risk verifier + Gemini 합의: CUD 의사결정(create/update/retire 판정)은 Phase 1/2 컨텍스트가 필요하므로 메인 에이전트가 수행. Task subagent는 **결정된 명령만 실행** (imperative execution only). 이렇게 하면:
> - Subagent hallucination으로 인한 잘못된 CUD 판정 방지
> - Main agent의 CUD tool call은 ~2-3 lines (결정 출력)로 최소
> - Subagent의 Bash tool call (~30-50 lines)만 격리

**CUD resolution context 전달:**
- 메인 에이전트가 CUD resolution 수행 후 **정확한 명령 목록**을 Task prompt에 직접 포함
- 예: "Run these exact commands in order: (1) `python3 .../memory_write.py --action create ...` (2) `python3 .../memory_enforce.py ...`"
- 파일 쓰기 불필요 — prompt에 직접 포함 (추가 tool call noise 방지)

**Cleanup:**
- Task subagent가 save 완료 후 `.staging/triage-data.json` 삭제
- `.staging/context-*.txt` 파일도 삭제 (stale file 축적 방지)
- Save 결과를 `~/.claude/last-save-result.json` (글로벌 경로)에 작성 (Phase 3 확인용)

**Error handling (V1 Risk):**
- Task subagent 실패/timeout 시: 메인 에이전트가 error 감지
- Deferred sentinel (`.triage-pending.json`) 작성 (Phase 4 연계)
- `triage-data.json` 및 `context-*.txt` 보존 (삭제하지 않음)

**주의사항:**
- Subagent가 `$CLAUDE_PLUGIN_ROOT` 경로에 접근 가능해야 함 — 명령에 절대 경로 포함
- `memory_write.py`의 venv bootstrap (`os.execv()`)이 subagent에서도 동작해야 함

**단계:**
- [ ] 5분 subagent isolation 검증 테스트 실행
- [ ] SKILL.md Phase 3 섹션 재작성 (main agent CUD → subagent imperative execution)
- [ ] Task prompt 설계: 정확한 명령 목록 + cleanup 지시 + 결과 파일 작성
- [ ] Cleanup 로직 (triage-data.json, context-*.txt 삭제)
- [ ] Error handling (subagent 실패 → deferred sentinel)
- [ ] Save 결과 파일 작성 로직 (last-save-result.json)
- [ ] `memory_write.py` venv bootstrap 동작 확인
- [ ] CUD resolution 정합성 검증 (메인 에이전트 직접 실행과 동일 결과)
- [ ] 통합 테스트: 전체 save flow 검증
- [ ] Visible output line count 측정 및 기록

**Rollback:** SKILL.md를 이전 버전으로 revert. Phase 1의 triage_data 외부화는 유지.

---

### Phase 3: Save Confirmation via UserPromptSubmit [/]

**목적:** 이전 세션에서 저장된 메모리를 다음 세션 첫 프롬프트에서 확인 메시지로 표시. Silent failure 방지.

> **SessionStart 대신 UserPromptSubmit 사용 (Gemini R3).**
> SessionStart command hook stdout의 UI 표시 여부 불확실. UserPromptSubmit (`memory_retrieve.py`)은 stdout → context 주입이 검증됨. 새 스크립트 불필요.

**1. Save 결과 파일** — Phase 2의 Task subagent가 **글로벌 경로**에 작성 (V2 Contrarian cross-project 해결):
```
~/.claude/last-save-result.json
```
```json
{
  "saved_at": "2026-02-28T12:00:00Z",
  "project": "/path/to/project",
  "categories": ["session_summary", "decision"],
  "titles": ["Session summary updated", "API auth decision"],
  "errors": [{"category": "constraint", "error": "OCC_CONFLICT"}]
}
```

**2. `memory_retrieve.py` 수정** — `main()` 함수, **line 422 이전** (short prompt check 전). **[v] 구현 완료:**
- 글로벌 경로 `Path.home() / ".claude" / "last-save-result.json"` 사용
- Same project → 상세 확인 (카테고리 + 타이틀), Different project → 간략 노트
- 24시간 timestamp check, 1회 표시 후 삭제 (finally block)
- `html.escape()` 적용 (XML injection 방지)
- Structured error dict 처리 (`{category, error}` → "category: error" 포맷)
- `_just_saved` 플래그로 Block 2 orphan detection 억제

> **Partial save 시나리오 (V1 Risk):** 일부 카테고리 성공, 일부 실패 시 — confirmation과 pending notification이 동시에 표시될 수 있음. 이는 의도된 동작 (사용자에게 정확한 상태 전달).

> **Cross-project 해결 (V2 Contrarian):** 글로벌 경로 `~/.claude/last-save-result.json` 사용. `project` 필드로 프로젝트 구분. Same project이면 상세 확인, different project이면 간략 노트 표시.

**단계:**
- [v] `last-save-result.json` 스키마 정의 (글로벌 경로, project 필드 포함)
- [ ] Phase 2의 Task subagent prompt에 결과 파일 작성 지시 추가 **(Phase 2 의존)**
- [v] `memory_retrieve.py`에 save confirmation 로직 추가 (line 422 이전)
- [v] 24시간 timestamp check 추가
- [v] 테스트: 정상 save → 확인 메시지 → 파일 삭제
- [v] 테스트: 24시간 초과 결과 파일 무시
- [v] 테스트: structured error dict 처리
- [v] 테스트: cross-project brief note

**Rollback:** `memory_retrieve.py`의 confirmation 블록만 제거. 다른 Phase에 영향 없음.

---

### Phase 4: Error Fallback — Deferred Sentinel [/]

**목적:** Save 실패 시 deferred sentinel 파일을 작성하여 다음 세션에서 재시도할 수 있게 함.

**구현:**

1. **SKILL.md error handling** — Phase 3 subagent 실패 시:
   - `.staging/triage-data.json`과 `context-*.txt` 보존 (삭제하지 않음)
   - `.staging/.triage-pending.json` sentinel 파일 작성

2. **`memory_retrieve.py`** — pending save 감지 (save confirmation 직후, line 422 이전). **[v] 구현 완료:**
   - `.staging/.triage-pending.json` 읽기, 카테고리 수 표시
   - 메시지: "Pending memory save: N categories from last session. Run /memory:save to re-triage and save."
   - `isinstance(dict)` 타입 가드, fail-open 패턴

3. **Cleanup race condition 방지 (V1 Impl):**
   - `.triage-pending.json`은 `/memory:save` 실행 후, 모든 save가 **검증된 후에만** 삭제
   - Subagent 부분 성공 시: pending 파일에 실패 카테고리만 남김

4. **Orphan crash recovery (V2 Contrarian):**
   Subagent가 unhandled crash (OOM, 네트워크 타임아웃) 시: `triage-data.json` + `context-*.txt` + `.triage-handled` 잔존, but `last-save-result.json`도 `.triage-pending.json`도 없음 → 사용자에게 무피드백.
   ```python
   # memory_retrieve.py: orphan detection (save confirmation 직후)
   triage_data_path = memory_root / ".staging" / "triage-data.json"
   if (triage_data_path.exists() and
       not result_path.exists() and not pending_path.exists()):
       # Orphaned crash state: staging files exist but no result/pending
       try:
           age = time.time() - triage_data_path.stat().st_mtime
           if age > 300:  # >5min = likely orphaned (not mid-save)
               print("<memory-note>Previous session may have crashed during save. "
                     "Use /memory:save to retry.</memory-note>")
       except OSError:
           pass
   ```

5. **`/memory:save` resume 단순화 (V2 Contrarian):**
   SKILL.md에 full resume 분기를 구현하는 대신, `/memory:save`는 항상 **fresh save**로 실행.
   Pending/orphan 파일이 있으면 cleanup 후 정상 triage → save 파이프라인 진행.
   이유: pre-existing context files의 staleness 판단이 불확실하고, session_summary는 이전 세션 transcript가 없으면 어차피 재생성 불가.

**의존성:** Phase 1 (triage-data.json 외부화), Phase 2 (subagent error handling)

**주의 (V2 Contrarian):** Deferred mode를 PRIMARY로 사용하면 ~5-10% save rate. 이 Phase는 **error fallback 전용**.

**단계:**
- [ ] `.triage-pending.json` 스키마 정의 **(Phase 2 의존)**
- [ ] SKILL.md Phase 3 subagent에 error handling 추가 **(Phase 2 의존)**
- [v] `memory_retrieve.py`에 pending save 감지 로직 추가
- [v] `memory_retrieve.py`에 orphan crash detection 추가 (V2 Contrarian)
- [v] SKILL.md Pre-Phase staging cleanup 추가 (fresh save, no resume)
- [v] 테스트: pending notification (21개 테스트 중 7개)
- [v] 테스트: orphan detection (21개 테스트 중 6개)
- [ ] 테스트: end-to-end save 실패 → pending 생성 → 다음 세션 감지 **(Phase 2 의존)**

**Rollback:** `memory_retrieve.py`의 pending 블록 제거. SKILL.md error handling은 무해하게 유지 가능.

---

### Phase 5: Optional Enhancements (P2-P3) [ ]

Phase 0 실험 결과 및 Phase 1-4 완료 후 선택적 진행.

#### 5a. Agent Hook Full Implementation (Phase 0 성공 시) [ ]

**조건:** Phase 0에서 agent hook subagent의 tool call이 메인 transcript에서 격리됨이 확인된 경우.

**Agent hook lifecycle (V2 Contrarian clarification):**
- Agent hook 시작 → 세션 자동 블록 (exit 불가, `ok` 값과 무관)
- Agent hook이 전체 pipeline 실행 (모든 tool call은 여기서 발생)
- Agent hook 반환 `ok: true` → 세션 exit 진행 / `ok: false` → 세션 exit 차단, reason 표시
- `ok` 값은 execution 중 blocking을 제어하지 않음 — execution 완료 후의 exit 허용 여부만 결정

**구현:**
- Stop hook을 `type: "agent"`로 변경
- Agent prompt가 전체 SKILL.md pipeline 실행 (또는 Bash로 `memory_triage.py` 호출 후 save)
- Save 성공 시 `ok: true` (세션 exit 허용), 실패 시 `ok: false` + error reason
- Save 결과를 `last-save-result.json`에 작성 (Phase 3 확인 경로 재사용)
- Timeout 120-180초 (pipeline 전체가 이 시간 내 완료 필요 — 세션은 전 시간 동안 블록됨)

**예상 효과:** UI noise 0-2 lines, context ~100 tokens

**단계:**
- [ ] Agent hook prompt 작성
- [ ] `hooks/hooks.json` Stop hook 변경
- [ ] 통합 테스트
- [ ] Visible output 측정 (목표: 0-2 lines)

#### 5b. Deferred Mode as Opt-in Config [ ]

**조건:** 사용자가 수동 제어를 선호하는 경우.

**주의 (V2 Contrarian):** session_summary 품질 저하, cross-project loss, ~5-10% trigger rate. **절대 default 아님.**

**단계:**
- [ ] `memory-config.json`에 `triage.save_mode` 추가
- [ ] `memory_triage.py`에 deferred mode 분기
- [ ] `memory_retrieve.py`에 notification
- [ ] 문서 업데이트

#### 5c. Foreground Single Task Consolidation (Solution 4) [ ]

**조건:** Fix A+B 이후에도 추가 noise 감소가 필요한 경우.

**예상 효과:** UI ~4-5 lines, context ~350 tokens

**단계:**
- [ ] SKILL.md 전체 재구성 (all phases → single Task)
- [ ] 통합 테스트
- [ ] Visible output 측정

---

## 리스크 및 완화 (Risks & Mitigations)

| 리스크 | 심각도 | 완화 전략 |
|--------|--------|----------|
| **Phase 1 배포 순서 오류** | CRITICAL | SKILL.md 먼저 배포 (backwards compatible), 그 후 memory_triage.py. 역순 시 silent save 실패 |
| **CUD resolution 정합성 깨짐** | HIGH | CUD 의사결정은 메인 에이전트가 수행. Subagent는 명령 실행만 (imperative execution) |
| **Agent hook 격리 미확인** | MEDIUM | Phase 0 time-boxed 실험. Fix A+B는 격리 여부와 무관하게 유효 |
| **Subagent transcript leakage** | MEDIUM | 알려진 버그. Phase 2 시작 전 isolation 검증. 발생 시 noise 감소 60% (85% 아님) |
| **`memory_write.py` venv bootstrap 실패** | MEDIUM | Phase 2 초기 독립 테스트. 실패 시 prompt에 activate 포함 |
| **triage-data.json 파일 쓰기 실패** | MEDIUM | Inline `<triage_data>` fallback (graceful degradation) |
| **Staging file 축적** | MEDIUM | Subagent cleanup 단계. Error path에서만 보존 |
| **Phase 2 subagent 실패** | MEDIUM | Deferred sentinel 작성 (Phase 4 연계) |
| **Save confirmation 반복 표시** | LOW | 24시간 timestamp check + 1회 표시 후 삭제 |
| **Partial save 혼란** | LOW | Confirmation + pending 동시 표시는 의도된 동작 (정확한 상태 전달) |

---

## Rollback 전략

| Phase | 수정 파일 | Rollback 방법 |
|-------|----------|--------------|
| Phase 0 | `hooks/hooks.json` (브랜치 격리) | `git checkout main` |
| Phase 1 | `memory_triage.py`, `SKILL.md`, `CLAUDE.md`, tests | `git revert` — SKILL.md는 backward compatible이므로 triage.py만 revert도 안전 |
| Phase 2 | `SKILL.md` | `git revert` Phase 2 commit. Phase 1 변경은 유지 |
| Phase 3 | `memory_retrieve.py` | Confirmation 블록 제거 |
| Phase 4 | `memory_retrieve.py`, SKILL.md | Pending 블록 제거 |

**호환성 매트릭스:**

| SKILL.md | memory_triage.py | 동작 |
|----------|-----------------|------|
| 구버전 | 구버전 | 현재 동작 (inline triage_data) |
| 신버전 | 구버전 | 정상 (inline fallback 사용) |
| 신버전 | 신버전 | 정상 (파일 기반 triage_data) |
| 구버전 | 신버전 | **BROKEN** — save silent 실패. 이 조합 방지 필수 |

---

## 진행 체크리스트

### Phase 0: Agent Hook Isolation 실험
- [ ] git 브랜치 생성
- [ ] 실험 A-D 실행
- [ ] 결과 문서화
- [ ] main 브랜치 복귀

### Phase 1: Fix A — triage_data 외부화
- [ ] SKILL.md Phase 0 업데이트 — **먼저 배포**
- [ ] `build_triage_data()` 헬퍼 추출
- [ ] `_run_triage()` 파일 쓰기 + error fallback
- [ ] `format_block_message()` 조건부 출력
- [ ] 기존 테스트 업데이트 (~15+ tests)
- [ ] 새 테스트 작성
- [ ] CLAUDE.md, SKILL.md 문서 업데이트
- [ ] `py_compile` + `pytest tests/ -v`
- [ ] 통합 검증

### Phase 2: Fix B — Phase 3 Single Task Subagent
- [ ] 5분 subagent isolation 검증
- [ ] SKILL.md Phase 3 재작성 (main CUD → subagent imperative)
- [ ] Task prompt 설계
- [ ] Cleanup + 결과 파일 로직
- [ ] Error handling (→ deferred sentinel)
- [ ] venv bootstrap 확인
- [ ] CUD 정합성 검증
- [ ] 통합 검증

### Phase 3: Save Confirmation
- [v] `last-save-result.json` 스키마 (글로벌 경로, project 필드, structured errors)
- [v] `memory_retrieve.py` confirmation 로직 (line 422 이전, 글로벌 경로, cross-project 지원)
- [v] 24h timestamp check + html.escape + _just_saved flag
- [ ] Phase 2 subagent에서 결과 파일 작성 **(Phase 2 의존)**
- [v] 테스트 (8개: same-project, cross-project, delete-after-display, old-ignored, corrupt, errors, no-file, short-prompt)

### Phase 4: Error Fallback
- [ ] `.triage-pending.json` 스키마 **(Phase 2 의존)**
- [ ] SKILL.md error handling **(Phase 2 의존)**
- [v] `memory_retrieve.py` pending 감지 (re-triage 메시지, dict 타입 가드)
- [v] `memory_retrieve.py` orphan crash detection (>5min staleness, _just_saved 억제)
- [v] SKILL.md Pre-Phase staging cleanup (fresh save, no resume)
- [v] SKILL.md Post-save atomic write + cleanup order (staging 먼저 삭제, 결과 파일 나중 작성)
- [v] 테스트 (13개: pending 7개 + orphan 6개)
- [ ] End-to-end 테스트 **(Phase 2 의존)**

### Phase 5: Optional
- [ ] 5a: Agent Hook Full Implementation (Phase 0 성공 시)
- [ ] 5b: Deferred Mode Opt-in
- [ ] 5c: Foreground Single Task

---

## 부록: 연구 소스 요약

**리서치 문서:** `research/memory-save-noise-reduction.md`

**연구 팀 구성:**
- 4 research agents (hook API, background agents, alt architectures, context impact)
- 2 V1 verification agents (security-ops, arch-UX)
- 2 V2 verification agents (contrarian, feasibility)
- Gemini 3.1 Pro cross-validation (4 rounds via PAL clink)
- V1 action plan reviewers (impl-verifier, risk-verifier)
- V2 action plan reviewers (contrarian, completeness)

**핵심 연구 결과:**
1. `suppressOutput`, `run_in_background` 등은 메인 에이전트 tool call 가시성 문제를 해결하지 못함
2. Fix A+B 조합이 가장 신뢰할 수 있는 primary path (60-85% noise 감소)
3. Agent hook 격리 여부는 경험적 테스트 필요 (문서에 명시적 보장 없음)
4. Deferred mode는 primary로 부적합 (~5-10% manual trigger rate, session_summary 품질 저하)
5. Inline API save는 보안 리스크 과대 (API key → prompt injection → exfiltration chain)

**V1/V2 검증 교정사항:**
- Deferred mode: Rank 2 → opt-in fallback (5-10% save rate, session_summary 파괴)
- Agent hook: "10분 실험" → "2-4시간" (스키마 차이)
- Fix A+B: fallback → primary (가장 낮은 리스크, 가장 높은 확실성)
- SessionStart hook → UserPromptSubmit 통합 (stdout 가시성 보장)
- triage_data scope bug fix (build_triage_data 헬퍼 추출)
- 배포 순서: SKILL.md 먼저 (backwards compatibility)
- CUD resolution: subagent 의사결정 → main agent 의사결정 + subagent 실행
- Insertion point: line 429 이후 → line 422 이전 (short prompt exit 전)
- Noise 감소: 85% → 60-85% 범위 (isolation 변수)

**연구 temp 파일:** `temp/research-*.md`, `temp/verification-*.md`, `temp/v2-*.md`, `temp/v1-impl-review.md`, `temp/v1-risk-review.md`
