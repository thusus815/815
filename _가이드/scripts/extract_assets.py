"""
인물 노트에서 주소·재산·신분 메타데이터 추출.

각 인물 노트에 다음을 추가한다:
1. 본문에 마커 블록:
     <!-- LLM-WIKI:ASSETS:START -->
     ## 주소·재산 정보 (사료 추출)
     ... 가독성 좋은 마크다운 ...
     <!-- LLM-WIKI:ASSETS:END -->
2. frontmatter에 핵심 필드 병합 (Dataview 쿼리용):
     본관, 본적, 출생지, 사망지, 작위, 은사금_총액

병렬 처리·키 로테이션·rate limit 처리 인프라는 summarize_persons.py 와 동일.

사용 예:

  $env:GEMINI_API_KEYS="key1,key2,key3,key4"
  python extract_assets.py --execute --workers 8

  # 특정 인물만 (테스트)
  python extract_assets.py --execute --limit 5

  # 이미 추출된 노트도 강제 재추출
  python extract_assets.py --execute --force --limit 3
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

# summarize_persons.py 의 LLM 호출/키관리/병렬 인프라 재사용
sys.path.insert(0, str(Path(__file__).parent))
from summarize_persons import (  # type: ignore
    call_gemini,
    KeyAllExhausted,
    _key_status,
    _load_keys,
)

VAULT_ROOT = Path(__file__).resolve().parents[2]
PERSONS_DIR = VAULT_ROOT / '01-인물'
PROMPT_FILE = VAULT_ROOT / '_가이드' / 'scripts' / 'prompts' / 'extract_assets.md'

ASSETS_START = '<!-- LLM-WIKI:ASSETS:START -->'
ASSETS_END = '<!-- LLM-WIKI:ASSETS:END -->'

DEFAULT_MODEL = 'gemini-2.5-flash-lite'

# frontmatter 에 병합할 핵심 필드 (Dataview 쿼리에 가장 자주 쓰일 것들)
FM_MERGE_FIELDS = [
    '본관', '본적', '출생지', '사망지',
]


def load_prompt() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f'프롬프트 파일이 없음: {PROMPT_FILE}')
    return PROMPT_FILE.read_text(encoding='utf-8')


def has_assets(content: str) -> bool:
    return ASSETS_START in content


def find_person_notes() -> list[Path]:
    if not PERSONS_DIR.exists():
        raise FileNotFoundError(f'인물 폴더 없음: {PERSONS_DIR}')
    return sorted(PERSONS_DIR.rglob('*.md'))


def split_frontmatter(content: str) -> tuple[str, str]:
    m = re.match(r'^(---\n.*?\n---\n)', content, re.DOTALL)
    if m:
        return content[: m.end()], content[m.end():]
    return '', content


def parse_yaml_simple(yaml_text: str) -> dict:
    """간단한 YAML 파서. assets 추출 결과(평탄한 키 + 리스트)만 처리.
    PyYAML 의존 안 하기 위함. 완벽 X — 가독성 좋은 출력 생성용."""
    # 코드 펜스 제거
    yaml_text = re.sub(r'^```(?:yaml)?\s*\n', '', yaml_text.strip())
    yaml_text = re.sub(r'\n```\s*$', '', yaml_text)
    out: dict = {}
    cur_key: str | None = None
    cur_list: list | None = None
    cur_obj: dict | None = None
    for raw in yaml_text.split('\n'):
        line = raw.rstrip()
        if not line.strip():
            continue
        # 최상위 키
        m = re.match(r'^([가-힣A-Za-z_][가-힣A-Za-z_0-9]*)\s*:\s*(.*)$', line)
        if m and not line.startswith(' ') and not line.startswith('\t'):
            # 직전 객체 마무리
            if cur_obj is not None and cur_list is not None:
                cur_list.append(cur_obj)
                cur_obj = None
            cur_key = m.group(1)
            val = m.group(2).strip()
            if val == '' or val == '[]':
                if val == '[]':
                    out[cur_key] = []
                    cur_list = None
                else:
                    out[cur_key] = []
                    cur_list = out[cur_key]
            else:
                # 인라인 값
                v = val
                if v.startswith('"') and v.endswith('"'):
                    v = v[1:-1]
                if v.startswith('[') and v.endswith(']'):
                    inner = v[1:-1].strip()
                    if not inner:
                        out[cur_key] = []
                    else:
                        items = [x.strip().strip('"') for x in inner.split(',')]
                        # 숫자만이면 int로
                        try:
                            out[cur_key] = [int(x) for x in items]
                        except ValueError:
                            out[cur_key] = items
                else:
                    out[cur_key] = v
                cur_list = None
            continue
        # 리스트 항목 시작 ( "  - ..." )
        m2 = re.match(r'^\s*-\s+([가-힣A-Za-z_][가-힣A-Za-z_0-9]*)\s*:\s*(.*)$', line)
        if m2 and cur_list is not None:
            # 새 객체 시작
            if cur_obj is not None:
                cur_list.append(cur_obj)
            cur_obj = {}
            k = m2.group(1)
            v = m2.group(2).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            cur_obj[k] = v
            continue
        # 객체 추가 필드 ( "    key: value" )
        m3 = re.match(r'^\s+([가-힣A-Za-z_][가-힣A-Za-z_0-9]*)\s*:\s*(.*)$', line)
        if m3 and cur_obj is not None:
            k = m3.group(1)
            v = m3.group(2).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            cur_obj[k] = v
            continue
        # 단순 리스트 항목 ("  - value")
        m4 = re.match(r'^\s*-\s+(.*)$', line)
        if m4 and cur_list is not None and cur_obj is None:
            v = m4.group(1).strip()
            if v.startswith('"') and v.endswith('"'):
                v = v[1:-1]
            cur_list.append(v)
            continue
    # 마지막 객체 마무리
    if cur_obj is not None and cur_list is not None:
        cur_list.append(cur_obj)
    return out


def render_assets_block(data: dict) -> str:
    """추출된 dict 를 가독성 좋은 마크다운으로."""
    lines = ['## 주소·재산 정보 (사료 추출)', '']

    # 신뢰도 표시
    conf = data.get('추출_신뢰도', '').strip() if isinstance(data.get('추출_신뢰도'), str) else ''
    if conf:
        emoji = {'high': '●●●', 'medium': '●●○', 'low': '●○○'}.get(conf.lower(), conf)
        lines.append(f'> 추출 신뢰도: {emoji}')
        lines.append('')

    def has(k: str) -> bool:
        v = data.get(k)
        if v is None:
            return False
        if isinstance(v, str):
            return v.strip() != ''
        if isinstance(v, list):
            return len(v) > 0
        return True

    # 본관·본적·출생·사망
    basic_fields = [('본관', '본관'), ('본적', '본적'), ('출생지', '출생지'),
                    ('사망지', '사망지'), ('묘소', '묘소')]
    if any(has(k) for _, k in basic_fields):
        lines.append('### 신원')
        for label, k in basic_fields:
            if has(k):
                lines.append(f'- **{label}**: {data[k]}')
        lines.append('')

    # 거주이력
    if has('거주이력'):
        lines.append('### 거주이력')
        for item in data['거주이력']:
            if isinstance(item, dict):
                t = item.get('시기', '').strip()
                a = item.get('주소', '').strip()
                if t and a:
                    lines.append(f'- **{t}**: {a}')
                elif a:
                    lines.append(f'- {a}')
        lines.append('')

    # 작위·훈장
    if has('작위_훈장'):
        lines.append('### 작위·훈장')
        for item in data['작위_훈장']:
            if isinstance(item, dict):
                name = item.get('명칭', '').strip()
                date = item.get('수여일', '').strip()
                src = item.get('근거', '').strip()
                parts = [f'**{name}**'] if name else []
                if date:
                    parts.append(f'({date})')
                if src:
                    parts.append(f'— {src}')
                if parts:
                    lines.append(f'- {" ".join(parts)}')
        lines.append('')

    # 은사금·보상
    if has('은사금_보상'):
        lines.append('### 은사금·보상')
        for item in data['은사금_보상']:
            if isinstance(item, dict):
                t = item.get('시기', '').strip()
                m = item.get('금액', '').strip()
                r = item.get('사유', '').strip()
                seg = [t, m, r]
                seg = [s for s in seg if s]
                if seg:
                    lines.append(f'- {" — ".join(seg)}')
        lines.append('')

    # 토지
    if has('토지_소유'):
        lines.append('### 토지 소유')
        for item in data['토지_소유']:
            if isinstance(item, dict):
                loc = item.get('위치', '').strip()
                area = item.get('면적', '').strip()
                t = item.get('시기', '').strip()
                memo = item.get('비고', '').strip()
                seg = [loc]
                if area:
                    seg.append(f'면적 {area}')
                if t:
                    seg.append(f'({t})')
                if memo:
                    seg.append(f'— {memo}')
                if loc:
                    lines.append(f'- {" ".join(seg)}')
        lines.append('')

    # 가옥·부동산
    if has('가옥_부동산'):
        lines.append('### 가옥·부동산')
        for item in data['가옥_부동산']:
            if isinstance(item, dict):
                loc = item.get('위치', '').strip()
                kind = item.get('종류', '').strip()
                t = item.get('시기', '').strip()
                seg = [loc]
                if kind:
                    seg.append(f'({kind})')
                if t:
                    seg.append(f'— {t}')
                if loc:
                    lines.append(f'- {" ".join(seg)}')
        lines.append('')

    # 직책·사업체
    if has('직책_사업체'):
        lines.append('### 직책·사업체')
        for item in data['직책_사업체']:
            if isinstance(item, dict):
                org = item.get('기관', '').strip()
                pos = item.get('직책', '').strip()
                t = item.get('시기', '').strip()
                seg = []
                if org:
                    seg.append(f'**{org}**')
                if pos:
                    seg.append(pos)
                if t:
                    seg.append(f'({t})')
                if seg:
                    lines.append(f'- {" ".join(seg)}')
        lines.append('')

    # 가족 관계
    if has('가족_관계'):
        lines.append('### 가족 관계')
        for item in data['가족_관계']:
            if isinstance(item, dict):
                rel = item.get('관계', '').strip()
                name = item.get('이름', '').strip()
                memo = item.get('비고', '').strip()
                seg = []
                if rel:
                    seg.append(f'**{rel}**')
                if name:
                    seg.append(f'[[{name}]]' if not name.startswith('[[') else name)
                if memo:
                    seg.append(f'— {memo}')
                if seg:
                    lines.append(f'- {" ".join(seg)}')
        lines.append('')

    # 학력
    if has('학력_교육'):
        lines.append('### 학력·교육')
        for item in data['학력_교육']:
            if isinstance(item, dict):
                org = item.get('기관', '').strip()
                t = item.get('시기', '').strip()
                seg = [org] if org else []
                if t:
                    seg.append(f'({t})')
                if seg:
                    lines.append(f'- {" ".join(seg)}')
        lines.append('')

    # 자료 쪽수
    if has('자료_쪽수'):
        pages = data['자료_쪽수']
        if isinstance(pages, list) and pages:
            lines.append(f'### 자료 인용 쪽수')
            lines.append(f'{", ".join(str(p) for p in pages)}')
            lines.append('')

    return '\n'.join(lines).rstrip() + '\n'


def merge_frontmatter(fm_text: str, extracted: dict) -> str:
    """기존 frontmatter 에 추출된 핵심 필드를 병합. 기존 값은 덮어쓰지 않음."""
    if not fm_text:
        return fm_text
    # frontmatter 의 본문 부분만 추출 (--- 사이)
    m = re.match(r'^(---\n)(.*?)(\n---\n)$', fm_text, re.DOTALL)
    if not m:
        return fm_text
    head, body, tail = m.group(1), m.group(2), m.group(3)

    additions = []
    for k in FM_MERGE_FIELDS:
        v = extracted.get(k, '')
        if not isinstance(v, str):
            continue
        v = v.strip()
        if not v:
            continue
        # 이미 있으면 스킵
        if re.search(rf'^{re.escape(k)}\s*:', body, re.MULTILINE):
            continue
        # 따옴표 처리
        if any(c in v for c in [':', '#', '[', ']', '{', '}', ',', '&', '*', '!', '|', '>', '%', '@', '`']) or v != v.strip():
            v_safe = '"' + v.replace('"', '\\"') + '"'
        else:
            v_safe = v
        additions.append(f'{k}: {v_safe}')

    # 작위 요약 (있는 경우 첫 번째 작위명만)
    if not re.search(r'^작위\s*:', body, re.MULTILINE):
        wlist = extracted.get('작위_훈장', [])
        if isinstance(wlist, list) and wlist:
            first = wlist[0]
            if isinstance(first, dict):
                name = first.get('명칭', '').strip()
                if name:
                    additions.append(f'작위: {name}')

    # 은사금 합계 표시 (있으면 첫 항목만)
    if not re.search(r'^은사금\s*:', body, re.MULTILINE):
        elist = extracted.get('은사금_보상', [])
        if isinstance(elist, list) and elist:
            first = elist[0]
            if isinstance(first, dict):
                amt = first.get('금액', '').strip()
                if amt:
                    additions.append(f'은사금: "{amt}"')

    if not additions:
        return fm_text
    new_body = body.rstrip() + '\n' + '\n'.join(additions)
    return head + new_body + tail


def insert_assets_block(content: str, block_text: str, extracted: dict) -> str:
    """본문에 ASSETS 블록 삽입 + frontmatter 병합."""
    fm, rest = split_frontmatter(content)
    fm = merge_frontmatter(fm, extracted)

    block = f'\n{ASSETS_START}\n{block_text.strip()}\n{ASSETS_END}\n'

    # 기존 SUMMARY 블록 다음, 본문 시작 전에 삽입
    summary_end_marker = '<!-- LLM-WIKI:SUMMARY:END -->'
    if summary_end_marker in rest:
        idx = rest.index(summary_end_marker) + len(summary_end_marker)
        # SUMMARY 블록 직후 줄바꿈 1개 다음에 삽입
        # 이미 줄바꿈이 있으면 그 뒤로 들어감
        before = rest[:idx]
        after = rest[idx:]
        # after 가 빈 줄로 시작하지 않으면 빈 줄 추가
        if not after.startswith('\n'):
            after = '\n' + after
        return fm + before + block + after
    else:
        # SUMMARY 블록이 없으면 frontmatter 직후
        return fm + block + rest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='어떤 노트가 처리될지 보기만')
    parser.add_argument('--execute', action='store_true', help='실제 API 호출')
    parser.add_argument('--limit', type=int, default=None, help='최대 N개만 처리')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'Gemini 모델명 (기본 {DEFAULT_MODEL})')
    parser.add_argument('--workers', type=int, default=8, help='동시 워커 수 (기본 8)')
    parser.add_argument('--force', action='store_true', help='이미 ASSETS 블록 있는 노트도 재처리')
    parser.add_argument('--side', choices=['친일', '항일', 'all'], default='all')
    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print('--dry-run 또는 --execute 중 하나를 지정하세요.', file=sys.stderr)
        return 2

    notes = find_person_notes()
    if args.side == '친일':
        notes = [n for n in notes if n.parent == PERSONS_DIR]
    elif args.side == '항일':
        notes = [n for n in notes if '항일' in n.parts]

    todo: list[Path] = []
    skipped = 0
    errored = 0
    for n in notes:
        try:
            content = n.read_text(encoding='utf-8')
        except Exception as e:
            errored += 1
            print(f'  ! 읽기실패 {n.name}: {e}', file=sys.stderr)
            continue
        if not args.force and has_assets(content):
            skipped += 1
            continue
        todo.append(n)
        if args.limit and len(todo) >= args.limit:
            break

    print(f'후보 노트: {len(notes)}')
    print(f'이미 추출됨(스킵): {skipped}')
    print(f'읽기 실패: {errored}')
    print(f'이번에 처리할 대상: {len(todo)}')

    if args.dry_run:
        print('\n--- 처리 대상 (최대 30개) ---')
        for p in todo[:30]:
            print(f'  - {p.relative_to(VAULT_ROOT)}')
        if len(todo) > 30:
            print(f'  ... 그리고 {len(todo) - 30}개 더')
        return 0

    prompt = load_prompt()
    keys = _load_keys()
    started_at = time.monotonic()

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock
    counter_lock = Lock()
    progress = {'done': 0, 'ok': 0, 'ng': 0, 'stop': False}
    total = len(todo)

    def work(p: Path) -> tuple[Path, str, str | Exception]:
        try:
            content = p.read_text(encoding='utf-8')
            yaml_out = call_gemini(args.model, prompt, content)
            data = parse_yaml_simple(yaml_out)
            block_text = render_assets_block(data)
            new_content = insert_assets_block(content, block_text, data)
            p.write_text(new_content, encoding='utf-8')
            return (p, 'ok', '')
        except KeyAllExhausted as e:
            return (p, 'stop', e)
        except Exception as e:
            return (p, 'err', e)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(work, p): p for p in todo}
        for fut in as_completed(futures):
            p, status, err = fut.result()
            rel = p.relative_to(VAULT_ROOT)
            with counter_lock:
                progress['done'] += 1
                i = progress['done']
                if status == 'ok':
                    progress['ok'] += 1
                    elapsed_min = (time.monotonic() - started_at) / 60
                    rate = progress['ok'] / elapsed_min if elapsed_min > 0 else 0
                    print(f'[{i:>4}/{total}] OK  {rel}  | {_key_status(keys)} | {elapsed_min:.1f}분 ({rate:.1f}/분)', flush=True)
                elif status == 'stop':
                    progress['stop'] = True
                    print('\n[중단] 모든 키 일일 한도 도달.', flush=True)
                else:
                    progress['ng'] += 1
                    print(f'[{i:>4}/{total}] ERR {rel} -> {err}', file=sys.stderr, flush=True)
            if progress['stop']:
                for f in futures:
                    f.cancel()
                break

    print(f'\n완료. 성공 {progress["ok"]}, 실패 {progress["ng"]}, 스킵 {skipped}')
    print(f'키별 통계: {_key_status(keys)}')
    return 0 if progress['ng'] == 0 and not progress['stop'] else 1


if __name__ == '__main__':
    sys.exit(main())
