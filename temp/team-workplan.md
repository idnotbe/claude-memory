# Team Workplan: Remove "model" field from Stop hooks

## Objective
Remove `"model": "sonnet"` from all 6 Stop hooks in `hooks/hooks.json` to fix the 404 error.
Default behavior (no model field) will use a fast model (Haiku) for prompt-type hooks.

## Target File
`hooks/hooks.json` — lines 10, 22, 34, 46, 58, 70

## Change Spec
- Remove `"model": "sonnet",` from each of the 6 Stop hook objects
- Preserve all other fields: type, timeout, statusMessage, prompt
- Ensure valid JSON after edit

## Team Structure

| Role | Name | Responsibility |
|------|------|---------------|
| Implementer | implementer | Make the edit, self-verify JSON validity |
| Safety Reviewer | safety-reviewer | Review from security/safety/risk angle |
| Correctness Reviewer | correctness-reviewer | Review from functional correctness angle |
| Verifier Round 1 | verifier-1 | Independent verification with sub-perspectives |
| Verifier Round 2 | verifier-2 | Second independent verification |

## Workflow
1. Implementer makes the change → writes result to temp/impl-result.md
2. Safety + Correctness reviewers read result file, review independently
3. Verifier-1 does first independent verification
4. Verifier-2 does second independent verification
5. All teammates use vibe-check and pal clink at key decision points

## Status
- [ ] Implementation
- [ ] Safety Review
- [ ] Correctness Review
- [ ] Verification Round 1
- [ ] Verification Round 2
