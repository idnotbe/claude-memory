# Phase 2: Implementation Results -- CONSTRAINT Threshold Fix

**Date**: 2026-03-22
**Status**: Complete

## Changes Applied

### 1. hooks/scripts/memory_triage.py -- DEFAULT_THRESHOLDS (line 58)
- **Before**: `"CONSTRAINT": 0.5`
- **After**: `"CONSTRAINT": 0.45`

### 2. hooks/scripts/memory_triage.py -- CONSTRAINT primary regex (line 134-136)
- **Removed**: `cannot` from primary pattern
- **Added**: `does\s+not\s+support`, `limited\s+to`, `hard\s+limit`, `service\s+limit`, `vendor\s+limitation`
- **Final**: `limitation|api\s+limit|restricted|not\s+supported|quota|rate\s+limit|does\s+not\s+support|limited\s+to|hard\s+limit|service\s+limit|vendor\s+limitation`

### 3. hooks/scripts/memory_triage.py -- CONSTRAINT booster regex (line 140-142)
- **Added**: `cannot`, `by\s+design`, `upstream`, `provider`, `not\s+configurable`, `managed\s+plan`, `incompatible`, `deprecated`
- **Final**: `discovered|found\s+that|turns\s+out|permanently|enduring|platform|cannot|by\s+design|upstream|provider|not\s+configurable|managed\s+plan|incompatible|deprecated`

### 4. assets/memory-config.default.json (line 73)
- **Before**: `"constraint": 0.5`
- **After**: `"constraint": 0.45`

### 5. README.md (line 192)
- **Before**: `constraint=0.5`
- **After**: `constraint=0.45`

### 6. README.md (line 285)
- **Before**: `Limitation keywords + discovery co-occurrence`
- **After**: `Limitation keywords + structural/permanence co-occurrence`

## Self-Check Verification

| Check | Result |
|-------|--------|
| Regex syntactically valid | PASS -- `python3 -m py_compile` succeeded with no errors |
| Denominator still 1.9 | PASS -- line 149: `"denominator": 1.9` unchanged |
| DEFAULT_THRESHOLDS matches config default | PASS -- both show 0.45 for CONSTRAINT |
| README reflects new values | PASS -- threshold table shows 0.45, triage signal updated |
| Weights/caps unchanged | PASS -- primary_weight=0.3, boosted_weight=0.5, max_primary=3, max_boosted=2 |
| `cannot` fully demoted | PASS -- absent from primary, present in booster |
| Other categories unmodified | PASS -- DECISION, RUNBOOK, TECH_DEBT, PREFERENCE, SESSION_SUMMARY untouched |
