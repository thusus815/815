"""
볼트 전체 위키링크 그래프 분석.

출력:
  network_stats.json   — 캔버스용 통계
  network_edges.csv    — InfraNodus / Gephi용 엣지리스트
  network_nodes.csv    — Gephi용 노드 속성
  network.gexf         — Gephi 직접 임포트용
  infranodus_input.txt — InfraNodus 텍스트 인풋 (개념쌍 나열)
"""
from __future__ import annotations
import json, re, csv, sys
from collections import defaultdict, Counter
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = VAULT_ROOT / '_가이드' / 'network'
OUT_DIR.mkdir(exist_ok=True)

EXCLUDE_TOP = {'00-원자료', '99-attachments', '_가이드', '08-스냅샷', '.obsidian'}
LINK_RE = re.compile(r'\[\[([^\[\]\n|#]+?)(?:\|[^\[\]\n]+?)?\]\]')
SIDE_RE = re.compile(r'^side:\s*(.+)', re.MULTILINE)
TYPE_RE = re.compile(r'^type:\s*(.+)', re.MULTILINE)
TAGS_RE = re.compile(r'^tags:\s*\[(.+?)\]', re.MULTILINE)

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
    side = (SIDE_RE.search(text) or ['', '미상'])[1] if SIDE_RE.search(text) else '미상'
    if hasattr(side, 'group'): side = side.group(1).strip()
    else:
        m = SIDE_RE.search(text)
        side = m.group(1).strip() if m else '미상'
    typ = TYPE_RE.search(text)
    typ = typ.group(1).strip() if typ else '기타'
    return {'side': side, 'type': typ}

def main():
    files = collect_files()
    stems = set(files.keys())
    
    edges: list[tuple[str,str]] = []
    node_meta: dict[str, dict] = {}
    
    for stem, fp in files.items():
        try:
            text = fp.read_text(encoding='utf-8')
        except:
            continue
        meta = get_meta(text)
        node_meta[stem] = meta
        for m in LINK_RE.finditer(text):
            tgt = norm(m.group(1))
            if tgt and tgt in stems and tgt != stem:
                edges.append((stem, tgt))

    # 방향 없는 그래프 (대칭 처리)
    G: dict[str, set[str]] = defaultdict(set)
    for s, t in edges:
        G[s].add(t)
        G[t].add(s)

    all_nodes = set(G.keys()) | stems
    degree = {n: len(G[n]) for n in all_nodes}

    # PageRank (간소 구현, 30 iter)
    pr = {n: 1/len(all_nodes) for n in all_nodes}
    d = 0.85
    for _ in range(30):
        new_pr = {}
        for n in all_nodes:
            in_sum = sum(pr[s] / max(len(G[s]), 1) for s in G[n])
            new_pr[n] = (1-d)/len(all_nodes) + d * in_sum
        pr = new_pr

    # 매개 중심성 (샘플: degree top-200 으로 근사)
    top_nodes = sorted(all_nodes, key=lambda n: -degree[n])[:200]
    betweenness: dict[str, float] = defaultdict(float)
    for src in top_nodes:
        # BFS
        from collections import deque
        dist = {src: 0}
        sigma = {src: 1.0}
        pred: dict[str, list[str]] = defaultdict(list)
        Q: deque = deque([src])
        S = []
        while Q:
            v = Q.popleft()
            S.append(v)
            for w in G[v]:
                if w not in dist:
                    dist[w] = dist[v] + 1
                    Q.append(w)
                if dist.get(w) == dist[v] + 1:
                    sigma[w] = sigma.get(w, 0) + sigma[v]
                    pred[w].append(v)
        delta = defaultdict(float)
        while S:
            w = S.pop()
            for v in pred[w]:
                delta[v] += sigma[v]/max(sigma[w],1e-9) * (1 + delta[w])
            if w != src:
                betweenness[w] += delta[w]

    # 커뮤니티 탐지 (Louvain 근사 — greedy modularity)
    # 간단 버전: connected component + 측면(side) 기준 분류
    community: dict[str, str] = {}
    for n in all_nodes:
        m = node_meta.get(n, {})
        s = m.get('side', '미상')
        t = m.get('type', '기타')
        if s == '친일':
            community[n] = '친일'
        elif s == '항일':
            community[n] = '항일'
        elif t == '항일학교':
            community[n] = '학교'
        elif t == '사건':
            community[n] = '사건'
        elif t == '지역':
            community[n] = '지역'
        else:
            community[n] = '기타'

    comm_counts = Counter(community.values())

    # Top 인물들
    top_degree   = sorted(all_nodes, key=lambda n: -degree[n])[:20]
    top_pr       = sorted(all_nodes, key=lambda n: -pr[n])[:20]
    top_between  = sorted(betweenness.keys(), key=lambda n: -betweenness[n])[:20]

    # 고립 노드 (링크 0)
    isolates = [n for n in stems if degree.get(n, 0) == 0]

    # side별 링크 수
    cross_links = 0
    same_links  = 0
    for s, t in set(edges):
        cs = community.get(s, '기타')
        ct = community.get(t, '기타')
        if cs == ct:
            same_links += 1
        else:
            cross_links += 1

    stats = {
        'total_nodes': len(all_nodes),
        'total_edges': len(set(edges)),
        'avg_degree': round(sum(degree.values()) / max(len(all_nodes), 1), 2),
        'max_degree': max(degree.values(), default=0),
        'isolates': len(isolates),
        'cross_community_edges': cross_links,
        'same_community_edges': same_links,
        'communities': dict(comm_counts),
        'top_degree': [
            {'name': n, 'degree': degree[n], 'side': community.get(n,'기타'), 'pr': round(pr.get(n,0)*1000,3)}
            for n in top_degree
        ],
        'top_betweenness': [
            {'name': n, 'score': round(betweenness[n],1), 'side': community.get(n,'기타')}
            for n in top_between
        ],
        'top_pagerank': [
            {'name': n, 'pr': round(pr.get(n,0)*10000,2), 'side': community.get(n,'기타')}
            for n in top_pr
        ],
    }

    # --- 파일 출력 ---
    (OUT_DIR / 'network_stats.json').write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding='utf-8')
    print('→ network_stats.json')

    # 엣지 CSV (InfraNodus / Gephi)
    edge_set = list({(min(s,t), max(s,t)) for s,t in edges})
    with open(OUT_DIR / 'network_edges.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Source', 'Target', 'Weight'])
        edge_counter = Counter((min(s,t), max(s,t)) for s,t in edges)
        for (s,t), cnt in edge_counter.most_common():
            w.writerow([s, t, cnt])
    print('→ network_edges.csv')

    # 노드 CSV
    with open(OUT_DIR / 'network_nodes.csv', 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['Id', 'Label', 'Side', 'Type', 'Degree', 'PageRank', 'Betweenness', 'Community'])
        for n in sorted(all_nodes):
            m = node_meta.get(n, {})
            w.writerow([n, n, m.get('side',''), m.get('type',''),
                        degree.get(n,0), round(pr.get(n,0)*10000,4),
                        round(betweenness.get(n,0),2), community.get(n,'기타')])
    print('→ network_nodes.csv')

    # GEXF (Gephi)
    gexf_lines = ['<?xml version="1.0" encoding="UTF-8"?>',
        '<gexf xmlns="http://gexf.net/1.3" version="1.3">',
        '  <graph defaultedgetype="undirected">',
        '    <attributes class="node">',
        '      <attribute id="0" title="side" type="string"/>',
        '      <attribute id="1" title="degree" type="integer"/>',
        '      <attribute id="2" title="community" type="string"/>',
        '      <attribute id="3" title="pagerank" type="float"/>',
        '    </attributes>',
        '    <nodes>']
    for n in sorted(all_nodes):
        m = node_meta.get(n, {})
        label = n.replace('"', '&quot;')
        gexf_lines.append(f'      <node id="{label}" label="{label}">')
        gexf_lines.append(f'        <attvalues>')
        gexf_lines.append(f'          <attvalue for="0" value="{m.get("side","")}"/>')
        gexf_lines.append(f'          <attvalue for="1" value="{degree.get(n,0)}"/>')
        gexf_lines.append(f'          <attvalue for="2" value="{community.get(n,"")}"/>')
        gexf_lines.append(f'          <attvalue for="3" value="{round(pr.get(n,0)*10000,4)}"/>')
        gexf_lines.append(f'        </attvalues>')
        gexf_lines.append(f'      </node>')
    gexf_lines.append('    </nodes>')
    gexf_lines.append('    <edges>')
    for i, ((s, t), cnt) in enumerate(edge_counter.most_common()):
        sl, tl = s.replace('"','&quot;'), t.replace('"','&quot;')
        gexf_lines.append(f'      <edge id="{i}" source="{sl}" target="{tl}" weight="{cnt}"/>')
    gexf_lines += ['    </edges>', '  </graph>', '</gexf>']
    (OUT_DIR / 'network.gexf').write_text('\n'.join(gexf_lines), encoding='utf-8')
    print('→ network.gexf (Gephi 직접 임포트)')

    # InfraNodus 텍스트 인풋 (엣지쌍을 문장처럼)
    infra_lines = []
    for (s, t), cnt in edge_counter.most_common(2000):
        for _ in range(min(cnt, 3)):
            infra_lines.append(f'{s} {t}')
    (OUT_DIR / 'infranodus_input.txt').write_text('\n'.join(infra_lines), encoding='utf-8')
    print('→ infranodus_input.txt (InfraNodus 텍스트 인풋)')

    print(f'\n=== 분석 완료 ===')
    print(f'노드: {stats["total_nodes"]:,}')
    print(f'엣지: {stats["total_edges"]:,}')
    print(f'평균 연결수: {stats["avg_degree"]}')
    print(f'커뮤니티: {dict(comm_counts)}')
    print(f'브로커 Top3: {[x["name"] for x in stats["top_betweenness"][:3]]}')
    print(f'허브 Top3: {[x["name"] for x in stats["top_degree"][:3]]}')
    return 0

if __name__ == '__main__':
    sys.exit(main())
