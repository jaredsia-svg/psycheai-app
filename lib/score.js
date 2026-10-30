// Pair scoring, all in code: cheap enough to run on every pair that passes the
// filters, and the same answer every time.
//
// 1. Filters, both directions: mode, who each is seeking, age ranges, city,
//    intent, the kids deal-breaker, each side's must-haves, blocks. Fail any
//    and the pair is never scored.
// 2. Seven dimensions, each 0..1, from the cells both people have. Each cell
//    counts by the weaker of the two confidences, so a guess on one side
//    cannot carry a match.
// 3. The weighted average, pulled toward 50 when the two profiles share
//    little data: a thin pair cannot reach the threshold on two lucky fields.
// 4. Each side's nice-to-haves (up to +5) and the attraction bucket (±3).
//
// The weights are a first guess. README "Calibration" has how they get tuned.

const { val, FIELDS, MOTIVATORS } = require('./schema');
const { passesMusts, niceShare, pendingKeys, maybeCount } = require('./preferences');
const traits = require('./traits');

const WEIGHTS = {
  dating: { needs: 0.20, lifestyle: 0.18, future: 0.20, communication: 0.12, values: 0.12, background: 0.08, personality: 0.10 },
  friends: { needs: 0.10, lifestyle: 0.30, future: 0.05, communication: 0.10, values: 0.20, background: 0.10, personality: 0.15 },
};
const DIMENSIONS = Object.keys(WEIGHTS.dating);
const FULL_COVERAGE = 0.6;   // share of weighted data at which no shrinking applies
const NICE_POINTS = 5;
const ATTRACTION_POINTS = 3;
const MAYBE_POINTS = 5;      // per custom must-have answered "maybe"
const APPRECIATE_POINTS = 2; // per trait the other is drawn to, up to two each way
// No weak areas: a dimension read from enough data must reach this on its own,
// however good the total, or the pair is not put in a drop (lib/weekly.js).
const AREA_FLOOR = Number(process.env.PSYCHE_AREA_FLOOR || 55);
const AREA_MIN_COVERAGE = 0.34;


// ---------- filters ----------

const INTENT_OK = {
  serious: ['serious', 'open'],
  open: ['serious', 'open', 'casual'],
  casual: ['open', 'casual'],
  friends: ['friends'],
};

function oneWay(a, b) {
  const A = a.basics, B = b.basics;
  if (!(A.seeking || []).includes(B.gender)) return 'seeking';
  if (B.age < A.ageMin || B.age > A.ageMax) return 'age';
  if (!passesMusts(a, b)) return 'must';
  if (traits.turnedOff(a, b)) return 'turnoff';
  if ((a.blocked || []).includes(b.id)) return 'blocked';
  return null;
}

/**
 * null when the two may be matched, 'pending_question' when the only thing
 * in the way is a custom question one of them has not answered yet, else
 * the first reason they may not.
 */
function filterReason(a, b, { ignorePending = false } = {}) {
  const hard = hardReason(a, b);
  if (hard) return hard;
  if (!ignorePending && (pendingKeys(a, b).length || pendingKeys(b, a).length)) return 'pending_question';
  return null;
}

function hardReason(a, b) {
  if (a.id === b.id) return 'self';
  if (!a.reviewedAt || !b.reviewedAt) return 'unreviewed';
  if (a.paused || b.paused) return 'paused';
  if (a.basics.mode !== b.basics.mode) return 'mode';
  if (String(a.basics.city).toLowerCase() !== String(b.basics.city).toLowerCase()) return 'city';
  if (!(INTENT_OK[a.basics.intent] || []).includes(b.basics.intent)) return 'intent';
  if (a.basics.mode === 'dating') {
    const kids = [val(a, 'future.kids'), val(b, 'future.kids')];
    if (kids.includes('wants') && kids.includes('doesnt_want')) return 'kids';
  }
  return oneWay(a, b) || oneWay(b, a);
}

// ---------- similarity helpers ----------

const scaleSim = (x, y) => 1 - Math.abs(x - y) / 4;
const traitSim = (x, y) => Math.max(0, 1 - Math.abs(x - y) / 60);
const textSim = (x, y) => (String(x).toLowerCase() === String(y).toLowerCase() ? 1 : 0.6);
const overlap = (x, y) => {
  if (!x.length || !y.length) return 0;
  const shared = x.filter(v => y.includes(v)).length;
  return Math.min(1, shared / Math.min(x.length, y.length, 3));
};
const table = rows => (x, y) => {
  if (x === y && rows[x + '|' + y] === undefined) return 1;
  const v = rows[x + '|' + y] !== undefined ? rows[x + '|' + y] : rows[y + '|' + x];
  return v === undefined ? 0.5 : v;
};

const ATTACHMENT = table({
  'secure|secure': 1, 'secure|anxious': 0.8, 'secure|avoidant': 0.75, 'secure|fearful': 0.65,
  'anxious|anxious': 0.5, 'avoidant|avoidant': 0.5, 'anxious|avoidant': 0.2, 'fearful|fearful': 0.35,
  'anxious|fearful': 0.35, 'avoidant|fearful': 0.3,
});
const DRINKING = table({ 'never|social': 0.6, 'never|regular': 0.15, 'social|regular': 0.7 });
const SMOKING = table({ 'no|sometimes': 0.4, 'no|yes': 0.1, 'sometimes|yes': 0.7 });
const PETS = table({ 'none|wants': 0.5, 'none|has': 0.4, 'wants|has': 0.9 });
const KIDS = table({ 'wants|open': 0.7, 'open|doesnt_want': 0.6, 'wants|has': 0.7, 'open|has': 0.8, 'doesnt_want|has': 0.3, 'has|has': 0.9 });
const KIDS_WHEN = table({ 'within_2y|2_5y': 0.6, 'within_2y|5y_plus': 0.2, '2_5y|5y_plus': 0.6, 'na|within_2y': 0.5, 'na|2_5y': 0.5, 'na|5y_plus': 0.5 });
const MARRIAGE = table({ 'wants|open': 0.7, 'open|doesnt_want': 0.7, 'wants|doesnt_want': 0.1 });
const MONEY = table({ 'saver|balanced': 0.75, 'balanced|spender': 0.75, 'saver|spender': 0.35 });
const CONFLICT = table({
  'talk_now|cool_off_then_talk': 0.75, 'talk_now|avoid': 0.3, 'talk_now|confront': 0.6,
  'cool_off_then_talk|avoid': 0.5, 'cool_off_then_talk|confront': 0.45, 'avoid|confront': 0.15,
  'avoid|avoid': 0.45, 'confront|confront': 0.4,
});
const LIFE_STAGES = FIELDS['background.lifeStage'].options;
const lifeStageSim = (x, y) => {
  const gap = Math.abs(LIFE_STAGES.indexOf(x) - LIFE_STAGES.indexOf(y));
  return gap === 0 ? 1 : gap === 1 ? 0.6 : 0.2;
};
const EDUCATION = FIELDS['background.education'].options;

// Close religions count as close: the three non-religious answers, and the
// two Christian ones. "Prefer not to say" is unknown, never a mismatch.
const RELIGION_GROUPS = [['free_thinker', 'atheist', 'agnostic'], ['christian', 'catholic']];
const religionSim = (x, y) => {
  if (x === 'prefer_not_to_say' || y === 'prefer_not_to_say') return null;
  if (x === y) return 1;
  return RELIGION_GROUPS.some(g => g.includes(x) && g.includes(y)) ? 0.75 : 0;
};

// Motivations sit on Schwartz's circle: the same one is 1, a neighbour 0.8,
// the opposite side 0. Each of one person's top three is matched to the
// nearest of the other's, both ways, and averaged.
const circleGap = (x, y) => { const d = Math.abs(MOTIVATORS.indexOf(x) - MOTIVATORS.indexOf(y)); return Math.min(d, MOTIVATORS.length - d); };
const nearest = (from, to) => from.reduce((sum, m) => sum + (1 - Math.min(...to.map(t => circleGap(m, t))) / 5), 0) / from.length;
const motivatorSim = (x, y) => (x.length && y.length ? (nearest(x, y) + nearest(y, x)) / 2 : null);
const educationSim = (x, y) => 1 - Math.abs(EDUCATION.indexOf(x) - EDUCATION.indexOf(y)) / 4;

// ---------- dimensions ----------

// One comparison: a similarity from both people's cells, weighted by the
// weaker confidence. `needs` lists the field keys it reads.
function cmp(keys, sim) { return { keys: [].concat(keys), sim }; }

function run(a, b, comparisons) {
  let total = 0, weight = 0, possible = 0;
  for (const { keys, sim } of comparisons) {
    possible += 1;
    const cellsA = keys.map(k => a.traits[k]);
    const cellsB = keys.map(k => b.traits[k]);
    if (cellsA.some(c => !c) || cellsB.some(c => !c)) continue;
    const w = Math.min(...cellsA.map(c => c.confidence), ...cellsB.map(c => c.confidence));
    if (w <= 0) continue;
    const s = sim(...cellsA.map(c => c.value), ...cellsB.map(c => c.value));
    if (s === null || s === undefined || Number.isNaN(s)) continue;
    total += s * w;
    weight += w;
  }
  return weight ? { score: total / weight, coverage: weight / possible } : { score: null, coverage: 0 };
}

// Love languages are directional: what A gives against what B likes to receive.
const lands = (giving, receiving) => (giving.some(g => receiving.includes(g)) ? 1 : 0.3);

const DIMENSION_RULES = {
  needs: [
    cmp('needs.attachment', ATTACHMENT),
    cmp(['needs.loveGiving', 'needs.loveReceiving'], (ga, ra, gb, rb) => (lands(ga, rb) + lands(gb, ra)) / 2),
    cmp('needs.closeness', scaleSim),
    // Someone who needs reassurance does best with someone who says how they feel.
    cmp(['needs.reassurance', 'communication.expressive'], (ra, ea, rb, eb) =>
      (Math.min(1, 1 - Math.max(0, ra - eb) / 4) + Math.min(1, 1 - Math.max(0, rb - ea) / 4)) / 2),
  ],
  lifestyle: [
    cmp('lifestyle.social', scaleSim),
    cmp('lifestyle.active', scaleSim),
    cmp('lifestyle.travel', scaleSim),
    cmp('lifestyle.nightlife', scaleSim),
    cmp('lifestyle.pace', scaleSim),
    cmp('lifestyle.drinking', DRINKING),
    cmp('lifestyle.smoking', SMOKING),
    cmp('lifestyle.pets', PETS),
    // With 10 to 20 interests each, four in common is a strong overlap.
    cmp('lifestyle.interests', (x, y) => 0.3 + 0.7 * Math.min(1, x.filter(v => y.includes(v)).length / Math.min(4, x.length, y.length))),
  ],
  future: [
    cmp('future.kids', KIDS),
    cmp('future.kidsWhen', KIDS_WHEN),
    cmp('future.marriage', MARRIAGE),
    cmp('future.settle', textSim),
    cmp('future.ambition', scaleSim),
    cmp('future.money', MONEY),
    cmp('future.familyInvolvement', scaleSim),
    // Religion only counts when one of them says it matters.
    cmp(['future.religion', 'future.religionImportance'], (ra, ia, rb, ib) => {
      const same = religionSim(ra, rb);
      if (same === null || Math.max(ia, ib) < 3) return null;
      return same === 1 ? 1 : Math.max(0, same - (Math.max(ia, ib) - 2) * 0.3 * (1 - same));
    }),
  ],
  communication: [
    cmp('communication.conflict', CONFLICT),
    cmp('communication.expressive', scaleSim),
    cmp('communication.repair', scaleSim),
  ],
  values: [
    cmp('values.top', (x, y) => 0.2 + 0.8 * overlap(x, y)),
    cmp('values.motivators', motivatorSim),
  ],
  background: [
    cmp('background.education', educationSim),
    cmp('background.lifeStage', lifeStageSim),
    cmp('background.familyCloseness', scaleSim),
    cmp('background.upbringing', textSim),
  ],
  personality: [
    cmp('personality.openness', traitSim),
    cmp('personality.conscientiousness', traitSim),
    cmp('personality.extraversion', traitSim),
    // Level, not similarity: two kind people, and two steady ones, do well.
    cmp('personality.agreeableness', (x, y) => (x + y) / 200),
    cmp('personality.neuroticism', (x, y) => 1 - (x + y) / 200),
  ],
};

// ---------- the score ----------

/**
 * Score a pair. Returns null when a filter rules them out, else
 * { score: 0..100, breakdown: { needs: 0..100|null, ... }, coverage: 0..1 }.
 * `buckets` maps profile id to 'above' | 'below' | null (lib/attraction.js).
 */
function scorePair(a, b, buckets = {}, options = {}) {
  if (filterReason(a, b, options)) return null;
  const weights = WEIGHTS[a.basics.mode] || WEIGHTS.dating;
  const breakdown = {};
  let sum = 0, used = 0, coverage = 0, weakest = null;
  for (const dim of DIMENSIONS) {
    const r = run(a, b, DIMENSION_RULES[dim]);
    breakdown[dim] = r.score === null ? null : Math.round(r.score * 100);
    if (r.score !== null && r.coverage >= AREA_MIN_COVERAGE) weakest = weakest === null ? breakdown[dim] : Math.min(weakest, breakdown[dim]);
    if (r.score === null) continue;
    sum += weights[dim] * r.coverage * r.score;
    used += weights[dim] * r.coverage;
    coverage += weights[dim] * r.coverage;
  }
  if (!used) return { score: 50, breakdown, coverage: 0, weakest };
  const raw = sum / used;
  const shrunk = 0.5 + (raw - 0.5) * Math.min(1, coverage / FULL_COVERAGE);
  let score = shrunk * 100;

  const shares = [niceShare(a, b), niceShare(b, a)].filter(s => s !== null);
  if (shares.length) score += NICE_POINTS * shares.reduce((x, y) => x + y, 0) / shares.length;

  score -= MAYBE_POINTS * (maybeCount(a, b) + maybeCount(b, a));
  score += APPRECIATE_POINTS * (Math.min(2, traits.appreciated(a, b).length) + Math.min(2, traits.appreciated(b, a).length));

  const ba = buckets[a.id], bb = buckets[b.id];
  if (a.basics.mode === 'dating' && ba && bb) score += ba === bb ? ATTRACTION_POINTS : -ATTRACTION_POINTS;

  return { score: Math.max(0, Math.min(100, Math.round(score))), breakdown, coverage: Math.round(coverage * 100) / 100, weakest };
}

/** What the two share, sharpest first: the "you two both…" line on a card. */
function highlights(a, b) {
  const out = [];
  const shared = (key) => {
    const x = val(a, key, 0.5), y = val(b, key, 0.5);
    return Array.isArray(x) && Array.isArray(y) ? x.filter(v => y.includes(v)) : [];
  };
  const values = shared('values.top');
  if (values.length) out.push('both put ' + values.slice(0, 2).join(' and ') + ' first');
  const interests = shared('lifestyle.interests');
  if (interests.length) out.push('both love ' + interests.slice(0, 2).join(' and '));
  const kids = [val(a, 'future.kids', 0.5), val(b, 'future.kids', 0.5)];
  if (kids[0] && kids[0] === kids[1] && kids[0] === 'wants') out.push('both want kids');
  const settle = [val(a, 'future.settle', 0.5), val(b, 'future.settle', 0.5)];
  if (settle[0] && settle[1] && textSim(settle[0], settle[1]) === 1) out.push('both see yourselves in ' + settle[0]);
  return out;
}

/** No area below the floor, where there was enough data to judge it. */
const noWeakArea = fit => fit.weakest === null || fit.weakest === undefined || fit.weakest >= AREA_FLOOR;

module.exports = { WEIGHTS, DIMENSIONS, AREA_FLOOR, filterReason, scorePair, highlights, pendingKeys, noWeakArea };
