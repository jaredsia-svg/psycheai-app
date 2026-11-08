// Psyche Together (branch claude/psyche-together): a deep dive for two
// people in a relationship (README "Psyche Together"). Its own product: Sync stays
// friends-only and never romance, and Psyche Pair stays matching strangers.
//
// Everything about the two people is read, answered and written in each one's own
// Muse, by the skill, and locked there before it's sent (as a Sync is from release
// 164, README "Sync, locked on the device"). This server is a mailbox: it finds a
// couple by a hash of the link's code and keeps locked boxes, A's profile, B's
// profile, the joint read and each one's card picture, which it can't open. It knows two account ids
// are a couple, and when; nothing else.
//
//   together_link   A made a code in their workspace: keep the couple by its hash.
//   together_join   B used A's link (by hash): B joins, once.
//   together_get    The couple's boxes and who has sent theirs.
//   together_put    Replace this person's profile box or card picture, or the read once both are in.
//   together_end    Either of them ends it: everything goes, for both.

const store = require('./store');
const notify = require('./notify');

const COUPLES = 'together';        // hash of the code → { a, b, at, joinedAt, profiles: { a, b }, read }
const OF = 'togetherof';           // userId → hash of their couple's code
const JOIN_DAYS = 30;
const ID = /^[0-9a-f]{64}$/;

// Off unless PSYCHE_TOGETHER=1 (README "Psyche Together"): built on its branch, switched on only once its own skill has passed
// Muse's safety check on fresh installs.
const enabled = () => process.env.PSYCHE_TOGETHER === '1';
const skillOnly = user => (!enabled() ? { error: 'Psyche Together isn\'t available yet.' }
  : user && user.via === 'skill' ? null : { error: 'Psyche Together runs in its own skill, which locks it on the device: install it in Muse first.' });

// Prepared for a paid Psyche Together (PLAN.md), not built: when it is, this says whether this account may start one,
// and if not returns { access: { say, url } } pointing to the website, where it is bought (CLAUDE.md: nothing is sold
// inside the host). The one who starts it is the one it applies to; joining stays free. Today everyone may.
const access = user => null;

function link(user, args = {}, now = Date.now()) {
  const no = skillOnly(user);
  if (no) return no;
  const gate = access(user);
  if (gate) return { access: gate };
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

// The boxes (README "Psyche Together, release 21") are kept as sealed blobs, each its own key, never in the rows loaded
// at boot: a profile holds a full Psyche report, and the conversation sample is up to 120,000 characters, so a
// couple's boxes come to about 1 MB. The row keeps only which boxes exist. A couple saved before that, with its
// boxes in the row, still reads; each box moves to a blob when it's next saved.
const KINDS = ['profile', 'chat', 'pic'];
const BOX_MAX = 250000;                        // characters of one box's ciphertext: under one /mcp request (256 KB)
const blobKey = (id, kind, role) => 'together:' + id + ':' + kind + (role ? ':' + role : '');
const INLINE = { profile: 'profiles', pic: 'pics' };

function box(b) {
  if (!b || typeof b !== 'object' || Array.isArray(b) || b.v !== 'e2e1') return null;
  const { n, c, t } = b;
  if (![n, c, t].every(x => typeof x === 'string' && B64.test(x)) || n.length !== 22 || t.length !== 43 || c.length > BOX_MAX) return null;
  return { v: 'e2e1', n, c, t };
}
const B64 = /^[A-Za-z0-9_-]+$/;
const has = (row, kind, role) => Boolean(((row.has || {})[kind] || {})[role] || (INLINE[kind] && (row[INLINE[kind]] || {})[role]));
const hasRead = row => Boolean((row.has || {}).read || row.read);

async function load(id, row, kind, role) {
  if (role ? ((row.has || {})[kind] || {})[role] : (row.has || {})[kind]) {
    const raw = await store.getBlob(blobKey(id, kind, role));
    try { return raw ? JSON.parse(raw.toString('utf8')) : null; } catch (err) { return null; }
  }
  return role ? (INLINE[kind] ? (row[INLINE[kind]] || {})[role] || null : null) : row[kind] || null;
}

async function get(user) {
  const no = skillOnly(user);
  if (no) return no;
  const m = mine(user);
  if (!m) return { none: true };
  const { row, id } = m;
  const e2e = { id, role: m.role, read: await load(id, row, 'read') };
  for (const kind of KINDS) {
    const out = {};
    for (const r of ['a', 'b']) out[r] = await load(id, row, kind, r);
    e2e[kind === 'profile' ? 'profiles' : kind === 'pic' ? 'pics' : 'chats'] = out;
  }
  return { e2e, joined: Boolean(row.b), sent: { a: has(row, 'profile', 'a'), b: has(row, 'profile', 'b') }, written: hasRead(row) };
}

async function put(user, args = {}) {
  const no = skillOnly(user);
  if (no) return no;
  const m = mine(user);
  if (!m) return { error: 'There\'s no Psyche Together to save to.' };
  const e = args.e2e || {};
  const row = { ...m.row, has: { profile: {}, chat: {}, pic: {}, read: false, ...(m.row.has || {}) } };
  for (const kind of KINDS) row.has[kind] = { ...(row.has[kind] || {}) };
  const writes = [];
  for (const kind of KINDS) {
    if (e[kind] === undefined) continue;
    const b = box(e[kind]);
    if (!b) return { error: 'The locked ' + (kind === 'pic' ? 'card picture' : kind === 'chat' ? 'conversation' : 'profile') + ' is not valid: update Psyche Together and try again.' };
    writes.push([blobKey(m.id, kind, m.role), b]);
    row.has[kind][m.role] = true;
    if (INLINE[kind] && row[INLINE[kind]]) row[INLINE[kind]] = { ...row[INLINE[kind]], [m.role]: null };
  }
  if (e.read !== undefined) {
    const b = box(e.read);
    if (!b) return { error: 'The locked read is not valid: update Psyche Together and try again.' };
    if (!row.b || !has(row, 'profile', 'a') || !has(row, 'profile', 'b')) return { error: 'The read can be saved once both of them have sent theirs.' };
    writes.push([blobKey(m.id, 'read'), b]);
    row.has.read = true;
    row.read = null;
  }
  for (const [k, b] of writes) await store.putBlob(k, Buffer.from(JSON.stringify(b)));
  store.kvSet(COUPLES, m.id, row);
  return { ok: true, sent: { a: has(row, 'profile', 'a'), b: has(row, 'profile', 'b') }, written: hasRead(row) };
}

/** Either of them ends it: the couple and its boxes go, for both, and the other sees only that it ended. */
async function end(user) {
  const m = mine(user);
  if (!m) return { ok: true };
  store.kvDel(COUPLES, m.id);
  for (const u of [m.row.a, m.row.b]) if (u && store.kvGet(OF, u) === m.id) store.kvDel(OF, u);
  const keys = [blobKey(m.id, 'read'), ...KINDS.flatMap(k => ['a', 'b'].map(r => blobKey(m.id, k, r)))];
  for (const k of keys) await store.delBlob(k);
  return { ok: true, ended: true };
}

/** For delete_my_data. */
function forget(userId) {
  const done = end({ id: userId });
  store.kvDel(OF, userId);
  return done;
}

module.exports = { link, join, get, put, end, forget, enabled, JOIN_DAYS, BOX_MAX, blobKey };
