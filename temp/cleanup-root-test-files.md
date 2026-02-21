# Root test_fts5*.py Files Cleanup Analysis

## Question
루트에 흩어진 test_fts5*.py 18개 파일: 삭제해도 되는가? tests/로 옮겨야 하는가?

## Investigation Results

### Finding 1: 프로젝트는 FTS5/SQLite를 전혀 사용하지 않음
- memory_retrieve.py: regex 기반 keyword matching (sqlite3 import 없음)
- memory_index.py: 파일시스템 스캔 + index.md 텍스트 파일 (DB 없음)
- memory_write.py: JSON CRUD + Pydantic 검증 (DB 없음)
- memory_candidate.py: markdown index 파싱 (DB 없음)

### Finding 2: 전부 standalone 실험/프로토타입 파일
- 모두 `sqlite3.connect(':memory:')` 직접 사용
- 프로젝트 모듈 import 없음 (hooks/scripts/*, tests/* 등 참조 없음)
- FTS5 쿼리 문법, 토큰화, BM25 스코어링 탐색 목적

### Finding 3: Git에 커밋된 적 없음
- `git log --oneline --all -- test_fts5*.py` 결과 없음
- 전부 untracked 상태 (`??`)
- 2026-02-20에 생성된 최근 연구 파일

### Finding 4: 반복/이터레이션 패턴
- underscore → underscore2 → underscore3 → underscore4 (점진적 실험)
- phrase → phrase2 (변형 테스트)
- bm25 → bm25_cutoff → bm25_mixed (스코어링 실험)

### Finding 5: research/ 및 temp/ 폴더에 관련 조사 문서 다수 존재
- FTS5를 미래 개선안으로 **평가**하는 연구 문서들
- 결론: 현재 키워드 매칭 방식 유지 (FTS5 미도입)

## Conclusion

**삭제해도 안전함.** 이유:
1. 프로젝트 기능과 무관한 독립 실험 파일
2. tests/로 옮길 이유 없음 (프로젝트 코드를 테스트하지 않음)
3. Git 미커밋 → 버전 관리되지 않는 일회성 파일
4. FTS5 도입 결정이 내려지지 않았으므로 보존 가치 낮음

## Self-Critique
- 혹시 research/ 폴더에 이미 정리본이 있어서 이 파일들의 핵심 지식이 보존되어 있는지? → research/ 폴더에 FTS5 관련 분석 문서 다수 존재 확인됨. 실험 결과의 핵심은 이미 문서화되어 있을 가능성 높음.
- 사용자가 나중에 FTS5 도입을 재검토할 때 필요할 수 있는가? → 실험 파일은 매우 단순(10~70줄)하여 재작성 용이. 보존 가치 < 정리 가치.
