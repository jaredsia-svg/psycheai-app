// Signed links for card images and card pages. The token carries who is
// looking (v) at whom (o) and when it expires (e), signed with HMAC-SHA256
// under PSYCHE_LINK_SECRET, so nobody can forge a link to someone else's
// card or change who it is for. What the link shows is worked out live from
// where the two stand (lib/weekly.js cardContext), so one link stays good as
// a match moves from the drop to mutual.

const crypto = require('node:crypto');
const { BASE_URL } = require('./config');

const TTL_DAYS = 14;
const SECRET = crypto.createHash('sha256').update(process.env.PSYCHE_LINK_SECRET || crypto.randomBytes(32).toString('hex')).digest();
if (!process.env.PSYCHE_LINK_SECRET && process.env.NODE_ENV !== 'test' && require.main !== module) {
  console.warn('[links] PSYCHE_LINK_SECRET not set: card links die with this process');
}

const mac = body => crypto.createHmac('sha256', SECRET).update(body).digest('base64url');

// A key in a link (c) is itself encrypted under the link secret, so an access
// log line, which keeps the path, can't open anything without the secret too.
const HIDE = crypto.createHash('sha256').update('psyche|link-key|').update(SECRET).digest();
function hide(key) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', HIDE, iv);
  return Buffer.concat([iv, c.update(String(key), 'utf8'), c.final(), c.getAuthTag()]).toString('base64url');
}
function reveal(hidden) {
  try {
    const raw = Buffer.from(String(hidden), 'base64url');
    const d = crypto.createDecipheriv('aes-256-gcm', HIDE, raw.subarray(0, 12));
    d.setAuthTag(raw.subarray(raw.length - 16));
    return Buffer.concat([d.update(raw.subarray(12, raw.length - 16)), d.final()]).toString('utf8');
  } catch { return null; }
}

function sign(payload, now = Date.now(), ttlMs = TTL_DAYS * 86400000) {
  const p = payload.c ? { ...payload, c: hide(payload.c) } : payload;
  const body = Buffer.from(JSON.stringify({ ...p, e: now + ttlMs })).toString('base64url');
  return body + '.' + mac(body);
}

function verify(token, now = Date.now()) {
  const [body, sig] = String(token || '').split('.');
  if (!body || !sig) return null;
  const want = mac(body);
  if (sig.length !== want.length || !crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(want))) return null;
  try {
    const p = JSON.parse(Buffer.from(body, 'base64url').toString('utf8'));
    if (p.c) p.c = reveal(p.c);
    return p.e > now ? p : null;
  } catch { return null; }
}

/**
 * The image and the page for viewer looking at other (other = viewer for their
 * own card). kind 'psyche' is their PsycheAI card, from their latest read.
 */
function cardLinks(viewerId, otherId, kind, photoCount = 0, key = null) {
  // A Psyche card's or Sync's key rides in its own link (c): this server can open it only when the link is used.
  const t = sign(kind ? { v: viewerId, o: otherId, k: kind, ...(key ? { c: key } : {}) } : { v: viewerId, o: otherId });
  const out = { image: `${BASE_URL}/card/${t}.png`, page: `${BASE_URL}/m/${t}` };
  // Their photos, shown below the card (never in it), through the same signed link.
  if (photoCount > 0) out.photos = Array.from({ length: Math.min(3, photoCount) }, (_, i) => `${BASE_URL}/photo/${t}/${i}.jpg`);
  return out;
}

module.exports = { sign, verify, cardLinks, TTL_DAYS };
