// Custom questions: must-haves the profile cannot answer.
//
// A user says their match must be open to keeping reptiles. No profile field
// covers that, so the host adds a yes / maybe / no question to the shared bank
// ("Would you be okay with a partner who keeps pet reptiles?") and uses it as
// a must-have rule, field 'q.open_to_pet_reptiles'.
//
// People whose answer is unknown are held back from that user's drop, and the
// question is queued for them, but only if they would otherwise clear the
// bar. Their host asks it openly the next time they visit, as a question that
// sharpens their own matches. It never says who asked, and the asker never
// sees the answer, only who reaches their drop. Answers are kept on the
// answerer's profile as stated, so one answer serves every future asker.
//
// The same queue carries stated-only profile fields ('f:background.ethnicity'):
// when someone's must-have is on a field a strong match left empty, that match
// is asked whether they want to add it, with the field's own options, and may
// skip. It is never filled in for them.
//
// Every question comes back with fixed options, so the host can show them as
// buttons rather than asking the user to type.
//
// Limits: at most WEEKLY_LIMIT questions handed to a host per person per
// week; queued questions lapse after QUEUE_TTL_DAYS and are not asked again
// for SKIP_DAYS; only yes / maybe / no questions about lifestyle and
// preferences, never the topics in BANNED.

const store = require('./store');
const { FIELDS, checkValue } = require('./schema');

const ANSWERS = ['yes', 'maybe', 'no'];
const WEEKLY_LIMIT = 3;
const QUEUE_TTL_DAYS = 14;
const SKIP_DAYS = 60;
const TEXT_MAX = 140;
const DAY = 86400000;

// Topics a custom question may never touch. Some have their own field and are
// asked by the host itself (religion, kids); the rest are not asked at all.
const BANNED = [
  [/\b(sex\w*|virgin\w*|kink\w*|fetish\w*|nude\w*|nsfw|hook ?ups?|body count)\b/i, 'sexual topics'],
  [/\b(income\w*|salar\w*|earn\w*|rich\w*|wealth\w*|net worth|money|debts?|propert\w*|cars?|paid|pays?)\b/i, 'money and wealth'],
  [/\b(race|racial\w*|ethnic\w*|skin|colou?red|chinese|malay|indian|eurasian|white|black|asian|caucasian)\b/i, 'race and ethnicity'],
  [/\b(religio\w*|church\w*|mosques?|temples?|god|faith\w*|pray\w*)\b/i, 'religion (it has its own field)'],
  [/\b(health\w*|disease\w*|disab\w*|ill|illness\w*|medic\w*|hiv|stds?|stis?|depress\w*|anxiety|therap\w*|mental\w*)\b/i, 'health'],
  [/\b(weigh\w*|fat\w*|thin\w*|heights?|tall\w*|short\w*|bod(y|ies)|looks?|attractiv\w*|pretty|handsome|ugly)\b/i, 'bodies and looks'],
  [/\b(pregnan\w*|fertil\w*|abortion\w*|kids?|child\w*|marr\w*)\b/i, 'kids and marriage (they have their own fields)'],
  [/\b(criminal\w*|arrest\w*|prison\w*|jail\w*|visas?|immigra\w*|citizen\w*|passports?|politic\w*|vot\w*)\b/i, 'legal status and politics'],
];

const slug = s => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 48);
const normText = s => String(s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, '').replace(/\s+/g, ' ').trim();

function checkQuestion(text) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  if (!t) return 'text is required';
  if (t.length > TEXT_MAX) return 'text is over ' + TEXT_MAX + ' characters';
  if (!t.endsWith('?')) return 'text must be a question someone can answer yes, maybe or no';
  if (!/^(would|are|do|could|can|is|have|will)\b/i.test(t)) return 'start with Would, Are, Do, Could, Can, Is, Have or Will';
  for (const [re, topic] of BANNED) if (re.test(t)) return 'custom questions cannot be about ' + topic;
  return null;
}

/** Add a question to the bank, or return the existing one it duplicates. */
function addQuestion({ key, text }, now = Date.now()) {
  const k = slug(key || text);
  if (k.length < 3) return { error: 'key is too short' };
  const existing = store.getQuestion(k) || store.allQuestions().find(q => normText(q.text) === normText(text));
  if (existing) return { key: existing.key, text: existing.text, reused: true };
  const why = checkQuestion(text);
  if (why) return { error: why };
  const q = store.addQuestion({ key: k, text: String(text).replace(/\s+/g, ' ').trim(), createdAt: now });
  return { key: q.key, text: q.text, reused: false };
}

const isField = key => String(key).startsWith('f:');
const fieldOf = key => FIELDS[String(key).slice(2)];

function known(key) {
  return isField(key) ? Boolean(fieldOf(key) && fieldOf(key).statedOnly) : Boolean(store.getQuestion(key));
}

const pretty = v => String(v).replace(/_/g, ' ');

/** What the host shows: the text and the buttons. */
function describe(key) {
  if (isField(key)) {
    const spec = fieldOf(key);
    const label = spec.label.replace(/\s*\(optional\)/i, '').toLowerCase();
    return {
      key,
      text: `Would you like to add your ${label} to your profile? Some of your strongest matches care about it. Skip any time.`,
      options: spec.kind === 'enum' ? [...spec.options.map(pretty), 'skip'] : ['type a number', 'skip'],
    };
  }
  return { key, text: store.getQuestion(key).text, options: [...ANSWERS, 'skip'] };
}

function hasAnswer(user, key) {
  if (isField(key)) return Boolean(user.profile && user.profile.traits[key.slice(2)]);
  return Boolean((user.answers || {})[key]);
}

/** Queue a question for someone, unless they answered, skipped it lately, or have it queued. */
function enqueue(userId, key, now = Date.now()) {
  const user = store.getUser(userId);
  if (!user || !known(key)) return false;
  if (hasAnswer(user, key)) return false;
  const skippedAt = (user.skipped || {})[key];
  if (skippedAt && now - skippedAt < SKIP_DAYS * DAY) return false;
  const queue = store.getQueue(userId);
  if (queue.some(q => q.key === key)) return false;
  store.setQueue(userId, [...queue, { key, at: now }]);
  return true;
}

/** What the host should ask this visit: up to the week's allowance, oldest first. */
function pendingFor(userId, week, now = Date.now()) {
  const user = store.getUser(userId);
  if (!user) return [];
  const live = [];
  const skipped = { ...(user.skipped || {}) };
  for (const q of store.getQueue(userId)) {
    if (now - q.at > QUEUE_TTL_DAYS * DAY) skipped[q.key] = now;
    else live.push(q);
  }
  store.updateUser(userId, { skipped });
  store.setQueue(userId, live);
  const delivered = store.getDelivered(userId, week);
  const again = live.filter(q => delivered.includes(q.key));
  const fresh = live.filter(q => !delivered.includes(q.key)).slice(0, Math.max(0, WEEKLY_LIMIT - delivered.length));
  fresh.forEach(q => store.addDelivered(userId, week, q.key));
  return [...again, ...fresh].filter(q => known(q.key)).map(q => describe(q.key));
}

function answer(userId, key, value, now = Date.now()) {
  const user = store.getUser(userId);
  if (!user) return { error: 'No such user.' };
  if (!known(key)) return { error: 'No such question.' };
  if (isField(key) && value !== 'skip') {
    const field = key.slice(2);
    const spec = FIELDS[field];
    const raw = spec.kind === 'int' ? Number(value) : String(value).trim().toLowerCase().replace(/ /g, '_');
    const r = checkValue(spec, raw);
    if (!r.ok || r.value === null) return { error: field + ' ' + (r.why || 'needs a value') };
    if (!user.profile) return { error: 'Confirm your profile first.' };
    const cell = { value: r.value, source: 'stated', confidence: 0.9 };
    store.updateUser(userId, {
      profile: { ...user.profile, traits: { ...user.profile.traits, [field]: cell } },
      ...(user.draft ? { draft: { ...user.draft, traits: { ...user.draft.traits, [field]: cell } } } : {}),
    });
  } else if (value === 'skip') {
    store.updateUser(userId, { skipped: { ...(user.skipped || {}), [key]: now } });
  } else if (ANSWERS.includes(value)) {
    store.updateUser(userId, { answers: { ...(user.answers || {}), [key]: value } });
  } else {
    return { error: 'answer must be yes, maybe, no or skip' };
  }
  store.setQueue(userId, store.getQueue(userId).filter(q => q.key !== key));
  return { saved: true };
}

module.exports = { ANSWERS, WEEKLY_LIMIT, QUEUE_TTL_DAYS, BANNED, checkQuestion, addQuestion, enqueue, pendingFor, answer, describe, slug };
