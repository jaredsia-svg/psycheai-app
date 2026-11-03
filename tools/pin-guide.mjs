// Pin PsycheAI's guides into the signed skill (README "The guide is signed").
//
//   node tools/pin-guide.mjs            # reads ../psycheai, or PSYCHEAI_REPO
//
// Writes skill/guide.json: the read guide (spec, MBTI rubric, schema), the
// Deep Psyche's added plan, and the Sync guide (spec, brief, schema), exactly
// as psycheai.io's lib/museimport.js guide() serves them. The skill uses this
// copy, signed with the rest, never the one a server sends, so a server
// someone got into can't change what Muse is asked to write. Run it after a
// guide changes on psycheai.io, then node tools/sign-skill.mjs.
const { createRequire } = await import('node:module');
const require = createRequire(import.meta.url);
const fs = require('node:fs');
const path = require('node:path');

const here = path.dirname(new URL(import.meta.url).pathname);
const repo = path.resolve(process.env.PSYCHEAI_REPO || path.join(here, '..', '..', 'psycheai'));
const museimport = require(path.join(repo, 'lib', 'museimport.js'));
const read = museimport.guide('read');
const deep = museimport.guide('read', 'deep');
const sync = museimport.guide('sync');
if (!deep.spec.startsWith(read.spec)) throw new Error('The deep guide no longer extends the read guide');
const musepdf = require(path.join(repo, 'lib', 'musepdf.js'));
const pinned = {
  read: { spec: read.spec, rubric: read.rubric, schema: read.schema },
  deepSpec: deep.spec.slice(read.spec.length),
  sync: { spec: sync.spec, brief: sync.brief, schema: sync.schema },
  // The report's fixed wording (motivator names, labels, icons), so the skill lays out the report
  // itself and the read never leaves Muse (README "The report stays in Muse").
  labels: musepdf.labels(),
};
fs.writeFileSync(path.join(here, '..', 'skill', 'guide.json'), JSON.stringify(pinned, null, 1) + '\n');

// What psycheai.io makes of two sample reads (the report's layout, and the card summary this
// server keeps), for the selftest to hold the skill's own layout to: the site's docs/sample.json
// and its mock read, with the mock's evidence dated as a Muse read's must be.
const psyche = require(path.join(here, '..', 'lib', 'psyche.js'));
const dated = a => { const d = JSON.parse(JSON.stringify(a)); const fix = l => Array.isArray(l) ? l.map((x, i) => typeof x === 'string' ? 'Your May 2025 story, moment ' + (i + 1) : x) : l;
  (d.patterns || []).forEach(p => { p.evidence = fix(p.evidence); }); ((d.mbti || {}).letters || []).forEach(l => { l.evidence = fix(l.evidence); });
  Object.values(d.wellness || {}).forEach(v => { if (v && Array.isArray(v.evidence)) v.evidence = fix(v.evidence); }); if (d.attachment) d.attachment.derivedFrom = fix(d.attachment.derivedFrom); return d; };
const samples = [['Emily Carter', dated(JSON.parse(fs.readFileSync(path.join(repo, 'docs', 'sample.json'), 'utf8')))],
  ['Mei Tan', dated((await require(path.join(repo, 'lib', 'mock.js')).analyseMerged({})).data)]];
const fixture = samples.map(([name, answer]) => {
  const b = museimport.bundleFrom(answer);
  if (!b.ok) throw new Error(name + "'s sample no longer imports: " + JSON.stringify(b.problems).slice(0, 300));
  return { name, answer, full: musepdf.fullView(b.bundle.data, name, b.answer), card: psyche.summarize(answer, name) };
});
fs.mkdirSync(path.join(here, 'fixtures'), { recursive: true });
fs.writeFileSync(path.join(here, 'fixtures', 'report-view.json'), JSON.stringify(fixture, null, 1) + '\n');
console.log('Pinned the guides from', repo, '(' + JSON.stringify(pinned).length + ' characters)');
