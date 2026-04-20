"""
누락된 충북 인물 노트 자동 생성.

입력: missing_chungbuk.json (find_missing_chungbuk_persons.py --json 으로 생성)
처리:
  1. 인물별로 출처 학교 노트들의 본문을 모음 (대상 인물 이름이 등장하는 부분 ±N줄 컨텍스트)
  2. LLM에게 "이 인물 노트 1건 작성" 프롬프트 + 출처 컨텍스트 전달
  3. 결과를 01-인물/항일/{이름}.md 로 저장 (이미 있으면 스킵)
  4. 인명사전.md 끝에 부록 섹션으로 명단 추가

사용:
  python generate_missing_persons.py --execute --workers 4
  python generate_missing_persons.py --dry-run --limit 3
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from summarize_persons import call_gemini, _key_status, _load_keys, KeyAllExhausted  # type: ignore

VAULT_ROOT = Path(__file__).resolve().parents[2]
PERSONS_HANGIL_DIR = VAULT_ROOT / '01-인물' / '항일'
PERSONS_CHINIL_DIR = VAULT_ROOT / '01-인물'
PROMPT_FILE = VAULT_ROOT / '_가이드' / 'scripts' / 'prompts' / 'generate_chungbuk_person.md'
PROMPT_FILE_CHINIL = VAULT_ROOT / '_가이드' / 'scripts' / 'prompts' / 'generate_chinil_person.md'
INDEX_FILE = VAULT_ROOT / '01-인물' / '항일' / '충북_학생_항일독립운동_인명사전.md'


def target_path(name: str, side: str) -> Path:
    if side == '친일':
        return PERSONS_CHINIL_DIR / f'{name}.md'
    return PERSONS_HANGIL_DIR / f'{name}.md'

# 노이즈 제외 (한자가 잘려서 단어처럼 보이는 것)
NOISE = {'청년연맹'}


def context_for_person(name: str, source_paths: list[str], window: int = 12) -> str:
    """대상 인물 이름이 등장하는 부분 ±window 줄을 모아서 컨텍스트 작성."""
    chunks: list[str] = []
    for rel in source_paths:
        fp = VAULT_ROOT / rel
        try:
            text = fp.read_text(encoding='utf-8')
        except Exception:
            continue
        lines = text.split('\n')
        hits = [i for i, ln in enumerate(lines) if name in ln]
        if not hits:
            continue
        # merge overlapping windows
        ranges: list[tuple[int, int]] = []
        for h in hits:
            lo, hi = max(0, h - window), min(len(lines), h + window + 1)
            if ranges and lo <= ranges[-1][1]:
                ranges[-1] = (ranges[-1][0], max(ranges[-1][1], hi))
            else:
                ranges.append((lo, hi))
        for lo, hi in ranges:
            chunks.append(f'[출처: {rel} 줄 {lo+1}~{hi}]\n' + '\n'.join(lines[lo:hi]))
    return '\n\n---\n\n'.join(chunks) if chunks else ''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default=str(VAULT_ROOT / '_가이드' / 'scripts' / 'missing_chungbuk.json'))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--model', default='gemini-2.5-flash-lite')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-index-update', action='store_true', help='인명사전 부록 갱신 건너뛰기')
    ap.add_argument('--side', choices=['auto', '항일', '친일'], default='auto')
    args = ap.parse_args()

    if not args.dry_run and not args.execute:
        print('--dry-run 또는 --execute 지정', file=sys.stderr)
        return 2

    data = json.loads(Path(args.input).read_text(encoding='utf-8'))
    todo: list[tuple[str, dict]] = []
    skipped_existing = 0
    skipped_noise = 0
    skipped_no_ctx = 0
    for name, info in data.items():
        if name in NOISE:
            skipped_noise += 1
            continue
        side = args.side if args.side != 'auto' else info.get('side', '항일')
        if side == '미상':
            side = '항일'
        target = target_path(name, side)
        if target.exists() and not args.force:
            skipped_existing += 1
            continue
        ctx = context_for_person(name, info['sources'])
        if not ctx.strip():
            skipped_no_ctx += 1
            continue
        todo.append((name, {**info, 'context': ctx, 'side': side}))
        if args.limit and len(todo) >= args.limit:
            break

    print(f'입력 후보: {len(data)}')
    print(f'  - 노이즈 제외: {skipped_noise}')
    print(f'  - 이미 노트 있음: {skipped_existing}')
    print(f'  - 컨텍스트 없음: {skipped_no_ctx}')
    print(f'  - 처리 대상: {len(todo)}')

    if args.dry_run:
        for name, info in todo:
            print(f'  • {name} ({info.get("hanja","")}) — 출처 {len(info["sources"])}건, ctx {len(info["context"])}자')
        return 0

    prompt_hangil = PROMPT_FILE.read_text(encoding='utf-8')
    prompt_chinil = PROMPT_FILE_CHINIL.read_text(encoding='utf-8') if PROMPT_FILE_CHINIL.exists() else prompt_hangil
    keys = _load_keys()
    started = time.monotonic()

    from concurrent.futures import ThreadPoolExecutor, as_completed
    from threading import Lock
    lock = Lock()
    progress = {'done': 0, 'ok': 0, 'ng': 0, 'stop': False, 'created': []}
    total = len(todo)

    def work(name: str, info: dict) -> tuple[str, str, str | Exception]:
        try:
            ctx = info['context']
            side = info.get('side', '항일')
            header = (
                f'## 대상 인물 정보\n'
                f'- 이름: {name}\n'
                f'- 측면(side): {side}\n'
                f'- 한자: {info.get("hanja","(미상)")}\n'
                f'- 생몰: {info.get("life","(미상)")}\n'
                f'- 서훈자 단서: {"있음" if info.get("honor") else "없음"}\n\n'
                f'## 출처 노트 본문 발췌\n\n'
                f'{ctx}\n'
            )
            prompt = prompt_chinil if side == '친일' else prompt_hangil
            md = call_gemini(args.model, prompt, header)
            md = re.sub(r'^```(?:markdown|md)?\s*\n', '', md.strip())
            md = re.sub(r'\n```\s*$', '', md)
            target = target_path(name, side)
            target.write_text(md, encoding='utf-8')
            return (name, 'ok', '')
        except KeyAllExhausted as e:
            return (name, 'stop', e)
        except Exception as e:
            return (name, 'err', e)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(work, n, i): n for n, i in todo}
        for fut in as_completed(futures):
            name, status, err = fut.result()
            with lock:
                progress['done'] += 1
                if status == 'ok':
                    progress['ok'] += 1
                    progress['created'].append(name)
                    print(f'[{progress["done"]:>3}/{total}] OK  {name}.md  | {_key_status(keys)}', flush=True)
                elif status == 'stop':
                    progress['stop'] = True
                    print('[중단] 키 한도 도달', flush=True)
                else:
                    progress['ng'] += 1
                    print(f'[{progress["done"]:>3}/{total}] ERR {name} -> {err}', file=sys.stderr, flush=True)
            if progress['stop']:
                for f in futures:
                    f.cancel()
                break

    elapsed = (time.monotonic() - started) / 60
    print(f'\n완료: 성공 {progress["ok"]}, 실패 {progress["ng"]} ({elapsed:.1f}분)')

    # 인명사전 부록 갱신
    if not args.no_index_update and progress['created'] and INDEX_FILE.exists():
        idx_text = INDEX_FILE.read_text(encoding='utf-8')
        marker = '\n\n## 부록: 본문 등장 추가 인물 (자동 발굴)\n'
        if marker not in idx_text:
            idx_text += marker + '> 「충북 학생 항일 독립투쟁사」 1·2부 본문에서 한자명·생몰·서훈 단서로 식별되었으나 3부 인명사전에는 누락된 인물들. 본문 발췌 기반으로 자동 생성됨.\n\n'
        else:
            idx_text = idx_text.split(marker)[0] + marker + '> 「충북 학생 항일 독립투쟁사」 1·2부 본문에서 한자명·생몰·서훈 단서로 식별되었으나 3부 인명사전에는 누락된 인물들. 본문 발췌 기반으로 자동 생성됨.\n\n'
        for name in sorted(progress['created']):
            idx_text += f'- [[{name}]]\n'
        INDEX_FILE.write_text(idx_text, encoding='utf-8')
        print(f'\n인명사전 부록에 {len(progress["created"])}명 추가됨: {INDEX_FILE.name}')

    return 0 if progress['ng'] == 0 and not progress['stop'] else 1


if __name__ == '__main__':
    sys.exit(main())
