// The photos someone adds for Psyche Pair: three, required to join, chosen by
// them in the details form (lib/pairform.js) and never by Muse, so nothing is
// ever read or judged from a photo. The form shrinks each in the browser to a
// JPEG of about 900 px before it's sent; here each is checked (a real JPEG,
// at most MAX_BYTES) and kept as its own sealed blob (store.putBlob), never in
// the records loaded at boot. A photo is served only through a card link, to
// someone that card is for (server.js /photo/<token>/<n>.jpg), shown below
// the card and never in it, and deleted with the rest of their data.

const store = require('./store');

const COUNT = 3;
const MAX_BYTES = 400 * 1024;
const key = (userId, i) => 'photo:' + userId + ':' + i;
const isJpeg = buf => buf.length > 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff;

/** A data: URL from the form, as a JPEG Buffer, or null. */
function fromDataUrl(text) {
  const m = /^data:image\/jpeg;base64,([A-Za-z0-9+/=]+)$/.exec(String(text || '').trim());
  if (!m) return null;
  const buf = Buffer.from(m[1], 'base64');
  return isJpeg(buf) && buf.length <= MAX_BYTES ? buf : null;
}

/** Replace someone's photos with these (exactly COUNT JPEG Buffers). */
async function save(userId, buffers, now = Date.now()) {
  if (buffers.length !== COUNT || !buffers.every(b => Buffer.isBuffer(b) && isJpeg(b) && b.length <= MAX_BYTES)) return { error: `Add ${COUNT} photos.` };
  for (let i = 0; i < COUNT; i++) await store.putBlob(key(userId, i), buffers[i]);
  store.updateUser(userId, { photos: { count: COUNT, at: now } });
  return { ok: true };
}

const countOf = user => (user && user.photos && user.photos.count) || 0;

/** One photo as a Buffer, or null. */
async function get(userId, i) {
  const n = Number(i);
  if (!Number.isInteger(n) || n < 0 || n >= countOf(store.getUser(userId))) return null;
  return store.getBlob(key(userId, n));
}

/** Everything photo-shaped about a person, for delete_my_data. */
async function forget(userId) {
  for (let i = 0; i < COUNT; i++) await store.delBlob(key(userId, i));
}

module.exports = { COUNT, MAX_BYTES, fromDataUrl, save, countOf, get, forget };
