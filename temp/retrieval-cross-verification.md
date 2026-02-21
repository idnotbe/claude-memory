# 검색 시스템 교차 검증 보고서

**작성일**: 2026-02-19
**검증 대상**: 5개 분석 보고서 (주요 보고서 1 + 개별 보고서 4)

---

## 1. 보고서간 모순 (Contradictions)

### 1.1 Stop words 수량
- **주요 보고서**: "32개 불용어 집합" (섹션 4.1)
- **scoring-analysis**: "60 tokens" (섹션 1)
- **검증**: 실제 코드의 STOP_WORDS 집합을 세면 60개가 맞다. 주요 보고서의 "32개"는 오류.

### 1.2 description 접두사 매칭에서 `already_matched` 변수
- **주요 보고서**: `score_description()`에서 `already_matched = exact` 사용 명시 (섹션 5.1)
- **flow-analysis**: 동일하게 설명
- **scoring-analysis**: 동일 코드 인용 — 일치
- 모순 없음, 단 주요 보고서의 stop words 수량 오류가 유일한 사실 오류.

### 1.3 `int(score)` 버림 동작에 대한 평가
- **주요 보고서**: "의도된 것인지 확인하지 못했다"고 자가비판
- **scoring-analysis**: "int() truncation is likely unintentional"로 결론 도출
- 모순은 아니나 주요 보고서는 미확정, scoring-analysis는 버그로 판정.

---

## 2. 주요 보고서에 누락된 발견 (Missing from Main Report)

### 2.1 태그 XML 주입 / 데이터 경계 이탈 (security-analysis — 심각)
태그 값이 `</memory-context>`를 포함할 경우 XML 블록이 중간에 닫힌다. 쓰기 측 `auto_fix`가 `<`, `>` 문자를 태그에서 제거하지 않으므로 실제 공격 가능. **주요 보고서는 태그 미sanitize 언급만 있고 이 구체적 익스플로잇 경로를 명시하지 않음.**

### 2.2 `_sanitize_title()`의 연산 순서 버그 (security-analysis)
XML 이스케이프(step 4) 후 120자 절단(step 5)이 발생. `&`가 60개인 120자 제목은 `&amp;` 300자로 팽창 후 절단 → 손상된 HTML entity 출력. 기능 버그로 판정. **주요 보고서 미언급.**

### 2.3 `grace_period_days` 타입 검증 누락 (security-analysis)
`memory_index.py`의 `gc_retired`에서 `grace_period_days`에 타입 체크 없음. 문자열 설정 시 `age_days >= "30"` TypeError 발생. **주요 보고서 미언급.**

### 2.4 `cat_key`(카테고리 키) 미sanitize (security-analysis)
`descriptions` 속성 조립 시 `cat_key` 값은 sanitize되지 않음. 이례적 config 키에 `=`나 `"` 포함 시 이론적 속성 주입 가능. **주요 보고서 미언급.**

### 2.5 description 점수가 카테고리 전체에 동일하게 적용되는 문제 (scoring-analysis)
같은 카테고리의 모든 엔트리가 동일한 description 점수를 받음. SESSION_SUMMARY 설명에 "next", "steps", "session" 등 일반적 단어가 많아, 해당 단어를 언급하는 모든 프롬프트에서 SESSION_SUMMARY 엔트리 전체가 +2 부스트를 받음. **주요 보고서는 설명 점수 상한이 낮다고만 언급, 이 범주 범람(category flooding) 문제는 미언급.**

### 2.6 2자 이하 토큰(ci, db, ui 등) 영구 불일치 (scoring-analysis)
프롬프트에서 `ci`, `db`, `ui` 같은 토큰이 `tokenize()`의 `len(word) > 2` 필터로 제거됨. 엔트리 태그 `ci`도 마찬가지로 exact match에서 절대 매칭 불가. prefix check도 `len(pw) >= 4` 조건으로 불가. **주요 보고서 미언급.**

### 2.7 `match_strategy` config 키가 스크립트에서 완전히 무시됨 (flow-analysis)
`"title_tags"` 값은 문서화 목적이며 Python 스크립트는 항상 full pipeline(title+tags+description)을 사용. **주요 보고서 섹션 7.5에서 "agent-interpreted"로 언급은 하나, 미래 전략 구현 가능성의 gap으로 명시하지 않음.**

### 2.8 RUNBOOK 우선순위 역설 (architecture-critique)
오류 관련 프롬프트에서 RUNBOOK이 DECISION보다 더 유용하지만 priority 4로 더 낮음. 동점 시 DECISION이 RUNBOOK보다 항상 먼저 선택됨. **주요 보고서 미언급.**

### 2.9 body 토큰 미인덱싱 문제 (architecture-critique)
메모리 본문(body) 내용이 인덱스에 포함되지 않아 제목과 태그에만 의존. 관련 내용이 body에만 있는 RUNBOOK은 영구적으로 낮은 Pass 1 점수를 받음. 개선안으로 `#body:token1,token2` 접미사 추가 제안. **주요 보고서는 키워드 매칭 한계로만 언급, 구체적 해결책 미제시.**

### 2.10 프롬프트 링 버퍼(Ring Buffer) 개선 제안 (architecture-critique)
직전 3-5개 프롬프트 토큰을 저장하는 ring buffer로 follow-up 프롬프트("같은 방식으로 해줘") 대응. **주요 보고서는 단일 프롬프트 한계만 언급, 해결책 미제시.**

### 2.11 path 필드도 unsanitized (flow-analysis, security-analysis)
출력 라인의 `entry["path"]`도 XML 이스케이프 없이 출력됨. Linux에서 `<`를 포함하는 경로가 이론적으로 가능. **주요 보고서 미언급.**

---

## 3. 모든 보고서가 동의하는 핵심 사항 (Consensus Findings)

1. **두 단계 스코어링 구조 정확성**: Pass 1 (인덱스 텍스트 매칭) → Pass 2 (상위 20개 JSON 딥 체크) 구조가 모든 보고서에서 일치.

2. **점수 가중치 일치**: 타이틀 정확 일치 +2, 태그 정확 일치 +3, 접두사 매칭 +1, description cap 2점. 모든 보고서 동의.

3. **retired 엔트리 21위 이후 누락 문제**: 5개 보고서 모두 `_DEEP_CHECK_LIMIT = 20` 이후 엔트리가 retired 필터를 통과하지 못함을 지적.

4. **태그 unsanitized**: 출력 시 태그에 XML 이스케이프가 적용되지 않음. flow-analysis, security-analysis, 주요 보고서 모두 지적.

5. **path traversal in check_recency**: `entry["path"]`를 `project_root`에 결합할 때 containment 검증 없음. 주요 보고서(섹션 10.5), security-analysis, flow-analysis 모두 언급.

6. **키워드 매칭의 동의어 한계**: semantic search 부재, 형태소 분석 없음. 모든 보고서 동의.

7. **prefix 방향의 비대칭성**: `target.startswith(prompt_word)` 방향만 지원. "authentication"으로 "auth" 태그를 매칭할 수 없음. 모든 보고서 일치.

---

## 4. 가장 중요한 10가지 인사이트 (Top 10 Insights)

**#1. 태그 XML 주입으로 `<memory-context>` 블록 이탈 가능** [security-analysis]
태그에 `</memory-context>` 값 저장 시 데이터 경계 이탈. `memory_write.py`의 `auto_fix`가 `<`, `>`를 태그에서 제거하지 않아 실제 공격 가능. 수정: retrieval 출력 시 태그도 XML 이스케이프 적용.

**#2. stop words 수량 오류** [scoring-analysis vs 주요 보고서]
주요 보고서의 "32개" 수치가 틀림. 실제 60개. 테스트 케이스 작성 시 이 오류가 버그를 유발할 수 있음.

**#3. `_sanitize_title()` XML 이스케이프 후 절단 버그** [security-analysis]
120자 제한이 이스케이프 팽창 후에 적용되어 손상된 HTML entity 출력 가능. 절단은 이스케이프 전에 수행되어야 함.

**#4. description 점수의 카테고리 범람 효과** [scoring-analysis]
SESSION_SUMMARY의 풍부한 description 어휘("next", "steps", "session" 등)가 해당 단어를 포함하는 모든 프롬프트에서 모든 SESSION_SUMMARY 엔트리에 +2를 부여. max_inject=5 환경에서 관련 없는 세션 요약이 context를 채울 수 있음.

**#5. 2자 이하 기술 약어 영구 불일치** [scoring-analysis]
`ci`, `db`, `ui`, `k8`(k8s에서 s 분리) 등이 `tokenize()`와 exact match 모두에서 매칭 불가. 기술 프로젝트에서 중요한 약어들이 검색에서 완전히 누락.

**#6. RUNBOOK 우선순위 역설** [architecture-critique]
오류 해결에 가장 유용한 카테고리가 priority 4. 동점 시 DECISION(priority 1)에 항상 밀림. 오류 프롬프트에서 DECISION이 RUNBOOK보다 먼저 주입되는 역설.

**#7. body 내용 미인덱싱으로 관련 RUNBOOK 누락** [architecture-critique]
인덱스에 body 토큰이 없어 내용은 매우 관련있지만 제목/태그가 약한 RUNBOOK이 Pass 1에서 낮은 점수. 개선안: `#body:token1,...` 접미사 추가로 아키텍처 변경 없이 recall 향상.

**#8. 단일 프롬프트만 고려 — follow-up 프롬프트에서 검색 실패** [architecture-critique]
"계속해줘", "같은 방식으로" 같은 follow-up 프롬프트는 도메인 키워드가 없어 검색 결과 없음. ring buffer 제안으로 해결 가능하나 API 지원 여부 미확인.

**#9. `grace_period_days` 타입 미검증 → TypeError 크래시** [security-analysis]
config에 `"grace_period_days": "30"` (문자열)이면 `gc_retired` 실행 시 TypeError. `--gc` 명령어 크래시. 낮은 심각도이나 수정 용이.

**#10. index.md 자동 재빌드 시 제목 미sanitize** [security-analysis + 주요 보고서]
`memory_index.py`가 JSON에서 제목을 읽어 index.md에 그대로 기록. 쓰기 우회 시 ` -> ` 또는 `#tags:` 포함 제목이 인덱스를 오염. 인정된 설계 gap이나 `memory_write_guard.py` 우회 시 단일 실패 지점.

---

## 5. 남은 미확인 영역 (Remaining Unknowns)

1. **`memory_write.py`가 write 후 index.md를 즉시 재빌드하는지**: create/update 후 on-demand 재빌드 vs 다음 retrieval hook 실행까지 지연 여부 미확인. 인덱스 동기화 보장 여부 불명.

2. **Claude Code hook API가 대화 이력을 `UserPromptSubmit`에 제공하는지**: architecture-critique가 ring buffer 또는 이전 메시지 활용을 제안하나, 실제 hook payload에 conversation history가 포함되는지 불확인.

3. **prefix 방향 비대칭이 의도된 설계인지 버그인지**: `target.startswith(prompt_word)` 방향이 짧은 프롬프트 단어로 긴 엔트리 토큰을 찾는 것이 의도적인지, 반대 방향 지원 부재가 의도적인지 문서 없음.

4. **`int(score)` 버림이 의도적 설계인지**: `score_description()`의 `int()` 대신 `round()` 사용이 더 적절할 수 있으나, 원저자의 의도 미확인.

5. **인덱스 동시 재빌드 경쟁 조건**: 여러 `UserPromptSubmit` 이벤트가 동시에 발생할 때 여러 `memory_index.py --rebuild` subprocess가 경합할 수 있음. POSIX atomic rename이 이를 안전하게 처리하는지 미검증.

6. **Unicode NFC/NFKC 정규화 부재의 실제 영향**: `_sanitize_title()`이 Unicode 정규화를 하지 않아 시각적으로 동일하나 코드포인트가 다른 문자로 우회 가능 여부 미테스트.

7. **실제 성능 프로파일**: 500개 메모리, WSL 환경(네트워크 파일시스템 유사 특성)에서 20개 JSON 파일 딥 체크의 실제 지연 시간. architecture-critique가 100-400ms를 예측하나 실측값 없음.

---

*교차 검증 결과: 5개 보고서 간 사실 모순은 1개(stop words 수량)이며, 주요 보고서에 누락된 중요 발견은 11개. 모든 보고서가 동의하는 핵심 취약점은 retired 필터 gap, 태그 unsanitized, path traversal 3개.*
