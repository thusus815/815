# 815 Chat Worker

Cloudflare Workers AI + GraphRAG 챗봇.

## 구조

```
worker/
├─ src/
│  └─ index.ts        ← 메인 워커 (그래프 검색 + Workers AI)
├─ wrangler.toml      ← 설정 (AI 바인딩 활성화)
├─ package.json
└─ README.md          ← 이 파일
```

## 작동 흐름

```
사용자 질문
    ↓
키워드 매칭으로 graph_data.json에서 노드 검색 (top 8)
    ↓
인접 노드 20개 + 관련 의미관계 30개 추출
    ↓
컨텍스트를 시스템 프롬프트에 주입
    ↓
@cf/meta/llama-3.1-8b-instruct 호출
    ↓
{ answer, sources } 반환
```

## 배포

### 0. 사전 준비
- Cloudflare 계정 (무료)
- `npm install -g wrangler` 또는 `npx wrangler`

### 1. 인증
```bash
cd worker
npx wrangler login
```

### 2. 의존성 설치
```bash
npm install
```

### 3. 로컬 테스트
```bash
npm run dev
# → http://localhost:8787 에서 테스트
curl -X POST http://localhost:8787/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"안중근은 누구를 사살했나?"}'
```

### 4. 배포
```bash
npm run deploy
# → https://815-chat.<your-subdomain>.workers.dev 로 배포됨
```

## 엔드포인트

### `GET /`
헬스체크.

### `POST /chat`
일반 Q&A 모드.
```json
요청: { "question": "이완용은 무엇을 했나?" }
응답: {
  "answer": "...",
  "sources": [{ "id": "...", "label": "...", "path": "..." }]
}
```

### `POST /persona`
페르소나 모드 (1인칭 대답).
```json
요청: { "question": "...", "persona": "이완용" }
응답: { "answer": "...", "persona": "이완용", "sources": [...] }
```

## 비용

- **Workers AI**: 매일 10,000 뉴런(neuron) 무료 (≈ llama-3 수백 회 호출)
- **Workers**: 매일 100,000 요청 무료
- 초과 시: $0.011 / 1,000 뉴런

## 보안

- CORS: 모든 도메인 허용 (`*`). 운영 시 `SITE_ORIGIN`만 허용으로 변경 권장.
- Rate Limit: 미설정. 운영 시 Cloudflare 무료 Rate Limiting 추가 권장.

## 다음 단계 (Step 4)

- 페르소나 별 system prompt를 KV 또는 D1에 저장
- 5단계 방어선 (사실확인 → 시대정합성 → 출처표기 → 면책고지 → 응답거부) 구현
- 사이트(`graph.html`)에 채팅 UI 추가
