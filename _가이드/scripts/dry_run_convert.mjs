/**
 * dry_run_convert.mjs
 *
 * 사용자 제출 이슈 30건(C:\..\사용자제출\issues\*.json)을
 * worker/src/converter.ts 의 buildMdFromIssue() 로 변환했을 때
 * 어떤 폴더/파일명/카테고리로 들어가는지 미리 표시한다.
 *
 * 실행:
 *   cd worker
 *   npx tsx ../_가이드/scripts/dry_run_convert.mjs
 * 또는:
 *   node --experimental-strip-types ../_가이드/scripts/dry_run_convert.mjs
 */

import { readdirSync, readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { buildMdFromIssue } from '../../worker/src/converter.ts';

const __dirname = dirname(fileURLToPath(import.meta.url));
const issuesDir = join(__dirname, '..', '..', '00-원자료', '사용자제출', 'issues');
const outDir    = join(__dirname, '..', '..', '00-원자료', '사용자제출', '_dry_run_preview');
mkdirSync(outDir, { recursive: true });

const files = readdirSync(issuesDir).filter(f => f.endsWith('.json')).sort();
const summary = [];

for (const f of files) {
  const raw = readFileSync(join(issuesDir, f), 'utf8').replace(/^﻿/, '');
  const issue = JSON.parse(raw);
  if (!issue.body) { summary.push({ num: issue.number, kind: '-', folder: '(no body)', filename: '', title: issue.title }); continue; }
  const r = buildMdFromIssue(issue);
  summary.push({ num: issue.number, kind: r.kind, folder: r.folder, filename: r.filename, title: issue.title });

  // 미리보기 저장
  const previewPath = join(outDir, `issue_${String(issue.number).padStart(4, '0')}__${r.kind}__${r.filename}`);
  writeFileSync(previewPath, r.md, 'utf8');
}

// 요약 표 출력
console.log('\n=== 변환 결과 요약 ===\n');
console.log('이슈# | 분류  | 폴더                            | 파일명');
console.log('-----+------+--------------------------------+---------------------');
for (const s of summary.sort((a, b) => a.num - b.num)) {
  console.log(`#${String(s.num).padStart(3)} | ${s.kind.padEnd(5)} | ${s.folder.padEnd(30)} | ${s.filename}`);
}

// 분류별 카운트
const byKind = {};
for (const s of summary) byKind[s.kind] = (byKind[s.kind] || 0) + 1;
console.log('\n=== 분류별 카운트 ===');
for (const [k, n] of Object.entries(byKind).sort((a, b) => b[1] - a[1])) console.log(`  ${k}: ${n}건`);

console.log(`\n미리보기 .md 파일 ${summary.length}개 → ${outDir}\n`);
