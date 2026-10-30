// A reviewer's account, for Meta's directory review (SUBMISSION.md): a signed-in
// user who has already had a read and joined Psyche Pair, with a week of
// matches, someone who picked them and a Sync, so every tool has something to
// show on an otherwise empty server.
//
//   PSYCHE_REVIEWER_EMAIL  the reviewer's sign-in email
//   PSYCHE_REVIEWER_CODE   a fixed 6-digit code that signs that email in, in
//                          place of the emailed one (lib/oauth.js verify), for
//                          a reviewer who can't read the inbox
//
// Both off by default; set them for the review and remove them after. Demo
// people are flagged `demo` and only ever match each other (weekly.candidates),
// so no real user sees them or is shown to them. Seeding is idempotent.

const crypto = require('node:crypto');
const store = require('./store');
const { validateProfile } = require('./schema');

const reviewerEmail = () => String(process.env.PSYCHE_REVIEWER_EMAIL || '').trim().toLowerCase();
const reviewerCode = () => String(process.env.PSYCHE_REVIEWER_CODE || '').trim();
const enabled = () => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(reviewerEmail()) && /^\d{6}$/.test(reviewerCode());

/** True when this email and code are the reviewer's. Constant-time. */
function reviewerSignIn(email, code) {
  if (!enabled() || String(email || '').trim().toLowerCase() !== reviewerEmail()) return false;
  const a = crypto.createHash('sha256').update(String(code || '').trim()).digest();
  const b = crypto.createHash('sha256').update(reviewerCode()).digest();
  return crypto.timingSafeEqual(a, b);
}

const c = (value, confidence = 0.8, source = 'observed') => ({ value, source, confidence });

function profile(basics, over = {}) {
  const traits = {
    'personality.mbti': c('ENFJ'), 'personality.openness': c(70), 'personality.conscientiousness': c(65),
    'personality.extraversion': c(60), 'personality.agreeableness': c(75), 'personality.neuroticism': c(40),
    'needs.attachment': c('secure'), 'needs.loveGiving': c(['time', 'acts']), 'needs.loveReceiving': c(['time', 'words']),
    'needs.closeness': c(4), 'needs.reassurance': c(3),
    'lifestyle.social': c(3), 'lifestyle.active': c(4), 'lifestyle.travel': c(4), 'lifestyle.nightlife': c(2),
    'lifestyle.pace': c(4), 'lifestyle.drinking': c('social'), 'lifestyle.smoking': c('no', 0.9, 'stated'),
    'lifestyle.pets': c('wants'), 'lifestyle.interests': c(['hiking', 'food', 'travel', 'coffee', 'board games']),
    'future.kids': c('wants', 0.9, 'stated'), 'future.kidsWhen': c('2_5y', 0.9, 'stated'), 'future.marriage': c('wants', 0.9, 'stated'),
    'future.settle': c('Singapore', 0.9, 'stated'), 'future.ambition': c(4), 'future.money': c('balanced'),
    'future.religion': c('christian', 0.9, 'stated'), 'future.religionImportance': c(2, 0.9, 'stated'), 'future.familyInvolvement': c(3, 0.9, 'stated'),
    'communication.conflict': c('talk_now'), 'communication.expressive': c(4), 'communication.repair': c(4),
    'values.top': c(['kindness', 'family', 'growth']),
    'background.education': c('master', 0.9, 'stated'), 'background.lifeStage': c('established'),
    'background.upbringing': c('Singapore'), 'background.familyCloseness': c(4),
    ...(over.traits || {}),
  };
  return validateProfile({
    basics: { age: 31, city: 'Singapore', intent: 'serious', mode: 'dating', ...basics },
    traits,
    summary: { headline: over.headline || 'Plans the trip, then talks to everyone on it', short: 'Warm, organised and curious.', career: 'Works in a small team, steady and ambitious.' },
    character: over.character,
    patterns: over.patterns,
  }).profile;
}

const MATCHES = [
  { name: 'Jun', headline: 'Weekend climber, weekday builder', character: 'Hiccup', picked: true },
  { name: 'Kai', headline: 'Cooks for everyone, remembers every birthday', character: 'Po' },
  { name: 'Leo', headline: 'Quiet planner with a loud laugh', character: 'Baymax' },
  { name: 'Ravi', headline: 'Reads the map, then takes the scenic route', character: 'Odysseus' },
];

/** Create (or refresh) the reviewer and their demo world. Returns the reviewer's id, or null when off. */
function seed(now = Date.now()) {
  if (!enabled()) return null;
  const email = reviewerEmail();
  let reviewer = store.userByEmail(email);
  if (!reviewer) reviewer = store.createUser({ email, platform: 'muse' }).user;
  const card = {
    firstName: 'Alex', fullName: 'Alex Reviewer', confidence: 74, character: 'Moana', why: 'Sets out before the map is finished, and brings people along.',
    headline: 'Curious, warm, and always one step ahead of the plan', mbti: 'ENFJ',
    letters: [{ letter: 'E', strength: 'moderate' }, { letter: 'N', strength: 'moderate' }, { letter: 'F', strength: 'clear' }, { letter: 'J', strength: 'slight' }],
    patterns: ['The trip planner', 'Warm in a small circle', 'First to help'], motivators: ['benevolence', 'self-direction', 'stimulation'],
    interests: ['hiking', 'food', 'travel'], values: ['Loyalty to a close circle'], bigFive: { openness: 70, conscientiousness: 65, extraversion: 60, agreeableness: 75, neuroticism: 40 },
    loveGiving: ['Quality time', 'Acts of service'],
  };
  store.kvSet('psyche', reviewer.id, { card, pair: true, expiresAt: now + 365 * 86400000 });
  const mine = profile({ firstName: 'Alex', gender: 'woman', seeking: ['man'], ageMin: 27, ageMax: 38, instagram: 'alex.reviewer' },
    { character: { name: 'Moana', why: card.why }, patterns: card.patterns.map(name => ({ name })) });
  store.updateUser(reviewer.id, { demo: true, profile: mine, draft: mine, reviewedAt: reviewer.reviewedAt || now, prefs: reviewer.prefs || { brief: '', must: [], nice: [] } });

  for (const m of MATCHES) {
    const handle = m.name.toLowerCase() + '.demo';
    const demoEmail = `${m.name.toLowerCase()}@demo.psycheai.invalid`;
    const user = store.userByEmail(demoEmail) || store.createUser({ email: demoEmail, platform: 'muse' }).user;
    const p = profile({ firstName: m.name, gender: 'man', seeking: ['woman'], ageMin: 26, ageMax: 36, age: 32, instagram: handle },
      { headline: m.headline, character: { name: m.character, why: 'A demo match for review.' } });
    store.updateUser(user.id, { demo: true, profile: p, draft: p, reviewedAt: now, prefs: { brief: '', must: [], nice: [] }, lastSeenAt: now });
    if (m.picked && !store.allIntros().some(i => i.from === user.id && i.to === reviewer.id)) {
      store.createIntro({ from: user.id, to: reviewer.id, week: require('./weekly').weekKey(now), status: 'pending', createdAt: now });
    }
  }
  return reviewer.id;
}

module.exports = { enabled, reviewerSignIn, seed };
