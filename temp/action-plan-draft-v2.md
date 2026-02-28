---
status: not-started
progress: "미시작"
---

# Plan: Memory Save UI Noise Reduction

**날짜:** 2026-02-28
**범위:** Stop hook save process의 UI noise 85-100% 감소 (50-100+ lines → 0-12 lines)
**검증 소스:** Opus 4.6 (research lead), Gemini 3.1 Pro (4 rounds cross-validation), V1/V2 verification teams
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
| Phase 2: Fix B | Phase 3 save operations을 single Task subagent으로 통합 | ~30-50 lines → ~3 lines |
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
| V2 Contrarian | Fix A+B 먼저, agent hook은 2-4시간 필요 | "Agent hook은 10분 실험이 아님. prompt 필드, ok:true/false 스키마 차이. Fix A+B가 가장 신뢰할 수 있는 경로" |
| V2 Feasibility | Agent hook 실험 먼저, 실패 시 Fix A+B | "Stop 이벤트에서 type: agent 지원 확인됨. 격리 여부만 경험적 테스트 필요" |
| Gemini R3 (action plan review) | Fix A+B 먼저, 실험은 R&D로 | "Speculative spike가 guaranteed value 전달을 지연. Fix A+B는 실험 결과와 무관하게 필요" |
| V1 Arch/UX | Agent hook 먼저 테스트 | "테스트 비용 대비 잠재적 이득이 가장 큼" |

**합의 결정:** Phase 0 실험을 **엄격하게 시간 제한된 스파이크**(최대 반나절)로 먼저 실행. 결과 불문 빠르게 종료하고 Fix A+B로 진입.

**근거:** Agent hook 격리 여부는 전체 아키텍처 방향을 결정하며, 실험 비용이 낮다 (hooks.json 수정 + 간단한 prompt). 격리 확인 시 Phase 5a에서 Fix A+B를 대체하는 full implementation이 가능하여, Phase 2의 SKILL.md 재구성 범위를 조정할 수 있다.

**대안:** Gemini R3의 제안대로 Fix A+B를 먼저 구현하고 실험을 나중에 진행해도 무방. Fix A+B는 실험 결과와 무관하게 유효하므로, 어느 순서든 최종 결과는 동일하다. 팀 리소스가 있으면 Phase 0과 Phase 1을 병렬 실행 가능.

### 코드 참조

| 파일 | 라인 | Phase 관련 |
|------|------|----------|
| `hooks/hooks.json` | 8-13 | Phase 0 — 현재 Stop hook (`type: "command"`) |
| `hooks/scripts/memory_triage.py` | 950-953 | Phase 1 — `<triage_data>` 인라인 임베딩 |
| `hooks/scripts/memory_triage.py` | 1110-1131 | Phase 1 — sentinel + context file 작성 + block message 출력 |
| `hooks/scripts/memory_triage.py` | 870-955 | Phase 1 — `format_block_message()` 전체 |
| `skills/memory-management/SKILL.md` | 38-40 | Phase 1 — Phase 0 triage output 파싱 |
| `skills/memory-management/SKILL.md` | 188-212 | Phase 2 — Phase 3 save operations (main agent) |
| `skills/memory-management/SKILL.md` | 228-247 | Phase 2 — CUD Verification Rules section |
| `hooks/scripts/memory_retrieve.py` | 411-429 | Phase 3/4 — config 로딩 + short prompt skip (pending save 감지 삽입 지점: line 429 이후) |

---

## Phase 상세 설계

### Phase 0: Agent Hook Isolation 실험 [ ]

**목적:** `type: "agent"` hook의 subagent tool call이 메인 transcript에서 격리되는지 경험적 확인. 이 결과가 전체 아키텍처 방향을 결정한다.

**핵심 질문:**
1. Agent hook subagent의 tool call이 메인 대화 transcript에 보이는가?
2. `ok: false`가 Stop 이벤트에서 session 종료를 차단하는가?
3. Agent hook subagent가 `$CLAUDE_PLUGIN_ROOT` 환경변수에 접근 가능한가?
4. Agent hook subagent가 Stop 이벤트의 transcript/context에 접근 가능한가?
5. Timeout 동작: 기본 60초 내에 save pipeline 완료 가능한가?

**브랜치 격리 필수:** `hooks.json` 변경은 모든 세션에 영향 — 별도 git 브랜치 (`exp/agent-hook-stop`)에서 실행.

**실험 설계:**

```
현재 (baseline):
  hooks.json: type="command" → memory_triage.py → stdout JSON → decision: block
  결과: 메인 에이전트가 SKILL.md 실행, 모든 tool call 노출

실험 A (격리 테스트):
  hooks.json: type="agent" → prompt: "Run: echo hello via Bash tool. Then return ok:true"
  측정: Bash tool call이 메인 transcript에 보이는가?

실험 B (파일 접근 테스트):
  hooks.json: type="agent" → prompt: "Read .claude/memory/memory-config.json using Read tool. Return ok:true"
  측정: 파일 접근 가능 여부, $CLAUDE_PLUGIN_ROOT 해석 여부

실험 C (block 테스트):
  hooks.json: type="agent" → prompt: "Return ok:false with reason 'test block'"
  측정: 세션 종료 차단 여부, reason이 메인 에이전트에 전달되는 방식

실험 D (데이터 접근 테스트):  [Gemini R3 반영]
  hooks.json: type="agent" → prompt: "Read the $ARGUMENTS variable. Report what data you received."
  측정: Stop 이벤트의 transcript/payload가 agent hook에 전달되는지
  참고: command hook은 stdin으로 JSON payload 수신. agent hook은 $ARGUMENTS 치환.
```

**Agent Hook 스키마 주의사항** (V2 Contrarian 검증):
- Agent hook은 `prompt` 필드 사용 (`command` 필드 무시)
- 반환 스키마: `{"ok": true/false, "reason": "..."}` (command hook의 `{"decision": "block"}` 아님)
- Agent hook 내에서 임의 구조화 데이터를 메인 세션으로 전달 불가 — `ok`/`reason` 만 반환
- `$ARGUMENTS`로 hook input JSON을 prompt에 치환 가능 (확인 필요)

**종료 기준 (Kill Criteria):**
- 최대 반나절 time-box
- 격리 확인 불가 시: 아키텍처 dead-end로 판정, Phase 5a agent hook 구현 취소
- 격리 확인 시: Phase 5a에서 full implementation 진행

**종료 후 경로:**
- Kill criteria 충족 또는 time-box 만료 시:
  1. 브랜치 아카이브 (`exp/agent-hook-stop` 유지, main에 미병합)
  2. 실험 결과를 `temp/agent-hook-stop-results.md`에 문서화 (각 실험별 결과, 스크린샷/로그)
  3. Phase 1로 즉시 진행 (실험 결과와 무관하게)

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

**목적:** `format_block_message()`에서 `<triage_data>` JSON 블록을 인라인 삽입 대신 파일로 외부화. reason 필드를 ~25 lines에서 ~3 lines로 축소.

**변경 내용:**

**1. `memory_triage.py` — triage_data를 파일로 작성 (lines 1110-1131 근처)**

현재:
```python
# line 1127-1131
message = format_block_message(
    results, context_paths, parallel_config,
    category_descriptions=cat_descs,
)
print(json.dumps({"decision": "block", "reason": message}))
```

변경:
```python
# triage_data를 파일로 작성 (format_block_message가 이 dict를 생성하기 전에)
triage_data_path = os.path.join(
    cwd, ".claude", "memory", ".staging", "triage-data.json"
)
os.makedirs(os.path.dirname(triage_data_path), exist_ok=True)
# atomic write pattern
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
    triage_data_path=triage_data_path,  # 새 파라미터
)
print(json.dumps({"decision": "block", "reason": message}))
```

**참고:** `triage_data` dict는 `format_block_message()` 내부에서 생성된다 (lines 908-948). 이를 외부에서도 접근하려면 `format_block_message()`가 `triage_data`를 반환하거나, `_run_triage()`에서 별도로 구성해야 한다. 구현 시 가장 깨끗한 접근법을 선택할 것.

**2. `memory_triage.py` — format_block_message() 변경 (lines 950-953)**

현재:
```python
lines.append("")
lines.append("<triage_data>")
lines.append(json.dumps(triage_data, indent=2))
lines.append("</triage_data>")
```

변경:
```python
lines.append("")
lines.append(f"<triage_data_file>{triage_data_path}</triage_data_file>")
```

**3. `SKILL.md` — Phase 0 파싱 업데이트 (line 39)**

현재:
```
Extract the `<triage_data>` JSON block from the stop hook output.
```

변경:
```
Read the triage data file path from `<triage_data_file>` tag in the stop hook output.
Load the JSON from that file path. If the tag is not present, fall back to extracting
inline `<triage_data>` JSON block (backwards compatibility).
```

**테스트:**
- [ ] `memory_triage.py` 구문 검증: `python3 -m py_compile hooks/scripts/memory_triage.py`
- [ ] 기존 pytest 통과: `pytest tests/ -v`
- [ ] `.staging/triage-data.json` 파일 생성 확인
- [ ] SKILL.md가 파일에서 triage data 정상 로드 확인
- [ ] 인라인 `<triage_data>` fallback 테스트 (backwards compatibility)

**예상 효과:**
- reason 필드: ~25 lines → ~5 lines (카테고리 목록 + 파일 경로)
- 메인 context: ~2,000-3,000 토큰 절감

**단계:**
- [ ] `format_block_message()`에 `triage_data_path` 파라미터 추가 및 인라인 JSON 제거
- [ ] `_run_triage()`에 triage_data.json 파일 쓰기 로직 추가 (atomic write)
- [ ] SKILL.md Phase 0 업데이트 (파일 경로 기반 로드 + fallback)
- [ ] 단위 테스트 작성/업데이트
- [ ] 통합 테스트: 전체 save flow 검증

---

### Phase 2: Fix B — Phase 3 Single Task Subagent [ ]

**목적:** SKILL.md Phase 3 (save operations)를 메인 에이전트 대신 단일 foreground Task subagent에서 실행. Phase 3의 ~30-50 lines tool call noise를 ~3 lines로 축소.

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
Spawn ONE foreground Task subagent to handle all save operations.

The Task prompt MUST include:
- Phase 1/2 results summary (action, draft file path, verification status per category)
- CUD resolution table (full table from SKILL.md)
- Plugin root path for memory_write.py / memory_enforce.py
- All draft file paths

The subagent executes: CUD resolution → memory_write.py calls → memory_enforce.py → cleanup.
The subagent returns: brief summary of saves performed + save result file path.

The main agent waits for the Task result and outputs only the summary.
```

**CUD resolution context 전달 (Gemini R3 반영):**
- Phase 1/2 결과를 **Task prompt 인자에 직접 포함** (파일 쓰기 아님 — 파일 쓰기는 추가 tool call noise 생성)
- 결과가 짧으므로 (카테고리별 1-2줄) prompt에 직접 포함이 적합
- CUD resolution table 전체를 prompt에 명시적 포함

**Cleanup (Gemini R3 반영):**
- Phase 3 subagent가 save 완료 후 `.staging/triage-data.json` 삭제
- `.staging/context-*.txt` 파일도 삭제 (stale file 축적 방지)
- Save 결과를 `.staging/last-save-result.json`에 작성 (Phase 3 확인용)

**주의사항:**
- Subagent가 `$CLAUDE_PLUGIN_ROOT` 경로에 접근 가능해야 함 — SKILL.md에서 경로를 prompt에 포함
- `memory_write.py`의 venv bootstrap (`os.execv()`)이 subagent에서도 정상 동작해야 함
- CUD resolution table의 정확한 전달 필요 (이중 검증 로직 보존)

**테스트:**
- [ ] Subagent에서 `memory_write.py` 실행 가능 확인
- [ ] CUD resolution 결과 정합성 확인 (메인 에이전트 실행과 동일한 결과)
- [ ] save 완료 후 `memory_enforce.py` 정상 실행 확인
- [ ] `.staging/triage-data.json` 및 `context-*.txt` cleanup 확인
- [ ] `.staging/last-save-result.json` 생성 확인
- [ ] 전체 save flow의 visible output이 ~3-5 lines로 감소 확인

**예상 효과 (Fix A + Fix B 합산):**

| 지표 | Before | After |
|------|--------|-------|
| Visible lines | 50-100+ | ~8-12 |
| Main context tokens | 7,000-20,000 | ~1,000-1,500 |
| UI noise 감소 | — | ~85% |
| /compact 영향 | 심각 | 최소 |
| 품질 | Full SKILL.md | Full SKILL.md |

**단계:**
- [ ] SKILL.md Phase 3 섹션 재작성 (single Task subagent 패턴)
- [ ] Task prompt 설계: Phase 1/2 결과 + CUD table + 경로 정보 포함
- [ ] Cleanup 로직 추가 (triage-data.json, context-*.txt 삭제)
- [ ] Save 결과 파일 작성 로직 추가 (last-save-result.json)
- [ ] CUD resolution table이 subagent 내에서 정확히 적용되는지 검증
- [ ] `memory_write.py` venv bootstrap 동작 확인
- [ ] 통합 테스트: 전체 save flow 검증
- [ ] Visible output line count 측정 및 기록

---

### Phase 3: Save Confirmation via UserPromptSubmit [ ]

**목적:** 이전 세션에서 저장된 메모리를 다음 세션 첫 프롬프트에서 확인 메시지로 표시. Silent failure 방지.

**근거 (V1 Arch/UX Verifier):**
- 어떤 noise-reducing approach든 save 확인이 필요
- Silent failure와 silent success를 구분할 수 없으면 사용자가 lost memories를 너무 늦게 발견

**구현 방식 (Gemini R3 반영):**

> **SessionStart 대신 UserPromptSubmit 사용 결정.**
> Gemini R3에서 지적: SessionStart command hook의 stdout이 메인 UI에 표시되는지 불확실. UserPromptSubmit은 이미 `memory_retrieve.py`가 사용 중이며, stdout이 컨텍스트에 주입됨이 확인됨. 새 스크립트/hook을 추가하지 않고 기존 `memory_retrieve.py`에 통합하여 실행 오버헤드도 제거.

**1. Save 결과 파일** — Phase 2의 Task subagent가 작성:
```
.claude/memory/.staging/last-save-result.json
```
```json
{
  "saved_at": "2026-02-28T12:00:00Z",
  "categories": ["session_summary", "decision"],
  "titles": ["Session summary updated", "API auth decision"],
  "errors": []
}
```

**2. `memory_retrieve.py` 수정** — `main()` 함수 초반부 (line 429 이후, short prompt check 후):
```python
# Save confirmation from previous session
result_path = memory_root / ".staging" / "last-save-result.json"
if result_path.exists():
    try:
        result = json.loads(result_path.read_text())
        cats = result.get("categories", [])
        errors = result.get("errors", [])
        if cats:
            titles = result.get("titles", [])
            print(f"<memory-note>Previous session: {len(cats)} memories saved "
                  f"({', '.join(cats)}). {'; '.join(titles[:3])}</memory-note>")
        if errors:
            print(f"<memory-note>Previous session save errors: "
                  f"{'; '.join(errors[:3])}</memory-note>")
        result_path.unlink()  # 1회 표시 후 삭제
    except (json.JSONDecodeError, OSError):
        pass
```

**장점 (vs SessionStart hook):**
- 새 스크립트/hook 불필요 — 기존 `memory_retrieve.py`에 ~15줄 추가
- stdout → 컨텍스트 주입 경로가 이미 검증됨
- Python 프로세스 추가 실행 없음 (기존 프로세스에서 처리)
- UserPromptSubmit는 사용자 첫 프롬프트에서 발동 — SessionStart와 동일한 타이밍

**단계:**
- [ ] `last-save-result.json` 스키마 정의
- [ ] Phase 2의 Task subagent prompt에 결과 파일 작성 지시 추가
- [ ] `memory_retrieve.py`에 save confirmation 로직 추가 (line 429 이후)
- [ ] 테스트: 정상 save 후 다음 세션 첫 프롬프트에서 확인 메시지 표시
- [ ] 테스트: save 실패 시 error 메시지 표시
- [ ] 테스트: 확인 메시지 1회 표시 후 파일 삭제 확인

---

### Phase 4: Error Fallback — Deferred Sentinel [ ]

**목적:** Save 실패 시 deferred sentinel 파일을 작성하여 다음 세션에서 재시도할 수 있게 함.

**근거:** 인라인 save가 타임아웃이나 에러로 실패하면 메모리가 영구 손실됨. Deferred sentinel은 이에 대한 안전망.

**구현:**

1. **SKILL.md error handling** — Phase 3 subagent의 save 실패 시:
   - `.staging/triage-data.json`과 `context-*.txt` 파일을 삭제하지 않고 보존
   - `.staging/.triage-pending.json` sentinel 파일 작성:
   ```json
   {
     "created_at": "2026-02-28T12:00:00Z",
     "categories": ["session_summary", "decision"],
     "triage_data_path": ".claude/memory/.staging/triage-data.json",
     "error": "memory_write.py timeout after 30s"
   }
   ```

2. **`memory_retrieve.py`** (UserPromptSubmit hook) — pending save 감지:
   ```python
   # line 429 이후 삽입 (save confirmation 로직 직후)
   pending_path = memory_root / ".staging" / ".triage-pending.json"
   if pending_path.exists():
       try:
           pending = json.loads(pending_path.read_text())
           n = len(pending.get("categories", []))
           if n > 0:
               print(f"<memory-note>{n} unsaved memories from last session. "
                     f"Use /memory:save to save them.</memory-note>")
       except (json.JSONDecodeError, OSError):
           pass
   ```

3. **Cleanup** — `/memory:save` skill 실행 후:
   - `.triage-pending.json` 삭제
   - triage-data.json, context-*.txt 처리 후 삭제

**의존성:** Fix A (triage-data.json 외부화)

**주의 (V2 Contrarian):**
- Deferred mode를 PRIMARY로 사용하면 ~5-10% save rate
- 이 Phase는 **error fallback 전용** — 인라인 save 실패 시에만 발동
- 정상 경로에서는 발동하지 않음

**단계:**
- [ ] `.triage-pending.json` 스키마 정의
- [ ] SKILL.md Phase 3 subagent에 error handling 추가: save 실패 시 pending 파일 작성, staging files 보존
- [ ] `memory_retrieve.py`에 pending save 감지 로직 추가 (save confirmation 직후)
- [ ] `/memory:save` skill에서 pending 파일 처리 + cleanup 로직 추가
- [ ] 테스트: save 실패 시뮬레이션 → pending 파일 생성 → 다음 세션 감지

---

### Phase 5: Optional Enhancements (P2-P3) [ ]

Phase 0 실험 결과 및 Phase 1-4 완료 후 선택적 진행.

#### 5a. Agent Hook Full Implementation (Phase 0 성공 시) [ ]

**조건:** Phase 0에서 agent hook subagent의 tool call이 메인 transcript에서 격리됨이 확인된 경우.

**구현:**
- Stop hook을 `type: "agent"`로 변경
- Agent prompt가 전체 SKILL.md 4-phase pipeline 실행
- `ok: false` 반환으로 save 중 session 종료 방지 (또는 `ok: true`로 save 완료 후 종료 허용)
- Save 결과를 `last-save-result.json`에 작성 (Phase 3 확인 경로 재사용)

**예상 효과:** UI noise 0-2 lines, context ~100 tokens (reason string만)

**주의사항:**
- 기존 `memory_triage.py` command hook의 역할 (keyword triage)을 agent prompt 내에서 수행하거나, agent가 Bash로 `memory_triage.py`를 호출하는 방식 선택 필요
- Agent hook 내에서 `$CLAUDE_PLUGIN_ROOT` 해석 메커니즘 확인 필요 (Phase 0 실험 D에서 확인)
- Timeout을 120-180초로 설정 (전체 pipeline 소요 시간)
- Agent hook은 `ok:true/false`만 반환 — save 결과는 파일 기반으로 전달

**단계:**
- [ ] Agent hook prompt 작성 (triage + SKILL.md 전체 flow)
- [ ] `hooks/hooks.json` Stop hook 변경 (type: "agent", prompt, timeout: 180)
- [ ] 통합 테스트: 정상 save flow
- [ ] 통합 테스트: save 실패 시 error handling
- [ ] Visible output 측정 (목표: 0-2 lines)

#### 5b. Deferred Mode as Opt-in Config [ ]

**조건:** 사용자가 수동 제어를 선호하는 경우를 위한 옵트인 설정.

**구현:**
- `memory-config.json`에 `triage.save_mode` 필드 추가: `"inline"` (default) | `"deferred"`
- `"deferred"` 모드: Stop hook이 triage + context files만 작성하고 block하지 않음
- 다음 세션의 UserPromptSubmit에서 `/memory:save` 안내

**주의 (V2 Contrarian):**
- `session_summary` 카테고리는 deferred mode에서 품질 저하 (reconstruction artifact)
- Cross-project pending saves 감지 불가
- 수동 trigger rate ~5-10% 예상 — auto-capture 약속 위반
- **절대 default로 설정하지 않을 것**

**단계:**
- [ ] `memory-config.json`에 `triage.save_mode` 필드 추가
- [ ] `memory_triage.py`에 deferred mode 분기 추가
- [ ] `memory_retrieve.py`에 deferred save notification 로직 추가
- [ ] 문서 업데이트 (SKILL.md, CLAUDE.md)

#### 5c. Foreground Single Task Consolidation (Solution 4) [ ]

**조건:** Fix A+B 이후에도 추가 noise 감소가 필요한 경우.

**구현:**
- Stop hook이 최소 1-line reason으로 block
- 메인 에이전트가 전체 4-phase pipeline을 하나의 foreground Task subagent에서 실행
- Task 결과로 brief summary만 수신

**예상 효과:** UI ~4-5 lines, context ~350 tokens

**단계:**
- [ ] SKILL.md 전체 재구성 (Phase 0-3 → single Task prompt)
- [ ] Stop hook reason을 1-line으로 축소
- [ ] 통합 테스트
- [ ] Visible output 측정

---

## 리스크 및 완화 (Risks & Mitigations)

| 리스크 | 심각도 | 완화 전략 |
|--------|--------|----------|
| Agent hook 격리 미확인 | Medium | Phase 0 시간 제한 실험으로 빠르게 확인. Fix A+B는 격리 여부와 무관하게 유효 |
| SKILL.md Phase 3 재구성 시 CUD resolution 정합성 깨짐 | High | CUD resolution table을 Task prompt에 명시적 포함. 결과를 메인 에이전트 직접 실행과 비교 검증 |
| `memory_write.py` venv bootstrap이 Task subagent에서 실패 | Medium | Phase 2 초기에 독립 테스트. 실패 시 subagent prompt에 `source .venv/bin/activate` 포함 |
| Staging file 축적 (triage-data.json, context-*.txt) | Medium | Phase 2의 subagent cleanup 단계에서 명시적 삭제. Phase 4 error path에서만 보존 |
| Subagent transcript leakage (#14118, #18351) | Medium | 알려진 버그로 수정 가능성 있음. 발생 시 noise는 기존보다 여전히 적음 |
| Save confirmation message 미표시 (UserPromptSubmit 변경) | Low | 기존 `memory_retrieve.py` stdout → context 경로 이미 검증됨. 추가 hook 불필요 |
| Agent hook이 Stop event data에 접근 불가 | Medium | Phase 0 실험 D에서 확인. 실패 시 agent hook이 직접 triage 불가 → Bash로 memory_triage.py 호출 필요 |

---

## 진행 체크리스트

### Phase 0: Agent Hook Isolation 실험
- [ ] git 브랜치 생성
- [ ] 실험 A: 격리 테스트
- [ ] 실험 B: 파일 접근 테스트
- [ ] 실험 C: block 테스트
- [ ] 실험 D: 데이터 접근 테스트
- [ ] 결과 문서화
- [ ] main 브랜치 복귀

### Phase 1: Fix A — triage_data 외부화
- [ ] `format_block_message()` 수정
- [ ] `_run_triage()` 파일 쓰기 추가
- [ ] SKILL.md Phase 0 업데이트
- [ ] 테스트 작성/실행
- [ ] 통합 검증

### Phase 2: Fix B — Phase 3 Single Task Subagent
- [ ] SKILL.md Phase 3 재작성
- [ ] Task prompt 설계 (Phase 1/2 결과 + CUD table 직접 포함)
- [ ] Staging file cleanup 로직
- [ ] Save 결과 파일 작성 로직
- [ ] venv bootstrap 동작 확인
- [ ] 통합 검증

### Phase 3: Save Confirmation via UserPromptSubmit
- [ ] `last-save-result.json` 스키마 정의
- [ ] `memory_retrieve.py`에 confirmation 로직 추가
- [ ] Phase 2 subagent에서 결과 파일 작성 지시
- [ ] 테스트

### Phase 4: Error Fallback
- [ ] pending 파일 스키마/작성
- [ ] retrieve hook 감지 로직
- [ ] cleanup 로직
- [ ] 테스트

### Phase 5: Optional Enhancements
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
- Vibe check (2 rounds)

**핵심 연구 결과:**
1. `suppressOutput`, `run_in_background` 등은 메인 에이전트 tool call 가시성 문제를 해결하지 못함
2. Fix A+B 조합이 가장 신뢰할 수 있는 primary path (~85% noise 감소)
3. Agent hook 격리 여부는 경험적 테스트 필요 (문서에 명시적 보장 없음)
4. Deferred mode는 primary로 부적합 (~5-10% manual trigger rate, session_summary 품질 저하)
5. Inline API save는 보안 리스크 과대 (API key → prompt injection → exfiltration chain)

**V2 검증 교정사항:**
- Deferred mode: Rank 2 → opt-in fallback으로 강등 (5-10% manual trigger rate, session_summary 파괴)
- Agent hook: "10분 실험" → "2-4시간" 재산정 (prompt 필드, ok:true/false 스키마 차이)
- Fix A+B: "fallback" → primary 승격 (가장 낮은 리스크, 가장 높은 확실성)

**Action Plan V1 검증 교정사항 (V2 draft):**
- SessionStart hook → UserPromptSubmit 통합 (Gemini R3: stdout 가시성 보장 + 오버헤드 제거)
- Phase 0에 실험 D 추가 (Gemini R3: agent hook 데이터 접근 확인)
- Fix B context 전달: 파일 쓰기 → prompt 직접 포함 (Gemini R3: 추가 tool call noise 방지)
- Staging file cleanup 명시 (Gemini R3: stale file 축적 방지)
- Code reference 교정: memory_triage.py 1117-1131 → 1110-1131, memory_retrieve.py 411-429는 삽입 지점

**연구 temp 파일:** `temp/research-*.md`, `temp/verification-*.md`, `temp/v2-*.md`
