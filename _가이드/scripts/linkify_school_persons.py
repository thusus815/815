"""
07-항일학교/ 의 모든 학교 노트에서
"언급된 항일 학생 투사" / "언급된 친일반민족행위자" 섹션의 인물 항목을
일관된 위키링크로 변환한다.

규칙
- ` - 강혁선`         → ` - [[강혁선]] ❓` (노트 없음)
- ` - 강혁선`         → ` - [[강혁선]]` (노트 있음)
- ` - [[인물/이성근|이성근]]`        → ` - [[이성근]]` (vault 폴더가 인물/이 아니므로 prefix 제거)
- ` - [[이성근]] - 설명`             → 그대로
- ` - 강혁선 (姜赫善)`              → ` - [[강혁선]] (姜赫善)`
- ` - 강혁선 — 설명`                → ` - [[강혁선]] — 설명`

❓ 마커는 인물 노트가 아직 없는 경우 — 향후 발굴 대상 식별용.
"""
from __future__ import annotations
import argparse
import re
import sys
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]
SCHOOLS_DIR = VAULT_ROOT / '07-항일학교'
PERSONS_ROOT = VAULT_ROOT / '01-인물'

NAME = r'[가-힣]{2,4}'

# 처리 대상 섹션
SECTION_TITLES = [
    '언급된 항일 학생 투사',
    '언급된 친일반민족행위자',
    '언급된 친일반민족행위자 (가해자)',
    '관련 인물',
]

# 라인 패턴
PLAIN_LIST = re.compile(rf'^(\s*[-*]\s+)({NAME})(\s*(?:\(|—|-|$).*)$')
WIKI_PREFIXED = re.compile(rf'^(\s*[-*]\s+)\[\[(?:[^\]/]+/)?({NAME})(?:\|{NAME})?\]\](.*)$')


def existing_persons() -> set[str]:
    return {p.stem for p in PERSONS_ROOT.rglob('*.md')} if PERSONS_ROOT.exists() else set()


def linkify_section_body(body: str, have: set[str]) -> tuple[str, dict]:
    """섹션 본문 라인들을 위키링크화. 통계 반환."""
    stats = {'plain': 0, 'prefixed': 0, 'missing': 0}
    out_lines: list[str] = []
    for ln in body.split('\n'):
        # 기존 ❓ 마커 제거 후 재계산 (idempotent)
        ln = re.sub(r'\s*❓+', '', ln).rstrip()
        m = WIKI_PREFIXED.match(ln)
        if m:
            bullet, name, rest = m.group(1), m.group(2), m.group(3)
            mark = '' if name in have else ' ❓'
            out_lines.append(f'{bullet}[[{name}]]{rest}{mark}'.rstrip())
            stats['prefixed'] += 1
            if name not in have:
                stats['missing'] += 1
            continue
        m = PLAIN_LIST.match(ln)
        if m:
            bullet, name, rest = m.group(1), m.group(2), m.group(3)
            mark = '' if name in have else ' ❓'
            out_lines.append(f'{bullet}[[{name}]]{rest}{mark}'.rstrip())
            stats['plain'] += 1
            if name not in have:
                stats['missing'] += 1
            continue
        out_lines.append(ln)
    return '\n'.join(out_lines), stats


def find_section(text: str, title: str) -> tuple[int, int] | None:
    """## title 섹션의 본문 시작/끝 인덱스 (제목 라인 다음 ~ 다음 ## 직전)."""
    pat = re.compile(rf'^##\s+{re.escape(title)}\s*$', re.MULTILINE)
    m = pat.search(text)
    if not m:
        return None
    body_start = m.end()
    next_h = re.search(r'\n##\s+', text[body_start:])
    body_end = body_start + next_h.start() if next_h else len(text)
    return (body_start, body_end)


def process_file(fp: Path, have: set[str], dry: bool) -> dict:
    text = fp.read_text(encoding='utf-8')
    new_text = text
    total_stats = {'plain': 0, 'prefixed': 0, 'missing': 0, 'sections': 0}
    # 뒤에서 앞으로 처리하면 인덱스 안밀림
    matches: list[tuple[int, int, str]] = []
    for title in SECTION_TITLES:
        rng = find_section(new_text, title)
        if not rng:
            continue
        matches.append((*rng, title))
    matches.sort(key=lambda x: x[0], reverse=True)
    for body_start, body_end, title in matches:
        body = new_text[body_start:body_end]
        new_body, stats = linkify_section_body(body, have)
        if new_body != body:
            new_text = new_text[:body_start] + new_body + new_text[body_end:]
            total_stats['plain'] += stats['plain']
            total_stats['prefixed'] += stats['prefixed']
            total_stats['missing'] += stats['missing']
            total_stats['sections'] += 1
    if not dry and new_text != text:
        fp.write_text(new_text, encoding='utf-8')
    total_stats['changed'] = new_text != text
    return total_stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--dir', default=str(SCHOOLS_DIR))
    args = ap.parse_args()

    have = existing_persons()
    print(f'전체 인물 노트: {len(have)}')
    targets = sorted(Path(args.dir).glob('*.md'))
    print(f'학교 노트: {len(targets)}')
    print('-' * 70)

    grand = {'plain': 0, 'prefixed': 0, 'missing': 0, 'changed_files': 0}
    missing_names: dict[str, set[str]] = {}
    for fp in targets:
        if fp.name in {'INDEX.md', '00-허브.md'}:
            continue
        s = process_file(fp, have, args.dry_run)
        if s['changed']:
            grand['changed_files'] += 1
            print(f'  {"[DRY] " if args.dry_run else ""}✓ {fp.name}  '
                  f'(plain {s["plain"]}, prefixed {s["prefixed"]}, missing {s["missing"]})')
        if s['missing']:
            # 어떤 이름이 missing인지 다시 스캔 (정확)
            text = fp.read_text(encoding='utf-8')
            for title in SECTION_TITLES:
                rng = find_section(text, title)
                if not rng:
                    continue
                body = text[rng[0]:rng[1]]
                for ln in body.split('\n'):
                    for m in re.finditer(r'\[\[([가-힣]{2,4})\]\]\s*❓', ln):
                        missing_names.setdefault(m.group(1), set()).add(fp.name)
        grand['plain'] += s['plain']
        grand['prefixed'] += s['prefixed']
        grand['missing'] += s['missing']

    print('-' * 70)
    print(f'변경 파일: {grand["changed_files"]}')
    print(f'  - 평문→링크: {grand["plain"]}')
    print(f'  - prefix링크 정규화: {grand["prefixed"]}')
    print(f'  - 노트 없는 인물(❓): {grand["missing"]}')
    if missing_names:
        print(f'\n노트 없는 학생 후보 ({len(missing_names)}명):')
        for n, files in sorted(missing_names.items()):
            print(f'  - {n}  ({len(files)}건: {", ".join(sorted(files)[:3])}'
                  f'{"..." if len(files) > 3 else ""})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
