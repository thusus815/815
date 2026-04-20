"""
볼트 헬스 체크 (Lint).

볼트 안의 모든 위키 노트(`01-인물/...`, `02-사건/...`, `03-단체/...`,
`04-지역/...`, `05-문헌/...`, `06-서훈/...`, `07-항일학교/...`)를 스캔하여
다음을 점검한다.

  1. 죽은 링크: `[[X]]` 인데 `X.md` 가 없는 경우
  2. 동명 노트: 같은 이름이 여러 폴더에 중복 존재
  3. 요약 섹션 없는 노트 (LLM-WIKI 마커 또는 `## 한 줄 요약` 등이 없는 노트)
  4. `source` frontmatter 없는 노트
  5. 인입 링크 0개인 고립 노트

결과는 `_가이드/lint_<오늘날짜>.md` 로 저장된다.

사용법:
  python lint_vault.py
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]

# 위키 그래프에서 제외할 최상위 폴더 (메타·원자료·첨부)
EXCLUDE_TOP_DIRS = {'00-원자료', '99-attachments', '_가이드', '08-스냅샷', '.obsidian'}

LINK_RE = re.compile(r'\[\[([^\[\]\n]+?)\]\]')
SUMMARY_MARKER = '<!-- LLM-WIKI:SUMMARY:START -->'
SUMMARY_HEADINGS = ['## 한 줄 요약', '## 요약', '## 개요', '## 한줄 요약']


def collect_md_files() -> list[Path]:
    files: list[Path] = []
    for p in VAULT_ROOT.rglob('*.md'):
        rel = p.relative_to(VAULT_ROOT)
        if not rel.parts:
            continue
        if rel.parts[0] in EXCLUDE_TOP_DIRS:
            continue
        files.append(p)
    return files


def normalize_link(link: str) -> str:
    """[[지역/충청북도|충북]] 같은 형식에서 표시할 노드명만 추출."""
    target = link.split('|', 1)[0]
    target = target.split('#', 1)[0]
    target = target.strip()
    if '/' in target:
        target = target.rsplit('/', 1)[-1]
    return target


def has_summary(content: str) -> bool:
    if SUMMARY_MARKER in content:
        return True
    return any(h in content for h in SUMMARY_HEADINGS)


def has_source_frontmatter(content: str) -> bool:
    m = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
    if not m:
        return False
    fm = m.group(1)
    return bool(re.search(r'^\s*source\s*:', fm, re.MULTILINE))


def main() -> int:
    files = collect_md_files()
    if not files:
        print('스캔된 위키 노트가 없습니다.', file=sys.stderr)
        return 1

    name_to_paths: dict[str, list[Path]] = defaultdict(list)
    for p in files:
        name_to_paths[p.stem].append(p)

    duplicates = {n: ps for n, ps in name_to_paths.items() if len(ps) > 1}

    dead_per_file: dict[str, set[str]] = defaultdict(set)
    dead_count: dict[str, int] = defaultdict(int)
    incoming: dict[str, set[str]] = defaultdict(set)
    no_summary: list[str] = []
    no_source: list[str] = []

    for p in files:
        try:
            content = p.read_text(encoding='utf-8')
        except Exception as e:
            print(f'  ! 읽기실패 {p}: {e}', file=sys.stderr)
            continue
        rel = str(p.relative_to(VAULT_ROOT)).replace('\\', '/')

        if not has_summary(content):
            no_summary.append(rel)
        if not has_source_frontmatter(content):
            no_source.append(rel)

        for m in LINK_RE.finditer(content):
            link = m.group(1).strip()
            target = normalize_link(link)
            if not target:
                continue
            if target in name_to_paths:
                incoming[target].add(rel)
            else:
                dead_per_file[rel].add(target)
                dead_count[target] += 1

    orphans = [
        str(p.relative_to(VAULT_ROOT)).replace('\\', '/')
        for p in files
        if p.stem not in incoming
    ]

    today = datetime.now().strftime('%Y-%m-%d')
    out_path = VAULT_ROOT / '_가이드' / f'lint_{today}.md'

    lines: list[str] = []
    lines.append(f'---')
    lines.append(f'제목: 볼트 Lint 보고서')
    lines.append(f'생성일: {today}')
    lines.append(f'type: 가이드')
    lines.append(f'tags: [가이드, lint]')
    lines.append(f'---')
    lines.append('')
    lines.append(f'# 볼트 Lint 보고서 ({today})')
    lines.append('')
    lines.append('| 항목 | 개수 |')
    lines.append('|---|---:|')
    lines.append(f'| 전체 위키 노트 (메타 제외) | {len(files):,} |')
    lines.append(f'| 동명 노트 (중복 가능성) | {len(duplicates):,} |')
    lines.append(f'| 죽은 링크가 있는 노트 | {len(dead_per_file):,} |')
    lines.append(f'| 고유한 죽은 링크 대상 | {len(dead_count):,} |')
    lines.append(f'| 죽은 링크 총 발생 횟수 | {sum(dead_count.values()):,} |')
    lines.append(f'| 요약 섹션 없는 노트 | {len(no_summary):,} |')
    lines.append(f'| `source` frontmatter 없는 노트 | {len(no_source):,} |')
    lines.append(f'| 인입 링크 0개 (고립) 노트 | {len(orphans):,} |')
    lines.append('')

    lines.append('## 1. 가장 많이 언급된 죽은 링크 Top 100')
    lines.append('')
    lines.append('이 후보들을 새 노트로 만들면 위키 연결이 가장 크게 강화됩니다.')
    lines.append('')
    lines.append('| 링크 대상 | 언급 횟수 |')
    lines.append('|---|---:|')
    for target, cnt in sorted(dead_count.items(), key=lambda x: -x[1])[:100]:
        lines.append(f'| `[[{target}]]` | {cnt} |')
    lines.append('')

    lines.append('## 2. 동명 노트 (중복 가능성 점검 필요)')
    lines.append('')
    if not duplicates:
        lines.append('없음.')
    else:
        for name, paths in sorted(duplicates.items()):
            lines.append(f'- **{name}**')
            for p in paths:
                rel = str(p.relative_to(VAULT_ROOT)).replace("\\", "/")
                lines.append(f'  - `{rel}`')
    lines.append('')

    lines.append('## 3. 요약 섹션 없는 노트 (샘플 100)')
    lines.append('')
    lines.append('LLM 위키 임계점 ① 미달. `summarize_persons.py` 로 일괄 추가 가능.')
    lines.append('')
    for n in no_summary[:100]:
        lines.append(f'- `{n}`')
    if len(no_summary) > 100:
        lines.append(f'')
        lines.append(f'... 외 {len(no_summary) - 100:,}개 더')
    lines.append('')

    lines.append('## 4. `source` frontmatter 없는 노트 (샘플 100)')
    lines.append('')
    for n in no_source[:100]:
        lines.append(f'- `{n}`')
    if len(no_source) > 100:
        lines.append(f'')
        lines.append(f'... 외 {len(no_source) - 100:,}개 더')
    lines.append('')

    lines.append('## 5. 고립 노트 — 인입 링크 0개 (샘플 100)')
    lines.append('')
    lines.append('아무 노트도 이쪽으로 링크하지 않는 노트. 의도적 허브가 아니면 정리 대상.')
    lines.append('')
    for n in orphans[:100]:
        lines.append(f'- `{n}`')
    if len(orphans) > 100:
        lines.append(f'')
        lines.append(f'... 외 {len(orphans) - 100:,}개 더')
    lines.append('')

    lines.append('## 6. 노트별 죽은 링크 상세 (샘플 50)')
    lines.append('')
    sorted_files = sorted(dead_per_file.items(), key=lambda x: -len(x[1]))[:50]
    for fname, targets in sorted_files:
        lines.append(f'- `{fname}` — {len(targets)}개')
        for t in sorted(targets):
            lines.append(f'  - `[[{t}]]`')
    if len(dead_per_file) > 50:
        lines.append(f'')
        lines.append(f'... 외 {len(dead_per_file) - 50:,}개 노트 더')
    lines.append('')

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'리포트 생성: {out_path}')
    print(f'  - 전체 노트: {len(files):,}')
    print(f'  - 죽은 링크 종류: {len(dead_count):,} (총 {sum(dead_count.values()):,}회 등장)')
    print(f'  - 요약 누락: {len(no_summary):,}')
    print(f'  - source 누락: {len(no_source):,}')
    print(f'  - 고립 노트: {len(orphans):,}')
    print(f'  - 동명 중복: {len(duplicates):,}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
