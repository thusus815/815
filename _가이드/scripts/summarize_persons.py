"""
인물 노트 일괄 요약 생성기.

각 인물 노트(`01-인물/*.md`, `01-인물/항일인물/*.md`) 맨 앞 frontmatter 직후에
`<!-- LLM-WIKI:SUMMARY:START -->` ... `<!-- LLM-WIKI:SUMMARY:END -->`
블록을 자동 삽입한다. 이 블록 안에는

  ## 한 줄 요약
  ## 핵심 행적
  ## 같은 흐름의 인물

세 섹션이 들어간다. 본문 원문은 절대 변경하지 않고, 마커 블록만 추가한다.

사용 예:

  # 1) 어떤 노트들이 처리될지 미리 보기 (API 호출 없음)
  python summarize_persons.py --dry-run

  # 2) 우선 10개만 실제 처리
  set GEMINI_API_KEY=AI...                # PowerShell: $env:GEMINI_API_KEY="AI..."
  python summarize_persons.py --execute --limit 10

  # 3) 전체 처리 (이미 요약된 노트는 자동 스킵)
  python summarize_persons.py --execute

  # 4) 모델/속도 조절
  python summarize_persons.py --execute --model gemini-2.5-flash --rate 1.5

요구 사항:
  pip install google-generativeai
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]
PERSONS_DIR = VAULT_ROOT / '01-인물'
PROMPT_FILE = VAULT_ROOT / '_가이드' / 'scripts' / 'prompts' / 'summarize_person.md'

SUMMARY_START = '<!-- LLM-WIKI:SUMMARY:START -->'
SUMMARY_END = '<!-- LLM-WIKI:SUMMARY:END -->'

DEFAULT_MODEL = 'gemini-2.5-flash'


def load_prompt() -> str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f'프롬프트 파일이 없음: {PROMPT_FILE}')
    return PROMPT_FILE.read_text(encoding='utf-8')


def has_summary(content: str) -> bool:
    return SUMMARY_START in content


def find_person_notes() -> list[Path]:
    if not PERSONS_DIR.exists():
        raise FileNotFoundError(f'인물 폴더 없음: {PERSONS_DIR}')
    return sorted(PERSONS_DIR.rglob('*.md'))


def split_frontmatter(content: str) -> tuple[str, str]:
    m = re.match(r'^(---\n.*?\n---\n)', content, re.DOTALL)
    if m:
        return content[: m.end()], content[m.end():]
    return '', content


def insert_summary(content: str, summary_body: str) -> str:
    fm, rest = split_frontmatter(content)
    block = f'\n{SUMMARY_START}\n{summary_body.strip()}\n{SUMMARY_END}\n'
    return fm + block + rest


class KeyAllExhausted(Exception):
    """모든 키가 일일 한도 도달 — 오늘은 더 이상 진행 불가."""


_KEYS_CACHE: list[str] | None = None
_KEY_LAST_CALL: dict[int, float] = {}        # idx -> last call epoch
_KEY_OK_COUNT: dict[int, int] = {}            # idx -> success count
_KEY_FAIL_COUNT: dict[int, int] = {}          # idx -> fail count
_KEY_DEAD: set[int] = set()                   # idx of keys exhausted (daily quota)
_KEY_NEXT_INDEX = 0
MIN_PER_KEY_INTERVAL = float(os.environ.get('GEMINI_MIN_INTERVAL', '0.2'))  # 키당 최소 간격(초). 무료=12, 유료=0.2 권장.

import threading
_KEY_LOCK = threading.Lock()


def _load_keys() -> list[str]:
    global _KEYS_CACHE
    if _KEYS_CACHE is not None:
        return _KEYS_CACHE
    multi = os.environ.get('GEMINI_API_KEYS', '').strip()
    if multi:
        keys = [k.strip() for k in multi.split(',') if k.strip()]
    else:
        single = os.environ.get('GEMINI_API_KEY', '').strip()
        keys = [single] if single else []
    if not keys:
        raise RuntimeError(
            'API 키가 없습니다.\n'
            '단일 키:  $env:GEMINI_API_KEY="AI..."\n'
            '여러 키:  $env:GEMINI_API_KEYS="AI...key1,AI...key2"'
        )
    _KEYS_CACHE = keys
    for i in range(len(keys)):
        _KEY_LAST_CALL[i] = 0.0
        _KEY_OK_COUNT[i] = 0
        _KEY_FAIL_COUNT[i] = 0
    print(f'[키 로딩] {len(keys)}개 키 사용 (스마트 라운드로빈, 키당 최소간격 {MIN_PER_KEY_INTERVAL:.0f}초)')
    return keys


def _short(key: str) -> str:
    return key[:8] + '…'


def _key_status(keys: list[str]) -> str:
    parts = []
    for i in range(len(keys)):
        flag = '✗' if i in _KEY_DEAD else '○'
        parts.append(f'k{i+1}{flag}({_KEY_OK_COUNT[i]}ok/{_KEY_FAIL_COUNT[i]}f)')
    return ' '.join(parts)


def _pick_next_key_idx(keys: list[str]) -> int:
    """살아있는 키 중 마지막 호출이 가장 오래 전인 것을 고른다. 동시성 안전."""
    with _KEY_LOCK:
        alive = [i for i in range(len(keys)) if i not in _KEY_DEAD]
        if not alive:
            raise KeyAllExhausted('모든 키 일일 한도 도달')
        idx = min(alive, key=lambda i: _KEY_LAST_CALL[i])
        _KEY_LAST_CALL[idx] = time.monotonic()  # 즉시 점유 (다른 스레드와 충돌 방지)
        return idx


_RETRY_DELAY_RE = re.compile(r'retry_delay\s*\{[^}]*seconds?\s*:\s*(\d+)', re.IGNORECASE)


def _parse_retry_delay(err_msg: str) -> float | None:
    m = _RETRY_DELAY_RE.search(err_msg)
    if m:
        return float(m.group(1))
    return None


def _is_daily_quota(err_msg: str) -> bool:
    """일일 한도 vs 분당 한도 구분.
    핵심 신호: retry_delay. Google이 돌려주는 retry_delay 가 절대적 진실.
    - retry_delay <= 120초: 분당 한도 — 그 시간만 기다리면 풀림
    - retry_delay > 120초:  일일 한도 — 키를 죽은 키로 표시
    metric 이름의 'PerDay' 문자열은 신뢰하지 않는다 (Google이 분당 throttle 에도 PerDay 메트릭 이름을 쓰는 경우가 관찰됨).
    """
    delay = _parse_retry_delay(err_msg)
    if delay is not None and delay > 120:
        return True
    return False


def _is_rate_limited(err_msg: str) -> bool:
    low = err_msg.lower()
    return any(s in low for s in ('429', 'quota', 'rate', 'resource_exhausted', 'exhausted'))


def call_gemini(model_name: str, prompt: str, note_text: str, max_retries: int = 6) -> str:
    """스마트 키 로테이션:
    - 키마다 최소 호출 간격(MIN_PER_KEY_INTERVAL) 강제
    - 분당 한도 시: retry_delay 만큼 대기 후 다른 키 시도
    - 일일 한도 시: 그 키 영구 스킵 (세션 끝까지)
    - 모든 키 죽으면 KeyAllExhausted 발생 → 메인 루프가 클린 종료
    """
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError(
            'google-generativeai 가 설치돼있지 않습니다.\n'
            '먼저 `pip install google-generativeai` 를 실행하세요.'
        )

    keys = _load_keys()
    full_prompt = f'{prompt}\n\n---\n# 입력 인물 노트\n\n{note_text}\n'

    last_err: Exception | None = None
    for attempt in range(max_retries):
        idx = _pick_next_key_idx(keys)
        key = keys[idx]
        try:
            genai.configure(api_key=key)
            model = genai.GenerativeModel(model_name)
            resp = model.generate_content(full_prompt)
            text = (resp.text or '').strip()
            if not text:
                raise RuntimeError('빈 응답')
            _KEY_OK_COUNT[idx] += 1
            return text
        except Exception as e:
            last_err = e
            err_msg = str(e)
            _KEY_FAIL_COUNT[idx] += 1
            if not _is_rate_limited(err_msg):
                raise
            if _is_daily_quota(err_msg):
                _KEY_DEAD.add(idx)
                print(f'  [일일한도] key={_short(key)} 영구 스킵. 상태: {_key_status(keys)}', flush=True)
                if len(_KEY_DEAD) >= len(keys):
                    raise KeyAllExhausted('모든 키 일일 한도 도달')
                continue  # try next key immediately
            delay = _parse_retry_delay(err_msg) or 8.0
            delay = min(delay + 1.0, 30.0)
            print(f'  [분당한도] key={_short(key)} {delay:.0f}초 대기 후 다른 키로', flush=True)
            time.sleep(delay)
            continue
    raise RuntimeError(f'재시도 한도 초과: {last_err}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='어떤 노트가 처리될지 보기만 (API 호출 안 함)')
    parser.add_argument('--execute', action='store_true', help='실제 API 호출하여 노트 갱신')
    parser.add_argument('--limit', type=int, default=None, help='최대 N개만 처리')
    parser.add_argument('--model', default=DEFAULT_MODEL, help=f'Gemini 모델명 (기본 {DEFAULT_MODEL})')
    parser.add_argument('--rate', type=float, default=2.0, help='직렬 모드에서 호출 사이 대기(초). 기본 2.0')
    parser.add_argument('--workers', type=int, default=1, help='동시 실행 워커 수. 유료 티어는 키 수×2 권장')
    parser.add_argument('--side', choices=['친일', '항일', 'all'], default='all',
                        help='친일=01-인물 직접만, 항일=01-인물/항일만, all=둘 다')
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
        if has_summary(content):
            skipped += 1
            continue
        todo.append(n)
        if args.limit and len(todo) >= args.limit:
            break

    print(f'후보 노트: {len(notes)}')
    print(f'이미 요약됨(스킵): {skipped}')
    print(f'읽기 실패: {errored}')
    print(f'이번에 처리할 대상: {len(todo)}')

    if args.dry_run:
        print('\n--- 처리 대상 미리보기 (최대 30개) ---')
        for p in todo[:30]:
            print(f'  - {p.relative_to(VAULT_ROOT)}')
        if len(todo) > 30:
            print(f'  ... 그리고 {len(todo) - 30}개 더')
        return 0

    prompt = load_prompt()
    ok, ng = 0, 0
    keys = _load_keys()
    started_at = time.monotonic()
    early_stop = False

    if args.workers <= 1:
        for i, p in enumerate(todo, 1):
            rel = p.relative_to(VAULT_ROOT)
            try:
                content = p.read_text(encoding='utf-8')
                summary = call_gemini(args.model, prompt, content)
                new_content = insert_summary(content, summary)
                p.write_text(new_content, encoding='utf-8')
                ok += 1
                elapsed_min = (time.monotonic() - started_at) / 60
                print(f'[{i:>4}/{len(todo)}] OK  {rel}  | {_key_status(keys)} | {elapsed_min:.1f}분', flush=True)
            except KeyAllExhausted:
                print('\n[중단] 모든 키 일일 한도 도달. 세션 종료.', flush=True)
                early_stop = True
                break
            except Exception as e:
                ng += 1
                print(f'[{i:>4}/{len(todo)}] ERR {rel} -> {e}', file=sys.stderr, flush=True)
            time.sleep(args.rate)
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from threading import Lock
        counter_lock = Lock()
        progress = {'done': 0, 'ok': 0, 'ng': 0, 'stop': False}
        total = len(todo)

        def work(p: Path) -> tuple[Path, str | None, Exception | None]:
            try:
                content = p.read_text(encoding='utf-8')
                summary = call_gemini(args.model, prompt, content)
                new_content = insert_summary(content, summary)
                p.write_text(new_content, encoding='utf-8')
                return (p, 'ok', None)
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
                        ok = progress['ok']
                        elapsed_min = (time.monotonic() - started_at) / 60
                        rate = ok / elapsed_min if elapsed_min > 0 else 0
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
        ok = progress['ok']
        ng = progress['ng']
        early_stop = progress['stop']

    print(f'\n완료. 성공 {ok}, 실패 {ng}, 스킵 {skipped}')
    print(f'키별 통계: {_key_status(keys)}')
    if early_stop:
        print('남은 노트가 있습니다. 24시간 후 같은 명령을 다시 실행하세요.')
        return 3
    return 0 if ng == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
