"""
각 Gemini API 키를 개별 진단.
- 현재 호출 가능한지
- 어떤 모델까지 가능한지 (flash, flash-lite, pro)
- 어떤 한도 메시지가 나오는지

GEMINI_API_KEYS 환경변수에서 콤마 구분 키들 읽음.
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime

MODELS_TO_TEST = [
    'gemini-2.5-flash-lite',
    'gemini-2.5-flash',
    'gemini-2.5-pro',
]

PROMPT = '한국어로 OK 라고 정확히 한 단어만 답해.'


def short(k: str) -> str:
    return k[:10] + '…' + k[-4:]


def test_key_model(key: str, model_name: str) -> dict:
    """단일 키-모델 조합 테스트. 결과 dict 반환."""
    import google.generativeai as genai
    out = {'model': model_name, 'success': False, 'note': '', 'retry_delay': None}
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel(model_name)
        t0 = time.monotonic()
        resp = model.generate_content(PROMPT)
        dt = time.monotonic() - t0
        text = (resp.text or '').strip()
        out['success'] = True
        out['note'] = f'OK ({dt:.1f}s) → "{text[:30]}"'
    except Exception as e:
        msg = str(e)
        out['note'] = msg[:200].replace('\n', ' ')
        # retry_delay 파싱
        import re
        m = re.search(r'retry_delay\s*\{[^}]*seconds?\s*:\s*(\d+)', msg, re.IGNORECASE)
        if m:
            out['retry_delay'] = int(m.group(1))
        # quota_value 파싱
        m2 = re.search(r'quota_value\s*:\s*(\d+)', msg)
        if m2:
            out['quota_value'] = int(m2.group(1))
        # quota_id 파싱
        m3 = re.search(r'quota_id\s*:\s*"([^"]+)"', msg)
        if m3:
            out['quota_id'] = m3.group(1)
    return out


def main() -> int:
    raw = os.environ.get('GEMINI_API_KEYS', '').strip() or os.environ.get('GEMINI_API_KEY', '').strip()
    if not raw:
        print('환경변수 GEMINI_API_KEYS 또는 GEMINI_API_KEY 가 없습니다.', file=sys.stderr)
        return 2
    keys = [k.strip() for k in raw.split(',') if k.strip()]
    print(f'\n진단 시작 ({datetime.now().strftime("%H:%M:%S")}). 키 {len(keys)}개, 모델 {len(MODELS_TO_TEST)}개\n')
    print(f'각 키-모델 조합마다 1회씩 실제 API 호출 (총 {len(keys)*len(MODELS_TO_TEST)}회). 5초 간격.\n')

    summary: list[tuple[str, str, dict]] = []

    for i, k in enumerate(keys, 1):
        sk = short(k)
        print(f'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
        print(f'키 {i}: {sk}')
        print(f'━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
        for model in MODELS_TO_TEST:
            print(f'  [{model}] 테스트 중...', end=' ', flush=True)
            result = test_key_model(k, model)
            summary.append((sk, model, result))
            if result['success']:
                print(f'✓ {result["note"]}')
            else:
                qv = result.get('quota_value')
                qid = result.get('quota_id', '')
                rd = result.get('retry_delay')
                tag = ''
                if qv is not None:
                    tag = f' [한도={qv}'
                    if rd is not None:
                        tag += f', 재시도={rd}s'
                    if qid:
                        tag += f', metric="{qid}"'
                    tag += ']'
                print(f'✗{tag}')
                print(f'      ↳ {result["note"][:160]}')
            time.sleep(5)

    print('\n\n━━━━━━━━━━ 요약 ━━━━━━━━━━\n')
    print(f'{"키":<22}{"모델":<28}{"상태":<10}{"한도":<10}{"재시도(초)":<12}')
    print('─' * 84)
    for sk, model, r in summary:
        status = '✓ OK' if r['success'] else '✗ 실패'
        qv = r.get('quota_value', '-')
        rd = r.get('retry_delay', '-')
        print(f'{sk:<22}{model:<28}{status:<10}{str(qv):<10}{str(rd):<12}')

    # 추천
    alive = [(sk, model) for sk, model, r in summary if r['success']]
    print(f'\n살아있는 키-모델 조합: {len(alive)}/{len(summary)}')
    if alive:
        print('이 조합들은 지금도 호출 가능합니다:')
        for sk, model in alive:
            print(f'  - {sk}  /  {model}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
