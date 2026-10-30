// Prints the starting reference distribution for lib/calibrate.js: raw pair
// scores from a synthetic pool, at 21 quantiles (0%, 5% … 100%). Used only
// until the real pool has MIN_REFERENCE eligible pairs. Seeded, so the
// output is the same every run: node tools/calibrate.mjs
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const schema = require('../lib/schema.js');
const { scorePair } = require('../lib/score.js');

let seed = 20261028;
const rand = () => { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
const pick = list => list[Math.floor(rand() * list.length)];
const INTERESTS = ['hiking', 'food', 'travel', 'gaming', 'art', 'music', 'running', 'books', 'yoga', 'coffee', 'cooking', 'photography',
  'films', 'k-dramas', 'football', 'tennis', 'cycling', 'climbing', 'dance', 'fashion', 'design', 'tech', 'startups', 'investing',
  'wine', 'baking', 'gym', 'swimming', 'diving', 'camping', 'museums', 'theatre', 'anime', 'podcasts', 'volunteering', 'pets',
  'gardening', 'writing', 'concerts', 'board games'];

function person(i, gender) {
  const traits = {};
  for (const [key, spec] of Object.entries(schema.FIELDS)) {
    let value;
    if (spec.kind === 'scale') value = 1 + Math.floor(rand() * 5);
    else if (spec.kind === 'score') value = Math.round(20 + rand() * 60);
    else if (spec.kind === 'enum') value = pick(spec.options);
    else if (spec.kind === 'set') value = [...new Set([pick(spec.options), pick(spec.options)])].slice(0, spec.max);
    else if (spec.kind === 'mbti') value = pick(['E', 'I']) + pick(['N', 'S']) + pick(['T', 'F']) + pick(['J', 'P']);
    else if (spec.kind === 'tags') value = [...new Set(Array.from({ length: 10 + Math.floor(rand() * 11) }, () => pick(INTERESTS)))];
    else value = pick(['Singapore', 'Malaysia', 'Hong Kong']);
    if (key === 'future.kids') value = pick(['wants', 'open', 'has']);
    if (spec.kind === 'int') value = spec.min + Math.floor(rand() * (spec.max - spec.min));
    traits[key] = { value, source: spec.statedOnly ? 'stated' : 'observed', confidence: 0.5 + rand() * 0.4 };
  }
  const { profile } = schema.validateProfile({ basics: { firstName: 'P' + i, age: 30, gender, seeking: [gender === 'woman' ? 'man' : 'woman'],
    city: 'Singapore', intent: 'serious', mode: 'dating' }, traits });
  return { id: 'p' + i, ...profile, prefs: { must: [], nice: [] }, reviewedAt: 1, blocked: [] };
}

const women = Array.from({ length: 200 }, (_, i) => person(i, 'woman'));
const men = Array.from({ length: 200 }, (_, i) => person(i + 200, 'man'));
const raws = [];
for (const w of women) for (const m of men) { const r = scorePair(w, m); if (r) raws.push(r.score); }
raws.sort((a, b) => a - b);
const q = Array.from({ length: 21 }, (_, i) => raws[Math.min(raws.length - 1, Math.floor(i / 20 * raws.length))]);
console.log(JSON.stringify(q));
