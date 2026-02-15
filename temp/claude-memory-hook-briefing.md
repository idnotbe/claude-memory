# claude-memory Stop Hook 에러: 조사 브리핑

## 문제

매 세션 종료 시 6개 Stop hook에서 "JSON validation failed" 에러 발생.

```
Ran 9 stop hooks
  Stop hook error: JSON validation failed   (x6)
```

## Debug 로그에서 확인된 실제 에러

```
404 {"type":"error","error":{"type":"not_found_error","message":"model: sonnet"}}
```

hooks.json의 `"model": "sonnet"` 이 API에서 404 리턴. Claude Code가 에러 메시지 텍스트를 JSON으로 파싱 시도하면서 "JSON validation failed" 표시.

## 수정 이력

| Round | Commit | 수정 내용 | 결과 |
|-------|--------|----------|------|
| 1 | 97c43e8 | extra JSON fields (lifecycle_event, cud_recommendation) 제거 → reason string에 임베드 | 실패 |
| 2 | b99323e | JSON formatting instructions 전부 제거, natural language only로 변환 | 실패 |

Round 1, 2 모두 프롬프트를 수정했지만, 실제 원인은 프롬프트가 아니라 **model alias "sonnet"이 resolve되지 않는 것**이었음.

## 이전 경위

- 원래 `"model": "haiku"` 사용 → haiku가 JSON을 잘못 쓴다고 판단하여 `"model": "sonnet"` 으로 변경 (commit 2bd67fa)
- 그런데 **"haiku"도 같은 404 에러였을 가능성**이 있음 (alias가 resolve 안 되는 동일한 문제)

## 핵심 질문

### Claude Code의 prompt-type hook에서 JSON 응답은 어떻게 생성되나?

**가능한 메커니즘 A: LLM이 JSON을 직접 작성**
- Claude Code가 내부 system prompt로 "respond with JSON `{ok, reason}`" 지시
- LLM이 JSON 문자열을 직접 생성
- Claude Code가 그 문자열을 파싱 + 검증

**가능한 메커니즘 B: 프로그래밍적 구성 (structured output / tool use)**
- Claude Code가 tool_use나 structured output을 사용
- LLM은 파라미터(ok 여부, reason 텍스트)만 전달
- Claude Code가 프로그래밍적으로 JSON 구성

**이것이 중요한 이유:**
- 메커니즘 A라면 → LLM이 JSON을 잘못 쓸 수 있음 → command-type hook으로 전환 권장
- 메커니즘 B라면 → JSON 형식 문제는 발생하지 않음 → model alias만 고치면 충분

### 추가 질문

1. `"model"` 필드에 유효한 값은? full model ID만 되나, alias("sonnet", "haiku")도 되나?
2. 이전에 "sonnet" alias가 작동했는데 언제/왜 깨졌나? (Claude Code 버전 업데이트?)
3. `"model"` 필드를 아예 제거하면 어떤 모델이 사용되나?

## 현재 hooks.json 구조 (6개 Stop hook 공통)

```json
{
  "type": "prompt",
  "model": "sonnet",        ← 이것이 404 원인
  "timeout": 30,
  "statusMessage": "Checking for ...",
  "prompt": "Evaluate whether ... (natural language)"
}
```

## 수정 옵션

| 옵션 | 변경 | 장점 | 단점 |
|------|------|------|------|
| A | `"model": "claude-haiku-4-5-20251001"` | 빠르고 저렴 | haiku가 JSON 잘 못 쓸 수 있음 (만약 메커니즘 A라면) |
| B | `"model": "claude-sonnet-4-5-20250929"` | 더 정확한 판단 | 느리고 비쌈 |
| C | `"model"` 필드 제거 | 가장 단순 | 세션 모델(Opus) 사용 → 매우 비쌈 |
| D | command-type hook으로 전환 | 완전한 제어 | 개발 필요 |
