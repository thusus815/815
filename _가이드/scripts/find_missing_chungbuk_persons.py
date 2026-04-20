"""
충북 학생 항일학교 노트(07-항일학교/) 본문에서 등장하는 학생·관련 인물 중
01-인물/항일/ 폴더에 노트가 없는 사람을 찾아낸다.

신호 (정밀):
  S1. "## 언급된 항일 학생 투사" 섹션 안의 단순 한글 이름 (가장 신뢰)
  S2. 본문의 "이름(한자, 생몰)" 패턴 — 예: 유석보(劉錫寶, 1906~?)
  S3. 본문의 "이름(한자, ..., 건국훈장|건국포장|애국장|애족장|독립장|대통령장)" — 서훈자
  S4. 본문의 "이름(한자, NNNN~NNNN)" 또는 "이름(한자, NNNN-NNNN)"

사용:
  python find_missing_chungbuk_persons.py             # 리포트
  python find_missing_chungbuk_persons.py --json out.json  # JSON 저장
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

VAULT_ROOT = Path(__file__).resolve().parents[2]
SCHOOL_DIR = VAULT_ROOT / '07-항일학교'
PERSONS_DIR = VAULT_ROOT / '01-인물'

NAME_RE = r'[가-힣]{2,4}'
HANJA_RE = r'[\u3400-\u9FFF]{2,4}'
YEAR_RE = r'(?:1[7-9]\d{2}|20\d{2}|미상|\?)'
HONOR_RE = r'건국훈장|건국포장|애국장|애족장|독립장|대통령장|문화훈장'

P_HANJA_LIFE = re.compile(rf'({NAME_RE})\s*\(\s*({HANJA_RE})\s*,\s*({YEAR_RE})\s*[~\-–−]\s*({YEAR_RE})')
P_HANJA_HONOR = re.compile(rf'({NAME_RE})\s*\(\s*({HANJA_RE})[^)]*?(?:{HONOR_RE})')
P_HANJA_LIFE_SIMPLE = re.compile(rf'({NAME_RE})\s*\(\s*({HANJA_RE})\s*,\s*당시 만\s*\d+세')

SECTION_PATTERNS = [
    r'## 언급된 항일 학생 투사\n(.*?)(?=\n## |\Z)',
    r'## 언급된 항일.*?\n(.*?)(?=\n## |\Z)',
]

LIST_LINK_RE = re.compile(rf'^\s*-\s*\[\[(?:항일인물/|인물/)?({NAME_RE})(?:\|{NAME_RE})?\]\]', re.MULTILINE)
LIST_PLAIN_RE = re.compile(rf'^\s*-\s*({NAME_RE})\s*(?:—|\(|$)', re.MULTILINE)

EXCLUDE_NAMES = {
    '항일인물', '인물', '지역', '사건', '단체', '학교', '학생', '교사', '교장', '본문', '본명', '한자',
    '독립운동', '경고문', '동맹휴학', '만세항쟁', '독립만세', '광주학생운동', '항일독립', '학생독립',
    '대본산', '조선총독부', '대한제국', '한국병합', '독립운동가', '항일투사', '독립유공자',
    '건국훈장', '건국포장', '애국장', '애족장', '독립장', '대통령장', '미서훈', '서훈자', '인명사전',
    '청주농고', '충주공보', '연도', '연관된', '관련', '기관',
    '필요', '내용', '결과', '경우', '시기', '당시', '이후', '부모',
}


def existing_persons() -> set[str]:
    out: set[str] = set()
    if PERSONS_DIR.exists():
        for p in PERSONS_DIR.rglob('*.md'):
            out.add(p.stem)
    return out


def extract_section(text: str, patterns: list[str]) -> str | None:
    for pat in patterns:
        m = re.search(pat, text, re.DOTALL)
        if m:
            return m.group(1)
    return None


def collect() -> dict[str, dict]:
    """인물별로 발견된 신호와 출처 모음."""
    out: dict[str, dict] = defaultdict(lambda: {
        'sources': set(), 'signals': set(), 'hanja': '', 'life': '', 'honor': False
    })

    for fp in SCHOOL_DIR.rglob('*.md'):
        if fp.name == 'INDEX.md':
            continue
        try:
            text = fp.read_text(encoding='utf-8')
        except Exception:
            continue
        rel = str(fp.relative_to(VAULT_ROOT))

        # S1: 언급된 학생 섹션
        sec = extract_section(text, SECTION_PATTERNS)
        if sec:
            for m in LIST_LINK_RE.finditer(sec):
                name = m.group(1)
                if name in EXCLUDE_NAMES:
                    continue
                out[name]['sources'].add(rel)
                out[name]['signals'].add('S1_section')
            for m in LIST_PLAIN_RE.finditer(sec):
                name = m.group(1)
                if name in EXCLUDE_NAMES:
                    continue
                out[name]['sources'].add(rel)
                out[name]['signals'].add('S1_section')

        # S2: 본문 이름(한자, 생몰)
        for m in P_HANJA_LIFE.finditer(text):
            name, hanja, born, died = m.groups()
            if name in EXCLUDE_NAMES:
                continue
            out[name]['sources'].add(rel)
            out[name]['signals'].add('S2_life')
            out[name]['hanja'] = hanja
            out[name]['life'] = f'{born}~{died}'

        # S2b: 이름(한자, 당시 만 N세)
        for m in P_HANJA_LIFE_SIMPLE.finditer(text):
            name, hanja = m.groups()
            if name in EXCLUDE_NAMES:
                continue
            out[name]['sources'].add(rel)
            out[name]['signals'].add('S2_life')
            out[name]['hanja'] = hanja

        # S3: 이름(한자, ... 서훈)
        for m in P_HANJA_HONOR.finditer(text):
            name, hanja = m.groups()
            if name in EXCLUDE_NAMES:
                continue
            out[name]['sources'].add(rel)
            out[name]['signals'].add('S3_honor')
            out[name]['hanja'] = hanja
            out[name]['honor'] = True

    return {k: {**v, 'sources': sorted(v['sources']), 'signals': sorted(v['signals'])} for k, v in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', dest='json_out', help='JSON 저장 경로')
    ap.add_argument('--strict', action='store_true', help='S2 또는 S3 신호 있는 것만 (이름 오인 거의 없음)')
    args = ap.parse_args()

    have = existing_persons()
    cands = collect()
    missing = {n: info for n, info in cands.items() if n not in have}
    if args.strict:
        missing = {n: info for n, info in missing.items()
                   if 'S2_life' in info['signals'] or 'S3_honor' in info['signals']}

    print(f'전체 인물 노트: {len(have)}')
    print(f'본문 후보 인물: {len(cands)}')
    print(f'노트 누락 후보: {len(missing)}')
    if args.strict:
        print('  (--strict: 한자+생몰/서훈 신호 있는 것만)')
    print('-' * 70)

    by_priority = sorted(missing.items(), key=lambda kv: (
        0 if kv[1]['honor'] else 1,
        0 if 'S2_life' in kv[1]['signals'] else 1,
        -len(kv[1]['sources']),
        kv[0],
    ))
    for name, info in by_priority:
        sig = ','.join(s.split('_')[0] for s in info['signals'])
        hj = f' ({info["hanja"]})' if info['hanja'] else ''
        lf = f' [{info["life"]}]' if info['life'] else ''
        ho = ' ★서훈' if info['honor'] else ''
        src_n = len(info['sources'])
        print(f'  [{sig:>10}]{ho}  {name}{hj}{lf}  ({src_n}건 출처)')
        for s in info['sources'][:2]:
            print(f'                   └ {s}')

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(missing, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'\n→ {args.json_out} 저장')

    return 0


if __name__ == '__main__':
    sys.exit(main())
