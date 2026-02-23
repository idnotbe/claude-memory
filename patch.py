import sys

file_path = "/home/idnotbe/projects/claude-memory/action-plans/plan-search-quality-logging.md"
with open(file_path, "r") as f:
    content = f.read()

rollback_section = """
## 롤백 전략 (Rollback Strategy)

| 단계 | 롤백 방법 (Rollback Method) | 영향 범위 (Impact Scope) |
|------|---------------------------|-------------------------|
| **Phase 2** (모듈) | `logging.enabled = false` 설정 변경, 또는 `memory_logger.py` 파일 삭제 (Lazy import 폴백 작동) | 파일 I/O 전면 중단. 기존 훅 로직(검색/주입)은 정상 동작 유지 (Fail-open) |
| **Phase 3** (계측) | 해당 스크립트의 `emit_event` 호출부 주석 처리/제거. (오류 발생 시 빈 함수로 자동 폴백) | 특정 파이프라인 지점의 로그만 누락. 검색/주입 기능 자체는 무영향 |
| **Phase 4** (마이그레이션) | 듀얼 라이트(Dual-write) 유지 기간 연장 및 기존 로그 출력(stderr 등) 방식 복구 | 구버전 로깅 파이프라인으로 복귀. 신규 JSONL 분석 일시 중단 |
| **전체** (Overall) | `git revert`를 통한 코드 롤백 및 축적된 로그 데이터 수동 삭제 (`rm -rf .claude/memory/logs/`) | 로깅 인프라 완전 제거 및 초기 상태(관측 불가 상태)로 원복 |
"""

if "## 롤백 전략" not in content:
    content = content.replace("## Plan #3 의존성", rollback_section + "\n## Plan #3 의존성")
    with open(file_path, "w") as f:
        f.write(content)
    print("Patch applied.")
else:
    print("Already exists.")
