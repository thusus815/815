---
title: 자료 제출 인큐베이션 가이드
tags: [인덱스, 가이드]
---

# `_inbox/` — 신규 자료 인큐베이션

이 폴더는 **검증 전 자료**의 임시 보관소입니다. 누구나 자료를 제출할 수 있고, 자동·수동 검증을 거쳐 메인 폴더로 이동됩니다.

---

## 작동 흐름

```
1. 제출자가 _inbox/대기/ 에 .md 파일 추가
        ↓
2. GitHub Actions가 자동 검증
   ✓ 필수 필드 (source_url, source_type 등)
   ✓ 출처 URL 도메인 화이트리스트
   ✓ 기존 노트와 중복 검사
   ✓ 형식·인코딩 검사
        ↓
3a. 검증 통과 → _inbox/승인됨/ 으로 이동 + 라벨
3b. 검증 실패 → _inbox/거부됨/ 으로 이동 + 사유 기록
        ↓
4. 관리자(운영자) 수동 검토:
   - 승인됨 → 적절한 메인 폴더(01-인물 등)로 이동
   - 거부됨 → 보완 요청 또는 폐기
        ↓
5. 메인 폴더 이동 시 graph_data.json 자동 재빌드 → 사이트 갱신
```

---

## 폴더 구조

| 폴더 | 용도 |
|---|---|
| `_inbox/대기/` | 신규 제출이 처음 도착하는 곳 |
| `_inbox/승인됨/` | 자동 검증 통과, 관리자 검토 대기 |
| `_inbox/거부됨/` | 자동 검증 실패, 보완 또는 폐기 |

---

## 제출 규칙

### 필수 frontmatter 필드

```yaml
---
title: 인물·사건명
tags: [인물, 항일]            # 또는 [인물, 친일], [사건], [지역] 등
source_type: 판결문            # 신문기사 | 판결문 | 보고서 | 회고록 | 사진 | 기타
source_name: 경성지방법원판결문   # 자료의 정식 명칭
source_institution: 국가기록원   # 보유 기관
source_url: https://...        # 직접 접근 가능한 URL (필수!)
source_date: 1919-03-15        # 자료 작성일
source_doc_id: ABC-123         # 기관 문서 ID (있으면)
source_reliability: ●●○        # ●●● ●●○ ●○○ ○○○ 중 하나
submitted_by: 홍길동           # 제출자 이름 또는 ID
submitted_at: 2026-04-15
---
```

### 필드 설명

| 필드 | 의미 | 필수 |
|---|---|---|
| `source_type` | 자료 종류 | ✅ |
| `source_url` | 검증 가능한 직접 URL | ✅ |
| `source_reliability` | 신뢰도 등급 | ✅ |
| `submitted_by` | 제출자 식별 | ✅ |
| `source_doc_id` | 문서 고유번호 | ⬜ |

### 신뢰도 등급

| 표시 | 의미 |
|---|---|
| `●●●` | 직접 접근 가능 (URL 클릭 → 원본 즉시 확인) |
| `●●○` | 명확한 출처 (URL은 있지만 인증 필요 등) |
| `●○○` | 2차 인용 (어떤 문헌에서 재인용) |
| `○○○` | 미검증 (가족 구술, 미공개 자료 등) |

---

## 출처 URL 화이트리스트

자동 검증 시 다음 도메인의 URL은 즉시 신뢰 처리됩니다.

```
공식 기관:
  e-gonghun.mpva.go.kr     (공훈전자사료관)
  theme.archives.go.kr     (국가기록원)
  www.archives.go.kr       (국가기록원)
  db.history.go.kr         (국사편찬위원회)
  people.aks.ac.kr         (한국학중앙연구원 인물DB)
  encykorea.aks.ac.kr      (한국민족문화대백과)
  www.law.go.kr            (국가법령정보)

언론·사료:
  newslibrary.naver.com    (네이버 뉴스 라이브러리)
  www.kjha.co.kr           (공주학아카이브)

기타 도메인은 수동 검토 대상이 됩니다.
```

---

## 제출 방법

### 방법 A: GitHub Web 인터페이스 (추천)

1. https://github.com/thusus815/815/tree/main/_inbox/%EB%8C%80%EA%B8%B0 접속
2. **Add file** → **Create new file**
3. 파일명: `홍길동_자료설명_2026.md` 형식
4. 위 frontmatter 복사 + 본문 작성
5. **Commit changes** → 자동 검증 시작

### 방법 B: Obsidian Web Clipper

1. Web Clipper 설치 후 `_inbox 제출용` 템플릿 사용 (별도 안내 예정)
2. 출처 URL이 있는 페이지에서 클립
3. `_inbox/대기/`로 자동 저장

### 방법 C: PR (Pull Request)

여러 파일 일괄 제출 시 추천. fork → branch → PR.

---

## 자주 거부되는 사유

| 사유 | 해결 |
|---|---|
| `source_url` 없음 | 반드시 검증 가능한 URL 첨부 |
| 도메인 미신뢰 | 신뢰 도메인 사용 또는 `source_reliability: ○○○` 명시 |
| 중복 노트 존재 | 기존 노트를 보완하는 형태로 변경 |
| 한자 미확인 | `한자필드 확인요청` 메모 남기기 |
| 제출자 미기재 | `submitted_by` 필드 추가 |

---

## 운영자 메모

- 관리자(thusus815)만 메인 폴더로 이동 권한
- `_inbox` 안의 모든 노트는 그래프에 **포함되지 않음** (`build_graph.py` EXCLUDE)
- 통계: `_inbox/대기/` 5개 이상 시 알림 (예정)
