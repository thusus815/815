"""
Step 3b — LLM 의미 관계(Semantic Relation) 라벨링 시스템

각 .md 노트에서 인물·사건 간 관계를 LLM으로 추출:
  ("안중근", "사살한다", "이토 히로부미", confidence=0.95)

증분 처리:
  - 노트 본문 SHA-256 해시 저장 (cache.json)
  - 해시 변경된 노트만 재라벨링 → 비용 폭증 방지

지원 LLM 백엔드 (환경변수로 선택):
  LLM_PROVIDER=github       → GitHub Models (무료 한도)
  LLM_PROVIDER=openai       → OpenAI API (OPENAI_API_KEY 필요)
  LLM_PROVIDER=gemini       → Google Gemini (GEMINI_API_KEY 필요)
  LLM_PROVIDER=cloudflare   → Cloudflare Workers AI (CF_API_TOKEN, CF_ACCOUNT_ID)
  LLM_PROVIDER=mock         → 가짜 응답 (개발/테스트용, 기본값)

출력:
  graph_relations.json — 관계 트리플 모음
  scripts/.label_cache.json — 노트 해시 캐시
"""
import os, re, sys, io, json, hashlib, argparse
import unicodedata
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

VAULT_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parser = argparse.ArgumentParser()
parser.add_argument("--vault",    default=VAULT_DEFAULT)
parser.add_argument("--out",      default=None)
parser.add_argument("--cache",    default=None)
parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "mock"))
parser.add_argument("--limit",    type=int, default=0, help="최대 처리 노트 수 (0=무제한)")
parser.add_argument("--force",    action="store_true", help="캐시 무시하고 재라벨링")
args = parser.parse_args()

VAULT = args.vault
OUT_PATH   = args.out   or os.path.join(VAULT, "graph_relations.json")
CACHE_PATH = args.cache or os.path.join(os.path.dirname(__file__), ".label_cache.json")

EXCLUDE = {"00-원자료", "_inbox", "99-attachments", "08-스냅샷", ".obsidian", ".git", ".github", "scripts", "templates"}
YAML_RE = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)

def load_cache():
    if os.path.exists(CACHE_PATH):
        try:
            return json.load(open(CACHE_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_cache(cache):
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def file_hash(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def slug(path):
    rel = os.path.relpath(path, VAULT).replace("\\", "/")
    return unicodedata.normalize("NFC", rel[:-3] if rel.endswith(".md") else rel)

# ===== LLM 호출 어댑터 =====

PROMPT_TEMPLATE = """당신은 한국 근현대사(1900~1945)의 친일·항일 인물·사건 관계를 추출하는 전문가입니다.

다음 노트를 읽고, 등장하는 인물·단체·사건 간의 의미적 관계(Semantic Relation)를 트리플 형식으로 추출하세요.

규칙:
1. 출력은 JSON 배열만. 설명 없이.
2. 각 트리플은 {{"subject": "...", "predicate": "...", "object": "...", "confidence": 0.0~1.0}}
3. predicate는 짧고 명확하게 (예: "암살한다", "동지", "후원", "재판한다", "투옥된다", "참여한다", "결성한다")
4. 본문에 명시되거나 강하게 함축된 관계만. 추측 금지.
5. confidence: 본문 직접 진술 0.9+, 강한 함축 0.7~0.9, 약한 함축 0.5~0.7

노트 제목: {title}
노트 본문:
{body}

JSON 트리플 배열:"""

def call_mock(prompt):
    """개발용 가짜 응답"""
    return [
        {"subject": "예시인물A", "predicate": "동지", "object": "예시인물B", "confidence": 0.85}
    ]

def call_github_models(prompt):
    """GitHub Models API"""
    import urllib.request
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN 환경변수 필요")
    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://models.inference.ai.azure.com/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    text = data["choices"][0]["message"]["content"]
    return _parse_json_response(text)

def call_openai(prompt):
    import urllib.request
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY 환경변수 필요")
    body = json.dumps({
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"}
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    text = data["choices"][0]["message"]["content"]
    return _parse_json_response(text)

def call_gemini(prompt):
    import urllib.request
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY 환경변수 필요")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={key}"
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2}
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return _parse_json_response(text)

def call_cloudflare(prompt):
    import urllib.request
    token = os.environ.get("CF_API_TOKEN")
    account = os.environ.get("CF_ACCOUNT_ID")
    if not token or not account:
        raise RuntimeError("CF_API_TOKEN, CF_ACCOUNT_ID 환경변수 필요")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/meta/llama-3.1-8b-instruct"
    body = json.dumps({
        "messages": [{"role": "user", "content": prompt}]
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read())
    text = data["result"]["response"]
    return _parse_json_response(text)

def _parse_json_response(text):
    """LLM 응답에서 JSON 배열 추출"""
    text = text.strip()
    # ```json ... ``` 제거
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # {"triples": [...]} 같은 객체로 감싼 경우
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            for v in obj.values():
                if isinstance(v, list):
                    return v
            return []
        return obj if isinstance(obj, list) else []
    except json.JSONDecodeError:
        # 배열만 추출 시도
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return []

PROVIDERS = {
    "mock":       call_mock,
    "github":     call_github_models,
    "openai":     call_openai,
    "gemini":     call_gemini,
    "cloudflare": call_cloudflare,
}

# ===== 메인 처리 =====

def main():
    if args.provider not in PROVIDERS:
        print(f"알 수 없는 provider: {args.provider}")
        print(f"사용 가능: {list(PROVIDERS.keys())}")
        return 1
    llm_call = PROVIDERS[args.provider]
    print(f"[설정] LLM provider = {args.provider}")
    if args.provider == "mock":
        print("       ⚠ 실제 라벨링 없음. API 키 설정 후 다시 실행하세요.")

    cache = load_cache() if not args.force else {}
    print(f"[캐시] 기존 라벨링 {len(cache)}개 노트 (force={args.force})")

    # 노트 수집
    md_files = []
    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]
        for f in files:
            if f.endswith(".md"):
                md_files.append(os.path.join(root, f))

    print(f"[스캔] 총 {len(md_files)}개 노트")

    new_relations = []
    skipped = 0
    processed = 0
    failed = 0

    for fpath in md_files:
        if args.limit and processed >= args.limit:
            break
        try:
            with open(fpath, encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue

        sl = slug(fpath)
        h = file_hash(content)

        # 캐시 확인
        if not args.force and cache.get(sl, {}).get("hash") == h:
            cached_rels = cache[sl].get("relations", [])
            for r in cached_rels:
                new_relations.append({**r, "source_note": sl, "from_cache": True})
            skipped += 1
            continue

        # frontmatter 제거 후 본문만
        body = YAML_RE.sub("", content, count=1).strip()
        if len(body) < 100:
            cache[sl] = {"hash": h, "relations": [], "ts": datetime.now().isoformat()}
            skipped += 1
            continue

        # 제목
        title_m = re.search(r"^title\s*:\s*(.+)", content, re.MULTILINE)
        title = title_m.group(1).strip().strip('"').strip("'") if title_m else os.path.splitext(os.path.basename(fpath))[0]

        prompt = PROMPT_TEMPLATE.format(title=title, body=body[:4000])

        try:
            triples = llm_call(prompt)
            rels = []
            for t in triples:
                if not isinstance(t, dict): continue
                if not all(k in t for k in ("subject", "predicate", "object")): continue
                rels.append({
                    "subject":   str(t["subject"]).strip(),
                    "predicate": str(t["predicate"]).strip(),
                    "object":    str(t["object"]).strip(),
                    "confidence": float(t.get("confidence", 0.7)),
                })
            cache[sl] = {"hash": h, "relations": rels, "ts": datetime.now().isoformat()}
            for r in rels:
                new_relations.append({**r, "source_note": sl, "from_cache": False})
            processed += 1
            if processed % 10 == 0:
                save_cache(cache)
                print(f"  [{processed}/{len(md_files)}] 진행 중...")
        except Exception as e:
            failed += 1
            print(f"  ❌ {sl}: {e}")

    save_cache(cache)

    # 결과 저장
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "provider": args.provider,
            "stats": {
                "total_notes": len(md_files),
                "processed":   processed,
                "skipped_cache": skipped,
                "failed":      failed,
                "relations":   len(new_relations),
            },
            "relations": new_relations,
        }, f, ensure_ascii=False, indent=2)

    print(f"\n결과:")
    print(f"  처리:   {processed}개 노트")
    print(f"  캐시:   {skipped}개 (스킵)")
    print(f"  실패:   {failed}개")
    print(f"  관계:   {len(new_relations)}개 트리플")
    print(f"  출력:   {OUT_PATH}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
