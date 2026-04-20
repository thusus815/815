---
title: 제출 템플릿 안내
tags: [가이드]
---

# Obsidian Web Clipper 제출 템플릿

## 사용법

### 1. Web Clipper 설치
- Chrome/Edge: https://chromewebstore.google.com/detail/obsidian-web-clipper
- Firefox: https://addons.mozilla.org/firefox/addon/obsidian-web-clipper/

### 2. 템플릿 가져오기

방법 A — 파일에서:
1. Web Clipper 확장 아이콘 → ⚙ 설정
2. Templates → "Import" 클릭
3. `templates/WebClipper_제출용.json` 선택
4. "815 아카이브 제출" 템플릿 활성화

방법 B — 직접 입력:
1. Templates → "+ New template"
2. 이름: `815 아카이브 제출`
3. 아래 필드 추가:
   ```
   title              → {{title}}
   tags               → 인물, 항일
   source_type        → 신문기사 (수정 가능)
   source_url         → {{url}}
   source_date        → {{date}}
   source_reliability → ●●○
   submitted_by       → 당신이름
   ```
4. Path: `_inbox/대기`
5. Note name: `{{date|date:'YYYYMMDD'}}_{{title|safeName}}`

### 3. 자료가 있는 페이지에서 클립
1. 출처 페이지 열기 (국가기록원, 공훈전자사료관 등)
2. Web Clipper 아이콘 클릭 → "815 아카이브 제출" 템플릿 선택
3. 필드 확인·수정
4. **Save** → 자동으로 `_inbox/대기/`에 저장됨

### 4. GitHub에 푸시
- Obsidian Sync 사용 시: 자동 동기화
- 수동: PowerShell에서 `git add . && git commit -m "Add submission" && git push`

### 5. 자동 검증 결과 확인
- GitHub Actions가 자동 실행 (1~2분)
- 통과: `_inbox/승인됨/` 으로 이동
- 거부: `_inbox/거부됨/` 으로 이동, `_검증결과.md` 확인

---

## 필드 설명

자세한 내용은 [[_inbox/README]] 참고.
