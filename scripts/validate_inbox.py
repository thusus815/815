"""
_inbox/대기/ 폴더의 신규 자료를 자동 검증.

검사 항목:
  1. 필수 frontmatter 필드 존재
  2. source_url 도메인 화이트리스트
  3. 기존 노트와 중복 검사 (제목 정규화 매칭)
  4. 형식·인코딩 검사

결과:
  통과 → _inbox/승인됨/ 으로 이동
  실패 → _inbox/거부됨/ 으로 이동, 사유 _검증결과.md 생성

GitHub Actions에서 push 시 자동 실행.
종료코드: 통과만 있으면 0, 실패 1개라도 있으면 1
"""
import os, re, sys, io, json, shutil, argparse, unicodedata
from urllib.parse import urlparse
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

VAULT_DEFAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
parser = argparse.ArgumentParser()
parser.add_argument("--vault", default=VAULT_DEFAULT)
parser.add_argument("--no-move", action="store_true", help="이동 없이 검사만")
args = parser.parse_args()

VAULT = args.vault
INBOX_PENDING  = os.path.join(VAULT, "_inbox", "대기")
INBOX_APPROVED = os.path.join(VAULT, "_inbox", "승인됨")
INBOX_REJECTED = os.path.join(VAULT, "_inbox", "거부됨")
EXCLUDE_FROM_DUPE = {"_inbox", "00-원자료", "99-attachments", "08-스냅샷", ".obsidian", ".git", ".github", "scripts"}

REQUIRED_FIELDS = {
    "title": "제목 (frontmatter)",
    "tags": "태그",
    "source_type": "자료 종류",
    "source_url": "출처 URL",
    "source_reliability": "신뢰도 등급",
    "submitted_by": "제출자",
}

WHITELIST_DOMAINS = {
    "e-gonghun.mpva.go.kr",
    "theme.archives.go.kr",
    "www.archives.go.kr",
    "archives.go.kr",
    "db.history.go.kr",
    "people.aks.ac.kr",
    "encykorea.aks.ac.kr",
    "www.law.go.kr",
    "law.go.kr",
    "newslibrary.naver.com",
    "www.kjha.co.kr",
    "kjha.co.kr",
}

VALID_RELIABILITY = {"●●●", "●●○", "●○○", "○○○"}

YAML_RE = re.compile(r'^---\s*\n(.*?)\n---', re.DOTALL)

def parse_frontmatter(content):
    m = YAML_RE.match(content)
    if not m:
        return None
    yaml_text = m.group(1)
    fields = {}
    for line in yaml_text.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        m2 = re.match(r"^([\w\-]+)\s*:\s*(.*)$", line)
        if m2:
            k, v = m2.group(1), m2.group(2).strip()
            v = v.strip('"').strip("'")
            fields[k] = v
    return fields

def normalize_title(s):
    s = unicodedata.normalize("NFC", s or "")
    s = re.sub(r"[\s_\-\(\)\[\]]+", "", s)
    return s.lower()

def list_existing_titles(vault):
    """메인 폴더(인큐베이션 제외)의 모든 .md 제목을 정규화하여 반환"""
    titles = set()
    for root, dirs, files in os.walk(vault):
        rel = os.path.relpath(root, vault).split(os.sep)[0]
        if rel in EXCLUDE_FROM_DUPE:
            continue
        for f in files:
            if not f.endswith(".md"):
                continue
            base = os.path.splitext(f)[0]
            titles.add(normalize_title(base))
    return titles

def validate_one(fpath, existing_titles):
    """한 파일 검증. (ok, reasons, fields) 반환"""
    reasons = []
    try:
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return False, [f"파일 읽기 실패: {e}"], None

    fields = parse_frontmatter(content)
    if not fields:
        return False, ["frontmatter(--- ... ---) 블록이 없습니다"], None

    # 1. 필수 필드
    for k, label in REQUIRED_FIELDS.items():
        if k not in fields or not fields[k]:
            reasons.append(f"필수 필드 누락: `{k}` ({label})")

    # 2. URL 도메인
    url = fields.get("source_url", "")
    if url:
        try:
            host = urlparse(url).hostname or ""
            host = host.lower()
            if host not in WHITELIST_DOMAINS:
                # 신뢰도 ○○○ 면 허용
                rel = fields.get("source_reliability", "")
                if rel != "○○○":
                    reasons.append(f"미신뢰 도메인: `{host}` (신뢰도를 ○○○로 명시하면 통과)")
        except Exception as e:
            reasons.append(f"URL 형식 오류: {e}")

    # 3. 신뢰도 등급
    rel = fields.get("source_reliability", "")
    if rel and rel not in VALID_RELIABILITY:
        reasons.append(f"신뢰도 값 오류: `{rel}` (●●● / ●●○ / ●○○ / ○○○ 중 하나)")

    # 4. 중복 검사
    title = fields.get("title", "") or os.path.splitext(os.path.basename(fpath))[0]
    norm = normalize_title(title)
    base_norm = normalize_title(os.path.splitext(os.path.basename(fpath))[0])
    if norm in existing_titles or base_norm in existing_titles:
        reasons.append(f"기존 노트와 제목 중복 가능: `{title}`")

    # 5. 본문 길이 (너무 짧으면 거부)
    body = re.sub(YAML_RE, "", content, count=1).strip()
    if len(body) < 50:
        reasons.append(f"본문 너무 짧음 ({len(body)}자, 최소 50자)")

    return (len(reasons) == 0), reasons, fields

def main():
    if not os.path.exists(INBOX_PENDING):
        print(f"_inbox/대기/ 폴더 없음: {INBOX_PENDING}")
        return 0

    os.makedirs(INBOX_APPROVED, exist_ok=True)
    os.makedirs(INBOX_REJECTED, exist_ok=True)

    print("[1/2] 기존 제목 인덱스 작성 중...")
    existing = list_existing_titles(VAULT)
    print(f"  {len(existing)}개 메인 노트 등록")

    print("[2/2] _inbox/대기/ 검증 중...")
    files = [f for f in os.listdir(INBOX_PENDING) if f.endswith(".md") and not f.startswith("_예시")]
    if not files:
        print("  검사할 신규 파일 없음")
        return 0

    pass_n = 0
    fail_n = 0
    summary = []

    for fname in files:
        src = os.path.join(INBOX_PENDING, fname)
        ok, reasons, fields = validate_one(src, existing)
        status = "통과" if ok else "거부"
        summary.append({
            "file": fname,
            "status": status,
            "reasons": reasons,
            "submitted_by": (fields or {}).get("submitted_by", "?"),
        })

        target_dir = INBOX_APPROVED if ok else INBOX_REJECTED
        target = os.path.join(target_dir, fname)

        if not args.no_move:
            shutil.move(src, target)
            # 거부 파일 옆에 사유 기록
            if not ok:
                report_path = os.path.join(target_dir, fname.replace(".md", "_검증결과.md"))
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(f"# 검증 결과: {fname}\n\n")
                    f.write(f"- 검증 시각: {datetime.now().isoformat()}\n")
                    f.write(f"- 결과: **거부**\n\n")
                    f.write("## 사유\n\n")
                    for r in reasons:
                        f.write(f"- {r}\n")
                    f.write("\n## 수정 후 다시 _inbox/대기/ 에 올려주세요.\n")

        if ok:
            pass_n += 1
            print(f"  ✅ {fname}")
        else:
            fail_n += 1
            print(f"  ❌ {fname}")
            for r in reasons:
                print(f"      - {r}")

    print(f"\n결과: 통과 {pass_n}개, 거부 {fail_n}개")

    # JSON 요약 저장 (대시보드용)
    summary_path = os.path.join(VAULT, "_inbox", "_검증결과.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "pass": pass_n, "fail": fail_n,
            "items": summary
        }, f, ensure_ascii=False, indent=2)

    return 1 if fail_n > 0 else 0

if __name__ == "__main__":
    sys.exit(main())
