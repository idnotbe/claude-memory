# CONSTRAINT Threshold Fix — Working Context

## Problem Summary
CONSTRAINT threshold(0.5) > max achievable score without booster(0.4737).
Math: `3 * 0.3 / 1.9 = 0.4737 < 0.5` → booster 없이 트리거 불가.
71 이벤트에서 booster 0회 매칭 → 사실상 CONSTRAINT 비활성.

## Current Code (memory_triage.py:132-149)
```python
"CONSTRAINT": {
    "primary": [
        re.compile(rf"{_WORD}(limitation|api\s+limit|cannot|restricted|not\s+supported|quota|rate\s+limit){_WORD}", re.IGNORECASE),
    ],
    "boosters": [
        re.compile(rf"{_WORD}(discovered|found\s+that|turns\s+out|permanently|enduring|platform){_WORD}", re.IGNORECASE),
    ],
    "primary_weight": 0.3,
    "boosted_weight": 0.5,
    "max_primary": 3,
    "max_boosted": 2,
    "denominator": 1.9,  # 3*0.3 + 2*0.5 = 1.9
}
```

## Current Config (assets/memory-config.default.json)
- threshold: 0.5 (all others are 0.4, session_summary is 0.6)

## Scoring Logic (memory_triage.py:355-404)
- For each line, check primary patterns
- If primary matches, check booster within ±4 lines window
- If booster found: raw_score += boosted_weight (0.5), up to max_boosted(2)
- Else: raw_score += primary_weight (0.3), up to max_primary(3)
- normalized = raw_score / denominator

## Score Quanta Table
| Scenario | Raw Score | Normalized |
|----------|-----------|-----------|
| 1 primary only | 0.3 | 0.1579 |
| 2 primary only | 0.6 | 0.3158 |
| 3 primary only | 0.9 | 0.4737 |  ← MAX without booster
| 1 boosted | 0.5 | 0.2632 |
| 1 boosted + 1 primary | 0.8 | 0.4211 |
| 1 boosted + 2 primary | 1.1 | 0.5789 |  ← FIRST to cross 0.5
| 2 boosted | 1.0 | 0.5263 |  ← crosses 0.5
| 2 boosted + 1 primary | 1.3 | 0.6842 |
| 2 boosted + 2 primary | 1.6 | 0.8421 |
| 2 boosted + 3 primary | 1.9 | 1.0000 |

## RUNBOOK Overlap
RUNBOOK primary: `error|exception|traceback|stack\s*trace|failed|failure|crash`
CONSTRAINT primary: `limitation|api\s+limit|cannot|restricted|not\s+supported|quota|rate\s+limit`
`cannot` is the overlap source — appears in both error contexts and constraint contexts.
Plan says 58.8% overlap in observed data.

## Option A: Keep booster gating (precision)
- Keep threshold 0.5
- Expand boosters: +incompatible, +deprecated, +blocked by, +upstream, +provider, +by design, +not configurable, +managed plan, +service tier, +vendor policy

## Option B: Relax booster gating (recall)
- Lower threshold to 0.47 (3-primary crosses)
- Demote `cannot` from primary to booster (RUNBOOK overlap fix)
- Add ops primaries: +does not support, +limited to, +hard limit, +service limit, +vendor limitation
- Update README

## Key Constraints
- Must be atomic (threshold + keyword together)
- Global default change needs N≥300, 3+ project types, precision≥70% (validation gate)
- Per-project change can be immediate
- README says "Limitation keywords + discovery co-occurrence" — may be intentional design

## Files to Modify
1. hooks/scripts/memory_triage.py (keywords + threshold)
2. assets/memory-config.default.json (threshold value)
3. README.md (docs)
4. tests/test_memory_triage.py (new regression tests)
