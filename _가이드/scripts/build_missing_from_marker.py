"""
linkify_school_persons.py 가 [[이름]] ❓ 마커로 표시한
노트 없는 인물을 generate_missing_persons.py 입력 JSON으로 변환.

각 인물의 sources는 ❓ 마커가 붙은 학교 노트 경로.
"""
from __future__ import annotations
import json
import re
from collections import defaultdict
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]
SCHOOLS_DIR = VAULT_ROOT / '07-항일학교'
OUT = VAULT_ROOT / '_가이드' / 'scripts' / 'missing_from_schools.json'

MARKER_RE = re.compile(r'\[\[([가-힣]{2,4})\]\]\s*❓')


def main() -> None:
    out: dict[str, dict] = defaultdict(lambda: {
        'sources': set(), 'signals': ['S1_section'], 'hanja': '',
        'life': '', 'honor': False, 'side': '항일',
    })
    for fp in sorted(SCHOOLS_DIR.glob('*.md')):
        text = fp.read_text(encoding='utf-8')
        rel = str(fp.relative_to(VAULT_ROOT))
        for m in MARKER_RE.finditer(text):
            out[m.group(1)]['sources'].add(rel)

    serial = {n: {**v, 'sources': sorted(v['sources'])} for n, v in out.items()}
    OUT.write_text(json.dumps(serial, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'{len(serial)}명 → {OUT}')


if __name__ == '__main__':
    main()
