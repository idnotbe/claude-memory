# Root Test File Cleanup - COMPLETED

## Summary
프로젝트 루트의 ad-hoc 테스트 파일 20개를 삭제하고 .gitignore에 재발 방지 패턴을 추가함.

## 삭제된 파일 (20개, 모두 untracked)

### Python (14개)
- test_atomic.py - PIPE_BUF 확인 snippet
- test_argparse.py - argparse 디버깅
- test_bash_guardian.py - 다른 프로젝트(claude-code-guardian) 참조
- test_bypass.py - regex quote detection (다른 프로젝트 관련)
- test_from_import.py - ImportError.name 테스트
- test_fts5.py - FTS5 기본 확인 (tests/test_fts5_*.py에서 커버)
- test_import.py - ImportError.name 테스트
- test_memory_guard.py - staging regex (tests/test_memory_write_guard.py에서 커버)
- test_regex.py - quote-aware regex (다른 프로젝트 관련)
- test_split.py - 다른 프로젝트(claude-code-guardian) 참조
- test_split2.py - 다른 프로젝트(claude-code-guardian) 참조
- test_subprocess.py - null byte 테스트
- hook_test.py - staging regex (tests/test_memory_write_guard.py에서 커버)
- hook_test2.py - staging regex (tests/test_memory_write_guard.py에서 커버)

### Shell (6개)
- test_bash.sh, test_bash_heredoc.sh~5.sh - heredoc/shift 실험

## 삭제 이유
1. 모두 print() 기반 ad-hoc snippet, pytest 형식 아님
2. 3개는 아예 다른 프로젝트 참조
3. 관련 기능은 tests/의 16개 proper pytest에서 이미 커버
4. tests/로 이동해도 완전히 재작성 필요 → 실질적으로 새 테스트 작성과 동일

## .gitignore 추가 패턴
```
/test_*.py
/test_*.sh
/hook_test*.py
```
루트 앵커(`/`)로 tests/ 폴더에는 영향 없음.

## 보존된 파일
- on_notification.wav, on_stop.wav (사용자 확인: 사용 중)

## 검증 결과 (2회 독립 검증, 모두 PASS)
- 루트에 test 파일 잔존 없음
- tests/ 디렉토리 16개 파일 + conftest.py 온전
- pytest 769 tests 수집 성공
- wav 파일 보존 확인
- .gitignore 패턴 확인
