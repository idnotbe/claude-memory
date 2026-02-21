# Agent Hook 검증 결과

## 핵심 발견: Agent hooks 존재하지만, 컨텍스트 주입 메커니즘이 다르다

### 확인된 사항
- Claude Code는 3가지 hook type 지원: `command`, `prompt`, `agent`
- Agent hooks는 UserPromptSubmit 이벤트 지원 O
- Agent hooks는 Read, Grep, Glob, Bash 등 도구 사용 가능 (최대 50턴)
- Plugin hooks/hooks.json에서도 agent 타입 사용 가능

### 결정적 차이: 출력 메커니즘
| Hook Type | 출력 | 용도 |
|-----------|------|------|
| command | stdout 텍스트 → Claude 컨텍스트에 주입 | 정보 제공 (현재 메모리 검색) |
| prompt/agent | `{ "ok": true/false, "reason": "..." }` → 허용/차단 결정 | 게이트키핑 |

### 함의
- **Command hook**: 메모리 검색 결과를 stdout으로 출력 → Claude 컨텍스트에 자동 주입. 이것이 현재 방식.
- **Agent hook**: Binary decision (ok/false) 반환. ok=false 시 reason이 Claude에게 전달되지만, 이는 "차단 사유"이지 "주입 컨텍스트"가 아님.

### 결론
1. Adversarial reviewer의 "hard constraint is false" 주장은 **부분적으로 정당**:
   - Agent hooks가 존재한다는 것은 맞음
   - UserPromptSubmit에서 사용 가능한 것도 맞음
   - LLM 판단을 hook에서 할 수 있다는 것도 맞음

2. 하지만 **메모리 주입(context injection)에는 여전히 command hook이 필요**:
   - Agent hook은 ok/false를 반환하지, 임의 텍스트를 주입하지 않음
   - 메모리 검색 결과를 Claude 컨텍스트에 넣으려면 command hook의 stdout 메커니즘이 필요

3. **하이브리드 접근 가능성**:
   - Command hook: BM25 검색 + 결과 주입 (현재 방식 유지)
   - Agent hook: 주입된 결과의 적절성 판단 (추가 가능)
   - 하지만 이는 두 개의 hook을 연쇄 실행하는 것이며, 복잡성 증가

4. **실질적 영향**: Synthesis의 핵심 결론(BM25 command hook으로 주입)은 여전히 유효.
   다만 "agent hooks 존재하며 향후 활용 가능"이라는 점은 반영해야 함.
