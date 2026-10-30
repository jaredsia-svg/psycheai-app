// State. Held in memory for speed and written through to Upstash Redis
// (UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN, as PsycheAI uses), so a
// restart or a redeploy loses nothing. Without Upstash it stays in memory, or
// in a JSON file for a dev server (PSYCHE_DATA_FILE).
//
// Every write goes through a function here, and each one marks the record it
// changed. A flush, at most every FLUSH_MS, writes each marked record to its
// collection's Redis hash (pp:<collection>, field = record key), or removes it
// if it is gone; lists are written whole. load() reads it all back at start.
// One server instance at a time: two would overwrite each other.
//
// Encrypted at rest: every value is sealed with AES-256-GCM under
// PSYCHE_STORE_KEY before it is written, bound to its collection and key, so
// a leaked Upstash token or backup reads as noise and a sealed record cannot
// be moved to another key. The key lives only in the server's environment.
// With Upstash configured and no key, load() refuses to start: we fail closed.
// This does not protect against a compromised server, which holds the key.
//
// Emails are kept apart from profiles: user records carry no email. The
// address sits in its own collection, and the lookup from email to user goes
// through an HMAC of the address, so not even Redis field names show one.
//
// What is held, and nothing else:
//   users     id → { id, platform, profile (confirmed), draft, prefs,
//                    reviewedAt, blocked[], paused, answers, skipped,
//                    lastSeenAt, lastDigestAt, createdAt }
//   tokens    sha256(token) → { userId, kind: 'access'|'refresh', clientId, expiresAt }
//             only hashes are kept, so a leaked store cannot sign anyone in
//   drops     'id|week' → candidate ids shown that week
//   picks     'id|week' → candidate ids picked that week
//   intros    id → { id, from, to, week, status, linkToken, chatTokens, instagram, createdAt, respondedAt }
//   stats     id → { shown, picked } for the attraction bucket
//   questions key → { key, text, createdAt }: the shared bank of custom
//             yes/maybe/no questions (lib/questions.js)
//   queue     id → [{ key, at }] questions waiting to be asked of this person
//   delivered 'id|week' → question keys handed to their host that week
//   chats     intro id → { messages: [{ from, at, box }], lastRead, heldUntil, ended }
//             messages are sealed (lib/chat.js); the store never sees text
//   reports   [{ from, about, introId, reason, at }]
//   outcomes  [{ introId, by, met, again, at }] for calibration
//   emails    id → email address
//   emailIndex hmac(email) → id
//   kv        table → key → value, for short-lived records: OAuth clients,
//             sign-in requests and codes (lib/oauth.js), notifications waiting
//             for the digest (lib/notify.js), sealed read links (lib/reads.js)

const fs = require('node:fs');
const crypto = require('node:crypto');

const FILE = process.env.PSYCHE_DATA_FILE || '';
const REDIS_URL = (process.env.UPSTASH_REDIS_REST_URL || '').replace(/\/$/, '');
const REDIS_TOKEN = process.env.UPSTASH_REDIS_REST_TOKEN || '';
const PREFIX = process.env.PSYCHE_REDIS_PREFIX || 'pp:';
const FLUSH_MS = 200;
const MAPS = ['users', 'emails', 'emailIndex', 'tokens', 'drops', 'picks', 'intros', 'stats', 'questions', 'queue', 'delivered', 'chats'];

// The at-rest key: 32 bytes of base64 as is, any other string hashed down.
const RAW_STORE_KEY = process.env.PSYCHE_STORE_KEY || '';
const STORE_KEY = RAW_STORE_KEY
  ? (Buffer.from(RAW_STORE_KEY, 'base64').length === 32 ? Buffer.from(RAW_STORE_KEY, 'base64') : crypto.createHash('sha256').update(RAW_STORE_KEY).digest())
  : null;
const INDEX_KEY = STORE_KEY ? crypto.createHmac('sha256', STORE_KEY).update('email-index').digest() : crypto.randomBytes(32);

const SEALED = 'v1.';
function seal(text, where) {
  if (!STORE_KEY) return text;
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', STORE_KEY, iv);
  c.setAAD(Buffer.from(where));
  const data = Buffer.concat([c.update(text, 'utf8'), c.final()]);
  return SEALED + [iv, c.getAuthTag(), data].map(x => x.toString('base64url')).join('.');
}
function unseal(stored, where) {
  if (typeof stored !== 'string' || !stored.startsWith(SEALED)) return stored;
  if (!STORE_KEY) throw new Error('store holds sealed data but PSYCHE_STORE_KEY is not set');
  const [iv, tag, data] = stored.slice(SEALED.length).split('.').map(x => Buffer.from(x, 'base64url'));
  const d = crypto.createDecipheriv('aes-256-gcm', STORE_KEY, iv);
  d.setAAD(Buffer.from(where));
  d.setAuthTag(tag);
  return Buffer.concat([d.update(data), d.final()]).toString('utf8');
}

/** The lookup key for an email address: an HMAC, never the address. */
const emailKey = email => crypto.createHmac('sha256', INDEX_KEY).update(String(email).trim().toLowerCase()).digest('base64url');
// An Instagram handle, for Sync's keys, kept apart from emails' by its prefix.
const handleKey = handle => crypto.createHmac('sha256', INDEX_KEY).update('ig:' + String(handle).trim().replace(/^@/, '').toLowerCase()).digest('base64url');
const LISTS = ['reports', 'outcomes'];

let state = empty();

function empty() {
  return { users: {}, emails: {}, emailIndex: {}, tokens: {}, drops: {}, picks: {}, intros: {}, stats: {}, reports: [],
    questions: {}, queue: {}, delivered: {}, chats: {}, outcomes: [], kv: {} };
}

// ---------- persistence ----------

const dirty = new Map();   // collection → Set of keys ('' for a whole list)
let timer = null;

function touch(collection, key = '') {
  if (!dirty.has(collection)) dirty.set(collection, new Set());
  dirty.get(collection).add(key);
  schedule();
}

function schedule() {
  if (timer || (!REDIS_URL && !FILE)) return;
  timer = setTimeout(() => { timer = null; flush().catch(err => console.error('[store] flush failed:', err.message)); }, FLUSH_MS);
  timer.unref();
}

async function redis(commands) {
  const res = await fetch(REDIS_URL + '/pipeline', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + REDIS_TOKEN, 'Content-Type': 'application/json' },
    body: JSON.stringify(commands),
  });
  if (!res.ok) throw new Error('upstash ' + res.status);
  const out = await res.json();
  const bad = out.find(r => r && r.error);
  if (bad) throw new Error('upstash ' + bad.error);
  return out.map(r => r.result);
}

const mapOf = collection => (collection.startsWith('kv:') ? (state.kv[collection.slice(3)] || {}) : state[collection]);

/** Write every marked record. Safe to call any time; tests and shutdown call it directly. */
async function flush() {
  if (!dirty.size) return;
  const batch = new Map(dirty);
  dirty.clear();
  if (FILE && !REDIS_URL) {
    fs.writeFileSync(FILE + '.tmp', JSON.stringify(state));
    fs.renameSync(FILE + '.tmp', FILE);
    return;
  }
  if (!REDIS_URL) return;
  const commands = [];
  for (const [collection, keys] of batch) {
    if (LISTS.includes(collection)) { commands.push(['SET', PREFIX + collection, seal(JSON.stringify(state[collection]), collection)]); continue; }
    if (collection.startsWith('kv:')) commands.push(['SADD', PREFIX + 'kv-tables', collection.slice(3)]);
    const map = mapOf(collection);
    for (const key of keys) {
      if (map[key] === undefined) commands.push(['HDEL', PREFIX + collection, key]);
      else commands.push(['HSET', PREFIX + collection, key, seal(JSON.stringify(map[key]), collection + '|' + key)]);
    }
  }
  try {
    for (let i = 0; i < commands.length; i += 500) await redis(commands.slice(i, i + 500));
  } catch (err) {
    // Mark it all again so the next flush retries.
    for (const [collection, keys] of batch) for (const key of keys) touch(collection, key);
    throw err;
  }
}

// Blobs: the photos people add for Psyche Pair (lib/photos.js). Never in
// `state`, which is loaded whole at boot and flushed in batches: each blob is
// its own Upstash key, sealed like every record, read only when a card shows
// it. In memory without Upstash (dev and tests).
const blobs = new Map();
const blobKey = key => PREFIX + 'blob:' + key;
async function putBlob(key, buf) {
  if (!REDIS_URL) { blobs.set(key, Buffer.from(buf)); return; }
  await redis([['SET', blobKey(key), seal(Buffer.from(buf).toString('base64'), 'blob|' + key)]]);
}
async function getBlob(key) {
  if (!REDIS_URL) return blobs.has(key) ? Buffer.from(blobs.get(key)) : null;
  const [stored] = await redis([['GET', blobKey(key)]]);
  return stored ? Buffer.from(unseal(stored, 'blob|' + key), 'base64') : null;
}
async function delBlob(key) {
  if (!REDIS_URL) { blobs.delete(key); return; }
  await redis([['DEL', blobKey(key)]]);
}

/** Read everything back: from Upstash, or the dev file. */
async function load() {
  if (REDIS_URL) {
    if (!STORE_KEY) throw new Error('PSYCHE_STORE_KEY must be set when Upstash is used: the store is encrypted at rest');
    const kvTables = (await redis([['SMEMBERS', PREFIX + 'kv-tables']]))[0] || [];
    const hashNames = [...MAPS, ...kvTables.map(t => 'kv:' + t)];
    const results = await redis([...hashNames.map(n => ['HGETALL', PREFIX + n]), ...LISTS.map(n => ['GET', PREFIX + n])]);
    state = empty();
    hashNames.forEach((name, i) => {
      const flat = results[i] || [];
      const map = {};
      for (let j = 0; j < flat.length; j += 2) map[flat[j]] = JSON.parse(unseal(flat[j + 1], name + '|' + flat[j]));
      if (name.startsWith('kv:')) state.kv[name.slice(3)] = map; else state[name] = map;
    });
    LISTS.forEach((name, i) => { const raw = results[hashNames.length + i]; state[name] = raw ? JSON.parse(unseal(raw, name)) : []; });
    return;
  }
  if (FILE && fs.existsSync(FILE)) state = { ...empty(), ...JSON.parse(fs.readFileSync(FILE, 'utf8')) };
}

// ---------- users and tokens ----------

const newId = (prefix) => prefix + '_' + crypto.randomBytes(9).toString('base64url');
const hash = token => crypto.createHash('sha256').update(String(token)).digest('base64url');
const ACCESS_TTL = 30 * 86400000;
const REFRESH_TTL = 180 * 86400000;

/** A new bearer token for this user; only its hash is stored. */
function issueToken(userId, kind = 'access', clientId = null, now = Date.now()) {
  const token = crypto.randomBytes(32).toString('base64url');
  const key = hash(token);
  state.tokens[key] = { userId, kind, clientId, expiresAt: now + (kind === 'refresh' ? REFRESH_TTL : ACCESS_TTL) };
  touch('tokens', key);
  return token;
}

/** The record behind a token of this kind, if it is live. */
function tokenRecord(token, kind = 'access', now = Date.now()) {
  const rec = state.tokens[hash(token)];
  if (!rec || rec.kind !== kind || rec.expiresAt < now || !state.users[rec.userId]) return null;
  return rec;
}

function revokeToken(token) { const key = hash(token); delete state.tokens[key]; touch('tokens', key); }

function createUser({ email, platform }) {
  const id = newId('u');
  if (email) {
    state.emails[id] = String(email).trim();
    touch('emails', id);
    const k = emailKey(email);
    state.emailIndex[k] = id;
    touch('emailIndex', k);
  }
  state.users[id] = { id, platform, profile: null, draft: null, prefs: { brief: '', must: [], nice: [] },
    reviewedAt: null, blocked: [], paused: false, answers: {}, skipped: {}, lastSeenAt: null, lastDigestAt: null, createdAt: Date.now() };
  touch('users', id);
  return { user: state.users[id], token: issueToken(id) };
}

const userByToken = token => { const rec = tokenRecord(token); return rec ? state.users[rec.userId] : null; };
const userByEmail = email => state.users[state.emailIndex[emailKey(email)]] || null;
const emailOf = id => state.emails[id] || null;

/** Give an account an email (an invisible account adding one later). False if the email is someone else's. */
function setEmail(id, email) {
  if (!state.users[id]) return false;
  const k = emailKey(email);
  if (state.emailIndex[k] && state.emailIndex[k] !== id) return false;
  if (state.emails[id]) { const old = emailKey(state.emails[id]); delete state.emailIndex[old]; touch('emailIndex', old); }
  state.emails[id] = String(email).trim(); touch('emails', id);
  state.emailIndex[k] = id; touch('emailIndex', k);
  return true;
}
const getUser = id => state.users[id] || null;
const allUsers = () => Object.values(state.users);

function updateUser(id, patch) {
  Object.assign(state.users[id], patch);
  touch('users', id);
  return state.users[id];
}

function dropKeys(collection, test) {
  for (const key of Object.keys(state[collection])) {
    if (test(key, state[collection][key])) { delete state[collection][key]; touch(collection, key); }
  }
}

/** Delete everything held about a person, including intros either way. */
function deleteUser(id) {
  delete state.users[id]; touch('users', id);
  if (state.emails[id]) {
    const k = emailKey(state.emails[id]);
    delete state.emailIndex[k]; touch('emailIndex', k);
    delete state.emails[id]; touch('emails', id);
  }
  delete state.stats[id]; touch('stats', id);
  dropKeys('tokens', (k, rec) => rec.userId === id);
  dropKeys('drops', k => k.startsWith(id + '|'));
  dropKeys('picks', k => k.startsWith(id + '|'));
  for (const [key, list] of Object.entries(state.drops)) {
    if (list.includes(id)) { state.drops[key] = list.filter(x => x !== id); touch('drops', key); }
  }
  for (const [iid, intro] of Object.entries(state.intros)) {
    if (intro.from === id || intro.to === id) {
      delete state.intros[iid]; touch('intros', iid);
      delete state.chats[iid]; touch('chats', iid);
    }
  }
  delete state.queue[id]; touch('queue', id);
  dropKeys('delivered', k => k.startsWith(id + '|'));
  kvDel('notes', id);
  kvDel('psyche', id);
  kvDel('igpick', id);
  kvDel('pairwait', id);
  state.outcomes = state.outcomes.filter(o => o.by !== id); touch('outcomes');
  state.reports = state.reports.filter(r => r.from !== id); touch('reports');
}

// ---------- matching records ----------

const getDrop = (id, week) => state.drops[id + '|' + week] || null;
function setDrop(id, week, ids) { const k = id + '|' + week; state.drops[k] = ids; touch('drops', k); }
const getPicks = (id, week) => state.picks[id + '|' + week] || [];
function addPick(id, week, other) { const k = id + '|' + week; state.picks[k] = [...getPicks(id, week), other]; touch('picks', k); }

function createIntro(fields) {
  const intro = { id: newId('i'), linkToken: crypto.randomBytes(18).toString('base64url'), createdAt: Date.now(), respondedAt: null, ...fields };
  state.intros[intro.id] = intro;
  touch('intros', intro.id);
  return intro;
}
const getIntro = id => state.intros[id] || null;
const allIntros = () => Object.values(state.intros);
function updateIntro(id, patch) { Object.assign(state.intros[id], patch); touch('intros', id); return state.intros[id]; }

const getStats = () => state.stats;
function bumpStat(id, key) {
  const s = state.stats[id] || (state.stats[id] = { shown: 0, picked: 0 });
  s[key] += 1;
  touch('stats', id);
}

function addReport(report) { state.reports.push({ ...report, at: Date.now() }); touch('reports'); }
const allReports = () => state.reports;

const getQuestion = key => state.questions[key] || null;
const allQuestions = () => Object.values(state.questions);
function addQuestion(q) { state.questions[q.key] = q; touch('questions', q.key); return q; }

const getQueue = id => state.queue[id] || [];
function setQueue(id, list) { if (list.length) state.queue[id] = list; else delete state.queue[id]; touch('queue', id); }
const getDelivered = (id, week) => state.delivered[id + '|' + week] || [];
function addDelivered(id, week, key) { const k = id + '|' + week; state.delivered[k] = [...new Set([...getDelivered(id, week), key])]; touch('delivered', k); }

const getChat = introId => state.chats[introId] || null;
function setChat(introId, chat) { if (chat) state.chats[introId] = chat; else delete state.chats[introId]; touch('chats', introId); }
const allChats = () => Object.entries(state.chats);

function addOutcome(o) { state.outcomes.push({ ...o, at: Date.now() }); touch('outcomes'); }
const allOutcomes = () => state.outcomes;

// ---------- short-lived tables ----------

const kvGet = (table, key) => (state.kv[table] && state.kv[table][key]) || null;
function kvSet(table, key, value) {
  (state.kv[table] || (state.kv[table] = {}))[key] = value;
  touch('kv:' + table, key);
  return value;
}
function kvDel(table, key) {
  if (!state.kv[table] || state.kv[table][key] === undefined) return;
  delete state.kv[table][key];
  touch('kv:' + table, key);
}
const kvAll = table => Object.entries(state.kv[table] || {});

function reset() { state = empty(); dirty.clear(); }

module.exports = {
  load, flush, reset, newId, hash, emailKey, handleKey, issueToken, tokenRecord, revokeToken, createUser, userByToken, userByEmail, emailOf, setEmail, putBlob, getBlob, delBlob, getUser, allUsers, updateUser, deleteUser,
  kvGet, kvSet, kvDel, kvAll,
  getDrop, setDrop, getPicks, addPick, createIntro, getIntro, allIntros, updateIntro,
  getStats, bumpStat, addReport, allReports,
  getQuestion, allQuestions, addQuestion, getQueue, setQueue, getDelivered, addDelivered,
  getChat, setChat, allChats, addOutcome, allOutcomes,
};
