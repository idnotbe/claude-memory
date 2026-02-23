# Action Plans 마이그레이션 프롬프트

아래 프롬프트를 각 레포의 Claude Code 인스턴스에 붙여넣어 사용.
필요에 따라 `[조정 포인트]` 부분을 수정.

---

## 프롬프트

```
이 레포에 action-plans/ 디렉토리를 도입하여 실행 계획 파일들을 체계적으로 관리하고자 한다.

## 배경

실행 계획(action plan) 파일들이 여기저기 흩어져 있거나, 상태(미시작/진행중/완료)를 파악하기 어렵다. 이를 해결하기 위해 아래 시스템을 적용한다.

## 해야 할 일

### 1. 디렉토리 구조 생성

action-plans/ 디렉토리를 만들고 하위에 _done/ 과 _ref/ 를 만들어라.

```
action-plans/
  README.md        # 시스템 규칙
  _done/           # 완료된 plan (.gitkeep 포함)
  _ref/            # 참고/역사적 문서 (.gitkeep 포함)
```

### 2. README.md 작성

action-plans/README.md 에 아래 내용 작성:

```markdown
# Action Plans

실행 계획 관리 디렉토리.

## 구조
- root의 .md 파일 = 활성 계획 (not-started, active, blocked)
- `_done/` = 완료된 계획
- `_ref/` = 참고/역사적 문서

## Frontmatter 규칙
모든 plan 파일 상단에 YAML frontmatter 필수:

---
status: not-started    # not-started | active | blocked | done
progress: "미시작"      # 현재 진행 상태 (자유 텍스트)
---

## Status Values
- **not-started**: 아직 시작 안 함
- **active**: 현재 진행 중
- **blocked**: 의존성 미해결로 대기
- **done**: 완료 → _done/으로 이동 가능

## Lifecycle
1. 새 plan 생성 → root에 파일 + frontmatter
2. 작업 시작 → status: active, progress 업데이트
3. 작업 완료 → status: done (선택: _done/으로 이동)
4. 참고 전환 → _ref/로 이동
```

### 3. 기존 plan 파일 마이그레이션

이 레포에 이미 plan/계획/실행 관련 파일이 있다면:
- plans/, plan/, docs/ 등에 있는 실행 계획 파일들을 action-plans/로 이동
- 각 파일 상단에 frontmatter 추가 (status + progress)
- 역사적/참고 문서는 action-plans/_ref/로 이동
- 이동한 파일을 참조하는 다른 파일(CLAUDE.md, README.md 등)의 경로 업데이트

[조정 포인트: 이 레포에서 plan 파일이 있는 위치를 확인하고 알려줘.
예시: plans/ 폴더, docs/ 폴더, 루트의 *-plan.md 파일 등]

### 4. CLAUDE.md 업데이트

CLAUDE.md에 아래 섹션 추가 (기존 내용에 맞게 적절한 위치에):

```markdown
## Action Plans

실행 계획 파일은 `action-plans/`에 있다. 각 파일 상단에 YAML frontmatter로 상태를 관리한다.

- `status`: not-started | active | blocked | done
- `progress`: 현재 진행 상태 (자유 텍스트)

**규칙:**
- plan 파일 작업 시작/완료 시 frontmatter의 status와 progress를 업데이트할 것
- 완료된 plan은 `action-plans/_done/`으로 이동 (선택)
- `action-plans/_ref/`는 참고/역사적 문서
```

### 5. .gitignore 확인

action-plans/ 가 .gitignore에 의해 무시되지 않는지 확인.

## 규칙

- 파일명은 kebab-case 사용 (예: plan-retrieval-improvements.md)
- frontmatter는 status와 progress 2개 필드만 (title, priority 등은 본문에 기술)
- 기존 파일의 내용은 변경하지 말 것 (frontmatter 추가 + 경로 이동만)
- 참조 경로 업데이트 누락 없도록 grep으로 전수 확인할 것

## 작업 완료 후

- 변경된 파일 목록과 각 변경 사유를 보여줘
- 경로가 깨진 참조가 없는지 확인 결과를 보여줘
```

---
