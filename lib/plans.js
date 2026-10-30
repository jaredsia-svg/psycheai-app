// What each plan allows (PLAN.md "Money"). Free is the whole product; Psyche
// Pair Plus only widens it. Plus is bought on the website (lib/plus.js), never
// offered or priced inside Muse or ChatGPT, so nothing here is ever worded as
// an upsell: a limit is stated as a limit.

const FREE = { name: 'free', picks: 2, drop: 5, customMustHaves: 1 };
const PLUS = { name: 'plus', picks: 5, drop: 8, customMustHaves: 5 };

// Stripe states that still count as paid. past_due keeps Plus while Stripe
// retries the card; the period end is the hard stop.
const PAID = ['active', 'trialing', 'past_due'];
const GRACE_MS = 3 * 86400000;

function isPlus(user, now = Date.now()) {
  const p = user && user.plus;
  return Boolean(p && PAID.includes(p.status) && typeof p.until === 'number' && p.until + GRACE_MS > now);
}

/** The limits for this user right now. */
const limitsFor = (user, now = Date.now()) => (isPlus(user, now) ? PLUS : FREE);

module.exports = { FREE, PLUS, PAID, isPlus, limitsFor };
