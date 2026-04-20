/**
 * Gephi 자동화: graph_data.json → graph.gexf (좌표·색상·크기 포함)
 *
 *   1. Louvain 커뮤니티 검출 (Modularity)
 *   2. ForceAtlas 2 레이아웃 (Dissuade Hubs ON, Prevent Overlap ON)
 *   3. 커뮤니티별 색상, degree 기반 크기
 *   4. GEXF (viz:position, viz:color, viz:size 포함)로 저장
 *
 * 결과: graph.gexf 가 사이트에서 즉시 사용 가능 (graph.html이 GEXF 우선 로드).
 *
 * 사용법:
 *   cd scripts/layout
 *   npm install
 *   node build_layout.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import Graph from "graphology";
import louvain from "graphology-communities-louvain";
import forceAtlas2 from "graphology-layout-forceatlas2";
import gexf from "graphology-gexf";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const VAULT = path.resolve(__dirname, "..", "..");
const IN  = path.join(VAULT, "graph_data.json");
const OUT = path.join(VAULT, "graph.gexf");

console.log(`[1/6] Reading ${IN}`);
const data = JSON.parse(fs.readFileSync(IN, "utf8"));
console.log(`     ${data.nodes.length} nodes, ${data.edges.length} edges`);

console.log("[2/6] Building graph...");
const g = new Graph({ type: "undirected", multi: false, allowSelfLoops: false });

for (const n of data.nodes) {
  if (g.hasNode(n.id)) continue;
  g.addNode(n.id, {
    label:    n.label || n.id,
    category: n.category || "",
    tags:     Array.isArray(n.tags) ? n.tags.join(",") : (n.tags || ""),
    path:     n.path || "",
  });
}
let dupSkip = 0, missingSkip = 0;
for (const e of data.edges) {
  if (!g.hasNode(e.source) || !g.hasNode(e.target)) { missingSkip++; continue; }
  if (e.source === e.target) continue;
  if (g.hasEdge(e.source, e.target)) { dupSkip++; continue; }
  g.addEdge(e.source, e.target, {
    weight:    e.weight || 1,
    direction: e.direction || "mutual",
    relType:   e.relType || "",
  });
}
console.log(`     Graph: ${g.order} nodes, ${g.size} edges  (skipped: dup=${dupSkip}, missing=${missingSkip})`);

console.log("[3/6] Louvain community detection...");
const communities = louvain(g, { resolution: 5.0 });
// 작은 커뮤니티(<10노드)는 "기타"로 통합
const commCount = {};
for (const c of Object.values(communities)) commCount[c] = (commCount[c] || 0) + 1;
const SMALL = 10;
const OTHER = -1;
let smallCount = 0;
for (const n of Object.keys(communities)) {
  if (commCount[communities[n]] < SMALL) { communities[n] = OTHER; smallCount++; }
}
const commSet = new Set(Object.values(communities));
console.log(`     ${commSet.size} communities (merged ${smallCount} nodes from small clusters into "기타")`);

const palette = [
  "#e63946", "#f4a261", "#2a9d8f", "#264653", "#8338ec",
  "#3a86ff", "#ff006e", "#fb5607", "#ffbe0b", "#06d6a0",
  "#118ab2", "#073b4c", "#ef476f", "#ffd166", "#7209b7",
  "#560bad", "#480ca8", "#3a0ca3", "#3f37c9", "#4361ee",
  "#4895ef", "#4cc9f0", "#90be6d", "#f9c74f", "#f8961e",
  "#f3722c", "#577590", "#43aa8b", "#9b5de5", "#00bbf9",
];

console.log("[4/6] Assigning colors and sizes...");
g.forEachNode((n) => {
  const c = communities[n] ?? 0;
  g.setNodeAttribute(n, "community", c);
  const color = (c === OTHER) ? "#cccccc" : palette[Math.abs(c) % palette.length];
  g.setNodeAttribute(n, "color", color);
  const deg = g.degree(n);
  g.setNodeAttribute(n, "size", Math.max(1.5, Math.min(12, Math.log2(1 + deg) * 1.8)));
  g.setNodeAttribute(n, "x", (Math.random() - 0.5) * 1000);
  g.setNodeAttribute(n, "y", (Math.random() - 0.5) * 1000);
});

console.log("[5/6] ForceAtlas 2 layout (1500 iterations)...");
const t0 = Date.now();
const inferred = forceAtlas2.inferSettings(g);
forceAtlas2.assign(g, {
  iterations: 1500,
  settings: {
    ...inferred,
    barnesHutOptimize:           true,
    barnesHutTheta:              0.6,
    gravity:                     1.0,
    scalingRatio:                10,
    strongGravityMode:           false,
    outboundAttractionDistribution: true,
    linLogMode:                  false,
    adjustSizes:                 true,
    edgeWeightInfluence:         0.5,
    slowDown:                    1,
  },
});
const dt = ((Date.now() - t0) / 1000).toFixed(1);
console.log(`     done in ${dt}s`);

// NaN/Infinity 좌표 복구 (isolated node 등에서 FA2가 NaN을 남길 수 있음)
let nanFix = 0;
g.forEachNode((n) => {
  const x = g.getNodeAttribute(n, "x");
  const y = g.getNodeAttribute(n, "y");
  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    g.setNodeAttribute(n, "x", (Math.random() - 0.5) * 2000);
    g.setNodeAttribute(n, "y", (Math.random() - 0.5) * 2000);
    nanFix++;
  }
});
if (nanFix) console.log(`     Fixed ${nanFix} NaN/Infinity coordinates (isolated nodes)`);

console.log("[6/6] Writing GEXF...");
const xml = gexf.write(g, { format: "gexf", pretty: true });
fs.writeFileSync(OUT, xml, "utf8");
const kb = (fs.statSync(OUT).size / 1024).toFixed(1);
console.log(`     Saved: ${OUT}  (${kb} KB)`);

console.log("\nDone. Push graph.gexf to deploy:");
console.log("  git add graph.gexf && git commit -m \"Auto-layout via graphology\" && git push");
