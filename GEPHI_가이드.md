---
title: Gephi로 그래프 디자인하는 방법
tags: [가이드]
---

# Gephi로 그래프 디자인하기

> `graph.gexf`를 Gephi에서 열어 클러스터링·레이아웃·색상을 디자인하면, Sigma.js가 그 결과를 즉시 표시합니다. 한 번만 작업해두면 영구 자산입니다.

---

## 1. Gephi 설치

1. https://gephi.org/users/download/ 접속
2. **Windows 64-bit Installer** 다운로드 (~150MB)
3. 설치 (기본값으로 다음 → 다음)
4. 처음 실행 시 Java 자동 설치 알림 → 따라서 설치
5. **권장 메모리 설정** (1700개 노드는 무리 없음):
   - 설치 폴더(예: `C:\Program Files\Gephi-0.10.1\etc\`)에서 `gephi.conf` 열기
   - `default_options=` 줄에서 `-J-Xmx512m` → `-J-Xmx2048m`로 변경

---

## 2. graph.gexf 열기

```
File → Open → C:\Users\ho\Desktop\친일반민족행위진상규명_보고서\graph.gexf
```

- **Graph Type**: Undirected (기본값 그대로)
- **Append to existing workspace**: 체크 해제
- OK

→ 처음에는 노드들이 한 점에 뭉쳐 있어서 정사각형 덩어리처럼 보입니다. 정상입니다.

---

## 3. Modularity (자동 클러스터 발견) ⭐

화면 우측 **Statistics** 패널에서:

```
Modularity → Run
  Resolution: 1.0 (기본값)
  Use weights: 체크
  → Run
```

- 결과창에 "Modularity: 0.6~0.8, Communities: 12~25" 정도 나오면 좋음
- **닫지 말고 보세요**: 의미 있는 클러스터가 자동 발견됨 (예: 임정 그룹, 신민회 그룹, 친일 핵심 그룹 등)

---

## 4. 클러스터별 색칠

좌측 상단 **Appearance** 패널:

```
Nodes → Color (색칠 아이콘)
   → Partition 탭
   → 드롭다운에서 "Modularity Class" 선택
   → "Apply" 또는 "Palette..."로 색상 직접 고르기
```

→ 노드들이 클러스터별로 다른 색이 됨

**팁**: Palette → "Generate" 클릭 → "Preset: Default" → 보기 좋은 색조합 자동 생성

---

## 5. 노드 크기 조정

같은 **Appearance** 패널:

```
Nodes → Size (크기 아이콘)
   → Ranking 탭
   → 드롭다운에서 "Degree" 선택
   → Min size: 4, Max size: 30
   → Apply
```

→ 연결 많은 인물(이회영, 김구, 이완용 등)이 크게 보임

---

## 6. ForceAtlas 2 레이아웃 (핵심) ⭐

좌측 하단 **Layout** 패널:

```
드롭다운에서 "ForceAtlas 2" 선택
   설정:
   ✓ Scaling: 10
   ✓ Gravity: 1
   ✓ Prevent Overlap: 체크 (충돌 방지)
   ✓ LinLog mode: 체크 (대형 그래프용)
   ✓ Stronger Gravity: 체크 안함
   ✓ Edge Weight Influence: 1
   
   → Run 클릭
```

- 그래프가 점점 펼쳐지면서 클러스터별로 모임
- **5~10분 정도 돌리세요** (안정될 때까지)
- 만족스러우면 **Stop** 클릭

**중간 조정 팁**:
- 너무 뭉쳐있다면 → Scaling 값 키우기 (15, 20...)
- 너무 흩어졌다면 → Gravity 값 키우기 (5, 10...)
- 조정하고 다시 Run

---

## 7. 노드 라벨 켜기 (선택)

화면 하단의 **그래프 미리보기 컨트롤바**:

```
T 아이콘 (글자) → 클릭 → 라벨 ON
A → 라벨 크기 조절
```

→ 너무 빽빽하면 일단 끄고 Sigma에서 줌인 시 보이게 함

---

## 8. 결과 저장 (가장 중요)

```
File → Export → Graph file...
   파일명: graph.gexf  (덮어쓰기)
   위치:   원래 폴더 (vault 루트)
   옵션:
     ✓ Position (좌표 포함)
     ✓ Color (색상 포함)
     ✓ Size (크기 포함)
     ✓ Attributes (메타데이터 포함)
   → OK
```

---

## 9. 사이트에 반영

PowerShell에서:

```powershell
cd C:\Users\ho\Desktop\친일반민족행위진상규명_보고서
git add graph.gexf
git commit -m "Update graph layout from Gephi"
git push
```

5~8분 후 사이트에 자동 반영됩니다.

---

## 다음 작업할 때 (반복)

```
새 .md 노트 추가
   ↓
git push (자동으로 graph_data.json 재생성됨)
   ↓
로컬에서 python scripts\json_to_gexf.py 실행
   ↓
Gephi에서 graph.gexf 다시 열기
   ↓
"위치 보존하시겠습니까?" → Yes (이전 좌표 유지)
   ↓
새 노드만 추가됨 → ForceAtlas 잠깐 돌려 정리
   ↓
Export → push
```

---

## 자주 하는 작업

### 특정 클러스터만 추출
```
Filters 패널 → Attributes → Equal → Modularity Class = N
   → Apply
   → 메인 그래프에 그 클러스터만 남음
```

### 특정 인물 중심 부분 그래프
```
Filters → Topology → Ego Network → 인물 ID 입력 → depth 2
```

### 깔끔한 PNG 출력 (인쇄용)
```
File → Export → SVG/PDF/PNG file
   해상도: 4000x4000
   여백: 5%
```

---

## 문제 해결

| 증상 | 원인 | 해결 |
|---|---|---|
| 한글 깨짐 | 폰트 미설정 | Tools → Options → Appearance → 한글 폰트(맑은 고딕) 선택 |
| 너무 느림 | 메모리 부족 | gephi.conf의 -Xmx 늘리기 |
| 모듈러리티 0.3 미만 | 데이터 너무 연결됨 | Resolution을 0.5로 낮추기 (더 작은 클러스터) |
| 라벨 안 보임 | 줌 부족 | 하단 T 아이콘 + 마우스 휠로 줌인 |
