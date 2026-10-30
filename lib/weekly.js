// The weekly cycle.
//
//   drop      Once a week each person gets up to DROP_SIZE matches whose fit
//             (lib/calibrate.js) is at or above THRESHOLD and whose raw score
//             clears RAW_FLOOR, best first. Fewer is fine; none is fine: the
//             point is to end dating fatigue, not to fill a quota.
//   pick      They choose up to PICKS_PER_WEEK. A pick sends the other person
//             an intro (email, and in their host on next visit).
//   respond   The other person says yes or no. If they had also picked the
//             first one, it is mutual straight away.
//   mutual    Both get the full card and each other's Instagram.
//
// Answering an intro does not use up one of your own picks: the limit is on
// reaching out, so a popular person is not forced to ignore people.
// Pending intros lapse after INTRO_TTL_DAYS.
//
// A strong candidate held back only by an unanswered custom question is not
// shown; the question is queued for them instead (lib/questions.js), and they
// can appear in a later drop once they answer.

const store = require('./store');
const mail = require('./mail');
const { scorePair, highlights, filterReason, pendingKeys, noWeakArea } = require('./score');
const { computeBuckets } = require('./attraction');
const { matchCard, selfCard } = require('./card');
const links = require('./links');
const psyche = require('./psyche');
const sync = require('./sync');
const plans = require('./plans');
const { toFit, referenceFrom, RAW_FLOOR } = require('./calibrate');
const questions = require('./questions');
const notify = require('./notify');
const crypto = require('node:crypto');

const THRESHOLD = Number(process.env.PSYCHE_THRESHOLD || 80);
// The free plan's; Psyche Pair Plus widens both (lib/plans.js).
const DROP_SIZE = plans.FREE.drop;
const PICKS_PER_WEEK = plans.FREE.picks;
const INTRO_TTL_DAYS = 14;

/** ISO week, e.g. '2026-W44'. Drops turn over on Monday 00:00 UTC. */
function weekKey(now = Date.now()) {
  const d = new Date(now);
  const day = (d.getUTCDay() + 6) % 7;
  const thursday = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - day + 3));
  const yearStart = new Date(Date.UTC(thursday.getUTCFullYear(), 0, 4));
  const week = 1 + Math.round(((thursday - yearStart) / 86400000 - 3 + ((yearStart.getUTCDay() + 6) % 7)) / 7);
  return thursday.getUTCFullYear() + '-W' + String(week).padStart(2, '0');
}

/** The view of a user the scorer reads. Null until they have a confirmed profile. */
function matchable(user) {
  if (!user || !user.profile) return null;
  return { id: user.id, ...user.profile, prefs: user.prefs, answers: user.answers || {}, reviewedAt: user.reviewedAt, blocked: user.blocked, paused: user.paused };
}

function blockedEither(a, b) {
  const ua = store.getUser(a), ub = store.getUser(b);
  return Boolean((ua && (ua.blocked || []).includes(b)) || (ub && (ub.blocked || []).includes(a)));
}

function introBetween(a, b) {
  return store.allIntros().find(i => (i.from === a && i.to === b) || (i.from === b && i.to === a)) || null;
}

function lapse(intro, now) {
  if (intro.status === 'pending' && now - intro.createdAt > INTRO_TTL_DAYS * 86400000) {
    return store.updateIntro(intro.id, { status: 'lapsed' });
  }
  return intro;
}

function fitFor(a, b) {
  return scorePair(a, b, computeBuckets(store.getStats()));
}

// Every eligible pair in the pool, scored once, as the ranking reference.
// Recomputed when anyone confirms, pauses or leaves; fine at pilot scale
// (a few thousand people), and the place to sample when it is not.
let refCache = { key: '', ref: null };
function poolReference(buckets) {
  const people = store.allUsers().map(matchable).filter(m => m && m.reviewedAt && !m.paused);
  const key = people.map(m => m.id + ':' + m.reviewedAt).join(',');
  if (refCache.key === key) return refCache.ref;
  const raws = [];
  for (let i = 0; i < people.length; i++) {
    for (let j = i + 1; j < people.length; j++) {
      const r = scorePair(people[i], people[j], buckets);
      if (r) raws.push(r.score);
    }
  }
  refCache = { key, ref: referenceFrom(raws) };
  return refCache.ref;
}

/** Raw score plus the calibrated fit people see; null when filtered out. */
function rate(a, b, options) {
  const buckets = computeBuckets(store.getStats());
  const r = scorePair(a, b, buckets, options);
  return r ? { ...r, fit: toFit(r.score, poolReference(buckets)) } : null;
}

/** Everyone who passes the filters with this person, scored, best first. */
function candidates(user) {
  const me = matchable(user);
  if (!me) return [];
  const out = [];
  for (const other of store.allUsers()) {
    // A reviewer's demo people (lib/demo.js) only ever meet each other.
    if (Boolean(other.demo) !== Boolean(user.demo)) continue;
    const them = matchable(other);
    if (!them) continue;
    const why = filterReason(me, them);
    if (why === 'pending_question') { askIfStrong(me, them); continue; }
    if (why) continue;
    const fit = rate(me, them);
    if (fit) out.push({ user: other, fit });
  }
  return out.sort((x, y) => y.fit.score - x.fit.score);
}

// Held back only by an unanswered custom question: if they would otherwise
// clear the bar, ask whoever has not answered. Each side's own must-haves are
// asked of the other side.
function askIfStrong(me, them) {
  const fit = rate(me, them, { ignorePending: true });
  if (!fit || fit.fit < THRESHOLD || fit.score < RAW_FLOOR || !noWeakArea(fit)) return;
  pendingKeys(me, them).forEach(key => questions.enqueue(them.id, key));
  pendingKeys(them, me).forEach(key => questions.enqueue(me.id, key));
}

/** How many people the filters and must-haves leave: shown when preferences change. */
function poolSize(user) {
  return candidates(user).length;
}

function weeklyDrop(userId, now = Date.now()) {
  const user = store.getUser(userId);
  const me = matchable(user);
  if (!me || !me.reviewedAt) return { week: weekKey(now), cards: [], picksLeft: 0, note: 'Confirm your profile first.' };
  const week = weekKey(now);
  let ids = store.getDrop(userId, week);
  if (!ids) {
    ids = candidates(user)
      .filter(c => c.fit.fit >= THRESHOLD && c.fit.score >= RAW_FLOOR && noWeakArea(c.fit) && !introBetween(userId, c.user.id))
      .slice(0, plans.limitsFor(user, now).drop)
      .map(c => c.user.id);
    store.setDrop(userId, week, ids);
    ids.forEach(id => store.bumpStat(id, 'shown'));
  }
  // Someone who picked you after the drop was made shows under intros instead.
  const visible = ids.filter(id => { const i = introBetween(userId, id); return !i || i.from === userId; });
  const cards = visible.map(id => store.getUser(id)).filter(Boolean).map(other => {
    const them = matchable(other);
    const fit = rate(me, them);
    return fit ? matchCard(other, 'drop', fit, highlights(me, them), me) : null;
  }).filter(Boolean);
  const picked = store.getPicks(userId, week);
  return {
    week,
    cards: cards.map(c => ({ ...c, picked: picked.includes(c.id), ...links.cardLinks(userId, c.id, undefined, c.photoCount) })),
    picksLeft: Math.max(0, plans.limitsFor(user, now).picks - picked.length),
    note: cards.length ? null : 'No one cleared the bar this week, so we are not showing anyone. New people join every week.',
  };
}

function pick(userId, candidateId, now = Date.now()) {
  const week = weekKey(now);
  const drop = store.getDrop(userId, week) || [];
  if (!drop.includes(candidateId)) return { ok: false, error: 'That person is not in this week\'s drop.' };
  const picked = store.getPicks(userId, week);
  if (picked.includes(candidateId)) return { ok: false, error: 'You already picked them.' };
  const me = store.getUser(userId);
  const allowed = plans.limitsFor(me, now).picks;
  if (picked.length >= allowed) return { ok: false, error: `You have used your ${allowed} picks this week.` };
  const other = store.getUser(candidateId);
  if (!other || !fitFor(matchable(me), matchable(other))) return { ok: false, error: 'That match is no longer available.' };

  store.addPick(userId, week, candidateId);
  store.bumpStat(candidateId, 'picked');

  const existing = introBetween(userId, candidateId);
  if (existing && existing.from === candidateId && lapse(existing, now).status === 'pending') {
    makeMutual(existing, now);
    return { ok: true, status: 'mutual', introId: existing.id };
  }
  if (existing) return { ok: false, error: 'You two already have an intro.' };
  const intro = store.createIntro({ from: userId, to: candidateId, week, status: 'pending', createdAt: now });
  store.bumpStat(userId, 'shown');
  notify.note(candidateId, 'picked', { introId: intro.id, name: me.profile.basics.firstName, yes: mail.introLink(intro, 'accept'), no: mail.introLink(intro, 'decline') }, now);
  return { ok: true, status: 'pending', introId: intro.id };
}

function respond(userId, introId, accept, now = Date.now()) {
  const found = store.getIntro(introId);
  if (!found || found.to !== userId) return { ok: false, error: 'No such intro.' };
  const intro = lapse(found, now);
  if (intro.status !== 'pending') return { ok: false, error: 'This intro is ' + intro.status + '.' };
  const me = store.getUser(userId);
  const other = store.getUser(intro.from);
  if (!other) return { ok: false, error: 'That person has left.' };
  if (!accept) {
    store.updateIntro(introId, { status: 'declined', respondedAt: now });
    return { ok: true, status: 'declined' };
  }
  store.bumpStat(intro.from, 'picked');
  makeMutual(intro, now);
  return { ok: true, status: 'mutual' };
}

// Both said yes: each gets a personal link to the private chat (used in the
// digest, if they are away), and the match shows in the host. Instagram is
// not shared yet: each decides per match (shareInstagram).
function makeMutual(intro, now) {
  const chatTokens = {
    [intro.from]: crypto.randomBytes(18).toString('base64url'),
    [intro.to]: crypto.randomBytes(18).toString('base64url'),
  };
  const done = store.updateIntro(intro.id, { status: 'mutual', respondedAt: now, chatTokens, instagram: {} });
  const a = store.getUser(intro.from), b = store.getUser(intro.to);
  notify.note(a.id, 'mutual', { introId: done.id, name: b.profile.basics.firstName, chat: mail.chatLink(done, a.id) }, now);
  notify.note(b.id, 'mutual', { introId: done.id, name: a.profile.basics.firstName, chat: mail.chatLink(done, b.id) }, now);
  return done;
}

/**
 * Offer (or withdraw) your Instagram to one mutual match. Handles show only
 * once both have offered; until then the other side sees that you have.
 */
function shareInstagram(userId, introId, share) {
  const intro = store.getIntro(introId);
  if (!intro || intro.status !== 'mutual' || (intro.from !== userId && intro.to !== userId)) return { ok: false, error: 'No such match.' };
  if (blockedEither(intro.from, intro.to)) return { ok: false, error: 'No such match.' };
  if (share && !store.getUser(userId).profile.basics.instagram) return { ok: false, error: 'Add your Instagram handle to your profile first.' };
  const next = { ...(intro.instagram || {}) };
  if (share) next[userId] = true; else delete next[userId];
  store.updateIntro(introId, { instagram: next });
  return { ok: true, swap: swapState(store.getIntro(introId), userId) };
}

function swapState(intro, userId) {
  const other = intro.from === userId ? intro.to : intro.from;
  const mine = Boolean(intro.instagram && intro.instagram[userId]);
  const theirs = Boolean(intro.instagram && intro.instagram[other]);
  return mine && theirs ? 'both' : theirs ? 'they_offered' : mine ? 'you_offered' : 'none';
}

/** Are this week's matches waiting unseen? For the digest; makes no drop. */
function hasNewDrop(userId, now = Date.now()) {
  const user = store.getUser(userId);
  if (!user || !user.reviewedAt || user.paused || store.getDrop(userId, weekKey(now))) return false;
  return candidates(user).some(c => c.fit.fit >= THRESHOLD && c.fit.score >= RAW_FLOOR && noWeakArea(c.fit) && !introBetween(userId, c.user.id));
}

/** After a date: did they meet, and would they again. Outcomes only, no words. */
function logDate(userId, introId, { met, again }) {
  const intro = store.getIntro(introId);
  if (!intro || intro.status !== 'mutual' || (intro.from !== userId && intro.to !== userId)) return { ok: false, error: 'No such match.' };
  if (typeof met !== 'boolean') return { ok: false, error: 'met must be true or false' };
  if (again !== undefined && !questions.ANSWERS.includes(again)) return { ok: false, error: 'again must be yes, maybe or no' };
  store.addOutcome({ introId, by: userId, met, again: again || null });
  return { ok: true };
}

/** Intros waiting on this person, and their mutual matches, as cards. */
function intros(userId, now = Date.now()) {
  const me = matchable(store.getUser(userId));
  if (!me) return { waiting: [], mutual: [], sent: [] };
  const out = { waiting: [], mutual: [], sent: [] };
  for (const raw of store.allIntros()) {
    if (raw.from !== userId && raw.to !== userId) continue;
    const intro = lapse(raw, now);
    const otherId = intro.from === userId ? intro.to : intro.from;
    if (blockedEither(userId, otherId)) continue;
    const other = store.getUser(otherId);
    const them = matchable(other);
    if (!them) continue;
    const fit = rate(me, them) || { score: null, fit: null, breakdown: {} };
    const urls = links.cardLinks(userId, otherId, undefined, require('./photos').countOf(other));
    if (intro.status === 'mutual') out.mutual.push({ introId: intro.id, ...matchCard(other, 'mutual', fit, highlights(me, them), me, { swap: swapState(intro, userId) }), ...urls });
    else if (intro.status === 'pending' && intro.to === userId) out.waiting.push({ introId: intro.id, ...matchCard(other, 'picked', fit, highlights(me, them), me), ...urls });
    else if (intro.status === 'pending') out.sent.push({ introId: intro.id, firstName: them.basics.firstName, status: 'waiting for their answer' });
  }
  return out;
}

/**
 * What viewer may see of other right now, for a card image or page: their own
 * card, a drop card, a card of someone who picked them, one they are waiting
 * on, or a mutual match. Null when there is nothing to show (no link between
 * them, declined, lapsed, blocked, or someone left).
 */
function cardContext(viewerId, otherId, now = Date.now(), kind, key) {
  const viewer = store.getUser(viewerId);
  if (!viewer) return null;
  if (kind === 'sync') return sync.context(viewerId, otherId, key);
  if (kind === 'psyche') {
    const card = viewerId === otherId ? psyche.card(viewerId, now, key) : null;
    return card ? { stage: 'psyche', card: { ...card, stage: 'psyche', characterName: card.character, character: [card.character, card.mbti].filter(Boolean).join(' · ') || null, characterWhy: card.why } } : null;
  }
  if (viewerId === otherId) {
    const card = selfCard(viewer);
    return card ? { stage: 'self', card } : null;
  }
  const other = store.getUser(otherId);
  const me = matchable(viewer), them = matchable(other);
  if (!me || !them || blockedEither(viewerId, otherId)) return null;
  const fit = rate(me, them, { ignorePending: true }) || { score: null, fit: null, breakdown: {} };
  const lines = highlights(me, them);
  const found = introBetween(viewerId, otherId);
  const intro = found && lapse(found, now);
  if (intro && intro.status === 'mutual') {
    return { stage: 'mutual', introId: intro.id, card: matchCard(other, 'mutual', fit, lines, me, { swap: swapState(intro, viewerId) }), chat: mail.chatLink(intro, viewerId) };
  }
  if (intro && intro.status === 'pending' && intro.to === viewerId) {
    return { stage: 'picked', introId: intro.id, card: matchCard(other, 'picked', fit, lines, me) };
  }
  if (intro && intro.status === 'pending') return { stage: 'sent', introId: intro.id, card: matchCard(other, 'drop', fit, lines, me) };
  if (intro) return null;
  const week = weekKey(now);
  if (!(store.getDrop(viewerId, week) || []).includes(otherId)) return null;
  const picks = store.getPicks(viewerId, week);
  const allowed = plans.limitsFor(viewer, now).picks;
  return { stage: 'drop', card: matchCard(other, 'drop', fit, lines, me), picksLeft: Math.max(0, allowed - picks.length), picksTotal: allowed };
}

module.exports = { THRESHOLD, DROP_SIZE, PICKS_PER_WEEK, weekKey, matchable, candidates, poolSize, weeklyDrop, pick, respond, intros, logDate, shareInstagram, hasNewDrop, cardContext };
