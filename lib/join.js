// Joining Psyche Pair from a read on psycheai.io (PLAN.md step 6): people who
// made their read the upload way, and Muse readers whose read went deeper
// when they added WhatsApp or Google there.
//
//   psycheai.io  "Use for Psyche Pair": after the reader agrees, the page posts
//                a card-level subset of their read (the structured fields
//                only: no report text, no data) to app.psycheai.io/join.
//   /join        keeps it for an hour under a random id, then the usual
//                sign-in (email code, Google or Apple; oauth.startWeb).
//   signed in    joinRead() lays it on their account: the card summary (as
//                publish_psyche keeps it) and the matching traits it
//                supports, source "uploaded". A trait the user stated is
//                never overwritten. A new email makes a new account.
//
// The host then shows them their card to check and asks what only they can
// answer, as for anyone (lib/instructions.js, the pair guide).
//
// Only what's mapped below is read from the post, so anything else in it is
// dropped unread. Every value is checked against the schema (validateProfile).

const crypto = require('node:crypto');
const store = require('./store');
const psyche = require('./psyche');
const { FIELDS, validateProfile, MOTIVATORS } = require('./schema');

const TABLE = 'joins';
const TTL_MS = 60 * 60000;
const MAX_BYTES = 16 * 1024;
const KEEP_DAYS = 30;

const LOVE = [['words', /word|affirm/i], ['time', /time/i], ['gifts', /gift/i], ['acts', /act|service/i], ['touch', /touch|physical/i]];
const VALUE_WORDS = [['honesty', /honest|truth/i], ['kindness', /kind|compassion|care for/i], ['ambition', /ambition|achiev|success/i],
  ['family', /family|close ties/i], ['adventure', /adventur|explor/i], ['faith', /faith|spiritual|god/i], ['humour', /humou?r|laugh|fun/i],
  ['loyalty', /loyal/i], ['growth', /growth|learn/i], ['independence', /independen|freedom/i], ['creativity', /creativ/i], ['stability', /stabil|security/i]];

/** How sure the read was, on the plugin's scale: 0.9 / 0.7 / 0.5 (lib/instructions.js CONFIDENCE). */
function confidenceOf(read) {
  const score = Number(read && read.confidence && read.confidence.score);
  return !Number.isFinite(score) ? 0.5 : score >= 80 ? 0.9 : score >= 60 ? 0.7 : 0.5;
}

const fromList = (list, words, field) => {
  const allowed = (FIELDS[field] && FIELDS[field].options) || [];
  const out = [];
  for (const item of Array.isArray(list) ? list : []) {
    const text = String((item && (item.language || item.value || item.name)) || item || '');
    const hit = words.find(([key, re]) => re.test(text) && allowed.includes(key));
    if (hit && !out.includes(hit[0])) out.push(hit[0]);
  }
  return out;
};

/** The matching traits a read supports: { key: { value, source: 'uploaded', confidence } }. */
function traitsFrom(read) {
  const r = read && typeof read === 'object' ? read : {};
  const conf = confidenceOf(r);
  const cell = value => ({ value, source: 'uploaded', confidence: conf });
  const out = {};
  const type = r.mbti && String(r.mbti.type || '').toUpperCase();
  if (/^[EI][NS][TF][JP]$/.test(type || '')) out['personality.mbti'] = cell(type);
  for (const k of ['openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism']) {
    const s = Number(r.bigFive && r.bigFive[k] && r.bigFive[k].score);
    if (Number.isFinite(s)) out['personality.' + k] = cell(Math.max(0, Math.min(100, Math.round(s))));
  }
  const style = String((r.attachment && r.attachment.style) || '').toLowerCase();
  const attach = ['fearful', 'anxious', 'avoidant', 'secure'].find(w => style.includes(w));
  // Attachment is the softest thing a read says, so it is held a step lower.
  if (attach) out['needs.attachment'] = { value: attach, source: 'uploaded', confidence: Math.min(conf, 0.5) };
  const love = (r.relationship && r.relationship.loveLanguages) || {};
  const giving = fromList(love.giving, LOVE, 'needs.loveGiving').slice(0, 2);
  const receiving = fromList(love.receiving, LOVE, 'needs.loveReceiving').slice(0, 2);
  if (giving.length) out['needs.loveGiving'] = cell(giving);
  if (receiving.length) out['needs.loveReceiving'] = cell(receiving);
  const interests = (Array.isArray(r.interests) ? r.interests : []).map(i => String((i && i.name) || i || '').toLowerCase().replace(/\s+/g, ' ').trim())
    .filter(t => t && t.length <= 30);
  if (interests.length) out['lifestyle.interests'] = cell([...new Set(interests)].slice(0, 20));
  const motivators = (Array.isArray(r.topMotivators) ? r.topMotivators : []).map(m => String(m).toLowerCase()).filter(m => MOTIVATORS.includes(m));
  if (motivators.length) out['values.motivators'] = cell([...new Set(motivators)].slice(0, 3));
  const values = fromList(r.values, VALUE_WORDS, 'values.top').slice(0, 3);
  if (values.length) out['values.top'] = cell(values);
  // Through the schema, so nothing it would refuse is kept.
  const { profile } = validateProfile({ traits: out });
  return profile.traits;
}

/** POST /join: keep the read for an hour. Resolves to { id } or { error }. */
function hold(raw, now = Date.now()) {
  if (!raw || raw.length > MAX_BYTES) return { error: 'That read is too large to send.' };
  let read;
  try { read = JSON.parse(raw); } catch { return { error: 'That read could not be read.' }; }
  if (!read || typeof read !== 'object' || Array.isArray(read)) return { error: 'That read could not be read.' };
  const name = String(read.name || '').replace(/\s+/g, ' ').trim().slice(0, 60);
  const card = psyche.summarize(read, name);
  const traits = traitsFrom(read);
  if (!card.character && !Object.keys(traits).length) return { error: 'That read has nothing Psyche Pair can use.' };
  const id = crypto.randomBytes(18).toString('base64url');
  store.kvSet(TABLE, id, { card, traits, expiresAt: now + TTL_MS });
  return { id };
}

const held = (id, now = Date.now()) => {
  const j = store.kvGet(TABLE, String(id || ''));
  return j && j.expiresAt > now ? j : null;
};

/** Lay a held read on an account. Stated traits are never replaced. */
function joinRead(userId, id, now = Date.now()) {
  const j = held(id, now);
  store.kvDel(TABLE, String(id || ''));
  const user = store.getUser(userId);
  if (!j || !user) return { error: 'This link has expired. Go back to psycheai.io and try again.' };
  store.kvSet('psyche', userId, { card: j.card, pair: true, expiresAt: now + KEEP_DAYS * 86400000 });
  const merge = profile => {
    const base = profile || { basics: {}, traits: {}, summary: {} };
    const traits = { ...base.traits };
    let changed = 0;
    for (const [key, cell] of Object.entries(j.traits)) {
      if (traits[key] && traits[key].source === 'stated') continue;
      traits[key] = cell;
      changed++;
    }
    const basics = { ...base.basics };
    if (!basics.firstName && j.card.firstName && j.card.firstName !== 'You') basics.firstName = j.card.firstName;
    const summary = { ...base.summary };
    if (!summary.headline && j.card.headline) summary.headline = j.card.headline.slice(0, 80);
    const patterns = base.patterns || (j.card.patterns || []).map(name => ({ name }));
    return { next: { ...base, basics, traits, summary, patterns }, changed };
  };
  const draft = merge(user.draft || user.profile);
  const patch = { draft: draft.next, joinedFromReadAt: now };
  if (user.profile) patch.profile = merge(user.profile).next;
  store.updateUser(userId, patch);
  return { ok: true, changed: draft.changed, live: Boolean(user.profile) };
}

function sweep(now = Date.now()) {
  for (const [id, j] of store.kvAll(TABLE)) if (j.expiresAt < now) store.kvDel(TABLE, id);
}

module.exports = { TTL_MS, MAX_BYTES, traitsFrom, hold, held, joinRead, sweep };
