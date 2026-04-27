# 친일반민족행위진상규명 보고서 — 프로젝트 개요

> 모든 Claude 세션이 이 파일을 자동으로 읽습니다. bkit 작동을 위한 핵심 컨텍스트와 작업 규칙을 여기 둡니다.

---

## bkit Level: Dynamic

> **Reason:** Cloudflare Worker(backend) + KV + R2 + GitHub Actions CI + 인증 흐름 보유. BaaS형 풀스택.

- `bkit-rules` 자동 적용 (PDCA 워크플로, 자동 에이전트 트리거, 코드 품질 가드)
- 추천 출력 스타일: `bkit-pdca-guide`
- 사용 가능한 Agent Teams: `developer`, `qa` (2-teammate)

레벨 변경이 필요하면 이 줄을 수정하세요.

---

## 프로젝트 정체

대통령소속 친일반민족행위진상규명위원회 보고서를 1차 사료로 한 한국 근대사 인물·사건·기관 위키. Andrej Karpathy의 LLM Wiki 패턴 (벡터 DB·청킹 없음, LLM이 직접 위키 링크를 따라 탐색).

**3계층 구조:** L1 원자료(읽기 전용) / L2 위키(자유 편집) / L3 메타(가이드·인덱스)

상세 운영 규칙은 [`AGENTS.md`](AGENTS.md) — 노트 작성 규약, 링크 규칙, 폴더별 의미, 절대 금지 사항.

---

## 주요 컴포넌트

| 파일/디렉토리 | 역할 |
|---|---|
| `submit.html` | 공개 자료 제출 폼 (누구나) |
| `review.html` | 검토자 화면 (김남균 선생 등) — 라벨·코멘트만 |
| `admin.html` | 관리자 화면 (운영자) — 승인·반려·커밋 |
| `chat.html` | 페르소나 챗봇 (박순길 등) |
| `worker/` | Cloudflare Worker (인증, GitHub API 프록시, KV 상태) |
| `_가이드/` | 운영 가이드 (검토자 운영, 마스터 인덱스, 스크립트) |
| `_inbox/` | 검증 전 자료 대기 |

권한·역할 매트릭스: [`_가이드/검토자_운영_가이드.md`](_가이드/검토자_운영_가이드.md)

---

## 핵심 워크플로

### 자료 제출 → 등재
```
공개 사용자 → submit.html → GitHub Issue (라벨: 자료제출)
              ↓
검토자 → review.html → 4종 플래그 (검토완료/수정필요/분류재검토/반려추천)
              ↓
운영자 → admin.html → 승인 시 GitHub Contents API로 .md 커밋 → GitHub Pages 배포
```

### 위키 노트 추가 (LLM이 직접)
1. `00-원자료/DB/*.db`에서 인물 구간 읽음
2. `AGENTS.md` 4-3 표준 섹션에 맞춰 `01-인물/<이름>.md` 생성
3. 양방향 링크·관련인물 frontmatter 채움

### 배포
- **wiki**: `git push origin main` → GitHub Pages 자동 빌드
- **worker**: `cd worker && npx wrangler deploy`

---

## 주요 명령어

```powershell
# 위키 점검
python _가이드/scripts/lint_vault.py

# 워커 비밀 관리
cd worker && npx wrangler secret put REVIEWER_SECRET
cd worker && npx wrangler kv key list --binding REVIEW_STATE --remote

# 워커 배포
cd worker && npx wrangler deploy
```

---

## 절대 금지 (bkit 가드와 별개)

- ❌ `00-원자료/` 안의 어떤 파일도 수정/이동/삭제하지 않는다.
- ❌ 사람 이름·한자·생몰년 등 frontmatter를 추측으로 채우지 않는다.
- ❌ 정치적 평가나 현대적 해석을 본문에 임의로 추가하지 않는다.
- ❌ `git push --force`로 main을 덮어쓰지 않는다.
- ❌ 비밀번호·토큰을 README나 가이드 문서에 평문으로 적지 않는다.

---

## bkit 즉시 사용 가능한 명령

| 작업 | 명령 |
|---|---|
| 코드 품질 검토 | `bkit:code-review` 스킬 |
| QA 실행 | `bkit:qa-phase` |
| 배포 | `bkit:deploy` |
| 보안 검토 | `bkit:phase-7-seo-security` |
| PDCA 사이클 | `bkit:pdca` |
| 진행 단계 안내 | `bkit:development-pipeline` |

상시 활성: 모든 `bkit:*` 스킬은 글로벌 플러그인으로 등록되어 있어 별도 설치 없이 호출 가능합니다.
