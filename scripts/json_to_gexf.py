"""
graph_data.json → graph.gexf 변환기

Gephi에서 열어 다음 작업을 하기 위함:
  - Statistics → Modularity (자동 클러스터)
  - Layout → ForceAtlas 2 (시각적 레이아웃)
  - Appearance → 색상/크기 조정
  - Export → graph.gexf (좌표·클러스터 포함)

변환된 GEXF는 모든 메타데이터(weight, direction, relType, category)를 보존합니다.
"""
import os, json, sys, io, argparse
from xml.sax.saxutils import escape

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

VAULT_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

parser = argparse.ArgumentParser()
parser.add_argument("--in",   dest="src", default=os.path.join(VAULT_DEFAULT, "graph_data.json"))
parser.add_argument("--out",  dest="dst", default=os.path.join(VAULT_DEFAULT, "graph.gexf"))
args = parser.parse_args()

print(f"[1/3] 읽기: {args.src}")
with open(args.src, encoding="utf-8") as f:
    data = json.load(f)

nodes = data.get("nodes", [])
edges = data.get("edges", [])
print(f"  노드 {len(nodes)}, 엣지 {len(edges)}")

def hex_to_rgb(h):
    h = h.lstrip("#")
    if len(h) != 6:
        return (136, 136, 136)
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

print("[2/3] GEXF 작성 중...")
out = []
out.append('<?xml version="1.0" encoding="UTF-8"?>')
out.append('<gexf xmlns="http://gexf.net/1.3" '
           'xmlns:viz="http://gexf.net/1.3/viz" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:schemaLocation="http://gexf.net/1.3 http://gexf.net/1.3/gexf.xsd" '
           'version="1.3">')
out.append('  <meta lastmodifieddate="2026-04-15">')
out.append('    <creator>815 독립운동 아카이브</creator>')
out.append('    <description>친일·항일 인물·사건·지역 지식 그래프</description>')
out.append('  </meta>')
out.append('  <graph defaultedgetype="undirected" mode="static">')

# 노드 속성 정의
out.append('    <attributes class="node">')
out.append('      <attribute id="category" title="category" type="string"/>')
out.append('      <attribute id="tags" title="tags" type="string"/>')
out.append('      <attribute id="path" title="path" type="string"/>')
out.append('    </attributes>')

# 엣지 속성 정의
out.append('    <attributes class="edge">')
out.append('      <attribute id="weight" title="weight" type="float"/>')
out.append('      <attribute id="direction" title="direction" type="string"/>')
out.append('      <attribute id="relType" title="relType" type="string"/>')
out.append('    </attributes>')

# 노드들
out.append('    <nodes>')
for n in nodes:
    nid = escape(str(n["id"]))
    label = escape(str(n.get("label", n["id"])))
    color = n.get("color", "#888888")
    r, g, b = hex_to_rgb(color)
    size = float(n.get("size", 5))
    category = escape(str(n.get("category", "기타")))
    tags = escape(",".join(n.get("tags", [])))
    path = escape(str(n.get("id", "")))

    out.append(f'      <node id="{nid}" label="{label}">')
    out.append(f'        <attvalues>')
    out.append(f'          <attvalue for="category" value="{category}"/>')
    out.append(f'          <attvalue for="tags" value="{tags}"/>')
    out.append(f'          <attvalue for="path" value="{path}"/>')
    out.append(f'        </attvalues>')
    out.append(f'        <viz:color r="{r}" g="{g}" b="{b}"/>')
    out.append(f'        <viz:size value="{size:.2f}"/>')
    out.append(f'      </node>')
out.append('    </nodes>')

# 엣지들
out.append('    <edges>')
for i, e in enumerate(edges):
    src = escape(str(e["source"]))
    tgt = escape(str(e["target"]))
    weight = float(e.get("weight", 1))
    direction = escape(str(e.get("direction", "forward")))
    relType = escape(str(e.get("relType", "")))
    color = e.get("color", "#3a4452")
    r, g, b = hex_to_rgb(color)

    out.append(f'      <edge id="{i}" source="{src}" target="{tgt}" weight="{weight:.2f}">')
    out.append(f'        <attvalues>')
    out.append(f'          <attvalue for="weight" value="{weight:.2f}"/>')
    out.append(f'          <attvalue for="direction" value="{direction}"/>')
    out.append(f'          <attvalue for="relType" value="{relType}"/>')
    out.append(f'        </attvalues>')
    out.append(f'        <viz:color r="{r}" g="{g}" b="{b}"/>')
    out.append(f'      </edge>')
out.append('    </edges>')

out.append('  </graph>')
out.append('</gexf>')

print(f"[3/3] 저장: {args.dst}")
with open(args.dst, "w", encoding="utf-8") as f:
    f.write("\n".join(out))

size_mb = os.path.getsize(args.dst) / (1024*1024)
print(f"\n완료!")
print(f"  파일: {args.dst}")
print(f"  크기: {size_mb:.2f} MB")
print(f"  노드: {len(nodes)}, 엣지: {len(edges)}")
print(f"\n다음 단계: Gephi에서 이 파일을 열어 디자인하세요.")
