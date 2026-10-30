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
const pinned = {
  read: { spec: read.spec, rubric: read.rubric, schema: read.schema },
  deepSpec: deep.spec.slice(read.spec.length),
  sync: { spec: sync.spec, brief: sync.brief, schema: sync.schema },
};
fs.writeFileSync(path.join(here, '..', 'skill', 'guide.json'), JSON.stringify(pinned, null, 1) + '\n');
console.log('Pinned the guides from', repo, '(' + JSON.stringify(pinned).length + ' characters)');
