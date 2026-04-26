"""
볼트 .md 파일에서 노드와 엣지를 추출해 Sigma.js용 graph.json 생성
- 방향성(direction): mutual(양방향) / forward(단방향)
- 가중치(weight): 인용 횟수 합계
- 관계타입(relType): "인물-사건", "인물-지역" 등
- 추론엣지(inferred): 같은 노트에서 함께 언급된 인물 쌍 (점선)
"""
import os, re, json, sys, io, math
import unicodedata
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import argparse
_parser = argparse.ArgumentParser()
_parser.add_argument("--vault", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_parser.add_argument("--out",   default=None)
_args, _ = _parser.parse_known_args()
VAULT = _args.vault
OUT   = _args.out or os.path.join(VAULT, "graph_data.json")

EXCLUDE = {
    "00-원자료", "_inbox", "99-attachments", "08-스냅샷",
    ".obsidian", ".git", ".github",
    "scripts", "templates", "worker", "node_modules",
}

# 그래프에서 제외할 메타 문서 파일명 패턴 (운영자 가이드, README 등)
EXCLUDE_FILE_PATTERNS = [
    re.compile(r"^README", re.IGNORECASE),
    re.compile(r"가이드"),
    re.compile(r"GUIDE", re.IGNORECASE),
    re.compile(r"^00_입력_템플릿"),
    re.compile(r"^_"),                         # _로 시작하는 임시·메타 파일
    re.compile(r"GEPHI", re.IGNORECASE),
    re.compile(r"design"),
    re.compile(r"방법$"),                      # "...하는 방법"
]

TAG_COLOR = {
    "친일인물":   "#FF6B35",
    "항일":       "#4A90D9",
    "사건":       "#7BC67E",
    "단체":       "#B07CC6",
    "지역":       "#F5C842",
    "학교":       "#E57373",
    "문헌":       "#90A4AE",
    "인덱스":     "#FFFFFF",
}
DEFAULT_COLOR = "#888888"

# 카테고리 분류 (관계타입 산출용)
def categorize(path, tags):
    p = path.replace("\\", "/")
    for t in (tags or []):
        ts = str(t)
        if "친일" in ts: return "친일인물"
        if "항일" in ts: return "항일인물"
        if "사건" in ts: return "사건"
        if "단체" in ts: return "단체"
        if "지역" in ts: return "지역"
        if "학교" in ts: return "학교"
        if "문헌" in ts: return "문헌"
    if "01-인물/항일" in p: return "항일인물"
    if "01-인물" in p:      return "친일인물"
    if "02-사건" in p:      return "사건"
    if "03-단체" in p:      return "단체"
    if "04-지역" in p:      return "지역"
    if "07-항일학교" in p:  return "학교"
    if "05-문헌" in p:      return "문헌"
    return "기타"

def get_color(category):
    return TAG_COLOR.get(category if category != "항일인물" else "항일",
                         TAG_COLOR.get(category, DEFAULT_COLOR))

# 관계타입 → 색상 (정렬된 카테고리 쌍)
REL_COLOR = {
    ("친일인물", "사건"):   "#7BC67E",
    ("항일인물", "사건"):   "#7BC67E",
    ("친일인물", "단체"):   "#B07CC6",
    ("항일인물", "단체"):   "#B07CC6",
    ("친일인물", "지역"):   "#F5C842",
    ("항일인물", "지역"):   "#F5C842",
    ("친일인물", "학교"):   "#E57373",
    ("항일인물", "학교"):   "#E57373",
    ("사건", "사건"):       "#4A90D9",
    ("사건", "단체"):       "#9D7CD8",
    ("사건", "지역"):       "#D4A85A",
    ("친일인물", "친일인물"): "#FF8C5C",
    ("항일인물", "항일인물"): "#5BAFE3",
    ("친일인물", "항일인물"): "#FF4444",  # 대립 관계
}
DEFAULT_EDGE_COLOR = "#3a4452"
MUTUAL_COLOR = "#FFD700"  # 양방향 = 금색

def rel_key(a, b):
    return tuple(sorted([a, b]))

LINK_RE = re.compile(r'\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]')
YAML_RE = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)

# frontmatter에 정의된 관계 필드 (배열 형태) — 이 필드의 값도 엣지로 인식
RELATION_FIELDS = ['관련인물', '관련학교', '관련사건', '관련기관', '관련지역']

def parse_tags(yaml_text):
    tags = []
    m = re.search(r'^tags\s*:\s*\[([^\]]+)\]', yaml_text, re.MULTILINE)
    if m:
        tags = [t.strip().strip('"\'') for t in m.group(1).split(',')]
    else:
        m2 = re.search(r'^tags\s*:\s*\n((?:\s+-\s*.+\n?)+)', yaml_text, re.MULTILINE)
        if m2:
            tags = re.findall(r'-\s*(.+)', m2.group(1))
    return [t.strip() for t in tags if t.strip()]

def parse_relation_field(yaml_text, field_name):
    """frontmatter의 '관련인물: [A, B, C]' 같은 배열 필드를 추출."""
    out = []
    # 인라인 배열 형식: 관련인물: [A, B, C] 또는 관련인물: ["A", "B"]
    m = re.search(rf'^{field_name}\s*:\s*\[([^\]]*)\]', yaml_text, re.MULTILINE)
    if m and m.group(1).strip():
        out = [t.strip().strip('"\'') for t in m.group(1).split(',')]
    else:
        # 블록 배열 형식:
        #   관련인물:
        #     - A
        #     - B
        m2 = re.search(rf'^{field_name}\s*:\s*\n((?:\s+-\s*.+\n?)+)', yaml_text, re.MULTILINE)
        if m2:
            out = re.findall(r'-\s*(.+)', m2.group(1))
        else:
            # 단일 값: 관련인물: 홍길동
            m3 = re.search(rf'^{field_name}\s*:\s*([^\n\[].*)$', yaml_text, re.MULTILINE)
            if m3 and m3.group(1).strip() and not m3.group(1).strip().startswith('['):
                out = [m3.group(1).strip().strip('"\'')]
    return [t.strip() for t in out if t and t.strip()]

def slug(path):
    rel = os.path.relpath(path, VAULT).replace("\\", "/")
    return unicodedata.normalize("NFC", rel[:-3] if rel.endswith(".md") else rel)

# ===== 1. 파일 스캔 =====
print("[1/4] .md 파일 스캔 중...")
md_files = []
skipped_meta = []
for root, dirs, files in os.walk(VAULT):
    dirs[:] = [d for d in dirs if d not in EXCLUDE]
    for f in files:
        if not f.endswith(".md"):
            continue
        base = f[:-3]
        if any(p.search(base) for p in EXCLUDE_FILE_PATTERNS):
            skipped_meta.append(f)
            continue
        md_files.append(os.path.join(root, f))
print(f"  총 {len(md_files)}개 파일 (메타 문서 {len(skipped_meta)}개 제외)")

# ===== 2. 노드 구축 =====
nodes = {}              # slug → {id, label, color, size, tags, category}
file_links = {}         # slug → [outgoing link slugs]
slug_by_basename = {}   # basename(no ext) → slug (빠른 매칭용)

for fpath in md_files:
    try:
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
    except:
        continue
    sl = slug(fpath)
    label = os.path.splitext(os.path.basename(fpath))[0]
    tags = []
    yaml_m = YAML_RE.match(content)
    if yaml_m:
        tags = parse_tags(yaml_m.group(1))
        title_m = re.search(r'^title\s*:\s*(.+)', yaml_m.group(1), re.MULTILINE)
        if title_m:
            label = title_m.group(1).strip().strip('"\'')
    cat = categorize(fpath, tags)
    nodes[sl] = {
        "id": sl, "label": label, "color": get_color(cat),
        "size": 3, "tags": tags, "category": cat
    }
    base = os.path.splitext(os.path.basename(sl))[0]
    slug_by_basename.setdefault(base, sl)

# ===== 3. 방향성 있는 링크 카운트 =====
print("[2/4] 방향성 링크 추출 중...")
directed_count = defaultdict(int)   # (src, tgt) → count
src_links_in_file = {}              # fpath → list of target slugs (추론 엣지용)

for fpath in md_files:
    try:
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
    except:
        continue
    src = slug(fpath)
    targets_in_this_file = []

    def resolve(link_raw):
        link = unicodedata.normalize("NFC", link_raw.strip())
        if not link:
            return None
        m = slug_by_basename.get(link)
        if m:
            return m
        for nsl in nodes:
            if nsl == link or nsl.endswith("/" + link):
                return nsl
        return None

    # 1) 본문 [[wikilink]] — 인용 횟수 그대로 카운트 (weight 누적)
    for raw in LINK_RE.findall(content):
        matched = resolve(raw)
        if matched and matched != src:
            directed_count[(src, matched)] += 1
            targets_in_this_file.append(matched)

    # 2) frontmatter 관계 필드 — 각 타겟당 1번만 추가 (중복 가중치 방지)
    yaml_m = YAML_RE.match(content)
    if yaml_m:
        already_from_body = set(targets_in_this_file)
        for fld in RELATION_FIELDS:
            for raw in parse_relation_field(yaml_m.group(1), fld):
                matched = resolve(raw)
                if matched and matched != src and matched not in already_from_body:
                    directed_count[(src, matched)] += 1
                    targets_in_this_file.append(matched)
                    already_from_body.add(matched)

    src_links_in_file[fpath] = targets_in_this_file

# ===== 4. 양방향/단방향 판별 + 엣지 통합 =====
print("[3/4] 양방향성 판별 + 관계타입 산출 중...")
edge_map = {}  # frozenset({a,b}) → {weight, direction, src→tgt counts}

for (s, t), cnt in directed_count.items():
    key = frozenset([s, t])
    if key not in edge_map:
        edge_map[key] = {"weight": 0, "fwd": 0, "bwd": 0, "a": s, "b": t}
    e = edge_map[key]
    if s == e["a"]:
        e["fwd"] += cnt
    else:
        e["bwd"] += cnt
    e["weight"] += cnt

edges = []
mutual_count = 0
forward_count = 0
for key, e in edge_map.items():
    a, b = e["a"], e["b"]
    cat_a = nodes[a]["category"]
    cat_b = nodes[b]["category"]
    rel = rel_key(cat_a, cat_b)
    is_mutual = e["fwd"] > 0 and e["bwd"] > 0
    if is_mutual:
        mutual_count += 1
        color = MUTUAL_COLOR
    else:
        forward_count += 1
        color = REL_COLOR.get(rel, DEFAULT_EDGE_COLOR)

    # 굵기: log 스케일 (1회=0.3, 5회=0.7, 20회=1.5, 100회=3)
    w = e["weight"]
    size = round(0.3 + math.log(1 + w) * 0.5, 2)

    edges.append({
        "source": a,
        "target": b,
        "weight": w,
        "direction": "mutual" if is_mutual else "forward",
        "relType": f"{rel[0]}-{rel[1]}",
        "color": color,
        "size": size,
        "type": "arrow" if not is_mutual else "line",
    })

# 노드 크기: 들어오는 링크 수 기준
in_degree = defaultdict(int)
for (s, t), cnt in directed_count.items():
    in_degree[t] += cnt
for nsl, cnt in in_degree.items():
    if nsl in nodes:
        nodes[nsl]["size"] = max(3, min(25, 3 + math.log(1 + cnt) * 2))

# ===== 5. 출력 =====
print(f"[4/4] graph.json 저장 중...")
graph = {
    "nodes": list(nodes.values()),
    "edges": [{"id": f"e{i}", **e} for i, e in enumerate(edges)]
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(graph, f, ensure_ascii=False, indent=2)

print(f"""
완료!
  노드: {len(graph['nodes'])}개
  엣지: {len(graph['edges'])}개
    - 양방향 (mutual):  {mutual_count}개  🟡
    - 단방향 (forward): {forward_count}개  ⬜
  출력: {OUT}
""")
