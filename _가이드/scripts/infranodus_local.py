"""
InfraNodus 핵심 기능 로컬 구현.

InfraNodus가 하는 세 가지를 Python으로 재현:
  1. Louvain 커뮤니티 탐지
  2. 구조적 공백(Structural Gap) 탐지
  3. 인터랙티브 네트워크 HTML 시각화 (브라우저에서 열림)

출력: _가이드/network/infranodus_viz.html
     _가이드/network/structural_gaps.json

사용:
  python infranodus_local.py                  # 전체 그래프 (느림)
  python infranodus_local.py --top 300        # 상위 300노드만
  python infranodus_local.py --filter 친일    # 특정 커뮤니티만
  python infranodus_local.py --top 150 --open # 완료 후 브라우저 자동 오픈
"""
from __future__ import annotations
import argparse, json, re, sys, webbrowser
from collections import defaultdict, Counter
from pathlib import Path

import networkx as nx
import community as community_louvain   # python-louvain
from pyvis.network import Network

VAULT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = VAULT_ROOT / '_가이드' / 'network'
OUT_DIR.mkdir(exist_ok=True)

EXCLUDE_TOP = {'00-원자료', '99-attachments', '_가이드', '08-스냅샷', '.obsidian'}
LINK_RE  = re.compile(r'\[\[([^\[\]\n|#]+?)(?:\|[^\[\]\n]+?)?\]\]')
SIDE_RE  = re.compile(r'^side:\s*(.+)', re.MULTILINE)
TYPE_RE  = re.compile(r'^type:\s*(.+)', re.MULTILINE)

# 커뮤니티별 색상 (InfraNodus 스타일 — 부드러운 톤)
COMM_COLORS = {
    '친일': '#e05252',
    '항일': '#4caf7d',
    '지역': '#5b9bd5',
    '학교': '#f5a623',
    '사건': '#9b59b6',
    '기타': '#95a5a6',
}

def collect_files():
    files = {}
    for p in VAULT_ROOT.rglob('*.md'):
        rel = p.relative_to(VAULT_ROOT)
        if not rel.parts or rel.parts[0] in EXCLUDE_TOP:
            continue
        files[p.stem] = p
    return files

def norm(link: str) -> str:
    t = link.split('|')[0].split('#')[0].strip()
    return t.rsplit('/', 1)[-1] if '/' in t else t

def get_meta(text: str) -> dict:
    sm = SIDE_RE.search(text)
    tm = TYPE_RE.search(text)
    return {
        'side': sm.group(1).strip() if sm else '미상',
        'type': tm.group(1).strip() if tm else '기타',
    }

def side_to_community(meta: dict) -> str:
    s, t = meta.get('side','미상'), meta.get('type','기타')
    if s == '친일': return '친일'
    if s == '항일': return '항일'
    if t == '항일학교': return '학교'
    if t == '사건': return '사건'
    if t == '지역': return '지역'
    return '기타'


def build_graph(files: dict, top_n: int | None, filter_side: str | None) -> tuple[nx.Graph, dict]:
    stems = set(files.keys())
    node_meta: dict[str, dict] = {}
    edge_counter: Counter = Counter()

    print(f'노트 파싱 중 ({len(files)}개)...', flush=True)
    for stem, fp in files.items():
        try:
            text = fp.read_text(encoding='utf-8')
        except Exception:
            continue
        meta = get_meta(text)
        node_meta[stem] = meta
        for m in LINK_RE.finditer(text):
            tgt = norm(m.group(1))
            if tgt and tgt in stems and tgt != stem:
                edge_counter[(min(stem, tgt), max(stem, tgt))] += 1

    # degree 기준 top_n 필터
    degree: Counter = Counter()
    for (s, t), w in edge_counter.items():
        degree[s] += w
        degree[t] += w

    if top_n:
        keep = {n for n, _ in degree.most_common(top_n)}
    else:
        keep = set(files.keys())

    if filter_side:
        keep = {n for n in keep
                if side_to_community(node_meta.get(n, {})) == filter_side}

    G = nx.Graph()
    for n in keep:
        meta = node_meta.get(n, {'side': '미상', 'type': '기타'})
        comm = side_to_community(meta)
        G.add_node(n, community=comm, side=meta['side'],
                   degree=degree.get(n, 0))
    for (s, t), w in edge_counter.items():
        if s in keep and t in keep:
            G.add_edge(s, t, weight=w)

    return G, node_meta


def detect_communities_louvain(G: nx.Graph) -> dict[str, int]:
    """python-louvain으로 커뮤니티 번호 부여."""
    if len(G) == 0:
        return {}
    part = community_louvain.best_partition(G, weight='weight', random_state=42)
    return part


def find_structural_gaps(G: nx.Graph, partition: dict[str, int]) -> list[dict]:
    """
    InfraNodus 핵심 알고리즘:
    매개 중심성이 높으면서 자신의 커뮤니티 내 엣지 비율이 낮은 노드
    = 다른 커뮤니티들을 연결하는 브릿지 → 구조적 공백 위치
    """
    if len(G) < 3:
        return []
    print('매개 중심성 계산 중 (샘플링)...', flush=True)
    k = min(len(G), 100)
    betw = nx.betweenness_centrality(G, k=k, weight='weight', normalized=True)

    gaps = []
    for n in G.nodes():
        neighbors = list(G.neighbors(n))
        if not neighbors:
            continue
        own_comm = partition.get(n, -1)
        same = sum(1 for nb in neighbors if partition.get(nb, -2) == own_comm)
        ratio = same / len(neighbors)
        b = betw.get(n, 0)
        gap_score = b * (1 - ratio)  # 높을수록 구조적 공백
        if gap_score > 0:
            # 어떤 커뮤니티들을 연결하는지
            nb_comms = Counter(partition.get(nb, -1) for nb in neighbors if partition.get(nb,-1) != own_comm)
            gaps.append({
                'node': n,
                'gap_score': round(gap_score * 1000, 3),
                'betweenness': round(b, 4),
                'cross_ratio': round(1 - ratio, 3),
                'community': G.nodes[n].get('community', '기타'),
                'bridges_comms': len(nb_comms),
                'degree': len(neighbors),
            })

    gaps.sort(key=lambda x: -x['gap_score'])
    return gaps[:30]


def build_pyvis(G: nx.Graph, partition: dict[str, int],
                gaps: list[dict], node_meta: dict) -> Network:
    """pyvis 인터랙티브 그래프 생성 (InfraNodus 스타일)."""
    nt = Network(
        height='780px', width='100%',
        bgcolor='#0f1117', font_color='#e0e0e0',
        directed=False,
    )
    nt.set_options("""
    {
      "physics": {
        "forceAtlas2Based": {
          "gravitationalConstant": -80,
          "centralGravity": 0.01,
          "springLength": 100,
          "springConstant": 0.08
        },
        "maxVelocity": 50,
        "solver": "forceAtlas2Based",
        "timestep": 0.35,
        "stabilization": { "iterations": 150 }
      },
      "edges": {
        "color": { "color": "#2a2a3a", "highlight": "#aaaacc" },
        "smooth": { "type": "continuous" }
      },
      "interaction": {
        "hover": true,
        "tooltipDelay": 100,
        "zoomView": true
      }
    }
    """)

    gap_nodes = {g['node'] for g in gaps[:10]}
    comm_count = Counter(partition.get(n, -1) for n in G.nodes())
    num_comms = len(set(partition.values()))
    palette = [
        '#e05252','#4caf7d','#5b9bd5','#f5a623',
        '#9b59b6','#1abc9c','#e67e22','#3498db',
        '#e91e63','#00bcd4',
    ]

    degree = dict(G.degree())
    max_deg = max(degree.values(), default=1)

    for n in G.nodes():
        comm_id = partition.get(n, 0)
        color = palette[comm_id % len(palette)]
        meta = node_meta.get(n, {})
        side_label = side_to_community(meta)
        deg = degree[n]
        size = 6 + int(deg / max_deg * 40)

        # 구조적 공백 노드 강조
        border = '#ffffff' if n in gap_nodes else color
        border_width = 3 if n in gap_nodes else 1

        gap_info = next((g for g in gaps if g['node'] == n), None)
        tooltip = (
            f"<b>{n}</b><br>"
            f"커뮤니티: {side_label}<br>"
            f"연결수: {deg}<br>"
        )
        if gap_info:
            tooltip += (
                f"<hr><b>구조적 공백 노드</b><br>"
                f"Gap Score: {gap_info['gap_score']}<br>"
                f"매개중심성: {gap_info['betweenness']}<br>"
                f"커뮤니티 횡단 비율: {int(gap_info['cross_ratio']*100)}%"
            )

        nt.add_node(
            n, label=n if deg > max_deg * 0.05 else '',
            title=tooltip,
            color={'background': color, 'border': border},
            borderWidth=border_width,
            size=size,
        )

    for s, t, data in G.edges(data=True):
        w = data.get('weight', 1)
        nt.add_edge(s, t, value=min(w, 5), width=min(w * 0.5, 3))

    return nt


def inject_gap_panel(html: str, gaps: list[dict]) -> str:
    """생성된 HTML에 구조적 공백 패널 삽입."""
    panel_html = """
<style>
#gap-panel {
  position: fixed; top: 12px; right: 12px; width: 300px;
  background: #1a1a2e; border: 1px solid #2a2a4a;
  border-radius: 8px; padding: 14px; z-index: 9999;
  font-family: system-ui, sans-serif; color: #c8d0e0;
  max-height: 90vh; overflow-y: auto;
}
#gap-panel h3 { margin: 0 0 10px; font-size: 13px; color: #8ab4f8; letter-spacing: 0.5px; }
#gap-panel .subtitle { font-size: 11px; color: #6a7280; margin-bottom: 12px; }
.gap-item { border-bottom: 1px solid #2a2a4a; padding: 8px 0; }
.gap-item:last-child { border-bottom: none; }
.gap-node { font-weight: 600; font-size: 12px; color: #fff; }
.gap-badge { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; margin-left: 5px; }
.gap-친일 { background: #4a1c1c; color: #e05252; }
.gap-항일 { background: #1c3a2a; color: #4caf7d; }
.gap-기타 { background: #2a2a3a; color: #95a5a6; }
.gap-학교 { background: #3a2a0a; color: #f5a623; }
.gap-지역 { background: #1a2a3a; color: #5b9bd5; }
.gap-사건 { background: #2a1a3a; color: #9b59b6; }
.gap-meta { font-size: 10px; color: #6a7280; margin-top: 3px; }
.gap-score { float: right; font-size: 11px; color: #f5a623; }
.legend { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.leg { font-size: 10px; display: flex; align-items: center; gap: 4px; }
.leg-dot { width: 8px; height: 8px; border-radius: 50%; }
</style>
<div id="gap-panel">
  <h3>InfraNodus — 구조적 공백</h3>
  <div class="subtitle">커뮤니티 경계를 횡단하는 브릿지 노드 Top 15</div>
  <div class="legend">
    <div class="leg"><div class="leg-dot" style="background:#e05252"></div>친일</div>
    <div class="leg"><div class="leg-dot" style="background:#4caf7d"></div>항일</div>
    <div class="leg"><div class="leg-dot" style="background:#5b9bd5"></div>지역</div>
    <div class="leg"><div class="leg-dot" style="background:#f5a623"></div>학교</div>
    <div class="leg"><div class="leg-dot" style="background:#9b59b6"></div>사건</div>
    <div class="leg"><div class="leg-dot" style="background:#95a5a6"></div>기타</div>
  </div>
"""
    for i, g in enumerate(gaps[:15]):
        comm = g['community']
        panel_html += f"""
  <div class="gap-item">
    <div class="gap-score">{g['gap_score']}</div>
    <div class="gap-node">{i+1}. {g['node']} <span class="gap-badge gap-{comm}">{comm}</span></div>
    <div class="gap-meta">
      연결 {g['degree']}개 · 횡단 {int(g['cross_ratio']*100)}% · 커뮤니티 {g['bridges_comms']}개 연결
    </div>
  </div>"""
    panel_html += "\n</div>"

    return html.replace('</body>', panel_html + '\n</body>')


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--top',    type=int, default=400, help='상위 N개 노드만 (기본 400)')
    ap.add_argument('--filter', dest='filter_side', help='커뮤니티 필터 (친일/항일 등)')
    ap.add_argument('--open',   action='store_true', help='완료 후 브라우저 자동 오픈')
    ap.add_argument('--all',    action='store_true', help='전체 노드 (느림)')
    args = ap.parse_args()

    top_n = None if args.all else args.top

    files = collect_files()
    G, node_meta = build_graph(files, top_n, args.filter_side)

    print(f'그래프: {G.number_of_nodes()}노드 / {G.number_of_edges()}엣지')

    # Louvain 커뮤니티
    print('Louvain 커뮤니티 탐지 중...', flush=True)
    partition = detect_communities_louvain(G)
    n_comms = len(set(partition.values()))
    comm_sizes = Counter(partition.values())
    print(f'커뮤니티 {n_comms}개 탐지 (최대 {max(comm_sizes.values())}노드)')

    # 구조적 공백
    print('구조적 공백 탐지 중...', flush=True)
    gaps = find_structural_gaps(G, partition)
    print(f'구조적 공백 노드 {len(gaps)}개 식별')

    # 결과 저장
    gap_out = OUT_DIR / 'structural_gaps.json'
    gap_out.write_text(json.dumps(gaps, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'→ {gap_out.name}')

    print('pyvis 그래프 렌더링 중...', flush=True)
    nt = build_pyvis(G, partition, gaps, node_meta)

    html_path = OUT_DIR / 'infranodus_viz.html'
    nt.save_graph(str(html_path))

    # 구조적 공백 패널 삽입
    html = html_path.read_text(encoding='utf-8')
    html = inject_gap_panel(html, gaps)
    html_path.write_text(html, encoding='utf-8')

    print(f'→ {html_path}')
    print(f'\n완료! 브라우저에서 열기:')
    print(f'  {html_path}')

    if args.open:
        webbrowser.open(html_path.as_uri())
        print('  (브라우저 자동 오픈됨)')

    # 콘솔 요약
    print(f'\n=== 구조적 공백 Top 10 ===')
    for g in gaps[:10]:
        print(f'  [{g["gap_score"]:>7}] {g["node"]:20} | 커뮤니티횡단 {int(g["cross_ratio"]*100)}% | 연결 {g["degree"]}개')

    return 0


if __name__ == '__main__':
    sys.exit(main())
