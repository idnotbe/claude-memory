# claude-memory 플러그인 로드 실패 수정 프롬프트

아래를 `~/projects/claude-memory`에서 Claude Code에 붙여넣으세요.

---

```
이 플러그인이 --plugin-dir로 로드할 때 "inline[0] Plugin · unknown · ✘ failed to load · 1 error"로 실패한다.

## 조사 결과

같은 ccyolo alias에서 로드되는 4개 플러그인(claude-code-guardian, vibe-check, deepscan, prd-creator)은 모두 정상 로드된다. claude-memory만 실패.

### 확인 완료 (문제 아님)
- JSON syntax: plugin.json, hooks.json 모두 valid
- 참조 파일: 모든 commands, skills, hook scripts 존재
- Python scripts: 모든 스크립트 import 성공, 에러 없음
- hook event types: UserPromptSubmit, PostToolUse, Stop 모두 공식 지원
- hook type "prompt": model, timeout, statusMessage 필드 포함 공식 지원
- hooks.json의 top-level "description" 필드: 공식 문서에 예시 있음

### 가장 유력한 원인: plugin.json의 `"engines"` 필드
- 정상 작동하는 4개 플러그인 중 어느 것도 `engines` 필드가 없음
- claude-memory만 유일하게 `"engines": {"claude-code": ">=1.0.0"}` 보유
- 플러그인 이름이 "unknown"으로 표시 → plugin.json 파싱 자체가 실패하는 것으로 추정
- Claude Code의 plugin.json 스키마가 additionalProperties를 허용하지 않을 가능성

### 수정 방법
1. `.claude-plugin/plugin.json`에서 `"engines"` 블록 제거
2. 수정 후 `ccyolo`로 로드 테스트

만약 engines 제거로 해결 안 되면, hooks.json에서 한 번에 하나씩 비활성화하며 원인 좁히기:
- 먼저 UserPromptSubmit 블록만 제거 후 테스트
- 그 다음 PostToolUse 블록만 제거 후 테스트
- 그 다음 Stop의 prompt-type hooks를 command-type으로 교체 후 테스트

수정하고 결과를 알려달라.
```
