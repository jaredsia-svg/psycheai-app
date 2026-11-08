// Psyche Together, bought on the website (README "Psyche Together, paid on the website"). Nothing is sold inside
// the host (CLAUDE.md): when payment is on, starting one without a purchase answers with a link here, worded as a
// limit, and the purchase happens on this page through Stripe Checkout.
//
//   GET  /together/buy/<token>            what it is, and the button (or "you're set")
//   POST /together/buy/<token>/checkout   off to Stripe Checkout, one payment
//   POST /stripe/webhook                  (lib/plus.js passes Together's sessions here) the only place a purchase lands
//
// One purchase is one Psyche Together, started by the one who bought it: joining stays free, and so do writing the
// read again and the four-week check-ins. The token is a signed link for one account that lasts an hour, as Plus's
// is. A purchase is credited only from a webhook whose signature checks out, never from the return from Checkout,
// and each Checkout session is credited once.

const store = require('./store');
const links = require('./links');
const { page, esc } = require('./theme');
const { BASE_URL } = require('./config');

const PAID = 'togetherpaid';         // userId → { credits, sessions: [Checkout session ids credited] }
const LINK_MS = 60 * 60000;
const PRICE = () => process.env.STRIPE_PRICE_TOGETHER || '';
const SHOWN = () => process.env.PSYCHE_TOGETHER_PRICE_SHOWN || '';      // e.g. "US$9.99", shown on this page only

/** Payment is on only when asked for and fully set up: otherwise everyone may start one, as before. */
const enabled = () => process.env.PSYCHE_TOGETHER_PAID === '1' && Boolean(PRICE() && process.env.STRIPE_SECRET_KEY && process.env.STRIPE_WEBHOOK_SECRET);

const tokenFor = (userId, now = Date.now()) => links.sign({ v: userId, k: 'together' }, now, LINK_MS);
function userFor(token, now = Date.now()) {
  const p = links.verify(token, now);
  return p && p.k === 'together' ? store.getUser(p.v) : null;
}

const credits = userId => Math.max(0, Number((store.kvGet(PAID, userId) || {}).credits) || 0);

/** For lib/together.js: null when this account may start one, else what to say and where to buy it. */
function gate(user, now = Date.now()) {
  if (!enabled() || !user || credits(user.id) > 0) return null;
  return {
    say: 'Starting a Psyche Together needs it set up on the PsycheAI website first. Open this link, then come back and say "Start Psyche Together". Joining a partner\'s stays free.',
    url: BASE_URL + '/together/buy/' + tokenFor(user.id, now),
  };
}

/** A new couple was made: one purchase is used. */
function use(userId) {
  if (!enabled()) return;
  const row = store.kvGet(PAID, userId) || { credits: 0, sessions: [] };
  if (row.credits > 0) store.kvSet(PAID, userId, { ...row, credits: row.credits - 1 });
}

/** From a verified webhook: credit one Psyche Together for this Checkout session, once. */
function credit(userId, sessionId) {
  if (!userId || !sessionId || !store.getUser(userId)) return false;
  const row = store.kvGet(PAID, userId) || { credits: 0, sessions: [] };
  if ((row.sessions || []).includes(sessionId)) return false;
  store.kvSet(PAID, userId, { credits: (Number(row.credits) || 0) + 1, sessions: [...(row.sessions || []), sessionId].slice(-50) });
  return true;
}

function buyPage(user, token, note, done) {
  const set = credits(user.id) > 0;
  const body = [`<div class="hero"><p class="kicker">PsycheAI</p><h1>Psyche Together</h1><p>The two of you, read together.</p></div>`];
  if (note) body.push(`<p class="error">${esc(note)}</p>`);
  body.push(`<div class="box"><p style="margin:0">You and your partner each answer about twenty private questions in your own Muse. You both get one read of the two of you, from both your Psyches and your conversation together: how you care and connect, live together, share meaning, feel secure and work through disagreements, with next steps drawn from the evidence, four weeks of small things to do, and a check-in again every four weeks.</p></div>`);
  if (set || done) {
    body.push(`<div class="box"><p class="lab">${set ? 'You\'re set' : 'Thank you'}</p><p style="margin:0">${set ? 'Go back to your PsycheAI chat in Muse and say <b>Start Psyche Together</b>.' : 'Your payment is being confirmed. In a minute, go back to your PsycheAI chat in Muse and say <b>Start Psyche Together</b>.'}</p></div>`);
  } else if (enabled()) {
    body.push(`<div class="actions"><form method="post" action="/together/buy/${esc(token)}/checkout"><button>${SHOWN() ? 'Get Psyche Together · ' + esc(SHOWN()) : 'Get Psyche Together'}</button></form>` +
      `<p class="note">One payment, through Stripe. It's for you and your partner: joining is free for them.</p></div>`);
  } else body.push(`<p class="note">Psyche Together needs nothing here right now: say Start Psyche Together in Muse.</p>`);
  body.push(`<p class="note">Signed in as ${esc(String(store.emailOf(user.id) || '').replace(/^(.)[^@]*(@.*)$/, '$1•••$2'))}.</p>`);
  return page('Psyche Together', body.join(''));
}

/** GET /together/buy/<token> */
function show(token, now = Date.now(), done = false) {
  const user = userFor(token, now);
  if (!user) return { status: 404, html: page('Link expired', '<h1>This link has expired</h1><p>Say Start Psyche Together in Muse for a new one.</p>') };
  return { status: 200, html: buyPage(user, token, '', done) };
}

/** POST /together/buy/<token>/checkout */
async function checkout(token, now = Date.now(), stripe = require('./plus').stripeCall) {
  const user = userFor(token, now);
  if (!user) return show(token, now);
  if (!enabled()) return { status: 503, html: buyPage(user, token, 'Psyche Together can\'t be bought here right now.') };
  if (credits(user.id) > 0) return { status: 303, location: BASE_URL + '/together/buy/' + token };
  const back = BASE_URL + '/together/buy/' + tokenFor(user.id, now);
  try {
    const session = await stripe('/v1/checkout/sessions', {
      mode: 'payment',
      line_items: [{ price: PRICE(), quantity: 1 }],
      client_reference_id: user.id,
      metadata: { kind: 'together', userId: user.id },
      payment_intent_data: { metadata: { kind: 'together', userId: user.id } },
      customer_email: store.emailOf(user.id) || undefined,
      allow_promotion_codes: 'true',
      success_url: back + '?done=1',
      cancel_url: back,
    });
    return { status: 303, location: session.url };
  } catch (err) {
    return { status: 502, html: buyPage(user, token, 'Stripe could not be reached. Try again in a minute.') };
  }
}

/** For lib/plus.js's webhook, once the signature has been checked: a paid Together session is credited. */
function fromWebhook(event) {
  const obj = (event.data && event.data.object) || {};
  if (!/^checkout\.session\.(completed|async_payment_succeeded)$/.test(event.type)) return false;
  if (!obj.metadata || obj.metadata.kind !== 'together') return false;
  if (obj.payment_status !== 'paid') return true;          // ours, not paid yet: async_payment_succeeded credits it
  credit(obj.client_reference_id || obj.metadata.userId, obj.id);
  return true;
}

/** For delete_my_data. */
function forget(userId) {
  store.kvDel(PAID, userId);
}

module.exports = { enabled, gate, use, credit, credits, tokenFor, userFor, show, checkout, fromWebhook, forget };
