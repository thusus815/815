"""
generate_missing_persons.py 가 만든 노트의 ASSETS 블록에서
LLM이 채우지 않은 자리표시자({시기}, {주소} 등)와 빈 섹션을 정리한다.

대상: 새로 만든 14명만 (또는 --all 로 모든 항일 노트).
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]
PERSONS_DIR = VAULT_ROOT / '01-인물' / '항일'
PERSONS_ROOT = VAULT_ROOT / '01-인물'


def find_person_path(name: str) -> Path | None:
    """이름으로 노트를 항일/친일 어느 위치든 찾는다."""
    for cand in [PERSONS_DIR / f'{name}.md', PERSONS_ROOT / f'{name}.md']:
        if cand.exists():
            return cand
    matches = list(PERSONS_ROOT.rglob(f'{name}.md'))
    return matches[0] if matches else None

ASSETS_RE = re.compile(r'(<!-- LLM-WIKI:ASSETS:START -->\n)(.*?)(<!-- LLM-WIKI:ASSETS:END -->)', re.DOTALL)
PLACEHOLDER_RE = re.compile(r'\{[^}\n]+\}')


def clean_assets(block: str) -> str:
    """ASSETS 블록 내용 정리."""
    lines = block.split('\n')
    out: list[str] = []
    for ln in lines:
        # 자리표시자만으로 구성된 항목 줄 제거 (- ... {x} ... 패턴)
        if PLACEHOLDER_RE.search(ln):
            stripped = ln.strip()
            if stripped.startswith('-') or stripped.startswith('* '):
                continue
            if stripped.startswith('**') and stripped.endswith('}'):
                continue
            ln = PLACEHOLDER_RE.sub('', ln)
        # 신원 섹션의 빈 필드 (- **본관**: ) 제거
        m = re.match(r'^-\s+\*\*([가-힣A-Za-z_]+)\*\*\s*:\s*$', ln)
        if m:
            continue
        out.append(ln)
    text = '\n'.join(out)

    # 빈 ### 섹션 제거 (### 제목 + 빈 줄들 + 다음 ### 또는 끝)
    text = re.sub(
        r'\n###\s+[^\n]+\n(?:\s*\n)*(?=\n###|\n>|<!-- LLM-WIKI:ASSETS:END -->|\Z)',
        '\n', text)
    # 연속된 빈 줄 정리
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text


def process(path: Path) -> bool:
    text = path.read_text(encoding='utf-8')
    m = ASSETS_RE.search(text)
    if not m:
        return False
    head, body, tail = m.group(1), m.group(2), m.group(3)
    new_body = clean_assets(body)
    if new_body == body:
        return False
    new_text = text[:m.start()] + head + new_body + tail + text[m.end():]
    path.write_text(new_text, encoding='utf-8')
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--all', action='store_true', help='모든 항일 노트 처리')
    ap.add_argument('--names', help='쉼표 구분 이름들만')
    ap.add_argument('--from-json', help='created list 가 있는 JSON')
    args = ap.parse_args()

    if args.all:
        targets = sorted(PERSONS_ROOT.rglob('*.md'))
    elif args.names:
        targets = [find_person_path(n.strip()) or (PERSONS_DIR / f'{n.strip()}.md')
                   for n in args.names.split(',')]
    elif args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding='utf-8'))
        names = list(data.keys()) if isinstance(data, dict) else list(data)
        targets = [find_person_path(n) or (PERSONS_DIR / f'{n}.md') for n in names]
    else:
        # 기본: 누락 14명
        names = ['손병희', '이갑', '홍명희', '홍범도', '연병룡', '황학수', '김교환',
                 '장용근', '변영봉', '정진섭', '곽재기', '한봉수', '김태희', '김종부']
        targets = [find_person_path(n) or (PERSONS_DIR / f'{n}.md') for n in names]

    changed = 0
    for p in targets:
        if not p.exists():
            print(f'  ! 없음: {p.name}')
            continue
        if process(p):
            print(f'  ✓ {p.name}')
            changed += 1
    print(f'\n정리 완료: {changed}/{len(targets)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
