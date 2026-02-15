# Working Memory: claude-memory Storage Architecture Analysis

## Question
메모리 저장 단위는? 프로젝트별? 유저별? 글로벌?

## Three-Model Consensus (Claude Opus + Codex 5.3 + Gemini 3 Pro)

### 1. 메모리 저장 단위: **프로젝트별 (per-project)**
- 3개 모델 모두 동일한 결론
- 핵심 코드: `memory_root = Path(cwd) / ".claude" / "memory"`
- `cwd`는 Claude Code가 hook input으로 전달하는 프로젝트 루트 디렉토리
- 각 프로젝트마다 독립적인 `.claude/memory/` 디렉토리 생성

### 2. 유저 구분: **없음 (no user separation)**
- 스키마에 user_id/author 필드 없음
- 같은 프로젝트에서 작업하는 모든 사용자가 동일한 메모리 공유
- Gemini: "Team Brain"으로 기능 - 의도적 설계
- Codex: privacy 경계 없음 - 보안 리스크 가능성

### 3. 글로벌 설치 vs 로컬 저장
- 플러그인은 글로벌 설치 가능
- 저장은 항상 로컬 (각 레포의 `.claude/memory/`)
- 프로젝트 간 데이터 누출 없음

### 4. 주요 우려사항 (모델별 고유 관점)

| 모델 | 고유 우려사항 |
|------|-------------|
| Claude Explore | unclamped max_inject, config manipulation, index format fragility |
| Codex | _resolve_memory_root() fallback으로 .claude/memory 외부 쓰기 가능, create가 기존 파일 덮어쓸 수 있음 |
| Gemini | Git merge conflict on index.md (High severity), NFS/SMB에서 flock 불안정, 스키마 진화 시 마이그레이션 필요 |

### 디렉토리 구조
```
project-root/
└── .claude/
    └── memory/
        ├── memory-config.json
        ├── index.md
        ├── sessions/
        ├── decisions/
        ├── runbooks/
        ├── constraints/
        ├── tech-debt/
        └── preferences/
```
