/**
 * 사용자 제출 이슈 → 위키 .md 변환기
 *
 * worker/src/index.ts와 dry-run 스크립트(scripts/dry_run_convert.mjs)에서 공유.
 * 워커 환경(no Node API)과 Node 환경 모두에서 동작하도록 표준 JS만 사용.
 */

export type RouteKind = '인물' | '학교' | '신문' | '판결문' | '사건' | '단체' | '지역';
export interface ConvertResult { md: string; folder: string; filename: string; kind: RouteKind; }

export function parseSection(body: string, heading: string): string {
  const re = new RegExp(`## ${heading}\\s*\\n([\\s\\S]*?)(?=\\n## |\\n---|-$)`, 'm');
  const m = body.match(re);
  return m ? m[1].trim() : '';
}

export function regionToFolder(region: string): string {
  const r = region.trim();
  if (r.includes('당진')) return '04-지역/충남/당진';
  if (r.includes('서천')) return '04-지역/충남/서천';
  if (r.includes('예산')) return '04-지역/충남/예산';
  if (r.includes('공주')) return '04-지역/충남/공주';
  if (r.includes('천안') || r.includes('아산')) return '04-지역/충남/천안';
  if (r.includes('서산')) return '04-지역/충남/서산';
  if (r.includes('홍성')) return '04-지역/충남/홍성';
  if (r.includes('논산') || r.includes('계룡')) return '04-지역/충남/논산';
  if (r.includes('금산')) return '04-지역/충남/금산';
  if (r.includes('부여')) return '04-지역/충남/부여';
  if (r.includes('청양')) return '04-지역/충남/청양';
  if (r.includes('태안')) return '04-지역/충남/태안';
  if (r.includes('충남') || r.includes('충청남도')) return '04-지역/충남';
  if (r.includes('세종') || r.includes('조치원') || r.includes('연기군')) return '04-지역/세종';
  if (r.includes('청주')) return '04-지역/충북/청주';
  if (r.includes('충주')) return '04-지역/충북/충주';
  if (r.includes('제천')) return '04-지역/충북/제천';
  if (r.includes('충북') || r.includes('충청북도')) return '04-지역/충북';
  if (r.includes('서울') || r.includes('경성')) return '04-지역/서울';
  if (r.includes('인천')) return '04-지역/인천';
  if (r.includes('광주')) return '04-지역/광주';
  if (r.includes('대전')) return '04-지역/대전';
  if (r.includes('제주')) return '04-지역/제주';
  if (r.includes('강원')) return '04-지역/강원';
  return '04-지역/미분류';
}

export function detectNewspaper(text: string): string | null {
  const papers = ['매일신보', '경성일보', '동아일보', '조선일보', '시대일보', '중외일보', '조선중앙일보', '한겨레'];
  for (const p of papers) if (text.includes(p)) return p;
  return null;
}

export function detectSchool(text: string): string | null {
  const m = text.match(/([가-힣]{2,8}(?:공립)?(?:보통|국민|소|중|고등|상업|농업(?:보습)?|보습)?(?:학교|고등학교|고보))/g);
  if (!m || m.length === 0) return null;
  const counts = new Map<string, number>();
  for (const s of m) counts.set(s, (counts.get(s) || 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
}

export function extractKeyValues(note: string): Record<string, string> {
  const out: Record<string, string> = {};
  const lines = note.split(/\r?\n/);
  for (const ln of lines) {
    const m = ln.match(/^[\s□<>\-•]*([^:]{1,30})\s*[:：]\s*(.+)$/);
    if (!m) continue;
    const key = m[1].trim().replace(/^[\s□<>\-•]+/, '');
    const val = m[2].trim();
    if (!key || !val || val.length > 200) continue;
    out[key] = val;
  }
  return out;
}

export function normalizeDate(raw: string): string | null {
  if (!raw) return null;
  let m = raw.match(/(\d{4})\D+(\d{1,2})\D+(\d{1,2})/);
  if (m) return `${m[1]}-${m[2].padStart(2, '0')}-${m[3].padStart(2, '0')}`;
  m = raw.match(/(\d{4})/);
  if (m) return m[1];
  return null;
}

export function toYaml(obj: Record<string, any>): string {
  const lines: string[] = ['---'];
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null || v === '') continue;
    if (Array.isArray(v)) {
      if (v.length === 0) continue;
      lines.push(`${k}: [${v.map(x => JSON.stringify(x)).join(', ')}]`);
    } else if (typeof v === 'string' && (v.includes(':') || v.includes('#') || v.includes('\n'))) {
      lines.push(`${k}: ${JSON.stringify(v)}`);
    } else {
      lines.push(`${k}: ${v}`);
    }
  }
  lines.push('---');
  return lines.join('\n');
}

export function detectKind(title: string, type: string, note: string, kv: Record<string, string>): RouteKind {
  const t = title + ' ' + type;
  if (kv['성명'] || kv['셩명'] || kv['생년월일'] || kv['출생일']) return '인물';
  if (/공훈록|공적개요|독립유공자|훈격/.test(note)) return '인물';
  if (/판결문|형사사건부|법원/.test(t) || /판결문/.test(note)) return '판결문';
  if (detectNewspaper(t) || /기사|보도/.test(t)) return '신문';
  if (/연혁|교사|학교사/.test(t)) return '학교';
  if (/만세항쟁|동맹휴학|맹휴|격문|시위|항쟁|운동/.test(t)) return '사건';
  if (/단체|회|동맹|결사/.test(t)) return '단체';
  return '지역';
}

export function normalizeSourceType(type: string): string {
  if (/판결문/.test(type)) return '판결문';
  if (/신문|기사|보도/.test(type)) return '신문기사';
  if (/공문서|행정/.test(type)) return '공문서';
  if (/회고|구술/.test(type)) return '회고록';
  if (/사진|이미지/.test(type)) return '사진';
  if (/보고서/.test(type)) return '보고서';
  return type || '기타';
}

export function extractSourceUrl(note: string, source: string): string {
  const blob = `${note}\n${source}`;
  const m = blob.match(/https?:\/\/[^\s<>\)\]]+/);
  return m ? m[0] : '';
}

export function buildMdFromIssue(issue: any): ConvertResult {
  const body: string = issue.body || '';
  const title    = parseSection(body, '자료 제목') || (issue.title || '').replace('[자료 제출] ', '');
  const type     = parseSection(body, '자료 종류');
  const date     = parseSection(body, '자료 연도');
  const region   = parseSection(body, '관련 지역');
  const persons  = parseSection(body, '관련 인물·사건');
  const source   = parseSection(body, '자료 출처·소장처');
  const note     = parseSection(body, '설명·메모');
  const files    = parseSection(body, '첨부 파일 목록');

  const submitterLine = (body.match(/^제출자: (.+)$/m) || [])[1] || '';
  const kv = extractKeyValues(note);
  const kind = detectKind(title, type, note, kv);

  const name      = kv['성명'] || kv['셩명'] || '';
  const nameMatch = name.match(/^([가-힣]{2,5})/);
  const koName    = nameMatch ? nameMatch[1] : '';
  const hanjaMatch = name.match(/[一-龥]{2,5}/);
  const hanja     = hanjaMatch ? hanjaMatch[0] : '';

  const birth = normalizeDate(kv['출생일'] || kv['생년월일'] || '');
  const death = normalizeDate(kv['사망일'] || kv['사망년월일'] || '');
  const honor = kv['훈격'] || kv['포상정보'] || '';
  const movementType = kv['운동계열'] || '';
  const homeAddress  = kv['본적'] || '';
  const school       = kv['소속'] || kv['출신학교'] || detectSchool(note + ' ' + title) || '';
  const sourceUrl    = extractSourceUrl(note, source);

  let folder: string;
  let filename: string;
  switch (kind) {
    case '인물': {
      folder = '01-인물/항일';
      const base = koName || title.replace(/[\/\\:*?"<>|]/g, '_').slice(0, 40);
      filename = `${base}.md`;
      break;
    }
    case '학교': {
      folder = '07-항일학교';
      const sch = school || title.replace(/[\/\\:*?"<>|]/g, '_').slice(0, 40);
      filename = `${sch}.md`;
      break;
    }
    case '신문': {
      const paper = detectNewspaper(title + ' ' + type) || '미상신문';
      folder = `05-문헌/${paper}`;
      filename = `${title.replace(/[\/\\:*?"<>|]/g, '_').slice(0, 60)}.md`;
      break;
    }
    case '판결문': {
      folder = '05-문헌/판결문';
      filename = `${title.replace(/[\/\\:*?"<>|]/g, '_').slice(0, 60)}.md`;
      break;
    }
    case '사건': {
      folder = '02-사건';
      filename = `${title.replace(/[\/\\:*?"<>|]/g, '_').slice(0, 60)}.md`;
      break;
    }
    case '단체': {
      folder = '03-단체';
      filename = `${title.replace(/[\/\\:*?"<>|]/g, '_').slice(0, 60)}.md`;
      break;
    }
    default:
      folder = regionToFolder(region);
      filename = `${title.replace(/[\/\\:*?"<>|]/g, '_').slice(0, 60)}.md`;
  }

  // persons 토큰을 인물·학교·사건·기관으로 분류 (그래프 wikilink 생성용)
  // build_graph.py가 본문 [[link]]만 엣지로 만드므로, 분류된 토큰을 본문에 [[]]로 삽입.
  const personTokens: string[] = [];
  const schoolTokens: string[] = [];
  const eventTokens: string[] = [];
  const orgTokens: string[] = [];
  if (persons && persons !== '(미기재)') {
    const tokens = persons.split(/[,，、·\n]+/).map(s => s.trim()).filter(Boolean);
    for (const t of tokens) {
      // 한자/괄호 제거하여 한글 표기만 추출
      const k = t.replace(/\([^)]*\)/g, '').replace(/[一-龥]+/g, '').trim();
      if (!k) continue;
      if (/(학교|고보|고등학교|보습)/.test(k)) schoolTokens.push(k);
      else if (/(운동|항쟁|시위|맹휴|동맹휴학|사건|격문)/.test(k)) eventTokens.push(k);
      else if (/(회|단|협의|동맹|위원|조합|총독부|보안|경찰)/.test(k)) orgTokens.push(k);
      else if (/^[가-힣]{2,5}$/.test(k)) personTokens.push(k);
      else orgTokens.push(k);  // 분류 모호 시 기관 카테고리로
    }
  }

  // 본문에 등장하는 인물 한자명을 한글로 추출 (예: "박창신(朴昌信)" → "박창신")
  const inlinePersons = new Set<string>();
  for (const m of (note || '').matchAll(/([가-힣]{2,5})\s*\([一-龥\s]{2,5}\)/g)) {
    if (m[1] !== koName) inlinePersons.add(m[1]);
  }
  for (const p of inlinePersons) if (!personTokens.includes(p)) personTokens.push(p);

  // 학교 검출 결과 통합 — '충남 당진군 면천면 면천공립보통학교' 같은 긴 표기에서 마지막 학교명만 추출
  if (school) {
    const cleanSchool = (school.match(/[가-힣]{2,8}(?:공립|공립보통|공립농업|공립상업)?(?:보통|국민|소|중|고등|상업|농업(?:보습)?|보습)?(?:학교|고등학교|고보)/g) || []).pop() || school;
    if (cleanSchool && !schoolTokens.includes(cleanSchool)) schoolTokens.unshift(cleanSchool);
  }

  // 그래프 카테고리 친화 tags (build_graph.py categorize() 매칭)
  const categoryTag = kind === '인물' ? '항일인물'
                    : kind === '학교' ? '학교'
                    : kind === '사건' ? '사건'
                    : kind === '단체' ? '단체'
                    : kind === '신문' || kind === '판결문' ? '문헌'
                    : kind === '지역' ? '지역'
                    : '기타';

  // 연도 태그 (1919.3.1 → 연도/1919)
  const yearMatch = (date || '').match(/\d{4}/) || (note || '').match(/(\d{4})년/);
  const yearTag = yearMatch ? `연도/${yearMatch[1] || yearMatch[0]}` : null;

  const fm: Record<string, any> = {
    type: kind === '인물' ? '인물' : kind === '학교' ? '학교' : kind === '사건' ? '사건' : kind === '단체' ? '단체' : kind === '신문' || kind === '판결문' ? '문헌' : '지역',
    side: kind === '인물' ? '항일' : undefined,
    제목: title,
    이름: koName || undefined,
    한자: hanja || undefined,
    생년월일: birth || undefined,
    사망년월일: death || undefined,
    본적: homeAddress || undefined,
    훈격: honor || undefined,
    운동계열: movementType || undefined,
    소속: school || undefined,
    관련학교: schoolTokens.length ? schoolTokens : undefined,
    관련지역: region || undefined,
    관련인물: personTokens.length ? personTokens : undefined,
    관련사건: eventTokens.length ? eventTokens : undefined,
    관련기관: orgTokens.length ? orgTokens : undefined,
    자료종류: type || undefined,
    source_type: normalizeSourceType(type),
    source: sourceUrl ? '제출자료' : (source || '제출자료'),
    source_url: sourceUrl || undefined,
    source_reliability: sourceUrl ? '●●○' : '●○○',
    submitted_by: (submitterLine.split('/')[0] || '익명').trim(),
    submitted_at: (issue.created_at || '').slice(0, 10),
    원본이슈: `#${issue.number}`,
    원본이슈_url: issue.html_url,
    생성일: new Date().toISOString().slice(0, 10),
    tags: ['사용자제출', categoryTag, ...(yearTag ? [yearTag] : []), ...(region ? [region.replace(/\s.*/, '')] : [])],
  };

  const lines: string[] = [];
  lines.push(toYaml(fm));
  lines.push('');
  lines.push(`# ${title}`);
  lines.push('');
  if (kind === '인물') {
    lines.push(`> ${honor ? `${honor}. ` : ''}${birth ? `${birth} ~ ${death || ''}. ` : ''}${homeAddress ? `본적: ${homeAddress}.` : ''}`);
    lines.push('');
    lines.push('## 가. 인적사항');
    if (koName)        lines.push(`- 성명: ${koName}${hanja ? ` (${hanja})` : ''}`);
    if (birth)         lines.push(`- 출생: ${birth}`);
    if (death)         lines.push(`- 사망: ${death}`);
    if (homeAddress)   lines.push(`- 본적: ${homeAddress}`);
    if (school)        lines.push(`- 소속: ${school}`);
    if (movementType)  lines.push(`- 운동계열: ${movementType}`);
    if (honor)         lines.push(`- 훈격: ${honor}`);
    lines.push('');
    if (kv['공적개요']) { lines.push('## 나. 공적 개요'); lines.push(''); lines.push(kv['공적개요']); lines.push(''); }
    lines.push('## 다. 공훈록 / 활동 상세');
    lines.push('');
    lines.push(note || '(없음)');
    lines.push('');
  } else {
    lines.push('## 자료 정보');
    lines.push('');
    lines.push(`- **자료 종류**: ${type || '미상'}`);
    lines.push(`- **연도**: ${date || '미상'}`);
    lines.push(`- **지역**: ${region || '미상'}`);
    lines.push(`- **출처**: ${source || '미기재'}`);
    if (sourceUrl) lines.push(`- **출처 URL**: ${sourceUrl}`);
    lines.push(`- **제출자**: ${submitterLine}`);
    lines.push(`- **원본 이슈**: [#${issue.number}](${issue.html_url})`);
    lines.push('');
    lines.push('## 관련 인물·사건');
    lines.push('');
    lines.push(persons || '(미기재)');
    lines.push('');
    lines.push('## 본문 / 설명');
    lines.push('');
    lines.push(note || '(없음)');
    lines.push('');
  }
  // ── AGENTS.md §4-3 표준 섹션: 위키링크 (그래프 엣지 생성용) ──
  // build_graph.py가 본문 [[link]]만 엣지로 인식하므로, 관계를 [[]]로 표기.
  // 노트 미존재 시 build_graph가 자동으로 무시 (ghost 안 만듦).
  if (personTokens.length) {
    lines.push('## 관련 인물');
    lines.push('');
    for (const p of personTokens) lines.push(`- [[${p}]]`);
    lines.push('');
  }
  if (schoolTokens.length) {
    lines.push('## 관련 학교');
    lines.push('');
    for (const s of schoolTokens) lines.push(`- [[${s}]]`);
    lines.push('');
  }
  if (eventTokens.length) {
    lines.push('## 관련 사건');
    lines.push('');
    for (const e of eventTokens) lines.push(`- [[${e}]]`);
    lines.push('');
  }
  if (orgTokens.length) {
    lines.push('## 관련 기관');
    lines.push('');
    for (const o of orgTokens) lines.push(`- [[${o}]]`);
    lines.push('');
  }
  // 지역 백링크 — region이 정확히 시군 단위인 경우만 [[]]
  const regionMatch = region && region.match(/([가-힣]{2,3}(?:시|군|구|도))/);
  if (regionMatch) {
    lines.push('## 관련 지역');
    lines.push('');
    lines.push(`- [[${regionMatch[1]}]]`);
    lines.push('');
  }

  lines.push('## 첨부 파일');
  lines.push('');
  lines.push(files || '(없음)');
  lines.push('');
  lines.push('## 출처');
  lines.push('');
  lines.push(`- 사용자 제출 (이슈 [#${issue.number}](${issue.html_url}))`);
  if (sourceUrl) lines.push(`- 원출처: ${sourceUrl}`);
  if (source && source !== sourceUrl) lines.push(`- 소장처: ${source}`);

  return { md: lines.join('\n'), folder, filename, kind };
}
