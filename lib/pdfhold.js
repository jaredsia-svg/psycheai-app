// A Muse report's PDF, held in this server's memory only until Muse attaches it
// (README "Nothing kept"). psycheai.io checks the report and makes the PDF in
// memory and keeps none of it; it hands the PDF back, and it waits here behind a
// one-time random link for at most HOLD_MS or MAX_FETCHES downloads, whichever
// comes first. It is never written to the store, to disk or to a log, and a
// restart drops it (a republish makes a new one).
const crypto = require('node:crypto');
const { BASE_URL } = require('./config');

const HOLD_MS = 30 * 60 * 1000;
const MAX_FETCHES = 3;        // the skill may need a second try on a flaky network
const MAX_BYTES = 8 * 1024 * 1024;
const MAX_HELD = 200;         // a bound on memory: the oldest goes first
const ID = /^[A-Za-z0-9_-]{32}$/;

const held = new Map();

function sweep(now = Date.now()) {
  for (const [id, h] of held) if (h.until <= now) held.delete(id);
}

/** Hold a PDF; returns its one-time link, or null if it isn't a PDF. */
function hold(pdf, now = Date.now()) {
  if (!Buffer.isBuffer(pdf) || !pdf.length || pdf.length > MAX_BYTES || pdf.subarray(0, 5).toString() !== '%PDF-') return null;
  sweep(now);
  while (held.size >= MAX_HELD) held.delete(held.keys().next().value);
  const id = crypto.randomBytes(24).toString('base64url');
  held.set(id, { pdf, until: now + HOLD_MS, fetches: 0 });
  return BASE_URL + '/report/' + id + '.pdf';
}

/** The PDF for a link's id, counting the download; gone after MAX_FETCHES or HOLD_MS. */
function take(id, now = Date.now()) {
  if (!ID.test(String(id || ''))) return null;
  const h = held.get(id);
  if (!h) return null;
  if (h.until <= now) { held.delete(id); return null; }
  h.fetches += 1;
  if (h.fetches >= MAX_FETCHES) held.delete(id);
  return h.pdf;
}

function size() { return held.size; }

module.exports = { hold, take, sweep, size, HOLD_MS, MAX_FETCHES, ID };
