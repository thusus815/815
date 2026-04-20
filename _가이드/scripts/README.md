---
제목: 볼트 운영 스크립트
type: 가이드
layer: meta
tags: [가이드, scripts, lint, 자동화]
---

# 볼트 운영 스크립트

> 이 폴더는 **L3 메타 영역**이다. Obsidian 그래프에서 자동 제외된다.
> 위키 노트는 절대 여기 두지 마라.

## 폴더 구조

```
_가이드/scripts/
├─ README.md                       # 이 문서
├─ requirements.txt                # Python 의존성
├─ summarize_persons.py            # 인물 노트에 요약 블록 자동 추가 (Gemini)
├─ lint_vault.py                   # 죽은 링크/고립/중복 등 헬스 체크
└─ prompts/
   └─ summarize_person.md          # 요약 생성 프롬프트 템플릿
```

## 0. 사전 준비

### Python 환경
이 컴퓨터의 `(.venv)` (예: `c:/Users/ho/My Maker Space/.../venv`) 또는
새 가상환경에서 실행한다.

```powershell
pip install -r "C:\Users\ho\Desktop\친일반민족행위진상규명_보고서\_가이드\scripts\requirements.txt"
```

### Gemini API 키 (요약 스크립트만 필요)
PowerShell:
```powershell
$env:GEMINI_API_KEY = "AI..."
```

영구 저장하려면:
```powershell
[System.Environment]::SetEnvironmentVariable('GEMINI_API_KEY','AI...','User')
```

## 1. `lint_vault.py` — 볼트 헬스 체크

API 호출 없음. 즉시 실행 가능.

```powershell
cd "C:\Users\ho\Desktop\친일반민족행위진상규명_보고서\_가이드\scripts"
python lint_vault.py
```

결과:
- `_가이드/lint_<YYYY-MM-DD>.md` 자동 생성
- 콘솔에 요약 통계 출력

리포트 항목:
1. **죽은 링크 Top 100** — 어떤 후보 노트를 만들면 가장 효과가 큰지
2. **동명 노트** — 같은 이름이 여러 폴더에 있으면 중복 가능성
3. **요약 섹션 없는 노트** — LLM 위키 임계점 ① 미달
4. **`source` frontmatter 없는 노트** — 출처 추적 불가
5. **고립 노트** — 인입 링크 0개 (의도적 허브가 아니면 정리 대상)
6. **노트별 죽은 링크 상세 Top 50**

## 2. `summarize_persons.py` — 인물 요약 자동 생성

각 인물 노트의 frontmatter 직후에 다음 블록을 삽입한다.

```markdown
<!-- LLM-WIKI:SUMMARY:START -->

## 한 줄 요약
...

## 핵심 행적
1. **YYYY 사건명**: ...
2. ...
3. ...

## 같은 흐름의 인물
- [[인물1]] — 관계 설명
- ...

<!-- LLM-WIKI:SUMMARY:END -->
```

**원본 본문은 절대 변경되지 않는다.** 마커 블록만 추가한다.

### 단계별 사용

```powershell
cd "C:\Users\ho\Desktop\친일반민족행위진상규명_보고서\_가이드\scripts"

# 0) 어떤 노트가 처리될지 미리 보기 (API 호출 없음)
python summarize_persons.py --dry-run

# 1) 항일인물 5개로 시험
python summarize_persons.py --execute --side 항일 --limit 5

# 2) 결과를 Obsidian에서 확인 후, 친일인물 10개 시험
python summarize_persons.py --execute --side 친일 --limit 10

# 3) 만족하면 전체 일괄 (1442개, 약 50~80분 소요, 무료 한도 주의)
python summarize_persons.py --execute --rate 2.0
```

### 옵션
| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--dry-run` | - | 처리 대상만 출력, API 호출 없음 |
| `--execute` | - | 실제 API 호출하여 노트 갱신 |
| `--limit N` | 없음 | 최대 N개만 처리 |
| `--side` | `all` | `친일` / `항일` / `all` 중 선택 |
| `--model` | `gemini-2.5-flash` | 다른 Gemini 모델 사용 가능 |
| `--rate` | `2.0` | 호출 간격(초). 무료 한도 회피용 |

### 재실행 안전성
- 이미 `<!-- LLM-WIKI:SUMMARY:START -->` 마커가 있는 노트는 **자동 스킵**.
- 중간에 끊겨도 다시 돌리면 남은 것부터 진행.

### 결과를 되돌리고 싶을 때

요약 블록만 일괄 제거하려면 PowerShell:
```powershell
Get-ChildItem 'C:\Users\ho\Desktop\친일반민족행위진상규명_보고서\01-인물' -Recurse -Filter '*.md' | ForEach-Object {
    $c = Get-Content $_.FullName -Raw -Encoding UTF8
    $new = [regex]::Replace($c, '\n?<!-- LLM-WIKI:SUMMARY:START -->.*?<!-- LLM-WIKI:SUMMARY:END -->\n?', '', 'Singleline')
    if ($new -ne $c) { Set-Content -Path $_.FullName -Value $new -Encoding UTF8 -NoNewline }
}
```

## 3. 권장 작업 순서

1. **`lint_vault.py` 실행** → 현재 상태 파악
2. 보고서의 *죽은 링크 Top 100*에서 의미 있는 후보를 새 노트로 생성
3. **`summarize_persons.py --dry-run`** → 처리 대상 확인
4. **`summarize_persons.py --execute --limit 5`** → 결과 품질 확인
5. 프롬프트가 마음에 들면 전체 실행, 아니면 `prompts/summarize_person.md` 수정 후 다시
6. 작업 완료 후 다시 `lint_vault.py` 실행 → 변화 확인

## 주의

- `00-원자료/` 와 `99-attachments/` 는 절대 수정하지 마라 (`AGENTS.md` § 7).
- API 비용/한도는 본인이 관리한다. Gemini 무료 한도는 2026 기준 모델별 분당 RPM 제한이 있다.
- 스크립트가 만든 요약 내용은 LLM 출력이므로 **사실 검증 후 사용**할 것. 학술 인용에 그대로 쓰지 마라.
