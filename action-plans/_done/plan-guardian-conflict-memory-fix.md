---
status: done
progress: "완료. C2 staging guard + C1 SKILL.md 강화 + 24 tests + V1/V2 검증 + ReDoS fix + CLAUDE.md 업데이트"
---

# Plan #4: Guardian 충돌 메모리 측 즉시 수정 (Guardian Conflict Memory-Side Immediate Fix)

**날짜:** 2026-02-22
**범위:** 2개 즉시 수정 (SKILL.md 강화 + PreToolUse:Bash staging guard)
**소요 시간:** ~45분
**검증 소스:** Codex 5.3 (planner), Gemini 3 Pro (planner), Vibe-check
**분석 문서:** `research/guardian-memory-pretooluse-conflict.md`

---

## 배경 (Background)

### 문제 요약

메모리 플러그인의 서브에이전트(특히 haiku 모델)가 `.claude/memory/.staging/` 디렉토리에 JSON 파일을 작성할 때, Write tool 대신 Bash heredoc(`cat > path << 'EOFZ'`)을 사용하면 Guardian 플러그인의 `bash_guardian.py`가 false positive를 발생시킨다.

**20시간 동안 7회 팝업 발생.** 사용자 작업 흐름이 반복적으로 중단됨.

### 두 가지 독립적 실패 모드

| 실패 모드 | 트리거 | Guardian 코드 경로 | 사용자 메시지 |
|-----------|--------|-------------------|-------------|
| **A: 경로 해석 실패** | Heredoc body에 `>` 포함 (예: `B->A->C`) | `split_commands()` → `is_write_command()` → F1 fail-closed | `[CONFIRM] Detected write but could not resolve target paths` |
| **B: 보호 경로 감지** | Heredoc body에 `.env` 문자열 포함 | `scan_protected_paths()` on raw string | `[CONFIRM] Protected path reference detected: .env` |

### 기존 수정 이력

이미 SKILL.md에 Write tool 사용 mandate가 추가되었으나(Fix C), 서브에이전트(특히 소형 모델)가 이를 무시한다. **LLM 준수율은 100%가 아니므로** 프롬프트 강화만으로는 불충분하며, 프로그래밍 방식의 가드레일이 필요하다.

---

## 목적 (Purpose)

| 수정 | 목적 | 방어 계층 |
|------|------|----------|
| **C1: SKILL.md 강화** | 서브에이전트가 heredoc 사용 자체를 시도하지 않도록 프롬프트 수준 억제 | 소프트 (행동 교정) |
| **C2: staging guard hook** | heredoc 시도를 프로그래밍 방식으로 차단 + 올바른 패턴 안내 | 하드 (강제 차단) |

**두 계층을 함께 배포함으로써:**
- C1이 대부분의 시도를 사전에 방지 (soft layer)
- C2가 나머지 시도를 강제 차단 (hard layer)
- Guardian false positive 팝업이 완전히 제거됨

---

## 관련 정보 (Related Info)

### 구현 순서 결정

| 소스 | 추천 순서 | 핵심 근거 |
|------|----------|----------|
| Codex 5.3 | C1 -> C2 | "SKILL.md 변경이 더 간단하고 즉각적. Guard hook은 후속 안전망" |
| Gemini 3 Pro | **C2 -> C1** | "가드레일(C2) 먼저 적용하여 차단 검증(Fail-fast), 이후 C1로 트리거 자체를 제거. Test-Driven 접근" |
| Vibe-check | 순서 무관 | "45분 내 두 가지 모두 배포. 순서는 중요하지 않음" |

**결정: C2 -> C1 순서.** Gemini의 Test-Driven 접근법 채택. 하드 가드레일(C2)을 먼저 배포하여 차단이 정상 작동하는지 검증한 후, 소프트 계층(C1)으로 트리거 빈도를 0으로 수렴시킨다.

### 리스크 평가

| 리스크 | 심각도 | 완화 방안 |
|--------|--------|----------|
| Guard hook regex가 비쓰기 명령까지 차단 (false positive) | 중간 | regex에 리다이렉션 연산자(`>`) 필수 매칭 포함. 읽기 전용 명령(`cat`, `ls`, `grep` 등)은 `>` 없으면 무통과 |
| 경로 우회 (셸 변수, 상대 경로) | 낮음 | 서브에이전트는 SKILL.md 템플릿을 따르므로 exotic 경로 패턴 사용 가능성 극히 낮음. C1이 1차 방어 |
| Deny loop (에이전트가 재시도 반복) | 낮음 | deny 메시지에 정확한 대안 패턴(Write tool 사용법) 포함하여 즉시 전환 유도 |
| Guardian이 memory guard보다 먼저 실행 | 낮음 | 플러그인 간 hook 실행 순서 미보장. Memory guard는 defense-in-depth -- Guardian 팝업이 먼저 뜨더라도 근본 원인(heredoc 사용)은 C1이 억제 |

### 코드 참조

| 파일 | 라인 | 역할 |
|------|------|------|
| `skills/memory-management/SKILL.md` | 81-83 | 현재 Write tool mandate (강화 대상) |
| `hooks/hooks.json` | 전체 | 현재 hook 등록 (C2 추가 대상) |
| `hooks/scripts/memory_write_guard.py` | 전체 | 기존 PreToolUse:Write guard (C2 패턴 참고) |
| `research/guardian-memory-pretooluse-conflict.md` | Section 2 | 수정 상세 설계 |

---

## 실행 단계 (Execution Steps)

### Step 1: Fix C2 -- `memory_staging_guard.py` 생성 (20분) [v] DONE

#### 1-1. 스크립트 생성

**파일:** `hooks/scripts/memory_staging_guard.py`

```python
#!/usr/bin/env python3
"""Memory staging guard -- blocks Bash writes to .staging/ directory."""
import json, re, sys

def main():
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    if input_data.get("tool_name") != "Bash":
        sys.exit(0)

    command = input_data.get("tool_input", {}).get("command", "")

    # Detect writes to .staging/ via bash (require redirection operator)
    staging_write_pattern = (
        r'(?:cat|echo|printf)\s+[^|&;\n]*>\s*[^\s]*\.claude/memory/\.staging/'
        r'|'
        r'\btee\s+.*\.claude/memory/\.staging/'
        r'|'
        r'(?:cp|mv|install|dd)\s+.*\.claude/memory/\.staging/'
        r'|'
        r'[&]?>{1,2}\s*[^\s]*\.claude/memory/\.staging/'
    )

    if re.search(staging_write_pattern, command, re.DOTALL | re.IGNORECASE):
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "Bash writes to .claude/memory/.staging/ are blocked to prevent "
                    "guardian false positives. Use the Write tool instead: "
                    "Write(file_path='.claude/memory/.staging/<filename>', content='<json>')"
                ),
            }
        }))
        sys.exit(0)

    sys.exit(0)

if __name__ == "__main__":
    main()
```

#### 1-2. Hook 등록

**파일:** `hooks/hooks.json` -- `PreToolUse` 배열에 다음 항목 추가:

```json
{
  "matcher": "Bash",
  "hooks": [
    {
      "type": "command",
      "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_staging_guard.py\"",
      "timeout": 5,
      "statusMessage": "Checking memory staging write..."
    }
  ]
}
```

**변경 후 `PreToolUse` 섹션 전체:**
```json
"PreToolUse": [
  {
    "matcher": "Write",
    "hooks": [
      {
        "type": "command",
        "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_write_guard.py\"",
        "timeout": 5,
        "statusMessage": "Checking memory write path..."
      }
    ]
  },
  {
    "matcher": "Bash",
    "hooks": [
      {
        "type": "command",
        "command": "python3 \"$CLAUDE_PLUGIN_ROOT/hooks/scripts/memory_staging_guard.py\"",
        "timeout": 5,
        "statusMessage": "Checking memory staging write..."
      }
    ]
  }
]
```

#### 1-3. 컴파일 검증

```bash
python3 -m py_compile hooks/scripts/memory_staging_guard.py
```

---

### Step 2: Fix C1 -- SKILL.md 강화 (10분) [v] DONE

**파일:** `skills/memory-management/SKILL.md` lines 81-83

**Before (현재):**
```markdown
> **MANDATE**: All file writes to `.claude/memory/.staging/` MUST use the **Write tool**
> (not Bash cat/heredoc/echo). This avoids Guardian bash-scanning false positives
> when memory content mentions protected paths like `.env`.
```

**After (교체):**
```markdown
> **FORBIDDEN**: You are PROHIBITED from using the Bash tool to create or write
> files in `.claude/memory/.staging/`. This includes `cat >`, `echo >`, heredoc
> (`<< EOF`), `tee`, or any other shell write mechanism. ALL staging file writes
> MUST use the **Write tool** exclusively.
>
> **Anti-pattern (DO NOT DO THIS):**
> ```bash
> # WRONG -- will be blocked by Guardian and memory guard hooks
> cat > .claude/memory/.staging/input-decision.json << 'EOFZ'
> {"title": "..."}
> EOFZ
> ```
>
> **Correct pattern:**
> ```
> Use the Write tool with path: .claude/memory/.staging/input-decision.json
> ```
```

---

### Step 3: 테스트 (15분) [v] DONE

#### 테스트 매트릭스

| # | 카테고리 | 테스트 케이스 | 예상 결과 |
|---|---------|-------------|----------|
| T1 | 차단 (True Positive) | `cat > .claude/memory/.staging/test.json << 'EOF'` | **DENY** + Write tool 안내 메시지 |
| T2 | 차단 (True Positive) | `echo '{"title":"test"}' > .claude/memory/.staging/test.json` | **DENY** |
| T3 | 차단 (True Positive) | `tee .claude/memory/.staging/test.json` | **DENY** |
| T4 | 차단 (True Positive) | `cp /tmp/test.json .claude/memory/.staging/test.json` | **DENY** |
| T5 | 허용 (True Negative) | Write tool로 `.staging/` 파일 생성 | **ALLOW** (Write tool은 Bash 아님) |
| T6 | 허용 (True Negative) | `cat .claude/memory/.staging/test.json` (읽기 전용) | **ALLOW** (`>` 없으므로 무통과) |
| T7 | 허용 (True Negative) | `ls .claude/memory/.staging/` | **ALLOW** |
| T8 | 허용 (True Negative) | `cat > /tmp/test.json << 'EOF'` (다른 디렉토리) | **ALLOW** |
| T9 | 허용 (True Negative) | `python3 hooks/scripts/memory_write.py --action create ...` | **ALLOW** (python3 실행은 패턴 미해당) |
| T10 | 차단 (True Positive) | `mv /tmp/x.json .claude/memory/.staging/x.json` | **DENY** |
| T11 | 차단 (True Positive) | `dd if=/tmp/x.json of=.claude/memory/.staging/x.json` | **DENY** |
| T12 | 차단 (True Positive) | `install /tmp/x.json .claude/memory/.staging/x.json` | **DENY** |
| T13 | 차단 (True Positive) | `> .claude/memory/.staging/test.json` (command-less redirect) | **DENY** |
| T14 | 차단 (True Positive) | `tee -a .claude/memory/.staging/test.json` (플래그 포함) | **DENY** |
| T15 | 회복 (Recovery) | T1 차단 후 에이전트가 Write tool로 전환하는지 | deny 메시지 내 안내 확인 |

#### 수동 검증 방법

```bash
# T1: heredoc 차단 검증
echo '{"tool_name":"Bash","tool_input":{"command":"cat > .claude/memory/.staging/test.json << '\''EOFZ'\''\n{\"title\":\"test\"}\nEOFZ"}}' | \
  python3 hooks/scripts/memory_staging_guard.py
# 예상: JSON 출력에 "permissionDecision": "deny" 포함

# T6: 읽기 허용 검증
echo '{"tool_name":"Bash","tool_input":{"command":"cat .claude/memory/.staging/test.json"}}' | \
  python3 hooks/scripts/memory_staging_guard.py
# 예상: 출력 없음 (exit 0)

# T8: 다른 디렉토리 허용 검증
echo '{"tool_name":"Bash","tool_input":{"command":"cat > /tmp/test.json << '\''EOF'\''\n{}\nEOF"}}' | \
  python3 hooks/scripts/memory_staging_guard.py
# 예상: 출력 없음 (exit 0)
```

#### pytest 테스트 (신규)

`tests/test_memory_staging_guard.py` 파일을 생성하여 주요 케이스를 자동화:

```python
import json, subprocess

SCRIPT = "hooks/scripts/memory_staging_guard.py"

def run_guard(tool_name, command):
    input_data = json.dumps({"tool_name": tool_name, "tool_input": {"command": command}})
    result = subprocess.run(
        ["python3", SCRIPT], input=input_data, capture_output=True, text=True
    )
    return result.stdout.strip(), result.returncode

def test_blocks_heredoc_to_staging():
    out, _ = run_guard("Bash", "cat > .claude/memory/.staging/input.json << 'EOFZ'\n{}\nEOFZ")
    assert '"deny"' in out

def test_blocks_echo_to_staging():
    out, _ = run_guard("Bash", "echo '{}' > .claude/memory/.staging/input.json")
    assert '"deny"' in out

def test_blocks_tee_to_staging():
    out, _ = run_guard("Bash", "echo '{}' | tee .claude/memory/.staging/input.json")
    assert '"deny"' in out

def test_blocks_cp_to_staging():
    out, _ = run_guard("Bash", "cp /tmp/x.json .claude/memory/.staging/x.json")
    assert '"deny"' in out

def test_blocks_mv_to_staging():
    out, _ = run_guard("Bash", "mv /tmp/x.json .claude/memory/.staging/x.json")
    assert '"deny"' in out

def test_blocks_dd_to_staging():
    out, _ = run_guard("Bash", "dd if=/tmp/x.json of=.claude/memory/.staging/x.json")
    assert '"deny"' in out

def test_blocks_install_to_staging():
    out, _ = run_guard("Bash", "install /tmp/x.json .claude/memory/.staging/x.json")
    assert '"deny"' in out

def test_blocks_bare_redirect_to_staging():
    out, _ = run_guard("Bash", "> .claude/memory/.staging/test.json")
    assert '"deny"' in out

def test_blocks_tee_with_flags():
    out, _ = run_guard("Bash", "echo '{}' | tee -a .claude/memory/.staging/test.json")
    assert '"deny"' in out

def test_allows_write_tool():
    out, _ = run_guard("Write", ".claude/memory/.staging/input.json")
    assert out == ""

def test_allows_read_from_staging():
    out, _ = run_guard("Bash", "cat .claude/memory/.staging/input.json")
    assert out == ""

def test_allows_ls_staging():
    out, _ = run_guard("Bash", "ls .claude/memory/.staging/")
    assert out == ""

def test_allows_other_directory():
    out, _ = run_guard("Bash", "cat > /tmp/test.json << 'EOF'\n{}\nEOF")
    assert out == ""

def test_allows_memory_write_script():
    out, _ = run_guard("Bash", "python3 hooks/scripts/memory_write.py --action create --category decision")
    assert out == ""
```

---

## 배포 후 모니터링

### 성공 기준

| 지표 | 목표값 | 측정 방법 |
|------|--------|----------|
| Guardian false positive 팝업 | **0회** | 사용자 수동 관찰 (24시간) |
| staging guard deny 발동 횟수 | **0에 수렴** | C1이 효과적이면 guard가 발동할 일이 없음 |
| 메모리 저장 실패율 | **변화 없음** | Write tool 경로는 영향 없으므로 기존과 동일해야 함 |

### 모니터링 체크리스트

- [ ] 배포 후 24시간 Guardian 팝업 발생 여부 확인
- [ ] Deny loop (에이전트 재시도 반복) 패턴 관찰 시 deny 메시지 개선
- [ ] 서브에이전트가 deny 후 Write tool로 올바르게 전환하는지 확인
- [ ] `guardian.log`에 `.staging/` 관련 경고 신규 발생 여부 교차 검증

---

## 의존성 매핑

```
이 계획 (Plan #4)
├── 선행 조건: 없음 (즉시 실행 가능)
├── 차단 대상: Guardian false positive 문제 (해결)
└── 후속 작업 (선택적, 별도 계획):
    ├── Guardian parser heredoc 인식 추가 (Fix A) -- claude-code-guardian repo
    ├── is_write_command() 따옴표 인식 (Fix B) -- claude-code-guardian repo
    └── scan_protected_paths() heredoc body 제외 (Fix A2) -- claude-code-guardian repo
```

**참고:** Guardian 측 수정(Fix A/B/A2)은 별도 리포지토리에서 중기적으로 진행. 이 계획의 즉시 수정(C1+C2)으로 메모리 플러그인 사용자의 문제는 즉시 해결된다.

---

## CLAUDE.md 업데이트 사항

Plan #4 완료 후 `CLAUDE.md` Key Files 테이블에 추가:

```markdown
| hooks/scripts/memory_staging_guard.py | PreToolUse:Bash guard blocking heredoc writes to .staging/ | stdlib only |
```

`hooks/hooks.json` 설명도 Hook Type 테이블에 반영:

```markdown
| PreToolUse:Bash (x1) | Staging guard -- blocks Bash writes to .staging/ directory |
```

---

## 알려진 한계 및 수용된 리스크 (Known Limitations)

이 섹션은 구현 과정에서 V1/V2 adversarial review (2라운드)를 통해 식별된 보안 갭과 ReDoS 취약점 수정 사항을 문서화한다.

### 요약 테이블

| # | 우회 패턴 | 심각도 | 상태 | 근거 |
|---|-----------|--------|------|------|
| 1 | Shell 변수 간접 참조 (`DIR=...; cat > $DIR/x.json`) | LOW-MEDIUM | **수용** | C1이 "모든 shell 쓰기 메커니즘" 금지. 다만 C1 준수율이 100%가 아니므로 C2와 동일한 한계를 공유 |
| 2 | `>\|` clobber 연산자 (`echo '{}' >\| .staging/x.json`) | LOW | **수용** | 극히 드문 연산자로, subagent가 자발적으로 생성하지 않음 |
| 3 | Python 인라인 파일 I/O (`python3 -c "open(...,'w').write(...)"`) | LOW | **수용** | shell 리다이렉션이 아니므로 Guardian false positive를 유발하지 않음 (원래 문제의 범위 밖) |
| 4 | 이중 슬래시 경로 (`> .claude/memory//.staging/x.json`) | LOW | **수용** | regex가 raw string에서 리터럴 `.claude/memory/.staging/`를 매칭하므로, `//`는 불일치. subagent가 비표준 경로를 생성하지 않음 |
| 5 | rsync/curl/wget 등 미포함 명령 | LOW | **수용** | 가드가 포함하는 명령 집합(cat/echo/printf/tee/cp/mv/install/dd) 외의 쓰기 도구. subagent가 이런 도구로 .staging/에 쓰지 않음 |
| 6 | 경로 순회 (`> .claude/memory/../memory/.staging/x.json`) | LOW | **수용** | `../` 포함 경로는 regex 리터럴 매칭을 회피. subagent가 순회 경로를 생성하지 않음 |
| 7 | ReDoS 취약점 (`\s+`와 `[^|&;\n]*` 겹침) | MODERATE | **수정** | 정규식 수정으로 O(N^2) backtracking 제거. 32K 입력 기준 385배 성능 개선 실측 |

### 방어 심층(Defense-in-Depth) 구조 및 우회 수용 근거

이 구현은 단일 방어선이 아닌 두 계층의 방어를 채택한다:

- **C1 (소프트 계층):** `SKILL.md` 금지 조항 -- subagent 오케스트레이션 템플릿 수준에서 `.staging/`에 대한 Bash heredoc/리다이렉션 사용을 명시적으로 금지한다. "모든 shell 쓰기 메커니즘"을 포괄하는 추상 규칙 + 구체적 안티패턴 예시를 제공.
- **C2 (하드 계층):** `memory_staging_guard.py` PreToolUse:Bash 훅 -- 리다이렉션 구문을 포함하는 Bash 명령이 `.claude/memory/.staging/`를 대상으로 할 때 차단한다.

우회 수용의 핵심 전제는 **위협 모델의 범위**다. 이 가드의 목적은 Guardian permission popup을 유발하는 패턴 -- 즉, subagent가 SKILL.md 템플릿을 따르는 과정에서 실수로 생성하는 정직한(honest) 패턴 -- 을 차단하는 것이다. 악의적인 행위자가 의도적으로 우회 기법을 사용하는 시나리오는 이 위협 모델의 범위 밖이다.

**솔직한 한계 인정:** C2 가드를 만든 이유 자체가 "C1 SKILL.md 준수율이 100%가 아니기 때문"이다. 같은 논리로, C2의 regex 우회(항목 1-6)에 대한 방어도 결국 C1 준수에 의존한다. 즉 C1이 실패하면 C2도 우회될 수 있는 구조적 한계가 있다. 다만, 현실적으로 subagent가 생성하는 패턴은 직선적이며(변수 간접 참조, clobber 연산자 등은 사용하지 않음), 이 전제 하에서 C1+C2 조합은 충분하다.

각 수용 항목의 추가 근거:

- **Shell 변수 우회 (항목 1):** 변수 간접 참조(`$DIR`)를 사용하면 regex가 리터럴 경로를 찾지 못함. C1이 "모든 shell 쓰기 메커니즘"을 금지하므로 1차 방지되나, 소형 모델(haiku)이 추상 규칙보다 구체적 예시에 더 강하게 반응하는 경향이 있어 완전한 방지를 보장하지 못함.
- **`>\|` 연산자 우회 (항목 2):** `noclobber` 관련 연산자로 일반적인 스크립트에서도 거의 사용되지 않는다. LLM subagent가 이 연산자를 생성할 실질적인 확률은 무시 가능하다.
- **Python 인라인 우회 (항목 3):** 이 패턴은 shell 리다이렉션 구문을 사용하지 않으므로 Guardian이 Bash 훅으로 스캔하는 대상이 아니다. 즉, 이 패턴은 C2 가드를 우회하더라도 원래 문제(Guardian false positive popup)를 유발하지 않는다. 따라서 C2 가드의 적용 범위 밖에 있는 것이 의도된 설계다.
- **이중 슬래시 우회 (항목 4):** regex는 raw command string에서 리터럴 `.claude/memory/.staging/`를 매칭한다. `//`가 포함된 경로는 이 리터럴과 일치하지 않으므로 가드를 통과한다 (파일시스템 정규화는 regex 이후 단계에서 발생하므로 무관). 어떤 subagent도 이 비표준 경로 형식을 생성하지 않는다.
- **미포함 명령 우회 (항목 5):** `rsync`, `curl -o`, `wget -O` 등은 `.staging/`에 파일을 쓸 수 있으나 regex 명령 집합에 포함되지 않음. subagent가 이런 도구를 사용할 시나리오가 없으므로 수용.
- **경로 순회 우회 (항목 6):** `../` 등으로 regex 리터럴을 우회 가능하나, SKILL.md 템플릿이 정규 경로만 제공하므로 subagent가 순회 경로를 생성하지 않음.

### ReDoS 취약점 수정

#### 문제

원본 정규식 패턴의 첫 번째 arm(이하 p1)에서 catastrophic backtracking이 발견되었다:

```
# 수정 전 (취약)
_STAGING_WRITE_PATTERN arm 1:
r'(?:cat|echo|printf)\s+[^|&;\n]*>\s*[^\s]*\.claude/memory/\.staging/'
```

**근본 원인:** `\s+`(명령명 뒤 공백)와 `[^|&;\n]*`(인자 부분)가 **둘 다 공백 문자를 소비할 수 있다.** 입력 `echo` + N개 공백 + `> /tmp/non-staging`에서, regex 엔진이 N개 공백을 `\s+`와 `[^|&;\n]*` 사이에 어떻게 분배할지 모든 조합을 시도하여 O(N^2) 백트래킹이 발생한다.

**실측 영향:** 32K 공백 문자 입력 시 약 1.4초 소요. hook timeout(5초)에 근접하면 fail-open으로 가드가 우회될 수 있다.

#### 수정

`[^|&;\n]*`의 문자 클래스에서 `\s`(공백)와 `>`를 모두 제외하여, `\s+`와의 겹침을 완전히 제거:

```
# 수정 후 (안전)
_STAGING_WRITE_PATTERN arm 1:
r'(?:cat|echo|printf)\s+[^|&;\n>\s]*>\s*[^\s]*\.claude/memory/\.staging/'
```

이 수정으로 `\s+`가 모든 공백을 독점적으로 소비하고, `[^|&;\n>\s]*`는 비공백 인자만 매칭한다. 두 quantifier 간 소비 대상이 겹치지 않으므로 백트래킹이 발생하지 않는다.

**실측 개선:** 32K 공백 입력 기준 1413ms → 3.67ms (**385배 개선**).

| N (공백 수) | 수정 전 (ms) | 수정 후 (ms) | 개선 배율 |
|------------|-------------|-------------|----------|
| 1,000 | 1.6 | 0.1 | 16.8x |
| 4,000 | 23.7 | 0.4 | 61.5x |
| 8,000 | 95.8 | 0.8 | 124.5x |
| 16,000 | 361.5 | 1.3 | 276.8x |
| 32,000 | 1,413.4 | 3.7 | 384.8x |

#### 수정의 의미론적 안전성

`\s`와 `>`를 첫 번째 문자 클래스에서 제외하는 것은 의미론적으로 안전하다. 이 정규식이 매칭하려는 패턴 구조는:

```
<명령어> <공백> <인자들> > <대상경로>
       \s+     [^...]*  > \.claude/...
```

- **`\s` 제외:** 명령어와 리다이렉션 사이의 공백은 `\s+`가 담당한다. 인자에 공백이 포함되면 shell은 이를 별도 인자로 파싱하므로, `[^|&;\n>\s]*`로 비공백 인자만 매칭하는 것이 shell 의미론과 일치한다.
- **`>` 제외:** unquoted `>`는 shell이 리다이렉션으로 해석한다. 따라서 `[^|&;\n>\s]*`가 첫 번째 `>`에서 정지하고, 뒤따르는 `>\s*`가 리다이렉션 연산자를 매칭한다.

**보완 관계:** p1이 `echo 'a > b' > .staging/x.json` 같은 따옴표 내 `>`를 포함한 명령에서 첫 번째 `>`에서 잘못 정지할 수 있으나, 이 경우 p4(bare redirect arm: `[&]?>{1,2}\s*[^\s]*\.claude/memory/\.staging/`)가 실제 리다이렉션을 매칭하여 차단한다. 즉 p1과 p4가 상호 보완 관계로 동작한다.

### Hook Timeout 동작

PreToolUse 훅의 timeout은 5초다. 훅이 timeout되면 Claude Code는 **fail-open** (허용)으로 동작한다. ReDoS 수정 전에는 ~45K 공백 입력으로 timeout을 유발하여 가드를 우회할 수 있었으나, 수정 후에는 32K 입력에서도 3.7ms로 완료되므로 이 경로의 실질적 위험은 제거되었다.
