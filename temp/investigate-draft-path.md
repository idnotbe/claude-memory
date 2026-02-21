# Investigation: memory_draft.py Path Reference Issue

## Problem Statement
- `ops` 프로젝트에서 `claude-memory` 플러그인 사용 중
- `/home/idnotbe/projects/claude-memory/hooks/scripts/memory_draft.py` 경로를 참조함
- 이 경로는 ops 경로도 아니고, 설치된 플러그인 경로(`~/.claude/plugins/claude-memory/`)도 아님
- 개발 소스 디렉토리를 직접 참조하고 있음

## Key Questions
1. `memory_draft.py`는 어디서 참조되는가? (hooks.json? SKILL.md? 다른 스크립트?)
2. `$CLAUDE_PLUGIN_ROOT`는 어떤 값으로 설정되는가?
3. 플러그인이 symlink로 설치되어 있는가?
4. `memory_draft.py`는 무엇을 하는 파일인가? (untracked file임)

## Investigation Tracks
- [ ] Track A: memory_draft.py 참조 위치 찾기
- [ ] Track B: 플러그인 설치 방식 확인 (symlink?)
- [ ] Track C: hooks.json 내용 확인
- [ ] Track D: $CLAUDE_PLUGIN_ROOT 설정 확인
- [ ] Track E: memory_draft.py 파일 내용 확인

## Findings

### Track A: memory_draft.py 참조 위치
- `hooks/hooks.json`: 참조 없음 (hook이 아님)
- `plugin.json`: 존재하지 않음
- `SKILL.md` (working tree): 6곳에서 참조 (steps 7, 8 등)
- `SKILL.md` (HEAD/커밋됨): 참조 없음 — 완전히 다른 파이프라인 사용
- `CLAUDE.md`: Key Files 테이블에 없음

### Track B: 플러그인 설치 방식
- `~/.claude/plugins/claude-memory/` 에 설치되어 있지 않음
- marketplace 설치도 아님
- `ccyolo` bash 함수가 `--plugin-dir ~/projects/claude-memory` 으로 로드
- ops의 `.claude/plugin-dirs`에 `~/projects/claude-memory` 등록됨
- → `$CLAUDE_PLUGIN_ROOT` = `/home/idnotbe/projects/claude-memory` (개발 소스 디렉토리)

### Track C: git 상태 불일치 (핵심 원인)
| 파일 | git 상태 | 내용 |
|------|----------|------|
| `SKILL.md` | Modified (unstaged) | memory_draft.py 참조 추가, /tmp → .staging 이동 등 |
| `hooks/scripts/memory_draft.py` | Untracked | 새로 작성된 draft assembler 스크립트 |
| `tests/test_memory_draft.py` | Untracked | 테스트 파일 |

HEAD의 SKILL.md는 `memory_draft.py`를 전혀 참조하지 않고, LLM이 직접 complete JSON을 `/tmp/`에 쓰는 구조.
Working tree의 SKILL.md는 `memory_draft.py`를 intermediate assembler로 사용하는 새 파이프라인.

### Track D: 외부 모델 의견 (codex 5.3 + gemini 3 pro)
- **Codex**: "expected path resolution, not a resolver bug. Dirty plugin build from dev tree."
- **Gemini**: "ticking time bomb in version control. User may think Claude is hallucinating."
- 둘 다 진단 일치: git state mismatch가 근본 원인

## Root Cause
**SKILL.md가 수정되어 memory_draft.py를 참조하지만, 이 변경사항이 커밋되지 않았음.**
- `--plugin-dir`로 개발 디렉토리를 직접 마운트하므로, untracked 파일도 접근 가능
- 경로 자체는 정상 (`$CLAUDE_PLUGIN_ROOT` 해석 결과)
- 하지만 사용자 입장에서는 "커밋되지 않은 파일의 절대 경로"가 나타나므로 혼란 발생

## Action Options
1. **커밋하기**: memory_draft.py + SKILL.md 변경 + test를 함께 커밋 → 정식 파이프라인으로 확정
2. **되돌리기**: SKILL.md를 HEAD로 복원 → 이전 파이프라인 (LLM이 직접 JSON 작성) 사용
3. **중간 방안**: ops에서 사용 시 커밋된 버전만 참조하도록 별도 release branch 사용
