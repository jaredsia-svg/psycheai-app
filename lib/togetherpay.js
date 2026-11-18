// Psyche Together, bought on the website (README "Psyche Together, paid on the website"). Nothing is sold inside
// the host (CLAUDE.md): when payment is on, starting one without a purchase answers with a link here, worded as a
// limit, and the purchase happens on this page through Stripe Checkout.
//
//   GET  /together/buy/<token>            what it is, and the button (or "you're set")
//   POST /together/buy/<token>/checkout   off to Stripe Checkout, one payment
//   POST /stripe/webhook                  (lib/plus.js passes Together's sessions here) the only place a purchase lands
//
// One purchase is one Psyche Together, started by the one who bought it: joining stays free, and so do writing the
// read again and the four-week check-ins; and if the partner never joins, the link goes after 30 days and the
// purchase is refunded (PLAN.md). The token is a signed link for one account that lasts an hour, as Plus's
// is. A purchase is credited only from a webhook whose signature checks out, never from the return from Checkout,
// and each Checkout session is credited once.

const store = require('./store');
const links = require('./links');
const { page, esc } = require('./theme');
const { BASE_URL } = require('./config');

const PAID = 'togetherpaid';         // userId → { credits, sessions: [Checkout session ids credited] }
const LINK_MS = 60 * 60000;

// US$5, and rounded local prices in the same markets as psycheai.io's US$5 report (psycheai docs/prices.js, `unlock`).
// Amounts in each currency's minor unit, as Stripe takes them; JPY has none. Everywhere else pays in USD.
const PRICES = {
  usd: { shown: 'US$5', amount: 500 }, sgd: { shown: 'S$7', amount: 700 }, gbp: { shown: '£4', amount: 400 },
  eur: { shown: '€5', amount: 500 }, aud: { shown: 'A$8', amount: 800 }, cad: { shown: 'C$7', amount: 700 },
  nzd: { shown: 'NZ$9', amount: 900 }, hkd: { shown: 'HK$39', amount: 3900 }, jpy: { shown: '¥800', amount: 800 },
  chf: { shown: 'CHF 5', amount: 500 }, myr: { shown: 'RM22', amount: 2200 },
};
const EUROZONE = ['AT', 'BE', 'CY', 'DE', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PT', 'SI', 'SK'];
const COUNTRY_CURRENCY = Object.assign({ US: 'usd', SG: 'sgd', GB: 'gbp', AU: 'aud', CA: 'cad', NZ: 'nzd', HK: 'hkd', JP: 'jpy', CH: 'chf', LI: 'chf', MY: 'myr' },
  Object.fromEntries(EUROZONE.map(c => [c, 'eur'])));

/** The currency to charge in: one asked for by the page (?cur=), else from the country Cloudflare saw, else the
 *  region of the browser's language, else USD. A guess, and an honest one: the prices are rounded equivalents. */
function currencyFor(asked, country, language) {
  if (PRICES[String(asked || '').toLowerCase()]) return String(asked).toLowerCase();
  const c = String(country || '').toUpperCase();
  if (COUNTRY_CURRENCY[c]) return COUNTRY_CURRENCY[c];
  const region = (String(language || '').split(',')[0].split('-')[1] || '').toUpperCase();
  return COUNTRY_CURRENCY[region] || 'usd';
}

/** Payment is on only when asked for and fully set up: otherwise everyone may start one, as before. */
const enabled = () => process.env.PSYCHE_TOGETHER_PAID === '1' && Boolean(process.env.STRIPE_SECRET_KEY && process.env.STRIPE_WEBHOOK_SECRET);

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
    say: 'Starting a Psyche Together needs it set up on the PsycheAI website first. Open this link, then come back and tap the button. Joining a partner\'s stays free.',
    url: BASE_URL + '/together/buy/' + tokenFor(user.id, now),
  };
}

/** A new couple was made: one purchase is used. Returns { session, pi } for the couple to keep, so it can be refunded
 *  if the partner never joins, or null. */
function use(userId) {
  if (!enabled()) return null;
  const row = store.kvGet(PAID, userId) || { credits: 0, sessions: [] };
  if (!(row.credits > 0)) return null;
  const unused = [...(row.unused || [])];
  const paid = unused.shift() || null;
  store.kvSet(PAID, userId, { ...row, credits: row.credits - 1, unused });
  return paid;
}

/** The partner never joined (lib/together.js sweep): the purchase is refunded through Stripe. Resolves true once done. */
async function refund(paid, stripe = require('./plus').stripeCall) {
  if (!paid || !paid.pi) return true;            // nothing to refund (free, or paid before refunds were kept)
  if (!process.env.STRIPE_SECRET_KEY) return false;
  try {
    await stripe('/v1/refunds', { payment_intent: paid.pi, metadata: { kind: 'together', reason: 'partner never joined' } });
    return true;
  } catch (err) {
    return false;
  }
}

/** From a verified webhook: credit one Psyche Together for this Checkout session, once. */
function credit(userId, sessionId, pi) {
  if (!userId || !sessionId || !store.getUser(userId)) return false;
  const row = store.kvGet(PAID, userId) || { credits: 0, sessions: [] };
  if ((row.sessions || []).includes(sessionId)) return false;
  store.kvSet(PAID, userId, { credits: (Number(row.credits) || 0) + 1, sessions: [...(row.sessions || []), sessionId].slice(-50),
                              unused: [...(row.unused || []), { session: sessionId, pi: pi || null }] });
  return true;
}

// The buy page (README "The Psyche Together page"): what it is in a few plain lines, the sample to scroll, the price for
// both of them, and one button that stays in reach. The price is shown here only, never in Muse.
const CHAPTERS = [
  ['#c2366d', 'Care and connection', 'How you each feel loved, and how to show it.'],
  ['#2d5fa8', 'Living together', 'What feels fair at home, and what doesn’t.'],
  ['#6a4bb5', 'Shared meaning', 'Your values and big decisions, side by side.'],
  ['#2f7d6b', 'Feeling secure', 'How sure you both are, and what helps.'],
  ['#c2571a', 'Conflict and repair', 'The loop behind your rows, and how to break it.'],
];
const BUY_CSS = `
.tg{background:linear-gradient(140deg,#5b2a86,#7b3fa0 45%,#c2366d);color:#fff;border-radius:26px;padding:26px 20px 22px;text-align:center;position:relative;overflow:hidden}
.tg .pair{display:flex;justify-content:center;align-items:center;margin:2px 0 14px}
.tg .pc{width:74px;height:98px;border-radius:12px;background:rgba(255,255,255,.16);border:2px solid rgba(255,255,255,.55);display:grid;place-items:center;font:700 .85rem var(--font);letter-spacing:.02em}
.tg .pc.l{transform:rotate(-8deg)}.tg .pc.r{transform:rotate(8deg)}
.tg .hz{width:38px;height:38px;border-radius:50%;background:#fff;display:grid;place-items:center;margin:0 -8px;z-index:1;box-shadow:0 4px 14px rgba(0,0,0,.18)}
.tg .hz svg{width:20px;height:20px}
.tg h1{color:#fff;font-size:2rem}.tg p{margin:.45rem 0 0;font-size:1.05rem;opacity:.95}
.sample{margin:14px 0 0}
h2{font-size:1.15rem;margin:26px 0 10px;letter-spacing:-.01em}
.ch{list-style:none;padding:0;margin:0}
.ch li{display:flex;gap:12px;align-items:flex-start;background:var(--alt);border:1px solid var(--line);border-radius:16px;padding:11px 14px;margin:8px 0}
.ch i{flex:0 0 10px;height:10px;border-radius:50%;margin-top:7px}
.ch b{display:block}.ch span{color:var(--soft);font-size:.95rem}
.steps{list-style:none;padding:0;margin:0;counter-reset:s}
.steps li{position:relative;padding:0 0 14px 40px}
.steps li:before{counter-increment:s;content:counter(s);position:absolute;left:0;top:0;width:28px;height:28px;border-radius:50%;background:var(--accent);color:#fff;display:grid;place-items:center;font-weight:700;font-size:.85rem}
.steps b{display:block}.steps span{color:var(--soft);font-size:.95rem}
.priv p{margin:.3rem 0}
.price{text-align:center;background:var(--alt);border:1px solid var(--line);border-radius:20px;padding:18px 16px;margin:22px 0 0}
.price .big{font-size:2.2rem;font-weight:800;letter-spacing:-.02em;margin:0}
.price .muted{margin:.2rem 0 0}
details{background:var(--alt);border:1px solid var(--line);border-radius:14px;padding:10px 14px;margin:8px 0}
summary{font-weight:600;cursor:pointer}details p{margin:.4rem 0 0;color:var(--soft)}
.dock{position:sticky;bottom:0;padding:12px 0 10px;background:linear-gradient(transparent,var(--bg) 30%);margin-top:18px}
.dock button{box-shadow:0 8px 22px rgba(123,63,160,.28)}
.dock .note{margin-top:6px}
.done{text-align:center}.done .tick{width:56px;height:56px;border-radius:50%;background:#2f7d5b;color:#fff;display:grid;place-items:center;font-size:1.7rem;margin:6px auto 10px}`;
const HEART = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#c2366d" d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 5 6.4 5c2 0 3.6 1.1 4.6 2.6l1 1.4 1-1.4C14 6.1 15.6 5 17.6 5 21 5 23.1 8.4 21.6 11.8 19.5 16.4 12 21 12 21z"/></svg>';

function buyPage(user, token, note, done, cur = 'usd') {
  const set = credits(user.id) > 0;
  const price = PRICES[cur] || PRICES.usd;
  const hero = `<div class="tg"><div class="pair"><div class="pc l">You</div><div class="hz">${HEART}</div><div class="pc r">Partner</div></div>` +
    `<h1>Psyche Together</h1><p>See how the two of you really work, and what to try next.</p></div>`;
  const body = [`<style>${BUY_CSS}</style>`, hero];
  if (note) body.push(`<p class="error">${esc(note)}</p>`);
  if (set || done) {
    body.push(`<div class="box done"><div class="tick">✓</div><h2 style="margin:0 0 6px">${set ? 'You’re all set' : 'Thank you!'}</h2>` +
      `<p style="margin:0">${set ? '' : 'Your payment is going through. '}Go back to Muse and tap <b>I’ve paid, start it</b>. There’s nothing to copy or paste.</p></div>`);
    return page('Psyche Together', body.join(''));
  }
  body.push(`<a class="btn ghost sample" href="/together/sample" target="_blank" rel="noopener">See a sample report →</a>`);
  body.push('<h2>What you get</h2><ul class="ch">' + CHAPTERS.map(([c, t, d]) => `<li><i style="background:${c}"></i><div><b>${esc(t)}</b><span>${esc(d)}</span></div></li>`).join('') +
    '<li><i style="background:#2f7d5b"></i><div><b>A 28-day plan</b><span>Small things to do together, one a day.</span></div></li></ul>');
  body.push('<h2>How it works</h2><ol class="steps">' +
    '<li><b>You start it in Muse</b><span>Your partner joins for free.</span></li>' +
    '<li><b>You each answer 8 quick screens</b><span>About 2 minutes, in your own Muse.</span></li>' +
    '<li><b>You both get the report</b><span>Built from both your Psyches and your chat together. Check in again every 4 weeks.</span></li></ol>');
  body.push('<div class="box priv"><p class="lab">Private</p><p>Your answers stay private. Only a few, like your big decisions, are shown side by side.</p>' +
    '<p>PsycheAI can’t read your answers or your report.</p></div>');
  body.push(`<div class="price"><p class="big">${esc(price.shown)}</p><p class="muted">One payment, for both of you. No subscription.</p>` +
    '<p class="muted">If your partner doesn’t join within 30 days, you get your money back automatically.</p></div>');
  body.push('<h2>Questions</h2>' +
    '<details><summary>Does my partner need to pay?</summary><p>No. One payment covers you both.</p></details>' +
    '<details><summary>What do we need first?</summary><p>You each need your own Psyche from PsycheAI in Muse. It’s free.</p></details>' +
    '<details><summary>What happens after I pay?</summary><p>Go back to Muse and tap <b>I’ve paid, start it</b>. Nothing to copy or paste.</p></details>');
  if (enabled()) {
    body.push(`<div class="dock"><form method="post" action="/together/buy/${esc(token)}/checkout?cur=${esc(cur)}"><button>Get Psyche Together · ${esc(price.shown)}</button></form>` +
      '<p class="note">Secure payment by Stripe.</p></div>');
  } else body.push('<p class="note">Psyche Together needs nothing here right now: say Start Psyche Together in Muse.</p>');
  return page('Psyche Together', body.join(''));
}

/** GET /together/buy/<token> */
function show(token, now = Date.now(), done = false, where = {}) {
  const user = userFor(token, now);
  if (!user) return { status: 404, html: page('Link expired', '<h1>This link has expired</h1><p>Say Start Psyche Together in Muse for a new one.</p>') };
  return { status: 200, html: buyPage(user, token, '', done, currencyFor(where.cur, where.country, where.language)) };
}

/** POST /together/buy/<token>/checkout */
async function checkout(token, now = Date.now(), stripe = require('./plus').stripeCall, where = {}) {
  const user = userFor(token, now);
  if (!user) return show(token, now);
  const cur = currencyFor(where.cur, where.country, where.language);
  if (!enabled()) return { status: 503, html: buyPage(user, token, 'Psyche Together can\'t be bought here right now.', false, cur) };
  if (credits(user.id) > 0) return { status: 303, location: BASE_URL + '/together/buy/' + token };
  const back = BASE_URL + '/together/buy/' + tokenFor(user.id, now);
  try {
    const session = await stripe('/v1/checkout/sessions', {
      mode: 'payment',
      // The amount comes from PRICES only, never from the page: the page can pick a currency, not a price.
      line_items: [{ quantity: 1, price_data: { currency: cur, unit_amount: PRICES[cur].amount, product_data: { name: 'Psyche Together', description: 'One Psyche Together for you and your partner' } } }],
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
    return { status: 502, html: buyPage(user, token, 'Stripe could not be reached. Try again in a minute.', false, cur) };
  }
}

/** For lib/plus.js's webhook, once the signature has been checked: a paid Together session is credited. */
function fromWebhook(event) {
  const obj = (event.data && event.data.object) || {};
  if (!/^checkout\.session\.(completed|async_payment_succeeded)$/.test(event.type)) return false;
  if (!obj.metadata || obj.metadata.kind !== 'together') return false;
  if (obj.payment_status !== 'paid') return true;          // ours, not paid yet: async_payment_succeeded credits it
  credit(obj.client_reference_id || obj.metadata.userId, obj.id, typeof obj.payment_intent === 'string' ? obj.payment_intent : null);
  return true;
}

/** For delete_my_data. */
function forget(userId) {
  store.kvDel(PAID, userId);
}

module.exports = { PRICES, currencyFor, enabled, gate, use, refund, credit, credits, tokenFor, userFor, show, checkout, fromWebhook, forget };
