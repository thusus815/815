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

interface Env {
  AI: Ai;
  SITE_ORIGIN: string;
  GRAPH_DATA_URL: string;
  RELATIONS_URL: string;
  GITHUB_TOKEN?: string;
  SUBMIT_AUTH: KVNamespace;
  ATTACHMENTS: R2Bucket;
  ADMIN_SECRET?: string;
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

// 이슈 본문에서 섹션 값 추출
function parseSection(body: string, heading: string): string {
  const re = new RegExp(`## ${heading}\\s*\\n([\\s\\S]*?)(?=\\n## |\\n---|-$)`, 'm');
  const m = body.match(re);
  return m ? m[1].trim() : '';
}

// 지역 → 폴더 경로 자동 매핑
function regionToFolder(region: string): string {
  const r = region.trim();
  if (r.includes('예산')) return '04-지역/충남/예산';
  if (r.includes('공주')) return '04-지역/충남/공주';
  if (r.includes('천안') || r.includes('아산')) return '04-지역/충남/천안';
  if (r.includes('충남')) return '04-지역/충남';
  if (r.includes('청주') || r.includes('충북')) return '04-지역/충북/청주';
  if (r.includes('충북')) return '04-지역/충북';
  if (r.includes('서울') || r.includes('경성')) return '04-지역/서울';
  return '04-지역/미분류';
}

// 이슈 본문 → md 파일 내용 자동 생성
function buildMdFromIssue(issue: any): { md: string; folder: string; filename: string } {
  const body: string = issue.body || '';
  const title    = parseSection(body, '자료 제목') || issue.title.replace('[자료 제출] ', '');
  const type     = parseSection(body, '자료 종류');
  const date     = parseSection(body, '자료 연도');
  const region   = parseSection(body, '관련 지역');
  const persons  = parseSection(body, '관련 인물·사건');
  const source   = parseSection(body, '자료 출처·소장처');
  const note     = parseSection(body, '설명·메모');
  const files    = parseSection(body, '첨부 파일 목록');

  const submitterLine = (body.match(/^제출자: (.+)$/m) || [])[1] || '';

  const folder   = regionToFolder(region);
  const safeTitle = title.replace(/[\/\\:*?"<>|]/g, '_').slice(0, 60);
  const filename  = `${safeTitle}.md`;

  const md = [
    `# ${title}`,
    ``,
    `- **자료 종류**: ${type || '미상'}`,
    `- **연도**: ${date || '미상'}`,
    `- **지역**: ${region || '미상'}`,
    `- **출처**: ${source || '미기재'}`,
    `- **제출자**: ${submitterLine}`,
    `- **원본 이슈**: [#${issue.number}](${issue.html_url})`,
    ``,
    `---`,
    ``,
    `## 관련 인물·사건`,
    ``,
    persons || '(미기재)',
    ``,
    `## 설명·메모`,
    ``,
    note || '(없음)',
    ``,
    `## 첨부 파일`,
    ``,
    files || '(없음)',
  ].join('\n');

  return { md, folder, filename };
}

async function handleAdminIssues(req: Request, env: Env) {
  if (!checkAdmin(req, env)) return Response.json({ error: '인증 실패' }, { status: 401 });
  if (!env.GITHUB_TOKEN) return Response.json({ error: 'GITHUB_TOKEN 미설정' }, { status: 503 });

  const url = new URL(req.url);
  const state = url.searchParams.get('state') || 'open';
  const page  = url.searchParams.get('page') || '1';

  const ghRes = await fetch(
    `https://api.github.com/repos/thusus815/815/issues?labels=%EC%9E%90%EB%A3%8C%EC%A0%9C%EC%B6%9C&state=${state}&per_page=30&page=${page}`,
    { headers: { Authorization: `token ${env.GITHUB_TOKEN}`, Accept: 'application/vnd.github+json', 'User-Agent': 'my-31-admin' } }
  );
  const issues = await ghRes.json();
  return Response.json(issues);
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

  return Response.json({ ok: true, file_path: filePath, commit_url: created.commit?.html_url });
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

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
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
