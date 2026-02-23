# CLAUDE.md Cleanup & Commit - Working Memory

## Tasks
1. [x] CLAUDE.md 정리 (claude-md-improver 스킬 사용)
2. [ ] TEST-PLAN.md 이동 확인 (CLAUDE.md에서 plans/TEST-PLAN.md 참조 변경됨)
3. [ ] External model opinions (clink: codex + gemini)
4. [ ] Vibe check
5. [ ] Commit & push
6. [ ] Independent verification x2

## Observations
- CLAUDE.md가 수정됨: `TEST-PLAN.md` → `plans/TEST-PLAN.md` (line 88)
- 하지만 TEST-PLAN.md가 실제로 plans/로 이동되었는지 확인 필요!
- 이전 작업에서 git mv로: rd-08 → plans/retrieval-improvement-plan.md, MEMORY-CONSOLIDATION-PROPOSAL.md → plans/
- 아직 커밋 안 됨

## Potential Issues
- TEST-PLAN.md 참조 변경 vs 실제 파일 위치 불일치 가능성 → RESOLVED (이미 plans/로 이동됨)
- CLAUDE.md 내 다른 경로 참조가 이전 작업으로 깨졌을 수 있음

## Model Consensus (Audit + Codex + Gemini + My analysis)

| 변경 사항 | Audit | Codex | Gemini | 결정 |
|-----------|-------|-------|--------|------|
| Security: 상세→요약 | Move out | Condense+link | Option D (topics only) | **Option D: 토픽 유지, 구현 상세 제거 (~7줄)** |
| "What needs tests" 삭제 | Remove | Remove | Delete | **삭제, pointer로 대체** |
| Smoke check 압축 | Loop | Loop | - | **단일 루프로** |
| Stale refs 수정 | Fix all | Fix, drop counts | - | **수정** |
| Setup 섹션 추가 | Add | Add | - | **2-3줄 추가** |
| Test count "15" | Fix to 16 | Accurate but brittle | - | **숫자 삭제, command-derived 추천** |

## Edit Plan - COMPLETED
1. [x] Fix stale ref: plugin.json → .claude-plugin/plugin.json
2. [x] Fix test section: remove stale list, remove brittle counts, add pointer
3. [x] Condense Security to ~7 lines with pointer
4. [x] Condense smoke check to loop
5. [-] Setup note: skipped (Venv Bootstrap section already covers essentials)

## Verification Results
- V1 (reference check): **ALL 7 CHECKS PASS** - all paths verified, no content loss
- V2 (semantic check): **PASS** with note: Security items 2+3 merged (acceptable)
  - Bonus: smoke check glob covers 11 files vs old list's 8 (improvement!)
  - Bonus: fixed 2 latent path bugs (plugin.json, memory-config.json)
- Result: 148 lines → 121 lines (-27 lines, -18%)

## Ready for commit + push
