// Keys this server never stores (README "Nothing readable kept").
//
// A Psyche card summary is locked under a key made for it at each publish,
// and a Sync under its inviter's Sync code. Those keys live in the user's own
// Muse workspace: the skill sends them with each call (X-Psyche-Card-Key, and
// X-Psyche-Sync-Keys for the Sync codes it holds), and a card picture's own
// link carries its key. They're held in memory for the request that carries
// them and gone when it ends, so a copy of the database holds nothing readable
// about anyone; only a request someone makes opens their own data.

const crypto = require('node:crypto');

const CARD_KEY = /^[A-Za-z0-9_-]{43}$/;     // 32 random bytes, base64url
const SYNC_CODE = /^[A-Za-z0-9_-]{22}$/;    // 16 random bytes, base64url: the Sync link's code, and its key

// ---------- held for a request ----------

const held = new Map();     // userId → { card, syncs: Set, n }

/** Run with this user's keys at hand (from their own request), then forget them. */
async function withKeys(userId, { card, syncs } = {}, run) {
  const codes = String(syncs || '').split(',').map(s => s.trim()).filter(s => SYNC_CODE.test(s)).slice(0, 200);
  const cardKey = CARD_KEY.test(String(card || '')) ? card : null;
  if (!userId || (!cardKey && !codes.length)) return run();
  const h = held.get(userId) || { card: null, syncs: new Set(), n: 0 };
  if (cardKey) h.card = cardKey;
  for (const c of codes) h.syncs.add(c);
  h.n += 1;
  held.set(userId, h);
  try {
    return await run();
  } finally {
    if (--h.n <= 0) held.delete(userId);
  }
}
const cardKeyOf = userId => (held.get(userId) || {}).card || null;
const syncCodesOf = userId => [...((held.get(userId) || {}).syncs || [])];
/** A Sync code this request brought, so later steps of the same request can use it. */
function addSyncCode(userId, code) {
  const h = held.get(userId);
  if (h && SYNC_CODE.test(code)) h.syncs.add(code);
}

// ---------- locking ----------

const derive = (purpose, secret) => crypto.createHash('sha256').update('psyche|' + purpose + '|' + secret).digest();
const keyFrom = secret => (CARD_KEY.test(secret) ? Buffer.from(secret, 'base64url') : null);

function lock(value, key) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', key, iv);
  const box = Buffer.concat([c.update(JSON.stringify(value), 'utf8'), c.final(), c.getAuthTag()]);
  return { iv: iv.toString('base64url'), box: box.toString('base64url') };
}
function unlock(sealed, key) {
  if (!sealed || !key) return null;
  try {
    const box = Buffer.from(sealed.box, 'base64url');
    const d = crypto.createDecipheriv('aes-256-gcm', key, Buffer.from(sealed.iv, 'base64url'));
    d.setAuthTag(box.subarray(box.length - 16));
    return JSON.parse(Buffer.concat([d.update(box.subarray(0, box.length - 16)), d.final()]).toString('utf8'));
  } catch (err) {
    return null;
  }
}

const newCardKey = () => crypto.randomBytes(32).toString('base64url');
const newSyncCode = () => crypto.randomBytes(16).toString('base64url');
/** What a Sync code locks: the inviter's card, and each Sync made with it. Its id is what's stored to find it. */
const syncCardKey = code => derive('sync-card', code);
const syncPairKey = code => derive('sync-pair', code);
const syncId = code => derive('sync-id', code).toString('hex');

module.exports = { CARD_KEY, SYNC_CODE, withKeys, cardKeyOf, syncCodesOf, addSyncCode, lock, unlock, keyFrom, newCardKey, newSyncCode, syncCardKey, syncPairKey, syncId };
