// "Appreciates" and "turn-offs" (PLAN.md, matching changes).
//
// Each user has two short lists from this vocabulary: the traits they are
// drawn to in other people, and the ones that put them off. Muse fills them
// from how the user talks about people (observed), or the user states them,
// and they review them with their card. A trait one person dislikes is never
// matched with them; a trait they appreciate counts in the other's favour
// and is said, positively, on the card ("calm and a planner, the kind of
// person you're drawn to"). So someone others might see one way is matched
// with someone who sees that very thing as a plus.
//
// Each word is defined by the other person's profile: a test on their cells,
// read only when the cell is confident enough (MIN_CONFIDENCE). Unknown is
// never a hit, either way.

const MIN_CONFIDENCE = 0.5;
// A turn-off read from Instagram has to be surer than that to keep two people
// apart; one the user stated always counts.
const TURNOFF_CONFIDENCE = 0.6;

const cell = (p, key) => (p && p.traits && p.traits[key]) || null;
const num = (p, key) => { const c = cell(p, key); return c && c.confidence >= MIN_CONFIDENCE && typeof c.value === 'number' ? c.value : null; };
const one = (p, key) => { const c = cell(p, key); return c && c.confidence >= MIN_CONFIDENCE ? c.value : null; };
const has = (p, key, v) => { const x = one(p, key); return Array.isArray(x) && x.includes(v); };
const atLeast = (x, n) => x !== null && x >= n;
const atMost = (x, n) => x !== null && x <= n;

// word → [how it reads on a card, test on the other person's profile]
const WORDS = {
  calm: ['calm', p => atMost(num(p, 'personality.neuroticism'), 40)],
  outgoing: ['outgoing', p => atLeast(num(p, 'lifestyle.social'), 4) || atLeast(num(p, 'personality.extraversion'), 65)],
  homebody: ['a homebody', p => atMost(num(p, 'lifestyle.social'), 2)],
  adventurous: ['adventurous', p => atLeast(num(p, 'lifestyle.travel'), 4) || atLeast(num(p, 'personality.openness'), 72)],
  planner: ['a planner', p => atLeast(num(p, 'personality.conscientiousness'), 65)],
  spontaneous: ['spontaneous', p => atMost(num(p, 'personality.conscientiousness'), 40)],
  ambitious: ['ambitious', p => atLeast(num(p, 'future.ambition'), 4)],
  easygoing: ['easygoing', p => atMost(num(p, 'lifestyle.pace'), 2) || atLeast(num(p, 'personality.agreeableness'), 72)],
  expressive: ['open about feelings', p => atLeast(num(p, 'communication.expressive'), 4)],
  reserved: ['quietly private', p => atMost(num(p, 'communication.expressive'), 2)],
  active: ['active', p => atLeast(num(p, 'lifestyle.active'), 4)],
  creative: ['creative', p => has(p, 'values.top', 'creativity') || atLeast(num(p, 'personality.openness'), 78)],
  family: ['close to family', p => atLeast(num(p, 'background.familyCloseness'), 4)],
  nightlife: ['into nights out', p => atLeast(num(p, 'lifestyle.nightlife'), 4)],
  drinker: ['a regular drinker', p => one(p, 'lifestyle.drinking') === 'regular'],
  smoker: ['a smoker', p => ['yes', 'sometimes'].includes(one(p, 'lifestyle.smoking'))],
  spender: ['a spender', p => one(p, 'future.money') === 'spender'],
  saver: ['a saver', p => one(p, 'future.money') === 'saver'],
};
const VOCAB = Object.keys(WORDS);

const listOf = (p, key, minConfidence) => {
  const c = cell(p, key);
  if (!c || !Array.isArray(c.value)) return [];
  if (c.confidence < minConfidence && c.source !== 'stated') return [];
  return c.value.filter(w => WORDS[w]);
};

/** The words in a's list `key` that b's profile shows. */
function hits(a, b, key, minConfidence = MIN_CONFIDENCE) {
  return listOf(a, key, minConfidence).filter(w => WORDS[w][1](b));
}

/** Does b show anything a has said puts them off? */
const turnedOff = (a, b) => hits(a, b, 'partner.turnOffs', TURNOFF_CONFIDENCE).length > 0;

/** What b is that a is drawn to, as card words. */
const appreciated = (a, b) => hits(a, b, 'partner.appreciates').map(w => WORDS[w][0]);

/** "calm and a planner", "calm, active and a planner". */
function phrase(words) {
  if (words.length <= 1) return words[0] || '';
  return words.slice(0, -1).join(', ') + ' and ' + words[words.length - 1];
}

module.exports = { VOCAB, WORDS, MIN_CONFIDENCE, TURNOFF_CONFIDENCE, hits, turnedOff, appreciated, phrase };
