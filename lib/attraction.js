// The hidden attraction bucket: 'above' or 'below' average, or null while unknown.
//
// It comes from behaviour, never from a model looking at photos: of the times
// someone's card (with photo) was shown in a weekly drop, how often was it
// picked. Judging faces with a model brings in bias by race, age and body,
// would not pass Meta's review, and is a legal risk in Singapore and the EU.
// Picks from people who saw the photo are what attraction actually looks like.
//
// The rate is smoothed toward a prior so a few early picks do not decide it,
// and nobody gets a bucket before MIN_SHOWN showings. Buckets are relative to
// the pool's median, so they stay half and half as the pool grows. Never shown
// to anyone, including the person themselves.

const MIN_SHOWN = 20;
const PRIOR_PICKS = 2;
const PRIOR_SHOWN = 6;

const rate = s => (s.picked + PRIOR_PICKS) / (s.shown + PRIOR_SHOWN);

/** stats: { [id]: { shown, picked } } → { [id]: 'above' | 'below' | null } */
function computeBuckets(stats) {
  const known = Object.entries(stats).filter(([, s]) => s.shown >= MIN_SHOWN);
  const out = Object.fromEntries(Object.keys(stats).map(id => [id, null]));
  if (known.length < 2) return out;
  const rates = known.map(([, s]) => rate(s)).sort((x, y) => x - y);
  const mid = rates.length / 2;
  const median = rates.length % 2 ? rates[Math.floor(mid)] : (rates[mid - 1] + rates[mid]) / 2;
  for (const [id, s] of known) out[id] = rate(s) >= median ? 'above' : 'below';
  return out;
}

module.exports = { MIN_SHOWN, computeBuckets };
