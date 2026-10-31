// The PsycheAI read, on the Muse path (PLAN.md, step 2).
//
// Muse writes the read itself, as one answer to PsycheAI's merged schema,
// following PsycheAI's own prompt with a Muse preface. Both come from
// PsycheAI (GET /api/import/guide), so the rules live in one place. The
// answer goes to PsycheAI (POST /api/import), which checks it as it checks a
// provider's, seals it under a key it makes for it, and hands back the link
// psycheai.io/?m=<id>#<key>. The read itself is never kept here.
//
// What is kept, for READ_DAYS and then deleted: a card-level summary
// (character, headline, type, pattern names, top motivations, a few
// interests), to draw the card image the user sees beside their link. The same
// fields a shared Psyche Card shows; nothing from the report. It's kept
// locked under a key made at each publish that this server never stores
// (lib/keys.js): the key goes back to the user's workspace and into the card
// picture's own link (README "Nothing readable kept").
//
// Both servers share PSYCHEAI_IMPORT_SECRET; PSYCHEAI_URL says where PsycheAI is.

const store = require('./store');
const links = require('./links');
const keys = require('./keys');
const notify = require('./notify');

const PSYCHEAI_URL = () => (process.env.PSYCHEAI_URL || 'https://psycheai.io').replace(/\/$/, '');
const SECRET = () => process.env.PSYCHEAI_IMPORT_SECRET || '';
const READ_DAYS = 7;
// Short, so a PsycheAI deploy reaches Muse within minutes.
const GUIDE_TTL_MS = 5 * 60000;
const TABLE = 'psyche';

let guideCache = null;

async function call(path, options = {}) {
  if (!SECRET()) throw Object.assign(new Error('PsycheAI is not connected (PSYCHEAI_IMPORT_SECRET is not set).'), { status: 503 });
  const res = await fetch(PSYCHEAI_URL() + path, {
    ...options,
    headers: { Authorization: 'Bearer ' + SECRET(), 'Content-Type': 'application/json', ...(options.headers || {}) },
    signal: AbortSignal.timeout(20000),
  });
  const body = await res.json().catch(() => ({}));
  return { status: res.status, body };
}

/**
 * One of PsycheAI's guides: kind 'read' { spec, schema } or 'sync' { spec, brief, schema }. A short
 * specification of the document, never a prompt: a tool result that sets the assistant's role reads
 * to a host as prompt injection, and Muse refused the old one (README "The read guide is a spec").
 */
async function fetchGuide(kind = 'read', depth = null) {
  let res;
  try { res = await call('/api/import/guide' + (kind === 'read' ? (depth === 'deep' ? '?depth=deep' : '') : '?kind=' + kind)); } catch (err) {
    return { error: err.status === 503 ? err.message : 'The PsycheAI guide is unavailable right now. Try again in a minute.' };
  }
  const { status, body } = res;
  if (status !== 200 || typeof body.spec !== 'string' || !body.schema) {
    return { error: 'The PsycheAI guide is unavailable right now. Try again in a minute.' };
  }
  // Everything the guide carries: the brief (Sync) and the MBTI rubric (a read),
  // whose row ids the ledger must use. Leaving the rubric out made Muse write
  // descriptive rows and flag them as a risk before saving.
  return { spec: body.spec, schema: body.schema, ...(typeof body.brief === 'string' ? { brief: body.brief } : {}), ...(typeof body.rubric === 'string' ? { rubric: body.rubric } : {}) };
}

/** PsycheAI's guide for writing a read: { system, schema }. Cached for an hour. */
// depth 'deep': a Deep Psyche, with its plan added to the spec (psycheai.io
// lib/museimport.js DEEP_SPEC). Cached apart.
async function guide(now = Date.now(), depth = null) {
  const key = depth === 'deep' ? 'deep' : 'read';
  const hit = guideCache && guideCache[key];
  if (hit && now - hit.at < GUIDE_TTL_MS) return hit.value;
  const out = await fetchGuide('read', key === 'deep' ? 'deep' : null);
  if (out.error) return out;
  guideCache = { ...(guideCache || {}), [key]: { at: now, value: out } };
  return out;
}

// The motivators by the names psycheai.io's card uses (docs/copy.js
// STRUCTURED.motivators), so the card here says what the site's does.
const MOTIVATOR_LABELS = { 'self-direction': 'Self-direction', stimulation: 'Stimulation', hedonism: 'Enjoyment', achievement: 'Achievement', power: 'Influence',
  security: 'Security', conformity: 'Conformity', tradition: 'Tradition', benevolence: 'Care for your people', universalism: 'Care for the wider world' };

const list = (value, pick, max) => (Array.isArray(value) ? value.map(pick).filter(Boolean).slice(0, max) : []);
const text = (value, max) => (typeof value === 'string' ? value.replace(/\s+/g, ' ').trim().slice(0, max) : null);

/** The card-level summary of a merged answer: what a shared Psyche Card shows, no more. */
// The card's write-up as psycheai.io's card picks it (docs/app.js cardBlurb):
// the first two sentences of cardHighlights, the text written for the card.
// Without it, the character's why; never the report's summary, which isn't
// card text and isn't kept here.
const sentences = t => String(t || '').replace(/\s+/g, ' ').trim().split(/(?<=[.!?])\s+/).filter(Boolean);
const blurb = (a, essence) => text(sentences(a.cardHighlights || essence.why).slice(0, 2).join(' '), 400);

function summarize(answer, name) {
  const a = answer && typeof answer === 'object' ? answer : {};
  const essence = a.essence || {};
  const big = a.bigFive || {};
  const love = (a.relationship && a.relationship.loveLanguages) || {};
  const letters = a.mbti && Array.isArray(a.mbti.letters) ? a.mbti.letters : [];
  return {
    firstName: text(String(name || '').split(/\s+/)[0], 40) || 'You',
    fullName: text(name, 60),
    confidence: a.confidence && Number.isFinite(Number(a.confidence.score)) ? Math.round(Number(a.confidence.score)) : null,
    letters: letters.slice(0, 4).map(l => ({ letter: text(l && l.choice, 1), strength: text(l && l.strength, 12) })).filter(l => l.letter && /^[EINSTFJP]$/.test(l.letter)),
    character: text(essence.character, 40),
    why: blurb(a, essence),
    headline: text(a.card && a.card.headline, 120),
    mbti: text(a.mbti && a.mbti.type, 4),
    patterns: list(a.patterns, p => text(p && p.name, 40), 3),
    motivators: list(a.topMotivators, m => MOTIVATOR_LABELS[m] || text(m, 30), 3),
    interests: list(a.interests, i => text(i && (i.name || i), 60), 6),
    // Three values and a belief, as psycheai.io's card shows them.
    values: [...list(a.values, v => text(v && (v.value || v), 40), 3), ...list(a.beliefs, b => text(b && (b.belief || b), 40), 1)].slice(0, 4),
    bigFive: Object.fromEntries(['openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism']
      .map(k => [k, big[k] && Number.isFinite(Number(big[k].score)) ? Math.round(Number(big[k].score)) : null])),
    loveGiving: list(love.giving, l => text(l && l.language, 30), 2),
  };
}

// How the chat shows a publish result: also in the signed SKILL.md (README "Result lines are signed").
const showFor = (hasSections, pdf, story, hasView) => 'For the chat:' + (hasSections ? ' sections is the report in short, each a title and its points (its finding as bullets);' : '') +
      (hasView ? ' view is the whole report for the widget: its scores and one-line readings, without the evidence;' : '') +
      ' image is their Psyche Card as a picture;' +
      (pdf ? (pdf.includes('#') ? ' pdf opens the report as a PDF, with their Psyche Card on its first page, unlocked in their browser on psycheai.io (with the PsycheAI skill, bin/psyche.py show pdf saves it as a file);'
        : ' the PDF is the file, with their Psyche Card on its first page (pdf is its link, for when it can\'t be attached);') : '') + ' url opens their card and report on psycheai.io' +
      (story ? '; story opens the card full screen on psycheai.io, where they can share it themselves if they want' : '') + '.';

/** Publish Muse's read. Resolves to { ok, url, image, page } or { ok: false, problems | error }. */
async function publish(user, answer, name, now = Date.now()) {
  if (!answer || typeof answer !== 'object') return { ok: false, error: 'answer must be the JSON object the guide asks for' };
  let res;
  try {
    res = await call('/api/import', { method: 'POST', body: JSON.stringify({ answer, name: String(name || '').slice(0, 60) }) });
  } catch (err) {
    return { ok: false, error: err.status === 503 ? err.message : 'PsycheAI could not be reached. Try again in a minute.' };
  }
  if (res.status === 422) return { ok: false, problems: res.body.problems || [], error: 'Fix these and publish again.' };
  if (res.status !== 200 || !res.body.url) return { ok: false, error: 'PsycheAI could not save your Psyche. Try again in a minute.' };
  // The id only (never the key after #): so a reminder can go out if the
  // link is about to close unopened (remindUnopened).
  const readId = (/[?&]m=([A-Za-z0-9_-]+)/.exec(res.body.url) || [])[1] || null;
  const cardKey = keys.newCardKey();
  store.kvSet(TABLE, user.id, { sealed: keys.lock(summarize(answer, name), keys.keyFrom(cardKey)), expiresAt: now + READ_DAYS * 86400000, readId });
  store.updateUser(user.id, { psycheAt: now });
  // One link and no picture: the card and report are seen and downloaded on
  // psycheai.io, the site's own design, rather than a second drawing of the
  // card here that never quite matched it (README "The card lives on the site").
  // The report's PDF, made by psycheai.io from its own PDF code, handed to
  // the chat as a file (attach) as well as a link, so they can read it in Muse.
  const pdf = typeof res.body.pdf === 'string' && /^https:\/\//.test(res.body.pdf) ? res.body.pdf : null;
  const pdfName = String(res.body.pdfName || 'Psyche Report.pdf').slice(0, 80);
  // The card image, drawn here in psycheai.io's card design (lib/cardimage.js).
  const image = links.cardLinks(user.id, user.id, 'psyche', 0, cardKey).image;
  // The report in short from psycheai.io: each section its conclusions as
  // bullets (up to ten), never the evidence. Muse shows them collapsed.
  const sections = (Array.isArray(res.body.sections) ? res.body.sections : []).slice(0, 8)
    .map(s => ({ title: text(s && s.title, 40), finding: text(s && s.finding, 1500),
      points: (Array.isArray(s && s.points) ? s.points : []).slice(0, 10).map(p => text(p, 300)).filter(Boolean) }))
    .filter(s => s.title && s.finding)
    .map(s => (s.points.length ? s : { title: s.title, finding: s.finding }));
  // The whole report for Muse's one widget (README "The report in the chat"):
  // psycheai.io's scores and one-line readings, never the evidence, kept to
  // its shape's size here: strings, finite numbers, short lists, shallow objects.
  const clip = (v, depth) => {
    if (typeof v === 'string') return text(v, 300);
    if (typeof v === 'number') return Number.isFinite(v) ? v : null;
    if (v === null || depth > 4) return null;
    if (Array.isArray(v)) return v.slice(0, 12).map(x => clip(x, depth + 1));
    if (typeof v === 'object') return Object.fromEntries(Object.keys(v).slice(0, 20).map(k => [text(k, 40), clip(v[k], depth + 1)]));
    return null;
  };
  const view = res.body.view && typeof res.body.view === 'object' && !Array.isArray(res.body.view) ? clip(res.body.view, 0) : null;
  // The same link with story=1 opens on the card full screen with one "Share
  // to Story" button (psycheai.io README "Share to your Story from Muse").
  const story = typeof res.body.url === 'string' && res.body.url.includes('#') ? res.body.url.replace('#', (res.body.url.split('#')[0].includes('?') ? '&' : '?') + 'story=1#') : null;
  return { ok: true, url: res.body.url, ...(story ? { story } : {}), image, cardKey, ...(sections.length ? { sections } : {}), ...(view ? { view } : {}),
    // The PDF to attach. The card picture (image) is shown too, right under
    // "Your Psyche is ready." (README "The card picture is back"); the skill
    // saves it as a file (show card), since a link shows only as a cropped preview.
    // A link with its key after the # (psycheai.io /report-pdf, README "The PDF's key
    // stays out of the address") is a page that unlocks the PDF in the browser, not
    // a file a host can fetch: the skill saves the PDF itself (show pdf), sending
    // the key in a header. Only an older ?k= link is a file to attach.
    attach: pdf && !pdf.includes('#') ? [{ uri: pdf, name: pdfName, mimeType: 'application/pdf', description: 'Your Psyche Report' }] : [],
    ...(pdf ? { pdf, pdfName } : {}),
    // What each part is, not orders: a result line asking for the card to go
    // "on their Instagram Story" read to Muse's safety check as a tool result
    // directing a post to the user's account, and stopped the card's delivery.
    show: showFor(sections.length > 0, pdf, story, Boolean(view)) };
}

/** Whether there's a live card, without opening it. */
function has(userId, now = Date.now()) {
  const kept = store.kvGet(TABLE, userId);
  if (!kept) return false;
  if (kept.expiresAt < now) { store.kvDel(TABLE, userId); return false; }
  return true;
}

/**
 * The card summary for a user's latest read, if it hasn't expired and its key
 * came with the request (or is given). A Psyche Pair account's card (pair:
 * true, from a psycheai.io read joined to Pair, lib/join.js) is kept as Pair
 * profiles are, since Pair matches on the server.
 */
function card(userId, now = Date.now(), key = keys.cardKeyOf(userId)) {
  if (!has(userId, now)) return null;
  const kept = store.kvGet(TABLE, userId);
  if (kept.pair) return kept.card || null;
  return kept.sealed ? keys.unlock(kept.sealed, keys.keyFrom(String(key || ''))) : null;
}

/** Cards kept readable before they were locked: gone, so nothing readable stays. */
function forgetUnlocked() {
  for (const [id, row] of store.kvAll(TABLE)) if (row && !row.sealed && !row.pair) store.kvDel(TABLE, id);
}

/**
 * About a day before a link closes, ask PsycheAI whether it was opened (yes or
 * no, nothing more), and if not, remind the user once: a note for the email
 * digest, and `closing` for start's news. Once opened, the card and report stay
 * in their browser, so an opened link needs nothing.
 */
const REMIND_BEFORE_MS = 86400000;
async function remindUnopened(now = Date.now()) {
  let reminded = 0;
  for (const [userId, kept] of store.kvAll(TABLE)) {
    if (!kept.readId || kept.checked || kept.expiresAt < now || kept.expiresAt - now > REMIND_BEFORE_MS) continue;
    let res;
    try { res = await call('/api/import/status?id=' + encodeURIComponent(kept.readId)); } catch { continue; }
    // 404 only counts when PsycheAI says the read is gone, not when the route is missing (an older deploy).
    if (res.status !== 200 && !(res.status === 404 && /No such read/.test(String(res.body.error || '')))) continue;
    const unopened = res.status === 200 && res.body.exists && !res.body.opened;
    store.kvSet(TABLE, userId, { ...kept, checked: true, closing: unopened });
    if (unopened && store.getUser(userId)) { notify.note(userId, 'readClosing', {}, now); reminded++; }
  }
  return reminded;
}

/** True when the user's link closes within a day and hasn't been opened. */
function closingUnopened(userId, now = Date.now()) {
  const kept = store.kvGet(TABLE, userId);
  return Boolean(kept && kept.closing && kept.expiresAt > now);
}

function sweep(now = Date.now()) {
  for (const [id, kept] of store.kvAll(TABLE)) if (kept.expiresAt < now) store.kvDel(TABLE, id);
}

function resetGuideCache() { guideCache = null; }

/** For /health: how big the read guide last fetched was, and how old. Nothing from inside it. */
const guideInfo = (now = Date.now()) => {
  const hit = guideCache && guideCache.read;
  const v = hit && hit.value;
  return v ? { chars: String(v.spec || '').length + JSON.stringify(v.schema || null).length, ageMinutes: Math.round((now - hit.at) / 60000) } : null;
};

/**
 * A written Sync as PsycheAI's own Sync PDF (psycheai.io /api/import/syncpdf),
 * written to a (the viewer) about b. Made on request and kept nowhere. A
 * Buffer, or null if PsycheAI can't make it right now.
 */
async function syncPdf(report, a, b) {
  if (!SECRET()) return null;
  try {
    const res = await fetch(PSYCHEAI_URL() + '/api/import/syncpdf', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + SECRET(), 'Content-Type': 'application/json' },
      body: JSON.stringify({ report, a, b }),
      signal: AbortSignal.timeout(20000),
    });
    if (res.status !== 200 || !/application\/pdf/.test(res.headers.get('content-type') || '')) return null;
    return Buffer.from(await res.arrayBuffer());
  } catch { return null; }
}

module.exports = { showFor, READ_DAYS, fetchGuide, syncPdf, guide, guideInfo, publish, summarize, card, has, forgetUnlocked, sweep, remindUnopened, closingUnopened, resetGuideCache };
