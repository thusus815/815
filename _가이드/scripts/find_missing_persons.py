"""
범용 누락 인물 발굴기.

여러 사료 폴더(07-항일학교/, 05-문헌/, 02-사건/ 등)의 본문에서
인물 신호(한자+생몰, 한자+서훈, 학생 명단)를 추출하고,
01-인물/ 전체에 노트가 없는 사람을 찾아낸다.

각 인물에 대해 출처 노트의 폴더 분류로 측면(side)을 추정한다.

사용:
  python find_missing_persons.py --strict --json out.json
  python find_missing_persons.py --dirs 07-항일학교 05-문헌 02-사건
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

VAULT_ROOT = Path(__file__).resolve().parents[2]
PERSONS_DIR = VAULT_ROOT / '01-인물'

DEFAULT_DIRS = ['07-항일학교', '05-문헌', '02-사건', '03-단체', '04-지역']

NAME_RE = r'[가-힣]{2,4}'
HANJA_RE = r'[\u3400-\u9FFF]{2,4}'
YEAR_RE = r'(?:1[7-9]\d{2}|20\d{2}|미상|\?)'
HONOR_RE = r'건국훈장|건국포장|애국장|애족장|독립장|대통령장|문화훈장|보국훈장'

P_HANJA_LIFE = re.compile(rf'({NAME_RE})\s*\(\s*({HANJA_RE})\s*,\s*({YEAR_RE})\s*[~\-–−]\s*({YEAR_RE})')
P_HANJA_HONOR = re.compile(rf'({NAME_RE})\s*\(\s*({HANJA_RE})[^)]*?(?:{HONOR_RE})')
P_HANJA_AGE = re.compile(rf'({NAME_RE})\s*\(\s*({HANJA_RE})\s*,\s*당시 만\s*\d+세')
P_TITLE_NAME = re.compile(rf'(?:참의|군수|면장|판사|검사|경부|중추원|후작|백작|자작|남작|공작|도지사|총감)\s+({NAME_RE})\s*\(\s*({HANJA_RE})')

SECTION_PATTERNS = [
    r'## 언급된 항일.*?\n(.*?)(?=\n## |\Z)',
    r'## 언급된 친일.*?\n(.*?)(?=\n## |\Z)',
    r'## 관련 인물.*?\n(.*?)(?=\n## |\Z)',
]

LIST_LINK_RE = re.compile(rf'^\s*-\s*\[\[(?:[가-힣A-Za-z]+/)?({NAME_RE})(?:\|{NAME_RE})?\]\]', re.MULTILINE)
LIST_PLAIN_RE = re.compile(rf'^\s*-\s*({NAME_RE})\s*(?:—|\(|$)', re.MULTILINE)

EXCLUDE_NAMES = {
    '항일인물', '인물', '지역', '사건', '단체', '학교', '학생', '교사', '교장', '본문', '본명', '한자',
    '독립운동', '경고문', '동맹휴학', '만세항쟁', '독립만세', '광주학생운동', '항일독립', '학생독립',
    '대본산', '조선총독부', '대한제국', '한국병합', '독립운동가', '항일투사', '독립유공자',
    '건국훈장', '건국포장', '애국장', '애족장', '독립장', '대통령장', '미서훈', '서훈자', '인명사전',
    '청주농고', '충주공보', '연도', '연관된', '관련', '기관',
    '필요', '내용', '결과', '경우', '시기', '당시', '이후', '부모',
    '청년연맹', '식산은행', '국민회', '신민회',
    '잔재물', '잔재', '친일잔재', '청산', '불망', '파묘',
}

# 출처 폴더로 side 추정
def guess_side(rel: str) -> str:
    if '01-인물/항일' in rel.replace('\\', '/'):
        return '항일'
    if '07-항일학교' in rel:
        return '항일'
    if '친일잔재' in rel or '친일' in rel:
        return '친일'
    if '02-사건' in rel:
        return '항일'  # 대부분 독립운동 사건
    return '미상'


def existing_persons() -> set[str]:
    return {p.stem for p in PERSONS_DIR.rglob('*.md')} if PERSONS_DIR.exists() else set()


def extract_section(text: str) -> str:
    chunks = []
    for pat in SECTION_PATTERNS:
        m = re.search(pat, text, re.DOTALL)
        if m:
            chunks.append(m.group(1))
    return '\n'.join(chunks)


def collect(dirs: list[Path]) -> dict[str, dict]:
    out: dict[str, dict] = defaultdict(lambda: {
        'sources': set(), 'signals': set(), 'hanja': '', 'life': '', 'honor': False,
        'side_votes': defaultdict(int),
    })

    for base in dirs:
        if not base.exists():
            continue
        for fp in base.rglob('*.md'):
            if fp.name in {'INDEX.md', '00-허브.md'}:
                continue
            try:
                text = fp.read_text(encoding='utf-8')
            except Exception:
                continue
            rel = str(fp.relative_to(VAULT_ROOT))
            side = guess_side(rel)

            sec = extract_section(text)
            if sec:
                for m in LIST_LINK_RE.finditer(sec):
                    name = m.group(1)
                    if name in EXCLUDE_NAMES:
                        continue
                    out[name]['sources'].add(rel)
                    out[name]['signals'].add('S1_section')
                    out[name]['side_votes'][side] += 1
                for m in LIST_PLAIN_RE.finditer(sec):
                    name = m.group(1)
                    if name in EXCLUDE_NAMES:
                        continue
                    out[name]['sources'].add(rel)
                    out[name]['signals'].add('S1_section')
                    out[name]['side_votes'][side] += 1

            for m in P_HANJA_LIFE.finditer(text):
                name, hanja, born, died = m.groups()
                if name in EXCLUDE_NAMES:
                    continue
                out[name]['sources'].add(rel)
                out[name]['signals'].add('S2_life')
                out[name]['hanja'] = hanja
                out[name]['life'] = f'{born}~{died}'
                out[name]['side_votes'][side] += 1

            for m in P_HANJA_AGE.finditer(text):
                name, hanja = m.groups()
                if name in EXCLUDE_NAMES:
                    continue
                out[name]['sources'].add(rel)
                out[name]['signals'].add('S2_life')
                out[name]['hanja'] = hanja
                out[name]['side_votes'][side] += 1

            for m in P_HANJA_HONOR.finditer(text):
                name, hanja = m.groups()
                if name in EXCLUDE_NAMES:
                    continue
                out[name]['sources'].add(rel)
                out[name]['signals'].add('S3_honor')
                out[name]['hanja'] = hanja
                out[name]['honor'] = True
                out[name]['side_votes'][side] += 1

            for m in P_TITLE_NAME.finditer(text):
                name, hanja = m.groups()
                if name in EXCLUDE_NAMES:
                    continue
                out[name]['sources'].add(rel)
                out[name]['signals'].add('S4_title')
                out[name]['hanja'] = hanja
                out[name]['side_votes'][side] += 1

    return {k: {
        'sources': sorted(v['sources']),
        'signals': sorted(v['signals']),
        'hanja': v['hanja'],
        'life': v['life'],
        'honor': v['honor'],
        'side': max(v['side_votes'].items(), key=lambda x: x[1])[0] if v['side_votes'] else '미상',
    } for k, v in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dirs', nargs='*', default=DEFAULT_DIRS)
    ap.add_argument('--json', dest='json_out')
    ap.add_argument('--strict', action='store_true', help='S2/S3/S4 신호 있는 것만')
    args = ap.parse_args()

    have = existing_persons()
    cands = collect([VAULT_ROOT / d for d in args.dirs])
    missing = {n: info for n, info in cands.items() if n not in have}
    if args.strict:
        missing = {n: info for n, info in missing.items()
                   if any(s.startswith(('S2', 'S3', 'S4')) for s in info['signals'])}

    print(f'스캔 폴더: {", ".join(args.dirs)}')
    print(f'전체 인물 노트: {len(have)}')
    print(f'본문 후보 인물: {len(cands)}')
    print(f'노트 누락 후보: {len(missing)}{" (--strict)" if args.strict else ""}')
    print('-' * 70)

    by_side: dict[str, list] = defaultdict(list)
    for n, info in missing.items():
        by_side[info['side']].append((n, info))

    for side in ['친일', '항일', '미상']:
        items = sorted(by_side[side], key=lambda kv: (
            0 if kv[1]['honor'] else 1,
            -len(kv[1]['sources']),
            kv[0],
        ))
        if not items:
            continue
        print(f'\n=== [{side}] {len(items)}명 ===')
        for n, info in items:
            sig = ','.join(s.split('_')[0] for s in info['signals'])
            hj = f' ({info["hanja"]})' if info['hanja'] else ''
            lf = f' [{info["life"]}]' if info['life'] else ''
            ho = ' ★서훈' if info['honor'] else ''
            print(f'  [{sig:>10}]{ho}  {n}{hj}{lf}  ({len(info["sources"])}건)')

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(missing, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\n→ {args.json_out} 저장')

    return 0


if __name__ == '__main__':
    sys.exit(main())
