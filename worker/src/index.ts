/**
 * 815 Archive Chat Worker
 *
 * Cloudflare Workers AI 기반 GraphRAG 챗봇.
 *
 * 흐름:
 *   1. 사용자 질문 수신
 *   2. graph_data.json + graph_relations.json 에서 관련 노드/관계 추출
 *      (벡터화 없이 키워드 + 그래프 인접 노드)
 *   3. 추출한 컨텍스트를 시스템 프롬프트에 주입
 *   4. Workers AI (llama-3.1-8b-instruct) 로 응답 생성
 *
 * 엔드포인트:
 *   GET  /            → 헬스체크
 *   POST /chat        → { question, persona? } → { answer, sources }
 *   POST /persona     → { persona_id, question } → 페르소나 모드
 *   GET  /personas    → 사용 가능한 페르소나 목록
 */

import { getPersona, PERSONAS } from "./personas";
import { buildMdFromIssue } from "./converter";

interface Env {
  AI: Ai;
  SITE_ORIGIN: string;
  GRAPH_DATA_URL: string;
  RELATIONS_URL: string;
  GITHUB_TOKEN?: string;
  SUBMIT_AUTH: KVNamespace;
  REVIEW_STATE: KVNamespace;
  ATTACHMENTS: R2Bucket;
  ADMIN_SECRET?: string;
  REVIEWER_SECRET?: string;  // 콤마로 다중 비밀번호 (검토자별)
  GEMINI_API_KEY?: string;
}

interface SubmitPayload {
  title: string;
  type: string;
  date?: string;
  region: string;
  persons?: string;
  source?: string;
  note?: string;
  submitter?: string;
  contact?: string;
  files?: string[];
  password?: string; // 추후 문의용 비밀번호
}

interface CommentPayload {
  issue_number: number;
  password: string;
  message: string;
  submitter?: string;
}

// 간단한 해시 (SHA-256 via SubtleCrypto)
async function hashPassword(pw: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(pw));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

interface GraphNode {
  id: string;
  label: string;
  category?: string;
  tags?: string[];
  path?: string;
}

interface GraphEdge {
  source: string;
  target: string;
  weight?: number;
  relType?: string;
  direction?: string;
}

interface Relation {
  subject: string;
  predicate: string;
  object: string;
  confidence: number;
  source_note: string;
}

let cachedGraph: { nodes: GraphNode[]; edges: GraphEdge[] } | null = null;
let cachedRelations: Relation[] | null = null;
let cacheStamp = 0;
const CACHE_TTL_MS = 5 * 60 * 1000;

async function loadGraph(env: Env) {
  const now = Date.now();
  if (cachedGraph && now - cacheStamp < CACHE_TTL_MS) return { graph: cachedGraph, relations: cachedRelations || [] };
  const [g, r] = await Promise.all([
    fetch(env.GRAPH_DATA_URL).then(x => x.ok ? x.json() : null),
    fetch(env.RELATIONS_URL).then(x => x.ok ? x.json() : null).catch(() => null),
  ]);
  cachedGraph = g as any;
  cachedRelations = (r as any)?.relations || [];
  cacheStamp = now;
  return { graph: cachedGraph!, relations: cachedRelations! };
}

// 한국어 별칭 → 검색 보강 토큰 매핑
const KO_ALIASES: Record<string, string[]> = {
  "청주농고":    ["청주농업고", "청주공립농업"],
  "청주농업고":  ["청주농고", "청주공립농업"],
  "청남":        ["청남학교", "청주청남"],
  "영명":        ["영명학교", "공주영명"],
  "내수":        ["내수초", "내수공립"],
  "3·1":         ["3·1운동", "만세운동", "1919"],
  "신사참배":    ["신사참배거부", "신사참배_거부"],
  "맹휴":        ["동맹휴학", "맹휴투쟁"],
  "광주학생운동":["광주학생", "광주_학생"],
  "의열단":      ["의열단_1920", "김원봉"],
  "박순길":      ["청주농업고", "1930", "맹휴"],
};

function expandTokens(tokens: string[]): string[] {
  const expanded = new Set(tokens);
  for (const t of tokens) {
    const aliases = KO_ALIASES[t];
    if (aliases) aliases.forEach(a => expanded.add(a));
    // 부분 매칭: 사전 키가 토큰을 포함하거나 토큰이 키를 포함할 때
    for (const [key, vals] of Object.entries(KO_ALIASES)) {
      if (t.includes(key) || key.includes(t)) vals.forEach(a => expanded.add(a));
    }
  }
  return Array.from(expanded);
}

function findRelevantNodes(question: string, graph: { nodes: GraphNode[]; edges: GraphEdge[] }, topK = 8) {
  const q = question.toLowerCase();
  const rawTokens = q.split(/[\s,.\?!:;()\+·]+/).filter(t => t.length >= 2);
  const tokens = expandTokens(rawTokens);

  const scored = graph.nodes.map(n => {
    let score = 0;
    const label = n.label.toLowerCase();
    for (const t of tokens) {
      if (label.includes(t)) score += (rawTokens.includes(t) ? 4 : 2); // 원본 토큰이면 가중치 높게
    }
    if (label === q) score += 10;
    // 연도 직접 매칭
    const yearMatch = q.match(/\d{4}/g);
    if (yearMatch) for (const yr of yearMatch) if (label.includes(yr)) score += 3;
    return { node: n, score };
  }).filter(x => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, topK);
  return scored.map(x => x.node);
}

function buildContext(
  seedNodes: GraphNode[],
  graph: { nodes: GraphNode[]; edges: GraphEdge[] },
  relations: Relation[],
) {
  const ids = new Set(seedNodes.map(n => n.id));
  const neighbors = new Map<string, GraphNode>();
  for (const e of graph.edges) {
    if (ids.has(e.source)) {
      const n = graph.nodes.find(x => x.id === e.target);
      if (n) neighbors.set(n.id, n);
    } else if (ids.has(e.target)) {
      const n = graph.nodes.find(x => x.id === e.source);
      if (n) neighbors.set(n.id, n);
    }
  }
  const triples = relations.filter(r =>
    ids.has(r.subject) || ids.has(r.object) ||
    seedNodes.some(n => r.subject === n.label || r.object === n.label)
  ).slice(0, 30);

  const lines: string[] = [];
  lines.push("## 핵심 노드");
  for (const n of seedNodes) lines.push(`- ${n.label} (${n.category || "?"})`);
  lines.push("");
  lines.push("## 관련 노드");
  for (const n of Array.from(neighbors.values()).slice(0, 20)) lines.push(`- ${n.label}`);
  lines.push("");
  if (triples.length) {
    lines.push("## 의미 관계 (LLM 추출)");
    for (const t of triples) {
      lines.push(`- ${t.subject} → ${t.predicate} → ${t.object} [${t.confidence.toFixed(2)}]`);
    }
  }
  return lines.join("\n");
}

const BASE_SYSTEM_PROMPT = `당신은 한국 근현대사(1900~1945) 친일·항일 인물·사건 아카이브의 챗봇입니다.

규칙:
1. 답변은 반드시 제공된 컨텍스트 노드/관계에 근거합니다.
2. 컨텍스트에 없는 정보는 "자료에 없음"이라고 명시합니다.
3. 인물·사건명은 정확히 표기합니다.
4. 친일/항일 분류가 컨텍스트에 명시된 경우 그대로 따릅니다.`;

// ─── 한글 띄어쓰기·문장 정리 (Workers AI) ─────────────────────────────
const SPACING_PROMPT = `당신은 1920~1930년대 한국 신문 OCR 텍스트를 현대 한국어 띄어쓰기 규범에 맞게 정리하는 도구입니다.

규칙:
1. 원문의 단어·표현·한자 병기는 절대 바꾸지 마세요. 띄어쓰기만 정상화하고, 어휘는 보존합니다.
2. 한자 병기 "(漢字)" 또는 "(漢字(한글))" 형식은 그대로 유지합니다.
3. 인명·지명·학교명은 한 단위로 붙여 씁니다 (예: "부여농업보습학교", "강성구").
4. 조사·어미는 앞 단어에 붙입니다 ("학교에", "갔다").
5. 결과 텍스트만 출력. 설명·머리말·코드블록 마커 없이.

원본:
\`\`\`
{INPUT}
\`\`\`

띄어쓰기 정리본:`;

async function normalizeKoreanSpacing(text: string, env: Env): Promise<string> {
  if (!text || text.length < 20) return text;
  // 너무 긴 텍스트는 잘라서 보냄 (Llama 컨텍스트 보호)
  const MAX = 6000;
  const chunk = text.length > MAX ? text.slice(0, MAX) : text;
  try {
    const response = await env.AI.run('@cf/meta/llama-3.3-70b-instruct-fp8-fast', {
      messages: [
        { role: 'system', content: '당신은 한국어 띄어쓰기 정리 도구입니다. 결과 텍스트만 출력합니다.' },
        { role: 'user', content: SPACING_PROMPT.replace('{INPUT}', chunk) },
      ],
      max_tokens: 4096,
    } as any);
    let out = ((response as any).response || '').trim();
    // 모델이 코드블록 마커를 붙였을 경우 제거
    out = out.replace(/^```[\w]*\n?/, '').replace(/\n?```\s*$/, '').trim();
    return out || text;
  } catch (e) {
    console.error('normalizeKoreanSpacing error:', e);
    return text;
  }
}

async function handleNormalizeSpacing(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  const { text } = await req.json() as { text?: string };
  if (!text) return Response.json({ error: 'text required' }, { status: 400 });
  const normalized = await normalizeKoreanSpacing(text, env);
  return Response.json({ ok: true, normalized });
}

async function handleChat(req: Request, env: Env) {
  const { question } = await req.json() as { question?: string };
  if (!question) return Response.json({ error: "question required" }, { status: 400 });

  const { graph, relations } = await loadGraph(env);
  const seeds = findRelevantNodes(question, graph);
  const ctx = buildContext(seeds, graph, relations);

  const messages = [
    { role: "system", content: BASE_SYSTEM_PROMPT },
    { role: "user", content: `질문: ${question}\n\n# 참고 컨텍스트\n${ctx}` },
  ];

  const response = await env.AI.run("@cf/meta/llama-3.3-70b-instruct-fp8-fast", { messages } as any);

  return Response.json({
    answer: (response as any).response,
    sources: seeds.map(n => ({ id: n.id, label: n.label, path: n.path })),
    persona: null,
  });
}

async function handlePersona(req: Request, env: Env) {
  const { persona_id, question } = await req.json() as {
    persona_id?: string;
    question?: string;
  };
  if (!question) return Response.json({ error: "question required" }, { status: 400 });
  if (!persona_id) return Response.json({ error: "persona_id required" }, { status: 400 });

  const persona = getPersona(persona_id);
  if (!persona) {
    return Response.json(
      { error: `알 수 없는 persona_id: ${persona_id}`, available: Object.keys(PERSONAS) },
      { status: 400 },
    );
  }

  const { graph, relations } = await loadGraph(env);

  // 페르소나의 지역·시대와 연관된 노드를 우선 검색
  const regionTokens = persona.region.split(/[·\s,]+/).filter(t => t.length >= 2);
  const enrichedQuestion = `${question} ${regionTokens.join(" ")}`;
  const seeds = findRelevantNodes(enrichedQuestion, graph, 10);
  const ctx = buildContext(seeds, graph, relations);

  const systemPrompt = `${persona.systemPrompt}

# 아카이브 컨텍스트 (관련 노드·관계)
${ctx}`;

  const messages = [
    { role: "system", content: systemPrompt },
    { role: "user", content: question },
  ];

  const response = await env.AI.run("@cf/meta/llama-3.3-70b-instruct-fp8-fast", { messages } as any);

  return Response.json({
    answer: (response as any).response,
    persona: {
      id: persona.id,
      displayName: persona.displayName,
      era: persona.era,
      region: persona.region,
    },
    sources: seeds.map(n => ({ id: n.id, label: n.label, path: n.path })),
  });
}

// 허용 MIME 타입
const ALLOWED_TYPES = new Set([
  'image/jpeg', 'image/png', 'image/gif', 'image/webp', 'image/tiff',
  'application/pdf',
]);
const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20MB

async function handleUpload(req: Request, env: Env) {
  const formData = await req.formData();
  const uploaded: { name: string; url: string; type: string }[] = [];

  for (const [, value] of formData.entries()) {
    if (!(value instanceof File)) continue;

    if (!ALLOWED_TYPES.has(value.type)) {
      return Response.json({ error: `허용되지 않는 파일 형식: ${value.type}` }, { status: 400 });
    }
    if (value.size > MAX_FILE_SIZE) {
      return Response.json({ error: `파일 크기 초과 (최대 20MB): ${value.name}` }, { status: 400 });
    }

    // 파일명 충돌 방지: timestamp + 원본 파일명
    const ts = Date.now();
    const safeName = value.name.replace(/[^a-zA-Z0-9가-힣._-]/g, '_');
    const key = `${ts}_${safeName}`;

    await env.ATTACHMENTS.put(key, await value.arrayBuffer(), {
      httpMetadata: { contentType: value.type },
    });

    const url = `https://pub-d4943151a8eb406e8517d30d72f465f4.r2.dev/${key}`;
    uploaded.push({ name: value.name, url, type: value.type });
  }

  return Response.json({ ok: true, files: uploaded });
}

async function handleSubmit(req: Request, env: Env) {
  const payload = await req.json() as SubmitPayload;

  if (!payload.title?.trim()) return Response.json({ error: "title required" }, { status: 400 });
  if (!payload.region?.trim()) return Response.json({ error: "region required" }, { status: 400 });

  const fileSection = payload.files?.length
    ? payload.files.map(f => `- ${f}`).join('\n')
    : '(첨부 파일 없음 — 이슈에서 직접 첨부 가능)';

  const body = [
    `## 자료 제목`,
    payload.title,
    ``,
    `## 자료 종류`,
    payload.type || '(미기재)',
    ``,
    `## 자료 연도`,
    payload.date || '미상',
    ``,
    `## 관련 지역`,
    payload.region,
    ``,
    `## 관련 인물·사건`,
    payload.persons || '(미기재)',
    ``,
    `## 자료 출처·소장처`,
    payload.source || '(미기재)',
    ``,
    `## 설명·메모`,
    payload.note || '(없음)',
    ``,
    `## 첨부 파일 목록`,
    fileSection,
    ``,
    `---`,
    `제출자: ${payload.submitter || '익명'}${payload.contact ? ` / ${payload.contact}` : ''}`,
    `제출 경로: 나의 3·1 자료 제출 폼`,
  ].join('\n');

  if (!env.GITHUB_TOKEN) {
    return Response.json({ error: "GITHUB_TOKEN not configured" }, { status: 503 });
  }

  const ghRes = await fetch('https://api.github.com/repos/thusus815/815/issues', {
    method: 'POST',
    headers: {
      'Authorization': `token ${env.GITHUB_TOKEN}`,
      'Content-Type': 'application/json',
      'User-Agent': 'my-31-archive-submit',
      'Accept': 'application/vnd.github+json',
    },
    body: JSON.stringify({
      title: `[자료 제출] ${payload.title}`,
      body,
      labels: ['자료제출'],
    }),
  });

  if (!ghRes.ok) {
    const err = await ghRes.text();
    return Response.json({ error: `GitHub API 오류: ${ghRes.status}`, detail: err }, { status: 502 });
  }

  const issue = await ghRes.json() as { html_url: string; number: number };

  // 비밀번호가 있으면 해시해서 KV에 저장 (30일 TTL)
  if (payload.password?.trim()) {
    const hash = await hashPassword(payload.password.trim());
    await env.SUBMIT_AUTH.put(`issue:${issue.number}`, hash, { expirationTtl: 60 * 60 * 24 * 30 });
  }

  return Response.json({ ok: true, issue_url: issue.html_url, issue_number: issue.number });
}

async function handleComment(req: Request, env: Env) {
  const payload = await req.json() as CommentPayload;

  if (!payload.issue_number) return Response.json({ error: "issue_number required" }, { status: 400 });
  if (!payload.password?.trim()) return Response.json({ error: "password required" }, { status: 400 });
  if (!payload.message?.trim()) return Response.json({ error: "message required" }, { status: 400 });

  // KV에서 해시 확인
  const storedHash = await env.SUBMIT_AUTH.get(`issue:${payload.issue_number}`);
  if (!storedHash) {
    return Response.json({ error: "이슈를 찾을 수 없거나 비밀번호 설정이 없습니다." }, { status: 404 });
  }

  const inputHash = await hashPassword(payload.password.trim());
  if (inputHash !== storedHash) {
    return Response.json({ error: "비밀번호가 일치하지 않습니다." }, { status: 403 });
  }

  if (!env.GITHUB_TOKEN) return Response.json({ error: "GITHUB_TOKEN not configured" }, { status: 503 });

  const body = [
    payload.message,
    ``,
    `---`,
    `제출자: ${payload.submitter || '익명'} (자료 제출 폼 추가 문의)`,
  ].join('\n');

  const ghRes = await fetch(`https://api.github.com/repos/thusus815/815/issues/${payload.issue_number}/comments`, {
    method: 'POST',
    headers: {
      'Authorization': `token ${env.GITHUB_TOKEN}`,
      'Content-Type': 'application/json',
      'User-Agent': 'my-31-archive-comment',
      'Accept': 'application/vnd.github+json',
    },
    body: JSON.stringify({ body }),
  });

  if (!ghRes.ok) {
    const err = await ghRes.text();
    return Response.json({ error: `GitHub API 오류: ${ghRes.status}`, detail: err }, { status: 502 });
  }

  const comment = await ghRes.json() as { html_url: string };
  return Response.json({ ok: true, comment_url: comment.html_url });
}

// ─── 관리자 인증 ────────────────────────────────────────────
function checkAdmin(req: Request, env: Env): boolean {
  const secret = req.headers.get('X-Admin-Secret');
  if (!secret || !env.ADMIN_SECRET) return false;
  // 쉼표로 구분된 여러 비밀번호 지원
  return env.ADMIN_SECRET.split(',').map(s => s.trim()).includes(secret);
}

// ────────────────────────────────────────────────────────────
// 변환 로직(parseSection·regionToFolder·buildMdFromIssue 등)은 converter.ts로 분리.
// 아래는 dead code (이전 인라인 정의). 삭제 마커 시작.
// ────────────────────────────────────────────────────────────

async function handleAdminIssues(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  if (!env.GITHUB_TOKEN) return Response.json({ error: 'GITHUB_TOKEN 미설정' }, { status: 503 });

  const url = new URL(req.url);
  const stateRaw = url.searchParams.get('state') || 'open';
  const state = ['open', 'closed', 'all'].includes(stateRaw) ? stateRaw : 'open';
  const pageRaw = url.searchParams.get('page') || '1';
  const pageNum = Number.parseInt(pageRaw, 10);
  const page = Number.isFinite(pageNum) && pageNum >= 1 && pageNum <= 50 ? pageNum : 1;

  const ghRes = await fetch(
    `https://api.github.com/repos/thusus815/815/issues?labels=%EC%9E%90%EB%A3%8C%EC%A0%9C%EC%B6%9C&state=${state}&per_page=100&page=${page}`,
    { headers: { Authorization: `token ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'User-Agent': 'my-31-admin' } }
  );
  const issues = await ghRes.json() as any[];
  if (!Array.isArray(issues)) return Response.json(issues);

  // 각 이슈에 KV의 review state 부착 (GitHub 라벨 동기화가 실패해도
  // 검토자 검토완료/수정필요 등 상태가 admin에 정상 노출되도록).
  const enriched = await Promise.all(issues.map(async (iss) => {
    const rs = await getReviewState(env, iss.number);
    return {
      ...iss,
      review_state: rs.status,
      review_suggested_md: !!rs.suggested_md,
      review_last_reviewer: rs.last_reviewer || null,
      review_updated_at: rs.updated_at || null,
    };
  }));
  return Response.json(enriched);
}

async function handleAdminApprove(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  if (!env.GITHUB_TOKEN) return Response.json({ error: 'GITHUB_TOKEN 미설정' }, { status: 503 });

  const { issue_number, folder_override, filename_override, md_override } =
    await req.json() as {
      issue_number: number;
      folder_override?: string;
      filename_override?: string;
      md_override?: string;
    };

  // 이슈 상세 조회
  const issueRes = await fetch(
    `https://api.github.com/repos/thusus815/815/issues/${issue_number}`,
    { headers: { Authorization: `token ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'User-Agent': 'my-31-admin' } }
  );
  const issue = await issueRes.json() as any;

  const { md: autoMd, folder: autoFolder, filename: autoFilename } = buildMdFromIssue(issue);
  const folder   = folder_override   || autoFolder;
  const filename = filename_override || autoFilename;
  const md       = md_override       || autoMd;

  const filePath = `${folder}/${filename}`;
  const content  = btoa(unescape(encodeURIComponent(md))); // base64 UTF-8

  // GitHub Contents API로 md 파일 생성
  const createRes = await fetch(
    `https://api.github.com/repos/thusus815/815/contents/${encodeURIComponent(filePath)}`,
    {
      method: 'PUT',
      headers: {
        Authorization: `token ${env.GITHUB_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'my-31-admin',
      },
      body: JSON.stringify({
        message: `feat: 자료 승인 #${issue_number} — ${filename}`,
        content,
      }),
    }
  );

  if (!createRes.ok) {
    const err = await createRes.text();
    return Response.json({ error: `파일 생성 실패: ${createRes.status}`, detail: err }, { status: 502 });
  }
  const created = await createRes.json() as any;

  // 이슈에 승인 댓글
  await fetch(
    `https://api.github.com/repos/thusus815/815/issues/${issue_number}/comments`,
    {
      method: 'POST',
      headers: { Authorization: `token ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json', 'User-Agent': 'my-31-admin' },
      body: JSON.stringify({ body: `✅ **자료가 승인되어 아카이브에 반영되었습니다.**\n\n- 경로: \`${filePath}\`\n- 커밋: ${created.commit?.html_url || ''}` }),
    }
  );

  // 이슈 닫기
  await fetch(
    `https://api.github.com/repos/thusus815/815/issues/${issue_number}`,
    {
      method: 'PATCH',
      headers: { Authorization: `token ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json', 'User-Agent': 'my-31-admin' },
      body: JSON.stringify({ state: 'closed', state_reason: 'completed' }),
    }
  );

  // 사후 회수를 위한 승인 기록 저장 (KV)
  await env.REVIEW_STATE.put(
    `approved:${issue_number}`,
    JSON.stringify({
      folder, filename, file_path: filePath,
      commit_url: created.commit?.html_url,
      approved_at: Date.now(),
    }),
  );

  return Response.json({ ok: true, file_path: filePath, commit_url: created.commit?.html_url });
}

// ─── 사후 수정/보충 (이미 승인된 .md를 새 내용으로 덮어쓰기) ──────
async function handleAdminUpdate(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  if (!env.GITHUB_TOKEN) return Response.json({ error: 'GITHUB_TOKEN 미설정' }, { status: 503 });

  const { issue_number, md, kind, comment } = await req.json() as {
    issue_number: number; md: string; kind?: string; comment?: string;
  };
  if (!issue_number || !md) return Response.json({ error: 'issue_number, md required' }, { status: 400 });

  const raw = await env.REVIEW_STATE.get(`approved:${issue_number}`);
  if (!raw) return Response.json({ error: '승인 기록 없음 (이미 회수되었거나 KV 만료).' }, { status: 404 });
  const { file_path } = JSON.parse(raw) as { file_path: string };

  const ghHeaders = {
    Authorization: `token ${env.GITHUB_TOKEN}`,
    Accept: 'application/vnd.github+json',
    'Content-Type': 'application/json',
    'User-Agent': 'my-31-admin',
  };

  // 1. 기존 파일 SHA 조회
  const getRes = await fetch(
    `https://api.github.com/repos/thusus815/815/contents/${encodeURIComponent(file_path)}`,
    { headers: ghHeaders },
  );
  if (!getRes.ok) return Response.json({ error: `파일 조회 실패: ${getRes.status}` }, { status: 502 });
  const fileData = await getRes.json() as { sha: string };

  // 2. 새 내용 PUT (덮어쓰기)
  const content = btoa(unescape(encodeURIComponent(md)));
  const action = kind === 'supplement' ? '보충' : '수정';
  const putRes = await fetch(
    `https://api.github.com/repos/thusus815/815/contents/${encodeURIComponent(file_path)}`,
    {
      method: 'PUT', headers: ghHeaders,
      body: JSON.stringify({
        message: `chore: 자료 ${action} #${issue_number}${comment ? ` - ${comment}` : ''}`,
        content, sha: fileData.sha,
      }),
    },
  );
  if (!putRes.ok) {
    const err = await putRes.text();
    return Response.json({ error: `파일 갱신 실패: ${putRes.status}`, detail: err.slice(0, 300) }, { status: 502 });
  }
  const putData = await putRes.json() as any;

  // 3. 이슈에 수정/보충 코멘트
  await fetch(
    `https://api.github.com/repos/thusus815/815/issues/${issue_number}/comments`,
    {
      method: 'POST', headers: ghHeaders,
      body: JSON.stringify({
        body: `✏️ **자료가 ${action}되었습니다.**\n\n- 경로: \`${file_path}\`\n${comment ? `- 메모: ${comment}\n` : ''}- 커밋: ${putData.commit?.html_url || ''}`,
      }),
    },
  );

  return Response.json({ ok: true, file_path, commit_url: putData.commit?.html_url, action });
}

// closed 이슈의 현재 .md 내용을 GitHub에서 가져와 반환 (수정 시 사용)
async function handleAdminGetCurrentMd(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  if (!env.GITHUB_TOKEN) return Response.json({ error: 'GITHUB_TOKEN 미설정' }, { status: 503 });

  const url = new URL(req.url);
  const issue_number = Number(url.searchParams.get('issue_number'));
  if (!issue_number) return Response.json({ error: 'issue_number required' }, { status: 400 });

  const raw = await env.REVIEW_STATE.get(`approved:${issue_number}`);
  if (!raw) return Response.json({ error: '승인 기록 없음' }, { status: 404 });
  const { file_path } = JSON.parse(raw) as { file_path: string };

  const getRes = await fetch(
    `https://api.github.com/repos/thusus815/815/contents/${encodeURIComponent(file_path)}`,
    { headers: { Authorization: `token ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'User-Agent': 'my-31-admin' } },
  );
  if (!getRes.ok) return Response.json({ error: `파일 조회 실패: ${getRes.status}` }, { status: 502 });
  const data = await getRes.json() as { content: string };
  // base64 → utf-8
  const md = decodeURIComponent(escape(atob(data.content.replace(/\n/g, ''))));
  return Response.json({ ok: true, md, file_path });
}

// admin이 특정 이슈의 검토자 review state 조회 (검토자 제안 포함)
async function handleAdminGetReviewState(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  const url = new URL(req.url);
  const issue_number = Number(url.searchParams.get('issue_number'));
  if (!issue_number) return Response.json({ error: 'issue_number required' }, { status: 400 });
  const st = await getReviewState(env, issue_number);
  return Response.json({ ok: true, review: st });
}

// ─── 사후 회수 (검토자 반려 의견 후 관리자가 결정) ──────────────────
async function handleAdminRecall(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  if (!env.GITHUB_TOKEN) return Response.json({ error: 'GITHUB_TOKEN 미설정' }, { status: 503 });

  const { issue_number, reason } = await req.json() as { issue_number: number; reason?: string };
  if (!issue_number) return Response.json({ error: 'issue_number required' }, { status: 400 });

  // 승인 기록 조회
  const raw = await env.REVIEW_STATE.get(`approved:${issue_number}`);
  if (!raw) return Response.json({ error: '이 이슈의 승인 기록을 찾을 수 없습니다 (이미 회수되었거나 KV 만료).' }, { status: 404 });
  const { file_path } = JSON.parse(raw) as { file_path: string };

  const ghHeaders = {
    Authorization: `token ${env.GITHUB_TOKEN}`,
    Accept: 'application/vnd.github+json',
    'Content-Type': 'application/json',
    'User-Agent': 'my-31-admin',
  };

  // 1. 현재 파일 SHA 조회 (DELETE 시 필요)
  const getRes = await fetch(
    `https://api.github.com/repos/thusus815/815/contents/${encodeURIComponent(file_path)}`,
    { headers: ghHeaders },
  );
  if (!getRes.ok) {
    return Response.json({ error: `파일 조회 실패: ${getRes.status} (이미 삭제되었을 수 있음)`, file_path }, { status: 502 });
  }
  const fileData = await getRes.json() as { sha: string };

  // 2. GitHub에서 .md 삭제
  const delRes = await fetch(
    `https://api.github.com/repos/thusus815/815/contents/${encodeURIComponent(file_path)}`,
    {
      method: 'DELETE',
      headers: ghHeaders,
      body: JSON.stringify({
        message: `chore: 자료 회수 #${issue_number} (사후 반려)${reason ? ` - ${reason}` : ''}`,
        sha: fileData.sha,
      }),
    },
  );
  if (!delRes.ok) {
    const err = await delRes.text();
    return Response.json({ error: `파일 삭제 실패: ${delRes.status}`, detail: err.slice(0, 300) }, { status: 502 });
  }

  // 3. 이슈 reopen
  await fetch(
    `https://api.github.com/repos/thusus815/815/issues/${issue_number}`,
    {
      method: 'PATCH', headers: ghHeaders,
      body: JSON.stringify({ state: 'open', state_reason: 'reopened' }),
    },
  );

  // 4. 회수 코멘트 추가
  await fetch(
    `https://api.github.com/repos/thusus815/815/issues/${issue_number}/comments`,
    {
      method: 'POST', headers: ghHeaders,
      body: JSON.stringify({
        body: `🔄 **자료가 사후 반려에 의해 회수되었습니다.**\n\n- 삭제된 파일: \`${file_path}\`\n${reason ? `- 사유: ${reason}\n` : ''}- 이슈가 다시 열렸습니다. 수정 후 재승인 가능합니다.`,
      }),
    },
  );

  // 5. KV 승인 기록 삭제
  await env.REVIEW_STATE.delete(`approved:${issue_number}`);

  return Response.json({ ok: true, file_path });
}

async function handleAdminReject(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  if (!env.GITHUB_TOKEN) return Response.json({ error: 'GITHUB_TOKEN 미설정' }, { status: 503 });

  const { issue_number, reason } = await req.json() as { issue_number: number; reason: string };

  await fetch(
    `https://api.github.com/repos/thusus815/815/issues/${issue_number}/comments`,
    {
      method: 'POST',
      headers: { Authorization: `token ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json', 'User-Agent': 'my-31-admin' },
      body: JSON.stringify({ body: `⚠️ **자료 검토 결과 반려 처리되었습니다.**\n\n**사유**: ${reason}\n\n추가 자료나 수정 후 재제출해 주세요.` }),
    }
  );

  await fetch(
    `https://api.github.com/repos/thusus815/815/issues/${issue_number}`,
    {
      method: 'PATCH',
      headers: { Authorization: `token ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'Content-Type': 'application/json', 'User-Agent': 'my-31-admin' },
      body: JSON.stringify({ state: 'closed', state_reason: 'not_planned' }),
    }
  );

  return Response.json({ ok: true });
}

const GEMINI_INSPECT_PROMPT = `당신은 한국 근현대사(1900~1945) 전문 사료 분석가입니다.
첨부된 이미지는 역사 자료(신문기사 스캔, 판결문, 공문서 등)입니다.

아래 두 가지를 수행하세요:

## [1] 텍스트 전문 추출
이미지에 있는 모든 텍스트를 원문 그대로 추출하세요. 한자·일본어·한국어 모두 포함합니다. 판독 불가 부분은 □로 표시합니다.

## [2] 사료 분석
1. **문서 종류**: (판결문 / 신문기사 / 공문서 / 사진 / 기타)
2. **날짜**: 문서에서 확인되는 날짜
3. **등장 인물**: 이름, 역할
4. **주요 사건·내용**: 핵심 사실 요약 3~5줄
5. **관련 지역**: 언급된 지역
6. **사료 신뢰도**: 높음 / 보통 / 낮음 + 이유
7. **아카이브 활용 가능성**: 항일·친일 아카이브에서 어떻게 활용될 수 있는지

반드시 한국어로 답하고, [1]과 [2]를 명확히 구분해주세요.`;

async function handleAdminOcr(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  if (!env.GEMINI_API_KEY) return Response.json({ error: 'GEMINI_API_KEY 미설정' }, { status: 503 });

  const { image_url, title } = await req.json() as { image_url: string; title?: string };
  if (!image_url) return Response.json({ error: 'image_url required' }, { status: 400 });

  // R2에서 이미지 가져와 base64 변환
  const imgRes = await fetch(image_url);
  if (!imgRes.ok) return Response.json({ error: `이미지 로드 실패: ${imgRes.status}` }, { status: 502 });

  const contentType = imgRes.headers.get('content-type') || 'image/jpeg';
  const buffer = await imgRes.arrayBuffer();
  const base64 = btoa(String.fromCharCode(...new Uint8Array(buffer)));

  // Gemini 2.5 Flash — 이미지 + 텍스트 프롬프트
  const geminiRes = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-04-17:generateContent?key=${env.GEMINI_API_KEY}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{
          parts: [
            { inlineData: { mimeType: contentType, data: base64 } },
            { text: title ? `자료명: ${title}\n\n${GEMINI_INSPECT_PROMPT}` : GEMINI_INSPECT_PROMPT },
          ],
        }],
        generationConfig: { temperature: 0.1, maxOutputTokens: 8192 },
      }),
    }
  );

  if (!geminiRes.ok) {
    const err = await geminiRes.text();
    return Response.json({ error: `Gemini API 오류: ${geminiRes.status}`, detail: err }, { status: 502 });
  }

  const geminiData = await geminiRes.json() as any;
  const result = geminiData.candidates?.[0]?.content?.parts?.[0]?.text || '';

  if (!result) return Response.json({ error: '분석 결과를 받지 못했습니다.' }, { status: 502 });

  // [1] 텍스트 추출 / [2] 분석 분리
  const textMatch = result.match(/\[1\][^\n]*\n([\s\S]*?)(?=\[2\]|$)/);
  const analysisMatch = result.match(/\[2\][^\n]*\n([\s\S]*?)$/);

  return Response.json({
    ok: true,
    text: textMatch?.[1]?.trim() || '',
    analysis: analysisMatch?.[1]?.trim() || '',
    full: result,
  });
}

// /admin/analyze는 OCR 없이 텍스트만 받아 분석 (구버전 호환)
async function handleAdminAnalyze(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });

  const { text, title } = await req.json() as { text: string; title?: string };
  if (!text?.trim()) return Response.json({ error: 'text required' }, { status: 400 });

  const response = await env.AI.run('@cf/meta/llama-3.3-70b-instruct-fp8-fast', {
    messages: [
      { role: 'system', content: `당신은 한국 근현대사(1900~1945) 전문 사료 분석가입니다. 주어진 텍스트를 분석하세요.` },
      { role: 'user', content: `자료명: ${title || ''}\n\n${text.slice(0, 6000)}` },
    ],
  } as any);

  return Response.json({ ok: true, analysis: (response as any).response });
}

// ─── 검토자(Reviewer) — 자료 검토만 가능, 승인/커밋 권한 없음 ─────
//
// REVIEWER_SECRET 형식: "김남균:secret_for_kim,홍길동:secret_for_hong"
// 매칭되는 이름이 토큰 세션에 기록되고 모든 검토 행위에 reviewer 식별로 사용.

interface ReviewerSession { name: string; expires: number; }

function parseReviewerSecrets(env: Env): Array<{ name: string; secret: string }> {
  if (!env.REVIEWER_SECRET) return [];
  return env.REVIEWER_SECRET.split(',').map(s => {
    const [n, sec] = s.split(':').map(x => x.trim());
    return { name: n, secret: sec };
  }).filter(x => x.name && x.secret);
}

async function authReviewer(req: Request, env: Env): Promise<ReviewerSession | null> {
  const auth = req.headers.get('Authorization') || '';
  const m = auth.match(/^Bearer\s+(\S+)$/);
  if (!m) return null;
  const raw = await env.REVIEW_STATE.get(`session:${m[1]}`);
  if (!raw) return null;
  const sess = JSON.parse(raw) as ReviewerSession;
  if (sess.expires < Date.now()) return null;
  return sess;
}

function randomToken(): string {
  const buf = new Uint8Array(32);
  crypto.getRandomValues(buf);
  return Array.from(buf).map(b => b.toString(16).padStart(2, '0')).join('');
}

async function handleReviewLogin(req: Request, env: Env) {
  const { password } = await req.json() as { password?: string };
  if (!password) return Response.json({ error: 'password required' }, { status: 400 });

  const reviewers = parseReviewerSecrets(env);
  const match = reviewers.find(r => r.secret === password.trim());
  if (!match) return Response.json({ error: '비밀번호가 일치하지 않습니다.' }, { status: 401 });

  const token = randomToken();
  const expires = Date.now() + 7 * 24 * 60 * 60 * 1000;  // 7일
  await env.REVIEW_STATE.put(
    `session:${token}`,
    JSON.stringify({ name: match.name, expires }),
    { expirationTtl: 7 * 24 * 60 * 60 },
  );
  return Response.json({ ok: true, token, reviewer_name: match.name, expires });
}

interface ReviewState {
  status: 'pending' | 'ok' | 'edit_needed' | 'reject_suggested' | 'reroute_suggested';
  comments: Array<{ reviewer: string; text: string; ts: number }>;
  suggested_md?: string;
  suggested_at?: number;
  suggested_by?: string;
  suggested_kind?: 'edit' | 'supplement';
  last_reviewer?: string;
  updated_at?: number;
}

async function getReviewState(env: Env, num: number): Promise<ReviewState> {
  const raw = await env.REVIEW_STATE.get(`review:${num}`);
  if (!raw) return { status: 'pending', comments: [] };
  return JSON.parse(raw) as ReviewState;
}

async function putReviewState(env: Env, num: number, st: ReviewState) {
  await env.REVIEW_STATE.put(`review:${num}`, JSON.stringify(st));
}

async function handleReviewIssues(req: Request, env: Env) {
  const sess = await authReviewer(req, env);
  if (!sess) return Response.json({ error: '인증 필요' }, { status: 401 });

  // 페이지네이션 — 134건+ 모두 가져오도록 page=1..10 (최대 1000건)
  const PER_PAGE = 100, MAX_PAGES = 10;
  const issues: any[] = [];
  for (let page = 1; page <= MAX_PAGES; page++) {
    const ghRes = await fetch(
      `https://api.github.com/repos/thusus815/815/issues?labels=%EC%9E%90%EB%A3%8C%EC%A0%9C%EC%B6%9C&state=all&per_page=${PER_PAGE}&page=${page}`,
      { headers: { Accept: 'application/vnd.github+json', 'User-Agent': 'my-31-review' } }
    );
    if (!ghRes.ok) return Response.json({ error: 'GitHub API 오류' }, { status: 502 });
    const arr = await ghRes.json() as any[];
    if (!Array.isArray(arr)) return Response.json({ error: 'GitHub API 응답 오류' }, { status: 502 });
    issues.push(...arr);
    if (arr.length < PER_PAGE) break;
  }

  // 각 이슈에 자동 분류 미리보기 + 검토 상태 부착
  const enriched = await Promise.all(issues.map(async (iss) => {
    const preview = iss.body ? buildMdFromIssue(iss) : null;
    const st = await getReviewState(env, iss.number);
    return {
      number: iss.number,
      title: iss.title,
      state: iss.state,
      created_at: iss.created_at,
      labels: (iss.labels || []).map((l: any) => l.name),
      body: iss.body,
      html_url: iss.html_url,
      preview: preview ? {
        kind: preview.kind,
        folder: preview.folder,
        filename: preview.filename,
        md: preview.md,
      } : null,
      review: st,
    };
  }));

  return new Response(
    JSON.stringify({ ok: true, reviewer: sess.name, issues: enriched }),
    {
      headers: {
        'Content-Type': 'application/json',
        'Cache-Control': 'no-store, no-cache, must-revalidate',
      },
    }
  );
}

// 검토자가 web에서 .md 수정 제안 제출 (GitHub 직접 접근 없이)
async function handleReviewSuggestEdit(req: Request, env: Env) {
  const sess = await authReviewer(req, env);
  if (!sess) return Response.json({ error: '인증 필요' }, { status: 401 });

  const { issue_number, md, kind, note } = await req.json() as {
    issue_number?: number; md?: string; kind?: 'edit' | 'supplement'; note?: string;
  };
  if (!issue_number || !md) return Response.json({ error: 'issue_number, md required' }, { status: 400 });

  const st = await getReviewState(env, issue_number);
  st.suggested_md = md;
  st.suggested_at = Date.now();
  st.suggested_by = sess.name;
  st.suggested_kind = kind === 'supplement' ? 'supplement' : 'edit';
  if (note) {
    st.comments.push({ reviewer: sess.name, text: `[${st.suggested_kind === 'supplement' ? '보충' : '수정'} 제안] ${note}`, ts: Date.now() });
  }
  st.last_reviewer = sess.name;
  st.updated_at = Date.now();
  await putReviewState(env, issue_number, st);

  return Response.json({ ok: true, kind: st.suggested_kind });
}

async function handleReviewComment(req: Request, env: Env) {
  const sess = await authReviewer(req, env);
  if (!sess) return Response.json({ error: '인증 필요' }, { status: 401 });

  const { issue_number, text } = await req.json() as { issue_number?: number; text?: string };
  if (!issue_number || !text?.trim()) return Response.json({ error: 'issue_number, text required' }, { status: 400 });

  // KV에 검토 코멘트 추가
  const st = await getReviewState(env, issue_number);
  st.comments.push({ reviewer: sess.name, text: text.trim(), ts: Date.now() });
  st.last_reviewer = sess.name;
  st.updated_at = Date.now();
  await putReviewState(env, issue_number, st);

  // GitHub 이슈에도 댓글 (워커의 GITHUB_TOKEN으로 — 검토자는 직접 GH 권한 없음)
  if (env.GITHUB_TOKEN) {
    await fetch(`https://api.github.com/repos/thusus815/815/issues/${issue_number}/comments`, {
      method: 'POST',
      headers: {
        Authorization: `token ${env.GITHUB_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'Content-Type': 'application/json',
        'User-Agent': 'my-31-review',
      },
      body: JSON.stringify({ body: `**검토자 의견 (${sess.name})**\n\n${text.trim()}` }),
    });
  }

  return Response.json({ ok: true, review: st });
}

async function handleReviewFlag(req: Request, env: Env) {
  const sess = await authReviewer(req, env);
  if (!sess) return Response.json({ error: '인증 필요' }, { status: 401 });

  const { issue_number, status, note } = await req.json() as {
    issue_number?: number;
    status?: ReviewState['status'];
    note?: string;
  };
  if (!issue_number || !status) return Response.json({ error: 'issue_number, status required' }, { status: 400 });

  const validStatuses: ReviewState['status'][] = ['pending', 'ok', 'edit_needed', 'reject_suggested', 'reroute_suggested'];
  if (!validStatuses.includes(status)) return Response.json({ error: 'invalid status' }, { status: 400 });

  // KV 업데이트
  const st = await getReviewState(env, issue_number);
  st.status = status;
  st.last_reviewer = sess.name;
  st.updated_at = Date.now();
  if (note?.trim()) st.comments.push({ reviewer: sess.name, text: `[${status}] ${note.trim()}`, ts: Date.now() });
  await putReviewState(env, issue_number, st);

  // GitHub 라벨 토글
  const labelMap: Record<ReviewState['status'], string | null> = {
    'pending': null,
    'ok': '검토완료',
    'edit_needed': '수정필요',
    'reject_suggested': '반려추천',
    'reroute_suggested': '분류재검토',
  };

  if (env.GITHUB_TOKEN) {
    const headers = { Authorization: `token ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'User-Agent': 'my-31-review' };
    const headersJson = { ...headers, 'Content-Type': 'application/json' };
    const newLabel = labelMap[status];
    const oldLabels = ['검토완료', '수정필요', '반려추천', '분류재검토'];

    // 기존 라벨 제거(병렬) + 새 라벨 부착(필요 시) + 댓글(필요 시)을 모두 동시 실행
    const ops: Promise<any>[] = oldLabels.map(lbl =>
      fetch(
        `https://api.github.com/repos/thusus815/815/issues/${issue_number}/labels/${encodeURIComponent(lbl)}`,
        { method: 'DELETE', headers }
      ).catch(() => {})
    );
    if (newLabel) {
      ops.push(fetch(
        `https://api.github.com/repos/thusus815/815/issues/${issue_number}/labels`,
        { method: 'POST', headers: headersJson, body: JSON.stringify({ labels: [newLabel] }) }
      ).catch(() => {}));
    }
    if (note?.trim()) {
      ops.push(fetch(
        `https://api.github.com/repos/thusus815/815/issues/${issue_number}/comments`,
        { method: 'POST', headers: headersJson, body: JSON.stringify({ body: `**검토자 (${sess.name}) — ${newLabel || status}**\n\n${note.trim()}` }) }
      ).catch(() => {}));
    }

    // 응답을 빠르게 돌려주고 GitHub API 호출은 백그라운드로 (waitUntil 대용 — 그냥 fire-and-forget)
    // 다만 oldLabels 제거는 정합성 위해 await
    await Promise.allSettled(ops);
  }

  return Response.json({ ok: true, review: st });
}

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-Admin-Secret, Authorization",
};

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { headers: CORS });

    try {
      let res: Response;
      if (url.pathname === "/" && req.method === "GET") {
        res = Response.json({ ok: true, service: "815-chat", endpoints: ["/chat", "/persona", "/personas"] });
      } else if (url.pathname === "/chat" && req.method === "POST") {
        res = await handleChat(req, env);
      } else if (url.pathname === "/persona" && req.method === "POST") {
        res = await handlePersona(req, env);
      } else if (url.pathname === "/upload" && req.method === "POST") {
        res = await handleUpload(req, env);
      } else if (url.pathname === "/submit" && req.method === "POST") {
        res = await handleSubmit(req, env);
      } else if (url.pathname === "/comment" && req.method === "POST") {
        res = await handleComment(req, env);
      } else if (url.pathname === "/admin/issues" && req.method === "GET") {
        res = await handleAdminIssues(req, env);
      } else if (url.pathname === "/admin/approve" && req.method === "POST") {
        res = await handleAdminApprove(req, env);
      } else if (url.pathname === "/admin/reject" && req.method === "POST") {
        res = await handleAdminReject(req, env);
      } else if (url.pathname === "/admin/ocr" && req.method === "POST") {
        res = await handleAdminOcr(req, env);
      } else if (url.pathname === "/admin/analyze" && req.method === "POST") {
        res = await handleAdminAnalyze(req, env);
      } else if (url.pathname === "/admin/normalize-spacing" && req.method === "POST") {
        res = await handleNormalizeSpacing(req, env);
      } else if (url.pathname === "/admin/recall" && req.method === "POST") {
        res = await handleAdminRecall(req, env);
      } else if (url.pathname === "/admin/update" && req.method === "POST") {
        res = await handleAdminUpdate(req, env);
      } else if (url.pathname === "/admin/get-md" && req.method === "GET") {
        res = await handleAdminGetCurrentMd(req, env);
      } else if (url.pathname === "/admin/review-state" && req.method === "GET") {
        res = await handleAdminGetReviewState(req, env);
      } else if (url.pathname === "/review/login" && req.method === "POST") {
        res = await handleReviewLogin(req, env);
      } else if (url.pathname === "/review/issues" && req.method === "GET") {
        res = await handleReviewIssues(req, env);
      } else if (url.pathname === "/review/comment" && req.method === "POST") {
        res = await handleReviewComment(req, env);
      } else if (url.pathname === "/review/flag" && req.method === "POST") {
        res = await handleReviewFlag(req, env);
      } else if (url.pathname === "/review/suggest-edit" && req.method === "POST") {
        res = await handleReviewSuggestEdit(req, env);
      } else if (url.pathname === "/personas" && req.method === "GET") {
        res = Response.json(
          Object.values(PERSONAS).map(p => ({ id: p.id, displayName: p.displayName, era: p.era, region: p.region }))
        );
      } else {
        res = new Response("Not Found", { status: 404 });
      }
      const headers = new Headers(res.headers);
      for (const [k, v] of Object.entries(CORS)) headers.set(k, v);
      return new Response(res.body, { status: res.status, headers });
    } catch (e: any) {
      return Response.json({ error: e.message || String(e) }, { status: 500, headers: CORS });
    }
  },
} satisfies ExportedHandler<Env>;
