"""
Lint 보고서의 죽은 링크 중 자동 처리 가능한 것을 일괄 수정한다.

처리 종류:
  1. PLACEHOLDER  — 의미 없는 분류 링크. 평문(또는 '#태그')으로 변환.
                    ex) `[[이름미상]]`, `[[{이름}]]`, `[[독립운동가]]`
  2. REDIRECT     — 같은 실체의 다른 이름. 정식 노트명으로 변환.
                    ex) `[[청주공립농업학교]]` → `[[청주농업고등학교]]`
  3. NORMALIZE    — 점·공백 표기 통일.
                    ex) `[[3.1운동]]` → `[[3·1운동]]`

각 항목은 정확한 매칭만 적용 (대소문자 구분, 부분문자 X).
"""
from __future__ import annotations
import argparse
import re
from collections import Counter
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]

EXCLUDE_TOP_DIRS = {'00-원자료', '99-attachments', '_가이드', '08-스냅샷', '.obsidian'}

# 1) Placeholder → 평문 (또는 빈 문자열)
PLACEHOLDERS = {
    '이름미상': '이름 미상',
    '이름 미상': '이름 미상',
    '{이름}': '',
    '{관련인물1}': '',
    '{관련인물2}': '',
    '항일독립투사': '항일 독립투사',
    '독립운동가': '독립운동가',
    '항일독립운동가': '항일 독립운동가',
    '항일 독립운동가': '항일 독립운동가',
    '학생독립운동': '학생 독립운동',
    '학생독립운동가': '학생 독립운동가',
    '학생 항일 독립운동가': '학생 항일 독립운동가',
    '학생 항일 운동가': '학생 항일 운동가',
    '학생 항일운동': '학생 항일 운동',
    '학생 항일 투쟁 인물': '학생 항일 투쟁 인물',
    '청주공립농업학교 학생들': '청주공립농업학교 학생들',
    '청주공립농업학교 학생': '청주공립농업학교 학생',
    '청주고등보통학교 학생들': '청주고등보통학교 학생들',
    '청주고등보통학교 학생': '청주고등보통학교 학생',
    '청주고등여학교 학생': '청주고등여학교 학생',
    '청천공립보통학교 학생들': '청천공립보통학교 학생들',
    '동맹휴교 및 만세 투쟁 참여 학생': '동맹휴교·만세 투쟁 참여 학생',
    '김씨': '김씨',
    '친일반민족행위진상규명_보고서': '친일반민족행위진상규명 보고서',
}

# 2) Redirect 정식 노트로 매핑
REDIRECTS = {
    '청주공립농업학교': '청주농업고등학교',
    '청남초등학교': '청주_청남초등학교',
    '청남학교': '청주_청남초등학교',
    '청주공립농업학교 학생들': '청주농업고등학교',
    '청주공립농업학교 학생': '청주농업고등학교',
    '청주고등보통학교': '청주중고등학교',
    '청주고등보통학교 학생들': '청주중고등학교',
    '청주고등보통학교 학생': '청주중고등학교',
    '청주고등여학교 학생': '청주고등여학교',
    '청천공립보통학교': '괴산_청천초등학교',
    '청천공립보통학교 학생들': '괴산_청천초등학교',
    '용원학당': '충주_용원학당',
    '제천 동명초등학교': '제천_동명초등학교',
    '제천공립보통학교': '제천_동명초등학교',
    '괴산공립보통학교': '괴산_명덕초등학교',
    '유흥식': '류자명',
    '광주학생항일운동': '광주학생운동',
    '광주 학생 항일 운동': '광주학생운동',
    '주정 이갑': '이갑',
    '충북 학생 항일 독립투쟁사': '충북_학생_항일독립투쟁_개요',
}

# 3) 표기 정규화 — 가운뎃점·공백
NORMALIZE = {
    '3.1운동': '3·1운동',
    '3·1 운동': '3·1운동',
    '3.1 운동': '3·1운동',
    '6.10만세운동': '6·10만세운동',
    '6·10 만세운동': '6·10만세운동',
}

LINK_RE = re.compile(r'\[\[([^\[\]\n|#]+?)(\|[^\[\]\n]+?)?\]\]')


def collect_md_files() -> list[Path]:
    files: list[Path] = []
    for p in VAULT_ROOT.rglob('*.md'):
        rel = p.relative_to(VAULT_ROOT)
        if not rel.parts or rel.parts[0] in EXCLUDE_TOP_DIRS:
            continue
        files.append(p)
    return files


def existing_notes() -> set[str]:
    return {p.stem for p in collect_md_files()}


def transform_link(target: str, alias_part: str | None,
                   have: set[str]) -> tuple[str, str]:
    """
    Returns (replacement_text, kind) where kind ∈
    {'placeholder', 'redirect', 'normalize', 'keep'}.
    """
    t = target.strip()
    if t in NORMALIZE and NORMALIZE[t] in have:
        new = NORMALIZE[t]
        return f'[[{new}]]', 'normalize'
    if t in REDIRECTS and REDIRECTS[t] in have:
        new = REDIRECTS[t]
        return f'[[{new}]]', 'redirect'
    if t in PLACEHOLDERS:
        plain = PLACEHOLDERS[t]
        return plain, 'placeholder'
    return f'[[{target}{alias_part or ""}]]', 'keep'


def process(text: str, have: set[str]) -> tuple[str, Counter]:
    counter: Counter = Counter()

    def sub(m: re.Match) -> str:
        target = m.group(1)
        alias_part = m.group(2)
        new, kind = transform_link(target, alias_part, have)
        counter[kind] += 1
        return new

    new_text = LINK_RE.sub(sub, text)
    return new_text, counter


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    files = collect_md_files()
    have = {p.stem for p in files}
    grand: Counter = Counter()
    changed = 0
    for fp in files:
        text = fp.read_text(encoding='utf-8')
        new_text, c = process(text, have)
        # 'keep'은 변화 없음. 변경 발생 케이스만 카운트
        meaningful = sum(c[k] for k in ['placeholder', 'redirect', 'normalize'])
        if meaningful and new_text != text:
            if not args.dry_run:
                fp.write_text(new_text, encoding='utf-8')
            changed += 1
            for k in ['placeholder', 'redirect', 'normalize']:
                grand[k] += c[k]

    print(f'스캔 노트: {len(files)}')
    print(f'변경 파일: {changed}{" (DRY)" if args.dry_run else ""}')
    print(f'  - placeholder 평문화: {grand["placeholder"]}')
    print(f'  - redirect → 정식 노트: {grand["redirect"]}')
    print(f'  - 표기 정규화: {grand["normalize"]}')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
