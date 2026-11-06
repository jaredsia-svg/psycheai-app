// Psyche Together (experimental, branch claude/psyche-together): a deep dive for two
// people in a relationship (README "Psyche Together"). Its own product: Sync stays
// friends-only and never romance, and Psyche Pair stays matching strangers.
//
// Everything about the two people is read, answered and written in each one's own
// Muse, by the skill, and locked there before it's sent (as a Sync is from release
// 164, README "Sync, locked on the device"). This server is a mailbox: it finds a
// couple by a hash of the link's code and keeps three locked boxes, A's profile,
// B's profile and the joint read, which it can't open. It knows two account ids
// are a couple, and when; nothing else.
//
//   together_link   A made a code in their workspace: keep the couple by its hash.
//   together_join   B used A's link (by hash): B joins, once.
//   together_get    The couple's boxes and who has sent theirs.
//   together_put    Replace this person's profile box, or the read once both are in.
//   together_end    Either of them ends it: everything goes, for both.

const store = require('./store');
const notify = require('./notify');
const { e2eBox } = require('./sync');

const COUPLES = 'together';        // hash of the code → { a, b, at, joinedAt, profiles: { a, b }, read }
const OF = 'togetherof';           // userId → hash of their couple's code
const JOIN_DAYS = 30;
const ID = /^[0-9a-f]{64}$/;

const skillOnly = user => (user && user.via === 'skill' ? null : { error: 'Psyche Together runs in the PsycheAI skill, which locks it on the device: install it in Muse first.' });

function link(user, args = {}, now = Date.now()) {
  const no = skillOnly(user);
  if (no) return no;
  const id = args.e2e && ID.test(String(args.e2e.id || '')) ? String(args.e2e.id) : null;
  if (!id) return { error: 'The link id is not valid: update PsycheAI and try again.' };
  const current = store.kvGet(OF, user.id);
  if (current && current !== id && store.kvGet(COUPLES, current)) return { error: 'There\'s a Psyche Together already: end it first ("End Psyche Together").' };
  const row = store.kvGet(COUPLES, id);
  if (row && row.a !== user.id) return { error: 'That link id is taken: make a new link.' };
  if (!row) store.kvSet(COUPLES, id, { a: user.id, b: null, at: now, profiles: { a: null, b: null }, read: null });
  store.kvSet(OF, user.id, id);
  return { ok: true, days: JOIN_DAYS };
}

function join(user, args = {}, now = Date.now()) {
  const no = skillOnly(user);
  if (no) return no;
  const id = args.e2e && ID.test(String(args.e2e.id || '')) ? String(args.e2e.id) : null;
  const row = id && store.kvGet(COUPLES, id);
  if (!row || (!row.b && now - row.at > JOIN_DAYS * 86400000)) return { error: 'That Psyche Together link isn\'t valid or has expired. Ask for a new one.' };
  if (row.a === user.id) return { error: 'That\'s the user\'s own Psyche Together link: it\'s for their partner.' };
  if (row.b && row.b !== user.id) return { error: 'Someone has already joined with that link.' };
  const current = store.kvGet(OF, user.id);
  if (current && current !== id && store.kvGet(COUPLES, current)) return { error: 'There\'s a Psyche Together already: end it first ("End Psyche Together").' };
  if (!row.b) {
    store.kvSet(COUPLES, id, { ...row, b: user.id, joinedAt: now });
    notify.note(row.a, 'together', {}, now);
  }
  store.kvSet(OF, user.id, id);
  return { ok: true, joined: true };
}

function mine(user) {
  const id = store.kvGet(OF, user.id);
  const row = id && store.kvGet(COUPLES, id);
  if (!row || (row.a !== user.id && row.b !== user.id)) return null;
  return { id, row, role: row.a === user.id ? 'a' : 'b' };
}

function get(user) {
  const no = skillOnly(user);
  if (no) return no;
  const m = mine(user);
  if (!m) return { none: true };
  const { row } = m;
  return { e2e: { id: m.id, role: m.role, profiles: row.profiles, read: row.read }, joined: Boolean(row.b),
    sent: { a: Boolean(row.profiles.a), b: Boolean(row.profiles.b) }, written: Boolean(row.read) };
}

function put(user, args = {}) {
  const no = skillOnly(user);
  if (no) return no;
  const m = mine(user);
  if (!m) return { error: 'There\'s no Psyche Together to save to.' };
  const e = args.e2e || {};
  const row = { ...m.row, profiles: { ...m.row.profiles } };
  if (e.profile !== undefined) {
    const box = e2eBox(e.profile);
    if (!box) return { error: 'The locked profile is not valid: update PsycheAI and try again.' };
    row.profiles[m.role] = box;
  }
  if (e.read !== undefined) {
    const box = e2eBox(e.read);
    if (!box) return { error: 'The locked read is not valid: update PsycheAI and try again.' };
    if (!row.b || !row.profiles.a || !row.profiles.b) return { error: 'The read can be saved once both of them have sent theirs.' };
    row.read = box;
  }
  store.kvSet(COUPLES, m.id, row);
  return { ok: true, sent: { a: Boolean(row.profiles.a), b: Boolean(row.profiles.b) }, written: Boolean(row.read) };
}

/** Either of them ends it: the couple and its boxes go, for both, and the other sees only that it ended. */
function end(user) {
  const m = mine(user);
  if (!m) return { ok: true };
  store.kvDel(COUPLES, m.id);
  for (const u of [m.row.a, m.row.b]) if (u && store.kvGet(OF, u) === m.id) store.kvDel(OF, u);
  return { ok: true, ended: true };
}

/** For delete_my_data. */
function forget(userId) {
  end({ id: userId });
  store.kvDel(OF, userId);
}

module.exports = { link, join, get, put, end, forget, JOIN_DAYS };
