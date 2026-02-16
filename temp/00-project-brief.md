# Stop Hook JSON Validation Error - Project Brief

## Problem
Claude Code의 대화 종료 시 6개의 Stop hooks (type: "prompt")에서 "JSON validation failed" 에러가 반복 발생.

## Current Architecture
- hooks/hooks.json에 6개의 Stop hooks (각 카테고리별: session_summary, decision, runbook, constraint, tech_debt, preference)
- 각 hook은 `type: "prompt"` 사용, Haiku/Sonnet 모델이 평가
- prompt 결과가 Claude Code가 기대하는 JSON 형식과 불일치하면 에러 발생

## Root Cause
- `type: "prompt"` hooks는 Claude Code가 내부적으로 LLM을 호출하여 평가
- LLM 응답이 Claude Code가 기대하는 structured JSON output과 일치하지 않을 때 에러
- 6개 hook이 병렬 실행되므로 에러 6번 발생
- 이전 수정(b99323e)에서 natural-language prompt로 전환했으나 여전히 에러 발생

## Previous Solution Attempted
1. JSON output → natural-language prompt로 전환 (b99323e) → 실패
2. 6개를 1개로 단일화 제안 → 에러 빈도 줄일 뿐 근본 해결 안됨

## User Requirements
1. **100% 에러 없는** Stop hooks
2. Hallucination 최소화 (gemini flash 등 병렬 사용 가능)
3. claude-mem (https://github.com/thedotmack/claude-mem) 구조 참고 (단, 메모리 누수 이슈 주의)

## Key Files
- hooks/hooks.json - 현재 hook 설정
- hooks/scripts/memory_*.py - Python 스크립트들
- .claude-plugin/plugin.json - 플러그인 매니페스트
- .claude/settings.json - 프로젝트 설정

## Constraints
- Claude Code의 Stop hook은 "prompt" 또는 "command" type만 지원
- "prompt" type은 LLM 응답의 JSON 포맷 불일치 위험 있음
- "command" type은 직접 실행하므로 JSON 에러 없음 (stdout/stderr만 반환)
- 단, "command" type은 conversation context에 접근 불가
