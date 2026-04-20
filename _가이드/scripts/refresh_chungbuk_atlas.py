"""
충북 11개 시·군 지역 노트의 Dataview 쿼리를 새 폴더 구조(01-인물)에 맞춰 갱신.
출생지·본적 frontmatter (Phase 1 추출)도 활용.
"""
from __future__ import annotations
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[2]
REGION_DIR = VAULT_ROOT / '04-지역'

CHUNGBUK_CITIES = [
    '청주시', '충주시', '제천시',
    '보은군', '옥천군', '영동군',
    '진천군', '괴산군', '음성군', '단양군', '증평군',
]

# 핵심 학교/사건 메모 (충북 학생 항일 독립투쟁사 1부에서 파악)
CITY_LANDMARKS = {
    '청주시': [
        '청주공립농업학교 (현 청주농업고) — 1919.3.9 충북 학생 만세항쟁의 시작',
        '청주 내수공립보통학교 — 1919.4.2 한봉수 의병장과 만세시위, 1921 일본인 교사 배척 동맹휴학',
    ],
    '충주시': [
        '충주공립보통학교 부설 충주간이농업학교 — 1919.4.8 유석보·오언영·장천석 만세항쟁',
        '충주 신니면 용원장터 — 1919.4.1 단경옥·이강렴 만세항쟁',
    ],
    '제천시': [
        '제천공립보통학교 (현 동명초) — 1926.6.11 6·10 만세항쟁 맹휴, 박육경 등 6명 체포 (전교 432명 중 399명 참여)',
    ],
    '보은군': [],
    '옥천군': [
        '옥천공립보통학교 (현 죽향초) — 1919.3.20 교실 앞 바위에 혈서 "독립만세"',
    ],
    '영동군': [
        '영동공립보통학교 (현 영동초) — 1919.3.29 이흥연·이성주 목판 시위, 1926.4.30 6·10 만세항쟁 시작',
    ],
    '진천군': [
        '진천공립보통학교 (현 상산초) — 1919.3.15 만세시위, 22명 체포 14명 구속',
    ],
    '괴산군': [
        '괴산공립보통학교 (현 명덕초) — 1919.3.19 충북 최초의 만세항쟁, 곽용순 등 15명 체포',
        '괴산청안공립보통학교 (현 청안초) — 1919.3.20 만세항쟁 계획 발각, 7명 체포',
        '괴산공립보통학교 — 1925.10 조선민족 멸시 교장 배척 맹휴',
    ],
    '음성군': [],
    '단양군': [],
    '증평군': [
        '증평 도안공립보통학교 — 1926 일본인 교장 배척 맹휴',
    ],
}


def render(city: str, prov: str = '충청북도') -> str:
    landmarks = CITY_LANDMARKS.get(city, [])
    landmarks_md = ''
    if landmarks:
        landmarks_md = '## 주요 거점·사건\n\n' + '\n'.join(f'- {x}' for x in landmarks) + '\n\n'

    yaml_type = '시' if city.endswith('시') else '군'

    return f'''---
지역명: {city}
유형: {yaml_type}
상위지역: {prov}
분류: 지역
tags: [지역, {yaml_type}, {city}]
생성일: 2026-04-15
source: 친일반민족행위진상규명_보고서
type: 지역
---

# {city}

상위 지역: [[{prov}]]

{landmarks_md}## 출신 인물 (출생지·본적 기준)

```dataview
TABLE 출생지, 본적, side, 작위
FROM "01-인물"
WHERE contains(출생지, "{city}") OR contains(본적, "{city}")
   OR contains(출생지, "{city.rstrip("시군")}") OR contains(본적, "{city.rstrip("시군")}")
SORT side ASC, file.name ASC
LIMIT 100
```

## 본문에 "{city}" 언급된 노트

```dataview
TABLE side
FROM "01-인물"
WHERE contains(file.content, "{city}") OR contains(file.content, "{city.rstrip("시군")}")
SORT file.name ASC
LIMIT 50
```

## 관련 항일학교·사건 노트

```dataview
LIST
FROM "07-항일학교" OR "02-사건"
WHERE contains(file.content, "{city.rstrip("시군")}")
SORT file.name ASC
LIMIT 30
```
'''


def main() -> int:
    updated = 0
    for city in CHUNGBUK_CITIES:
        p = REGION_DIR / f'{city}.md'
        new = render(city)
        if p.exists():
            old = p.read_text(encoding='utf-8')
            if old.strip() == new.strip():
                continue
        p.write_text(new, encoding='utf-8')
        print(f'  ✓ {city}.md')
        updated += 1
    print(f'\n갱신 완료: {updated}건')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
