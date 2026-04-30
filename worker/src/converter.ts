/**
 * 사용자 제출 이슈 → 위키 .md 변환기
 *
 * worker/src/index.ts와 dry-run 스크립트(scripts/dry_run_convert.mjs)에서 공유.
 * 워커 환경(no Node API)과 Node 환경 모두에서 동작하도록 표준 JS만 사용.
 */

export type RouteKind = '인물' | '학교' | '신문' | '판결문' | '사건' | '단체' | '지역';
export interface ConvertResult { md: string; folder: string; filename: string; kind: RouteKind; }

// submit.html이 사용하는 표준 8개 섹션 헤딩만 종료자로 인정.
// note에 들어온 사용자 마크다운에 비표준 ## 헤딩(예: "## 본문 — 한자 원문")이 있어도
// 다음 표준 섹션을 만나기 전까지 본문이 잘리지 않도록 한다.
const STD_HEADINGS = [
  '자료 제목', '자료 종류', '자료 연도', '관련 지역',
  '관련 인물·사건', '자료 출처·소장처', '설명·메모', '첨부 파일 목록',
];

export function parseSection(body: string, heading: string): string {
  // 'm' 플래그를 쓰지 않는다 — 'm' 모드에서 $는 줄 끝에 매치되어
  // 본문 첫 줄 직후 즉시 종료되는 버그가 있었음. 여기서는 input end만
  // 종료자로 인정한다.
  const enders = STD_HEADINGS
    .filter(h => h !== heading)
    .map(h => `\\n## ${h.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`)
    .join('|');
  const re = new RegExp(`## ${heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\n([\\s\\S]*?)(?=${enders}|\\n---\\n|$(?![\\s\\S]))`);
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
  // GitHub API의 issue.body는 \r\n 라인엔딩을 사용. parseSection·코드블록
  // 정규식의 [^\n]* 가 \r를 포함하지 않게 본문 진입 시 정규화.
  const body: string = (issue.body || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n');
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
  // 일반명사(학생·교사·청년 등)를 인물로 오인식하지 않도록 제외 목록
  const NON_PERSON_WORDS = new Set([
    '학생', '교사', '경찰', '주민', '청년', '관계자', '인사', '동지',
    '여러분', '학교', '직원', '교원', '당국', '관청', '동민', '일동',
    '소년', '소녀', '부인', '농민', '노동자', '사람', '시민', '검사', '판사',
    '간부', '회원', '대표', '단원', '인원', '전부', '일부', '명단',
    '면장', '지국', '경찰서', '읍내', '연구가', '기자', '학자', '작가',
    '인쇄', '출판', '발행', '편집', '주서', '복윤', '원문',
  ]);

  // 띄어쓰기 없는 OCR 본문에서 잘못 잡히는 false positive 차단:
  // 토큰에 한국어 조사/어미가 포함되거나 시작이 직함이면 정리·거부.
  const PARTICLE_RE = /(?:으로|로서|에서|하면|하며|면서|에는|되었|있는|이라|이라는|이라고|하는|되는|하던|되던|하기|되기|되면|있어|있었|있다|이며|또한|그러|이러|되어|있으|라하|라며|라면|마다|만흔|는바|만은|쇄물|업보)/;
  const TITLE_PREFIX_RE = /^(?:선생|청년|공인|국원|면장|학생|교사|교원|위원|동지|소년|소녀|여러분|일동|단원|회원|대표|간부|부인|농민|노동자|시민|검사|판사|관계자|인사|지국장|기자|관청|당국|동민|중에|중의|즉시|매번|모두|이번|금번|특히|당시|그때|이때)/;
  const NON_PERSON_SUFFIX_RE = /(?:군|면|리|읍|동|시|도|국|회|단|서|소|부|과|청|점|원|장|가|학교|학원|위원회|협의회|조합|보안)$/;
  const PERSON_RE = /^[가-힣]{2,4}$/;
  const SCHOOL_RE = /^[가-힣]{2,3}(?:공립|사립|시립)?(?:(?:농업|상업|공업|보습|보통|국민|고등|중|소)+(?:학교|학원|보교|상교|농교|고보)|보교|상교|농교|고보|학원|중학교|소학교|고등학교)$/;
  const EVENT_RE  = /^[가-힣]{2,4}(?:동맹휴학|맹휴|만세항쟁|만세운동|시위|격문|항쟁|운동|사건)$/;
  const SUSPICIOUS_PREFIX_RE = /^(?:업보|편으|로농|하는|되는|이라|하면|하며|되면|되었|이었|있는|쇄물|마다|만흔|만은|는바|중정|등의|등을|등이|등은|등도|업보)/;

  function stripTitlePrefix(s: string): string {
    let prev = '';
    while (prev !== s) { prev = s; s = s.replace(TITLE_PREFIX_RE, ''); }
    return s;
  }

  function isCleanPerson(k: string): string | null {
    if (PARTICLE_RE.test(k)) return null;
    if (NON_PERSON_SUFFIX_RE.test(k)) return null;  // 부여군/지국/경찰서 등
    const stripped = stripTitlePrefix(k);
    if (!stripped || !PERSON_RE.test(stripped)) return null;
    if (NON_PERSON_WORDS.has(stripped)) return null;
    if (NON_PERSON_SUFFIX_RE.test(stripped)) return null;
    return stripped;
  }
  function isCleanSchool(k: string): string | null {
    if (PARTICLE_RE.test(k)) return null;
    if (SUSPICIOUS_PREFIX_RE.test(k)) return null;
    const stripped = stripTitlePrefix(k);
    if (!stripped || stripped.length < 4 || stripped.length > 9) return null;
    if (SUSPICIOUS_PREFIX_RE.test(stripped)) return null;
    if (!SCHOOL_RE.test(stripped)) return null;
    return stripped;
  }
  function isCleanEvent(k: string): string | null {
    if (PARTICLE_RE.test(k)) return null;
    if (SUSPICIOUS_PREFIX_RE.test(k)) return null;
    const stripped = stripTitlePrefix(k);
    if (!stripped || stripped.length < 4 || stripped.length > 9) return null;
    if (!EVENT_RE.test(stripped)) return null;
    return stripped;
  }
  if (persons && persons !== '(미기재)') {
    const tokens = persons.split(/[,，、·\n]+/).map(s => s.trim()).filter(Boolean);
    for (const t of tokens) {
      // 한자/괄호 제거하여 한글 표기만 추출
      const k = t.replace(/\([^)]*\)/g, '').replace(/[一-龥]+/g, '').trim();
      if (!k) continue;
      // 학교/사건/단체는 패턴 검증 후 등록 (false positive 차단)
      if (/(학교|고보|고등학교|보습)/.test(k)) {
        const cs = isCleanSchool(k);
        if (cs && !schoolTokens.includes(cs)) schoolTokens.push(cs);
        continue;
      }
      if (/(운동|항쟁|시위|맹휴|동맹휴학|사건|격문)/.test(k)) {
        const ce = isCleanEvent(k);
        if (ce && !eventTokens.includes(ce)) eventTokens.push(ce);
        continue;
      }
      if (/(회|단|협의|동맹|위원|조합|총독부|보안|경찰)/.test(k)) {
        if (!orgTokens.includes(k)) orgTokens.push(k);
        continue;
      }
      const cp = isCleanPerson(k);
      if (cp && !personTokens.includes(cp)) personTokens.push(cp);
    }
  }

  // 본문에 등장하는 인물 한자명을 한글로 추출 (예: "박창신(朴昌信)" → "박창신")
  const inlinePersons = new Set<string>();
  for (const m of (note || '').matchAll(/([가-힣]{2,7})\s*\([一-龥\s]{1,8}\)/g)) {
    const cp = isCleanPerson(m[1]);
    if (cp && cp !== koName) inlinePersons.add(cp);
  }
  for (const p of inlinePersons) if (!personTokens.includes(p)) personTokens.push(p);

  // 학교/사건은 한자 병기가 붙은 단어만 추출 — 띄어쓰기 안 된 OCR 한글
  // 본문에서 어미가 결합되어 잘못 추출되는 false positive는 isCleanSchool/Event로 차단.
  for (const m of (note || '').matchAll(/([가-힣]{2,12})\s*\([一-龥\s]{2,15}\)/g)) {
    const k = m[1];
    if (NON_PERSON_WORDS.has(k)) continue;
    const cs = isCleanSchool(k);
    if (cs) { if (!schoolTokens.includes(cs)) schoolTokens.push(cs); continue; }
    const ce = isCleanEvent(k);
    if (ce) { if (!eventTokens.includes(ce)) eventTokens.push(ce); continue; }
    // 인물은 inlinePersons에서 따로 처리됨
  }
  // detectSchool 결과(한자 무관, 폼의 '관련 인물' 필드 기반)도 보존하되
  // 한자 병기 없는 자동 추출은 차단. 폼 입력은 신뢰.
  if (school) {
    const cleanSchool = (school.match(/[가-힣]{2,10}(?:학교|고등학교|고보|농교|보교|상교|보습)/g) || []).pop() || school;
    if (cleanSchool && !schoolTokens.includes(cleanSchool)) schoolTokens.unshift(cleanSchool);
  }
  // 제목에서 사건 키워드 (제목은 띄어쓰기 정상이므로 안전)
  for (const m of title.matchAll(/(?:[가-힣]{2,6}\s+)?(?:동맹휴학|맹휴|만세항쟁|만세운동|시위|격문\s*사건|항쟁|운동|사건)/g)) {
    const e = m[0].trim();
    if (e.length >= 3 && e.length <= 14 && !eventTokens.includes(e)) eventTokens.push(e);
  }
  // 본문에서 지역명(시·군·면·리 단위) 한글 추출
  for (const m of (note || '').matchAll(/[가-힣]{2,4}(?:군|면|리|읍|동)/g)) {
    if (!orgTokens.includes(m[0]) && m[0].length >= 3) {
      // 지역은 별도 카테고리지만 이번에는 orgTokens에 합치지 않고 독립 처리.
      // (현재 frontmatter 구조는 단일 region만 있으니 토큰만 누적해 두고 본문에는 표기 안 함.)
    }
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
    // 신문기사 타입: note에서 한자 본문 / 한글 변환 코드블록 추출
    const isNewspaper = kind === '신문' || /신문|기사/.test(type);
    let hanjaText = '';
    let koreanText = '';
    let naverUrl = sourceUrl;
    if (isNewspaper && note) {
      const hanjaRe = /## 본문[^\n]*?(?:\d{4}|한자)[^\n]*\n+```\n?([\s\S]*?)\n?```/m;
      const koreanRe = /## 본문[^\n]*?한글[^\n]*\n+```\n?([\s\S]*?)\n?```/m;
      const hm = note.match(hanjaRe); if (hm) hanjaText = hm[1].trim();
      const km = note.match(koreanRe); if (km) koreanText = km[1].trim();
      const nm = note.match(/https:\/\/newslibrary\.naver\.com\/viewer\/[^\s\)\"<>]+/);
      if (nm) naverUrl = nm[0];
    }
    lines.push('## 자료 정보');
    lines.push('');
    lines.push(`- **자료 종류**: ${type || '미상'}`);
    lines.push(`- **연도**: ${date || '미상'}`);
    lines.push(`- **지역**: ${region || '미상'}`);
    lines.push(`- **출처**: ${source || '미기재'}`);
    if (naverUrl) lines.push(`- **원기사 URL**: ${naverUrl}`);
    lines.push(`- **제출자**: ${submitterLine}`);
    lines.push(`- **원본 이슈**: [#${issue.number}](${issue.html_url})`);
    lines.push('');
    if (hanjaText) {
      lines.push('## 본문 — 원문 (한자)');
      lines.push('');
      lines.push('```');
      lines.push(hanjaText);
      lines.push('```');
      lines.push('');
    }
    if (koreanText) {
      lines.push('## 본문 — 한글 변환 (네이버 OCR)');
      lines.push('');
      lines.push('```');
      lines.push(koreanText);
      lines.push('```');
      lines.push('');
    }
    if (!hanjaText && !koreanText) {
      lines.push('## 관련 인물·사건');
      lines.push('');
      lines.push(persons || '(미기재)');
      lines.push('');
      lines.push('## 본문 / 설명');
      lines.push('');
      lines.push(note || '(없음)');
      lines.push('');
    } else if (persons && persons !== '(미기재)') {
      lines.push('## 관련 인물·사건');
      lines.push('');
      lines.push(persons);
      lines.push('');
    }
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
