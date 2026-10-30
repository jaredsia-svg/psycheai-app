// Psyche Pair Plus, bought on the website (PLAN.md "Money"): US$4.99 a month
// or US$29 a year for 5 picks a week, a drop of 8 and 5 custom must-haves.
//
//   GET  /plus                    sign in (email code, Google or Apple), the
//                                 same accounts as the hosts (lib/oauth.js)
//   GET  /plus/<token>            your plan, and the buttons
//   POST /plus/<token>/month|year off to Stripe Checkout
//   POST /plus/<token>/manage     Stripe's billing portal (cancel, card)
//   POST /stripe/webhook          Stripe tells us; the only place a plan changes
//
// The token is a signed link (lib/links.js) for one account that lasts an
// hour: no cookies, as with the card pages. Stripe is called over its REST
// API with fetch, so there's no SDK. The price ids come from the
// environment, so prices are changed in Stripe, not here. A plan changes only
// on a webhook whose signature checks out, never on the return from Checkout.

const crypto = require('node:crypto');
const store = require('./store');
const links = require('./links');
const plans = require('./plans');
const { page, esc } = require('./theme');
const { BASE_URL } = require('./config');

const API = () => (process.env.STRIPE_API_URL || 'https://api.stripe.com').replace(/\/$/, '');
const KEY = () => process.env.STRIPE_SECRET_KEY || '';
const WEBHOOK_SECRET = () => process.env.STRIPE_WEBHOOK_SECRET || '';
const PRICES = () => ({ month: process.env.STRIPE_PRICE_MONTHLY || '', year: process.env.STRIPE_PRICE_YEARLY || '' });
const SHOWN = { month: 'US$4.99 a month', year: 'US$29 a year' };
const LINK_MS = 60 * 60000;
const TOLERANCE_S = 300;

const enabled = () => Boolean(KEY() && WEBHOOK_SECRET() && PRICES().month && PRICES().year);

/** Stripe's form encoding, nested keys included (a[b][0][c]=…). */
function form(obj, prefix = '', out = new URLSearchParams()) {
  for (const [k, v] of Object.entries(obj)) {
    if (v === undefined || v === null) continue;
    const key = prefix ? `${prefix}[${k}]` : k;
    if (typeof v === 'object') form(v, key, out);
    else out.append(key, String(v));
  }
  return out;
}

async function stripe(path, body, method = 'POST') {
  const res = await fetch(API() + path, {
    method,
    headers: { Authorization: 'Bearer ' + KEY(), 'Content-Type': 'application/x-www-form-urlencoded' },
    body: form(body).toString(),
    signal: AbortSignal.timeout(15000),
  });
  const json = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error((json.error && json.error.message) || 'Stripe error'), { status: 502 });
  return json;
}

const tokenFor = (userId, now = Date.now()) => links.sign({ v: userId, k: 'plus' }, now, LINK_MS);

/** The account a /plus/<token> link is for, or null. */
function userFor(token, now = Date.now()) {
  const p = links.verify(token, now);
  return p && p.k === 'plus' ? store.getUser(p.v) : null;
}

const masked = email => String(email || '').replace(/^(.)[^@]*(@.*)$/, '$1•••$2');

function accountPage(user, token, note) {
  const plus = plans.isPlus(user);
  const L = plus ? plans.PLUS : plans.FREE;
  const body = [`<div class="hero"><p class="kicker">Psyche Pair</p><h1>${plus ? 'You have Plus' : 'Psyche Pair Plus'}</h1>` +
    `<p>${plus ? 'Thank you. Your extra picks are on.' : 'More of the people who fit you.'}</p></div>`];
  if (note) body.push(`<p class="error">${esc(note)}</p>`);
  body.push(`<div class="box"><p class="lab">Your plan</p><p style="margin:0"><b>${plus ? 'Plus' : 'Free'}</b>: ${L.picks} picks a week, a drop of up to ${L.drop}, ` +
    `${L.customMustHaves} custom must-have${L.customMustHaves === 1 ? '' : 's'}.</p>` +
    (plus && user.plus.until ? `<p class="muted" style="margin:6px 0 0">${user.plus.cancelAt ? 'Ends' : 'Renews'} ${new Date(user.plus.until).toISOString().slice(0, 10)}</p>` : '') + `</div>`);
  if (!plus) {
    body.push(`<div class="box"><p class="lab">Plus</p><ol class="num light"><li><b>1</b>5 picks a week instead of 2</li><li><b>2</b>A drop of up to 8 instead of 5</li><li><b>3</b>5 custom must-haves instead of 1</li></ol>` +
      `<p class="muted" style="margin:10px 0 0">Matches still have to clear the same bar: Plus shows you more of the people who fit, never people who don't.</p></div>`);
    if (enabled()) {
      body.push(`<div class="actions"><form method="post" action="/plus/${esc(token)}/year"><button>${SHOWN.year}</button></form>` +
        `<form method="post" action="/plus/${esc(token)}/month"><button class="ghost">${SHOWN.month}</button></form>` +
        `<p class="note">Cancel any time. Paid through Stripe.</p></div>`);
    } else body.push(`<p class="note">Plus isn't open yet.</p>`);
  } else if (user.plus.customer && enabled()) {
    body.push(`<div class="actions"><form method="post" action="/plus/${esc(token)}/manage"><button class="ghost">Manage or cancel</button></form></div>`);
  }
  body.push(`<p class="note">Signed in as ${esc(masked(store.emailOf(user.id)))}. Free stays free: the read, Sync, 2 picks a week, chat and the Instagram swap.</p>`);
  return page('Psyche Pair Plus', body.join(''));
}

/** GET /plus/<token> */
function show(token, now = Date.now()) {
  const user = userFor(token, now);
  if (!user) return { status: 404, html: page('Link expired', '<h1>This link has expired</h1><p><a href="/plus">Sign in again</a>.</p>') };
  return { status: 200, html: accountPage(user, token) };
}

/** POST /plus/<token>/<action> */
async function act(token, action, now = Date.now()) {
  const user = userFor(token, now);
  if (!user) return show(token, now);
  if (!enabled()) return { status: 503, html: accountPage(user, token, 'Plus isn\'t open yet.') };
  const back = BASE_URL + '/plus/' + tokenFor(user.id, now);
  try {
    if (action === 'month' || action === 'year') {
      if (plans.isPlus(user, now)) return { status: 303, location: back };
      const session = await stripe('/v1/checkout/sessions', {
        mode: 'subscription',
        line_items: [{ price: PRICES()[action], quantity: 1 }],
        client_reference_id: user.id,
        subscription_data: { metadata: { userId: user.id } },
        ...(user.plus && user.plus.customer ? { customer: user.plus.customer } : { customer_email: store.emailOf(user.id) }),
        allow_promotion_codes: 'true',
        success_url: back + '?done=1',
        cancel_url: back,
      });
      return { status: 303, location: session.url };
    }
    if (action === 'manage' && user.plus && user.plus.customer) {
      const portal = await stripe('/v1/billing_portal/sessions', { customer: user.plus.customer, return_url: back });
      return { status: 303, location: portal.url };
    }
  } catch (err) {
    return { status: 502, html: accountPage(user, token, 'Stripe could not be reached. Try again in a minute.') };
  }
  return { status: 400, html: accountPage(user, token) };
}

/**
 * Stop billing before an account is deleted: cancel a live subscription now.
 * Resolves to { ok } or { error }, and nothing should be deleted on an error.
 */
async function cancelFor(user) {
  const p = user && user.plus;
  if (!p || !p.subscription || p.status === 'canceled') return { ok: true };
  if (!KEY()) return { error: 'Your Psyche Pair Plus subscription could not be cancelled right now. Try again later.' };
  try {
    await stripe('/v1/subscriptions/' + encodeURIComponent(p.subscription), {}, 'DELETE');
    return { ok: true };
  } catch {
    return { error: 'Your Psyche Pair Plus subscription could not be cancelled right now, so nothing was deleted. Try again in a minute.' };
  }
}

/** Stripe-Signature: t=<seconds>,v1=<hex HMAC of "t.body">. Within five minutes. */
function verifySignature(raw, header, now = Date.now()) {
  if (!WEBHOOK_SECRET() || !header) return false;
  const parts = String(header).split(',').map(p => p.split('='));
  const t = (parts.find(([k]) => k === 't') || [])[1];
  const sigs = parts.filter(([k]) => k === 'v1').map(([, v]) => v);
  if (!t || !sigs.length || Math.abs(now / 1000 - Number(t)) > TOLERANCE_S) return false;
  const want = crypto.createHmac('sha256', WEBHOOK_SECRET()).update(t + '.' + raw).digest('hex');
  return sigs.some(s => s.length === want.length && crypto.timingSafeEqual(Buffer.from(s), Buffer.from(want)));
}

// current_period_end moved onto the subscription item in newer API versions.
const periodEnd = sub => sub.current_period_end || (sub.items && sub.items.data && sub.items.data[0] && sub.items.data[0].current_period_end) || null;

/** POST /stripe/webhook. Resolves to { status, body }. */
function webhook(raw, header, now = Date.now()) {
  if (!verifySignature(raw, header, now)) return { status: 400, body: { error: 'bad signature' } };
  let event;
  try { event = JSON.parse(raw); } catch { return { status: 400, body: { error: 'bad json' } }; }
  const obj = (event.data && event.data.object) || {};
  if (event.type === 'checkout.session.completed') {
    const user = store.getUser(obj.client_reference_id || '');
    if (user && obj.customer) store.updateUser(user.id, { plus: { ...(user.plus || {}), customer: obj.customer, subscription: obj.subscription || null } });
  } else if (/^customer\.subscription\.(created|updated|deleted)$/.test(event.type)) {
    const user = store.getUser((obj.metadata && obj.metadata.userId) || '');
    if (user) {
      const ended = event.type.endsWith('deleted');
      const end = periodEnd(obj);
      store.updateUser(user.id, {
        plus: {
          customer: obj.customer, subscription: obj.id,
          status: ended ? 'canceled' : obj.status,
          until: ended ? (obj.ended_at || Math.floor(now / 1000)) * 1000 : end ? end * 1000 : null,
          cancelAt: Boolean(obj.cancel_at_period_end),
        },
      });
    }
  }
  return { status: 200, body: { received: true } };
}

module.exports = { SHOWN, enabled, tokenFor, userFor, show, act, webhook, verifySignature, cancelFor, form };
