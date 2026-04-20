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
  // RELATIONS?: KVNamespace;
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

function findRelevantNodes(question: string, graph: { nodes: GraphNode[]; edges: GraphEdge[] }, topK = 8) {
  const q = question.toLowerCase();
  const tokens = q.split(/[\s,.\?!:;()]+/).filter(t => t.length >= 2);
  const scored = graph.nodes.map(n => {
    let score = 0;
    const label = n.label.toLowerCase();
    for (const t of tokens) if (label.includes(t)) score += 3;
    if (label === q) score += 10;
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

  const response = await env.AI.run("@cf/meta/llama-3.1-8b-instruct", { messages } as any);

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

  const response = await env.AI.run("@cf/meta/llama-3.1-8b-instruct", { messages } as any);

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
